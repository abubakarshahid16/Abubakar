"""ONE meaning of "checked" (plan change 6 part B): one function for the bench, the
board call and the CRS. The headline is a PAIR, reported together every time:

  coverage  decided of applicable. `applicable`: the rules the run states apply to
            this document (`requirement_split`: reached the comparison + applies
            but not checked), each rule once. `decided`: code said pass or fail.
  risk      wrong among decided. Only knowable where a truth set names the wrong
            rows; without one it is "not measured", never 0.

Three outcomes: pass, fail, unknown. A Pass on a value the sheet defers (D2) is
unknown, as is anything sent to another document or left to the engineer. The
stored `checked` count is never read as decided: it counts what reached the
comparison, and older runs stored rows sent to another document in it.

The other denominator in circulation is `clause_coverage.applicable`. It counts
stored rows, not rules (a repeat counts again), and adds the rules a checklist
covers, so it is larger on the same run. It stays where the approval and the
ledger read it; with ONE_CHECKED_DEFINITION_ENABLED it is not what the CRS and
the screen print.

Checklist decisions are stated apart and never added: a checklist clause is text,
not linked to a stored rule (the same lane as the bench's source row, PR #1566).

Read only. Counts only: no document text leaves this module except the gate
reasons a run stored, which the bench does not print (`crs_bench.safe_reason`).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import deferred_pass, deferred_value, requirement_split, spec_kit
from .config import settings

PASS, FAIL = "COMPLIANT", "NON_COMPLIANT"
DECIDED = (PASS, FAIL)
#: Rows that are an engineer's by construction, whatever status they carry.
DRAFT_ORIGINS = ("ai_engineering_check", "web_standard_check", "clause_review", "chat")
NOT_MEASURED = "not measured"
NO_TYPE = "no equipment type"
#: The gate-reason row of the rules that passed every gate and reached the comparison.
REACHED = "reached the code comparison"
NOTE = "Risk and coverage"
NOTE_CHECKLIST = "Checklist decisions"
TRUTH = Path(__file__).resolve().parents[2] / "eval" / "bench" / "truth.json"

_LOOK_UP = object()

# What a row CLAIMS, so a truth matcher survives a label change (#1569): `check` is
# the checklist item's id, `value` whether the row carries a value from the sheet
# ("absent"/"present": never the value itself, the truth file holds no document
# text), `page` the page it cites. `section` is the row's label: it can change
# while the claim stays, so the truth file does not use it. `value` tests only
# that the row has evidence text: a quote that defers the value is "present".
MATCH_KEYS = (
    "origin",
    "status",
    "requirement_id",
    "match_method",
    "section",
    "check",
    "value",
    "page",
    "deferred",
)
VALUE_STATES = ("absent", "present")


def _check_id(finding: dict) -> str | None:
    from .datasheet_checks import LABEL

    source = finding.get("requirement_source_text") or ""
    found = re.match(rf"{re.escape(LABEL)} (\S+):", source)
    return found.group(1) if found else None


def matches(finding: dict, matcher: dict) -> bool:
    """Does a truth matcher name this finding?"""
    if not set(matcher) & set(MATCH_KEYS):
        raise ValueError(f"a truth matcher must name at least one of {MATCH_KEYS}")
    # an unknown key used to be ignored, which quietly widened the matcher
    unknown = set(matcher) - set(MATCH_KEYS) - {"why"}
    if unknown:
        raise ValueError(f"a truth matcher has unknown keys: {sorted(unknown)}")
    if "value" in matcher and matcher["value"] not in VALUE_STATES:
        raise ValueError(f"a truth matcher's value must be one of {VALUE_STATES}")
    has_value = (finding.get("contractor_evidence_text") or "").strip()
    for key in MATCH_KEYS:
        if key not in matcher:
            continue
        want = matcher[key]
        got = {
            "status": finding.get("compliance_status"),
            "section": finding.get("contractor_section"),
            "check": _check_id(finding),
            "value": "present" if has_value else "absent",
            "page": finding.get("contractor_page"),
        }.get(key, finding.get(key))
        if (got or "") != want:
            return False
    return True


def hits(findings: list[dict], matchers: list[dict]) -> list[dict]:
    return [f for f in findings if any(matches(f, m) for m in matchers)]


def _rows(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return [dict(r) for r in cursor.execute(sql, params)]


def value_is_deferred(conn: sqlite3.Connection, finding: dict) -> bool:
    """D2, whichever reading the row kept: its wording defers the value, or another
    current reading of the same field on the same page does."""
    if deferred_pass.is_deferred_pass(finding):
        return True
    rows = _rows(
        conn,
        "SELECT o.value_note FROM submittal_facts f JOIN submittal_facts o"
        " ON o.submittal_document_id = f.submittal_document_id"
        " AND o.field_name = f.field_name AND o.page IS f.page"
        " AND o.equipment_tag IS f.equipment_tag"
        " WHERE f.id = ? AND o.superseded_at IS NULL",
        (finding.get("fact_id"),),
    )
    return any(deferred_value.note_of({"value_note": r["value_note"]}) for r in rows)


def truth_case(run_id: str) -> dict | None:
    """The truth case that names this run, or None: then risk is not measured."""
    try:
        cases = json.loads(TRUTH.read_text(encoding="utf-8")).get("cases") or []
    except (OSError, ValueError):
        return None
    return next((c for c in cases if c.get("run") == run_id), None)


def _rule_texts(conn: sqlite3.Connection, ids: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    wanted = sorted(ids)
    try:
        for start in range(0, len(wanted), 500):
            part = wanted[start : start + 500]
            marks = ",".join("?" * len(part))
            for r in _rows(
                conn,
                "SELECT id, standard_document_id, requirement_text"
                f" FROM standard_requirements WHERE id IN ({marks})",
                part,
            ):
                out[r["id"]] = r
    except sqlite3.OperationalError:  # a copy without the table: nothing links
        return {}
    return out


def _is_kit_card(finding: dict) -> bool:
    from . import kit_core

    text = f"{finding.get('requirement') or ''} {finding.get('requirement_source_text') or ''}"
    return any(k.words and k.words in text for k in kit_core._kits())


def _lane(finding: dict, rules: dict[str, dict]) -> str | None:
    """ "rule", "checklist" or None. The bench's `finding_source` gives the same answer
    for its rule and checklist rows; a test holds the two together."""
    origin = finding.get("origin")
    if origin in DRAFT_ORIGINS or origin == spec_kit.ORIGIN:
        return None
    if origin == "datasheet_check" and _is_kit_card(finding):
        return None
    if (
        finding.get("show_for_engineer_tick")
        and finding.get("compliance_status") == PASS
    ):
        return None  # a safety_tick row the engineer must tick
    if origin == "datasheet_check":
        return "checklist"
    return "rule" if finding.get("requirement_id") in rules else None


def _stated_split(outcome: dict) -> dict | None:
    return outcome.get("requirement_split") or requirement_split.from_counts(
        outcome.get("unchecked_counts")
    )


def _left_out(split: dict | None) -> dict:
    split = split or {}
    return {
        "does_not_apply": split.get("does_not_apply"),
        "covered_by_checklist": split.get("not_used"),
        "stored_repeats": split.get("repeats_ignored"),
    }


def _boundary(left: dict) -> str:
    parts = [
        f"{left[key]} {words}"
        for key, words in (
            ("does_not_apply", "that do not apply"),
            ("covered_by_checklist", "covered by the checklist"),
            ("stored_repeats", "stored repeats"),
        )
        if left[key] is not None
    ]
    said = f"; left out: {', '.join(parts)}" if parts else ""
    return (
        "Boundary: the standard rules this run states apply to this run's document, each"
        f" rule once{said}."
    )


def _gate_rows(split: dict | None, decided: int, wrong: int | None) -> list[dict]:
    """Per gate reason: where each applicable rule stopped. Adds up to `applicable`;
    a count with no stored reason is said, never dropped."""
    if not split:
        return []
    reached = int(split.get("checked") or 0)
    held = int(split.get("applies_not_checked") or 0)
    rows = [
        {"reason": REACHED, "applicable": reached, "decided": decided, "wrong": wrong}
    ]
    told = 0
    for item in split.get("applies_not_checked_reasons") or []:
        told += int(item.get("count") or 0)
        rows.append(
            {
                "reason": item.get("reason") or requirement_split.NO_REASON,
                "applicable": int(item.get("count") or 0),
                "decided": 0,
                "wrong": None,
            }
        )
    if told < held:
        rows.append(
            {
                "reason": requirement_split.NO_REASON,
                "applicable": held - told,
                "decided": 0,
                "wrong": None,
            }
        )
    return rows


def coverage_text(pair: dict) -> str:
    """ "decided of applicable", or nothing when the run states no boundary (null is
    never 0), or when the decisions do not fit inside the boundary it states."""
    cov = pair["coverage"]
    if cov["applicable"] is None or cov["decided"] > cov["applicable"]:
        return ""
    return f"{cov['decided']} of {cov['applicable']}"


def risk_text(pair: dict) -> str:
    risk = pair["risk"]
    if not risk["measured"]:
        return NOT_MEASURED
    return f"{risk['wrong']} wrong of {risk['decided']} decided"


def _line(pair: dict) -> str:
    cov = coverage_text(pair)
    if cov:
        head = (
            f"Standard rules decided: {cov} that apply (pass {pair['pass']}, fail"
            f" {pair['fail']}, unknown {pair['unknown']})"
        )
    elif pair["applicable"] is None:
        head = (
            f"Standard rules decided: {pair['decided']} (pass {pair['pass']}, fail"
            f" {pair['fail']}); this run states no rules that apply"
        )
    else:
        head = (
            f"Standard rules decided: {pair['decided']}, more than the {pair['applicable']}"
            " this run states apply, so no coverage is given"
        )
    return f"{head}. Risk: {risk_text(pair)}."


def compute(
    conn: sqlite3.Connection,
    run: dict,
    findings: list[dict],
    *,
    matchers: list[dict] | None,
    equipment_type: str | None,
) -> dict:
    """The pair for one run, from its row and its findings. `matchers`: the truth
    set's wrong rows, None when there is no truth set."""
    outcome = json.loads(run.get("outcome_json") or "{}")
    split = _stated_split(outcome)
    rules = _rule_texts(
        conn, {f["requirement_id"] for f in findings if f.get("requirement_id")}
    )
    if matchers and any(m.get("deferred") for m in matchers):
        for f in findings:
            f["deferred"] = f.get("compliance_status") == PASS and value_is_deferred(
                conn, f
            )
    wrong_ids = None if matchers is None else {id(f) for f in hits(findings, matchers)}

    passed: set[str] = set()
    failed: set[str] = set()
    wrong_rules: set[str] = set()
    deferred_rules: set[str] = set()
    checklist = {"decided": 0, "rows": 0, "pass": 0, "fail": 0, "wrong": 0}
    for f in findings:
        lane = _lane(f, rules)
        if lane is None:
            continue
        if lane == "checklist":
            checklist["rows"] += 1
        status = f.get("compliance_status")
        if status not in DECIDED:
            continue
        key = (
            requirement_split.requirement_key(rules[f["requirement_id"]])
            if lane == "rule"
            else None
        )
        if status == PASS and value_is_deferred(conn, f):
            if key is not None:
                deferred_rules.add(key)
            continue
        is_wrong = wrong_ids is not None and id(f) in wrong_ids
        if lane == "checklist":
            checklist["decided"] += 1
            checklist["pass" if status == PASS else "fail"] += 1
            checklist["wrong"] += int(is_wrong)
            continue
        (passed if status == PASS else failed).add(key)
        if is_wrong:
            wrong_rules.add(key)

    passed -= failed  # a rule with a Pass on one row and a Fail on another is a Fail
    decided = len(passed) + len(failed)
    applicable = (
        None
        if split is None
        else int(split.get("checked") or 0) + int(split.get("applies_not_checked") or 0)
    )
    fits = applicable is not None and decided <= applicable
    wrong = None if wrong_ids is None else len(wrong_rules)
    if wrong_ids is None:
        checklist["wrong"] = None
    left = _left_out(split)
    pair = {
        "run": run["id"],
        "document": run.get("submittal_document_id"),
        "equipment_type": equipment_type,
        "applicable": applicable,
        "decided": decided,
        "pass": len(passed),
        "fail": len(failed),
        "unknown": applicable - decided if fits else None,
        "deferred_passes": len(deferred_rules - passed - failed),
        "coverage": {"decided": decided, "applicable": applicable},
        "risk": {"measured": wrong is not None, "wrong": wrong, "decided": decided},
        "checklist": checklist,
        "left_out": left,
        "boundary": _boundary(left),
        "by_gate_reason": _gate_rows(split, decided, wrong),
    }
    pair["line"] = _line(pair)
    pair["checklist_line"] = (
        f"Checklist, stated apart, not added to the rules: {checklist['decided']} of"
        f" {checklist['rows']} items decided."
    )
    return pair


def for_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    case: dict | object | None = _LOOK_UP,
    replayed: bool = False,
) -> dict | None:
    """THE function: the pair for a stored run, None when there is no such run. `case`:
    the truth case; left out, the truth file is asked by run, so every home gets the
    same answer. A case with no "wrong" key is no truth set. `replayed`: the bench's
    replay column also counts `wrong_replay` (a saved run keeps the rows it wrote)."""
    runs = _rows(conn, "SELECT * FROM review_runs WHERE id = ?", (run_id,))
    if not runs:
        return None
    if case is _LOOK_UP:
        case = truth_case(run_id)
    matchers = None
    if isinstance(case, dict) and "wrong" in case:
        matchers = list(case["wrong"]) + (
            list(case.get("wrong_replay") or []) if replayed else []
        )
    findings = _rows(
        conn, "SELECT * FROM review_findings WHERE review_run_id = ?", (run_id,)
    )
    kinds = _rows(
        conn,
        "SELECT equipment_type FROM document_classification WHERE document_id = ?",
        (runs[0].get("submittal_document_id"),),
    )
    return compute(
        conn,
        runs[0],
        findings,
        matchers=matchers,
        equipment_type=(kinds[0]["equipment_type"] or None) if kinds else None,
    )


def by_equipment_type(pairs: list[dict]) -> dict[str, dict]:
    """The pair per equipment type over these runs: a good type must not hide a bad
    one. Risk adds only the runs a truth set measured and says how many they were."""
    out: dict[str, dict] = {}
    for p in pairs:
        slot = out.setdefault(
            p.get("equipment_type") or NO_TYPE,
            {
                "runs": 0,
                "decided": 0,
                "applicable": None,
                "risk": {"measured_runs": 0, "wrong": None, "decided": None},
            },
        )
        slot["runs"] += 1
        if p["applicable"] is not None:
            slot["applicable"] = (slot["applicable"] or 0) + p["applicable"]
            slot["decided"] += p["decided"]
        if p["risk"]["measured"]:
            risk = slot["risk"]
            risk["measured_runs"] += 1
            risk["wrong"] = (risk["wrong"] or 0) + p["risk"]["wrong"]
            risk["decided"] = (risk["decided"] or 0) + p["risk"]["decided"]
    return out


# ----------------------------------------------------- screen and CRS, behind the switch


def for_screen(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """The pair for a screen, or None with the switch off (screens stay as they were)."""
    if not settings.one_checked_definition_enabled:
        return None
    return for_run(conn, run_id)


def screen_coverage(coverage: dict, conn: sqlite3.Connection, run_id: str) -> dict:
    """The run's coverage route: with the switch on its one line is the pair's."""
    pair = for_screen(conn, run_id)
    return coverage if pair is None else {**coverage, "line": pair["line"]}


def crs_notes(notes: list[dict], conn: sqlite3.Connection, run_id: str) -> list[dict]:
    """The CRS review notes. With the switch on the pair replaces the clause coverage
    note, so the sheet prints one denominator; with it off, `notes` is returned as is."""
    pair = for_screen(conn, run_id)
    if pair is None:
        return notes
    from .clause_coverage import NOTE as OLD_NOTE

    return [n for n in notes if n.get("note") != OLD_NOTE] + [
        {
            "note": NOTE,
            "standard": "",
            "count": pair["applicable"],
            "detail": f"{pair['line']} {pair['boundary']}",
        },
        {
            "note": NOTE_CHECKLIST,
            "standard": "",
            "count": pair["checklist"]["rows"],
            "detail": pair["checklist_line"],
        },
    ]
