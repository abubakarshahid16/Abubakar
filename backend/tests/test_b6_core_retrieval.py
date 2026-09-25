"""Master order B6 - core retrieval, proven end to end on the real pipeline.

Each part of the search is checked on the corpus in `fixtures/retrieval_bench`
after a REAL ingestion - extraction, chunking, embedding with the staged e5
model, FTS5 indexing - so nothing below is a stub:

  1. FTS5 keyword search finds exact identifiers and numbers.
  2. Dense (semantic) search finds paraphrases the keyword side cannot.
  3. RRF fusion keeps both sides and ranks agreement first.
  4. Reranking runs with the real cross-encoder, and degrades to RRF order -
     not to nothing - when the model is unavailable.
  5. Every hit cites a document, a page, the clause it sits under, and a quote
     that is verbatim on that page.
  6. Permission filtering: a document outside the caller's grants is absent
     from every stage, and does not shrink what the caller may see.
  7. Recall@1/@5, MRR, precision@5, negative-query behaviour and latency are
     MEASURED on this synthetic set and reported in the test log.

SYNTHETIC. These numbers say whether the pipeline works, not how well it does
on the client corpus - that is `scripts/eval_retrieval.py` on the owner's
machine. Needs the staged models (CI stages them; the conftest guard refuses a
run without them).
"""
from __future__ import annotations

import re
import statistics
import time
import warnings
from textwrap import wrap

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, reranker, search
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app
from tests.fixtures.retrieval_bench import CORPUS, NEGATIVES, POSITIVES

TOP_K = 5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    """The corpus, uploaded and ingested once for the whole module."""
    root = tmp_path_factory.mktemp("b6")
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "data_dir", root)
    mp.setattr(settings, "upload_dir", root / "uploads")
    mp.setattr(settings, "db_path", root / "b6.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    ids: dict[str, str] = {}
    for key, clauses in CORPUS.items():
        path = root / f"{key}.pdf"
        pdf = pymupdf.open()
        for heading, body in clauses:
            page = pdf.new_page()
            page.insert_text((72, 90), heading, fontsize=12)
            for i, line in enumerate(wrap(body, 80)):
                page.insert_text((72, 120 + i * 16), line, fontsize=11)
        pdf.save(str(path))
        pdf.close()
        with open(path, "rb") as fh:
            response = client.post("/api/documents",
                                   files={"file": (f"{key}.pdf", fh, "application/pdf")})
        assert response.status_code in (200, 201), response.text
        ids[key] = response.json()["document"]["id"]
        IngestionWorker().process(ids[key])
    # NO TEST MAY PASS ON AN EMPTY INDEX. Without the staged models chunking
    # fails and every search returns nothing - which several assertions below
    # (absence of a hidden document, "no hits" for a negative query) would
    # read as success. Every document must have reached READY first.
    statuses = {key: db.connect().execute(
        "SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0]
        for key, doc in ids.items()}
    if any(status != "ready" for status in statuses.values()):
        mp.undo()
        pytest.fail(f"B6 corpus did not ingest (models staged?): {statuses}")
    everything = frozenset(ids.values())
    yield {"ids": ids, "by_id": {v: k for k, v in ids.items()}, "all": everything}
    db.reset_connection()
    mp.undo()


def _where(bench, hit) -> tuple[str, int]:
    return bench["by_id"].get(hit["document_id"]), hit["page_start"]


def _rank(bench, hits, expected) -> int | None:
    """1-based rank of the first hit on the expected (document, page)."""
    for i, hit in enumerate(hits, start=1):
        if _where(bench, hit) == expected:
            return i
    return None


def test_the_corpus_was_really_ingested_and_embedded(bench):
    """The precondition for everything below: every page is a retrievable
    chunk with a vector. A pipeline that silently skipped embedding would make
    every dense test pass vacuously on keyword results."""
    conn = db.connect()
    chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE retrievable = 1").fetchone()[0]
    vectors = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    pages = sum(len(c) for c in CORPUS.values())
    assert chunks >= pages
    assert vectors == chunks, f"{vectors} vectors for {chunks} retrievable chunks"


# ================================================================ 1. FTS5

def test_keyword_search_finds_every_exact_query_first(bench):
    exact = [(q, e) for q, kind, e in POSITIVES if kind == "exact"]
    missed = [q for q, e in exact
              if _rank(bench, keyword.search(q, limit=TOP_K,
                                             allowed_document_ids=bench["all"]), e) != 1]
    assert missed == [], f"FTS5 did not rank the answering clause first for: {missed}"


def test_keyword_search_returns_nothing_for_words_no_clause_contains(bench):
    assert keyword.search("helicopter deck lighting", limit=TOP_K,
                          allowed_document_ids=bench["all"]) == []


# ================================================================ 2. dense

def test_dense_search_finds_paraphrases_the_keyword_side_misses(bench):
    """The reason the dense side exists: a question in other words."""
    paraphrases = [(q, e) for q, kind, e in POSITIVES if kind == "paraphrase"]
    dense_found = keyword_missed_but_dense_found = 0
    for query, expected in paraphrases:
        dense_rank = _rank(bench, search.dense_search(
            query, limit=TOP_K, allowed_document_ids=bench["all"]), expected)
        kw_rank = _rank(bench, keyword.search(
            query, limit=TOP_K, allowed_document_ids=bench["all"]), expected)
        dense_found += dense_rank is not None
        keyword_missed_but_dense_found += dense_rank is not None and kw_rank is None
    assert dense_found >= 6, f"dense found {dense_found} of {len(paraphrases)} paraphrases in top {TOP_K}"
    assert keyword_missed_but_dense_found >= 4, (
        f"only {keyword_missed_but_dense_found} paraphrases were found by dense alone")


# ================================================================ 3. RRF

def test_fusion_keeps_both_sides_and_ranks_agreement_first(bench):
    """Hybrid mode, both ranks carried, and an exact query's answer - found by
    BOTH sides - is first after fusion (no rerank, so this is RRF's order)."""
    for query, kind, expected in POSITIVES:
        if kind != "exact":
            continue
        result = search.search(query, limit=TOP_K, rerank=False,
                               allowed_document_ids=bench["all"])
        assert result["mode"] == "hybrid" and result["dense_candidates"] > 0
        top = result["hits"][0]
        assert _where(bench, top) == expected, query
        assert top["keyword_rank"] is not None and top["dense_rank"] is not None, query


def test_fusion_brings_a_dense_only_answer_into_the_hybrid_results(bench):
    found = 0
    for query, kind, expected in POSITIVES:
        if kind != "paraphrase":
            continue
        hits = search.search(query, limit=TOP_K, rerank=False,
                             allowed_document_ids=bench["all"])["hits"]
        rank = _rank(bench, hits, expected)
        if rank is not None and hits[rank - 1]["keyword_rank"] is None:
            found += 1
    assert found >= 4, f"fusion surfaced {found} dense-only answers"


# ================================================================ 4. rerank

def test_the_real_cross_encoder_scores_every_hit(bench):
    result = search.search("how loud is it allowed to be", limit=TOP_K, rerank=True,
                           allowed_document_ids=bench["all"])
    assert result["reranked"] is True
    assert all(h["rerank_score"] is not None for h in result["hits"])
    scores = [h["rerank_score"] for h in result["hits"]]
    assert scores == sorted(scores, reverse=True)


def test_without_the_reranker_the_fused_order_is_kept_not_lost(bench, monkeypatch):
    monkeypatch.setattr(reranker, "rerank", lambda question, pairs, batch=None: [])
    result = search.search("API 682 category 2 seal flush plan", limit=TOP_K,
                           rerank=True, allowed_document_ids=bench["all"])
    assert result["hits"], "a missing reranker must not empty the results"
    assert _where(bench, result["hits"][0]) == ("PUMPSPEC", 2)


# ================================================================ 5. citations

def test_every_hit_cites_page_clause_and_a_verbatim_quote(bench):
    conn = db.connect()
    headings = {(k, i + 1): h for k, clauses in CORPUS.items()
                for i, (h, _b) in enumerate(clauses)}
    checked = 0
    for query, _kind, _expected in POSITIVES:
        for hit in search.search(query, limit=TOP_K, rerank=False,
                                 allowed_document_ids=bench["all"])["hits"]:
            key, page = _where(bench, hit)
            assert key is not None and 1 <= page <= len(CORPUS[key])
            assert hit["page_end"] >= page
            pages = " ".join(r[0] or "" for r in conn.execute(
                "SELECT text FROM pages WHERE document_id = ? AND page_no BETWEEN ? AND ?",
                (hit["document_id"], page, hit["page_end"])))
            body = _norm(hit["text"])
            assert body and body in _norm(pages), f"quote not verbatim on page {page}"
            assert hit["section"] and _norm(headings[(key, page)]).startswith(
                _norm(hit["section"]).split(" ")[0]), (
                f"clause {hit['section']!r} is not the heading on {key} p{page}")
            checked += 1
    assert checked >= len(POSITIVES)


# ================================================================ 6. permissions

def test_a_document_outside_the_grants_is_absent_from_every_stage(bench):
    hidden = bench["ids"]["COATSPEC"]
    allowed = bench["all"] - {hidden}
    for query in ["Sa 2.5 abrasive blast surface profile", "how do we fix scratched paint",
                  "SSPC-PA 2 spot readings"]:
        stages = {
            "keyword": keyword.search(query, limit=10, allowed_document_ids=allowed),
            "dense": search.dense_search(query, limit=10, allowed_document_ids=allowed),
            "hybrid": search.search(query, limit=10, allowed_document_ids=allowed)["hits"],
        }
        for stage, hits in stages.items():
            assert hidden not in {h["document_id"] for h in hits}, (stage, query)


def test_the_mask_applies_before_top_k_so_the_caller_loses_nothing(bench):
    """A hidden document must not take slots: with only PUMPSPEC granted, a
    top-3 dense search returns 3 PUMPSPEC hits even for a coating question."""
    pump = frozenset({bench["ids"]["PUMPSPEC"]})
    hits = search.dense_search("which layers of paint are applied", limit=3,
                               allowed_document_ids=pump)
    assert len(hits) == 3 and {h["document_id"] for h in hits} == set(pump)


def test_an_empty_grant_returns_nothing_at_all(bench):
    assert search.search("vibration", limit=TOP_K, allowed_document_ids=frozenset())["hits"] == []


# ================================================================ 7. measured

def test_recall_mrr_precision_and_latency_are_measured(bench):
    """The B6 measurement, on the SYNTHETIC set. Reported in the test log as a
    warning (the CI log prints warnings) and held to floors well below what a
    working pipeline scores, so a broken stage fails the build."""
    ranks, latencies = [], []
    for query, _kind, expected in POSITIVES:
        started = time.perf_counter()
        hits = search.search(query, limit=TOP_K, rerank=True,
                             allowed_document_ids=bench["all"])["hits"]
        latencies.append(time.perf_counter() - started)
        ranks.append(_rank(bench, hits, expected))
    n = len(ranks)
    recall_1 = sum(r == 1 for r in ranks) / n
    recall_5 = sum(r is not None for r in ranks) / n
    mrr = sum(1 / r for r in ranks if r) / n
    precision_5 = sum(1 for r in ranks if r) / (n * TOP_K)

    negative_top, negative_flagged = [], 0
    for query in NEGATIVES:
        started = time.perf_counter()
        result = search.search(query, limit=TOP_K, rerank=True,
                               allowed_document_ids=bench["all"])
        latencies.append(time.perf_counter() - started)
        negative_flagged += bool(result["low_confidence"]) or not result["hits"]
        if result["hits"]:
            negative_top.append(result["hits"][0]["rerank_score"])
    positive_top = [search.search(q, limit=1, rerank=True,
                                  allowed_document_ids=bench["all"])["hits"][0]["rerank_score"]
                    for q, _k, _e in POSITIVES]

    ordered = sorted(latencies)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    report = (
        f"B6 SYNTHETIC retrieval benchmark ({n} positive, {len(NEGATIVES)} negative queries, "
        f"hybrid + rerank, top {TOP_K}): recall@1 {recall_1:.2f}, recall@{TOP_K} "
        f"{recall_5:.2f}, MRR {mrr:.2f}, precision@{TOP_K} {precision_5:.2f} (max 0.20, one "
        f"answering page per query); negatives flagged low-confidence {negative_flagged} of "
        f"{len(NEGATIVES)}; best negative rerank score "
        f"{max(negative_top) if negative_top else None}, worst positive top score "
        f"{min(positive_top):.2f}; latency p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms "
        f"(CI runner, not the 16 GB laptop)")
    warnings.warn(report, UserWarning, stacklevel=1)
    print(report)

    assert recall_5 >= 0.75, report
    assert mrr >= 0.6, report
    assert p95 < 5.0, report
