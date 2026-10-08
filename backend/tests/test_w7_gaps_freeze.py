"""#606: one Gap analysis run cannot freeze the backend.

Invented engineering text only. The retrieval step (`analysis.gather`) is
replaced by a function returning synthetic passages, because retrieval needs
the embedding model; everything this issue is about (acronym map, claim
extraction, clustering, the budget, single flight) runs for real against a
throwaway database of many documents.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import access, acronyms, analysis, claims, db
from app.config import settings

SUBJECTS = ["design pressure", "test pressure", "coating thickness", "wall thickness",
            "operating temperature", "flange rating", "bolt torque", "noise level"]
UNITS = [("bar", [1, 5, 10, 16, 25]), ("mm", [2, 3, 6, 12]), ("kPa", [100, 350]), ("dB(A)", [80, 85, 90])]


def _text(rnd: random.Random, sentences: int) -> str:
    out = []
    for _ in range(sentences):
        subject = rnd.choice(SUBJECTS)
        unit, values = rnd.choice(UNITS)
        value = rnd.choice(values)
        clause = f"{rnd.randint(1, 12)}.{rnd.randint(1, 9)}.{rnd.randint(1, 9)}"
        form = rnd.randint(0, 2)
        if form == 0:
            out.append(f"{clause} The {subject} shall not exceed {value} {unit} unless Table {rnd.randint(1, 9)} says otherwise.")
        elif form == 1:
            out.append(f"{subject.capitalize()} {value} {unit} | {rnd.choice(values)} {unit} | Note {rnd.randint(1, 9)}")
        else:
            out.append(f"Non-destructive examination (NDE) of the {subject} is required, see clause {clause} (PWHT).")
    return " ".join(out)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w7.sqlite")
    monkeypatch.setattr(settings, "startup_warmup", False)
    db.reset_connection()
    db.init_db()
    acronyms.reset_cache()
    rnd = random.Random(11)
    con = db.connect()
    ids = []
    with con:
        for d in range(120):
            did = f"doc{d:04d}"
            ids.append(did)
            con.execute(
                "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, page_count, pages_done,"
                " chunk_count, chunk_count_total, chunk_signature, status, uploaded_at, indexed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, f"STD-{d:03d}.pdf", hashlib.sha256(did.encode()).hexdigest(), 1, "/x", 10, 10, 40, 40,
                 f"sig{d}", "ready", "2026-01-01", "2026-01-01"))
            for o in range(40):
                text = _text(rnd, rnd.randint(4, 10))
                con.execute(
                    "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end, section, kind,"
                    " text, token_count, content_hash, retrievable) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (f"{did}-{o}", did, f"STD-{d:03d}.pdf", o, o // 4 + 1, o // 4 + 1, f"{o // 4 + 1}.1", "prose",
                     text, len(text) // 4, hashlib.sha256(text.encode()).hexdigest()))
    yield ids
    db.reset_connection()


def _evidence(ids, n=60, chars=3000):
    rnd = random.Random(5)
    out = []
    for i in range(n):
        text = _text(rnd, 60)
        while len(text) < chars:
            text += " " + _text(rnd, 10)
        out.append({"evidence_id": f"e{i}", "document_id": ids[i % len(ids)], "filename": f"STD-{i % len(ids):03d}.pdf",
                    "page_start": 1, "section": "1.1", "text": text, "exact_span": text})
    return out


def _stub_gather(monkeypatch, evidence, counter=None, delay=0.0):
    def fake(question, scope, *, limit=8, document_id=None):
        if counter is not None:
            counter.append(1)
        if delay:
            time.sleep(delay)
        return evidence[:limit], {}
    monkeypatch.setattr(analysis, "gather", fake)


def _scope(ids):
    return access.AccessScope(user_id=None, allowed_document_ids=frozenset(ids))


def test_a_cold_acronym_map_is_not_built_inside_the_request(corpus, monkeypatch):
    built = []
    real = acronyms._build_document_map
    monkeypatch.setattr(acronyms, "_build_document_map", lambda *a, **k: built.append(a[0]) or real(*a, **k))
    _stub_gather(monkeypatch, _evidence(corpus, n=6, chars=800))
    out = analysis.gaps("design pressure", _scope(corpus), limit=6)
    assert built == [], "a request built a document's acronym map"
    assert out["acronym_map"] == {"documents_not_ready": len(corpus), "complete": False}


def test_after_the_background_build_the_same_request_is_complete(corpus, monkeypatch):
    assert acronyms.warm_all() == len(corpus)
    assert acronyms.warm_all() == 0                       # nothing changed, nothing rebuilt
    _stub_gather(monkeypatch, _evidence(corpus, n=6, chars=800))
    out = analysis.gaps("design pressure", _scope(corpus), limit=6)
    assert out["acronym_map"] == {"documents_not_ready": 0, "complete": True}


def test_a_changed_document_is_rebuilt_and_the_others_are_not(corpus):
    acronyms.warm_all()
    with db.connect() as con:
        con.execute("UPDATE documents SET chunk_signature = 'new' WHERE id = ?", (corpus[0],))
    assert acronyms.warm_all() == 1


def test_n_claims_read_the_corpus_once_not_n_times(corpus, monkeypatch):
    acronyms.warm_all()
    calls = []
    real = acronyms._signatures
    monkeypatch.setattr(acronyms, "_signatures", lambda *a, **k: calls.append(1) or real(*a, **k))
    rows = claims.extract_claims(_evidence(corpus, n=4, chars=1500),
                                 allowed_document_ids=frozenset(corpus))
    assert len(rows) >= 40, "the fixture must produce many claims"
    assert len(calls) == 1, f"{len(calls)} corpus reads for {len(rows)} claims"


def test_two_concurrent_identical_gap_runs_do_the_work_once(corpus, monkeypatch):
    runs = []
    _stub_gather(monkeypatch, _evidence(corpus, n=6, chars=800), counter=runs, delay=0.6)
    results = []

    def call():
        results.append(analysis.gaps("design pressure", _scope(corpus), limit=6))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(runs) == 1, "the same request ran twice at once"
    assert sorted(r.get("coalesced", False) for r in results) == [False, True]


def test_different_requests_are_not_merged(corpus, monkeypatch):
    runs = []
    _stub_gather(monkeypatch, _evidence(corpus, n=6, chars=800), counter=runs, delay=0.3)
    threads = [threading.Thread(target=lambda q=q: analysis.gaps(q, _scope(corpus), limit=6))
               for q in ("design pressure", "wall thickness")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(runs) == 2


def test_a_second_caller_after_the_first_finished_runs_again(corpus, monkeypatch):
    runs = []
    _stub_gather(monkeypatch, _evidence(corpus, n=4, chars=800), counter=runs)
    analysis.gaps("design pressure", _scope(corpus), limit=4)
    analysis.gaps("design pressure", _scope(corpus), limit=4)
    assert len(runs) == 2, "a finished run must not be cached as an answer"


def test_a_heavy_run_stops_at_its_budget_and_says_it_was_cut(corpus, monkeypatch):
    acronyms.warm_all()
    monkeypatch.setattr(settings, "analysis_gaps_budget_seconds", 0.4)
    _stub_gather(monkeypatch, _evidence(corpus, n=60, chars=6000))
    start = time.perf_counter()
    out = analysis.gaps("design pressure", _scope(corpus), limit=60)
    took = time.perf_counter() - start
    assert out["truncated"] is True
    assert "time budget" in out["truncation_reason"]
    assert took < 5, f"the run took {took:.1f}s against a 0.4s budget"


def test_the_claim_cap_truncates_with_a_reason(corpus, monkeypatch):
    acronyms.warm_all()
    monkeypatch.setattr(settings, "analysis_max_claims", 15)
    _stub_gather(monkeypatch, _evidence(corpus, n=6, chars=2000))
    out = analysis.gaps("design pressure", _scope(corpus), limit=6)
    assert out["truncated"] is True and "claim cap of 15" in out["truncation_reason"]
    assert sum(len(c["rows"]) for c in out["claim_clusters"]) <= 15


def test_an_evidence_request_above_the_cap_is_cut_and_said(corpus, monkeypatch):
    acronyms.warm_all()
    monkeypatch.setattr(settings, "analysis_max_evidence", 3)
    seen = []
    def fake(question, scope, *, limit=8, document_id=None):
        seen.append(limit)
        return _evidence(corpus, n=3, chars=500), {}
    monkeypatch.setattr(analysis, "gather", fake)
    out = analysis.gaps("design pressure", _scope(corpus), limit=500)
    assert seen == [3]
    assert out["truncated"] is True and "capped at 3" in out["truncation_reason"]


def test_a_run_inside_its_budget_is_not_marked_truncated(corpus, monkeypatch):
    acronyms.warm_all()
    _stub_gather(monkeypatch, _evidence(corpus, n=4, chars=800))
    out = analysis.gaps("design pressure", _scope(corpus), limit=4)
    assert out["truncated"] is False and out["truncation_reason"] is None


def test_health_answers_within_a_second_while_a_heavy_run_is_going(corpus, monkeypatch):
    monkeypatch.setattr(settings, "analysis_gaps_budget_seconds", 3.0)
    _stub_gather(monkeypatch, _evidence(corpus, n=60, chars=6000))
    from app.main import app
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/health").status_code == 200
    box = {}

    def heavy():
        t = time.perf_counter()
        box["out"] = analysis.gaps("design pressure", _scope(corpus), limit=60)
        box["took"] = time.perf_counter() - t

    th = threading.Thread(target=heavy)
    th.start()
    time.sleep(0.3)
    worst = 0.0
    while th.is_alive():
        t = time.perf_counter()
        assert client.get("/api/health").status_code == 200
        worst = max(worst, time.perf_counter() - t)
        time.sleep(0.2)
    th.join()
    assert worst < 1.0, f"health took {worst:.2f}s during a heavy run"
    assert box["took"] < 15, f"the heavy run took {box['took']:.1f}s against a 3s budget"


def test_two_cold_requests_build_a_documents_map_once(corpus, monkeypatch):
    """Both threads find the map cold; the second waits for the first."""
    built = []
    real = acronyms._build_document_map

    def slow(document_id, key):
        built.append(document_id)
        time.sleep(0.3)
        return real(document_id, key)

    monkeypatch.setattr(acronyms, "_build_document_map", slow)
    signature = acronyms._signatures(None, frozenset(corpus[:1]))[corpus[0]]
    threads = [threading.Thread(target=lambda: acronyms._document_map(corpus[0], signature))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert built == [corpus[0]], f"the same map was built {len(built)} times"


def test_a_background_warm_does_not_start_when_background_jobs_are_off(corpus, monkeypatch):
    monkeypatch.setattr(settings, "startup_warmup", False)
    assert acronyms.warm_in_background() is False
