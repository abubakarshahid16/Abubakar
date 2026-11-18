"""The three always-on items of every general review (G1 cited standards, G2 internal consistency, G3 required entries): method
items, the same on every paper, judged like any other item, never Met / Not met and never "compared by code". Invented papers;
no paid call, no socket."""

from __future__ import annotations

import pytest

from app import aim_review, aim_review_store
from app.aim_review import always as A
from app.aim_review import engine as E
from app.aim_review import steps as S
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _shown(d) -> str:
    line = E.to_line(1, d)
    return aim_review_store.shown_label(
        line["label"], line["code_compare_json"], line["deferred"]
    )


def _g(gid, checklist=None, conn=None, pages=None):
    got = A.items(
        conn,
        {"equipment_type": None},
        checklist or {"items": [], "books": []},
        frozenset(),
        pages or {},
    )
    return next(it for it in got if it["id"] == gid)


def test_every_review_judges_the_three_always_on_items_through_run(aim_db):
    r, model, store = _run(aim_db)
    ids = [ln["item_id"] for ln in r.lines]
    assert ids[-3:] == ["G1", "G2", "G3"] and all(
        ln["topic"] == "always checked" for ln in r.lines[-3:]
    )
    assert "G1" not in [
        it["id"] for it in store.get(r.checklist_key)["items"]
    ]  # never saved with the type's checklist
    prompts = [c["prompt"] for c in model.asked if c["step"] == "aim_judge"]
    assert any('"id": "G1"' in p and "THE LIBRARY FACTS" in p for p in prompts)


def _run(conn):
    model = E.FakeModel(kind="datasheet", subject_key="test_item")
    store = MemoryStore()
    r = aim_review.run(conn, run_id="run_aim_g", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                       max_usd=5.0, model=model)  # fmt: skip
    assert r.status == "done", r.stop_reason
    return r, model, store


# ---- G1 cited standards ---------------------------------------------------------------------------------------------------


def test_g1_an_obsolete_cited_standard_is_a_sent_ai_opinion_never_a_verdict():
    pages = {1: "Design to QX-STD-101 (2009) for the invented test item\n"}
    j = {"label": "Not met", "page": 1, "quote": "Design to QX-STD-101 (2009) for the invented test item",
         "comment": "the cited edition appears obsolete; please confirm the current edition"}  # fmt: skip
    for label in ("Not met", "Met"):
        d = S._decide(_g("G1"), dict(j, label=label), Paper("doc_g1", pages), {}, "")
        assert d["label"] in ("AI opinion", "Does not apply") and _shown(d) not in (
            aim_review_store.PASS_BY_CODE, aim_review_store.FAIL_BY_CODE)  # fmt: skip
    d = S._decide(_g("G1"), j, Paper("doc_g1", pages), {}, "")
    assert d["label"] == "AI opinion" and aim_review.sendable(E.to_line(1, d))


def test_g1_facts_name_the_cited_standards_and_only_books_on_the_list(aim_db):
    pages = {1: "The invented item is built to API 999 (2015) and to QX-NOT-HELD-7.\n"}
    facts = _g("G1", conn=aim_db, pages=pages)["context"]
    assert (
        facts.startswith("THE LIBRARY FACTS")
        and "cited: API 999 (2015); not among this review's books" in facts
    )
    # a held book that is not on this review's list is never named (the list here is empty)
    assert BOOK_A not in facts and BOOK_B not in facts


# ---- G2 internal consistency ----------------------------------------------------------------------------------------------

G2_PAGES = {
    1: "Normal flow of the invented item: 120 m3/h\n",
    2: "Rated flow of the invented item: 100 m3/h\n",
}


def _g2(label, op="<="):
    return {"label": label, "page": 1, "quote": "Normal flow of the invented item: 120 m3/h", "comment": "the AI's words",
            "numbers": {"paper_value": "120", "paper_unit": "m3/h", "operator": op, "rule_value": "100", "rule_unit": "m3/h",
                        "limit_quote": "Rated flow of the invented item: 100 m3/h", "limit_page": 2}}  # fmt: skip


def test_g2_two_paper_values_that_disagree_are_a_sent_ai_opinion_compared_as_paper_values():
    d = S._decide(_g("G2"), _g2("Not met"), Paper("doc_g2", G2_PAGES), {}, "")
    assert d["label"] == "AI opinion" and d["code_compare"]["result"] == "fail"
    assert d["code_compare"][
        "read_from"
    ] == "verified paper quotes" and aim_review.sendable(E.to_line(1, d))
    assert d["comment"].startswith(
        "The stated 120 m3/h is above the 100 m3/h stated on page 2;"
    )
    assert _shown(d) not in (
        aim_review_store.PASS_BY_CODE,
        aim_review_store.FAIL_BY_CODE,
    )


def test_g2_values_that_agree_are_held_back():
    d = S._decide(_g("G2"), _g2("Met", op=">="), Paper("doc_g2", G2_PAGES), {}, "")
    assert d["code_compare"]["result"] == "pass" and not aim_review.sendable(
        E.to_line(1, d)
    )


# ---- G3 required entries --------------------------------------------------------------------------------------------------


def test_g3_a_required_entry_left_blank_is_a_sent_question():
    pages = {
        1: "Seal flush plan of the invented item: ____\nCasing material: carbon steel\n"
    }
    j = {
        "label": "Not met",
        "page": 1,
        "quote": "Seal flush plan of the invented item: ____",
        "comment": "please state it",
    }
    d = S._decide(_g("G3"), j, Paper("doc_g3", pages), {}, "")
    assert (
        d["label"] == "Question"
        and d["deferred"] is True
        and aim_review.sendable(E.to_line(1, d))
    )


def test_g3_lists_and_declares_only_items_whose_book_is_on_the_list():
    checklist = {
        # public-family identifiers: G3's second lock lets a book in only when it is public or a company book the paper cites
        "books": [{"alias": "B01", "book": "doc_listed", "identifier": "ISO 99101"},
                  {"alias": "B02", "book": "doc_unlisted", "identifier": "ISO 99202"}],
        "items": [
            {"id": "C001", "book": "B01", "source": S.HELD, "topic": "seal flush", "what_to_check": "plan stated",
             "paper_fields": ["flush plan"]},
            {"id": "C002", "book": "B02", "source": S.HELD, "topic": "hidden topic", "what_to_check": "x", "paper_fields": []},
        ],
    }  # fmt: skip
    got = A.items(None, {}, checklist, frozenset({"doc_listed"}), {})
    g3 = next(it for it in got if it["id"] == "G3")
    assert (
        "seal flush: plan stated (fields: flush plan)" in g3["context"]
        and "hidden topic" not in g3["context"]
    )
    assert g3["carries"] == ["doc_listed"]
    assert [it["id"] for it in got] == ["G1", "G2", "G3"] and all(
        it["topic"] == "always checked" for it in got
    )


# ---- light check of f4b870ba: G1 declares the books it names; rule 5 covers G lines; count by id -------------------------------


def test_g1_declares_and_records_the_listed_books_its_facts_name(aim_db):
    from tests.test_aim_method_helpers import _doc

    with (
        aim_db
    ):  # two invented held books of a public family, one on this review's list, one not
        _doc(
            aim_db,
            "doc_api9990",
            "API 9990.pdf",
            "COMPANY_STANDARD",
            {1: "Section heading of the invented book\n"},
        )
        _doc(
            aim_db,
            "doc_api9991",
            "API 9991.pdf",
            "COMPANY_STANDARD",
            {1: "Section heading of the invented book\n"},
        )
    pages = {1: "The invented item is built to API 9990 (2009) and to API 9991.\n"}
    got = A.items(
        aim_db,
        {},
        {"items": [], "books": []},
        frozenset({"doc_api9990", BOOK_B}),
        pages,
    )
    g1 = next(it for it in got if it["id"] == "G1")
    assert g1["carries"] == ["doc_api9990"] and [
        b["id"] for b in g1["named_books"]
    ] == ["doc_api9990"]
    name = g1["named_books"][0]["name"]
    assert name and f"on this review's list as {name}" in g1["context"]
    # API 9991 is held but not on the list: never declared, never named beyond the paper's own words
    assert (
        "doc_api9991" not in g1["carries"]
        and "cited: API 9991; not among this review's books" in g1["context"]
    )
    d = S._decide(g1, {"label": "Not met", "page": 1, "quote": "built to API 9990 (2009) and to API 9991",
                       "comment": f"{name} is cited with an old edition"}, Paper("doc_x", pages), {}, "")  # fmt: skip
    assert (
        E.to_line(1, d)["named_books_json"]
        == f'[{{"id": "doc_api9990", "name": "{name}"}}]'
    )


class _Viewer:
    def __init__(self, readable):
        self.readable = set(readable)

    def may_read(self, doc_id):
        return doc_id in self.readable


def test_a_g_line_naming_a_book_the_viewer_may_not_read_is_hidden_with_the_fixed_words(
    aim_db,
):
    from app import aim_review_view as V

    row = {"item_id": "G1", "label": "AI opinion", "comment": "QX-STD-101 is cited without its edition", "standard": "",
           "book_document_id": None, "named_books": [{"id": BOOK_A, "name": "QX-STD-101"}], "topic": "always checked"}  # fmt: skip
    assert V.book_hidden(aim_db, row, _Viewer({BOOK_A})) is False
    assert V.book_hidden(aim_db, row, _Viewer({BOOK_B})) is True
    assert V.book_hidden(aim_db, row, None) is False  # the app's own counting
    shown = V.line_view(row, 1, True)
    assert (
        "QX-STD-101" not in shown["comment"] and V.HIDDEN_BOOK_WORDS in shown["comment"]
    )
    stored = {
        **row,
        "named_books": None,
        "named_books_json": '[{"id": "doc_gone", "name": "QX-STD-999"}]',
    }
    assert (
        V.book_hidden(aim_db, stored, _Viewer({"doc_gone"})) is True
    )  # a book no longer in the library


def test_always_items_are_counted_by_id_not_by_topic_words():
    from app import aim_review_view as V

    points = [
        {"item_id": "C001", "topic": "always checked"},
        {"item_id": "G1", "topic": "other words"},
        {"item_id": "G2", "topic": "always checked"},
        {"item_id": "G2", "topic": "always checked"},
    ]
    got = V._checklist(None, {"checklist_key": None}, points)
    assert got["always_items"] == 2 and got["items"] == 1
    assert A.is_always("G3") and not A.is_always("C003") and not A.is_always(None)


def test_the_store_keeps_named_books_and_adds_the_column_to_an_older_table(aim_db):
    from app import aim_review_store as store

    aim_db.execute(
        "CREATE TABLE aim_lines (run_id TEXT NOT NULL, line_no INTEGER NOT NULL, item_id TEXT, label TEXT NOT NULL,"
        " shown_label TEXT NOT NULL, field TEXT, page INTEGER, quote TEXT, quote_unverified TEXT, comment TEXT, standard TEXT,"
        " book_document_id TEXT, clause TEXT, source TEXT, topic TEXT, code_note TEXT, numbers_json TEXT,"
        " code_compare_json TEXT, PRIMARY KEY (run_id, line_no))"
    )  # the table as it was made before the column
    store.ensure_schema(aim_db)
    cols = {r[1] for r in aim_db.execute("PRAGMA table_info(aim_lines)")}
    assert "named_books_json" in cols
    store.start_run(aim_db, "run_named", PAPER, "2026-11-18T00:00:00Z")
    line = {
        "item_id": "G1",
        "label": "AI opinion",
        "comment": "c",
        "named_books": [{"id": BOOK_A, "name": "QX-STD-101"}],
    }
    store.finish_run(
        aim_db, "run_named", {"status": "done", "lines": [line]}, "2026-11-18T00:01:00Z"
    )
    assert store.lines(aim_db, "run_named")[0]["named_books"] == [
        {"id": BOOK_A, "name": "QX-STD-101"}
    ]


def test_g3_lists_only_usable_rule_books_items_and_a_citation_never_adds_one():
    """G3's second lock: on the shown list AND a usable rule book. With no database only an unroled public name is known; a
    cited id never makes a document a rule book (fix check 961f7126, N2)."""
    checklist = {
        "books": [{"alias": "B01", "book": "doc_public", "identifier": "ISO 99101"},
                  {"alias": "B02", "book": "doc_company", "identifier": "97-ZQ-707"}],
        "items": [
            {"id": "C001", "book": "B01", "source": S.HELD, "topic": "public topic", "what_to_check": "x", "paper_fields": []},
            {"id": "C002", "book": "B02", "source": S.HELD, "topic": "company topic", "what_to_check": "x", "paper_fields": []},
        ],
    }  # fmt: skip
    shown = frozenset({"doc_public", "doc_company"})
    g3 = next(it for it in A.items(None, {}, checklist, shown, {}) if it["id"] == "G3")
    assert "company topic" not in g3["context"] and g3["carries"] == ["doc_public"]
