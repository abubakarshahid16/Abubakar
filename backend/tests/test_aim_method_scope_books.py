"""A contract's technical rule books only when its own scope names their subject (owner, 18 Nov 2026 after live): by the paper's
recorded kind; a cited book always stays; a saved checklist with books the scope does not name is rebuilt. Invented values only."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import engine as E
from app.aim_review import library as L
from app.aim_review import scope_books as SB
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

LISTED = frozenset({BOOK_A, BOOK_B})
GENERIC = "perform the following work (herein referred to as the Work)"
NAMES_WELDING = "the Work: welding and inspection of the invented piping"


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def test_a_scope_names_a_subject_only_with_all_its_naming_words():
    assert SB.scope_names(
        NAMES_WELDING, ["welding procedure submission"]
    )  # "procedure", "submission" name nothing
    assert SB.scope_names(NAMES_WELDING, ["piping inspection"])
    assert not SB.scope_names(
        NAMES_WELDING, ["coating of piping"]
    )  # "coating" is not in the scope
    assert not SB.scope_names(
        GENERIC, ["weld map submission", "contractor approval"]
    )  # generic words name nothing
    assert not SB.scope_names("", ["welding"]) and not SB.scope_names(NAMES_WELDING, [])
    assert SB.scope_names(
        "the Work to QX-STD-707 and its annexes", [], "QX-STD-707"
    )  # the book itself named


def _cat(*books):
    return [{"book": b, "identifier": f"QX-{b}", "subjects": [s]} for b, s in books]


def test_only_a_contract_drops_the_books_its_scope_does_not_name_and_a_cited_book_stays():
    cat = _cat(
        ("b1", "welding inspection"),
        ("b2", "coating thickness"),
        ("b3", "cathodic protection"),
    )
    required = {"b2": "governs", "b1": "governs"}
    kept, req = SB.keep(cat, required, "contract", NAMES_WELDING, frozenset({"b3"}))
    assert [c["book"] for c in kept] == ["b1", "b3"] and req == {"b1": "governs"}
    kept, req = SB.keep(
        cat, required, "datasheet", "", frozenset()
    )  # any other kind: as given
    assert len(kept) == 3 and req == required


def test_a_saved_contract_checklist_is_reused_only_when_its_scope_names_every_book(
    monkeypatch,
):
    monkeypatch.setattr(L, "saved_books", lambda saved: ["b1", "b2"])
    monkeypatch.setattr(
        L, "library", lambda conn, within=None, **k: [{"id": b} for b in within or ()]
    )
    monkeypatch.setattr(L, "rule_pool", lambda conn, kind, etype, within=None, **k: [])
    monkeypatch.setattr(
        L,
        "catalog",
        lambda by_id, pool: _cat(
            ("b1", "welding inspection"), ("b2", "coating thickness")
        ),
    )
    monkeypatch.setattr(L, "identifier_of", lambda e: f"QX-{e['id']}")
    contract = {"kind": "contract", "scope_quote": NAMES_WELDING}
    assert not SB.saved_fits_scope(
        None, {}, contract
    )  # b2's subject is not named: rebuilt
    assert SB.saved_fits_scope(
        None, {}, contract, frozenset({"b2"})
    )  # b2 is cited by the paper
    assert SB.saved_fits_scope(
        None,
        {},
        {**contract, "scope_quote": NAMES_WELDING + "; coating thickness checks"},
    )
    assert SB.saved_fits_scope(
        None, {}, {"kind": "datasheet", "scope_quote": ""}
    )  # any other kind: reused as before


def _run(conn, kind):
    model = E.FakeModel(kind=kind, subject_key="test_item")
    r = aim_review.run(conn, run_id=f"run_scope_{kind}", paper_id=PAPER, allowed_books=LISTED, store=MemoryStore(),
                       max_usd=5.0, model=model)  # fmt: skip
    return r, [c["step"] for c in model.asked]


def test_a_contract_with_no_stated_scope_is_offered_no_technical_book_and_a_datasheet_still_is(
    aim_db,
):
    r, steps = _run(aim_db, "datasheet")
    assert r.status == "done" and "aim_select" in steps and r.books
    r, steps = _run(
        aim_db, "contract"
    )  # the fake paper states no scope: nothing names a book
    assert r.status == "done" and "aim_select" not in steps and r.books == []


def test_a_saved_contract_checklist_resting_on_books_the_scope_does_not_name_is_built_again(
    aim_db,
):
    """A checklist saved for the contract's type before this rule (it rests on technical books) is not reused for a contract whose
    scope names none of them: it is built again, with no such book."""
    store = MemoryStore()
    model = E.FakeModel(kind="datasheet", subject_key="test_item")
    first = aim_review.run(aim_db, run_id="run_scope_seed", paper_id=PAPER, allowed_books=LISTED, store=store, max_usd=5.0,
                           model=model)  # fmt: skip
    assert first.books and store.saved
    old = next(iter(store.saved.values()))[-1][1]
    store.saved["contract__test_item"] = [
        ("seeded", {**old, "key": "contract__test_item"})
    ]
    r = aim_review.run(aim_db, run_id="run_scope_reuse", paper_id=PAPER, allowed_books=LISTED, store=store, max_usd=5.0,
                       model=E.FakeModel(kind="contract", subject_key="test_item"))  # fmt: skip
    assert r.status == "done" and r.checklist_reused is False and r.books == []
