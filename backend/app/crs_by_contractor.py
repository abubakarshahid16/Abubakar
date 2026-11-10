"""ONE "BY CONTRACTOR" QUERY ROW ON THE CONTRACTOR COPY (owner order 11 Nov 2026, owner answer; part of #805),
behind CRS_BY_CONTRACTOR_ONE_ROW_ENABLED (off).

A value the sheet prints with a deferral phrase ("By Contractor", "TBA") is never decided: its check is held as
a query with the hold reason `deferred_marker` (`deferred_value.hold_results`). Each such field was its own CRS
row, so the contractor read the same question once per field. With the switch on, the CONTRACTOR (issue) copy
carries ONE query row for them instead:

    These values are marked By Contractor (or similar) on the sheet; give the confirmed figures:
    - <field> (tag <tag>, p.<page>, <number>)
    ...

one line per finding, every field still named with its tag, page and the row's own number. The INTERNAL copy
keeps one row per field. Which sheet, never which verdict: no finding, status or count changes here.

Two halves, so the export never re-reads findings:

  * `fields(group, ...)`: `crs_mapping.build_crs_rows` asks it for each finding row; it returns the field
    entries (never printed) only when EVERY finding of the row is a held query whose stored hold reason is
    `deferred_marker`, with no words of the engineer's own, an id and a field name. Else None, and the row
    carries no entry (switch off: never one, so every row is as on main).
  * `one_row(rows)`: `crs_export.build_crs_view` calls it on the issue copy only. A row joins the query row
    only when its entries cover exactly the findings it stands on (a row merged with another finding later
    keeps its own row), its comment is not the engineer's, no contractor reply is recorded on it and its
    number is not closed. The issue copy prints only rows an engineer confirmed, so a query the engineer
    ACCEPTED as written is folded (the query row asks the same question); a row the engineer worded or edited
    is their own comment and keeps its own row. Fewer than two such rows: as they came. The query row takes the first member's place
    and number; every member's field, tag, page and number is on its own line (no row is lost).

General: no field name, label, tag or layout is read (rule 13); the words come from what the findings stored.
"""

from __future__ import annotations

from . import hold_reason
from .config import settings

#: The never-printed key a finding row carries its deferred field entries under.
KEY = "by_contractor_fields"
#: The query row's first line (owner's words, 11 Nov).
LEAD = (
    "These values are marked By Contractor (or similar) on the sheet; "
    "give the confirmed figures:"
)
NO_PAGE = "page not stated"
_HELD = "NEEDS_ENGINEER_REVIEW"
_CLOSED = "Closed"  # `crs_numbers.CLOSED`; a test holds them equal


def enabled() -> bool:
    return bool(settings.crs_by_contractor_one_row_enabled)


def fields(group: list[dict], label_of, page_of) -> list[dict] | None:
    """The field entries of one CRS finding row (switch on), or None.

    `label_of(finding)`: the field as the row prints it (`crs_mapping._field_label`); `page_of(finding)`: its
    page words (`word_pages.at`). An entry per finding: its id, field, tag and page."""
    if not enabled() or not group:
        return None
    out = []
    for f in group:
        if hold_reason.of(f) != hold_reason.DEFERRED_MARKER:
            return None
        if f.get("compliance_status") != _HELD or f.get("engineer_comment"):
            return None
        field = " ".join(str(label_of(f) or "").split())
        if not f.get("id") or not field:
            return None
        out.append(
            {
                "finding_id": str(f["id"]),
                "field": field,
                "tag": str(f.get("equipment_tag") or "").strip(),
                "page": page_of(f) if f.get("contractor_page") else "",
            }
        )
    return out


def mark(row: dict, group: list[dict], label_of, page_of) -> None:
    """`crs_mapping.build_crs_rows`, per finding row: put the entries (`fields`) on the row, never printed.
    Switch off, or not a deferred-value row: the row is left as it was (no key)."""
    entries = fields(group, label_of, page_of)
    if entries is not None:
        row[KEY] = entries


def _member(row: dict) -> bool:
    """May this issue-copy row be folded into the query row?"""
    entries = row.get(KEY)
    if not entries:
        return False
    if row.get("edited") or row.get("engineer_worded"):
        return False
    if str(row.get("crs_response") or "").strip():
        return False
    if str(row.get("crs_status") or "").startswith(_CLOSED):
        return False
    stands_on = sorted(row.get("finding_ids") or [row.get("finding_id")])
    return stands_on == sorted(e["finding_id"] for e in entries)


def line(entry: dict, number: str) -> str:
    """One field of the query row: "- <field> (tag <tag>, p.<page>, <number>)"."""
    bits = [
        f"tag {entry['tag']}" if entry["tag"] else "",
        entry["page"] or NO_PAGE,
        number,
    ]
    return f"- {entry['field']} ({', '.join(b for b in bits if b)})"


def _joined(members: list[dict]) -> dict:
    first = members[0]
    entries = [e for r in members for e in r[KEY]]
    lines = [line(e, str(r.get("crs_ref") or "")) for r in members for e in r[KEY]]
    priorities = [p for r in members if isinstance(p := r.get("priority"), int)]

    def joined(key: str) -> str:
        return "; ".join(
            dict.fromkeys(str(r.get(key) or "") for r in members if r.get(key))
        )

    row = {
        **first,
        "comment": "\n".join([LEAD, *dict.fromkeys(lines)]),
        "ai_comment": "",
        "comment_by": joined("comment_by"),
        "standard_reference": joined("standard_reference"),
        "page_section": "; ".join(
            dict.fromkeys(e["page"] for e in entries if e["page"])
        ),
        "finding_ids": [e["finding_id"] for e in entries],
        "by_contractor_rows": len(members),
        KEY: entries,
    }
    if priorities:
        row["priority"] = min(priorities)
    return row


def one_row(rows: list[dict]) -> list[dict]:
    """The issue copy's rows with every deferred-value row folded into ONE query row at the first one's place
    (switch on, two or more such rows). Off, or fewer than two: `rows` as they came."""
    if not enabled():
        return rows
    at = [i for i, r in enumerate(rows) if _member(r)]
    if len(at) < 2:
        return rows
    folded = set(at)
    query = _joined([rows[i] for i in at])
    return [
        query if i == at[0] else r
        for i, r in enumerate(rows)
        if i == at[0] or i not in folded
    ]
