"""#1525: one machine-written audit file per review run (`AUDIT.md` + `AUDIT.json`).

The owner asked (1 Nov 2026) for a report that tells everything about a review:
which pages were read, which standards and rules were compared, where the AI
was used. EXPORT ONLY: this reads what the finished run stored (the same
inputs as the stored trace, `review_trace.build`) and writes two local files.
It decides nothing and changes no verdict.

Rules it keeps (CLAUDE.md rule 4):
- every count states its boundary: the documents the requester may read, and
  the denominator where there is one (pages total, clauses read of total);
- a figure the run did not record reads "not recorded" (None in the JSON),
  never 0;
- no document text: page and clause numbers, field labels and the quote
  snippets the CRS itself shows. The text of pages and standards is never copied.

Local files only: never pushed, never in CI. OFF by default
(`REVIEW_AUDIT_REPORT_ENABLED`). A failure here never breaks a review.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import (
    ai_call_ledger,
    deferred_pass,
    presence_check,
    review_audit_detail,
    review_audit_rows,
)
from .config import settings

NOT_RECORDED = "not recorded"
PKT = timedelta(hours=5)
BOUNDARY = (
    "Counts are over the documents the requester may read, for this one review run; "
    "a figure the run did not store is shown as 'not recorded', never as 0."
)
#: The plain verdict names (the bench's words) for the stored compliance codes.
VERDICT = {
    presence_check.STATUS: presence_check.WORDS,
    "COMPLIANT": "Pass",
    "NON_COMPLIANT": "Fail",
    "MISSING_INFORMATION": "Query",
    "NEEDS_ENGINEER_REVIEW": "engineer",
    "NOT_APPLICABLE": "not in scope",
    "NOT_IN_DOCUMENT_SCOPE": "needs other document",
}
#: What the AI totals are over, printed with them (CLAUDE.md rule 4).
AI_BOUNDARY = (
    "Answers asked for or reused during this attempt of this review job, over the steps "
    "listed with a record. A reused answer is a stored answer: no model was asked, and it "
    "is never counted as a fresh call. A refused or failed call is not fresh: on a step "
    "counted during the job it is counted as failed (a timeout, a refusal, any error). "
    "clause_review's and ai_engineering_check's stored counts are calls attempted, failed "
    "ones included, so their failed count is not recorded. "
    "Field naming counts one answer per named item. Not counted: reading done when the "
    "document was added, and steps that keep no count of their own: rule_eval, "
    "statement_roles, field_vocabulary, vision_reader and the matcher's Claude path."
)


def audit_root() -> Path:
    """`REVIEW_AUDIT_DIR`, else `~/project/mirror/proof`."""
    default = Path("~/project/mirror/proof").expanduser()
    if not settings.review_audit_dir:
        return default
    chosen = Path(settings.review_audit_dir).expanduser().resolve()
    for fenced in (
        Path(__file__).resolve().parents[2],
        Path(settings.data_dir).resolve(),
    ):
        if chosen == fenced or fenced in chosen.parents:
            logging.getLogger(__name__).warning(
                "REVIEW_AUDIT_DIR is inside the repository or the data folder; using the default"
            )
            return default
    return chosen


def _pkt(stamp: str | None) -> str | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (when + PKT).strftime("%Y-%m-%d %H:%M:%S PKT")


def _seconds(start: str | None, end: str | None) -> float | None:
    try:
        a, b = datetime.fromisoformat(start or ""), datetime.fromisoformat(end or "")
    except ValueError:
        return None
    if (a.tzinfo is None) != (b.tzinfo is None):
        return None
    return round((b - a).total_seconds(), 1)


def _loads(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _run_section(run: dict, sub: str, filename, steps: dict, ai_use: dict) -> dict:
    from . import document_kind, review_jobs
    from .db import connect

    kind = None
    try:
        stored = document_kind.stored_kind(sub)
    except Exception:  # noqa: BLE001 - the table may not exist; the kind is then not recorded
        stored = None
    if stored:
        row = (
            connect()
            .execute(
                "SELECT evidence FROM document_kinds WHERE document_id = ?", (sub,)
            )
            .fetchone()
        )
        evidence = _loads(row["evidence"]) if row else {}
        kind = {
            "kind": stored[0],
            "state": stored[1],
            "page": evidence.get("page"),
            "cue": evidence.get("cue") or evidence.get("rule"),
        }
    ai = _loads(run.get("ai_check_status"))
    # `model_name`: the Claude models that answered up to the end of the comparison,
    # comma-joined (`claude_models.record_run`). NULL: none answered by then. The AI check
    # runs AFTER it, so its model is not in `model_name` and is taken from `ai` here.
    models = sorted(
        {
            m
            for m in (
                *(run.get("model_name") or "").split(", "),
                ai.get("model"),
                *(s.get("model") for s in ai_use["steps"]),
            )
            if m
        }
    )
    switches = sorted(
        name
        for name in type(settings).model_fields
        if name.endswith("_enabled") and getattr(settings, name) is True
    )
    return {
        "id": run["id"],
        "document_id": sub,
        "document_title": filename,
        "kind_decided": kind,
        "equipment_type": steps["EQUIPMENT"]["summary"]
        .split("|")[0]
        .replace("type:", "")
        .strip(),
        "started_pkt": _pkt(run.get("started_at") or run.get("created_at")),
        "finished_pkt": _pkt(run.get("completed_at")),
        "seconds": _seconds(
            run.get("started_at") or run.get("created_at"), run.get("completed_at")
        ),
        "code_version": review_jobs.review_code_version(),
        "switches_on": switches,
        "models_used": models or None,
        "ai_calls_made": ai_use["totals"]["fresh"],
        "ai_calls_failed": ai_use["totals"]["failed"],
        "ai_calls_refused": review_audit_detail.calls_refused(ai_use),
        "ai_answers_reused": ai_use["totals"]["reused"],
        "started_by": run.get("started_by"),
        "status": run.get("status"),
    }


def _pages_section(sub: str) -> dict:
    from . import page_ledger, page_not_read

    rows = page_ledger.rows(sub)
    if not rows:
        return {
            "total": None,
            "read_text": None,
            "read_picture": None,
            "not_read": None,
            "per_page": None,
        }
    per_page, not_read, text, picture = [], [], 0, 0
    for r in rows:
        read_text = r["native_status"] == "text"
        read_pic = r["ocr_status"] == "done"
        text += read_text
        picture += (not read_text) and read_pic
        entry = {
            "page": r["page_no"],
            "native": r["native_status"],
            "ocr": r["ocr_status"],
            "index": r["index_status"],
            "facts": r["facts_status"],
        }
        reason = str(r["index_reason"] or "")
        if reason.startswith("page_classified_"):
            entry["rule"] = reason.split(",")[0]
        if not (read_text or read_pic):
            why = page_not_read.unread_page_words(r)
            entry["not_read_reason"] = why
            not_read.append({"page": r["page_no"], "reason": why})
        per_page.append(entry)
    from . import reading_state, word_pages

    extra = {}
    if (word_read := word_pages.read_proof(sub)) is not None:
        extra["word_read"] = word_read
    # A picture reader's text goes on its page, so "pages read only by OCR" says 0 while
    # pictures came back: count pictures, from the one function "ready" reads.
    if (counts := reading_state.picture_counts(sub)) is not None:
        picture, extra["pictures_total"] = counts
    return {
        "total": len(rows),
        "read_text": text,
        "read_picture": picture,
        "not_read": not_read,
        "per_page": per_page,
        **extra,
    }


def _deferred_part(findings: list[dict], passes: int) -> dict:
    """D2: Passes on a contractor-deferred value are Query - counted as the bench does."""
    n = sum(map(deferred_pass.is_deferred_pass, findings))
    return {
        "pass_on_deferred": n,
        "pass_on_deferred_note": f"{n} of {passes} Pass rows are on a contractor-deferred value"
        + (" (Query under owner decision D2)" if n else ""),
    }


def _rules_section(
    findings: list[dict], allowed=frozenset(), equipment: str | None = None
) -> dict:
    counts = Counter(presence_check.status_of(f) for f in findings)  # #1638
    rows = review_audit_detail.rule_rows(findings, allowed, equipment)
    return {
        "rows_total": len(rows),
        "rows": rows,
        "verdict_counts": {VERDICT.get(k, k): v for k, v in counts.items() if k},
        **_deferred_part(presence_check.split(findings)[0], counts.get("COMPLIANT", 0)),
        "in_scope_by_standard": review_audit_detail.in_scope_by_standard(findings),
    }


def _ledger_steps(ledger: list[dict] | None) -> list[dict]:
    """The steps `ai_call_ledger` counted. None: this report was not written by
    the job itself, so what those steps did is not recorded (never 0)."""
    if ledger is None:
        return [
            {
                "name": "steps counted only during the job",
                "state": NOT_RECORDED,
                "model": None,
                "calls": None,
                "fresh": None,
                "failed": None,
                "reused": None,
            }
        ]
    return [
        {
            "name": row["step"],
            "state": "completed",
            "model": row["model"],
            "calls": row["fresh"],
            "fresh": row["fresh"],
            "failed": row["failed"],
            "reused": row["reused"],
            **review_audit_rows.not_sent(row),
        }
        for row in ledger
    ]


def _stored_steps(status: dict, wording: dict | None) -> list[dict]:
    """The steps whose own stored status counts their calls: the clause review
    (with its stored answers) and the CRS wording (stored Claude answers: `fold_stored_hits`)."""
    from .clause_review import STATUS_KEY

    out = []
    clause = status.get(STATUS_KEY)
    if isinstance(clause, dict):
        out.append(
            {
                "name": "clause_review",
                "state": "completed" if clause.get("ran") else NOT_RECORDED,
                "model": clause.get("model"),
                "calls": clause.get("calls"),
                "fresh": clause.get("calls"),
                "reused": clause.get("cache_hits"),
                **review_audit_detail.clause_figures(clause),
            }
        )
    if wording and wording.get("enabled"):
        tried = wording.get("tried")
        out.append(
            {
                "name": "crs_wording",
                "state": "stopped" if wording.get("stopped") else "completed",
                "model": wording.get("model"),
                "calls": tried,
                "fresh": tried,
                "reused": None if tried is None else 0,
            }
        )
    return out


def _totals(steps: list[dict]) -> dict:
    return {
        field: (
            sum(known)
            if (known := [s[field] for s in steps if s.get(field) is not None])
            else None
        )
        for field in ("fresh", "reused", "failed")
    } | {"boundary": AI_BOUNDARY}


def _ai_section(
    run: dict,
    timings: dict,
    *,
    ledger: list[dict] | None = None,
    wording: dict | None = None,
) -> dict:
    raw = run.get("ai_check_status")
    status = _loads(raw)
    if not raw:
        step = {"state": NOT_RECORDED, "model": None, "calls": None}
    else:
        ran, complete = status.get("ran"), status.get("complete")
        step = {
            "state": (
                "failed"
                if ran is False or complete is False or status.get("error")
                else "completed"
                if ran
                else NOT_RECORDED
            ),
            "model": status.get("model"),
            "calls": status.get("calls_made"),
            "reason": status.get("reason"),
            "proposed": status.get("proposed_items"),
            "kept": status.get("kept_items"),
            "rejected": status.get("rejected"),
        }
    step["name"] = "ai_engineering_check"
    # Stored Claude answers are moved here by `fold_stored_hits`; otherwise a true 0.
    step["fresh"] = step["calls"]
    step["reused"] = None if step["calls"] is None else 0
    step["clauses_read_of_total"] = NOT_RECORDED
    step["quotes_verified_of_total"] = NOT_RECORDED
    step["unverified_quotes_dropped"] = status.get("rejected") if raw else None
    step["seconds"] = (timings.get("checks") or {}).get("seconds") if timings else None
    step["effect_on_verdicts"] = (
        review_audit_detail.FAILED_NO_WORSE
        if step["state"] == "failed"
        else "see the findings; code decides"
    )
    figures = review_audit_rows.run_figures(run)
    own = [step, *_stored_steps(status, wording)]
    ledger = review_audit_rows.fold_stored_hits(own, ledger, figures)
    steps = [
        *own,
        *_ledger_steps(ledger),
        *review_audit_rows.skipped_steps(_loads(run.get("outcome_json"))),
    ]
    outcome = _loads(run.get("outcome_json"))
    return {
        "steps": steps,
        "totals": _totals(steps),
        **figures,
        "matcher": review_audit_detail.matcher_figures(outcome),
        "phase_seconds": review_audit_detail.phase_seconds(run["id"], timings),
    }


def _crs_section(review_run_id: str, scope, steps: dict) -> dict:
    crs = steps["CRS"]
    parts = {
        copy: review_audit_rows.for_copy(review_run_id, scope, copy)
        for copy in ("internal", "issue")
    }
    internal = parts["internal"] or {}
    return {
        "rows_composed": internal.get("audit_rows"),
        "rows_exported": internal.get("exported_rows"),
        "missed_standard_rows": internal.get("missed_standard_rows"),
        "rows_dropped": internal.get("removed"),
        "rows_boundary": review_audit_rows.ROWS_BOUNDARY,
        "reconciliation": parts,
        **review_audit_detail.crs_paths(review_run_id),
        "failed": crs.get("status") == "failed" or parts["internal"] is None,
    }


def _known_gaps() -> dict:
    """Entries of the honesty audit that name a switch which is OFF in this run."""
    path = Path(__file__).resolve().parents[2] / "docs" / "status-honesty-audit.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"entries": None, "note": NOT_RECORDED}
    gaps = []
    for entry in re.split(r"\n(?=- \*\*A-)", text):
        head = re.match(r"- \*\*(A-[0-9]+[a-z]?)\b", entry)
        if not head:
            continue
        for name in sorted(set(re.findall(r"`([a-z0-9_]+_enabled)`", entry))):
            if getattr(settings, name, None) is False:
                gaps.append({"id": head.group(1), "switch_off": name})
    return {
        "entries": gaps,
        "note": "Audit entries that name a switch which is off in this run; not a "
        "claim that this run was affected.",
    }


def build(review_run_id: str, scope, timings: dict | None = None) -> dict:
    """The run's audit, read from what it stored, under the caller's grants."""
    from . import comparison, review_trace, submittal_review

    allowed = scope.allowed_document_ids
    run = submittal_review.get_review_run(review_run_id, allowed_document_ids=allowed)
    if run is None:
        return {"run": {"id": review_run_id}, "error": "run not readable"}
    trace = review_trace.build(review_run_id, scope)
    steps = {s["step"]: s for s in trace["steps"]}
    outcome = comparison.run_outcome(review_run_id, allowed_document_ids=allowed) or {}
    findings = submittal_review.list_run_findings(
        review_run_id, allowed_document_ids=allowed
    )
    sub = run["submittal_document_id"]
    from . import crs_wording

    ai_use = _ai_section(
        run,
        timings or {},
        ledger=ai_call_ledger.snapshot(),
        wording=crs_wording.summary_of(review_run_id),
    )
    run_part = _run_section(run, sub, trace.get("document"), steps, ai_use)
    counts = review_audit_detail.bench_counts(run, findings, outcome)
    rules = _rules_section(findings, allowed, run_part["equipment_type"])
    return {
        "boundary": BOUNDARY,
        "run": run_part,
        "pages": _pages_section(sub),
        "standards": review_audit_detail.standards_section(
            review_run_id, outcome, allowed
        ),
        "rules": {**rules, "bench_counts": counts},
        "ai_use": ai_use,
        "gates": review_audit_detail.gates_section(
            run, outcome, findings, counts, steps
        ),
        "crs": _crs_section(review_run_id, scope, steps),
        "retractions_and_gaps": _known_gaps(),
    }


def _v(value) -> str:
    return NOT_RECORDED if value is None else str(value)


def _md_run(audit: dict) -> list[str]:
    run = audit["run"]
    kind = run.get("kind_decided")
    return [
        f"# Review audit {run['id']}",
        "",
        f"_{audit['boundary']}_",
        "",
        "## 1. Run",
        f"- run: {run['id']}",
        f"- document: {_v(run['document_id'])} ({_v(run['document_title'])})",
        "- kind decided: "
        + (
            f"{kind['kind']} ({kind['state']}; page {_v(kind['page'])}, cue {_v(kind['cue'])})"
            if kind
            else NOT_RECORDED
        ),
        f"- equipment type: {_v(run['equipment_type'])}",
        f"- started: {_v(run['started_pkt'])}; finished: {_v(run['finished_pkt'])}; "
        f"seconds: {_v(run['seconds'])}",
        f"- code: {run['code_version']}",
        f"- switches on: {', '.join(run['switches_on']) or 'none'}",
        f"- models used: {', '.join(run['models_used']) if run['models_used'] else NOT_RECORDED}",
        f"- AI calls made (fresh): {_v(run['ai_calls_made'])}; failed calls: "
        f"{_v(run['ai_calls_failed'])}; refused calls: {_v(run['ai_calls_refused'])}; "
        f"stored answers reused: {_v(run['ai_answers_reused'])}",
        f"  - {AI_BOUNDARY}",
        f"- started by: {_v(run['started_by'])}",
        f"- status: {_v(run['status'])}",
        "",
    ]


def _md_pages(audit: dict) -> list[str]:
    pages = audit["pages"]
    out = [
        "## 2. Pages",
        f"- pages in the document: {_v(pages['total'])}",
        f"- read (text): {_v(pages['read_text'])}; read (picture): {_v(pages['read_picture'])}"
        + (
            f" of {_v(pages['pictures_total'])} pictures"
            if "pictures_total" in pages
            else ""
        ),
    ]
    if pages["not_read"] is None:
        out.append(f"- not read: {NOT_RECORDED}")
    else:
        out.append(f"- not read: {len(pages['not_read'])} of {pages['total']}")
        out += [f"  - {_page_of(p, pages)}: {p['reason']}" for p in pages["not_read"]]
    out += [
        f"- {_page_of(p, pages)}: rule {p['rule']}"
        for p in (pages["per_page"] or [])
        if p.get("rule")
    ]
    if pages.get("word_read"):
        out += _md_word_read(pages["word_read"])
    return [*out, ""]


def _page_of(row: dict, pages: dict) -> str:
    """A ledger row's page; a part of a Word file with no pages names no number."""
    from . import word_pages

    source = (pages.get("word_read") or {}).get("page_source")
    if source in word_pages.NO_REAL_PAGE:
        return f"a part with {word_pages.NO_PAGE_SHORT}"
    return f"page {row['page']}"


def _md_word_read(word: dict) -> list[str]:
    """A Word file's own count against what reached the reader (rule 4: a picture
    with no text back is not read; a part is not a page)."""
    from . import word_pages

    saved = word["word_saved_pages"]
    out = [
        f"- Word page numbers: {word['page_source']} ({word['saved_markers']} saved marks, "
        f"{word['typed_breaks']} typed breaks, Word saved {_v(saved)} pages, "
        f"marks reach {'no page: none available' if word['pages'] is None else word['pages']})",
        f"- tables in the file: {word['tables_in_file']}; read: {word['tables_read']}",
        f"- pictures in the file: {word['pictures_in_file']}; with a reading: "
        f"{word['pictures_read']}; in headers and footers, not sent: {word['furniture_pictures']}",
    ]
    out += [
        f"  - {n['kind']} not read, {word_pages.place(n)}: {n['reason']}"
        for n in word["not_read"]
    ]
    return out


def _md_rules(audit: dict) -> list[str]:
    rules = audit["rules"]
    out = [
        "## 4. Rules",
        f"- rules compared: {rules['rows_total']}",
        "- verdicts: "
        + (
            ", ".join(
                f"{k} {v} of {rules['rows_total']}"
                for k, v in rules["verdict_counts"].items()
            )
            or NOT_RECORDED
        ),
        f"- {rules['pass_on_deferred_note']}",
        *review_audit_detail.md_bench_counts(rules["bench_counts"]),
        "",
        "| clause | field | value read | page | limit | comparator | verdict | basis "
        "| quote | card | approval |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rules["rows"]:
        out.append(
            "| "
            + " | ".join(
                _cell(x)
                for x in (
                    r["standard_clause"],
                    r["field"],
                    r["value_read"],
                    r["page"],
                    r["limit"],
                    r["comparator"],
                    r["verdict"],
                    r["basis"],
                    r["evidence_quote_id"],
                    r["kit_card_id"],
                    r["kit_card_approval"],
                )
            )
            + " |"
        )
    return [*out, ""]


def _md_ai(audit: dict) -> list[str]:
    totals = audit["ai_use"]["totals"]
    out = [
        "## 5. AI use",
        f"- fresh calls {_v(totals['fresh'])}; failed calls {_v(totals['failed'])}; "
        f"reused answers {_v(totals['reused'])}",
        f"  - {totals['boundary']}",
    ]
    out += review_audit_rows.claude_lines(audit["ai_use"])
    out += review_audit_detail.md_ai_extra(audit["ai_use"])
    for s in audit["ai_use"]["steps"]:
        out.append(
            f"- {s['name']}: {s['state']}; model {_v(s['model'])}; fresh calls "
            f"{_v(s['fresh'])}; failed calls {_v(s.get('failed'))}; reused answers "
            f"{_v(s['reused'])}"
        )
        out += [f"  - {s['not_sent']}"] if s.get("not_sent") else []
        if "clauses_read_of_total" not in s:
            continue
        out[-1] += (
            f"; clauses read of total {s['clauses_read_of_total']}; quotes verified of total "
            f"{s['quotes_verified_of_total']}; unverified quotes dropped "
            f"{_v(s['unverified_quotes_dropped'])}; seconds {_v(s['seconds'])}"
        )
        out.append(f"  - effect on verdicts: {s['effect_on_verdicts']}")
        if s.get("reason"):
            out.append(f"  - reason: {s['reason']}")
    return [*out, ""]


def _md_gates_crs(audit: dict) -> list[str]:
    crs = audit["crs"]
    return [
        *review_audit_detail.md_gates(audit["gates"]),
        "",
        "## 7. CRS",
        f"- rows exported (internal copy): {_v(crs['rows_exported'])}",
        f"- missed-standard rows (internal copy): {_v(crs['missed_standard_rows'])}",
        *(
            f"- {copy} copy: {part['line'] if part else NOT_RECORDED}"
            for copy, part in crs["reconciliation"].items()
        ),
        f"  - {crs['rows_boundary']}",
        f"- client copy: {crs['client_copy_path']}; internal copy: {crs['internal_copy_path']}",
        "",
    ]


def render_markdown(audit: dict) -> str:
    gaps = audit["retractions_and_gaps"]
    out = [
        f"# Review audit {audit['run']['id']}",
        "",
        f"_{audit['boundary']}_",
        "",
        *_md_run(audit),
        *_md_pages(audit),
        *review_audit_detail.md_standards(audit["standards"]),
        *_md_rules(audit),
        *_md_ai(audit),
        *_md_gates_crs(audit),
        "## 8. Retractions and known gaps",
        f"- {gaps['note']}",
    ]
    out += [
        f"  - {g['id']} (switch {g['switch_off']} is off)"
        for g in gaps["entries"] or []
    ]
    return "\n".join(out) + "\n"


def _cell(value) -> str:
    return (
        NOT_RECORDED
        if value in (None, "", [])
        else str(value).replace("|", "/").replace("\n", " ")
    )


def _record_path(review_run_id: str, folder: Path) -> None:
    """Keep the audit folder in the run's stored trace (`audit_path`); a run that ended
    before it stored a trace keeps it in its outcome."""
    from . import review_trace
    from .db import connect

    review_trace.ensure_schema()
    conn = connect()
    row = conn.execute(
        "SELECT trace FROM review_run_traces WHERE review_run_id = ?", (review_run_id,)
    ).fetchone()
    if row is None:
        stored = conn.execute(
            "SELECT outcome_json FROM review_runs WHERE id = ?", (review_run_id,)
        ).fetchone()
        outcome = {**_loads(stored["outcome_json"]), "audit_path": str(folder)}
        with conn:
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                (json.dumps(outcome), review_run_id),
            )
        return
    trace = _loads(row["trace"])
    trace["audit_path"] = str(folder)
    with conn:
        conn.execute(
            "UPDATE review_run_traces SET trace = ? WHERE review_run_id = ?",
            (json.dumps(trace), review_run_id),
        )


def write(review_run_id: str, scope, timings: dict | None = None) -> Path | None:
    """Write AUDIT.md and AUDIT.json for the run; None when the switch is off or
    anything failed (never raises: an audit never breaks or changes a review)."""
    if not settings.review_audit_report_enabled:
        return None
    try:
        audit = build(review_run_id, scope, timings)
        markdown = render_markdown(audit)
        folder = audit_root() / f"{datetime.now(UTC) + PKT:%Y-%m-%d}-{review_run_id}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "AUDIT.md").write_text(markdown, encoding="utf-8")
        (folder / "AUDIT.json").write_text(
            json.dumps(audit, indent=2, default=str), encoding="utf-8"
        )
        _record_path(review_run_id, folder)
        logging.getLogger(__name__).info(
            "review audit written for run %s", review_run_id
        )
        return folder
    except Exception:
        logging.getLogger(__name__).warning(
            "review audit not written for run %s", review_run_id, exc_info=True
        )
        return None
