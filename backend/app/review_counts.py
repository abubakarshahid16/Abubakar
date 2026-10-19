"""Order 152.2: the sheet's counts, on the server, in ONE place.

"Comments" and "need your judgement" are counted in three units: rows on the
CRS sheet, findings (the inbox's `/counts`) and notes in the file's Review
notes. A row that groups 13 blanks is one comment on the sheet and 13
findings. This module counts what the SHEET shows, in rows, from the same
inputs the file is built from (the run's findings, the file's grouping
`api.run_summary.crs_row_fields` returns, the tier of each finding
`review_tiers.tier_of` gives), and says its unit on every number, so a screen
reads it instead of counting again.

A finding is on no row when an engineer removed it, when it is a chat note,
when it is a page-reading note (`comparison.UNREAD_PAGES`, `PAGE_READER_ONLY`)
or when the file puts it in its Review notes (`crs_note`). Every other
finding is on one row: the row of its `crs_group`, else a row of its own. A
row's tier is the worst of its findings' (needs you, then comment, else the
first's), the rule `crs/tiers.ts:tierOfGroup` has. A row of tier A (met, not
applicable, another document) is not a comment.

Display only: nothing is decided or written. None when the grouping could not
be computed (the sheet then shows one row per finding and says so), never a
guess and never zeros.
"""

from __future__ import annotations

from . import comparison, review_tiers

CHAT_ORIGIN = "chat"


def _on_a_row(finding: dict, groups: dict[str, dict]) -> bool:
    """Whether a finding that is still in a tier lands on a sheet row."""
    if finding.get("origin") == CHAT_ORIGIN:
        return False
    rationale = finding.get("ai_rationale") or ""
    if rationale.startswith((comparison.UNREAD_PAGES, comparison.PAGE_READER_ONLY)):
        return False
    return not (groups.get(finding["id"]) or {}).get("crs_note")


def _row_tier(tiers: list[tuple[str, str]]) -> tuple[str, str]:
    """(tier, label) of a row of several findings: needs you first, then a
    comment, else the first (`tierOfGroup`)."""
    for wanted in (review_tiers.C, review_tiers.B):
        for tier, label in tiers:
            if tier == wanted:
                return tier, label
    return tiers[0]


def sheet_counts(
    findings: list[dict],
    facts: review_tiers.RunFacts,
    groups: dict[str, dict] | None,
) -> dict | None:
    """The sheet's counts, each in the unit it names:

    * ``comments`` / ``needs_you`` / ``met`` / ``not_applicable`` /
      ``another_document``: ROWS of the sheet, by tier (``comments`` is the
      comment rows plus the needs-you rows, the headline's number);
    * ``findings_in_comments``: the FINDINGS those comment rows hold;
    * ``review_notes``: findings the file puts in its Review notes;
    * ``removed``: findings an engineer removed;
    * ``findings``: every finding of the run, removed ones included.
    """
    if groups is None:
        return None
    rows: dict[str, list[tuple[str, str]]] = {}
    sizes: dict[str, int] = {}
    removed = notes = 0
    for finding in findings:
        tier, label, _reason = review_tiers.tier_of(finding, facts)
        if tier == review_tiers.REMOVED:
            removed += 1
            continue
        if not _on_a_row(finding, groups):
            if (groups.get(finding["id"]) or {}).get("crs_note"):
                notes += 1
            continue
        key = (groups.get(finding["id"]) or {}).get(
            "crs_group"
        ) or f"one:{finding['id']}"
        rows.setdefault(key, []).append((tier, label))
        sizes[key] = sizes.get(key, 0) + 1
    out = dict.fromkeys(review_tiers.RULES["count_keys"].values(), 0)
    findings_in_comments = 0
    for key, tiers in rows.items():
        tier, label = _row_tier(tiers)
        out[review_tiers.RULES["count_keys"][label]] += 1
        if tier != review_tiers.A:
            findings_in_comments += sizes[key]
    return {
        "comments": out["comment"] + out["needs_you"],
        "needs_you": out["needs_you"],
        "met": out["met"],
        "not_applicable": out["not_applicable"],
        "another_document": out["another_document"],
        "findings_in_comments": findings_in_comments,
        "review_notes": notes,
        "removed": removed,
        "findings": len(findings),
    }
