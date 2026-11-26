"""The same clause number in the OTHER held contract parts, for the citations builder A's lookup cannot settle (goal G6, lead-4 26 Nov
2026; queries/CFC fault 4). Each part numbers its own clauses, so these are marked as a different clause with the same number. Invented
contract text only."""

from __future__ import annotations

from app import db
from app import technical_query_every_part as EP
from tests.test_tq_g_feature_off import hold_contract, on, storage  # noqa: F401 - helpers, fixture

CLAUSE = "4.2.1 Invented Lining\nThe invented lining shall be two coats of invented resin.\nEach coat shall cure for one invented day.\n"
OTHER = "4.2.2 Invented Flushing\nThe invented line shall be flushed with invented water.\n"
CONTENTS = "Contents\n4.2.1 Invented Lining ........ 7\n4.2.2 Invented Flushing ........ 8\n"


def _hold(doc, text, page=2):
    hold_contract(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,0,1)", (doc, page, text, len(text))
        )


def _reranker(monkeypatch, score_of=None):
    monkeypatch.setattr(
        "app.reranker.rerank", lambda q, passages, batch=None: [] if score_of is None else [(i, score_of(t)) for i, t in passages]
    )


def test_a_part_has_the_clause_with_its_own_text_not_its_contents_line():
    got = EP.find_clause([(1, CONTENTS), (7, "Invented header\n" + CLAUSE + OTHER)], "4.2.1")
    assert got["page"] == 7 and got["heading"] == "4.2.1 Invented Lining"
    assert got["text"].startswith("4.2.1 Invented Lining\nThe invented lining") and "flushed" not in got["text"]
    assert got["shortened"] is False
    assert EP.find_clause([(1, CONTENTS)], "4.2.1") is None  # a contents line is not the clause
    assert EP.find_clause([(1, "4.2.1 Invented Lining\n")], "4.2.1") is None  # a heading alone is not the clause
    assert EP.find_clause([(7, CLAUSE)], "4.2") is None  # 4.2 is not 4.2.1


def test_a_long_clause_is_cut_at_a_line_and_the_cut_is_said():
    long = "9.3 Invented Payment\n" + "".join(f"Invented payment sentence number {n} of the clause.\n" for n in range(80))
    got = EP.find_clause([(3, long)], "9.3")
    assert got["shortened"] is True and len(got["text"]) <= EP.MAX_CLAUSE_CHARS
    assert long.startswith(got["text"])  # verbatim lines, never a word that is not on the page


def test_every_other_part_is_looked_in_and_each_find_is_marked_a_different_clause(monkeypatch):
    on(monkeypatch)
    _reranker(monkeypatch, lambda t: 1.5)
    for doc, text in (("con-a", CLAUSE), ("con-b", OTHER), ("con-c", "Invented preface\n" + CLAUSE), ("con-named", CLAUSE)):
        _hold(doc, text)
    hits, said = EP.every_part("4.2.1", ["con-a", "con-b", "con-c", "con-named"], "What lining?", exclude=frozenset({"con-named"}))
    assert [(h["document_id"], h["page_start"], h["locator"], h["same_number_other_part"]) for h in hits] == [
        ("con-a", 2, "4.2.1 Invented Lining", True),
        ("con-c", 2, "4.2.1 Invented Lining", True),
    ]
    assert all(h["rerank_score"] == 1.5 for h in hits)
    assert said == (
        "Clause 4.2.1: 2 of 3 other contract parts have a clause with the same number. Each part numbers its own clauses, so each is a "
        "different clause, shown for reference only."
    )


def test_a_number_in_many_parts_is_too_common_and_only_counted(monkeypatch):
    on(monkeypatch)
    _reranker(monkeypatch, lambda t: 5.0)
    docs = [f"con-{n}" for n in range(EP.OTHER_PARTS_LISTED + 1)]
    for doc in docs:
        _hold(doc, CLAUSE)
    hits, said = EP.every_part("4.2.1", docs, "q")
    assert hits == []
    assert said.startswith(f"Clause 4.2.1: {len(docs)} of {len(docs)} other contract parts have a clause with the same number.")
    assert said.endswith("So many parts use this number that none is listed.")
    hits, _ = EP.every_part("4.2.1", docs[: EP.OTHER_PARTS_LISTED], "q")
    assert len(hits) == EP.OTHER_PARTS_LISTED  # up to the limit, each is listed, marked


def test_nothing_found_none_held_and_no_reranker_are_said_plainly(monkeypatch):
    on(monkeypatch)
    _reranker(monkeypatch)
    _hold("con-a", OTHER)
    assert EP.every_part("4.2.1", ["con-a"], "q") == ([], "Clause 4.2.1: no other contract part (of 1 looked in) has a clause with this number.")
    assert EP.every_part("4.2.1", ["con-a"], "q", exclude=frozenset({"con-a"}))[1] == (
        "Clause 4.2.1: no other contract part that you may read is held, so no other part was looked in."
    )
    _hold("con-b", CLAUSE)
    hits, _ = EP.every_part("4.2.1", ["con-b"], "q")
    assert hits[0]["rerank_score"] is None  # unscored, never an invented score
