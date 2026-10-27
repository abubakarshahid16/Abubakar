"""R7 (#771): a submittal that cites one edition of a standard while the library holds another
is SAID, never read as the same edition silently.

Three ways, honestly: same, different, or not known. Nothing is said when either year is not
printed, when the citation carries two different years, or when the held copy prints two. A
standard's own number, a pressure rating and a date are not editions. Invented data only.
"""

from __future__ import annotations

import pytest

from app import cited_edition, standard_ids
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401
from tests.test_review_screen import world  # noqa: F401


def _find(library, identifier):
    return [e for e in library if standard_ids.same_standard(identifier, e["filename"])]


def _years(text):
    return {
        key: year for key, (_ident, year) in cited_edition.cited_years(text).items()
    }


@pytest.mark.parametrize(
    "text, key, year",
    [
        ("Tank to API 650 (2013).", "API 650", "2013"),
        ("Tank to API 650-2013 and more.", "API 650", "2013"),
        ("Tank to API 650: 2013.", "API 650", "2013"),
        ("Tank to API 650, edition 2013, welded.", "API 650", "2013"),
        ("Tank to API 650 2013.", "API 650", "2013"),
        ("Tank to API 650.", "API 650", None),
        (
            "Fire protection per NFPA 2001.",
            "NFPA 2001",
            None,
        ),  # the standard's own number
        ("Flanges ASME B16.5 2000 psi class.", "ASME B 16.5", None),  # a rating
        ("Valve per API 526, 7th edition.", "API 526", None),  # no year printed
    ],
)
def test_the_year_printed_after_a_citation_is_read_only_when_it_is_one(text, key, year):
    assert _years(text)[key] == year


def test_a_standard_cited_under_two_years_has_no_year():
    assert _years("QA per ISO 9001:2008, and ISO 9001:2015 audits.")["ISO 9001"] is None


def test_the_held_year_is_read_from_the_file_name_or_the_title_and_only_when_unambiguous():
    assert cited_edition.held_year({"filename": "API-650-2020.pdf"}) == "2020"
    assert (
        cited_edition.held_year({"filename": "API-650.pdf", "title": "API 650, 2018"})
        == "2018"
    )
    assert cited_edition.held_year({"filename": "API-650.pdf"}) is None
    # two years: nothing is claimed
    assert (
        cited_edition.held_year(
            {"filename": "API 610 2010.pdf", "title": "API 610, January 2021"}
        )
        is None
    )
    # a standard's own number is not an edition
    assert cited_edition.held_year({"filename": "NFPA 2001.pdf"}) is None


LIBRARY = [
    {"id": "d1", "filename": "API-650-2020.pdf"},
    {"id": "d2", "filename": "API-526.pdf"},
    {"id": "d3", "filename": "ASME B16.5-2020.pdf"},
]


def _differs(text):
    return cited_edition.differs(text, LIBRARY, _find)


def test_a_different_edition_is_said_with_which_is_older():
    [item] = _differs("Tank to API 650 (2013).")
    assert (item["identifier"], item["cited"], item["held"], item["relation"]) == (
        "API 650",
        "2013",
        "2020",
        "older",
    )
    [newer] = _differs("Tank to API 650 (2024).")
    assert newer["relation"] == "newer"


@pytest.mark.parametrize(
    "text",
    [
        "Tank to API 650 (2020).",  # the same edition
        "Tank to API 650.",  # no cited year: not known
        "Valve per API 526 (2014).",  # the held copy prints no year: not known
        "Flanges ASME B16.5 2000 psi class.",  # a rating, not an edition
        "Tank to API 650 (2013) and API 650 (2018).",  # two years for one standard
        "Pump to API 610 (2005).",  # not in the library: the missing-standards note's job
    ],
)
def test_nothing_is_said_when_the_editions_agree_or_one_side_is_not_known(text):
    assert _differs(text) == []


def test_the_note_is_for_the_engineer_and_says_what_was_checked():
    [note] = cited_edition.notes(_differs("Tank to API 650 (2013)."))
    assert note["note"] == cited_edition.NOTE and note["standard"] == "API 650"
    detail = note["detail"]
    assert "cites API 650 (2013)" in detail and "API-650-2020.pdf (2020)" in detail
    # the direction is said about the CITED edition, and it is the true one (s3's review)
    assert "The cited edition is older than the held one" in detail
    assert "checked the requirements of the held edition" in detail
    [newer] = cited_edition.notes(_differs("Tank to API 650 (2024)."))
    assert "The cited edition is newer than the held one" in newer["detail"]


def test_for_submittal_reads_the_submittal_and_the_library_it_may_see(temp_storage):  # noqa: F811
    std = _doc("std", "API-650-2020.pdf", "COMPANY_STANDARD", document_number="API 650")
    sub = _doc(
        "sub", "tank.pdf", "CONTRACTOR_SUBMITTAL", text="Tank shell to API 650 (2013)."
    )
    [note] = cited_edition.for_submittal(sub, _scope(sub, std))
    assert note["standard"] == "API 650" and "(2013)" in note["detail"]
    # a standard the caller may not read is not compared
    assert cited_edition.for_submittal(sub, _scope(sub)) == []
    # the same edition: nothing
    same = _doc(
        "sub2",
        "tank2.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Tank shell to API 650 (2020).",
    )
    assert cited_edition.for_submittal(same, _scope(same, std)) == []


def test_the_crs_review_notes_carry_the_edition_note(world, monkeypatch):  # noqa: F811
    """The wiring: `main._crs_content` puts the notes on the Review notes sheet (internal), after
    the missing-standards notes and before the 'Not checked' ones."""
    from app import main
    from app.access import AccessScope

    sub, run, scope = world
    seen = {}

    def fake(submittal_id, allowed):
        seen["args"] = (submittal_id, allowed)
        return [
            {
                "note": cited_edition.NOTE,
                "standard": "STD-X",
                "count": None,
                "detail": "d",
            }
        ]

    monkeypatch.setattr(main.cited_edition_mod, "for_submittal", fake)
    _rows, meta, *_ = main._crs_content(
        run, AccessScope(user_id="eng-1", allowed_document_ids=scope)
    )
    notes = [n for n in meta["review_notes"] if n["note"] == cited_edition.NOTE]
    assert [n["standard"] for n in notes] == ["STD-X"]
    assert seen["args"][0] == sub and seen["args"][1] == scope


def test_two_held_editions_say_nothing_when_one_of_them_is_the_cited_one():
    """cloud-2's review: whichever copy a lookup returned used to decide."""
    two = [
        {"id": "a", "filename": "API-610-2013.pdf"},
        {"id": "b", "filename": "API-610-2021.pdf"},
    ]
    assert cited_edition.differs("Pump to API 610 (2013).", two, _find) == []
    assert cited_edition.differs("Pump to API 610 (2021).", two, _find) == []
    [item] = cited_edition.differs("Pump to API 610 (2005).", two, _find)
    assert (
        item["held"] == "2013" and item["relation"] == "older"
    )  # the nearest held edition
    # a held copy that prints no year could be the cited one: nothing is claimed
    mixed = [*two, {"id": "c", "filename": "API-610.pdf"}]
    assert cited_edition.differs("Pump to API 610 (2005).", mixed, _find) == []


def test_a_check_that_cannot_run_says_so_and_does_not_fail_the_export(monkeypatch):
    from app import applicability

    def boom(*_args):
        raise RuntimeError("secret document text must not appear")

    monkeypatch.setattr(applicability, "_submittal_text", boom)
    [note] = cited_edition.for_submittal("sub", frozenset({"sub"}))
    assert note["note"] == cited_edition.NOTE
    assert note["detail"] == "The cited-edition check could not run (RuntimeError)."
    assert "secret" not in note["detail"]
