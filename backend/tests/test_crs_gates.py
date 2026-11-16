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


# ------------------------------------------------------------------------------------------------ G3


@pytest.mark.parametrize("words", [
    "Searched pages 1 to 4: found none.", "None found on the sheet.", "One reader's view: No correction needed.",
    "no corrections required", "Page 3 could not be read.", "the table cannot be read",
])  # fmt: skip
def test_g3_fails_each_noise_phrase(words):
    got = g.g3_noise([Row("C1", cells=("Set pressure", words))])
    assert got.status == FAIL and got.failed[0][0] == "C1"


def test_g3_passes_a_real_comment_and_close_but_honest_words():
    rows = [Row("C1", cells=("Set pressure", "Contractor to state the set pressure against STD-A-100 clause 4.2.")),
            Row("C2", cells=("Body", "The value could not be confirmed against the rule; the engineer decides."))]  # fmt: skip
    assert g.g3_noise(rows).status == PASS


# ------------------------------------------------------------------------------------------------ G4


def test_g4_fails_two_comments_on_one_field_written_two_ways():
    rows = [Row("C1", field="Set pressure"), Row("C2", field="SET PRESSURE (barg):"), Row("C3", field="Overpressure"),
            Row("C4", field="Over pressure %")]  # fmt: skip
    got = g.g4_one_per_field(rows)
    assert got.status == FAIL and sorted(i for i, _w in got.failed) == [
        "C1",
        "C2",
        "C3",
        "C4",
    ]


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


def test_g5_fails_a_firm_finding_without_a_paper_value_an_unverified_value_or_a_clause():
    rows = [_firm("C1", paper_value=None, value_verified=False), _firm("C2", rank=1, value_verified=False),
            _firm("C3", rank=2, clause=""), _firm("C4", rank=7, book="")]  # fmt: skip
    got = g.g5_firm(rows)
    assert got.status == FAIL and dict(got.failed) == {
        "C1": "no paper value", "C2": "paper value not verified on the page", "C3": "no book and clause", "C4": "no book and clause",
    }  # fmt: skip


def test_g5_counts_an_absence_proven_by_code_as_the_value_but_still_wants_the_clause():
    rows = [_firm("C1", paper_value=None, value_verified=False, absence_proven=True),
            _firm("C2", paper_value=None, value_verified=False, absence_proven=True, clause="")]  # fmt: skip
    got = g.g5_firm(rows)
    assert got.failed == [("C2", "no book and clause")]
    assert g.absence_proven(
        {"absence_check": {"proven": True}}
    ) and not g.absence_proven({"absence_check": {"proven": False}})


# ------------------------------------------------------------------------------------------------ G6


def _sig(n, rank=3, clause="4.2"):
    return g.signature(
        Row(f"C{n}", field=f"Field {n}", rank=rank, clauses=(("STD-A-100", clause),))
    )


def test_g6_passes_the_same_comments_twice_and_says_the_denominator():
    a = [_sig(n) for n in range(20)]
    got = g.g6_replay(a, list(a))
    assert got.status == PASS and "20 of 20 comments the same (100.0%" in got.note
    b = [*a[:19], _sig(99)]  # 19 the same of 21 counted once: 90.5%
    got = g.g6_replay(a, b)
    assert got.status == PASS and got.checked == 21 and "19 of 21" in got.note


def test_g6_fails_below_ninety_percent_a_changed_class_and_a_changed_clause():
    a = [_sig(n) for n in range(10)]
    b = [*a[:8], _sig(8, rank=4), _sig(9, clause="7.16")]  # 8 of 12 the same
    got = g.g6_replay(a, b)
    assert got.status == FAIL and "8 of 12 comments the same (66.7%" in got.note


def test_g6_is_not_run_without_a_second_run():
    assert g.g6_replay(None, None).status == NOT_RUN


# ------------------------------------------------------------------------------------------------ G7

LIBRARY = [
    {"id": "doc_std", "filename": "STD-A-100.pdf", "document_number": "STD-A-100"}
]


def test_g7_fails_a_guessed_rule_for_a_missing_book_and_rule_words_in_a_question():
    rows = [Row("E1", rank=3, names=("STD-Z-900",), clause="6.1", shows_rule_words=True),
            Row("E2", rank=4, names=("STD-Z-900",), shows_rule_words=True),
            Row("E3", rank=8, names=("STD-Z-900",))]  # fmt: skip
    got = g.g7_missing(rows, ["STD-Z-900"], LIBRARY, "rule books not held std-z-900")
    assert got.status == FAIL and dict(got.failed) == {
        "E1": "verdict on a rule whose book is not held", "E2": "rule words shown for a book not held",
        "E3": "verdict on a rule whose book is not held",
    }  # fmt: skip


def test_g7_passes_the_missing_listing_a_bare_question_and_a_held_book():
    rows = [Row("E1", names=("STD-Z-900",), is_missing_listing=True), Row("E2", rank=4, names=("STD-Z-900",)),
            Row("E3", rank=3, names=("STD-A-100",), clause="4.1", shows_rule_words=True)]  # fmt: skip
    got = g.g7_missing(rows, ["STD-Z-900"], LIBRARY, "rule books not held: std-z-900")
    assert got.status == PASS


def test_g7_fails_a_missing_book_the_file_does_not_name_and_a_book_the_library_lacks():
    got = g.g7_missing(
        [Row("E1", rank=5, names=("STD-Y-800",), clause="2")],
        ["STD-Z-900"],
        LIBRARY,
        "nothing listed",
    )
    assert got.status == FAIL and dict(got.failed) == {
        "E1": "verdict on a rule whose book is not held", "missing book 1": "not listed as book missing",
    }  # fmt: skip


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
