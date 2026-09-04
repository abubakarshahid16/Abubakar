"""Memory-mapped cache for the dense-search matrix.

`_load_vectors` used to re-read every stored vector blob out of SQLite on
every single query, join it against `chunks`, concatenate the blobs and
reshape. Measured across a corpus doubling (2,670 -> 4,780 retrievable
chunks):

    vector load    39.1 ms -> 82.6 ms   x2.11
    matmul         48.1 ms -> 50.7 ms   x1.05

It was the ONLY component of retrieval that grew with the corpus. Small today,
dominant at ten documents.

The matrix is written once to a file and mapped with np.memmap, NOT read into
the heap. That choice is about memory, not elegance: this machine demos at 92%
RAM, so a mapped file is pages the OS can evict and share, while a heap array
is pages it cannot.

VALIDITY. Rebuilding when nothing changed would give back the saving, and
serving a stale matrix would be a correctness bug, so the signature has to be
both cheap and sufficient. Measured: 0.19 ms against an 83 ms load.

    vector count + max vector rowid   catches additions, deletions, re-chunks
    excluded count + sum of rowids    catches retrievability changes, including
                                      one chunk excluded as another is restored

The residual risk is two simultaneous retrievability flips whose rowids happen
to sum equal. That cannot surface excluded content: `search()` hydrates every
candidate and drops any row where `retrievable` is false, so a stale matrix can
only cost a little ranking quality, never leak an excluded chunk. Stated here
because a cache whose failure mode is unexamined is worse than no cache.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from .config import settings
from .db import connect
from .embedder import EMBEDDING_DIM

_lock = threading.Lock()
#: document_id (or "" for the whole corpus) -> (signature, ids, mapped matrix)
_live: dict[str, tuple[tuple, list[str], np.ndarray]] = {}


def cache_dir() -> Path:
    return settings.data_dir / "vector_cache"


def _key(document_id: str | None) -> str:
    return document_id or ""


def signature(document_id: str | None = None) -> tuple:
    """Cheap fingerprint of everything the matrix depends on.

    Measured at 1.2 ms against an 83 ms load. Each term earns its place by a
    test that fails without it:

      documents.chunk_signature   a re-chunk that produces the same number of
                                  chunks with different content
      embedded_count              a re-embed of unchanged chunking
      MIN/MAX chunk_id            SQLite REUSES rowids after a full delete, so
                                  deleting every vector and reinserting the
                                  same number gives an identical count AND an
                                  identical max rowid. Found by the re-chunk
                                  test, not by reasoning.
      COUNT + MAX(rowid)          additions, deletions, partial writes
      excluded COUNT + SUM(rowid) retrievability changes, including one chunk
                                  excluded as another is restored
    """
    conn = connect()
    if document_id:
        docs = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(chunk_count), 0),"
            " COALESCE(SUM(embedded_count), 0),"
            " COALESCE(GROUP_CONCAT(chunk_signature), '')"
            " FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        vec = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0), MIN(chunk_id), MAX(chunk_id)"
            " FROM chunk_vectors WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        exc = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(rowid), 0) FROM chunks"
            " WHERE retrievable = 0 AND document_id = ?",
            (document_id,),
        ).fetchone()
    else:
        docs = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(chunk_count), 0),"
            " COALESCE(SUM(embedded_count), 0),"
            " COALESCE(GROUP_CONCAT(chunk_signature), '') FROM documents"
        ).fetchone()
        vec = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0), MIN(chunk_id), MAX(chunk_id)"
            " FROM chunk_vectors"
        ).fetchone()
        exc = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(rowid), 0) FROM chunks WHERE retrievable = 0"
        ).fetchone()
    return tuple(docs) + tuple(vec) + tuple(exc)


def _read_from_db(document_id: str | None) -> tuple[list[str], np.ndarray]:
    conn = connect()
    sql = """SELECT v.chunk_id, v.vector FROM chunk_vectors v
             JOIN chunks c ON c.id = v.chunk_id
             WHERE c.retrievable = 1"""
    params: list[object] = []
    if document_id:
        sql += " AND v.document_id = ?"
        params.append(document_id)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return [], np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    ids = [r["chunk_id"] for r in rows]
    matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32)
    return ids, matrix.reshape(len(ids), EMBEDDING_DIM)


def _paths(key: str) -> tuple[Path, Path]:
    stem = key or "corpus"
    # a document id is a hex digest, so this is already filesystem-safe; the
    # replace is for the corpus-wide case and any future non-hex id
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
    d = cache_dir()
    return d / f"{safe}.f32", d / f"{safe}.json"


def _build(key: str, document_id: str | None) -> tuple[list[str], np.ndarray]:
    ids, matrix = _read_from_db(document_id)
    data_path, meta_path = _paths(key)
    # release any mapping of the file about to be replaced (see _close)
    _close(key)
    cache_dir().mkdir(parents=True, exist_ok=True)
    # written to a temporary name and moved, so a crash mid-write cannot leave
    # a truncated matrix that would be mapped as though it were complete
    tmp = data_path.with_suffix(".f32.tmp")
    tmp.write_bytes(matrix.tobytes(order="C"))
    tmp.replace(data_path)
    meta_path.write_text(
        json.dumps({"signature": list(signature(document_id)), "ids": ids}),
        encoding="utf-8",
    )
    # Map the file we just wrote rather than returning the heap array we built
    # it from. Otherwise the process that performs the build - the one that has
    # just finished ingesting, and is therefore the one under most memory
    # pressure - is the only process that never gets the mapping.
    if not ids:
        return ids, matrix
    try:
        return ids, np.memmap(
            data_path, dtype=np.float32, mode="r", shape=(len(ids), EMBEDDING_DIM)
        )
    except OSError:
        # the matrix we just built is correct either way; only the memory
        # benefit is lost, and losing it must not lose the query
        return ids, matrix


def load(document_id: str | None = None) -> tuple[list[str], np.ndarray]:
    """The vectors for retrievable chunks, mapped rather than copied."""
    key = _key(document_id)
    sig = signature(document_id)

    cached = _live.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1], cached[2]

    with _lock:
        cached = _live.get(key)
        if cached is not None and cached[0] == sig:
            return cached[1], cached[2]

        data_path, meta_path = _paths(key)
        ids: list[str] | None = None
        matrix: np.ndarray | None = None

        if data_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if tuple(meta["signature"]) == sig:
                    ids = list(meta["ids"])
                    expected = len(ids) * EMBEDDING_DIM * 4
                    if data_path.stat().st_size == expected:
                        matrix = (
                            np.memmap(
                                data_path, dtype=np.float32, mode="r",
                                shape=(len(ids), EMBEDDING_DIM),
                            )
                            if ids
                            else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
                        )
            except Exception:  # noqa: BLE001 - a bad cache must never break search
                ids = matrix = None

        if ids is None or matrix is None:
            ids, matrix = _build(key, document_id)

        _live[key] = (sig, ids, matrix)
        return ids, matrix


def _close(key: str) -> None:
    """Release a mapping so the file underneath it can be replaced.

    WINDOWS-SPECIFIC AND LOAD-BEARING. A mapped file cannot be replaced while
    the mapping is open: `Path.replace` fails with WinError 5. On POSIX the
    rebuild would succeed silently, the old inode staying mapped, so this
    defect could only ever appear on the platform this actually ships on.

    Dropping the Python reference is not enough - numpy keeps the underlying
    mmap alive until it is closed explicitly.
    """
    entry = _live.pop(key, None)
    if entry is None:
        return
    mapping = getattr(entry[2], "_mmap", None)
    if mapping is not None:
        try:
            mapping.close()
        except (BufferError, ValueError):
            # still referenced by a caller mid-query; the rebuild will write to
            # a new temporary file and the next process will map the new one
            pass


def invalidate() -> None:
    """Drop the in-process handles, closing any mappings so their files can be
    replaced. The signature check makes calling this optional, but the
    ingestion path and the tests are clearer for being explicit."""
    with _lock:
        for key in list(_live):
            _close(key)
        _live.clear()
