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
PASS = "COMPLIANT"
ORIGIN = "datasheet_check"
REQUIRED = "required"
NOTE_DETAIL = (
    "These checklist items ask only that the field is stated. The value was not compared"
    " with anything, so they count for no approval and are not decided rules: "
)


@lru_cache(maxsize=8)
def _ids_of(_data_dir: str, _overlay_stamp: int) -> frozenset[str]:
    from . import datasheet_checks as dc

    rules = dc.load_rules()
    ids: set[str] = set()
    for key in rules.get("checklists") or {}:
        if key.startswith("_"):
            continue
        for item in (dc.checklist_for(key, rules) or {}).get("items", []):
            if item["rule"]["kind"] == REQUIRED:
                ids.add(item["id"])
    return frozenset(ids)


def item_ids() -> frozenset[str]:
    """Every presence-only checklist item, read from the rule data and the overlay."""
    from .datasheet_checks import LOCAL_DIR_NAME

    overlay = Path(settings.data_dir) / LOCAL_DIR_NAME
    stamp = overlay.stat().st_mtime_ns if overlay.is_dir() else 0
    return _ids_of(str(settings.data_dir), stamp)


def is_stated_only(finding: dict) -> bool:
    """A Pass that only says a field is stated. False with the switch off."""
    if not settings.presence_not_pass_enabled:
        return False
    if finding.get("origin") != ORIGIN or finding.get("compliance_status") != PASS:
        return False
    from .coverage_pair import _check_id

    return _check_id(finding) in item_ids()


def split(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the rows that may count, the stated rows)."""
    counted, stated = [], []
    for finding in findings:
        (stated if is_stated_only(finding) else counted).append(finding)
    return counted, stated


def not_a_pass(decide: Callable[..., dict]) -> Callable[..., dict]:
    """The code rule (`comparison._recommend_code`) never sees a stated row, so none is a
    Pass, nor the 'confirmed as met' that lets a blank through; its reason says so."""

    @wraps(decide)
    def wrapped(findings: list[dict], completeness: dict, **options) -> dict:
        counted, stated = split(findings)
        result = decide(counted, completeness, **options)
        if not stated:
            return result
        words = f"; {len(stated)} checklist item(s) were stated, not checked"
        return {**result, "reason": result["reason"] + words}

    return wrapped


def marked(item: dict) -> dict:
    """A finding row as the API hands it on, saying whether it is only stated."""
    return {**item, "stated_only": is_stated_only(item)}


def mark_trace_step(step: dict, checklist: list[dict]) -> None:
    """The review trace's checklist step counts the stated rows apart."""
    stated = len(split(checklist)[1])
    if stated:
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
