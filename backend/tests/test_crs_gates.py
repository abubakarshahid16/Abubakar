"""The shared gates G1 to G7 (owner order 14): each gate PASSES a good row and FAILS each bad case the owner named. Invented data only:
no client paper, no real book text, invented book names (STD-A-100 ...)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app import agent_review_pass_guards as guards
from tests.test_agent_review_routes import (
    client,  # noqa: F401 - fixture: a finished AI run on an invented paper
)

_SPEC = importlib.util.spec_from_file_location(
    "crs_gates", Path(__file__).resolve().parents[2] / "scripts" / "crs_gates.py"
)
g = importlib.util.module_from_spec(_SPEC)
sys.modules["crs_gates"] = g  # the dataclasses look their module up by name
_SPEC.loader.exec_module(g)
FAIL, NOT_RUN, PASS, UNDECIDED, Row = g.FAIL, g.NOT_RUN, g.PASS, g.UNDECIDED, g.Row

BOOK_TEXT = {
    3: "4.1 Relief devices. The inlet pressure loss shall not exceed three percent of the set pressure.",
    4: "4.2 Each device shall be marked with its set pressure and its capacity in the units of the order.",
}


class _Books:
    """`BookPages` stand-in: one invented book, held as doc_std."""

    def book(self, doc):
        return guards.Book(BOOK_TEXT if doc == "doc_std" else {})


# ------------------------------------------------------------------------------------------------ G1


def test_g1_passes_a_quote_that_stands_word_for_word_in_the_book():
    r = Row(
        "E1",
        quotes=("the inlet pressure loss shall not exceed three percent",),
        quote_docs=("doc_std",),
        quote_page=3,
    )
    got = g.g1_quotes([r], _Books())
    assert got.status == PASS and got.checked == 1


def test_g1_fails_checklist_wording_shown_as_the_books_words():
    checklist = Row(
        "E2",
        quotes=("Inlet loss max 3% and stated on the sheet",),
        quote_docs=("doc_std",),
        quote_page=3,
    )
    got = g.g1_quotes([checklist], _Books())
    assert got.status == FAIL and got.failed == [("E2", "quote not in the stored book")]


def test_g1_fails_a_quote_with_no_held_book_and_one_bad_quote_of_two():
    nobook = Row(
        "E3", quotes=("the inlet pressure loss shall not exceed three percent",)
    )
    mixed = Row("R4", quotes=("each device shall be marked with its set pressure", "our own checklist sentence here"),
                quote_docs=("doc_std",))  # fmt: skip
    got = g.g1_quotes([nobook, mixed], _Books())
    assert got.status == FAIL and dict(got.failed) == {
        "E3": "no held book to search",
        "R4": "quote not in the stored book",
    }


def test_g1_is_not_run_when_no_row_shows_a_quote():
    assert g.g1_quotes([Row("E5")], _Books()).status == NOT_RUN


# ------------------------------------------------------------------------------------------------ G2


def _mapping(tmp_path, kinds):
    p = tmp_path / "kind_books.json"
    p.write_text(
        json.dumps({"format": g.MAPPING_FORMAT, "kinds": kinds}), encoding="utf-8"
    )
    return p


def test_g2_clause_prefixes_cover_sub_clauses_but_never_a_longer_number():
    assert (
        g.clause_in("UG-150(a)", ["UG-150"])
        and g.clause_in("UG-150.1", ["UG-150"])
        and g.clause_in("ug-150", ["UG-150"])
    )
    assert not g.clause_in("UG-1500", ["UG-150"]) and not g.clause_in("2.5", ["UG-150"])
    assert g.clause_in("anything", None)


def test_g2_with_a_mapping_file_passes_a_governing_clause_and_fails_the_wrong_appendix_and_a_book_not_listed(
    tmp_path,
):
    path = _mapping(tmp_path, {
        "datasheet|relief valve": [{"book": "STD-A-100"}, {"book": "STD-B-200", "clauses": ["UG-150", "UG-151"]}],
        "datasheet": [{"book": "STD-C-300"}],
    })  # fmt: skip
    books = g.mapping_from_file(path, "datasheet", "relief valve")
    good = Row("E1", clauses=(("STD-A-100", "4.1.4.4"), ("STD-B-200", "UG-150(b)")))
    wrong_appendix = Row("E2", clauses=(("STD-B-200", "2.5"),))
    other_book = Row(
        "E3", clauses=(("STD-C-300", "1.1"),)
    )  # only under the plain kind; the specific key wins
    got = g.g2_books(
        [good, wrong_appendix, other_book], books, "datasheet", "relief valve"
    )
    assert got.status == FAIL and got.checked == 4
    assert dict(got.failed) == {
        "E2": "clause outside the part of the book that governs this kind: clause 2.5",
        "E3": "book not listed for this kind: clause 1.1",
    }
    assert got.counts == {
        "clause outside the part of the book that governs this kind": 1,
        "book not listed for this kind": 1,
    }
    assert g.g2_books([good], books, "datasheet", "relief valve").status == PASS


def test_g2_without_a_mapping_says_so_and_invents_none(tmp_path):
    path = _mapping(tmp_path, {"contract": [{"book": "STD-A-100"}]})
    assert g.mapping_from_file(path, "procedure", None) is None
    got = g.g2_books(
        [Row("E1", clauses=(("STD-A-100", "1"),))], None, "procedure", None
    )
    assert got.status == NOT_RUN and got.note.startswith(
        "G2 not run: no kind-to-book mapping"
    )


def test_g2_refuses_a_file_of_another_format(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"kinds": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        g.mapping_from_file(p, "datasheet", None)


def test_g2_with_the_app_tables_fails_a_design_book_on_a_procedure_and_leaves_a_part_book_undecided(
    monkeypatch,
):
    from app import applicability, kind_standards

    monkeypatch.setattr(kind_standards, "table", lambda path=None: {
        "kinds_apply": {"procedure": ["process/method", "general"], "datasheet": ["equipment design", "general"]},
        "method_standards": {"procedure": ["STD-M-10"]},
        "standards": {"STD-D-1": "equipment design", "STD-M-10": "process/method"},
    })  # fmt: skip
    monkeypatch.setattr(applicability, "governing_table", lambda path=None: {
        "equipment_types": {"relief valve": ["STD-A-100"]}, "materials_standards": ["STD-MAT-5"],
        "partial_standards": {"relief valve": [{"standard": "STD-B-200", "words": ["relief"]}]}, "equipment_subtypes": {},
    })  # fmt: skip
    proc = g.mapping_from_app("procedure", None)
    got = g.g2_books(
        [
            Row("E1", clauses=(("STD-D-1", "3.2"),)),
            Row("E2", clauses=(("STD-M-10", "5"),)),
        ],
        proc,
        "procedure",
        None,
    )
    assert got.status == FAIL and got.failed == [
        ("E1", "book does not govern this kind: clause 3.2")
    ]
    valve = g.mapping_from_app("datasheet", "relief valve")
    rows = [Row("E3", clauses=(("STD-A-100", "4.1"),)), Row("E4", clauses=(("STD-MAT-5", "A.1"),)),
            Row("E5", clauses=(("STD-B-200", "UG-150"),)), Row("E6", clauses=(("STD-X-9", "1"),))]  # fmt: skip
    got = g.g2_books(rows, valve, "datasheet", "relief valve")
    assert got.status == UNDECIDED and not got.failed and got.checked == 4
    assert got.counts == {
        "not judged: book governs this kind in part; clause range not given": 1,
        "not judged: no entry for this book": 1,
    }
    assert g.mapping_from_app("unknown kind", None) is None


def test_g2_skips_a_row_that_names_no_clause():
    got = g.g2_books(
        [Row("E1", clauses=(("STD-A-100", ""),))],
        g.KindBooks("t", [{"book": "STD-A-100"}]),
        "datasheet",
        None,
    )
    assert got.status == NOT_RUN and got.checked == 0


# ------------------------------------------------------------------------------------------------ G1 and G2: cut quotes, fused names


def test_g1_checks_a_cut_quote_piece_by_piece_in_order():
    cut_ok = Row(
        "R1",
        quotes=("The inlet pressure loss shall not exceed ... of the set pressure.",),
        quote_docs=("doc_std",),
        quote_page=3,
    )
    assert g.g1_quotes([cut_ok], _Books()).status == PASS
    over_pages = Row(
        "R2",
        quotes=("three percent of the set pressure. ... Each device shall be marked",),
        quote_docs=("doc_std",),
    )
    assert (
        g.g1_quotes([over_pages], _Books()).status == PASS
    )  # the next piece on the next page
    half_wrong = Row(
        "R3",
        quotes=(
            "The inlet pressure loss shall not exceed ... our own checklist words here",
        ),
        quote_docs=("doc_std",),
    )
    assert g.g1_quotes([half_wrong], _Books()).failed == [
        ("R3", "quote not in the stored book")
    ]
    backwards = Row(
        "R4",
        quotes=("of the set pressure ... The inlet pressure loss shall not",),
        quote_docs=("doc_std",),
        quote_page=3,
    )
    assert g.g1_quotes([backwards], _Books()).failed == [
        ("R4", "pieces not in the book's order")
    ]
    two_pages_back = Row(
        "R5",
        quotes=("Each device shall be marked ... The inlet pressure loss",),
        quote_docs=("doc_std",),
    )
    assert g.g1_quotes([two_pages_back], _Books()).failed == [
        ("R5", "pieces not in the book's order")
    ]
    assert g.quote_pieces("each device shall be marked … in the units of the order") == [
        "each device shall be marked", "in the units of the order",
    ]  # fmt: skip
    assert g.quote_pieces("loss shall not exceed ...") == [
        "loss shall not exceed"
    ]  # a mark at the end is no piece


def test_g1_fails_a_short_piece_never_drops_it():
    changed_tail = Row(
        "R1",
        quotes=("The inlet pressure loss shall not exceed ... 5%",),
        quote_docs=("doc_std",),
        quote_page=3,
    )
    assert g.g1_quotes([changed_tail], _Books()).failed == [
        ("R1", "piece too short to check")
    ]
    assert g.g1_quotes(
        [Row("R2", quotes=("ab ... cd",), quote_docs=("doc_std",))], _Books()
    ).failed == [("R2", "piece too short to check")]


def test_a_book_name_that_carries_its_clause_is_read_as_book_and_clause():
    assert g.split_fused("STD-A-100 4.2") == ("STD-A-100", "4.2")
    assert g.split_fused("STD-A-100 clause 4.1.4.4") == ("STD-A-100", "4.1.4.4")
    assert g.split_fused("STD-A-100 4.2", "5.1") == (
        "STD-A-100 4.2",
        "5.1",
    )  # the row's own clause wins
    assert g.split_fused("STD-A-100 2009") == (
        "STD-A-100 2009",
        "",
    )  # an edition year is not a clause
    assert g.split_fused("API 526 2009") == ("API 526 2009", "")
    assert g.split_fused("API 521") == ("API 521", "") and g.split_fused(
        "API RP 520 Pt-2"
    ) == ("API RP 520 Pt-2", "")


def _rc_point(name, **over):
    return {"id": "rc:k1", "rank": 3, "rule_ref": {"name": name, "clause": ""}, "rule_text": "each device shall be marked with its set pressure",
            "_book_docs": [], "books": [], **over}  # fmt: skip


def test_g1_finds_the_held_book_of_a_fused_name_and_says_not_in_the_book():
    held = g._point_row("E1", _rc_point("STD-A-100 4.2"), LIBRARY)
    assert (
        held.quote_docs == ("doc_std",)
        and held.clause == "4.2"
        and held.book == "STD-A-100"
    )
    assert g.g1_quotes([held], _Books()).status == PASS
    wrong = g._point_row(
        "E2",
        _rc_point("STD-A-100 4.2", rule_text="a checklist sentence not in the book"),
        LIBRARY,
    )
    assert g.g1_quotes([wrong], _Books()).failed == [
        ("E2", "quote not in the stored book")
    ]
    missing = g._point_row("E3", _rc_point("STD-Z-900 1.1"), LIBRARY)
    assert g.g1_quotes([missing], _Books()).failed == [("E3", "no held book to search")]


def test_g2_counts_and_fails_a_fused_clause_on_a_kind_its_book_does_not_govern():
    row = g._point_row("E1", _rc_point("STD-D-1 3.2"), LIBRARY)
    books = g.KindBooks("t", [{"book": "STD-M-10"}], does_not=["STD-D-1"])
    got = g.g2_books([row], books, "procedure", None)
    assert (
        got.status == FAIL
        and got.checked == 1
        and got.failed == [("E1", "book does not govern this kind: clause 3.2")]
    )


# ------------------------------------------------------------------------------------------------ G3


@pytest.mark.parametrize("words", [
    "Searched pages 1 to 4: found none.", "None found on the sheet.", "One reader's view: No correction needed.",
    "no corrections required", "Page 3 could not be read.", "the table cannot be read", "No action required.",
    "No change needed.", "No changes are required", "Nothing to correct.", "Correction not needed.", "no correction necessary",
    "Nothing found.", "No findings.", "None.", "The page is not readable.", "page 4 is not readable by the code",
    "It is not something a valve data sheet has to state.", "The sheet does not have to state it.",
    "Both are stated as Required on every sheet, which meets the accessories requirement.",
])  # fmt: skip
def test_g3_fails_each_noise_phrase(words):
    got = g.g3_noise([Row("C1", cells=("Set pressure", words))])
    assert got.status == FAIL and got.failed[0][0] == "C1"


def test_g3_passes_a_real_comment_and_close_but_honest_words():
    rows = [Row("C1", rank=3, cells=("Set pressure", "Contractor to state the set pressure against STD-A-100 clause 4.2.")),
            Row("C2", rank=4, cells=("Body", "The value could not be confirmed against the rule; the engineer decides.")),
            Row("C3", rank=3, cells=("Set pressure", "The paper does not state the set pressure.")),
            Row("C4", rank=4, cells=("Body", "Contractor to confirm the body material meets the rule.")),
            Row("C5", rank=4, reason="value_deferred", cells=("Seal", "No finding can be made until the vendor fills the field."))]  # fmt: skip
    assert g.g3_noise(rows).status == PASS


@pytest.mark.parametrize("rank, reason, why", [
    (5, "", "class Met"), (6, "", "class Met"), (7, "", "class Met"), (8, "", "class Does not apply"),
    (4, "pass_field_unknown", "pass reason"), (4, "met", "pass reason"), (3, "PASS_value", "pass reason"),
])  # fmt: skip
def test_g3_fails_a_row_whose_class_or_reason_says_nothing_is_to_be_corrected(
    rank, reason, why
):
    got = g.g3_noise(
        [
            Row(
                "C1",
                rank=rank,
                reason=reason,
                cells=("Lifting lever", "Contractor to confirm the lever."),
            )
        ]
    )
    assert got.failed == [("C1", why)]


def test_g3_never_fails_a_row_that_asks_for_a_deferred_value():
    rows = [Row("C1", rank=4, reason="pass_field_not_quoted", paper_value="Back pressure: By Contractor",
                cells=("Back pressure", "Contractor to provide the back pressure.")),
            Row("C2", rank=8, paper_value="TBA", cells=("Seal plan", "Does not apply"))]  # fmt: skip
    got = g.g3_noise(rows)
    assert got.status == PASS and "2 ask for a deferred value" in got.note
    got = g.g3_noise(
        [Row("C3", rank=4, reason="pass_field_not_quoted", paper_value="150 psig")]
    )
    assert got.failed == [
        ("C3", "pass reason")
    ]  # a real value with a pass reason still fails


# ------------------------------------------------------------------------------------------------ G4


def test_g4_fails_two_comments_on_one_field_written_two_ways():
    rows = [Row("C1", field="Set pressure"), Row("C2", field="SET PRESSURE:"), Row("C3", field="Overpressure"),
            Row("C4", field="Over pressure %")]  # fmt: skip
    got = g.g4_one_per_field(rows)
    assert got.status == FAIL and sorted(i for i, _w in got.failed) == [
        "C1",
        "C2",
        "C3",
        "C4",
    ]


def _near(rid, field, line="", clause=""):
    return Row(
        rid,
        field=field,
        paper_lines=(line,) if line else (),
        clauses=(("STD-A-100", clause),) if clause else (),
    )


def test_g4_fails_near_same_fields_only_when_they_share_a_paper_line_or_a_clause():
    rows = [_near("C1", "Compressibility factor", line="Compressibility factor Z 0.98"), _near("C2", "Compressibility", line="Compressibility factor Z 0.98"),
            _near("C3", "Required relieving capacity", clause="5.4"), _near("C4", "Required capacity", clause="5.4")]  # fmt: skip
    got = g.g4_one_per_field(rows)
    assert dict(got.failed) == {"C1": "near-same field as C2", "C2": "near-same field as C1", "C3": "near-same field as C4",
                                "C4": "near-same field as C3"}  # fmt: skip
    # with nothing shared the pair is UNDECIDED: counted and printed apart, never a pass
    got = g.g4_one_per_field(
        [
            _near("C1", "Compressibility factor", clause="5.1"),
            _near("C2", "Compressibility", clause="6.2"),
        ]
    )
    assert got.status == UNDECIDED and not got.failed and "C1/C2" in got.note
    assert got.counts == {
        "not judged: near-same pair, no shared paper line or clause": 1
    }


def test_g4_the_four_back_pressure_comments_on_one_sheet_line_fail():
    line = "Back press. Constant/Variable: By Contractor"
    rows = [_near("C5", "Valve type / Back press. Constant/Variable", line=line), _near("C6", "Back press. variable", line=line),
            _near("C7", "Back press. constant", line=line), _near("C8", "Back press. constant/variable", line=line)]  # fmt: skip
    assert sorted(i for i, _w in g.g4_one_per_field(rows).failed) == [
        "C5",
        "C6",
        "C7",
        "C8",
    ]


@pytest.mark.parametrize("a, b", [
    ("Set pressure", "Cold differential set pressure"), ("Back pressure", "Built-up back pressure"),
    ("Back pressure", "Superimposed back pressure"), ("Orifice area", "Effective orifice area"),
    ("Design temperature", "Minimum design temperature"), ("Nozzle notes", "Nozzle notes (M7) gasket dimensions"),
])  # fmt: skip
def test_g4_truly_different_near_same_names_are_undecided_never_failed(a, b):
    got = g.g4_one_per_field([_near("C1", a, line="first line of the sheet", clause="1.1"),
                              _near("C2", b, line="another line entirely", clause="2.2")])  # fmt: skip
    assert got.status == UNDECIDED and not got.failed


def test_g4_word_brackets_keep_fields_apart_and_reference_brackets_are_near_same():
    rows = [Row("C1", field="Design pressure (shell side)"), Row("C2", field="Design pressure (tube side)"),
            Row("C3", field="Nozzle size (inlet)"), Row("C4", field="Nozzle size (outlet)")]  # fmt: skip
    assert g.g4_one_per_field(rows).status == PASS
    assert (
        g.field_words("Nozzle notes (M7)")
        == g.field_words("Nozzle notes")
        == {"nozzle", "notes"}
    )
    assert g.field_words("Material (Note 4)") == {"material"} and g.field_words(
        "Seal (6.8.1)"
    ) == {"seal"}
    shared = "Note M7: gaskets to suit flange rating"
    got = g.g4_one_per_field([_near("C1", "Nozzle notes", line=shared), _near("C17", "Nozzle notes (M7)", line=shared),
                              _near("C20", "Nozzle notes (M7) external loads", line="Note M9: external loads by others")])  # fmt: skip
    assert dict(got.failed) == {
        "C1": "near-same field as C17",
        "C17": "near-same field as C1",
    }
    assert got.status == FAIL and "C1/C20" in got.note and "C17/C20" in got.note


def test_g4_a_field_that_is_a_book_name_is_a_topic():
    rows = [
        Row("C23", field="API 9999"),
        Row("C49", field="API 9999 clause 5.7"),
        Row("C51", field="API 9999 clause 8.8"),
    ]
    assert g.g4_one_per_field(rows).status == PASS
    assert g.key_of(rows[1]) != g.key_of(rows[2]) and g.key_of(rows[1]).startswith(
        "topic|"
    )
    assert not g.is_book_name("Note 4") and g.is_book_name(
        "API 9999"
    )  # "note 4" is no book
    assert (
        g.g4_one_per_field(
            [
                Row("C1", field="API 9999 clause 5.7"),
                Row("C2", book="API 9999", clause="5.7"),
            ]
        ).status
        == FAIL
    )


def test_g4_keeps_truly_different_fields_with_a_shared_word_apart():
    rows = [Row("C1", field="Inlet size"), Row("C2", field="Outlet size"), Row("C3", field="Type"), Row("C4", field="Seal type"),
            Row("C5", field="Fluid"), Row("C6", field="Mole. wt. of relieved fluid")]  # fmt: skip
    assert g.g4_one_per_field(rows).status == PASS
    assert not g.near_same(
        g.field_words("Fluid"), g.field_words("Fluid phase")
    )  # one short word: not near-same


def test_g4_judges_near_same_in_pairs_never_chained():
    line = "Design / operating pressure 10 / 8 barg"
    rows = [_near("C1", "Design pressure", line=line), _near("C2", "Design/operating pressure", line=line),
            _near("C3", "Operating pressure", line="operating pressure 10 / 8 barg")]  # fmt: skip
    got = g.g4_one_per_field(rows)
    assert dict(got.failed) == {
        "C1": "near-same field as C2",
        "C2": "near-same field as C1",
        "C3": "near-same field as C2",
    }


def test_g4_passes_one_comment_per_field_and_per_topic():
    rows = [Row("C1", field="Set pressure"), Row("C2", field="Relieving temperature"),
            Row("C3", book="STD-A-100", clause="5.1"), Row("C4", book="STD-A-100", clause="5.2"), Row("C5"), Row("C6")]  # fmt: skip
    got = g.g4_one_per_field(rows)
    assert got.status == PASS and got.checked == 6


def test_g4_fails_two_comments_on_one_topic():
    got = g.g4_one_per_field(
        [
            Row("C1", book="STD-A-100", clause="5.1"),
            Row("C2", book="STD-A-100", clause="Clause 5.1"),
        ]
    )
    assert got.status == FAIL and len(got.failed) == 2


# ------------------------------------------------------------------------------------------------ G5


def _firm(rid, **over):
    base = {
        "rank": 3,
        "paper_value": "150 psig",
        "value_verified": True,
        "book": "STD-A-100",
        "clause": "4.2",
    }
    return Row(rid, **{**base, **over})


def test_g5_passes_a_firm_finding_with_its_value_and_clause_and_leaves_questions_alone():
    rows = [_firm("C1"), _firm("C2", rank=6), _firm("C3", rank=4, paper_value=None, book="", clause=""),
            _firm("C4", rank=8, paper_value=None)]  # fmt: skip
    got = g.g5_firm(rows)
    assert got.status == PASS and got.checked == 2


def test_g5_fails_a_firm_finding_without_a_paper_value_an_unverified_value_a_book_or_a_clause():
    rows = [_firm("C1", paper_value=None, value_verified=False), _firm("C2", rank=1, value_verified=False),
            _firm("C3", rank=2, clause=""), _firm("C4", rank=7, book="")]  # fmt: skip
    got = g.g5_firm(rows)
    assert got.status == FAIL and dict(got.failed) == {
        "C1": "no paper value", "C2": "paper value not verified on the page", "C3": "no clause", "C4": "no book",
    }  # fmt: skip


def test_g5_a_firm_absent_finding_needs_a_code_proof_or_its_value_inside_the_quote():
    label_only = _firm("C1", reason="absent", paper_value="Set pressure: By Contractor")
    proven = _firm(
        "C2",
        reason="absent",
        paper_value=None,
        value_verified=False,
        absence_proven=True,
    )
    value_in = _firm(
        "C3",
        reason="absent",
        paper_value="Set pressure 150 psig",
        paper_figure="150 psig",
    )
    value_out = _firm(
        "C4", reason="absent", paper_value="Set pressure", paper_figure="150 psig"
    )
    got = g.g5_firm([label_only, proven, value_in, value_out])
    assert dict(got.failed) == {
        "C1": "absent, not proven by code",
        "C4": "absent, not proven by code",
    }
    assert g.absence_proven(
        {"absence_check": {"proven": True}}
    ) and not g.absence_proven({"absence_check": {"proven": False}})


def test_g5_counts_an_absence_proven_by_code_as_the_value_but_still_wants_the_clause():
    rows = [_firm("C1", paper_value=None, value_verified=False, absence_proven=True),
            _firm("C2", paper_value=None, value_verified=False, absence_proven=True, clause="")]  # fmt: skip
    assert g.g5_firm(rows).failed == [("C2", "no clause")]


def test_g5_accepts_the_apps_two_reader_absence_proof(monkeypatch):
    from app import agent_review_two_reader

    monkeypatch.setattr(
        agent_review_two_reader,
        "absence_agrees",
        lambda line: line.get("item_id") == "S-1",
    )
    assert g.absence_proven({"item_id": "S-1"}) and not g.absence_proven(
        {"item_id": "S-2"}
    )
    line = {"item_id": "S-1", "reason_code": "absent", "verdict_class": "AI verdict, two readers agree", "word": "AI verdict: not stated",
            "standard": "STD-A-100", "clause": "4.2", "paper_quote": "Set pressure", "quotes_checked": {"paper": True}}  # fmt: skip
    row = g._line_row("R1", line)
    assert (
        row.absence_proven
        and g.g5_firm(
            [
                Row(
                    "R1",
                    rank=2,
                    reason="absent",
                    absence_proven=True,
                    book="STD-A-100",
                    clause="4.2",
                )
            ]
        ).status
        == PASS
    )
    assert not g._line_row("R2", {**line, "item_id": "S-2"}).absence_proven


# ------------------------------------------------------------------------------------------------ G6


def _sig(n, rank=3, clause="4.2", rule=None):
    return g.signature(
        Row(
            f"C{n}",
            field=f"Field {n}",
            rank=rank,
            clauses=(("STD-A-100", clause),),
            rules=(rule or f"S-{n}",),
        )
    )


def test_g6_measures_same_comments_of_the_larger_run_and_prints_the_union_for_information():
    a = [_sig(n) for n in range(20)]
    got = g.g6_replay(a, list(a))
    assert (
        got.status == PASS
        and "20 of 20 (larger run) comments the same (100.0%" in got.note
    )
    b = [
        *a[:18],
        _sig(98),
        _sig(99),
    ]  # 18 of 20 = 90%: passes (the union would say 18 of 22)
    got = g.g6_replay(a, b)
    assert (
        got.status == PASS
        and got.checked == 20
        and "18 of 20 (larger run)" in got.note
        and "union: 18 of 22" in got.note
    )
    got = g.g6_replay(a[:18], a)  # the larger run counts: 18 of 20
    assert got.status == PASS and "18 of 20 (larger run)" in got.note


def test_g6_fails_below_ninety_percent_a_changed_class_and_a_changed_clause():
    a = [_sig(n) for n in range(10)]
    b = [*a[:8], _sig(8, rank=4), _sig(9, clause="7.16")]  # 8 of 10
    got = g.g6_replay(a, b)
    assert (
        got.status == FAIL
        and "8 of 10 (larger run) comments the same (80.0%" in got.note
    )


def test_g6_never_takes_two_comments_from_different_rules_for_one():
    one = Row(
        "C1",
        field="Set pressure",
        rank=3,
        clauses=(("STD-A-100", "4.2"),),
        rules=("S-EQ-02",),
    )
    other = Row(
        "C2",
        field="Set pressure",
        rank=3,
        clauses=(("STD-A-100", "4.2"),),
        rules=("R-77",),
    )
    assert g.signature(one) != g.signature(other)
    got = g.g6_replay([g.signature(one)], [g.signature(other)])
    assert got.status == FAIL and "0 of 1" in got.note


def test_g6_is_not_run_without_a_second_run():
    assert g.g6_replay(None, None).status == NOT_RUN


def test_the_rule_key_of_a_point_is_the_same_in_two_runs():
    assert (
        g._rule_key("ai:run-1:S-EQ-02") == g._rule_key("ai:run-2:S-EQ-02") == "S-EQ-02"
    )
    assert g._rule_key("rc:abc") == "rc:abc"


# ------------------------------------------------------------------------------------------------ G7

LIBRARY = [
    {"id": "doc_std", "filename": "STD-A-100.pdf", "document_number": "STD-A-100"}
]


def test_g7_fails_a_guessed_rule_for_a_missing_book_and_rule_words_in_a_question():
    rows = [Row("E1", rank=3, names=("STD-Z-900",), clause="6.1", shows_rule_words=True),
            Row("E2", rank=4, names=("STD-Z-900",), shows_rule_words=True),
            Row("E3", rank=8, names=("STD-Z-900",))]  # fmt: skip
    got = g.g7_missing(rows, ["STD-Z-900"], LIBRARY, ["STD-Z-900"])
    assert got.status == FAIL and dict(got.failed) == {
        "E1": "verdict on a rule whose book is not held", "E2": "rule words shown for a book not held",
        "E3": "verdict on a rule whose book is not held",
    }  # fmt: skip


def test_g7_passes_the_missing_listing_a_bare_question_and_a_held_book():
    rows = [Row("E1", names=("STD-Z-900",), is_missing_listing=True), Row("E2", rank=4, names=("STD-Z-900",)),
            Row("E3", rank=3, names=("STD-A-100",), clause="4.1", shows_rule_words=True)]  # fmt: skip
    got = g.g7_missing(rows, ["STD-Z-900"], LIBRARY, ["STD-Y-1; STD-Z-900"])
    assert got.status == PASS


def test_g7_fails_a_missing_book_named_only_in_a_question_and_a_book_the_library_lacks():
    got = g.g7_missing(
        [Row("E1", rank=5, names=("STD-Y-800",), clause="2")],
        ["STD-Z-900"],
        LIBRARY,
        [],
    )
    assert got.status == FAIL and dict(got.failed) == {
        "E1": "verdict on a rule whose book is not held", "missing book 1": "not in the book-missing listing",
    }  # fmt: skip


def test_g7_listed_means_named_in_the_book_missing_listing_not_anywhere_in_the_file():
    assert g.g7_missing([], ["STD-Z-900"], LIBRARY, ["STD-Y-1"]).failed == [
        ("missing book 1", "not in the book-missing listing")
    ]
    from openpyxl import Workbook

    from app import crs_ai_words as words
    from app.crs_ai_workbook import OTHER_COLUMNS

    wb = Workbook()
    ws = wb.active
    ws.title = words.OTHER_SHEET
    ws.append(list(OTHER_COLUMNS))
    ws.append(
        [
            1,
            "paper.pdf",
            "p.1",
            "STD-Z-900 clause 2",
            words.KIND_NOT_APPLICABLE,
            "a question that names the book",
        ]
    )
    ws.append(
        [
            2,
            "paper.pdf",
            None,
            "STD-Y-1",
            words.KIND_NOT_HELD,
            "The rule book is not in the library.",
        ]
    )
    assert g._run_listing(wb) == ["STD-Y-1"]  # the question row is not a listing


# ------------------------------------------------------------------------------------------------ on a finished run, both files


def test_every_gate_runs_on_a_finished_run_reads_only_and_prints_no_paper_text(client):  # noqa: F811 - the fixture
    from app.db import connect
    from tests.test_agent_review_routes import finished_run

    run_id = finished_run(client)
    conn = connect()
    before = conn.total_changes
    for which in (g.FILE_PAGE, g.FILE_RUN):
        rep = g.check(run_id, which)
        assert [x["gate"] for x in rep["gates"]] == list(g.GATES)
        assert all(
            x["status"] in (PASS, FAIL, NOT_RUN, UNDECIDED) for x in rep["gates"]
        )
        assert rep["comment_rows"] >= 1
        text = "\n".join(g.lines_of(rep))
        assert text.startswith(f"run {run_id}") and "G7 " in text
    assert conn.total_changes == before  # the gates write nothing
    with pytest.raises(g.GateInputError):
        g.check("no-such-run")


def test_the_command_prints_every_gate_and_exits_by_its_rule(client, capsys):  # noqa: F811 - the fixture
    from app.config import settings
    from tests.test_agent_review_routes import finished_run

    run_id = finished_run(client)
    data_dir = settings.data_dir
    code = g.main([run_id, "--db", str(settings.db_path), "--file", "run"])
    settings.data_dir = data_dir
    out = capsys.readouterr().out
    assert code in (0, 1) and all(f"{x} " in out for x in g.GATES)
    assert (
        "G6 NOT RUN" in out and code == 1
    )  # no replay given: G6 is not run, so not every gate passes
    assert g.main(["no-such-run", "--db", str(settings.db_path), "--file", "run"]) == 2
