"""Update 13's method part (planner, 26 Nov 2026): the always-on items G2 (values that must agree) and G3 (required entries left blank)
read the app's OWN data, the consistency pairs and the type's mandatory entries, only with AIM_U13_ENABLED on. Off: exactly as before.
No paper words; invented types only where a real key is not needed."""

from __future__ import annotations

from app.aim_review import always
from app.config import settings


def test_off_the_always_on_items_read_nothing_new(monkeypatch):
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    assert always.form_context({"equipment_type": "centrifugal_pump"}) == ("", "")


def test_on_g2_gets_the_apps_consistency_pairs_and_g3_the_types_required_entries(
    monkeypatch,
):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    pairs, entries = always.form_context({"equipment_type": "pressure_vessel"})
    assert pairs.startswith("PAIRS THAT MUST AGREE") and pairs.count("\n- ") >= 3
    assert entries.startswith("THE FORM OF THIS KIND OF PAPER requires these entries: ")
    assert "test pressure" in entries and "corrosion allowance" in entries


def test_a_review_key_reaches_its_form_through_the_taxonomy_and_an_unknown_type_gets_no_entries(
    monkeypatch,
):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    assert (
        "rated flow" in always.form_context({"equipment_type": "centrifugal_pump"})[1]
    )
    assert always.form_context({"equipment_type": "invented_thing"})[1] == ""
    assert always.form_context({})[1] == ""


def test_on_a_required_entries_question_the_paper_fills_is_not_sent_and_off_nothing_changes(
    monkeypatch,
):
    """Lead-4's WRONG guard: an always-on item never becomes a comment when the field IS filled; only a real gap is sent."""
    from app.aim_review import asks

    filled = {"item_id": "G3", "label": "Question", "field": "Corrosion allowance", "quote": "Corrosion allowance: 3 mm", "page": 2,
              "comment": "Please state the corrosion allowance.", "ask": "concern"}  # fmt: skip
    blank = dict(filled, quote="Corrosion allowance")
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    assert asks.entry_filled(filled) and not asks.entry_filled(blank)
    assert not asks.entry_filled(dict(filled, item_id="G2")) and not asks.entry_filled(
        dict(filled, page=None)
    )
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    assert not asks.entry_filled(filled)


# ---- (a) the paper's SERVICE as a key for book choice (lead-4, 26 Nov 2026: a pump in sour service missed its service books)


def test_a_service_is_declared_by_the_papers_own_words_never_by_a_bare_chemical_name():
    from app.aim_review import service_books as SVC

    assert SVC.declared("Service: sour service (wet H2S)") == ["sour"]
    assert SVC.declared("H2S content: 0 ppm") == [] and SVC.declared("") == []


def test_on_a_declared_service_brings_its_held_book_in_as_a_required_book_and_off_nothing(
    tmp_path, monkeypatch
):
    from app.aim_review import checklist as CL
    from app.aim_review import library as L
    from app.aim_review import service_books as SVC
    from tests.test_aim_method_helpers import BOOK_A, BOOK_B, PAPER, open_aim_db

    gen = open_aim_db(tmp_path, monkeypatch)
    conn = next(gen)
    try:
        monkeypatch.setattr(
            SVC,
            "_table",
            lambda: {
                "test": {"markers": ["invented\\s+service"], "standards": ["ISO 99202"]}
            },
        )
        with conn:
            conn.execute(
                "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = 1",
                ("\nService: invented service\n", PAPER),
            )
        monkeypatch.setattr(settings, "aim_u13_enabled", False)
        lib = L.library(conn, exclude=frozenset({PAPER}))
        assert SVC.service_books(conn, PAPER, lib) == []
        monkeypatch.setattr(settings, "aim_u13_enabled", True)
        got = SVC.service_books(conn, PAPER, lib)
        assert [(e and e["id"], name) for e, name in got] == [(BOOK_B, "ISO 99202")]
        ident = {"kind": "datasheet", "equipment_type": None}
        req = CL.wanted(
            conn, PAPER, ident, frozenset({BOOK_A, BOOK_B}), cited=frozenset()
        )
        assert req["listed"].get(BOOK_B) == SVC.WHY_SERVICE
    finally:
        next(gen, None)


# ---- (b) the applicable-standards list through G1, and every entry of a kind through G3 (item 5)


def test_on_g1_asks_for_the_standards_list_and_g3_for_each_entry_of_a_kind_and_off_neither(
    monkeypatch,
):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    assert (
        always.EACH_ENTRY
        in always.form_context({"equipment_type": "pressure_vessel"})[1]
    )
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    assert always.form_context({"equipment_type": "pressure_vessel"}) == ("", "")


# ---- items 7 and 8 (a procedure): its cited books reach the checklist; G2 asks for each definition and each interval


def test_on_a_book_the_paper_cites_stays_in_the_catalog_when_its_committee_role_does_not_fit_the_kind_and_off_it_is_dropped(
    tmp_path, monkeypatch
):
    """The stored procedure runs: both cited held books were dropped by the committee-role filter, before the scope filter that
    keeps cited books, so the checklist had no held rule at all. A cited book is on the shown list (rule 1: `within`)."""
    from app.aim_review import checklist as CL
    from app.aim_review import library as L
    from tests.test_aim_method_helpers import BOOK_A, BOOK_B, PAPER, open_aim_db

    gen = open_aim_db(tmp_path, monkeypatch)
    conn = next(gen)
    try:
        monkeypatch.setattr(L, "role_applies", lambda e, k: e["id"] != BOOK_A)
        ident, listed = (
            {"kind": "procedure", "equipment_type": None},
            frozenset({BOOK_A, BOOK_B}),
        )

        def books(cited):
            cat, *_ = CL._catalog(
                conn, PAPER, ident, listed, {"listed": {}}, lambda b: None, cited
            )
            return {c["book"] for c in cat}

        monkeypatch.setattr(settings, "aim_u13_enabled", False)
        assert BOOK_A not in books(frozenset({BOOK_A}))  # main: dropped
        monkeypatch.setattr(settings, "aim_u13_enabled", True)
        assert BOOK_A in books(frozenset({BOOK_A}))
        assert BOOK_A not in books(
            frozenset()
        )  # not cited: the role filter still holds
        cat, *_ = CL._catalog(
            conn,
            PAPER,
            ident,
            frozenset({BOOK_B}),
            {"listed": {}},
            lambda b: None,
            frozenset({BOOK_A}),
        )
        assert BOOK_A not in {
            c["book"] for c in cat
        }  # cited but not on the shown list: never in (rule 1)
    finally:
        next(gen, None)


def test_on_g2_asks_for_each_definition_and_each_interval_on_any_kind_and_off_not(
    monkeypatch,
):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    for etype in ("pressure_vessel", None):
        assert always.G2_MORE in always.form_context({"equipment_type": etype})[0]
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    assert always.form_context({"equipment_type": None}) == ("", "")
