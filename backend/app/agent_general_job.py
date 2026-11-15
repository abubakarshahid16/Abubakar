"""The general review as a step of the AI reviewer's job (#1690, #781): plan, run, store, write.

Called by `agent_review_jobs.run` (the SAME job, the same run row, the same switch) when the decided kind of the paper is one the
gate names for general review (`agent_review_gate.AGENT_GENERAL_REVIEW_KINDS`). This module declares what its Claude prompts
carry: exactly the paper and the project papers the request named (`claude_approved.carrying`), nothing else, and never rule-book
text. The calls themselves go through the review runner (`agent_review_run.Runner.call`) and so through `claude_spend.metered`
and the step gate: the USD caps are the existing ones.

A request's project papers are named by the person (`project_document_ids`), never chosen silently: the app has no project or
folder field on a document to choose from. Each is checked again here against the REQUESTER's scope (a filter may only narrow)
and, before any call, against the approved-documents list: one that fails stops the run with no call and no charge.

The run is re-writable: the lines of a run are replaced as a set, and every model reply is kept by step (local disk), so a
resumed run pays nothing twice. The tables and files are written for a partial run too.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

from . import (
    agent_claude,
    agent_review_schema,
    claude_approved,
    claude_spend,
    job_queue,
)
from . import agent_general_crs as crs
from . import agent_general_parts as parts
from . import agent_general_prompts as prompts
from . import agent_general_review as core
from . import agent_review_gate as gate
from . import agent_review_local as local_mod
from . import agent_review_request as request_mod
from . import agent_review_run as runner_mod
from . import crs_ai_header as crs_header
from .db import connect

log = logging.getLogger(__name__)


def requested_papers(conn, run_id: str) -> list[str]:
    row = conn.execute(
        "SELECT requested_json FROM agent_review_general WHERE run_id = ?", (run_id,)
    ).fetchone()
    try:
        return [str(x) for x in json.loads(row[0])] if row else []
    except ValueError:
        return []


def record_request(conn, run_id: str, project_ids: Iterable[str]) -> None:
    """The papers the request named, written in the SAME transaction that creates the run (a general run has this row)."""
    conn.execute(
        "INSERT OR REPLACE INTO agent_review_general (run_id, requested_json, project_json) VALUES (?,?, '[]')",
        (run_id, json.dumps([str(d) for d in project_ids])),
    )


def preflight(
    decision: dict, problems: list[str], shape: str | None = None, local: bool = False
) -> str | None:
    """Why this run is refused before any call, or None: the switch off, the paper or its kind refused by `decide_mode`, a project
    paper the requester may not use, a lead and a second model of the same family."""
    from . import agent_run_second

    if not gate.enabled():
        return "the AI reviewer is switched off"
    if shape:  # the table shape, before the first Claude call: never pay, then fail at the write
        return shape
    if not decision.get("ok"):
        return str(decision.get("message") or "refused").removeprefix("REFUSED | ")
    if problems:
        return "project paper refused: " + "; ".join(problems)
    if not local and not agent_run_second.models_differ(
        [agent_claude.LEAD_MODEL], agent_claude.SECOND_MODEL
    ):  # a local run checks its two models at the engine
        return "the lead and the second model are of the same family"
    return None


def store_lines(conn, run_id: str, lines: list[dict]) -> None:
    """The lines of the run REPLACE what an earlier attempt stored (one transaction): a resumed run never leaves a stale line."""
    rows = []
    for ln in lines:
        q = ln.get("quote_a") or ln.get("quote_paper") or {}
        page = q.get("page")
        trace = {
            "prompt_version": prompts.PROMPT_VERSION,
            "part": core.PART_WORDS[ln["part"]],
            "quotes_verified_by_code": bool(ln.get("quotes_verified_by_code")),
            "second_model": ln.get("second_model") or [],
            "second_model_reason": ln.get("second_model_reason"),
            "figures": ln.get("figures"),
        }
        rows.append(
            (
                run_id,
                ln["item_id"],
                ln["verdict_class"],
                ln["word"],
                page if isinstance(page, int) and page >= 1 else None,
                "",
                ln.get("rule_book") or ", ".join(ln.get("held_rule_books") or []),
                ln["text"],
                None,
                json.dumps({**ln, "general": True}, ensure_ascii=False, default=str),
                json.dumps(trace, ensure_ascii=False),
                core_now(),
                core.PART_WORDS[ln["part"]],
                ln.get("text_source"),
            )
        )
    with conn:
        # only this mode's own lines: a run that also asked the rules of its kind keeps the rule lines it stored
        conn.execute(
            "DELETE FROM agent_review_line WHERE run_id = ? AND json_extract(line_json, '$.general') = 1",
            (run_id,),
        )
        conn.executemany(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier,"
            " line_json, trace_json, decided_at, part, text_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def core_now() -> str:
    return job_queue.now_iso()


def _stop_text(g, stop: str) -> str:
    """The stop reason in words: the code, then the plain reason when it differs (numbers and codes only)."""
    if g is None or not g.stopped:
        return stop
    text = getattr(g.runner, "stop_text", "")
    return g.stopped if not text or text == g.stopped else f"{g.stopped}: {text}"


def _write_missing(conn, run_id: str, not_held: list[dict]) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
            [
                (run_id, str(b["rule_book"]), str(b.get("why") or ""))
                for b in not_held
                if b.get("rule_book")
            ],
        )


def _counts(g, lines: list, per_class: dict, dropped: dict) -> dict:
    """The run's counts: lines by class, what was dropped, the parts, and for a local run its requests (numbers only)."""
    return {
        "lines": len(lines),
        "not_reviewed": per_class.get(core.CLASS_NOT_REVIEWED, 0),
        "mode": core.MODE_WORD,
        "per_class": per_class,
        "dropped": dropped,
        "parts": {str(p): c for p, c in g.part_counts.items()} if g else {},
        **(g.local.stats() if g and g.local is not None else {}),
    }


def _run_parts(g, runner, carrier, local, run_id, heartbeat) -> None:
    """Run the five parts: on the local engine (nothing reaches Claude: no approval list, no spend context, no ledger; one big model
    at a time) or on the Claude lane (approvals, spend context, the step gate)."""
    if local is not None:
        if heartbeat is not None:
            heartbeat()
        local.progress_cb = local_mod.progress_writer(run_id)
        try:
            with local.session():
                g.run_all()
        except (
            local_mod.heavy_lock.HeavyJobBusy
        ) as exc:  # nothing was asked: said in plain words, not a type name
            g.stopped = local_mod.busy_words(exc)
        return
    with claude_approved.carrying(carrier), claude_spend.for_run(run_id):
        runner.gate = request_mod.AppStepGate(
            request_mod.app_cap(), claude_spend.step_spent(agent_claude.STEP)
        )
        _approval_stop(runner)
        g.stopped = runner.stopped
        if heartbeat is not None:
            heartbeat()
        g.run_all()


def _finish(
    conn,
    *,
    run_id,
    submittal,
    kind,
    started,
    folder: Path,
    g,
    accepted,
    stop,
    name,
    combined: bool = False,
) -> dict:
    lines = g.lines if g else []
    store_lines(conn, run_id, lines)
    meta = {
        "paper": name,
        "run_id": run_id,
        "date": started[:10],
        "lead_models": sorted(g.lead_models) if g else [],
        "second_models": sorted(g.second_models) if g else [],
        "header": crs_header.document_header(conn, submittal, None),
        "kind": kind.kind,
    }
    dropped = g.dropped.as_json() if g else {}
    crs.write_all(lines, folder, meta, accepted, dropped)
    per_class = dict(Counter(ln["verdict_class"] for ln in lines))
    counts = _counts(g, lines, per_class, dropped)
    spent = g is not None and sum(g.calls.values()) > 0
    stopped = _stop_text(g, stop)
    partial = bool(stopped) or bool(g and g.failures)
    usd = round(g.runner.run_usd, 6) if spent else None
    models = sorted(g.lead_models | g.second_models) if g else []
    with conn:
        if combined:
            _merge_run_row(
                conn, run_id, counts, usd, models, stopped, partial, len(lines)
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, equipment_type,"
                " usd, models_json, stop_reason, counts_json, items_total, partial, rule_set_changed_by, started_at, finished_at,"
                " equipment_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)",
                (
                    run_id,
                    submittal,
                    kind.kind,
                    kind.source,
                    None,
                    usd,
                    json.dumps(models),
                    stopped or None,
                    json.dumps(counts, default=str),
                    len(lines),
                    1 if partial else 0,
                    started,
                    core_now(),
                    json.dumps({}),
                ),
            )
        conn.execute(
            "INSERT INTO agent_review_general (run_id, requested_json, project_json) VALUES (?, '[]', ?)"
            " ON CONFLICT (run_id) DO UPDATE SET project_json = excluded.project_json",
            (run_id, json.dumps(accepted)),
        )
    return {
        "counts": {k: v for k, v in counts.items() if isinstance(v, int)},
        "stop_reason": stopped or None,
        "usd": round(g.runner.run_usd, 6) if spent else None,
        "partial": partial,
    }


def _merge_run_row(
    conn, run_id, counts, usd, models, stopped, partial, n_lines
) -> None:
    """A run that asked the rules of its kind FIRST has its run row already: this adds the general review to it (counts under
    `general_review`, the spend summed, the models joined, the stop reason kept, the line total summed). Nothing is replaced."""
    row = conn.execute(
        "SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)
    ).fetchone()
    old = json.loads(row["counts_json"] or "{}") if row else {}
    spent = [x for x in (row["usd"] if row else None, usd) if x is not None]
    joined = sorted(
        set(json.loads(row["models_json"] or "[]") if row else []) | set(models)
    )
    conn.execute(
        "UPDATE agent_review_run SET counts_json = ?, usd = ?, models_json = ?, stop_reason = COALESCE(stop_reason, ?),"
        " items_total = COALESCE(items_total, 0) + ?, partial = MAX(COALESCE(partial, 0), ?), finished_at = ? WHERE run_id = ?",
        (json.dumps({**old, "general_review": counts}, default=str), round(sum(spent), 6) if spent else None,
         json.dumps(joined), stopped or None, n_lines, 1 if partial else 0, core_now(), run_id),
    )  # fmt: skip


def merge_results(rule: dict, general: dict) -> dict:
    """The job's result of a run that did both parts: counts side by side (ints summed), the first stop reason, the spend summed."""
    counts = dict(rule.get("counts") or {})
    for k, v in (general.get("counts") or {}).items():
        if isinstance(v, int) and not isinstance(v, bool):
            counts[k] = counts.get(k, 0) + v
    usd = [x for x in (rule.get("usd"), general.get("usd")) if x is not None]
    return {
        "counts": counts,
        "stop_reason": rule.get("stop_reason") or general.get("stop_reason"),
        "usd": round(sum(usd), 6) if usd else None,
        "partial": bool(rule.get("partial") or general.get("partial")),
    }


def note_skipped(run_id: str, why: str) -> None:
    """The general parts were not run because the rule part stopped: the run row says so (a cause, never silence)."""
    conn = connect()
    with conn:
        row = conn.execute(
            "SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        old = json.loads(row["counts_json"] or "{}") if row else {}
        conn.execute(
            "UPDATE agent_review_run SET counts_json = ? WHERE run_id = ?",
            (
                json.dumps(
                    {
                        **old,
                        "general_review": {
                            "skipped": f"the rule part stopped first: {why}"
                        },
                    }
                ),
                run_id,
            ),
        )


def _make_runner(
    submittal: str, kind, send, env, retry_base: float, trace_path: Path, local=None
):
    return runner_mod.Runner(
        paper=submittal,
        items=[],
        pages=request_mod.DbPages(connect(), submittal),
        clauses=request_mod.ClauseCache({}),
        model=agent_claude.LEAD_MODEL,
        send=send,
        env=env,
        paper_kind=kind.kind,
        trace_path=trace_path,
        retry_base=retry_base,
        local=local,
    )


def _approval_stop(runner) -> None:
    """Before any call: a declared document the approval list refuses (or blocks) stops the run, nothing is sent."""
    refusal = claude_approved.refusal()
    if refusal is not None:
        runner._halt(agent_claude.AgentGateClosed(refusal[0]))


def _build(conn, run_id, submittal, kind, decision, accepted, folder, lane, local=None):
    """The run object, its runner and the carrier (the paper and the named project papers, nothing else)."""
    _write_missing(conn, run_id, decision["not_held"])
    items, info = core.checklist_items(conn, decision["kind"], submittal)
    ids = [p["document_id"] for p in accepted]
    carrier = [submittal, *ids]
    docs = core.load_documents(conn, submittal, ids, carrier)
    send, env = lane()
    retry = 0.0 if send is not None else request_mod.RETRY_BASE_SECONDS
    runner = _make_runner(
        submittal, kind, send, env, retry, folder / "trace.jsonl", local
    )
    g = parts.GeneralRun(
        paper=submittal, docs=docs, kind=decision["kind"], books=decision, items=items, items_info=info, project=ids,
        run_dir=folder, runner=runner, unread=core.unread_pages(conn, submittal), local=local,
    )  # fmt: skip
    return g, runner, carrier


def run(
    run_id: str,
    submittal: str,
    scope: frozenset[str],
    kind,
    started: str,
    *,
    folder: Path,
    name: str,
    lane: Callable[[], tuple],
    heartbeat: Callable[[], None] | None = None,
    combined: bool = False,
    local=None,
) -> dict:
    """The whole general review of one paper. Returns what the job's `_done` needs (counts, stop reason, USD, partial)."""
    conn = connect()
    folder.mkdir(parents=True, exist_ok=True)
    if agent_review_schema.shape_problem(
        conn
    ):  # before anything is read, asked or paid
        raise agent_review_schema.UpgradeFailed(
            "the older table shape is still in place"
        )
    decision = core.decide_mode(conn, submittal, kind.kind, kind.known)
    accepted, problems = core.check_project_papers(
        conn, submittal, requested_papers(conn, run_id), scope
    )
    refused = preflight(
        decision, problems, agent_review_schema.shape_problem(conn), local is not None
    )
    if refused:
        return _finish(
            conn,
            run_id=run_id,
            submittal=submittal,
            kind=kind,
            started=started,
            folder=folder,
            g=None,
            accepted=[],
            stop=f"refused: {refused}",
            name=name,
            combined=combined,
        )
    g, runner, carrier = _build(
        conn, run_id, submittal, kind, decision, accepted, folder, lane, local
    )
    try:
        _run_parts(g, runner, carrier, local, run_id, heartbeat)
    except BaseException as exc:
        if not g.stopped:
            g.stopped = request_mod.stop_reason(exc, runner.last_app_worst)[0]
        raise
    finally:
        done = _finish(
            conn,
            run_id=run_id,
            submittal=submittal,
            kind=kind,
            started=started,
            folder=folder,
            g=g,
            accepted=accepted,
            stop="",
            name=name,
            combined=combined,
        )
        log.info(
            "agent general review written: %d lines", done["counts"].get("lines", 0)
        )
    return done
