"""Held books are never "not held", and the books that govern, belong to the kind's method or are cited lead and are never cut
(owner, 18 Nov 2026 after live). Invented library: ISO 99101 / 99202 / 99303 (BOOK_A, B on the list; C held, not on the list)."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import book_names as BN
from app.aim_review import checklist as CL
from app.aim_review import engine as E
from app.aim_review import library as L
from app.aim_review import scope_books as SB
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    BOOK_C,
    PAPER,
    MemoryStore,
    open_aim_db,
)

LISTED = frozenset({BOOK_A, BOOK_B})


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def test_a_name_with_extra_words_or_two_identifiers_finds_the_held_book(aim_db):
    lib = L.library(aim_db)
    assert BN.held_book(lib, "ISO 99101 Invented relief devices")["id"] == BOOK_A
    assert (
        BN.held_book(lib, "ISO 99999 / ISO 99202 invented vessels")["id"] == BOOK_B
    )  # the second identifier is held
    assert BN.held_book(lib, "ISO 99999 invented unheld") is None


def test_the_ais_needed_names_split_into_used_unlisted_and_not_held(aim_db):
    rows = [
        {"name": "ISO 99202 Invented title"},
        {"name": "ISO 99303"},
        {"name": "ISO 99999"},
    ]
    use, unlisted, not_held = BN.sort_needed(
        aim_db, PAPER, rows, LISTED, "datasheet", lambda _b: None
    )
    assert (
        use == [BOOK_B]
        and unlisted == [BOOK_C]
        and [r["name"] for r in not_held] == ["ISO 99999"]
    )
    use, unlisted, _nh = BN.sort_needed(
        aim_db, PAPER, rows[:1], LISTED, "datasheet", lambda _b: "refused"
    )
    assert use == [] and unlisted == [
        BOOK_B
    ]  # held but the gate refuses it: never "not held"


def test_a_held_book_the_ai_names_as_needed_is_used_and_never_listed_not_held(aim_db):
    def select(step, cached, prompt):
        return {"books": [], "not_held_needed": [{"name": "ISO 99202 Invented title", "why": "x"},
                                                 {"name": "ISO 99303", "why": "y"}, {"name": "ISO 99999", "why": "z"}]}  # fmt: skip

    model = E.FakeModel(
        kind="datasheet", subject_key="test_item", answers={"aim_select": select}
    )
    r = aim_review.run(aim_db, run_id="run_books_needed", paper_id=PAPER, allowed_books=LISTED, store=MemoryStore(),
                       max_usd=5.0, model=model)  # fmt: skip
    names = [n["name"] for n in r.not_held]
    assert r.status == "done" and BOOK_B in r.books and "ISO 99999" in names
    assert not any(
        "99202" in n or "99303" in n for n in names
    )  # held: never "not held"
    assert BOOK_C in r.unlisted_books  # held, not on the list: the next plan lists it


def test_required_books_come_first_and_are_never_cut_by_the_cap(monkeypatch):
    monkeypatch.setattr(CL, "SELECT_MAX_BOOKS", 2)
    cat = [
        {"book": f"b{i}", "alias": f"B{i:02d}", "subjects": [], "required": i >= 5}
        for i in range(1, 8)
    ]
    out = {
        "books": [{"alias": f"B{i:02d}"} for i in range(1, 5)]
    }  # the model chose four that are not required
    got = [
        c["book"]
        for c in CL._chosen(out, cat, {"b5": "governs", "b6": "method", "b7": "cited"})
    ]
    assert got[:3] == ["b5", "b6", "b7"] and got[3:] == ["b1", "b2"]


def test_a_procedures_method_books_stay_and_its_other_books_need_its_scope():
    cat = [{"book": "m", "identifier": "QX-M", "subjects": ["hazard study method"]},
           {"book": "t", "identifier": "QX-T", "subjects": ["coating thickness"]}]  # fmt: skip
    kept, req = SB.keep(
        cat,
        {"m": L.WHY_METHOD},
        "procedure",
        "the study of the invented unit",
        frozenset(),
    )
    assert [c["book"] for c in kept] == ["m"] and req == {"m": L.WHY_METHOD}
    kept, _ = SB.keep(
        cat,
        {"m": L.WHY_METHOD},
        "procedure",
        "coating thickness of the invented unit",
        frozenset(),
    )
    assert [c["book"] for c in kept] == ["m", "t"]


def test_with_no_stored_equipment_the_plan_takes_the_type_the_last_review_named(
    monkeypatch,
):
    from app import aim_review_store

    monkeypatch.setattr(
        aim_review_store,
        "latest_run",
        lambda conn, pid, ended=True: {
            "identity_json": '{"equipment_type": "relief_valve"}'
        },
    )
    monkeypatch.setattr(L, "type_ids", lambda: frozenset({"relief_valve"}))
    assert BN.last_run_type(None, PAPER) == "relief_valve"
    monkeypatch.setattr(
        aim_review_store,
        "latest_run",
        lambda conn, pid, ended=True: {
            "identity_json": '{"equipment_type": "no_such"}'
        },
    )
    assert BN.last_run_type(None, PAPER) is None  # only a known type
    monkeypatch.setattr(
        aim_review_store, "latest_run", lambda conn, pid, ended=True: None
    )
    assert BN.last_run_type(None, PAPER) is None


def test_the_plan_reading_falls_back_to_the_last_reviews_type(monkeypatch):
    from app import agent_review_kind

    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda conn, pid: {"known": True, "kind": "datasheet", "method": "m"},
    )
    monkeypatch.setattr(
        agent_review_kind, "read_equipment", lambda pid, allowed: (None, None)
    )
    monkeypatch.setattr(BN, "last_run_type", lambda conn, pid: "relief_valve")
    assert L.stored_reading(None, PAPER, frozenset())[:2] == (
        "datasheet",
        "relief_valve",
    )


# ---- a REUSED checklist (owner via the lead, 18 Nov 2026): its saved "not held" names are sorted again --------------------------

AI = "AI: needed, not in the catalog"


def test_a_saved_not_held_list_is_sorted_again(aim_db):
    saved = [{"name": "API 9990", "why": "governs; not held", "source": "governs"},
             {"name": "ISO 99202 Invented title", "source": AI}, {"name": "ISO 99303", "source": AI},
             {"name": "ISO 99999", "source": AI}]  # fmt: skip
    from app.aim_review import checklist as CL

    saved[0]["source"] = CL.WANTED_SOURCES[0]
    use, unlisted, rows = BN.resort_saved(
        aim_db, PAPER, saved, LISTED, "datasheet", lambda _b: None
    )
    assert use == [BOOK_B] and unlisted == [BOOK_C]
    assert [r["name"] for r in rows] == [
        "API 9990",
        "ISO 99999",
    ]  # the table's name as saved, and the unheld AI name


def _seed(aim_db, store, extra_not_held):
    first = aim_review.run(aim_db, run_id="run_seed_books", paper_id=PAPER, allowed_books=LISTED, store=store, max_usd=5.0,
                           model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    rows = next(iter(store.saved.values()))
    sha, body = rows[-1]
    rows.append(
        (
            sha + "x",
            {**body, "not_held": list(body.get("not_held") or []) + extra_not_held},
        )
    )
    return first


def test_a_saved_checklist_whose_needed_name_is_now_a_held_listed_book_is_built_again(
    aim_db,
):
    """HAND-REVERT PROOF (b): with `and not use` taken out of the engine's reuse condition, the saved checklist is reused and
    this test fails."""
    store = MemoryStore()
    _seed(
        aim_db, store, [{"name": "ISO 99202 Invented title", "why": "x", "source": AI}]
    )
    r = aim_review.run(aim_db, run_id="run_rebuild_books", paper_id=PAPER, allowed_books=LISTED, store=store, max_usd=5.0,
                       model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    assert r.status == "done" and r.checklist_reused is False


def test_a_reused_checklist_never_reports_a_held_book_not_held(aim_db):
    store = MemoryStore()
    _seed(
        aim_db,
        store,
        [
            {"name": "ISO 99303", "why": "y", "source": AI},
            {"name": "ISO 99999", "why": "z", "source": AI},
        ],
    )
    r = aim_review.run(aim_db, run_id="run_reuse_books", paper_id=PAPER, allowed_books=LISTED, store=store, max_usd=5.0,
                       model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    names = [n["name"] for n in r.not_held]
    assert (
        r.checklist_reused is True and "ISO 99303" not in names and "ISO 99999" in names
    )
    assert BOOK_C in r.unlisted_books
