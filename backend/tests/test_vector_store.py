"""The dense-search vector store (`app/vector_store.py`).

Owner decision 2026-09-27: vectors are searched through sqlite-vec, a free
in-process SQLite extension, with the exact numpy matrix as the automatic
fallback. What must hold, each asserted below and each mutation-proven
(scripts/mutations/vector_store.py, M1265-M1284):

  PARITY      sqlite-vec returns the same top-k, with the same scores, as a
              plain numpy brute force computed IN THIS FILE - on full, wide and
              narrow scopes (the three query paths).
  SCOPE       never a chunk of a document outside `allowed_document_ids`, and
              the scope is applied BEFORE top-k (the caller loses nothing).
  FALLBACK    extension unavailable -> exact numpy, reported, logged once.
  STALE       a vector with another model/input tag is never searched, is
              counted, and `embed_pending` re-embeds it.
  FRESHNESS   every write that changes what may be returned reaches the index
              (vector added/deleted, chunk excluded, chunk deleted).
  NO SCAN     a query when nothing changed runs no statement over `chunks`
              (the audit's per-query chunk->doc rebuild, L3).
"""

from __future__ import annotations

import logging
import socket
import sqlite3

import numpy as np
import pytest

from app import db, embedder, keyword, metrics, schemas, vector_store, vectorcache
from app.config import settings
from app.db import connect
from app.embedder import EMBEDDING_DIM, embedding_tag

RNG_SEED = 20260927


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "vector_backend", "auto")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    vector_store.reset()
    yield
    vector_store.reset()
    db.reset_connection()


def _unit(rng, n):
    x = rng.standard_normal((n, EMBEDDING_DIM)).astype(np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def _add_document(conn, doc, vectors, tag=None, start=0):
    conn.execute(
        "INSERT OR IGNORE INTO documents (id, filename, sha256, size_bytes, stored_path,"
        " status, uploaded_at) VALUES (?, ?, ?, 1, 'p', 'ready', '2026-09-27T00:00:00Z')",
        (doc, f"{doc}.pdf", doc))
    for i, v in enumerate(vectors, start=start):
        cid = f"{doc}:c{i}"
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
            " page_end, kind, section, text, token_count, content_hash, retrievable)"
            " VALUES (?, ?, 'a.pdf', ?, 1, 1, 'prose', 'Heading', ?, 4, ?, 1)",
            (cid, doc, i, f"text for {cid}", cid))
        conn.execute(
            "INSERT INTO chunk_vectors (chunk_id, document_id, dim, vector, model,"
            " created_at) VALUES (?, ?, ?, ?, ?, '2026-09-27T00:00:00Z')",
            (cid, doc, EMBEDDING_DIM, v.astype(np.float32).tobytes(),
             tag or embedding_tag()))


@pytest.fixture
def corpus():
    """40 documents of uneven size (1 to ~300 chunks), 3,000-ish vectors."""
    rng = np.random.default_rng(RNG_SEED)
    sizes = np.maximum(1, rng.lognormal(3.6, 1.0, 40).astype(int))
    conn = connect()
    docs = {}
    with conn:
        for n, size in enumerate(sizes):
            doc = f"doc{n:02d}"
            docs[doc] = _unit(rng, int(size))
            _add_document(conn, doc, docs[doc])
    return docs


def _reference(docs, q, scope, limit):
    """Plain numpy brute force, written here and nowhere else: the oracle."""
    ids, rows = [], []
    for doc, vecs in docs.items():
        if doc in scope:
            ids += [f"{doc}:c{i}" for i in range(len(vecs))]
            rows.append(vecs)
    if not rows:
        return []
    scores = np.vstack(rows) @ q
    order = np.argsort(-scores, kind="stable")[:limit]
    return [(ids[i], float(scores[i])) for i in order]


def _run(q, scope, limit=30, document_id=None):
    return vector_store.search(lambda: q, limit=limit, allowed_document_ids=frozenset(scope),
                               document_id=document_id)


def _owner(chunk_id):
    return chunk_id.split(":")[0]


# ------------------------------------------------------------------ backend


def test_sqlite_vec_is_the_active_backend_when_the_extension_loads():
    """Guards every parity test below: without this they could all be
    passing on the numpy path and prove nothing about sqlite-vec."""
    active, reason = vector_store.backend()
    assert (active, reason) == ("sqlite_vec", None)
    status = vector_store.status()
    assert status["active"] == "sqlite_vec"
    assert status["sqlite_vec_version"]


# ------------------------------------------------------------------- PARITY


@pytest.mark.parametrize("backend_name", ["sqlite_vec", "numpy"])
@pytest.mark.parametrize("limit", [30, 200])
def test_full_scope_top_k_and_scores_match_exact_numpy(corpus, monkeypatch, backend_name, limit):
    """limit 200 as well as 30: numpy's argpartition happens to come back
    sorted for small k, so only a larger k proves the final ordering."""
    monkeypatch.setattr(settings, "vector_backend", "auto" if backend_name == "sqlite_vec" else "numpy")
    assert vector_store.backend()[0] == backend_name
    rng = np.random.default_rng(1)
    everything = set(corpus)
    for q in _unit(rng, 12):
        got = _run(q, everything, limit=limit)
        want = _reference(corpus, q, everything, limit)
        assert [h["chunk_id"] for h in got] == [w[0] for w in want]
        assert np.allclose([h["cosine"] for h in got], [w[1] for w in want], atol=1e-5)


def _scopes(corpus):
    names = sorted(corpus, key=lambda d: -len(corpus[d]))
    return {
        # one small and a few documents: the partition-key path
        "narrow-1": {names[-1]},
        "narrow-3": set(names[10:13]),
        # everything but two small documents: the widened-k post-filter path
        "wide": set(names[:-2]),
        # the biggest document alone is still narrow
        "largest": {names[0]},
    }


@pytest.mark.parametrize("scope_name", ["narrow-1", "narrow-3", "wide", "largest"])
def test_scoped_recall_equals_exact_on_every_query_path(corpus, scope_name):
    """Recall@30 = 1.0 against the oracle on each path sqlite-vec takes."""
    scope = _scopes(corpus)[scope_name]
    rng = np.random.default_rng(2)
    queries = list(_unit(rng, 8))
    # and queries aimed straight at OUT-of-scope vectors, so the hidden rows
    # really do outrank every in-scope one
    hidden = [d for d in corpus if d not in scope][:4]
    queries += [corpus[d][0] for d in hidden]
    for q in queries:
        got = _run(q, scope)
        want = _reference(corpus, q, scope, 30)
        assert [h["chunk_id"] for h in got] == [w[0] for w in want], scope_name
        assert np.allclose([h["cosine"] for h in got], [w[1] for w in want], atol=1e-5)


# -------------------------------------------------------------------- SCOPE


@pytest.mark.parametrize("backend_name", ["auto", "numpy"])
def test_never_returns_a_document_outside_the_scope(corpus, monkeypatch, backend_name):
    """ACCESS CONTROL (CLAUDE.md rule 5). The query IS a hidden chunk's own
    vector, so without the filter that chunk would rank first."""
    monkeypatch.setattr(settings, "vector_backend", backend_name)
    rng = np.random.default_rng(3)
    names = sorted(corpus)
    for trial in range(12):
        scope = set(rng.choice(names, size=int(rng.integers(1, len(names))), replace=False))
        hidden = [d for d in names if d not in scope]
        q = corpus[hidden[trial % len(hidden)]][0]
        hits = _run(q, scope, limit=50)
        assert hits, "nothing returned: this check would pass vacuously"
        assert {_owner(h["chunk_id"]) for h in hits} <= scope


def test_document_id_only_narrows_the_scope(corpus):
    """`document_id` is a filter, and a filter is an intersection: naming a
    document the caller may not read returns nothing, not that document."""
    a, b = sorted(corpus)[:2]
    q = corpus[b][0]
    assert _run(q, {a}, document_id=b) == []
    hits = _run(q, {a, b}, document_id=b)
    assert hits and {_owner(h["chunk_id"]) for h in hits} == {b}


def test_the_scope_is_applied_before_top_k_so_nothing_is_lost(corpus):
    """With one document granted, a top-k is k of THAT document's chunks even
    when the query sits squarely on another document."""
    names = sorted(corpus, key=lambda d: -len(corpus[d]))
    granted, other = names[0], names[1]
    hits = _run(corpus[other][0], {granted}, limit=10)
    assert len(hits) == min(10, len(corpus[granted]))


def test_an_empty_scope_returns_nothing_and_never_embeds(corpus):
    def must_not_embed():
        raise AssertionError("the query was embedded for an empty scope")
    assert vector_store.search(must_not_embed, limit=30, allowed_document_ids=frozenset()) == []
    assert vector_store.search(must_not_embed, limit=30,
                               allowed_document_ids=frozenset({"no-such-document"})) == []


# ----------------------------------------------------------------- FALLBACK


def test_extension_unavailable_falls_back_to_exact_numpy_and_says_so(corpus, monkeypatch, caplog):
    def cannot_load(conn):
        raise ImportError("No module named 'sqlite_vec'")
    monkeypatch.setattr(vector_store, "_load_extension", cannot_load)
    vector_store.reset()
    caplog.set_level(logging.WARNING, logger="uvicorn.error")

    active, reason = vector_store.backend()
    assert active == "numpy"
    assert reason == "the sqlite-vec package is not installed"
    status = vector_store.status()
    assert status["active"] == "numpy" and status["fallback_reason"] == reason
    assert status["sqlite_vec_version"] is None

    rng = np.random.default_rng(4)
    everything = set(corpus)
    for q in _unit(rng, 3):
        got = _run(q, everything)
        assert [h["chunk_id"] for h in got] == [w[0] for w in _reference(corpus, q, everything, 30)]
    said = [r for r in caplog.records if "exact numpy backend in use" in r.getMessage()]
    assert len(said) == 1, f"the fallback must be logged exactly once, got {len(said)}"
    assert not vector_store.index_path().exists(), "the index was built without the extension"


def test_a_failing_index_answers_from_numpy_and_reports_it(corpus, monkeypatch):
    def broken(*a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(vector_store, "_sqlite_vec_search", broken)
    q = corpus[sorted(corpus)[0]][0]
    got = _run(q, set(corpus))
    assert [h["chunk_id"] for h in got] == [w[0] for w in _reference(corpus, q, set(corpus), 30)]
    assert "malformed" in (vector_store.status()["last_error"] or "")


def test_numpy_can_be_chosen_explicitly_and_builds_no_index(corpus, monkeypatch):
    monkeypatch.setattr(settings, "vector_backend", "numpy")
    assert vector_store.backend() == ("numpy", "VECTOR_BACKEND=numpy")
    assert _run(corpus[sorted(corpus)[0]][0], set(corpus))
    assert not vector_store.index_path().exists()


# -------------------------------------------------------------------- STALE


@pytest.mark.parametrize("backend_name", ["auto", "numpy"])
def test_a_vector_from_another_model_is_stale_not_searched(corpus, monkeypatch, backend_name):
    monkeypatch.setattr(settings, "vector_backend", backend_name)
    rng = np.random.default_rng(5)
    old = _unit(rng, 6)
    conn = connect()
    with conn:
        _add_document(conn, "legacy", old, tag="model_qint8_avx512_vnni.onnx")  # body-only era
    hits = _run(old[0], set(corpus) | {"legacy"}, limit=50)
    assert hits, "vacuous: nothing returned"
    assert "legacy" not in {_owner(h["chunk_id"]) for h in hits}, (
        "a vector made from another input format was searched")
    status = vector_store.status(include_counts=True)
    assert status["stale_vectors"] == 6
    assert status["current_vectors"] == sum(len(v) for v in corpus.values())


def test_a_tag_change_makes_every_vector_stale(corpus, monkeypatch):
    q = corpus[sorted(corpus)[0]][0]
    assert _run(q, set(corpus))
    monkeypatch.setattr(embedder, "PASSAGE_INPUT_VERSION", "heading-v2")
    assert _run(q, set(corpus)) == [], "vectors of the old input format were still searched"
    assert vector_store.status(include_counts=True)["current_vectors"] == 0


def test_embed_pending_re_embeds_a_stale_vector():
    """The re-embed path. Real model: the vector must come back CURRENT."""
    from app.ingest import IngestionWorker

    rng = np.random.default_rng(6)
    conn = connect()
    with conn:
        _add_document(conn, "legacy", _unit(rng, 2), tag="some-older-model.onnx+heading-v0")
    assert vector_store.status(include_counts=True)["stale_vectors"] == 2
    done = IngestionWorker().embed_pending("legacy")
    assert done == 2
    tags = {r[0] for r in conn.execute(
        "SELECT model FROM chunk_vectors WHERE document_id = 'legacy'")}
    assert tags == {embedding_tag()}
    status = vector_store.status(include_counts=True)
    assert (status["stale_vectors"], status["current_vectors"]) == (0, 2)
    assert conn.execute("SELECT embedded_count FROM documents WHERE id = 'legacy'").fetchone()[0] == 2


def test_embedded_count_counts_only_current_vectors():
    from app.ingest import IngestionWorker

    rng = np.random.default_rng(7)
    conn = connect()
    with conn:
        _add_document(conn, "mixed", _unit(rng, 3))
        _add_document(conn, "mixed", _unit(rng, 2), tag="old+heading-v0", start=3)
    assert IngestionWorker()._recount_embedded("mixed") == 3


# ---------------------------------------------------------------- FRESHNESS


def test_every_relevant_write_reaches_the_index(corpus):
    names = sorted(corpus)
    everything = set(corpus) | {"late"}
    conn = connect()
    rng = np.random.default_rng(8)
    late = _unit(rng, 3)

    assert _run(late[0], everything)[0]["chunk_id"] != "late:c0"
    with conn:
        _add_document(conn, "late", late)
    assert _run(late[0], everything)[0]["chunk_id"] == "late:c0", "an added vector was missed"

    with conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE id = 'late:c0'")
    assert "late:c0" not in {h["chunk_id"] for h in _run(late[0], everything)}, (
        "an excluded chunk stayed searchable")

    with conn:
        conn.execute("UPDATE chunks SET retrievable = 1 WHERE id = 'late:c0'")
    assert _run(late[0], everything)[0]["chunk_id"] == "late:c0", "a restored chunk never came back"

    with conn:
        conn.execute("DELETE FROM chunks WHERE id = 'late:c0'")   # vector orphaned
    assert "late:c0" not in {h["chunk_id"] for h in _run(late[0], everything)}, (
        "an orphaned vector was searched")

    target = names[0]
    with conn:
        conn.execute("DELETE FROM chunk_vectors WHERE document_id = ?", (target,))
    assert target not in {_owner(h["chunk_id"]) for h in _run(corpus[target][0], everything, 100)}


def test_backfill_is_idempotent_and_embeds_nothing(corpus, monkeypatch):
    def no_model(*a, **k):
        raise AssertionError("the backfill tried to embed")
    monkeypatch.setattr(embedder.Embedder, "instance", no_model)
    first = vector_store.sync()
    assert first["documents_synced"] == len(corpus)
    assert first["vectors"] == sum(len(v) for v in corpus.values())
    again = vector_store.sync()
    assert again["documents_synced"] == 0 and again["documents_dropped"] == 0
    assert again["vectors"] == first["vectors"]


def test_a_query_when_nothing_changed_scans_nothing(corpus, monkeypatch):
    """The audit's L3: the per-query chunk->doc map and signature scans were
    98% of the dense stage. After the first query, the next runs no
    statement over `chunks` or `chunk_vectors`, and no sync."""
    q = corpus[sorted(corpus)[0]][0]
    for backend_name in ("auto", "numpy"):
        monkeypatch.setattr(settings, "vector_backend", backend_name)
        _run(q, set(corpus))
        seen: list[str] = []
        connect().set_trace_callback(seen.append)
        try:
            calls = []
            real_sync = vector_store.sync
            monkeypatch.setattr(vector_store, "sync", lambda: (calls.append(1), real_sync())[1])
            _run(q, set(corpus))
        finally:
            connect().set_trace_callback(None)
            monkeypatch.setattr(vector_store, "sync", real_sync)
        touched = [s for s in seen if "chunks" in s or "chunk_vectors" in s]
        assert touched == [], (backend_name, touched)
        assert calls == [], f"{backend_name}: the index re-synced with nothing changed"


# ------------------------------------------------------- PLACEMENT, SOCKETS


def test_the_index_lives_outside_the_live_database(corpus):
    """A vec0 table in rag_intelligence.sqlite would make every plain-sqlite3
    COUNT(*) of every table - backup verify, restore drill, admin explorer -
    fail with 'no such module: vec0'. The live database stays readable by a
    connection that never loaded the extension."""
    _run(corpus[sorted(corpus)[0]][0], set(corpus))
    assert vector_store.index_path().exists()
    assert vector_store.index_path().resolve() != settings.db_path.resolve()
    plain = sqlite3.connect(settings.db_path)
    try:
        for (name,) in plain.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
            plain.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
    finally:
        plain.close()


def test_the_vector_store_opens_no_socket(corpus, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the vector store opened a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    vector_store.reset()
    assert vector_store.startup()["active"] == "sqlite_vec"
    assert _run(corpus[sorted(corpus)[0]][0], set(corpus))


# ------------------------------------------------------------- SYSTEM HEALTH


def test_system_health_reports_the_backend_and_gates_the_counts(corpus, monkeypatch):
    monkeypatch.setattr(metrics, "models", lambda: {
        "embed_model": "e5", "embed_model_present": True, "reranker_model": "r",
        "reranker_present": True, "answer_model": "m", "answer_model_reachable": False,
        "answer_model_loaded": False, "ollama_error": None})
    worker = {"alive": True, "stalled": False, "current_document": None,
              "documents_completed": 0, "last_error": None, "stalled_reasons": []}
    admin = metrics.snapshot(worker, None, True, True)["vector_store"]
    engineer = metrics.snapshot(worker, [], False, False)["vector_store"]
    schemas.VectorStoreStatus(**admin)
    assert admin["active"] == "sqlite_vec"
    assert admin["current_vectors"] == sum(len(v) for v in corpus.values())
    assert engineer["active"] == "sqlite_vec"
    assert engineer["current_vectors"] is None and engineer["stale_vectors"] is None
