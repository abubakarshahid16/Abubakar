"""The AI reviewer as a job of the existing review worker (#1690): stage `agent_review`.

Same queue, same single worker thread, same run row as the classic review (`review_runs` + `jobs`), so the run list, progress,
cancel and the access scope work as today. This module never changes the classic path: it claims only its own stage, and only
when the one switch is on (`agent_review_gate.enabled`); with the switch off nothing is claimed, created or sent.

JOB ORDER
  1. read the paper (`nothing_read.read_phase`, as the classic review does);
  2. the paper's KIND first (`agent_review_kind`); unknown stays unknown: no rule is asked and the run says so;
  3. the standards: a finished classic run of the same code version is reused, else the classic selection runs inline;
  4. the RIGHT rules only (`agent_review_items.build_items`, rule labels on): kind must equal the paper's, tier usable;
     everything else is counted with one reason and stored as "left out";
  5. batches by page through the Claude lane, code verifies quotes and numbers (`agent_review_run.Runner`);
  6. lines, rules and missing rule books are written to the tables as they are decided (a restart resumes: a stored line is
     kept and never asked, or paid for, again);
  7. CRS internal and contractor copies (xlsx) are written under `<data dir>/agent_reviews/<run id>/`, with the trace file.

Money goes ONLY through `claude_spend` (USD 5 per step, USD 15 per run); a cap stops the run with a PARTIAL result and a stop
reason. No paper or rule-book text is logged.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from . import agent_review_crs as crs_lines
from . import (
    agent_review_gate,
    agent_review_kind,
    agent_review_schema,
    claude_approved,
    claude_auto_approve,
    job_queue,
    nothing_read,
    review_jobs,
)
from . import agent_review_items as items_mod
from . import agent_review_rules as rules
from . import agent_review_run as runner_mod
from . import agent_review_wording as wording
from .config import config_version, settings
from .db import connect

log = logging.getLogger(__name__)

STAGE = agent_review_gate.STAGE
STEPS = (
    "reading the paper",
    "choosing the paper kind and the rules",
    "asking the AI reviewer",
    "writing the CRS and the record",
)
ACTIVE_RUN = review_jobs.ACTIVE_RUN

#: Words of the contract (`api/agent_review_schemas.py`).
WORD_OF_LABEL = {"Query for the engineer": "Query"}
NOT_APPLICABLE = "Not applicable"
TIER_WORDS = {rules.TIER_AI: "AI approved", rules.TIER_ENGINEER: "Engineer", rules.TIER_OWNER: "Owner",
              rules.TIER_NOT_APPROVED: "Not AI approved"}
LEFT_OUT_WORDS = {
    rules.ANOTHER_PAPER: "needs another paper",
    rules.NEEDS_HUMAN: "needs a human",
    rules.QUOTE_NOT_FOUND: "quote not found",
    rules.NOT_LABELLED: "not labelled yet",
}
#: A checklist item (a skill) has no rule-book rule; its tier is the approved checklist's.
CHECKLIST_TIER = "Engineer"


class _Cancelled(Exception):
    pass


def _now() -> str:
    return job_queue.now_iso()


# ---------------------------------------------------------------- enqueue, claim, recover


def enqueue(submittal_document_id: str, *, allowed_document_ids: frozenset[str],
            requested_by: str | None) -> tuple[str, str]:
    """Create the run and its job together. Returns (run_id, job_id).

    Raises ReviewAlreadyActive when ANY review (classic or AI) of this submittal is queued or running, and ValueError when
    the caller may not read the submittal. Off: raises FeatureOff and creates nothing."""
    agent_review_gate.require_on()
    from . import submittal_review

    submittal_review.ensure_schema()
    agent_review_schema.ensure_schema()
    if submittal_document_id not in allowed_document_ids:
        raise ValueError("no submittal with that id")
    conn = connect()
    run_id, job_id, now = str(uuid.uuid4()), f"job_{uuid.uuid4().hex[:12]}", _now()
    with job_queue.immediate(conn):
        active = conn.execute(
            f"SELECT id FROM review_runs WHERE submittal_document_id = ?"
            f" AND status IN ({','.join('?' * len(ACTIVE_RUN))}) LIMIT 1",
            (submittal_document_id, *ACTIVE_RUN)).fetchone()
        if active is not None:
            raise review_jobs.ReviewAlreadyActive(active["id"])
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, started_by,"
            " started_at, created_at, updated_at) VALUES (?,?,'queued',?,?,?,?)",
            (run_id, submittal_document_id, requested_by, now, now, now))
        conn.execute(
            """INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at,
                                 priority, created_by, code_version, config_version,
                                 review_run_id, progress_done, progress_total, progress_label)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?, 'queued')""",
            (job_id, submittal_document_id, STAGE, now, now, job_queue.PRIORITY_INTERACTIVE,
             requested_by, review_jobs.review_code_version(), config_version(), run_id, len(STEPS)))
        job_queue.audit(conn, "job.queued", job_id, actor_user_id=requested_by,
                        detail=f"stage={STAGE} run={run_id}")
    claude_auto_approve.on_review_start(run_id)  # #1584: the subject joins the approved list, unless blocked
    return run_id, job_id


def claim_next(worker_id: str) -> str | None:
    """Claim the next AI review job (one conditional UPDATE). None when the switch is off or nothing is queued."""
    if not agent_review_gate.enabled():
        return None
    now = _now()
    conn = connect()
    with conn:
        row = conn.execute(
            f"""UPDATE jobs SET state = 'running', claimed_by = :me, claimed_at = :now, updated_at = :now
                WHERE id = (SELECT id FROM jobs WHERE stage = :stage AND {review_jobs._CLAIMABLE}
                            ORDER BY priority DESC, started_at LIMIT 1)
                  AND {review_jobs._CLAIMABLE} AND {job_queue.under_limit_sql()}
                RETURNING id, review_run_id""",
            {"me": worker_id, "now": now, "stage": STAGE, "stale": job_queue.stale_cutoff(),
             "limit": settings.job_max_running}).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE review_runs SET status = 'running', updated_at = ? WHERE id = ?",
                     (now, row["review_run_id"]))
    return row["id"]


def recover_stale(*, at_startup: bool = False) -> int:
    """A job left `running` by a dead process goes back to the queue with its run; the run resumes from its stored lines.
    Nothing is recovered, and no table is read, with the switch off."""
    if not agent_review_gate.enabled():
        return 0
    from . import review_recovery

    return review_recovery.recover(STAGE, at_startup=at_startup)


# ---------------------------------------------------------------- the job


def _progress(conn, job_id: str, done: int, heartbeat=None) -> None:
    """Record progress and honour a cancellation - between steps, never inside one."""
    if heartbeat is not None:
        heartbeat()
    with conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row and row["cancel_requested"]:
            raise _Cancelled()
        conn.execute("UPDATE jobs SET progress_done = ?, progress_label = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
                     (done, STEPS[min(done, len(STEPS) - 1)], _now(), _now(), job_id))


def run_dir(run_id: str) -> Path:
    return Path(settings.data_dir) / "agent_reviews" / run_id


def _scope_run_id(conn, submittal: str, run_id: str, scope: frozenset[str], heartbeat) -> str:
    """The run whose stored scope decisions name the rules to ask: this run's own (a resumed run), else a finished classic
    run of the SAME review code version, else the classic selection runs inline under this run's id."""
    from . import applicability, submittal_fill

    own = conn.execute("SELECT 1 FROM review_scope_decisions WHERE review_run_id = ? LIMIT 1", (run_id,)).fetchone()
    if own:
        return run_id
    reuse = conn.execute(
        "SELECT r.id FROM review_runs r JOIN jobs j ON j.review_run_id = r.id"
        " WHERE r.submittal_document_id = ? AND r.status = 'completed' AND j.stage = ? AND j.code_version = ?"
        " AND EXISTS (SELECT 1 FROM review_scope_decisions s WHERE s.review_run_id = r.id)"
        " ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
        (submittal, review_jobs.STAGE, review_jobs.review_code_version())).fetchone()
    if reuse:
        return reuse["id"]
    submittal_fill.for_review(submittal)
    applicability.select(submittal, allowed_document_ids=scope, review_run_id=run_id, persist=True, heartbeat=heartbeat)
    return run_id


def _tier_word(item: dict) -> str:
    """The tier of a rule item or of a stored line (both carry `rule_tier`, `source` and `rule_label`)."""
    if item.get("rule_tier") == rules.RULE_TIER_NOT_APPROVED:
        return "Not AI approved"
    if item.get("source") != "rule":
        return CHECKLIST_TIER
    tier = (item.get("rule_label") or {}).get("tier")
    return TIER_WORDS.get(tier) or "Not AI approved"  # a tier we cannot name is never shown as approved


def contract_class_and_word(line: dict) -> tuple[str, str]:
    """The contract's class and word of one line (`api/agent_review_schemas.py`). "Pass" / "Fail" only for a line proven by code."""
    line = wording.apply(line)
    if crs_lines.is_not_applicable(line) and line["verdict_class"] == wording.CLASS_QUERY:
        return "Not applicable", NOT_APPLICABLE
    label = line["verdict_label"]
    return line["verdict_class"], WORD_OF_LABEL.get(label, label)


def store_line(run_id: str, line: dict, trace: dict) -> None:
    """One line into `agent_review_line` (an upsert: a resumed run replaces its own failed line)."""
    line = wording.apply(line)
    cls, word = contract_class_and_word(line)
    reason = str(line.get("not_proven_reason") or line.get("reasoning") or line.get("why") or "")
    page = line.get("paper_page") or None
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book,"
            " reason, rule_tier, line_json, trace_json, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, str(line["item_id"]), cls, word, page if isinstance(page, int) and page >= 1 else None,
             str(line.get("clause") or ""), str(line.get("standard") or ""), reason, _tier_word(line),
             json.dumps(line, ensure_ascii=False, default=str), json.dumps(trace, ensure_ascii=False, default=str),
             _now()))


def stored_lines(run_id: str) -> dict[str, dict]:
    """The lines already decided for this run (the resume set), by item id."""
    out: dict[str, dict] = {}
    for r in connect().execute("SELECT item_id, line_json FROM agent_review_line WHERE run_id = ?", (run_id,)):
        try:
            out[r["item_id"]] = json.loads(r["line_json"])
        except ValueError:
            continue
    return out


def _write_rules(run_id: str, doc: dict, cache: dict, equipment: str | None, kind: str) -> None:
    """Every rule of the run: asked, or left out with its one reason. Idempotent (a resumed run writes the same rows)."""
    block = doc.get("rule_labels") or {}
    rows = []
    for it in doc.get("items") or []:
        if it.get("source") != "rule":
            continue
        lab = it.get("rule_label") or {}
        ref = it.get("rule_quote_ref") or it.get("clause_quote_ref")
        entry = cache.get(ref) if isinstance(ref, str) else None
        quote = entry.get("text") if isinstance(entry, dict) else (entry if isinstance(entry, str) else None)
        rows.append((run_id, str(it.get("item_id")), 1, None, str(it.get("standard") or ""), str(it.get("clause") or ""),
                     quote, it.get("clause_page"), lab.get("paper_kind") or kind, lab.get("field"), equipment,
                     _tier_word(it)))
    for rec in block.get("left_out") or []:
        reason = LEFT_OUT_WORDS.get(rec.get("reason"))
        if reason is None:
            continue  # "paper kind unknown": said once on the run, not once per rule
        rows.append((run_id, str(rec.get("rule_version_id") or rec.get("item_id")), 0, reason,
                     str(rec.get("rule_book") or ""), str(rec.get("clause") or ""), None, rec.get("page"),
                     rec.get("needs_paper_kind"), None, None, None))
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_rule (run_id, rule_key, asked, left_out_reason, rule_book, clause, quote,"
            " quote_page, paper_kind, field, equipment, tier) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def _write_missing(run_id: str, missing: list[dict]) -> None:
    with connect() as conn:
        conn.executemany("INSERT OR REPLACE INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
                         [(run_id, str(m.get("rule_book")), str(m.get("why") or "")) for m in missing if m.get("rule_book")])


def lane() -> tuple:
    """(send, env) for the Claude calls: (None, None) in the app, the real lane. Tests replace this with a fake model."""
    return None, None


def _document_name(submittal: str) -> str:
    row = connect().execute("SELECT filename FROM documents WHERE id = ?", (submittal,)).fetchone()
    return (row["filename"] if row else None) or submittal


def _finish(run_id: str, submittal: str, kind: agent_review_kind.PaperReading, block: dict, runner,
            items: list[dict], started: str, scope_run: str | None) -> dict:
    """The run row, the CRS copies and the status of the run. Called also for a partial run (a cap, a refusal)."""
    lines = [runner.lines[str(i["item_id"])] for i in items if str(i["item_id"]) in runner.lines] if runner else []
    lines = [wording.apply(ln) for ln in lines]
    counts = runner_mod.counts_of(lines)
    models = sorted((runner.lead_models | runner.second_models) if runner else set())
    partial = bool(runner and runner.stopped)
    stop = None
    if runner and runner.stopped:
        stop = f"{runner.stopped}: {runner.stop_text}" if runner.stop_text and runner.stop_text != runner.stopped else runner.stopped
    elif not kind.known:
        stop = "paper_kind_unknown: no rule was asked; an engineer names the paper kind and the review runs again"
    usd = round(runner.run_usd, 6) if runner and (runner.calls["lead"] or runner.calls["second"]
                                                  or runner.calls["context"]) else None
    folder = run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"paper": _document_name(submittal), "run_id": run_id, "date": started[:10], "lead_models": sorted(
        runner.lead_models) if runner else [], "second_models": sorted(runner.second_models) if runner else [],
        "rule_labels": block or None, "order12_counts": {"rules_left_out": (block or {}).get("counts"),
                                                         "rule_books_not_held": len((block or {}).get("missing_rule_books") or [])}}
    crs_lines.write_internal(lines, folder / "crs-internal.xlsx", meta)
    crs_lines.write_contractor(lines, folder / "crs-contractor.xlsx", meta)
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, equipment_type,"
            " usd, models_json, stop_reason, counts_json, items_total, partial, rule_set_changed_by, started_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)",
            (run_id, submittal, kind.kind, kind.source, kind.equipment_type, usd, json.dumps(models), stop,
             json.dumps(counts, default=str), len(items), 1 if partial else 0, started, _now()))
    return {"counts": counts, "stop_reason": stop, "usd": usd, "partial": partial, "scope_run": scope_run}


@review_jobs._review_scope  # the bar on the local engine; ledger lines carry the run's id; spend in the run's record
def run(job_id: str, worker_id: str, heartbeat=None) -> str:
    """Run one claimed AI review job to its end. Returns the job's final state."""
    from . import errors

    conn = connect()
    job = conn.execute("SELECT * FROM jobs WHERE id = ? AND state = 'running' AND claimed_by = ?",
                       (job_id, worker_id)).fetchone()
    if job is None:
        return "not_claimed"
    if not agent_review_gate.enabled():  # the switch went off while the job waited: nothing is sent, the job goes back
        with conn:
            conn.execute("UPDATE jobs SET state = 'queued', claimed_by = NULL, claimed_at = NULL, updated_at = ? WHERE id = ?",
                         (_now(), job_id))
            conn.execute("UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
                         (_now(), job["review_run_id"]))
        return "queued"
    agent_review_schema.ensure_schema()
    run_id, submittal = job["review_run_id"], job["document_id"]
    scope = review_jobs._scope_of(job["created_by"])
    started = _now()
    try:
        if submittal not in scope:
            raise PermissionError("the requester can no longer read this submittal")
        _progress(conn, job_id, 0, heartbeat)
        nothing_read.read_phase(submittal, scope, run_id)
        _progress(conn, job_id, 1, heartbeat)
        kind = agent_review_kind.decide(submittal, scope)
        block: dict = {}
        items: list[dict] = []
        runner = None
        scope_run = None
        if kind.known:
            scope_run = _scope_run_id(conn, submittal, run_id, scope, heartbeat)
            claude_auto_approve.on_review_start(scope_run)  # a cited standard joins the list too (when auto-approve is on)
            cache: dict = {}
            doc = items_mod.build_items(settings.db_path, submittal, kind.item_kind, run_id=scope_run, cache=cache,
                                        rule_labels=True, equipment_type=kind.equipment_type)
            block, items = doc.get("rule_labels") or {}, list(doc.get("items") or [])
            _write_rules(run_id, doc, cache, kind.equipment_type, kind.kind)
        else:
            cache, doc = {}, {}
            block = {"on": True, "paper_kind": None, "paper_kind_known": False,
                     "summary_lines": ["paper kind unknown: no rule was asked of this paper; an engineer names the paper "
                                       "kind and the review runs again"],
                     "left_out": [], "counts": {}, "missing_rule_books": rules.missing_rule_books(conn, submittal)}
        _write_missing(run_id, block.get("missing_rule_books") or [])
        _progress(conn, job_id, 2, heartbeat)
        if items:
            runner = _make_runner(run_id, submittal, kind, items, cache)
            declared = {submittal} | {str(i["standard_document_id"]) for i in items if i.get("standard_document_id")}
            from . import claude_spend

            try:
                with claude_approved.carrying(sorted(declared)), claude_spend.for_run(run_id):
                    runner.run()
            except BaseException as exc:  # the lines decided so far are kept; the stop is said, then re-raised
                if not runner.stopped:
                    runner.stopped, runner.stop_text = runner_mod.stop_reason(exc, runner.last_app_worst)
                raise
            finally:
                result = _finish(run_id, submittal, kind, block, runner, items, started, scope_run)
        else:
            result = _finish(run_id, submittal, kind, block, None, items, started, scope_run)
        _progress(conn, job_id, 3, heartbeat)
    except nothing_read.StoredFileAbsent as exc:
        return nothing_read.fail_run(job_id, run_id, exc)
    except _Cancelled:
        with conn:
            conn.execute("UPDATE review_runs SET status = 'cancelled', outcome_json = ?, updated_at = ? WHERE id = ?",
                         (json.dumps({"error": "cancelled by an engineer before it finished"}), _now(), run_id))
            conn.execute("UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?", (job_queue.CANCELLED, _now(), job_id))
            job_queue.audit(conn, "job.cancelled", job_id, detail=f"run={run_id} while running")
        return job_queue.CANCELLED
    except Exception as exc:  # noqa: BLE001 - a failed review must not kill the worker
        safe = errors.record_failure(exc, document_id=submittal, stage=STAGE)
        with conn:
            state = job_queue.fail(conn, job_id, code=type(exc).__name__, message=safe["message"])
            if state == job_queue.POISONED:
                conn.execute("UPDATE review_runs SET status = 'failed', outcome_json = ?, updated_at = ? WHERE id = ?",
                             (json.dumps({"error": safe["message"], "agent_review": True,
                                          "partial": bool(stored_lines(run_id))}), _now(), run_id))
            else:
                conn.execute("UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?", (_now(), run_id))
        return state
    outcome = {"agent_review": True, "partial": result["partial"], "stop_reason": result["stop_reason"],
               "counts": {k: v for k, v in result["counts"].items() if isinstance(v, int)}}
    with conn:
        conn.execute("UPDATE review_runs SET status = 'completed', outcome_json = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(outcome), _now(), _now(), run_id))
        conn.execute("UPDATE jobs SET state = 'done', progress_done = ?, progress_label = 'done', error_code = NULL,"
                     " error_message = NULL, next_attempt_at = NULL, updated_at = ? WHERE id = ?",
                     (len(STEPS), _now(), job_id))
        job_queue.audit(conn, "job.done", job_id, detail=f"stage={STAGE} run={run_id}")
    return "done"


def _make_runner(run_id: str, submittal: str, kind: agent_review_kind.PaperReading, items: list[dict], cache: dict):
    """The runner for this run: kept lines from an earlier attempt are not asked again (no second charge)."""
    from . import agent_claude

    send, env = lane()
    pages = runner_mod.DbPages(connect(), submittal)
    folder = run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    done = {k: v for k, v in stored_lines(run_id).items() if not v.get("error")}
    return runner_mod.Runner(
        paper=submittal, items=items, pages=pages, clauses=runner_mod.ClauseCache(cache), model=agent_claude.LEAD_MODEL,
        send=send, env=env, done_lines=done, paper_kind=kind.kind, equipment_type=kind.equipment_type,
        std_pages=runner_mod.StdPages(), sink=lambda line, trace: store_line(run_id, line, trace),
        trace_path=folder / "trace.jsonl", retry_base=0.0 if send is not None else runner_mod.RETRY_BASE_SECONDS)
