"""A held company book with a new numbering is "cited by the paper" when its RECORDED document number stands in the paper's text
(18 Nov 2026: the standard families alone never named it, so a newly uploaded book the paper cites was never used). Invented
numbers and words only; no paid call."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import book_names as BN
from app.aim_review import engine as E
from app.aim_review import library as L
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    _doc,
    open_aim_db,
)

NEW = "doc_aimbookZQ1"
NUMBER = "ZQ-TEST-STD-001"


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _cite(conn, words=f"The nameplate follows {NUMBER} in full."):
    with conn:
        conn.execute(
            "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = 1",
            ("\n" + words + "\n", PAPER),
        )


def _hold(conn, doc_id=NEW, role="COMPANY_STANDARD", number=NUMBER):
    with conn:
        _doc(
            conn,
            doc_id,
            f"{doc_id}.pdf",
            role,
            {
                1: "Section heading of an invented book\n4.1 The item shall carry a plate.\n"
            },
        )
        conn.execute(
            "UPDATE document_classification SET document_number = ? WHERE document_id = ?",
            (number, doc_id),
        )


@pytest.mark.parametrize(
    ("text", "found"),
    [
        (f"per {NUMBER}.", True),
        ("per zq test std 001", True),  # case and spacing
        ("per ZQTESTSTD001", True),
        ("per ZQ-TEST-STD-0012", False),  # another number: whole token only
        ("per XZQ-TEST-STD-001", False),
    ],
)
def test_a_recorded_number_is_found_as_a_whole_token(text, found):
    assert L._number_in(NUMBER, text) is found


def test_a_short_number_or_one_with_no_digit_is_never_matched_by_text():
    assert not L._number_in("AB-12", "per AB-12 in full")  # under 6 characters
    assert not L._number_in("ZQ-TEST-STD", "per ZQ-TEST-STD in full")  # no digit


def test_a_held_rule_book_whose_number_the_paper_carries_is_cited(aim_db):
    _hold(aim_db)
    _cite(aim_db)
    assert BN.paper_cited(aim_db, PAPER, frozenset({NEW, BOOK_A})) == {NEW}
    assert (
        BN.paper_cited(aim_db, PAPER, frozenset({BOOK_A})) == frozenset()
    )  # the caller may not read it: never named


def test_a_number_no_rule_book_carries_is_never_cited(aim_db):
    _cite(aim_db)
    assert NEW not in BN.paper_cited(
        aim_db, PAPER, frozenset({NEW, BOOK_A})
    )  # not held
    _hold(
        aim_db, doc_id="doc_sub_zq", role="CONTRACTOR_SUBMITTAL"
    )  # only a submittal carries that number
    _hold(aim_db, doc_id="doc_con_zq", role="CONTRACT_DOCUMENT")  # nor a contract
    assert (
        BN.paper_cited(aim_db, PAPER, frozenset({"doc_sub_zq", "doc_con_zq", BOOK_A}))
        == frozenset()
    )


def test_upload_then_the_plan_lists_it_cited_and_the_checklist_is_built_again_once(
    aim_db,
):
    """The whole path: the type's checklist is saved; a company book with a new numbering is uploaded and the paper carries its
    number; the plan lists it "cited by the paper"; the next review builds the checklist again WITH it; the next one reuses it."""
    allowed = frozenset({BOOK_A, BOOK_B, NEW})
    store = MemoryStore()

    def run(run_id):
        return aim_review.run(aim_db, run_id=run_id, paper_id=PAPER, allowed_books=allowed, store=store, max_usd=5.0,
                              model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip

    _cite(aim_db)
    first = run("run_zq1")
    assert run("run_zq2").checklist_reused  # not held yet: nothing changes
    _hold(aim_db)
    plan = L.candidates(aim_db, PAPER, allowed, store)
    assert {"id": NEW, "why": aim_review.WHY_CITED} in plan.books
    again = run("run_zq3")
    assert not again.checklist_reused and again.checklist_key == first.checklist_key
    assert NEW in {b["book"] for b in store.saved[again.checklist_key][-1][1]["books"]}
    assert run("run_zq4").checklist_reused


def test_a_book_with_no_recorded_number_is_found_by_the_identifier_its_file_name_records(
    aim_db,
):
    """No rule book of the library records a number (18 Nov count): an uploaded "ZQ-TEST-STD-001.pdf" is still found."""
    with aim_db:
        _doc(
            aim_db,
            NEW,
            f"{NUMBER}.pdf",
            "COMPANY_STANDARD",
            {1: "Section heading of an invented book\n4.1 A plate.\n"},
        )
    _cite(aim_db)
    assert BN.paper_cited(aim_db, PAPER, frozenset({NEW, BOOK_A})) == {NEW}


def test_a_held_contract_or_specification_sharing_the_name_is_never_the_cited_rule_book(
    aim_db,
):
    """Integrator's check of d03d62c9: a citation is resolved against the RULE BOOKS only, before the reader's narrowing. A held
    contract document named like the cited public standard is never "cited by the paper", even when the reader may read it."""
    public, contract = "doc_pub_9990", "doc_con_9990"
    with aim_db:
        _doc(
            aim_db,
            public,
            "API 9990.pdf",
            "",
            {1: "API 9990 invented public standard\n1.1 A rule.\n"},
        )
        _doc(
            aim_db,
            contract,
            "API 9990.pdf",
            "CONTRACT_DOCUMENT",
            {1: "Invented contract part\n"},
        )
    _cite(aim_db, "Design follows API 9990 throughout.")
    got = BN.paper_cited(aim_db, PAPER, frozenset({public, contract, BOOK_A}))
    assert contract not in got and got <= {public}
    names = [n for _e, n in L.cited_rule_books(aim_db, PAPER)]
    assert (
        all(
            e is None or L.is_rule_book(e)
            for e, _n in L.cited_rule_books(aim_db, PAPER)
        )
        and names
    )
