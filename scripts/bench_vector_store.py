"""Dense-stage benchmark: the old per-query path vs both vector-store backends.

    python scripts/bench_vector_store.py [--sizes 25000 100000 200000] [--queries 20]

SYNTHETIC ONLY. Builds a throwaway database in a temporary directory with
random unit 384-d vectors spread over documents of lognormal size (~99 chunks
per document on average, like the owner's library), and never opens the live
database. The query embedder is not run: every method gets the same query
vectors, so the numbers are the dense stage alone.

Methods, each timed warm (median and p95 of the queries) per scope:

    before      the pre-2026-09-27 path, reproduced faithfully: the three
                aggregate signature queries, a chunk->document dict built from
                every `chunks` row, a Python-list mask, full argsort
    numpy       vector_store with VECTOR_BACKEND=numpy (vectorcache)
    sqlite_vec  vector_store with the sqlite-vec vec0 index

Recall@30 of each method is measured against a plain numpy brute force over
the same scope. Prints ids and numbers only.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

K = 30


def _build(n: int, rng) -> tuple[dict[str, np.ndarray], float]:
    from app import db
    from app.embedder import EMBEDDING_DIM, embedding_tag

    sizes = np.maximum(1, rng.lognormal(4.2, 1.0, max(2, n // 99)))
    sizes = np.maximum(1, (sizes / sizes.sum() * n)).astype(int)
    conn = db.connect()
    docs: dict[str, np.ndarray] = {}
    tag = embedding_tag()
    started = time.perf_counter()
    with conn:
        for d, size in enumerate(sizes):
            doc = f"d{d:05d}"
            x = rng.standard_normal((int(size), EMBEDDING_DIM)).astype(np.float32)
            x /= np.linalg.norm(x, axis=1, keepdims=True)
            docs[doc] = x
            conn.execute(
                "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
                " status, uploaded_at) VALUES (?, ?, ?, 1, 'p', 'ready', 'now')",
                (doc, doc, doc))
            conn.executemany(
                "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
                " page_end, kind, text, token_count, content_hash, retrievable)"
                " VALUES (?, ?, 'f', ?, 1, 1, 'prose', 't', 1, ?, 1)",
                [(f"{doc}:{i}", doc, i, f"{doc}:{i}") for i in range(len(x))])
            conn.executemany(
                "INSERT INTO chunk_vectors (chunk_id, document_id, dim, vector, model,"
                " created_at) VALUES (?, ?, 384, ?, ?, 'now')",
                [(f"{doc}:{i}", doc, v.tobytes(), tag) for i, v in enumerate(x)])
    return docs, time.perf_counter() - started


def _before(q: np.ndarray, scope: frozenset[str], state: dict) -> list[str]:
    """The old search.dense_search + vectorcache.load, per query."""
    from app.db import connect

    conn = connect()
    sig = (tuple(conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(chunk_count), 0), COALESCE(SUM(embedded_count), 0),"
        " COALESCE(GROUP_CONCAT(chunk_signature), '') FROM documents").fetchone())
        + tuple(conn.execute("SELECT COUNT(*), COALESCE(MAX(rowid), 0), MIN(chunk_id),"
                             " MAX(chunk_id) FROM chunk_vectors").fetchone())
        + tuple(conn.execute("SELECT COUNT(*), COALESCE(SUM(rowid), 0) FROM chunks"
                             " WHERE retrievable = 0").fetchone()))
    if state.get("sig") != sig:
        rows = conn.execute("SELECT v.chunk_id, v.vector FROM chunk_vectors v JOIN chunks c"
                            " ON c.id = v.chunk_id WHERE c.retrievable = 1").fetchall()
        state.update(sig=sig, ids=[r[0] for r in rows], matrix=np.frombuffer(
            b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), 384))
    ids, matrix = state["ids"], state["matrix"]
    scores = matrix @ q
    owner = {r[0]: r[1] for r in conn.execute("SELECT id, document_id FROM chunks")}
    mask = np.array([owner.get(cid) in scope for cid in ids], dtype=bool)
    scores = np.where(mask, scores, -np.inf)
    top = np.argsort(-scores)[:K]
    return [ids[i] for i in top if np.isfinite(scores[i])]


def _oracle(docs, q, scope) -> list[str]:
    ids, rows = [], []
    for doc in sorted(scope):
        ids += [f"{doc}:{i}" for i in range(len(docs[doc]))]
        rows.append(docs[doc])
    s = np.vstack(rows) @ q
    return [ids[i] for i in np.argsort(-s)[:K]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sizes", type=int, nargs="+", default=[25_000, 100_000, 200_000])
    ap.add_argument("--queries", type=int, default=20)
    args = ap.parse_args()

    from app import db, vector_store
    from app.config import settings

    print("N | docs | scope | rows in scope | method | median ms | p95 ms | recall@30")
    for n in args.sizes:
        with tempfile.TemporaryDirectory(prefix="bench-vs-") as tmp:
            settings.data_dir = Path(tmp)
            settings.db_path = Path(tmp) / "bench.sqlite"
            db.reset_connection()
            db.init_db()
            vector_store.reset()
            rng = np.random.default_rng(n)
            docs, built = _build(n, rng)
            settings.vector_backend = "auto"
            t = time.perf_counter()
            synced = vector_store.sync()
            backfill = time.perf_counter() - t
            size_mb = vector_store.index_path().stat().st_size / 1e6
            print(f"# N={n}: {len(docs)} docs, insert {built:.1f}s, sqlite-vec backfill"
                  f" {backfill:.1f}s ({synced['vectors']} vectors, index file {size_mb:.0f} MB,"
                  f" raw vectors {n * 1536 / 1e6:.0f} MB)")
            names = sorted(docs)
            queries = rng.standard_normal((args.queries, 384)).astype(np.float32)
            queries /= np.linalg.norm(queries, axis=1, keepdims=True)
            for label, frac in (("100%", 1.0), ("10%", 0.10), ("1%", 0.01)):
                scope = frozenset(names if frac == 1.0 else
                                  rng.choice(names, max(1, int(len(names) * frac)), replace=False))
                rows_in = sum(len(docs[d]) for d in scope)
                truth = [_oracle(docs, q, scope) for q in queries]
                state: dict = {}

                def run_vs(q, backend):
                    settings.vector_backend = backend
                    return [h["chunk_id"] for h in vector_store.search(
                        lambda: q, limit=K, allowed_document_ids=scope)]

                methods = {
                    "before": lambda q: _before(q, scope, state),
                    "numpy": lambda q: run_vs(q, "numpy"),
                    "sqlite_vec": lambda q: run_vs(q, "auto"),
                }
                for name, fn in methods.items():
                    fn(queries[0])  # warm: builds the matrix / syncs the index
                    times, recall = [], []
                    for q, want in zip(queries, truth):
                        t = time.perf_counter()
                        got = fn(q)
                        times.append((time.perf_counter() - t) * 1000)
                        recall.append(len(set(got) & set(want)) / len(want))
                    print(f"{n} | {len(docs)} | {label} | {rows_in} | {name} |"
                          f" {np.median(times):.1f} | {np.percentile(times, 95):.1f} |"
                          f" {np.mean(recall):.3f}", flush=True)
            vector_store.reset()
            db.reset_connection()
    return 0


if __name__ == "__main__":
    sys.exit(main())
