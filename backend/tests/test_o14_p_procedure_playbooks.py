"""Order 14 lane P: draft review playbooks for general contractor procedures (pressure test, on-plot piping welding, PMI),
built only from rule books the library holds.

INVENTED documents and an invented library only (CLAUDE.md rule 3): the books are invented COMPANY_STANDARD rows
carrying public designations, the page texts are invented sentences. The quotes in the shipped files are checked
against the real stored pages by `scripts/playbook_quote_check.py` on a database copy, which records each verified
source's fingerprint (a hash, never text) in `fixtures/playbook_verified_quotes.json`; here the check itself is tested
with forged values, and every shipped verified source must still match its recorded fingerprint.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
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
REPO = Path(playbooks.__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "playbook_verified_quotes.json"
NEW = ("pressure_test_procedure", "piping_welding_procedure", "pmi_procedure")
QUOTED_BOOKS = {
    "pressure_test_procedure": {"SAES-A-004", "SAES-A-007"},
    "piping_welding_procedure": {"SAES-W-011"},
    "pmi_procedure": {"SAES-A-206"},
}


def _found():
    found, broken = playbooks.available()
    assert broken == [], broken
    return found


def _gates():
    sys.path.insert(0, str(REPO / "scripts"))
    import crs_gates

    return crs_gates


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
            assert playbooks.QUOTE_MIN_WORDS <= len(e.quote.split()) <= 25, (pid, e.id)
        for e in found[pid].elements:
            if e.standard not in QUOTED_BOOKS[pid]:
                assert not e.quote and e.page is None and not e.verified, (pid, e.id)


def test_every_shipped_verified_quote_is_the_one_the_check_verified():
    """A one-word change to a shipped quote, its page or its clause changes its fingerprint: CI fails until the quote
    check is run again on the stored pages (`scripts/playbook_quote_check.py --write-fixture`)."""
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    found = _found()
    shipped = {
        pb.id: {
            e.id: playbooks.source_fingerprint(e) for e in pb.elements if e.verified
        }
        for pb in found.values()
    }
    assert {k: v for k, v in shipped.items() if v} == recorded


def test_the_fingerprint_moves_with_one_word_of_the_quote_and_with_the_clause():
    e = next(e for e in _found()["pressure_test_procedure"].elements if e.verified)
    words = e.quote.split()
    forged = dataclasses.replace(e, quote=" ".join([*words[:-1], words[-1] + "x"]))
    assert playbooks.source_fingerprint(forged) != playbooks.source_fingerprint(e)
    assert playbooks.source_fingerprint(
        dataclasses.replace(e, clause=e.clause + ".9")
    ) != playbooks.source_fingerprint(e)
    assert playbooks.source_fingerprint(
        dataclasses.replace(e, quote="  ".join(words))
    ) == playbooks.source_fingerprint(e)


def test_conditional_elements_say_their_condition():
    found = _found()
    conditional = {
        pid: sorted(e.id for e in found[pid].elements if e.condition) for pid in NEW
    }
    assert conditional == {
        "pressure_test_procedure": ["PT03", "PT04", "PT05", "PT20"],
        "piping_welding_procedure": ["W09", "W10", "W11", "W17"],
        "pmi_procedure": [],
    }
    for pid, ids in conditional.items():
        for e in found[pid].elements:
            if e.id in ids:
                assert e.expects.startswith("When "), (pid, e.id)


# ---------------------------------------------------------------- which paper a playbook reaches


def _chosen(cover):
    text = procedure_playbook_rows.cover_text([(1, cover)])
    return sorted(
        pid for pid, pb in _found().items() if procedure_playbook_rows.matches(pb, text)
    )


@pytest.mark.parametrize(
    "cover, chosen",
    [
        (
            "Hydrostatic Pressure Test Procedure\nDocument PT-1 revision 0",
            ["pressure_test_procedure"],
        ),
        ("Hydrostatic Test Procedure\nDocument PT-2", ["pressure_test_procedure"]),
        ("HYDROTEST PROCEDURE FOR PLANT PIPING", ["pressure_test_procedure"]),
        ("Pneumatic Test Procedure", ["pressure_test_procedure"]),
        (
            "WELDING PROCEDURE SPECIFICATION FOR PIPING\nDocument W-1",
            ["piping_welding_procedure"],
        ),
        ("Welding Procedure for On-Plot Piping", ["piping_welding_procedure"]),
        ("WPS for carbon steel piping", ["piping_welding_procedure"]),
        (
            "Piping Fabrication, Welding and PMI Procedure",
            ["piping_welding_procedure", "pmi_procedure"],
        ),
        ("Positive Material Identification Procedure\nDocument M-1", ["pmi_procedure"]),
        ("PMI Procedure", ["pmi_procedure"]),
        ("HAZOP Study Procedure\nDocument H-1", ["hazop_procedure"]),
    ],
)
def test_a_cover_naming_the_type_chooses_its_playbook(cover, chosen):
    assert _chosen(cover) == chosen


@pytest.mark.parametrize(
    "cover",
    [
        "Pressure Safety Valve Bench Test Procedure",
        "Pressure Transmitter Calibration and Loop Test Procedure",
        "PRESSURE VESSEL V-101 FACTORY ACCEPTANCE TEST PROCEDURE",
        "Fire Water Pump Performance Test Procedure\nDischarge Pressure 10 bar",
        "Relief Valve Hydrostatic Test Procedure",
        "Pipeline Welding Procedure",
        "Structural Steel Welding Procedure",
        "Storage Tank Welding Procedure Specification",
        "Pressure Vessel Welding Procedure",
        "Welding Consumables Control Procedure",
        "Welding Machine Calibration Procedure",
        "Welding Procedure",  # SAES-W-011 1.1 is on-plot piping: a cover must name piping
        "WELDING PROCEDURE SPECIFICATION",
        "Rail Welding Procedure",
        "Underwater Welding Procedure",
        "Offshore Jacket Welding Procedure",
        "Pressure Gauge Calibration Procedure for Hydrostatic Test",  # a calibration procedure chooses none of the three
        "PMI Analyser Calibration Procedure",
        "Calibration of Piping WPS Welding Machines",
    ],
)
def test_a_cover_of_another_kind_of_work_chooses_no_new_playbook(cover):
    """Words of a cue scattered over the cover are not the phrase; a cover naming work outside the book's scope is out."""
    assert not set(_chosen(cover)) & set(NEW), cover


def test_every_title_is_a_cover_for_its_own_playbook_only():
    for pid, pb in _found().items():
        assert _chosen(pb.title) == [pid], pid


# ------------------------------------------------------------------ gate G2 per procedure type


def test_a_quoted_book_governs_only_the_procedure_type_its_playbook_covers():
    gates = _gates()
    path = REF / "kind_books.json"
    for pid in NEW:
        for book in QUOTED_BOOKS[pid]:
            assert (
                gates.mapping_from_file(path, "procedure", None, [pid]).judge(
                    book, "7.1"
                )[0]
                == "pass"
            ), (pid, book)
            for other in (
                [],
                ["hazop_procedure"],
                ["sil_procedure"],
                [p for p in NEW if p != pid],
            ):
                assert (
                    gates.mapping_from_file(path, "procedure", None, other).judge(
                        book, "7.1"
                    )[0]
                    == "fail"
                ), (pid, book, other)
    hazop = gates.mapping_from_file(path, "procedure", None, ["hazop_procedure"])
    assert hazop.judge("IEC 61882", "6.1")[0] == "pass"
    plain = json.loads(path.read_text(encoding="utf-8"))["kinds"]["procedure"]
    assert not {e["book"] for e in plain} & set().union(*QUOTED_BOOKS.values())


def test_the_type_of_a_procedure_paper_is_the_playbook_its_cover_chooses():
    gates = _gates()
    _doc(
        "pt1",
        [("Scope", "This procedure covers the hydrostatic test.")],
        cover="Hydrostatic Pressure Test Procedure",
    )
    _doc(
        "hz1",
        [("Scope", "This procedure covers the HAZOP study.")],
        cover="HAZOP Procedure",
    )
    assert gates.procedure_types("pt1", "procedure") == ["pressure_test_procedure"]
    assert gates.procedure_types("hz1", "procedure") == ["hazop_procedure"]
    assert gates.procedure_types("pt1", "datasheet") == []


# ------------------------------------------------------------------ the quote check


def _pb(elements, **top):
    return playbooks.parse(
        {
            "format": "review-playbook/1",
            "id": "x",
            "title": "Invented check procedure",
            "version": "1",
            "elements": elements,
            **top,
        },
        "invented",
    )


QUOTE = "The test record shall be kept on site for the inspector"


def _el(eid, standard, quote="", page=None, verified=False, clause="4.1"):
    source = {"standard": standard, "clause": clause}
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
PAGE = "4.1 The test record shall be kept on site for the inspector at all times.\n14.1 Another clause."


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
            _el("E1", "STD-Q-210", QUOTE, 3, True),
            _el(
                "E2", "STD-Q-210", QUOTE.replace("on site", "off site"), 3, True
            ),  # forged: one word changed
            _el("E3", "STD-Q-210", QUOTE, 4, True),  # the right words, the wrong page
            _el(
                "E4", "STD-Q-210", QUOTE, 3, False
            ),  # found, but the file says unverified
            _el("E5", "STD-Q-210"),  # a held book's element with no quote
            _el("E6", "STD-Z-999"),  # a book not held: book missing
            _el("E7", "STD-Z-999", QUOTE, 3, True),  # a quote of a book not held
            _el("E8", "STD-Q-210", QUOTE.replace("on site", "off site"), 3, False),
            _el(
                "E9", "STD-Q-210", "shall be kept on site", 3, True
            ),  # a fragment under the floor
            _el(
                "E10", "STD-Q-210", QUOTE, 3, True, clause="4.2"
            ),  # the clause is not on the page
            _el(
                "E11", "STD-Q-210", QUOTE, 3, True, clause="4"
            ),  # "4" only inside "4.1": not on the page
            _el(
                "E12", "STD-Q-210", QUOTE, 3, True, clause="14"
            ),  # "14" only inside "14.1"
        ]
    )
    assert out == {
        "E1": (playbooks.QUOTE_VERIFIED, True),
        "E2": (playbooks.FLAG_WRONG, False),
        "E3": (playbooks.CLAUSE_NOT_ON_PAGE, False),
        "E4": (playbooks.FLAG_NOT_SET, False),
        "E5": (playbooks.NO_QUOTE, False),
        "E6": (playbooks.BOOK_MISSING_NO_QUOTE, True),
        "E7": (playbooks.QUOTE_OF_A_BOOK_NOT_HELD, False),
        "E8": (playbooks.QUOTE_NOT_ON_PAGE, False),
        "E9": (playbooks.QUOTE_TOO_SHORT, False),
        "E10": (playbooks.CLAUSE_NOT_ON_PAGE, False),
        "E11": (playbooks.CLAUSE_NOT_ON_PAGE, False),
        "E12": (playbooks.CLAUSE_NOT_ON_PAGE, False),
    }


def test_the_loader_refuses_bad_sources_conditions_and_cue_lists():
    with pytest.raises(
        playbooks.PlaybookError, match=r"E1: a source quote needs the page"
    ):
        _pb([_el("E1", "STD-Q-210", "some words of the book")])
    bad = _el("E2", "STD-Q-210")
    bad["source"]["verified"] = True
    with pytest.raises(
        playbooks.PlaybookError,
        match=r"E2: source\.verified may be true only for a quote",
    ):
        _pb([bad])
    for page in (0, "3", True):
        bad = _el("E3", "STD-Q-210", page=3)
        bad["source"]["page"] = page
        with pytest.raises(
            playbooks.PlaybookError, match=r"E3: source\.page must be a page number"
        ):
            _pb([bad])
    for cond in (
        {"label": "", "any": ["x"]},
        {"label": "x", "any": []},
        {"label": "x"},
    ):
        bad = _el("E4", "STD-Q-210")
        bad["applies_when"] = cond
        with pytest.raises(playbooks.PlaybookError, match=r"E4 applies_when"):
            _pb([bad])
    for cues in ("pressure test", [""], [3]):
        with pytest.raises(playbooks.PlaybookError, match=r"title_cues must be a list"):
            _pb([_el("E5", "STD-Q-210")], title_cues=cues)


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
    assert "PT02: a source quote needs the page" in broken[0]["reason"]


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
        assert (
            r["comment"].count(
                "An engineer also confirms that each cited book governs this procedure."
            )
            == 1
        )
    states = {r["comment_key"]: (r["playbook_state"], r["comment"]) for r in mine}

    def state(eid):
        return states[crs_mapping.comment_key("playbook element", pb.id, eid)]

    assert (
        state("PT21")[0] == playbooks.STANDARD_NOT_HELD
    )  # GI-0002.102 is not held: never met
    for eid in (
        "PT04",
        "PT05",
        "PT03",
        "PT20",
    ):  # a hydro-only paper is never told the pneumatic test is "missing"
        got, comment = state(eid)
        assert got == playbooks.CONDITION_NOT_STATED, eid
        assert (
            "applies only when the procedure covers" in comment
            and "engineer to check" in comment
        )
        assert "not found" not in comment
    gauges = next(r for r in mine if "Calibrated gauges" in r["comment"])
    assert (
        "found at" in gauges["comment"] and "engineer to confirm" in gauges["comment"]
    )


WELDING_SECTIONS = [
    ("Welding procedures", "Each WPS is submitted with its PQR before welding starts."),
    (
        "Heat treatment",
        "Post weld heat treatment uses electric resistance heating pads with thermocouples at each joint.",
    ),
]


def test_a_condition_the_paper_names_is_checked_as_usual():
    hold("SAES-W-011")
    from app.search import every_document_id

    pb = _found()["piping_welding_procedure"]
    doc = _doc("w1", WELDING_SECTIONS, cover="Piping Welding Procedure")
    by = {
        e["id"]: e
        for e in playbooks.review(doc, pb, allowed_document_ids=every_document_id())[
            "elements"
        ]
    }
    assert (
        by["W09"]["state"] == playbooks.PRESENT
    )  # PWHT is named, so its element is checked
    assert by["W17"]["state"] == playbooks.CONDITION_NOT_STATED  # no alloy is named
    doc2 = _doc("w2", WELDING_SECTIONS[:1], cover="Piping Welding Procedure")
    by2 = {
        e["id"]: e
        for e in playbooks.review(doc2, pb, allowed_document_ids=every_document_id())[
            "elements"
        ]
    }
    assert by2["W09"]["state"] == playbooks.CONDITION_NOT_STATED
    assert (
        by2["W01"]["state"] != playbooks.CONDITION_NOT_STATED
    )  # an element without a condition is never one


def test_a_conditional_element_of_a_paper_not_read_in_full_is_never_condition_not_stated():
    """Absence proves nothing in a paper not read in full: the element stays "could not be checked"."""
    from app import db
    from app.search import every_document_id

    hold("SAES-W-011")
    doc = _doc("w3", WELDING_SECTIONS[:1], cover="Piping Welding Procedure")
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET needs_ocr = 1 WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    report = playbooks.review(
        doc,
        _found()["piping_welding_procedure"],
        allowed_document_ids=every_document_id(),
    )
    by = {e["id"]: e for e in report["elements"]}
    assert report["document"]["read_in_full"] is False
    for eid in ("W09", "W10", "W11", "W17"):
        assert by[eid]["state"] == playbooks.COULD_NOT_BE_CHECKED, eid
    assert report["counts"][playbooks.CONDITION_NOT_STATED] == 0


def test_a_condition_named_only_in_a_heading_counts():
    from app import db
    from app.search import every_document_id

    hold("SAES-A-004")
    hold("SAES-A-007")
    doc = _doc(
        "pt3",
        [("Pneumatic test", "The test is made with dry air after the leak check.")],
        cover="Pressure Test Procedure",
    )
    with (
        db.connect() as conn
    ):  # the passage's own text without its heading: the heading lives in the section title only
        conn.execute(
            "UPDATE chunks SET text = ? WHERE document_id = ?",
            ("The test is made with dry air after the leak check.", doc),
        )
    by = {
        e["id"]: e
        for e in playbooks.review(
            doc,
            _found()["pressure_test_procedure"],
            allowed_document_ids=every_document_id(),
        )["elements"]
    }
    assert by["PT04"]["state"] != playbooks.CONDITION_NOT_STATED
    assert by["PT05"]["state"] != playbooks.CONDITION_NOT_STATED
    assert (
        by["PT03"]["state"] == playbooks.CONDITION_NOT_STATED
    )  # no chemical treatment anywhere


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
