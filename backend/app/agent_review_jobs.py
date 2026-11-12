"""The AI reviewer as a job of the existing review worker (#1690): stage `agent_review`.

Same queue, same single worker thread, same run row as the classic review (`review_runs` + `jobs`), so the run list, progress,
cancel and the access scope work as today. This module never changes the classic path: it claims only its own stage, and only
when the one switch is on (`agent_review_gate.enabled`); with the switch off nothing is claimed, created or sent.

JOB ORDER
  1. read the paper (`nothing_read.read_phase`, as the classic review does);
  2. the paper's KIND first (`agent_review_kind`); unknown stays unknown. A datasheet goes to the rule review below; a
     procedure or a contract (`agent_review_gate.AGENT_GENERAL_REVIEW_KINDS`) goes to the GENERAL review
     (`agent_general_job`: no rule book, no Pass or Fail, internal only); any other kind asks nothing: the run says so;
  3. the standards: a finished classic run of the same code version is reused, else the classic selection runs inline;
  4. the RIGHT rules only (`agent_review_items.build_items`): kind must equal the paper's, tier usable, equipment type fits;
     everything else is counted with one reason and stored as "left out";
  5. PREFLIGHT: the run is refused before any call when its inputs are inconsistent (`preflight`);
  6. batches by page through the Claude lane, code verifies quotes and numbers (`agent_review_run.Runner`);
  7. lines, rules and missing rule books are written to the tables as they are decided (a restart resumes: a stored line is
     kept and never asked, or paid for, again);
  8. CRS internal and contractor copies (xlsx) are written under `<data dir>/agent_reviews/<run id>/`, with the trace file.

Money goes ONLY through `claude_spend` (USD 5 per step, USD 15 per run); a cap stops the run with a PARTIAL result and a stop
reason. No paper or rule-book text is logged.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from . import (
    agent_general_job as general_job,
)
from . import agent_review_crs as crs_lines
from . import (
    agent_review_gate,
    agent_review_kind,
    agent_review_schema,
    agent_review_text,
    agent_review_verdict,
    claude_approved,
    claude_auto_approve,
    job_queue,
    nothing_read,
    review_jobs,
    rule_labels,
)
from . import agent_review_items as items_mod
from . import agent_review_pair as pair_mod
from . import agent_review_request as request_mod
from . import agent_review_reread as reread_mod
from . import agent_review_rules as rules
from . import agent_review_run as runner_mod
from . import crs_ai_header as crs_header
from .agent_review_pair import (  # noqa: F401 - re-exported
    IllegalLine,
    contract_class_and_word,
)
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
#: Rules that are not AI approved are NOT asked in the app (lead decision, 11 Nov 2026 night): "measured 11 Nov: no key row
#: gained, more wrong opinions". The cap and the class "AI opinion, rule not yet approved" stay in the code and tests.
ASK_UNAPPROVED = "off"

#: Words of the contract (`api/agent_review_schemas.py`).
#: The label table's tier words -> the contract's. A tier we cannot name is never shown as approved.
TIER_WORDS = {
    "owner": "Owner",
    "engineer": "Engineer",
    "AI approved": "AI approved",
    "not AI approved": "Not AI approved",
}
#: The core's reason -> the contract's left-out word (`rules.REASON_WORDS`); "paper kind unknown" is said once on the run.
LEFT_OUT_WORDS = {
    k: v for k, v in rules.REASON_WORDS.items() if k != rules.KIND_UNKNOWN
}
EQUIPMENT_LINES = (
    "another equipment type",
    "the paper names no equipment",
    "the paper names equipment the equipment list does not know",
    "the paper's equipment could not be read",
)


class _Cancelled(Exception):
    pass


def _now() -> str:
    return job_queue.now_iso()


# ---------------------------------------------------------------- enqueue, claim, recover


def enqueue(
    submittal_document_id: str,
    *,
    allowed_document_ids: frozenset[str],
    requested_by: str | None,
    project_document_ids: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    """Create the run and its job together. Returns (run_id, job_id).

    Raises ReviewAlreadyActive when ANY review (classic or AI) of this submittal is queued or running, and ValueError when
    the caller may not read the submittal. Off: raises FeatureOff and creates nothing. (The paper's kind is checked by the
    caller first: `agent_review_gate.any_kind_enabled`.) `project_document_ids` is not None only for a GENERAL review (a
    procedure or a contract): the papers the request named for part 4, written with the run in the same transaction."""
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
            (submittal_document_id, *ACTIVE_RUN),
        ).fetchone()
        if active is not None:
            raise review_jobs.ReviewAlreadyActive(active["id"])
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, started_by,"
            " started_at, created_at, updated_at) VALUES (?,?,'queued',?,?,?,?)",
            (run_id, submittal_document_id, requested_by, now, now, now),
        )
        conn.execute(
            """INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at,
                                 priority, created_by, code_version, config_version,
                                 review_run_id, progress_done, progress_total, progress_label)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?, 'queued')""",
            (job_id, submittal_document_id, STAGE, now, now, job_queue.PRIORITY_INTERACTIVE, requested_by,
             review_jobs.review_code_version(), config_version(), run_id, len(STEPS)),
        )  # fmt: skip
        if project_document_ids is not None:
            general_job.record_request(conn, run_id, project_document_ids)
        job_queue.audit(
            conn,
            "job.queued",
            job_id,
            actor_user_id=requested_by,
            detail=f"stage={STAGE} run={run_id}",
        )
    claude_auto_approve.on_review_start(
        run_id
    )  # #1584: the subject joins the approved list, unless blocked
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
             "limit": settings.job_max_running},
        ).fetchone()  # fmt: skip
        if row is None:
            return None
        conn.execute(
            "UPDATE review_runs SET status = 'running', updated_at = ? WHERE id = ?",
            (now, row["review_run_id"]),
        )
    return row["id"]


def recover_stale(*, at_startup: bool = False) -> int:
    """A job left `running` by a dead process goes back to the queue with its run; the run resumes from its stored lines.
    Nothing is recovered, and no table is read, with the switch off."""
    if not agent_review_gate.enabled():
        return 0
    from . import review_recovery

    agent_review_schema.upgrade_if_old(
        quiet=True
    )  # an older line table is upgraded at the worker's start
    return review_recovery.recover(STAGE, at_startup=at_startup)


# ---------------------------------------------------------------- lines


def _progress(conn, job_id: str, done: int, heartbeat=None) -> None:
    """Record progress and honour a cancellation - between steps, never inside one."""
    if heartbeat is not None:
        heartbeat()
    with conn:
        row = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row and row["cancel_requested"]:
            raise _Cancelled()
        conn.execute(
            "UPDATE jobs SET progress_done = ?, progress_label = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
            (done, STEPS[min(done, len(STEPS) - 1)], _now(), _now(), job_id),
        )


def run_dir(run_id: str) -> Path:
    return Path(settings.data_dir) / "agent_reviews" / run_id


def _tier_word(item: dict) -> str | None:
    """The tier of a rule ITEM as asked (a checklist item has none: None)."""
    if item.get("source") != "rule":
        return None
    if item.get("rule_tier") == rules.RULE_NOT_APPROVED:
        return "Not AI approved"
    return (
        TIER_WORDS.get((item.get("rule_label") or {}).get("tier")) or "Not AI approved"
    )


def _line_tier(line: dict) -> str | None:
    """The tier of a stored LINE: the one the exit wrote (`tier`, from the CURRENT label table); a checklist line has none."""
    if line.get("checklist") is True and line.get("tier") is None:
        return None
    return TIER_WORDS.get(line.get("tier")) or "Not AI approved"


def store_line(run_id: str, line: dict, trace: dict | None) -> None:
    """One line into `agent_review_line` (an upsert: a resumed run replaces its own failed line). The line already went through
    the runner's one exit; the table's CHECK refuses an unproven Pass or Fail again."""
    cls, word = pair_mod.class_and_word_for_write(line, _line_tier(line))
    reason = str(
        line.get("not_proven_reason") or line.get("reasoning") or line.get("why") or ""
    )
    page = line.get("paper_page")
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book,"
            " reason, rule_tier, line_json, trace_json, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (run_id, item_id) DO UPDATE SET verdict_class = excluded.verdict_class, word = excluded.word,"
            " page = excluded.page, clause = excluded.clause, rule_book = excluded.rule_book, reason = excluded.reason,"
            " rule_tier = excluded.rule_tier, line_json = excluded.line_json,"
            " trace_json = COALESCE(excluded.trace_json, agent_review_line.trace_json),"
            " decided_at = excluded.decided_at",
            (run_id, str(line["item_id"]), cls, word, page if isinstance(page, int) and page >= 1 else None,
             str(line.get("clause") or ""), str(line.get("standard") or ""), reason, _line_tier(line),
             json.dumps(line, ensure_ascii=False, default=str),
             None if trace is None else json.dumps(trace, ensure_ascii=False, default=str), _now()),
        )  # fmt: skip


def stored_lines(run_id: str) -> dict[str, dict]:
    """The lines already decided for this run (the resume set), by item id."""
    out: dict[str, dict] = {}
    for r in connect().execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ?", (run_id,)
    ):
        try:
            out[r["item_id"]] = json.loads(r["line_json"])
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- rules and books


def _equipment_of(label: dict | None) -> str | None:
    """The equipment (type, else family) a rule's label AGREES on; None when the label has none or it is not agreed."""
    label = label or {}
    if str(label.get("equip_state") or "") != "agreed":
        return None
    return label.get("equip_type") or label.get("equip_family") or None


def _asked_row(run_id: str, it: dict, cache: dict, kind: str) -> tuple:
    lab = it.get("rule_label") or {}
    ref = it.get("rule_quote_ref") or it.get("clause_quote_ref")
    entry = cache.get(ref) if isinstance(ref, str) else None
    quote = (
        entry.get("text")
        if isinstance(entry, dict)
        else (entry if isinstance(entry, str) else None)
    )
    full = (
        rule_labels.label_for(connect(), requirement_id=str(it.get("rule_version_id")))
        or {}
    )
    read_from = "scan" if str(full.get("read_from") or "") == "scan" else "text"
    return (run_id, str(it.get("item_id")), 1, None, str(it.get("standard") or ""), str(it.get("clause") or ""), quote,
            it.get("clause_page"), it.get("standard_document_id"), read_from, lab.get("paper_kind") or kind,
            lab.get("field"), _equipment_of(lab.get("equipment")), _tier_word(it))  # fmt: skip


def _write_rules(run_id: str, doc: dict, cache: dict, kind: str) -> None:
    """Every rule of the run: asked, or left out with its one reason. Idempotent (a resumed run writes the same rows)."""
    block = doc.get("rule_labels") or {}
    rows = [
        _asked_row(run_id, it, cache, kind)
        for it in doc.get("items") or []
        if it.get("source") == "rule"
    ]
    for rec in block.get("left_out") or []:
        reason = LEFT_OUT_WORDS.get(rec.get("reason"))
        if reason is None:
            continue  # "paper kind unknown": said once on the run, not once per rule
        rows.append((run_id, str(rec.get("rule_version_id") or rec.get("item_id")), 0, reason,
                     str(rec.get("rule_book") or ""), str(rec.get("clause") or ""), None, rec.get("page"),
                     rec.get("standard_document_id"), "text", rec.get("needs_paper_kind"), None, None, None))  # fmt: skip
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_rule (run_id, rule_key, asked, left_out_reason, rule_book, clause, quote,"
            " quote_page, standard_document_id, read_from, paper_kind, field, equipment, tier)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def _write_missing(run_id: str, missing: list[dict]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
            [
                (run_id, str(m.get("rule_book")), str(m.get("why") or ""))
                for m in missing
                if m.get("rule_book")
            ],
        )


def lane() -> tuple:
    """(send, env) for the Claude calls: (None, None) in the app, the real lane. Tests replace this with a fake model."""
    return None, None


def _document_name(submittal: str) -> str:
    row = (
        connect()
        .execute("SELECT filename FROM documents WHERE id = ?", (submittal,))
        .fetchone()
    )
    return (row["filename"] if row else None) or submittal


# ---------------------------------------------------------------- plan, preflight, execute, finish


def _scope_run_id(
    conn, submittal: str, run_id: str, scope: frozenset[str], heartbeat
) -> str:
    """The run whose stored scope decisions name the rules to ask: this run's own (a resumed run), else a finished classic
    run of the SAME review code version, else the classic selection runs inline under this run's id."""
    from . import applicability, submittal_fill

    own = conn.execute(
        "SELECT 1 FROM review_scope_decisions WHERE review_run_id = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    if own:
        return run_id
    reuse = conn.execute(
        "SELECT r.id FROM review_runs r JOIN jobs j ON j.review_run_id = r.id"
        " WHERE r.submittal_document_id = ? AND r.status = 'completed' AND j.stage = ? AND j.code_version = ?"
        " AND EXISTS (SELECT 1 FROM review_scope_decisions s WHERE s.review_run_id = r.id)"
        " ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
        (submittal, review_jobs.STAGE, review_jobs.review_code_version()),
    ).fetchone()
    if reuse:
        return reuse["id"]
    submittal_fill.for_review(submittal)
    applicability.select(
        submittal,
        allowed_document_ids=scope,
        review_run_id=run_id,
        persist=True,
        heartbeat=heartbeat,
    )
    return run_id


def _no_rules_block(conn, submittal: str, why: str) -> dict:
    """The rules-used block of a paper no rule is asked of (unknown kind, or a kind the reviewer is not enabled for)."""
    return {"on": True, "paper_kind": None, "paper_kind_known": False, "summary_lines": [why], "left_out": [],
            "counts": {}, "missing_rule_books": rules.missing_rule_books(conn, submittal)}  # fmt: skip


def _nothing_asked(conn, submittal: str, why: str, stop: str) -> dict:
    return {
        "block": _no_rules_block(conn, submittal, why),
        "items": [],
        "cache": {},
        "stop": stop,
    }


def preflight(
    conn, submittal: str, kind: agent_review_kind.PaperReading, doc: dict, cache: dict
) -> str | None:
    """Why this run must be REFUSED before any call, or None. Inconsistent inputs are never asked of the model:
    the switch off, a kind the reviewer is not enabled for, a paper with no stored page, an item list that fails its own
    validation, a paper kind that differs from the one the rule filter used, rule-book pages missing for the context check,
    and a lead and a second model of the same family."""
    from . import agent_claude, agent_run_second

    block = doc.get("rule_labels") or {}
    if not agent_review_gate.enabled():
        return "the AI reviewer is switched off"
    shape = agent_review_schema.shape_problem(conn)  # before the first Claude call
    if shape:
        return shape
    if not (kind.known and agent_review_gate.kind_enabled(kind.kind)):
        return agent_review_gate.KIND_NOT_ENABLED_MESSAGE
    if not conn.execute(
        "SELECT 1 FROM pages WHERE document_id = ? AND TRIM(text) <> '' LIMIT 1",
        (submittal,),
    ).fetchone():
        return "the paper has no stored page text"
    problems = items_mod.validate(doc, cache)
    if problems:
        return f"the item list failed its checks ({len(problems)} problem(s))"
    if rules.norm_kind(block.get("paper_kind")) != rules.norm_kind(kind.kind):
        return "the paper kind of the run differs from the kind the rule filter used"
    docs = sorted(
        {
            str(i["standard_document_id"])
            for i in doc.get("items") or []
            if i.get("standard_document_id")
        }
    )
    for d in docs:
        if not conn.execute(
            "SELECT 1 FROM pages WHERE document_id = ? LIMIT 1", (d,)
        ).fetchone():
            return "a rule book of the item list has no stored pages (the context check needs them)"
    if not agent_run_second.models_differ(
        [agent_claude.LEAD_MODEL], agent_claude.SECOND_MODEL
    ):
        return "the lead and the second model are of the same family"
    return None


def _plan(
    conn,
    run_id: str,
    submittal: str,
    scope: frozenset[str],
    kind: agent_review_kind.PaperReading,
    heartbeat,
) -> dict:
    """The items of the run: the right rules only for a paper whose kind the reviewer is enabled for, else none."""
    if not kind.known:
        why = "paper kind unknown: no rule was asked of this paper; an engineer names the paper kind and the review runs again"
        return _nothing_asked(conn, submittal, why, f"paper_kind_unknown: {why}")
    if not agent_review_gate.kind_enabled(kind.kind):
        why = f"{agent_review_gate.KIND_NOT_ENABLED_MESSAGE}: no rule was asked of this {kind.kind.replace('_', ' ')}"
        return _nothing_asked(
            conn, submittal, why, f"{agent_review_gate.KIND_NOT_ENABLED}: {why}"
        )
    scope_run = _scope_run_id(conn, submittal, run_id, scope, heartbeat)
    claude_auto_approve.on_review_start(
        scope_run
    )  # a cited standard joins the list too (when auto-approve is on)
    cache: dict = {}
    # The classic selection run inline stores which BOOKS apply, never per-rule scope decisions (only a full classic review
    # writes those). With none stored, the candidates are the rules of the selected books; the label filter narrows them (#1749).
    doc = items_mod.build_items_for_run(conn, submittal, kind.as_dict(), scope_run, scope, cache=cache,
                                        equipment_type=kind.equipment_type, ask_unapproved=ASK_UNAPPROVED)  # fmt: skip
    _write_rules(run_id, doc, cache, kind.kind)
    refused = preflight(conn, submittal, kind, doc, cache)
    if refused:
        out = _nothing_asked(
            conn,
            submittal,
            f"refused before any call: {refused}",
            f"refused: {refused}",
        )
        out["block"]["left_out"], out["block"]["counts"] = (
            (doc.get("rule_labels") or {}).get("left_out", []),
            (doc.get("rule_labels") or {}).get("counts", {}),
        )
        return out
    return {
        "block": doc.get("rule_labels") or {},
        "items": list(doc.get("items") or []),
        "cache": cache,
        "stop": None,
    }


def _tier_lookup(kind: agent_review_kind.PaperReading):
    """The core's `rules.tier_lookup` on the calling thread's own connection (a sqlite connection does not cross threads)."""

    def lookup(item) -> str | None:
        return rules.tier_lookup(
            connect(), kind.kind, kind.known, equipment_type=kind.equipment_type
        )(item)

    return lookup


def _make_runner(
    run_id: str, submittal: str, kind: agent_review_kind.PaperReading, plan: dict
):
    """The runner for this run: kept lines from an earlier attempt are not asked again (no second charge)."""
    from . import agent_claude

    send, env = lane()
    folder = run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    done = {k: v for k, v in stored_lines(run_id).items() if not v.get("error")}
    return runner_mod.Runner(
        paper=submittal, items=plan["items"], pages=request_mod.DbPages(connect(), submittal),
        clauses=request_mod.ClauseCache(plan["cache"]), model=agent_claude.LEAD_MODEL, send=send, env=env,
        done_lines=done, paper_kind=kind.kind, equipment_type=kind.equipment_type, std_pages=request_mod.StdPages(),
        reread_silent=settings.agent_review_reread_silent_enabled,
        sink=lambda line, trace: store_line(run_id, line, trace), trace_path=folder / "trace.jsonl",
        tier_lookup=_tier_lookup(kind),
        retry_base=0.0 if send is not None else request_mod.RETRY_BASE_SECONDS,
    )  # fmt: skip


def _ask(
    run_id: str,
    submittal: str,
    kind: agent_review_kind.PaperReading,
    plan: dict,
    holder: dict,
) -> None:
    """Run the reviewer over the items. The lines decided so far are kept whatever happens; a stop is said, then re-raised."""
    from . import claude_spend

    if (
        not agent_review_verdict.checklist_ids()
    ):  # no checklist data on this machine: every checklist line is capped (safe)
        log.warning(
            "agent review: no checklist data found; no line can be a checklist line"
        )
    runner = holder["runner"] = _make_runner(run_id, submittal, kind, plan)
    declared = {submittal} | {
        str(i["standard_document_id"])
        for i in plan["items"]
        if i.get("standard_document_id")
    }
    try:
        with claude_approved.carrying(sorted(declared)), claude_spend.for_run(run_id):
            runner.run()
    except BaseException as exc:
        if not runner.stopped:
            runner.stopped, runner.stop_text = request_mod.stop_reason(
                exc, runner.last_app_worst
            )
        raise


def _stop_text(runner, plan: dict) -> str | None:
    if runner is not None and runner.stopped:
        same = not runner.stop_text or runner.stop_text == runner.stopped
        return runner.stopped if same else f"{runner.stopped}: {runner.stop_text}"
    return plan.get("stop")


def _header_facts(submittal: str, equipment_type: str | None) -> dict:
    """The CRS header block's facts (project, document number, title, revision, date, discipline) as the app holds them."""
    with connect() as conn:
        return crs_header.document_header(conn, submittal, equipment_type)


def _equipment_facts(block: dict) -> dict:
    """What the paper's equipment state means for the rules: the state word, and the summary sentences about equipment (counts
    only, no document text) that the summary and Rules used routes show."""
    eq = block.get("equipment") or {}
    notes = [
        ln
        for ln in block.get("summary_lines") or []
        if str(ln).startswith(EQUIPMENT_LINES)
    ]
    return {
        "state": eq.get("paper_equipment_state"),
        "types": eq.get("paper_types") or [],
        "notes": notes,
        "candidates": block.get("candidates"),
    }


def _finish(
    run_id: str,
    submittal: str,
    kind: agent_review_kind.PaperReading,
    plan: dict,
    runner,
    started: str,
) -> dict:
    """The run row and the CRS copies. Called also for a partial run (a cap, a refusal)."""
    items = plan["items"]
    lines = [runner.lines[k] for i in items if (k := str(i["item_id"])) in runner.lines] if runner else []  # fmt: skip
    counts = runner_mod.counts_of(lines, runner)
    reread = (  # C4: a stopped page re-read is stated, never dropped (null when off or ran fully)
        reread_mod.reread_facts(runner.reread_enabled, runner.reread_stopped, lines)
        if runner
        else None
    )
    models = sorted(runner.lead_models | runner.second_models) if runner else []
    spent = runner and (
        runner.calls["lead"] or runner.calls["second"] or runner.calls["context"]
    )
    usd = round(runner.run_usd, 6) if spent else None
    stop = _stop_text(runner, plan)
    meta = {"paper": _document_name(submittal), "run_id": run_id, "date": started[:10],
            "lead_models": sorted(runner.lead_models) if runner else [],
            "second_models": sorted(runner.second_models) if runner else [], "rule_labels": plan["block"] or None,
            "usd": usd, "header": _header_facts(submittal, kind.equipment_type), **{k: v for k, v in counts.items() if k.startswith("two_reader")},
            "order12_counts": {"rules_left_out": plan["block"].get("counts"),
                               "rule_books_not_held": len(plan["block"].get("missing_rule_books") or []),
                               **({"page_reread_stopped": reread_mod.stopped_sentence(reread)} if reread else {})}}  # fmt: skip
    folder = run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    crs_lines.write_internal(lines, folder / "crs-internal.xlsx", meta)
    crs_lines.write_contractor(lines, folder / "crs-contractor.xlsx", meta)
    partial = bool(runner and runner.stopped) or bool(counts.get("not_run"))
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, equipment_type,"
            " usd, models_json, stop_reason, counts_json, items_total, partial, rule_set_changed_by, started_at, finished_at,"
            " equipment_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)",
            (run_id, submittal, kind.kind, kind.source, kind.equipment_type, usd, json.dumps(models), stop,
             json.dumps(counts, default=str), len(items), 1 if partial else 0, started, _now(),
             json.dumps({**_equipment_facts(plan["block"]), "page_reread": reread})),
        )  # fmt: skip
    return {"counts": counts, "stop_reason": stop, "usd": usd, "partial": partial}


def _write_run_start(
    run_id: str, submittal: str, kind: agent_review_kind.PaperReading, started: str
) -> None:
    """A first row of the run, so its summary can be read while it runs (spend unknown: NULL, never 0)."""
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, equipment_type,"
            " started_at) VALUES (?,?,?,?,?,?)",
            (run_id, submittal, kind.kind, kind.source, kind.equipment_type, started),
        )


def _execute(
    run_id: str,
    submittal: str,
    kind: agent_review_kind.PaperReading,
    plan: dict,
    started: str,
) -> dict:
    _write_missing(run_id, plan["block"].get("missing_rule_books") or [])
    holder: dict = {}
    try:
        if plan["items"]:
            _ask(run_id, submittal, kind, plan, holder)
    finally:  # the CRS and the run row are written for a partial run too
        result = _finish(run_id, submittal, kind, plan, holder.get("runner"), started)
    return result


def _fail(conn, job_id: str, run_id: str, submittal: str, exc: Exception) -> str:
    from . import errors

    safe = errors.record_failure(exc, document_id=submittal, stage=STAGE)
    with conn:
        state = job_queue.fail(
            conn, job_id, code=type(exc).__name__, message=safe["message"]
        )
        if state == job_queue.POISONED:
            outcome = {
                "error": safe["message"],
                "agent_review": True,
                "partial": bool(stored_lines(run_id)),
            }
            conn.execute("UPDATE review_runs SET status = 'failed', outcome_json = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(outcome), _now(), run_id))  # fmt: skip
        else:
            conn.execute(
                "UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
                (_now(), run_id),
            )
    return state


def _cancelled(conn, job_id: str, run_id: str) -> str:
    with conn:
        conn.execute(
            "UPDATE review_runs SET status = 'cancelled', outcome_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps({"error": "cancelled by an engineer before it finished"}),
                _now(),
                run_id,
            ),
        )
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
            (job_queue.CANCELLED, _now(), job_id),
        )
        job_queue.audit(
            conn, "job.cancelled", job_id, detail=f"run={run_id} while running"
        )
    return job_queue.CANCELLED


def _done(conn, job_id: str, run_id: str, result: dict) -> str:
    outcome = {"agent_review": True, "partial": result["partial"], "stop_reason": result["stop_reason"],
               "counts": {k: v for k, v in result["counts"].items() if isinstance(v, int)}}  # fmt: skip
    with conn:
        conn.execute(
            "UPDATE review_runs SET status = 'completed', outcome_json = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (json.dumps(outcome), _now(), _now(), run_id),
        )
        conn.execute(
            "UPDATE jobs SET state = 'done', progress_done = ?, progress_label = 'done', error_code = NULL,"
            " error_message = NULL, next_attempt_at = NULL, updated_at = ? WHERE id = ?",
            (len(STEPS), _now(), job_id),
        )
        job_queue.audit(conn, "job.done", job_id, detail=f"stage={STAGE} run={run_id}")
    return "done"


def _requeue_switched_off(conn, job_id: str, run_id: str) -> str:
    """The switch went off while the job waited: nothing is sent, the job goes back to the queue."""
    with conn:
        conn.execute(
            "UPDATE jobs SET state = 'queued', claimed_by = NULL, claimed_at = NULL, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        conn.execute(
            "UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
            (_now(), run_id),
        )
    return "queued"


@review_jobs._review_scope  # the bar on the local engine; ledger lines carry the run's id; spend in the run's record
def run(job_id: str, worker_id: str, heartbeat=None) -> str:
    """Run one claimed AI review job to its end. Returns the job's final state."""
    conn = connect()
    job = conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND state = 'running' AND claimed_by = ?",
        (job_id, worker_id),
    ).fetchone()
    if job is None:
        return "not_claimed"
    run_id, submittal = job["review_run_id"], job["document_id"]
    if not agent_review_gate.enabled():
        return _requeue_switched_off(conn, job_id, run_id)
    try:
        agent_review_schema.ensure_schema()
    except (
        agent_review_schema.UpgradeFailed
    ) as exc:  # nothing is asked, nothing is paid
        return _fail(conn, job_id, run_id, job["document_id"], exc)
    scope, started = review_jobs._scope_of(job["created_by"]), _now()
    try:
        if submittal not in scope:
            raise PermissionError("the requester can no longer read this submittal")
        _progress(conn, job_id, 0, heartbeat)
        text = agent_review_text.read_step(conn, submittal, scope, run_id)
        _progress(conn, job_id, 1, heartbeat)
        kind = agent_review_kind.decide(submittal, scope)
        _write_run_start(run_id, submittal, kind, started)
        general = kind.known and agent_review_gate.general_kind_enabled(kind.kind)
        stops = text.stops_run(general)
        if general and not stops:
            _progress(conn, job_id, 2, heartbeat)
            result = general_job.run(run_id, submittal, scope, kind, started, folder=run_dir(run_id),
                                     name=_document_name(submittal), lane=lane,
                                     heartbeat=heartbeat)  # fmt: skip
            agent_review_text.record_general(conn, run_id, text, result)
            _progress(conn, job_id, 3, heartbeat)
            return _done(conn, job_id, run_id, result)
        plan = (_nothing_asked(conn, submittal, text.sentence, text.stop) if stops
                else _plan(conn, run_id, submittal, scope, kind, heartbeat))  # fmt: skip
        # a plan with nothing to ask always says why
        agent_review_text.ensure_stop(plan, LEFT_OUT_WORDS)
        _progress(conn, job_id, 2, heartbeat)
        result = _execute(run_id, submittal, kind, plan, started)
        agent_review_text.record(conn, run_id, text)
        _progress(conn, job_id, 3, heartbeat)
    except nothing_read.StoredFileAbsent as exc:
        return nothing_read.fail_run(job_id, run_id, exc)
    except _Cancelled:
        return _cancelled(conn, job_id, run_id)
    except Exception as exc:  # noqa: BLE001 - a failed review must not kill the worker
        log.warning(
            "agent review failed: %s", type(exc).__name__
        )  # the class only, never a text
        return _fail(conn, job_id, run_id, submittal, exc)
    return _done(conn, job_id, run_id, result)
