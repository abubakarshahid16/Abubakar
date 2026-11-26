"""A clause a technical query cites is read in EVERY held contract part, with its clause and page (goal G6, lead-4 26 Nov 2026; queries/CFC
fault 4). Invented contract text only."""

from __future__ import annotations

from app import db
from app import technical_query_cited as CI
from app import technical_query_contracts as C
from tests.test_tq_g_feature_off import hold_contract, on, storage  # noqa: F401 - helpers, fixture

CLAUSE = "4.2.1 Invented Lining\nThe invented lining shall be two coats of invented resin.\nEach coat shall cure for one invented day.\n"
OTHER = "4.2.2 Invented Flushing\nThe invented line shall be flushed with invented water.\n"
CONTENTS = "Contents\n4.2.1 Invented Lining ........ 7\n4.2.2 Invented Flushing ........ 8\n"


def _page(doc, page_no, text):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,0,1)",
            (doc, page_no, text, len(text)),
        )


def _no_reranker(monkeypatch, score=None):
    monkeypatch.setattr("app.reranker.rerank", lambda q, passages, batch=None: [] if score is None else [(i, score) for i, _ in passages])


def test_the_numbers_a_query_cites():
    assert CI.cited_numbers("Please confirm clause 4.2 and Article 9 for the 1.5 bar line; see also 7.1.15 and § 3.4.") == [
        "4.2",
        "9",
        "7.1.15",
        "3.4",
    ]
    assert CI.cited_numbers("The test pressure is 1.5 bar for 2.5 hours.") == []  # a bare value is never a citation
    assert CI.cited_numbers("clause 4.2.1, clause 4.2.1 again") == ["4.2.1"]
    assert len(CI.cited_numbers(" ".join(f"clause {n}.1" for n in range(1, 12)))) == CI.MAX_CITED


def test_a_part_holds_the_clause_with_its_own_text_not_its_contents_line():
    got = CI.find_clause([(1, CONTENTS), (7, "Invented header\n" + CLAUSE + OTHER)], "4.2.1")
    assert got["page"] == 7 and got["heading"] == "4.2.1 Invented Lining"
    assert got["text"].startswith("4.2.1 Invented Lining\nThe invented lining") and "flushed" not in got["text"]
    assert got["shortened"] is False
    assert CI.find_clause([(1, CONTENTS)], "4.2.1") is None  # a contents line is not the clause
    assert CI.find_clause([(1, "4.2.1 Invented Lining\n")], "4.2.1") is None  # a heading alone is not the clause
    assert CI.find_clause([(7, CLAUSE)], "4.2") is None  # 4.2 is not 4.2.1


def test_a_long_clause_is_cut_at_a_line_and_the_cut_is_said():
    long = "9.3 Invented Payment\n" + "".join(f"Invented payment sentence number {n} of the clause.\n" for n in range(80))
    got = CI.find_clause([(3, long)], "9.3")
    assert got["shortened"] is True and len(got["text"]) <= CI.MAX_CLAUSE_CHARS
    assert long.startswith(got["text"])  # verbatim lines, never a word that is not on the page


def test_every_part_is_looked_up_and_the_parts_without_it_are_counted(monkeypatch):
    on(monkeypatch)
    _no_reranker(monkeypatch, 1.5)
    for doc, text in (("con-a", CLAUSE), ("con-b", OTHER), ("con-c", "Invented preface\n" + CLAUSE)):
        hold_contract(doc)
        _page(doc, 2, text)
    got = CI.in_every_part(["4.2.1"], ["con-a", "con-b", "con-c"], "What lining applies?")
    assert [(h["document_id"], h["page_start"], h["locator"], h["cited"]) for h in got["hits"]] == [
        ("con-a", 2, "4.2.1 Invented Lining", "4.2.1"),
        ("con-c", 2, "4.2.1 Invented Lining", "4.2.1"),
    ]
    assert all(h["rerank_score"] == 1.5 for h in got["hits"])  # the reranker's own score of each passage
    assert got["cited"] == [{"clause": "4.2.1", "found_in": 2, "of": 3, "failed": 0, "shortened": 0}]
    assert CI.coverage_line(got["cited"]) == "Clause 4.2.1 (cited): found in 2 of 3 contract parts."


def test_without_a_reranker_the_passages_stay_unscored_never_invented(monkeypatch):
    on(monkeypatch)
    _no_reranker(monkeypatch)
    hold_contract("con-a")
    _page("con-a", 1, CLAUSE)
    got = CI.in_every_part(["4.2.1"], ["con-a"], "What lining applies?")
    assert got["hits"][0]["rerank_score"] is None


def test_the_search_lists_the_cited_clause_first_from_every_part_and_once(monkeypatch):
    on(monkeypatch)
    _no_reranker(monkeypatch, 0.5)
    for doc in ("con-a", "con-b"):
        hold_contract(doc)
        _page(doc, 2, CLAUSE)

    def fake(question, **kw):  # the meaning search found the same page of con-a, and another page
        return {"hits": [{"document_id": kw["document_id"], "page_start": p, "page_end": p, "text": f"invented {p}", "rerank_score": 3.0 - p} for p in (2, 5)]}

    monkeypatch.setattr("app.search.search", fake)
    got = C.search_all("Please confirm clause 4.2.1 for the invented lining.", frozenset({"con-a", "con-b"}))
    assert [(h["document_id"], h["page_start"], bool(h.get("cited"))) for h in got["hits"][:2]] == [("con-a", 2, True), ("con-b", 2, True)]
    assert not [h for h in got["hits"][2:] if h["page_start"] == 2]  # the same page is not listed twice
    assert got["coverage"]["line"].endswith("Clause 4.2.1 (cited): found in 2 of 2 contract parts.")
    # no citation: nothing is looked up and the line is as before
    plain = C.search_all("What lining applies?", frozenset({"con-a", "con-b"}))
    assert not [h for h in plain["hits"] if h.get("cited")] and plain["coverage"]["cited"] == []
    assert plain["coverage"]["line"] == C.coverage_line(2, 2, 2)


def test_a_cited_passage_is_never_held_back_and_the_cut_counts_searched_passages_only():
    cited = [{"document_id": f"c{n}", "cited": "4.2.1", "rerank_score": -9.0} for n in range(3)]
    searched = [{"document_id": f"s{n}", "rerank_score": 5.0 - n * 0.1} for n in range(20)]
    hits = cited + searched
    assert not any(C.held_back(hits, n, h) for n, h in enumerate(cited))
    kept = [h for n, h in enumerate(hits) if not C.held_back(hits, n, h)]
    assert len(kept) == len(cited) + C.LISTED
    assert C.floor_note(hits, len(kept)) == C.floor_note(searched, C.LISTED)


def test_the_evidence_row_is_located_at_the_cited_clause(monkeypatch):
    from app.technical_queries import import_message, prepare_evidence

    from .test_technical_queries import envelope

    on(monkeypatch)
    _no_reranker(monkeypatch, 2.0)
    for doc in ("k1", "k2"):
        hold_contract(doc)
        _page(doc, 4, "Invented preface line.\n" + CLAUSE + OTHER)
    monkeypatch.setattr("app.search.search", lambda q, **k: {"hits": []})
    mail = envelope("cited-1")
    mail["question"] = mail["body"] = "Please confirm clause 4.2.1 for the invented lining."
    item, _ = import_message(mail, "u1", False, False)
    got = prepare_evidence(item["id"], frozenset({"k1", "k2"}), "u1", True, False, "u1")
    rows = [(e["document_id"], e["page_start"], e["locator"]) for e in got["evidence"]]
    assert sorted(rows) == [("k1", 4, "4.2.1 Invented Lining"), ("k2", 4, "4.2.1 Invented Lining")]
    assert all(e["exact_quote"].startswith("4.2.1 Invented Lining") for e in got["evidence"])
