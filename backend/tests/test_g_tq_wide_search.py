"""The technical-query evidence search reaches wide into each contract: a wide candidate pool, a wide reranker shortlist, and the cut to a few
passages AFTER the reranker (measured 26 Nov 2026: right page found for 8 of 10 answered questions, against 7 of 10). Fake search; invented text."""

from __future__ import annotations

import inspect

from app import technical_query_contracts as TC
from tests.test_tq_g_feature_off import hold_contract, on, storage  # noqa: F401 - helpers, fixture

Q = "What coating thickness applies to carbon steel tanks?"


def hit(doc, page, score):
    return {"document_id": doc, "page_start": page, "page_end": page, "text": f"{doc} page {page}", "rerank_score": score, "score": score}


def test_each_contract_is_searched_with_a_wide_pool_and_the_cut_comes_after_the_reranker(monkeypatch):
    on(monkeypatch)
    for d in ("con-a", "con-b"):
        hold_contract(d)
    calls = []

    def fake(question, **kw):
        calls.append(kw)
        return {"hits": [hit(kw["document_id"], p, 0.9 - p / 100) for p in range(1, 12)]}

    monkeypatch.setattr("app.search.search", fake)
    got = TC.search_all(Q, frozenset({"con-a", "con-b"}))
    assert len(calls) == 2
    for kw in calls:
        assert kw["candidates"] == TC.WIDE_CANDIDATES and kw["rerank_candidates"] == TC.WIDE_SHORTLIST
        assert kw["limit"] == TC.PER_CONTRACT == 8 and kw["rerank"] is True and kw["dense"] is True
    assert len(got["hits"]) == 2 * TC.PER_PART_LISTED  # 8 searched per contract, a fair share of 3 per part listed
    assert "reach" not in got["coverage"]  # the three-ideas switch is gone


def test_a_hit_without_text_is_dropped_and_a_failed_contract_is_counted(monkeypatch):
    on(monkeypatch)
    for d in ("con-a", "con-b"):
        hold_contract(d)

    def fake(question, **kw):
        if kw["document_id"] == "con-b":
            raise RuntimeError("down")
        return {"hits": [hit("con-a", 1, 0.8), {**hit("con-a", 2, 0.7), "text": "  "}]}

    monkeypatch.setattr("app.search.search", fake)
    got = TC.search_all(Q, frozenset({"con-a", "con-b"}))
    assert [h["page_start"] for h in got["hits"]] == [1]
    assert got["coverage"]["searched"] == 1 and got["coverage"]["failed"] == 1


def test_the_search_accepts_a_wider_shortlist_and_defaults_to_the_setting():
    from app import search

    assert inspect.signature(search.search).parameters["rerank_candidates"].default is None
