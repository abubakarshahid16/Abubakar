"""The exact numpy backend of the vector store: one memory-mapped matrix.

`vector_store.py` is the interface search calls; this module is the backend
it uses when the sqlite-vec extension cannot load (or VECTOR_BACKEND=numpy).
Both backends are exact brute-force cosine and rank identically.

WHY A MAPPED FILE. `_load_vectors` used to re-read every stored vector blob out
of SQLite on every single query (x2.11 across a corpus doubling while the
matmul grew x1.05). The matrix is written once to a file and mapped with
np.memmap, NOT read into the heap: this machine demos at 92% RAM, so a mapped
file is pages the OS can evict and share, while a heap array is pages it
cannot.

WHAT A QUERY NO LONGER PAYS (retrieval audit 2026-09-27, 2.3 / L3). At the
full library (22,784 vectors) 98% of the dense stage was bookkeeping, not
vector math: `signature()` ran three aggregate queries, one a full scan of
`chunks`, and search rebuilt a chunk->document dict from every `chunks` row
and a Python-list mask, per query. Now:

  * validity is ONE indexed read of the corpus generation token that the
    `vector_generation` triggers replace on every relevant write (db.py);
  * each row's document is stored WITH the matrix as an int32 index built in
    the same read, so the scope mask is a vectorised lookup, never a dict;
  * top-k is `np.argpartition`, not a full sort.

SAFETY OF A STALE MATRIX, unchanged: `search()` hydrates every candidate and
drops any row that is gone or not retrievable, so a stale matrix could only
cost ranking quality, never surface an excluded chunk. The scope mask is
applied BEFORE top-k (CLAUDE.md rule 5): an out-of-scope row can never take a
slot or be returned.

THE SEGFAULT (code-review audit 2026-09-25 #8). The old `_close()` closed a
mapping another thread could still be multiplying against (exit 139). Files
are now VERSIONED by generation token and a mapping is never closed while
held: a rebuild writes a new file and drops the reference; the old file is
unlinked when the OS allows (Windows refuses while mapped - it is retried at
the next build).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import NamedTuple

import numpy as np

from .config import settings
from .db import connect
from .embedder import EMBEDDING_DIM, embedding_tag, searchable_tags

_lock = threading.Lock()


class Matrix(NamedTuple):
    """Every current vector of a retrievable chunk, and whose it is."""

    ids: list[str]
    #: row -> index into `documents`, aligned with `ids`
    doc_index: np.ndarray
    documents: list[str]
    matrix: np.ndarray
    #: the corpus generation token this was built at (None: no token table)
    token: int | None


#: (index path, tag) -> the Matrix currently served
_live: dict[tuple[str, str], Matrix] = {}


def cache_dir() -> Path:
    return settings.data_dir / "vector_cache"


def generation(conn: sqlite3.Connection | None = None) -> int | None:
    """The corpus-wide generation token, or None on a database without the
    `vector_generation` table (then nothing is cached: always rebuilt)."""
    try:
        row = (conn or connect()).execute(
            "SELECT token FROM vector_generation WHERE document_id = ''").fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else int(row[0])


def _read_from_db(token: int | None = None) -> Matrix:
    """The direct read: current vectors of retrievable chunks only.

    Joined to `chunks` on id AND document, so an orphaned vector (its chunk
    re-chunked away) or one filed under another document is never served. A
    vector whose `model` tag is not one of `searchable_tags()` is STALE and
    is left out: its cosine against a query embedded by the current model
    means nothing (P2-11). `vector_store.status()` counts those.
    """
    tags = searchable_tags()
    rows = connect().execute(
        f"""SELECT v.chunk_id, v.document_id, v.vector FROM chunk_vectors v
           JOIN chunks c ON c.id = v.chunk_id AND c.document_id = v.document_id
           WHERE c.retrievable = 1 AND v.model IN ({",".join("?" * len(tags))})
             AND length(v.vector) = ?
           ORDER BY v.rowid""",
        (*tags, EMBEDDING_DIM * 4),
    ).fetchall()
    if not rows:
        return Matrix([], np.zeros(0, dtype=np.int32), [],
                      np.zeros((0, EMBEDDING_DIM), dtype=np.float32), token)
    documents: list[str] = []
    position: dict[str, int] = {}
    doc_index = np.empty(len(rows), dtype=np.int32)
    for i, r in enumerate(rows):
        d = r[1]
        if d not in position:
            position[d] = len(documents)
            documents.append(d)
        doc_index[i] = position[d]
    matrix = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32)
    return Matrix([r[0] for r in rows], doc_index, documents,
                  matrix.reshape(len(rows), EMBEDDING_DIM), token)


def _stem(token: int | None) -> str:
    return f"corpus-{(token or 0) & 0xFFFFFFFFFFFFFFFF:016x}"


def _paths(token: int | None) -> tuple[Path, Path]:
    d = cache_dir()
    return d / f"{_stem(token)}.f32", d / f"{_stem(token)}.json"


def _sweep(keep: str) -> None:
    """Remove superseded cache files, including the unversioned per-document
    and `corpus.f32` files of the earlier layout - only this module writes
    here. Best effort: a file still mapped (here or by another process)
    cannot be unlinked on Windows, and is retried at the next build instead
    of being closed underneath its reader."""
    for path in cache_dir().iterdir():
        if path.is_file() and not path.name.startswith(keep):
            try:
                path.unlink()
            except OSError:
                pass


def _map(data_path: Path, rows: int) -> np.ndarray:
    return np.memmap(data_path, dtype=np.float32, mode="r", shape=(rows, EMBEDDING_DIM))


def _build(token: int | None) -> Matrix:
    m = _read_from_db(token)
    if token is None:
        return m  # nothing to key a file on: served from the heap, uncached
    data_path, meta_path = _paths(token)
    cache_dir().mkdir(parents=True, exist_ok=True)
    # temporary name then move, so a crash mid-write cannot leave a truncated
    # matrix that would be mapped as though it were complete
    tmp = data_path.with_suffix(".f32.tmp")
    tmp.write_bytes(np.ascontiguousarray(m.matrix).tobytes())
    tmp.replace(data_path)
    meta_path.write_text(json.dumps({
        "token": token, "tag": embedding_tag(), "ids": m.ids,
        "documents": m.documents, "doc_index": m.doc_index.tolist(),
    }), encoding="utf-8")
    _sweep(_stem(token))
    if not m.ids:
        return m
    try:
        # map what was just written, so the process that just ingested - the
        # one under most memory pressure - also gets the mapping
        return m._replace(matrix=_map(data_path, len(m.ids)))
    except OSError:
        return m  # the heap copy is correct; only the memory saving is lost


def _from_disk(token: int) -> Matrix | None:
    data_path, meta_path = _paths(token)
    if not (data_path.exists() and meta_path.exists()):
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("token") != token or meta.get("tag") != embedding_tag():
        return None
    ids = list(meta["ids"])
    doc_index = np.asarray(meta["doc_index"], dtype=np.int32)
    if len(doc_index) != len(ids) or data_path.stat().st_size != len(ids) * EMBEDDING_DIM * 4:
        return None  # truncated or torn: rebuild, never map a short file
    matrix = (_map(data_path, len(ids)) if ids
              else np.zeros((0, EMBEDDING_DIM), dtype=np.float32))
    return Matrix(ids, doc_index, list(meta["documents"]), matrix, token)


def load() -> Matrix:
    """The corpus matrix, mapped rather than copied; one indexed read to
    validate when nothing has changed."""
    token = generation()
    key = (str(cache_dir()), embedding_tag())
    cached = _live.get(key)
    if cached is not None and token is not None and cached.token == token:
        return cached
    with _lock:
        cached = _live.get(key)
        if cached is not None and token is not None and cached.token == token:
            return cached
        m = None
        if token is not None:
            try:
                m = _from_disk(token)
            except Exception:  # noqa: BLE001 - a bad cache file must never break search
                m = None
        if m is None:
            m = _build(token)
        # the previous Matrix is DROPPED, never closed: a thread still
        # multiplying against it keeps it alive until it finishes (#8)
        _live[key] = m
        return m


def search(query_vec: np.ndarray, limit: int, scope: frozenset[str]) -> list[dict]:
    """Exact cosine, masked by scope BEFORE top-k. `scope` is the final set of
    documents the caller may search (already intersected by the caller)."""
    try:
        m = load()
    except Exception:  # noqa: BLE001 - never let a cache fault break retrieval
        m = _read_from_db()
    if not m.ids or not scope or limit <= 0:
        return []
    allowed = np.fromiter((d in scope for d in m.documents), dtype=bool,
                          count=len(m.documents))
    mask = allowed[m.doc_index]
    n_in = int(mask.sum())
    if n_in == 0:
        return []
    scores = np.asarray(m.matrix @ np.asarray(query_vec, dtype=np.float32))
    # -inf rather than deletion keeps positions aligned with `ids`; an
    # out-of-scope row can never be selected however high it scored
    scores = np.where(mask, scores, -np.inf)
    k = min(limit, n_in)
    top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(len(scores))
    # score descending, then row order: deterministic under ties
    top = top[np.lexsort((top, -scores[top]))]
    return [{"chunk_id": m.ids[i], "cosine": float(scores[i])}
            for i in top if np.isfinite(scores[i])]


def invalidate() -> None:
    """Drop the in-process matrices (tests; a new data_dir). Mappings are
    released by reference, never closed underneath a reader (#8)."""
    with _lock:
        _live.clear()
