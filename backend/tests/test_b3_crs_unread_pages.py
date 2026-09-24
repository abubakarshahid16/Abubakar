"""B3 in the CRS: an unread page is engineer work, never a contractor comment.

Before B3 every requirement no field answered was MISSING_INFORMATION and
reached the CRS as one summary row. After B3, on a sheet with a page not read
into fields, those findings are NEEDS_ENGINEER_REVIEW with reason UNREAD_PAGES
- and the CRS puts every NEEDS_ENGINEER_REVIEW finding in as its own row. The
vessel run alone would have gained ~74 rows, each worded for an engineer, in a
document that goes to the contractor. They get ONE plain summary row instead
(owner, 2026-09-25: "pages not yet readable, needs engineer review").

Mutations: M472-M475 (M472/M473 are the UI side, in vitest).
"""
from __future__ import annotations

from app import crs_mapping

UNREAD = ("UNREAD_PAGES: no value for this requirement was found in the fields "
          "read from pages 4-5 of 11; pages 1-3, 6-11 were not read into fields")


def _f(i: int, status: str, rationale: str = "") -> dict:
    return {"id": f"f{i}", "compliance_status": status, "ai_rationale": rationale,
            "standard_document_id": "std", "standard_clause": f"{i}.1",
            "requirement_source_text": f"Requirement {i}"}


def _run() -> list[dict]:
    return ([_f(i, "NEEDS_ENGINEER_REVIEW", UNREAD) for i in range(74)]
            + [_f(100, "NEEDS_ENGINEER_REVIEW", "UNIT_MISMATCH: bar vs mm")]
            + [_f(200 + i, "MISSING_INFORMATION") for i in range(3)])


def test_unread_page_findings_are_one_plain_summary_row_not_74():
    rows = crs_mapping.build_crs_rows(_run(), [], "vessel.pdf",
                                      unread_pages=[1, 2, 3, 6, 7, 8, 9, 10, 11])

    individual = [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_NEEDS_ENGINEER_REVIEW]
    assert [r["finding_id"] for r in individual] == ["f100"], \
        "unread-page findings entered the CRS as contractor comments"
    [summary] = [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_PAGES_NOT_READABLE]
    assert summary["comment"].startswith("Pages not yet readable - needs engineer review.")
    assert "74 requirements" in summary["comment"]
    assert "pages 1-3, 6-11" in summary["comment"]
    assert "not a comment to the contractor" in summary["comment"]
    assert summary["page_section"] == "Pages 1-3, 6-11"


def test_no_unread_findings_means_no_summary_row():
    rows = crs_mapping.build_crs_rows(
        [_f(1, "NEEDS_ENGINEER_REVIEW", "UNIT_MISMATCH: x")], [], "s.pdf", unread_pages=[])
    assert not [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_PAGES_NOT_READABLE]


def test_the_missing_information_row_states_what_was_checked():
    """Honesty audit 50: 'have no value stated for them in it' claimed the
    document was silent; what is known is that no field read from it answered."""
    rows = crs_mapping.build_crs_rows(_run(), [], "vessel.pdf", unread_pages=[1])
    [missing] = [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_MISSING_INFORMATION]
    assert "not answered by any field read from it" in missing["comment"]
    assert "no value stated" not in missing["comment"]
