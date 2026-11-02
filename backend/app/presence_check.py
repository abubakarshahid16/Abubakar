"""#1638: a checklist `required` row is a presence check, not a decided rule.

It asks only that a field is stated, so a value over its limit, in the wrong unit or
in the wrong field still "passes" it. Stored status and wording stay as they are: the
row says "is stated", truly. What changes, with PRESENCE_NOT_PASS_ENABLED on, is what
the row may count for: never a Pass toward an approval (`comparison`), never a decided
rule (`coverage_pair`, the bench), and it is named "stated, not checked" to the reader.

Told from the checklist's own rule kind by the item id the row cites, for every
equipment type and the local overlay, so a stored run reads the same. Nothing here
names a type, a field or a layout (rule 13). With the switch off: nothing is a stated
row and every caller behaves as before.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache, wraps
from pathlib import Path

from .config import settings

#: The words a reader sees, in every home (rule 8).
WORDS = "Stated, not checked"
#: Its name where statuses are counted: the stored status stays COMPLIANT.
STATUS = "STATED_NOT_CHECKED"
PASS = "COMPLIANT"
ORIGIN = "datasheet_check"
REQUIRED = "required"
#: The datasheet's own checks (arithmetic, units): never a checklist item.
OWN_CHECK = "DS-"
NOTE_DETAIL = (
    "These checklist items ask only that the field is stated. The value was not compared"
    " with anything, so they count for no approval and are not decided rules: "
)


@lru_cache(maxsize=8)
def _compared(_stamp: tuple) -> frozenset[str]:
    from . import datasheet_checks as dc

    rules = dc.load_rules()
    ids = {rule["id"] for rule in rules.get("consistency") or []}
    for key in rules.get("checklists") or {}:
        if key.startswith("_"):
            continue
        for item in (dc.checklist_for(key, rules) or {}).get("items", []):
            if item["rule"]["kind"] != REQUIRED:
                ids.add(item["id"])
    return frozenset(ids)


def _stamp() -> tuple:
    """What the cached list was read from: an edit in place moves a file's stamp, not its
    folder's. A checklist file edited, added or removed is read without a restart."""
    from . import datasheet_checks as dc

    overlay = Path(settings.data_dir) / dc.LOCAL_DIR_NAME
    files = [
        dc.RULES_PATH,
        *(sorted(overlay.glob("*.json")) if overlay.is_dir() else []),
    ]
    return tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)


def compared_ids() -> frozenset[str]:
    """Every item whose rule compares a value. A row is told by being on this list, not by
    being off the presence list, so a row that names no known item counts for nothing."""
    return _compared(_stamp())


def is_stated_only(finding: dict) -> bool:
    """A checklist Pass nothing shows was compared: a `required` item, or a row whose item
    cannot be told (no id, or one no checklist lists). False with the switch off."""
    if not settings.presence_not_pass_enabled:
        return False
    if finding.get("origin") != ORIGIN or finding.get("compliance_status") != PASS:
        return False
    from .coverage_pair import _check_id

    check = _check_id(finding)
    if check and check.startswith(OWN_CHECK):
        return False
    return check not in compared_ids()


def status_of(finding: dict) -> str | None:
    """The status where statuses are counted: a stated row is not a Pass."""
    return STATUS if is_stated_only(finding) else finding.get("compliance_status")


def moved_counts(by_status: dict[str, int], findings: list[dict]) -> dict[str, int]:
    """Counts per stored status, with the stated rows moved out of the Passes."""
    stated = len(split(findings)[1])
    if not stated:
        return by_status
    return {**by_status, PASS: by_status.get(PASS, 0) - stated, STATUS: stated}


def with_stated_apart(run_id: str, by_status: dict[str, int]) -> dict[str, int]:
    """A run's counts per status. Reads the rows only with the switch on."""
    if not settings.presence_not_pass_enabled:
        return by_status
    from .db import connect

    rows = connect().execute(
        "SELECT origin, compliance_status, requirement_source_text FROM review_findings"
        " WHERE review_run_id = ? AND compliance_status = ?",
        (run_id, PASS),
    )
    return moved_counts(by_status, [dict(r) for r in rows])


def split(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the rows that may count, the stated rows)."""
    counted, stated = [], []
    for finding in findings:
        (stated if is_stated_only(finding) else counted).append(finding)
    return counted, stated


def _words(count: int) -> str:
    return f"{count} checklist item(s) were stated, not checked"


def not_a_pass(decide: Callable[..., dict]) -> Callable[..., dict]:
    """The code rule (`comparison._recommend_code`) never sees a stated row, and any stated
    row caps it below an approval, outright or with comments. A real Fail still wins."""

    @wraps(decide)
    def wrapped(findings: list[dict], completeness: dict, **options) -> dict:
        from .comparison import DEFAULT_CODES

        counted, stated = split(findings)
        result = decide(counted, completeness, **options)
        if not stated:
            return result
        approved, with_comments, _rejected, manual = (
            options.get("codes") or DEFAULT_CODES
        )
        words = _words(len(stated))
        if result["code"] == approved:
            return {**result, "code": manual, "reason": f"Manual review: {words}"}
        if result["code"] == with_comments:
            why = f"Manual review: {words}; {result['reason']}"
            return {**result, "code": manual, "reason": why}
        return {**result, "reason": f"{result['reason']}; {words}"}

    return wrapped


def says_how_many(recommend: Callable[..., dict]) -> Callable[..., dict]:
    """`comparison.recommend_code`: the plain reason is rewritten after the rule above, on
    some paths from nothing but its code, so the count is put back on the one people read."""

    @wraps(recommend)
    def wrapped(findings: list[dict], *args, **options) -> dict:
        result = recommend(findings, *args, **options)
        stated = len(split(findings)[1])
        if not stated or WORDS.lower() in result["reason"]:
            return result
        return {**result, "reason": f"{result['reason']} {_words(stated)}."}

    return wrapped


def marked(item: dict) -> dict:
    """A finding row as the API hands it on, saying whether it is only stated."""
    return {**item, "stated_only": is_stated_only(item)}


def mark_trace_steps(steps: list[dict], findings: list[dict]) -> None:
    """The review trace's checklist and decision steps say the stated rows apart."""
    stated = len(split(findings)[1])
    if not stated:
        return
    for step in steps:
        if step.get("step") in ("CHECKLIST", "DECIDE"):
            step["summary"] += f" | stated_not_checked {stated} (not decided)"
            step["counts"]["stated_not_checked"] = stated


def review_notes(findings: list[dict]) -> list[dict]:
    """The CRS Review-notes row, naming the fields, one per distinct field. None off."""
    _, stated = split(findings)
    if not stated:
        return []
    fields = sorted({f.get("contractor_section") or "" for f in stated} - {""})
    return [
        {
            "note": WORDS,
            "standard": "",
            "count": len(stated),
            "detail": NOTE_DETAIL + (", ".join(fields) or "no field named") + ".",
        }
    ]
