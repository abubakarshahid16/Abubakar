"""Order 152.2 (labels): "standard not in library" is only said when it is true.

It used to be printed for a blank with no standard behind it, for a blank whose
standard is in the library but outside this review, and for a met row whose
clause number merely began like a missing standard's. Now a blank says what is
true ("no standard linked", "standard outside this review") and a missing
standard is found between word edges only. The tier of every finding, and so
every count, is exactly as before: only the reason word moves. The issue gate's
open items also carry the standard the row names (local screen only).
Invented data.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app import crs_issue, review_tiers
from app.api import run_summary

T = review_tiers
NOT_IN_LIBRARY = "standard not in library"
NO_STANDARD = "no standard linked"
OUTSIDE = "standard outside this review"
BLANK = "MISSING_INFORMATION"


def facts(missing=(), library=("std-1",)) -> T.RunFacts:
    return T.RunFacts(
        missing_standards=tuple(missing),
        library_standard_ids=None if library is None else frozenset(library),
    )


def finding(status=BLANK, standard="std-1", **over) -> dict:
    return {
        "id": "f",
        "compliance_status": status,
        "standard_document_id": standard,
        "contractor_page": 1,
        **over,
    }


def test_blank_without_standard_is_not_called_not_in_library():
    got = T.tier_of(finding(standard=None), facts())
    assert got == ("C", "Needs you", NO_STANDARD)
    assert got[2] != NOT_IN_LIBRARY


def test_blank_with_standard_outside_the_review_is_not_called_not_in_library():
    got = T.tier_of(finding(standard="std-held-but-left-out"), facts())
    assert got == ("C", "Needs you", OUTSIDE)
    assert T.tier_of(finding(standard="std-1"), facts())[2] is None


def test_a_failed_standards_list_claims_nothing_about_a_standard():
    assert T.tier_of(finding(standard="std-x"), facts(library=None))[:2] == (
        "B",
        "Comment",
    )


def test_missing_standard_match_needs_word_edges():
    held = facts(missing=["STD-A 5"])
    hit = {"standard_clause": "STD-A 5 clause 3"}
    assert T.missing_standard_of(finding(**hit), held) == "STD-A 5"
    for clause in (
        "STD-A 52 clause 3",
        "STD-A 5a",
        "7STD-A 5",
        "éSTD-A 5",
        "STD-A 5é",
    ):
        assert T.missing_standard_of(finding(standard_clause=clause), held) is None
    # the fold makes "-" and "_" separators, so these are the same standard
    for clause in ("STD-A 5-1", "(STD-A 5)", "STD-A 5_2", "std_a_5 x"):
        assert T.missing_standard_of(finding(standard_clause=clause), held) == "STD-A 5"


def test_a_met_finding_in_library_is_not_needs_you_because_of_a_prefix():
    met = finding(status="COMPLIANT", standard_clause="STD-A 52 clause 3")
    assert T.tier_of(met, facts(missing=["STD-A 5"])) == ("A", "Met", None)
    rows = T.summarise([met], facts(missing=["STD-A 5"]))
    assert rows["rows"][0]["missing_standard_id"] is None
    assert rows["counts"]["met"] == 1 and rows["counts"]["needs_you"] == 0


def test_cited_not_held_standard_still_says_not_in_library():
    held = facts(missing=["STD-A 5"])
    for status in ("COMPLIANT", BLANK, "NON_COMPLIANT"):
        cited = finding(status=status, standard_clause="STD-A 5 clause 3")
        assert T.tier_of(cited, held) == ("C", "Needs you", NOT_IN_LIBRARY), status
    # a cited missing standard beats a blank's own reasons
    blank = finding(standard=None, governing_sources=["STD-A 5"])
    assert T.tier_of(blank, held)[2] == NOT_IN_LIBRARY


def _tier_before(f: dict, fa: T.RunFacts) -> tuple[str, str]:
    """The tier a blank had before this order: Comment only with a standard
    that is in the library (a failed list counts as in the library)."""
    standard = f.get("standard_document_id")
    held = bool(standard) and (
        fa.library_standard_ids is None or standard in fa.library_standard_ids
    )
    return ("B", "Comment") if held else ("C", "Needs you")


def test_blank_tier_and_counts_unchanged():
    import itertools

    for standard, library, missing in itertools.product(
        (None, "std-1", "std-gone"), (None, ("std-1",), ()), ((), ("API 526",))
    ):
        fa = facts(missing=missing, library=library)
        f = finding(standard=standard, requirement="no names here")
        assert T.tier_of(f, fa)[:2] == _tier_before(f, fa), (standard, library)
    mixed = [
        finding(standard=None),
        finding(standard="std-gone"),
        finding(standard="std-1"),
        finding(status="COMPLIANT"),
    ]
    counts = T.summarise(mixed, facts())["counts"]
    assert (counts["comment"], counts["needs_you"], counts["met"]) == (1, 2, 1)
    reasons = [r["reason"] for r in T.summarise(mixed, facts())["rows"]]
    assert sorted(r for r in reasons if r) == sorted([NO_STANDARD, OUTSIDE])


def test_the_new_reasons_are_data_and_the_api_accepts_them():
    mi = T.RULES["missing_information"]
    assert (mi["no_standard_reason"], mi["outside_review_reason"]) == (
        NO_STANDARD,
        OUTSIDE,
    )
    assert T.RULES["reasons"][-2:] == [NO_STANDARD, OUTSIDE]
    for word in (NO_STANDARD, OUTSIDE):
        row = run_summary.TierRow(
            finding_id="f", tier="C", label="Needs you", reason=word
        )
        assert row.reason == word


def test_open_items_name_their_standard_and_log_no_name(caplog):
    name = "STD-Q 77 clause 4.2"
    rows = [
        {
            "finding_id": "f1",
            "row_kind": "standard_not_cited",
            "standard_reference": name,
        },
        {"finding_id": "f2", "row_kind": "missing_information"},
    ]
    coverage = {"pages_total": 1, "pages_not_read_into_fields": []}
    with caplog.at_level(logging.DEBUG):
        gate = crs_issue.open_items("run-1", rows, coverage)
    by_id = {i["finding_id"]: i for i in gate["open_findings"]}
    assert by_id["f1"]["standard"] == name
    assert by_id["f2"]["standard"] is None  # never a guessed name
    assert name not in caplog.text
    assert name not in " ".join(gate["blockers"])
    source = Path(crs_issue.__file__).read_text(encoding="utf-8")
    assert "logging" not in source and "logger" not in source
