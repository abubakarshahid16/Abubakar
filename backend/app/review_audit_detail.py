"""#1525: the parts of the audit report that read further than the run's own row: the
gates, a rule row's limit and approval, the standards' split and editions, the clause
review's figures, the CRS copies' paths and the bench's counts (`run_measures`).

Export only, behind REVIEW_AUDIT_REPORT_ENABLED like the rest of `review_audit`. It reads
and counts; it decides nothing. What the run did not store stays None ("not recorded"),
never 0. General for every document: nothing here knows a layout or a sheet.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from . import (
    ai_call_ledger,
    cited_edition,
    claude_spend_report,
    coverage_pair,
    crs_export_quality,
    crs_issue,
    datasheet_checks,
    run_measures,
)
from .config import settings
from .db import connect

NOT_RECORDED = "not recorded"
NOT_ISSUED = "not issued"
FAILED_NO_WORSE = (
    "none: a failed step adds no finding and no verdict is more confident because of it"
)
SUGGESTIONS_ONLY = "suggestions only: an engineer confirms; no verdict comes from it"
TRUTH = Path(__file__).resolve().parents[2] / "eval" / "bench" / "truth.json"
BENCH_BOUNDARY = (
    "Counted by the one function the CRS bench reads (`run_measures.headline`), over the "
    "findings the requester may read. wrong and untrue exist only for a run named in the "
    "bench's truth file."
)
_AI_ORIGINS = ("ai_engineering_check", "web_standard_check", "clause_review")


def truth_case(review_run_id: str) -> dict | None:
    """This run's entry in the bench's truth file; None when the run or the file is not there."""
    try:
        cases = json.loads(TRUTH.read_text(encoding="utf-8"))["cases"]
    except (OSError, ValueError, KeyError):
        return None
    return next((c for c in cases if c.get("run") == review_run_id), None)


def bench_counts(run: dict, findings: list[dict], outcome: dict) -> dict:
    case = truth_case(run["id"])
    counts = run_measures.headline(
        connect(), run["submittal_document_id"], outcome, findings, case
    )
    return {**counts, "boundary": BENCH_BOUNDARY}


# ------------------------------------------------------------------ section 3


def standards_section(run_id: str, outcome: dict, allowed) -> dict:
    conn = connect()
    applied = [
        {
            "filename": r["filename"],
            "method": r["selection_method"],
            "edition": cited_edition.held_year({"filename": r["filename"]}),
        }
        for r in conn.execute(
            "SELECT d.filename, a.selection_method, a.standard_document_id"
            " FROM review_applicable_standards a JOIN documents d ON d.id = a.standard_document_id"
            " WHERE a.review_run_id = ? AND a.included = 1 ORDER BY d.filename",
            (run_id,),
        )
        if r["standard_document_id"] in allowed
    ]
    considered = conn.execute(
        "SELECT COUNT(*) AS n FROM review_applicable_standards"
        " WHERE review_run_id = ? AND included = 0",
        (run_id,),
    ).fetchone()
    missing = outcome.get("missing_references")
    return {
        "applied_count": len(applied),
        "applied_boundary": "of standards you may read",
        "applied": applied,
        "applied_by_method": dict(Counter(a["method"] for a in applied)),
        "considered_not_applied_count": considered["n"] if considered else None,
        "cited_not_in_library_count": None if missing is None else len(missing),
        "cited_not_in_library_split": None if missing is None else _split(missing),
        "editions_printed": sum(a["edition"] is not None for a in applied),
    }


def _split(missing: list) -> dict:
    kinds = (
        crs_export_quality.KIND_DESIGN,
        crs_export_quality.KIND_MATERIAL,
        crs_export_quality.KIND_PURCHASING,
    )
    names = [m if isinstance(m, str) else (m or {}).get("identifier") for m in missing]
    found = Counter(crs_export_quality.standard_kind(n) for n in names)
    return {kind: found[kind] for kind in kinds}


def md_standards(std: dict) -> list[str]:
    methods = ", ".join(f"{k} {v}" for k, v in std["applied_by_method"].items())
    cited = std["cited_not_in_library_count"]
    split = std["cited_not_in_library_split"]
    return [
        "## 3. Standards",
        f"- applied: {std['applied_count']} {std['applied_boundary']} "
        f"({methods or 'no method recorded'})",
        *[
            f"  - {a['filename']} ({a['method']}; edition {a['edition'] or NOT_RECORDED})"
            for a in std["applied"]
        ],
        f"- considered, not applied: {_v(std['considered_not_applied_count'])}",
        f"- cited, not in library: {_v(cited)}"
        + (
            f" (design {split['design']}, material {split['material']}, "
            f"purchasing {split['purchasing']})"
            if split
            else ""
        ),
        f"- editions: {std['editions_printed']} of {std['applied_count']} applied "
        "standards print a year in their name; the year is what the name prints, "
        "nothing else is read",
        "",
    ]


# ------------------------------------------------------------------ section 4


def checklist_limit(rule: dict) -> tuple[str | None, str | None]:
    """(limit, comparator) of an approved checklist rule, in the rule's own terms."""
    kind = rule.get("kind")
    if kind == "required":
        return "a value stated", "required"
    if kind == "allowed":
        return ", ".join(map(str, rule.get("values") or [])), "one of"
    if kind == "compare":
        return rule.get("right"), rule.get("op")
    if kind == "constant":
        return f"{rule.get('value')} {rule.get('unit') or ''}".strip(), rule.get("op")
    if kind == "percent_of":
        return f"{rule.get('percent')}% of {rule.get('right')}", rule.get("op")
    if kind == "above_by":
        return (
            f"{rule.get('right')}: {rule.get('percent')}%, at least "
            f"{rule.get('at_least')} {rule.get('unit') or ''}".strip(),
            "above by",
        )
    if kind == "calc":
        return rule.get("formula"), "calculated"
    return None, None


def _stored_rules(findings: list[dict], allowed) -> dict[str, dict]:
    ids = sorted({f["requirement_id"] for f in findings if f.get("requirement_id")})
    rules: dict[str, dict] = {}
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        marks = ",".join("?" * len(part))
        for row in connect().execute(
            "SELECT id, standard_document_id, operator, value, unit, raw_value,"
            f" raw_unit, confirmed_by FROM standard_requirements WHERE id IN ({marks})",
            part,
        ):
            if row["standard_document_id"] in allowed:
                rules[row["id"]] = dict(row)
    return rules


def _checklist_items(equipment_type: str | None) -> dict[str, dict]:
    rules = datasheet_checks.load_rules()
    items = {
        item["id"]: item
        for entry in (rules.get("checklists") or {}).values()
        if isinstance(entry, dict)
        for item in entry.get("items", [])
    }
    try:
        own = datasheet_checks.checklist_for(equipment_type, rules)
    except ValueError:
        own = None
    return {**items, **{i["id"]: i for i in (own or {}).get("items", [])}}


def _stored_limit(rule: dict) -> str | None:
    value = rule["raw_value"] if rule["raw_value"] is not None else rule["value"]
    if value is None:
        return None
    return f"{value} {rule['raw_unit'] or rule['unit'] or ''}".strip()


def _basis(finding: dict) -> str:
    from .comparison import METHOD_ASKED, METHOD_FIELD_NAME, METHOD_MODEL_CHOICE

    origin = finding.get("origin")
    if origin == "chat":
        return "engineer"
    method = str(finding.get("match_method") or "")
    by_model = method in (METHOD_ASKED, METHOD_FIELD_NAME, METHOD_MODEL_CHOICE)
    return (
        "AI-suggested"
        if origin in _AI_ORIGINS or by_model or method.startswith("ai")
        else "code"
    )


def _checklist_approval(finding: dict) -> str:
    if datasheet_checks.is_draft_checklist(finding.get("requirement_source_text")):
        return "draft, not signed off"
    return finding.get("trust_label") or "signed-off checklist"


def rule_rows(findings: list[dict], allowed, equipment_type: str | None) -> list[dict]:
    """One row per finding; a limit only where a rule or a checklist item states it."""
    from .review_audit import VERDICT

    stored = _stored_rules(findings, allowed)
    items = _checklist_items(equipment_type)
    rows = []
    for f in findings:
        rule, check = stored.get(f.get("requirement_id")), coverage_pair._check_id(f)
        limit, comparator, approval = None, None, None
        if rule is not None:
            limit, comparator = _stored_limit(rule), rule["operator"]
            approval = (
                "engineer confirmed"
                if rule["confirmed_by"]
                else f.get("trust_label") or "not confirmed"
            )
        elif check is not None:
            item = items.get(check)
            if item is not None:
                limit, comparator = checklist_limit(item.get("rule") or {})
            approval = _checklist_approval(f)
        status = f.get("compliance_status")
        rows.append(
            {
                "finding_id": f["id"],
                "standard_clause": f.get("standard_clause"),
                "field": f.get("matched_phrase") or f.get("contractor_section"),
                "value_read": f.get("contractor_evidence_text"),
                "page": f.get("contractor_page"),
                "limit": limit,
                "comparator": comparator,
                "verdict": VERDICT.get(status, status or None),
                "evidence_quote_id": f.get("citation_ids") or None,
                "basis": _basis(f),
                "kit_card_id": f.get("requirement_id") or check,
                "kit_card_approval": approval,
            }
        )
    return rows


def in_scope_by_standard(findings: list[dict]) -> dict[str, int]:
    """Rules in scope per standard: by file name, the standards' id where the file is gone."""
    in_scope = [
        f
        for f in findings
        if f.get("standard_document_id")
        and f.get("compliance_status") != run_measures.NOT_IN_SCOPE
    ]
    ids = sorted({f["standard_document_id"] for f in in_scope})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    names = {
        r["id"]: r["filename"]
        for r in connect().execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", ids
        )
    }
    found = Counter(
        names.get(f["standard_document_id"], f["standard_document_id"])
        for f in in_scope
    )
    return dict(found)


def md_bench_counts(counts: dict) -> list[str]:
    return [
        "- as the bench counts them:",
        f"  - checklist decided: {counts['checklist_decided']} of {counts['checklist_total']}",
        f"  - rules decided: {counts['rules_decided']} of {counts['rules_in_scope']} in scope",
        f"  - quotes verified: {counts['quotes_verified']} of {counts['quotes_total']}",
        f"  - pages read: {_v(counts['pages_read'])} of {_v(counts['pages_total'])}",
        f"  - {counts['boundary']}",
    ]


# ------------------------------------------------------------------ section 5


def clause_figures(clause: dict) -> dict:
    """The clause review's own stored counts, with their denominators."""
    outcomes = ("verified", "no_evidence", "unverified", "unreadable")
    total = clause.get("requirements")
    known = total is not None and all(clause.get(k) is not None for k in outcomes)
    read = sum(clause[k] for k in outcomes) if known else None
    quoted = clause["verified"] + clause["unverified"] if known else None
    failed = bool(clause.get("failed"))
    return {
        "clauses_read_of_total": f"{read} of {total}" if known else NOT_RECORDED,
        "quotes_verified_of_total": (
            f"{clause['verified']} of {quoted}" if known else NOT_RECORDED
        ),
        "unverified_quotes_dropped": clause.get("unverified"),
        "seconds": clause.get("elapsed_seconds"),
        "effect_on_verdicts": FAILED_NO_WORSE if failed else SUGGESTIONS_ONLY,
        **(
            {"state": "failed"}
            if failed
            else {"state": "stopped"}
            if clause.get("stopped") and clause.get("not_reviewed")
            else {}
        ),
    }


def matcher_figures(outcome: dict) -> dict | None:
    matcher = outcome.get("ai_matcher")
    if not matcher:
        return None
    return {**matcher, "model_calls": outcome.get("model_calls")}


def phase_seconds(review_run_id: str, timings: dict | None) -> dict | None:
    """Seconds per phase: the job's own clock, else what its stored trace kept."""
    if timings:
        found = {k: (v or {}).get("seconds") for k, v in timings.items()}
        return {k: v for k, v in found.items() if v is not None} or None
    try:
        row = (
            connect()
            .execute(
                "SELECT trace FROM review_run_traces WHERE review_run_id = ?",
                (review_run_id,),
            )
            .fetchone()
        )
    except sqlite3.OperationalError:  # the table may not exist; not recorded
        return None
    if row is None:
        return None
    from .review_trace import PHASE_OF

    out = {}
    for step in json.loads(row["trace"]).get("steps", []):
        seconds = (step.get("timing") or {}).get("seconds")
        if seconds is not None:
            out[PHASE_OF.get(step.get("step"), step.get("step"))] = seconds
    return out or None


def calls_refused(ai_use: dict) -> int | None:
    spend = ai_use.get(claude_spend_report.OUTCOME_KEY) or {}
    return spend.get("refused")


def md_ai_extra(ai_use: dict) -> list[str]:
    matcher, phases = ai_use.get("matcher"), ai_use.get("phase_seconds")
    out = []
    if matcher and matcher.get("enabled"):
        out.append(
            f"- matcher (not in the totals): {_v(matcher.get('asked'))} asked of "
            f"{_v(matcher.get('sent'))} sent; {_v(matcher.get('used'))} used; model "
            f"{_v(matcher.get('model'))}; model calls {_v(matcher.get('model_calls'))}"
        )
    words = ", ".join(f"{k} {v} s" for k, v in (phases or {}).items())
    out.append(f"- time per phase: {words or NOT_RECORDED}")
    return out


# ------------------------------------------------------------------ section 6


def _nothing_read_gate(run: dict, outcome: dict) -> dict:
    """Fired: seen on the stored run, whenever this is written. Not fired: only the job
    itself knows the switch was on, so a re-export says not recorded."""
    gate = {
        "gate": "nothing-read guard",
        "rule_id": "#1495 NOTHING_READ_FAILS_ENABLED",
        "count": None,
        "of": None,
    }
    row = (
        connect()
        .execute(
            "SELECT error_code FROM jobs WHERE review_run_id = ?"
            " ORDER BY updated_at DESC LIMIT 1",
            (run["id"],),
        )
        .fetchone()
    )
    fired = str(outcome.get("error") or "").startswith("nothing read") or (
        row is not None and row["error_code"] == "NothingRead"
    )
    in_job = ai_call_ledger.snapshot() is not None
    if fired:
        return {**gate, "count": 1, "of": 1}
    if in_job and settings.nothing_read_fails_enabled and not outcome.get("error"):
        return {**gate, "count": 0, "of": 1}
    return gate


def _other_document(findings: list[dict]) -> int:
    from . import comparison

    return sum(
        (f.get("reason_code") or comparison.reason_code_of(f.get("ai_rationale")))
        == comparison.REQUIRES_OTHER_DOCUMENT
        for f in findings
    )


def gates_section(
    run: dict, outcome: dict, findings: list[dict], counts: dict, steps: dict
) -> dict:
    clause = outcome.get("clause_coverage") or {}
    decided = sum(f.get("compliance_status") in run_measures.DECIDED for f in findings)
    passes = sum(f.get("compliance_status") == "COMPLIANT" for f in findings)
    truth = "the bench's truth file, eval/bench/truth.json (#1471)"
    gates = [
        {"gate": "wrong", "count": counts["wrong"], "of": decided, "rule_id": truth},
        {
            "gate": "untrue",
            "count": counts["untrue"],
            "of": len(findings),
            "rule_id": truth,
        },
        {
            "gate": "pass_on_deferred",
            "count": counts["pass_on_deferred"],
            "of": passes,
            "rule_id": "owner decision D2",
        },
        _nothing_read_gate(run, outcome),
        {
            "gate": "certificate guard",
            "count": _other_document(findings),
            "of": len(findings),
            "rule_id": "#163 requires_other_document",
        },
    ]
    return {
        "recorded": {
            "clause_coverage_adds_up": clause.get("adds_up") if clause else None,
            "draft_checklist_results": steps["CHECKLIST"]["counts"].get(
                "draft_checklist"
            ),
        },
        "gates": gates,
        "not_recorded_on_the_run": [g["gate"] for g in gates if g["count"] is None],
        "note": "A gate with no count was not recorded for this run: wrong and untrue "
        "exist only for a run on the bench's truth file; a guard that did not fire is "
        "known only to the job, when its switch was on.",
    }


def md_gates(gates: dict) -> list[str]:
    out = ["## 6. Safety gates"]
    out += [f"- {k}: {_v(v)}" for k, v in gates["recorded"].items()]
    for g in gates["gates"]:
        count = NOT_RECORDED if g["count"] is None else f"{g['count']} of {_v(g['of'])}"
        out.append(f"- {g['gate']}: {count} (rule {g['rule_id']})")
    return [*out, f"  - {gates['note']}"]


# ------------------------------------------------------------------ section 7


def crs_paths(review_run_id: str) -> dict:
    """The issued contractor copy's file. The internal copy has no file: it is built on request."""
    newest = None
    if crs_issue._has("crs_issued_copies"):
        newest = (
            connect()
            .execute(
                "SELECT path FROM crs_issued_copies WHERE review_run_id = ?"
                " ORDER BY issued_at DESC, id LIMIT 1",
                (review_run_id,),
            )
            .fetchone()
        )
    return {
        "client_copy_path": newest["path"] if newest else NOT_ISSUED,
        "internal_copy_path": f"no stored file: GET /api/reviews/runs/{review_run_id}/crs",
    }


def _v(value) -> str:
    return NOT_RECORDED if value is None else str(value)
