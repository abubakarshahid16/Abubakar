"""Order 14 lane P: draft review playbooks for general contractor procedures (pressure test, welding, PMI),
built only from rule books the library holds.

INVENTED documents and an invented library only (CLAUDE.md rule 3): the books are invented COMPANY_STANDARD rows
carrying public designations, the page texts are invented sentences. The quotes in the shipped files are checked
against the real stored pages by `scripts/playbook_quote_check.py` on a database copy; here the check itself is
tested, with a forged quote that must fail.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app import crs_mapping, playbooks, procedure_playbook_rows
from tests.test_1522_procedure_playbook_rows import (
    _crs,
    _doc,
    _mine,
    _run,
    on,  # noqa: F401  (the switch fixture)
    temp_storage,  # noqa: F401  (a fresh database per test)
)
from tests.test_w5b_679_playbooks import hold

REF = Path(playbooks.__file__).parent / "reference"
NEW = ("pressure_test_procedure", "welding_procedure", "pmi_procedure")
QUOTED_BOOKS = {
    "pressure_test_procedure": {"SAES-A-004", "SAES-A-007"},
    "welding_procedure": {"SAES-W-011"},
    "pmi_procedure": {"SAES-A-206"},
}


def _found():
    found, broken = playbooks.available()
    assert broken == [], broken
    return found


# ------------------------------------------------------------------ the shipped files


def test_the_three_new_playbooks_load_with_every_element_citing_its_clause():
    found = _found()
    assert set(NEW) <= set(found)
    for pid in NEW:
        pb = found[pid]
        assert pb.document_kind == "procedure" and len(pb.elements) >= 10, pid
        for e in pb.elements:
            assert e.standard and e.clause and e.groups and e.expects, (pid, e.id)


def test_they_are_ai_drafts_for_an_engineer_to_confirm_and_never_signed_off():
    found = _found()
    for pid in NEW:
        pb = found[pid]
        assert pb.signed_off is False and pb.sign_off == {
            "status": "draft",
            "by": None,
            "date": None,
        }
        assert (
            pb.clauses_verified is False
        )  # not every element is verified (a book is missing), so the file says no
        assert pb.note.startswith("AI draft, engineer to confirm")
        assert "not been signed off" in playbooks.notice(pb)


def test_a_quoted_element_has_its_page_and_a_book_missing_element_has_no_quote():
    found = _found()
    for pid in NEW:
        quoted = [e for e in found[pid].elements if e.quote]
        assert quoted, pid
        for e in quoted:
            assert e.page and e.page >= 1 and e.verified, (pid, e.id)
            assert e.standard in QUOTED_BOOKS[pid], (pid, e.id, e.standard)
            assert len(e.quote.split()) <= 25, (
                pid,
                e.id,
            )  # a short quote, never a passage of the book
        for e in found[pid].elements:
            if e.standard not in QUOTED_BOOKS[pid]:
                assert not e.quote and e.page is None and not e.verified, (pid, e.id)


def test_every_title_has_a_cue_of_its_own():
    found = _found()
    cues = {
        pid: set(procedure_playbook_rows.title_cue(pb)) for pid, pb in found.items()
    }
    for pid, cue in cues.items():
        assert cue, pid
        for other, theirs in cues.items():
            if other != pid:
                assert not cue <= theirs, (
                    pid,
                    other,
                )  # a cover naming the other never chooses this one


@pytest.mark.parametrize(
    "cover, chosen",
    [
        (
            "Hydrostatic Pressure Test Procedure\nDocument PT-1 revision 0",
            ["pressure_test_procedure"],
        ),
        ("WELDING PROCEDURE\nDocument W-1", ["welding_procedure"]),
        (
            "Positive Material Identification (PMI) Procedure\nDocument M-1",
            ["pmi_procedure"],
        ),
        ("HAZOP Study Procedure\nDocument H-1", ["hazop_procedure"]),
    ],
)
def test_a_cover_chooses_only_its_own_playbook(cover, chosen):
    found = _found()
    text = procedure_playbook_rows.cover_text([(1, cover)])
    assert (
        sorted(
            pid
            for pid, pb in found.items()
            if procedure_playbook_rows.matches(pb, text)
        )
        == chosen
    )


def test_every_book_a_playbook_quotes_governs_a_procedure_in_the_kind_books_file():
    """Gate G2 fails a cited book the file does not list for the paper's kind."""
    from app.standard_ids import same_standard

    listed = [
        e["book"]
        for e in json.loads((REF / "kind_books.json").read_text(encoding="utf-8"))[
            "kinds"
        ]["procedure"]
    ]
    for pid in NEW:
        for book in QUOTED_BOOKS[pid]:
            assert any(same_standard(book, x) for x in listed), (pid, book)


# ------------------------------------------------------------------ the quote check


def _pb(elements):
    return playbooks.parse(
        {
            "format": "review-playbook/1",
            "id": "x",
            "title": "Invented check procedure",
            "version": "1",
            "elements": elements,
        },
        "invented",
    )


def _el(eid, standard, quote="", page=None, verified=False):
    source = {"standard": standard, "clause": "4.1"}
    if page is not None:
        source["page"] = page
    if quote:
        source.update(quote=quote, verified=verified)
    return {
        "id": eid,
        "title": f"Element {eid}",
        "expects": "x",
        "source": source,
        "evidence": [{"label": "a", "any": ["alpha"]}],
    }


LIBRARY = [
    {
        "id": "std_held",
        "filename": "STD-Q-210.pdf",
        "document_number": "STD-Q-210",
        "title": None,
    }
]
PAGE = "4.1 The test record shall be kept on site for the inspector at all times."


def _page_text(document_id, page):
    return PAGE if (document_id, page) == ("std_held", 3) else "an unrelated page"


def _states(elements):
    return {
        r["element"]: (r["state"], r["passed"])
        for r in playbooks.source_quote_checks(_pb(elements), LIBRARY, _page_text)
    }


def test_a_quote_on_its_page_of_a_held_book_passes_and_a_forged_one_fails():
    out = _states(
        [
            _el("E1", "STD-Q-210", "The test record shall be kept on site", 3, True),
            _el(
                "E2", "STD-Q-210", "The test record shall be kept off site", 3, True
            ),  # forged: one word changed
            _el(
                "E3", "STD-Q-210", "The test record shall be kept on site", 4, True
            ),  # the right words, the wrong page
            _el(
                "E4", "STD-Q-210", "The test record shall be kept on site", 3, False
            ),  # found, but the file says unverified
            _el("E5", "STD-Q-210"),  # a held book's element with no quote
            _el("E6", "STD-Z-999"),  # a book not held: book missing
            _el(
                "E7", "STD-Z-999", "The test record shall be kept on site", 3, True
            ),  # a quote of a book not held
            _el("E8", "STD-Q-210", "The test record shall be kept off site", 3, False),
        ]
    )
    assert out == {
        "E1": (playbooks.QUOTE_VERIFIED, True),
        "E2": (playbooks.FLAG_WRONG, False),
        "E3": (playbooks.FLAG_WRONG, False),
        "E4": (playbooks.FLAG_NOT_SET, False),
        "E5": (playbooks.NO_QUOTE, False),
        "E6": (playbooks.BOOK_MISSING_NO_QUOTE, True),
        "E7": (playbooks.QUOTE_OF_A_BOOK_NOT_HELD, False),
        "E8": (playbooks.QUOTE_NOT_ON_PAGE, False),
    }


def test_the_loader_refuses_a_quote_without_its_page_and_a_verified_flag_without_a_quote():
    with pytest.raises(
        playbooks.PlaybookError, match=r"E1: a source quote needs the page"
    ):
        _pb([_el("E1", "STD-Q-210", "some words of the book")])
    with pytest.raises(
        playbooks.PlaybookError,
        match=r"E2: source\.verified may be true only for a quote",
    ):
        bad = _el("E2", "STD-Q-210")
        bad["source"]["verified"] = True
        _pb([bad])
    for page in (0, "3", True):
        bad = _el("E3", "STD-Q-210", page=3)
        bad["source"]["page"] = page
        with pytest.raises(
            playbooks.PlaybookError, match=r"E3: source\.page must be a page number"
        ):
            _pb([bad])


def test_a_broken_new_playbook_file_is_listed_not_dropped(tmp_path):
    good = json.loads(
        (REF / "playbooks" / "pressure_test_procedure.json").read_text(encoding="utf-8")
    )
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    bad = copy.deepcopy(good)
    del bad["elements"][0]["source"]["page"]
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    found, broken = playbooks.available(tmp_path)
    assert set(found) == {"pressure_test_procedure"} and [
        b["file"] for b in broken
    ] == ["bad.json"]
    assert "PT01: a source quote needs the page" in broken[0]["reason"]


# ------------------------------------------------- a procedure's CRS: engineer rows only (P3)

PRESSURE_TEST_SECTIONS = [
    (
        "Scope",
        "This procedure applies to the hydrostatic test of the new plant piping systems listed in the test packs.",
    ),
    (
        "Test medium",
        "The test medium is fresh water; a water sample analysis for chlorides and bacteria is taken.",
    ),
    (
        "Test pressure",
        "The test pressure is 1.5 times the design pressure, with a hold of 60 minutes.",
    ),
    (
        "Gauges",
        "Two pressure gauges and one recorder are used; each gauge is calibrated within 30 days.",
    ),
    (
        "Isolation",
        "Each test section is isolated with spectacle blinds or blind flanges.",
    ),
]


@pytest.mark.usefixtures("on")
def test_a_pressure_test_procedure_gets_engineer_rows_only_and_none_is_a_firm_verdict():
    hold("SAES-A-004")
    hold("SAES-A-007")
    cover = "Hydrostatic Pressure Test Procedure\nDocument PT-1 revision 0"
    rows, _meta = _crs(_run(_doc("pt1", PRESSURE_TEST_SECTIONS, cover=cover)))
    mine = _mine(rows)
    pb = _found()["pressure_test_procedure"]
    assert len(mine) == len(pb.elements)
    for r in mine:
        assert r["engineer_confirmed"] is False and r["severity"] == ""
        assert r["priority"] == crs_mapping.PRIORITY_ENGINEER_TO_CHECK
        assert "compliant" not in r["comment"].lower()
        assert "not been signed off" in r["comment"]
    states = {r["comment_key"]: r["playbook_state"] for r in mine}
    key = crs_mapping.comment_key("playbook element", pb.id, "PT21")
    assert (
        states[key] == playbooks.STANDARD_NOT_HELD
    )  # GI-0002.102 is not held: never met
    gauges = next(r for r in mine if "Calibrated gauges" in r["comment"])
    assert (
        "found at" in gauges["comment"] and "engineer to confirm" in gauges["comment"]
    )
    assert "met" not in gauges["comment"].replace("meets", "")


def test_the_report_shows_the_book_page_and_that_its_quote_was_verified():
    hold("SAES-A-004")
    doc = _doc("pt2", PRESSURE_TEST_SECTIONS, cover="Pressure Test Procedure")
    from app.search import every_document_id

    report = playbooks.review(
        doc,
        _found()["pressure_test_procedure"],
        allowed_document_ids=every_document_id(),
    )
    by = {e["id"]: e for e in report["elements"]}
    assert (
        by["PT09"]["source"]["page"] == 16
        and by["PT09"]["source"]["quote_verified"] is True
    )
    assert by["PT09"]["standard_held"] is True
    assert (
        by["PT03"]["state"] == playbooks.STANDARD_NOT_HELD
    )  # SAES-A-007 is not held in this library
    assert "not a finding that it is met" in by["PT03"]["reason"]
    assert by["PT21"]["source"] == {"standard": "GI-0002.102", "clause": "5.1.2.5"}
    assert report["counts"]["total"] == len(report["elements"])
