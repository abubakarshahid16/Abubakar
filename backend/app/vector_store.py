"""The dense-search vector store: ONE interface, two EXACT backends.

`search.dense_search` calls `vector_store.search` and nothing else.

    sqlite_vec  sqlite-vec's `vec0` virtual table (Apache-2.0/MIT, in-process,
                no server, no socket). The default whenever the extension
                loads. Exact KNN, cosine - no approximate index, no recall loss.
    numpy       `vectorcache.py`: one memory-mapped matrix, exact cosine. The
                automatic fallback when the extension cannot load, or chosen
                with VECTOR_BACKEND=numpy.

Both rank identically (same vectors, same cosine, float32; scores agree to
~1e-7) - the parity test holds them to it. A fallback is LOGGED ONCE and
reported on System Health (`status()`, in /api/metrics) - never silent.

SOURCE OF TRUTH. `chunk_vectors` in the main database stays the source of
truth; the vec0 table is a DERIVED index, rebuilt from it idempotently and
never embedding anything. It lives in its OWN file, `data/vector_index.sqlite`,
NOT inside rag_intelligence.sqlite, and that is deliberate (verified with
sqlite-vec 0.1.9): a `vec0` table in the live database is unreadable to any
connection that has not loaded the extension - `SELECT COUNT(*)` on it raises
"no such module: vec0", and it cannot even be DROPPED without the extension.
`live_guard._counts`, `backup_db.verify` and the admin table explorer all count
every table with a plain `sqlite3.connect`, so the vec0 table would have made
every verified backup, every restore drill and therefore every
`prepare_live_write` fail - and on a machine where the extension does not load
the database could not have been cleaned up. The index file needs no backup:
it is rebuilt from `chunk_vectors` (which IS backed up) in about a second per
25k vectors, by `sync()`, at startup and whenever a query finds it behind.

WHEN IT IS BEHIND. Triggers in the main database replace a random token per
document on every write that can change what dense search may return (db.py,
`vector_generation`). A query reads ONE token (the corpus-wide one); only when
it differs from the token the index was synced at does `sync()` run, and then
only for the documents whose token changed: their rows are deleted and
re-inserted from `chunk_vectors`. Nothing per query scans `chunks`.

ACCESS SCOPE (CLAUDE.md rule 5) is applied INSIDE the KNN, before top-k, on
every path, and each returned row's document is checked again on the way out:

  * scope = every indexed document   KNN over everything, k = limit
  * scope wide (in-scope rows >=     KNN over everything with k = limit + every
    out-of-scope rows)               out-of-scope row, then drop those rows.
                                     EXACT: at most that many rows can outrank
                                     the in-scope limit-th, so the in-scope
                                     top-`limit` is always inside the window.
  * scope narrow                     `document_id` is the vec0 PARTITION KEY,
                                     so `document_id IN (...)` scans only the
                                     granted documents; sqlite-vec returns the
                                     top k of EACH partition and the union is
                                     merged - exact, and sub-millisecond for a
                                     user granted a handful of documents.

MODEL-VERSION TAGGING (P2-11). A vector is indexed only when its
`chunk_vectors.model` is one of `searchable_tags()` (today's tag, or a legacy
input format of the same model); the rest are STALE, counted
per document in the index and on System Health, and re-embedded by
`IngestionWorker.embed_pending`. A change of tag rebuilds the index.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import states, vectorcache
from .config import settings
from .db import connect
from .embedder import EMBEDDING_DIM, embedding_tag, searchable_tags

log = logging.getLogger("uvicorn.error")

BACKENDS = ("auto", "sqlite_vec", "numpy")
#: Bumped when the index layout changes; a mismatch rebuilds the index file.
INDEX_FORMAT = "1"
TABLE = "chunk_vec"
#: vec0 preallocates a chunk of this many rows PER PARTITION (per document).
#: 1024 (the default) would reserve 1.5 MB for a 10-chunk document; 64 keeps
#: the file within ~1.4x the raw vectors on a real document-size spread.
CHUNK_SIZE = 64
#: sqlite-vec's ceiling on k (verified: 4097 is refused).
KNN_MAX = 4096

_lock = threading.RLock()
_local = threading.local()
#: memo of the extension probe: (ok, reason, version)
_probe: tuple[bool, str | None, str | None] | None = None
#: index path + embedding tag -> corpus token it was last synced at
_synced: dict[str, int | None] = {}
#: reasons already logged, so a fallback is said once, not per query
_logged: set[str] = set()
#: the last runtime failure of the sqlite_vec backend, surfaced in status()
_last_error: str | None = None


# ---------------------------------------------------------------- backend


def _load_extension(conn: sqlite3.Connection) -> None:
    """THE one place the extension is loaded. Loading is switched back off at
    once, so no later SQL on this connection can load anything else."""
    import sqlite_vec

    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def _extension() -> tuple[bool, str | None, str | None]:
    global _probe
    if _probe is None:
        try:
            probe = sqlite3.connect(":memory:")
            try:
                _load_extension(probe)
                version = probe.execute("SELECT vec_version()").fetchone()[0]
            finally:
                probe.close()
            _probe = (True, None, version)
        except ImportError:
            _probe = (False, "the sqlite-vec package is not installed", None)
        except AttributeError:
            _probe = (False, "this Python's sqlite3 cannot load extensions", None)
        except sqlite3.Error as exc:
            _probe = (False, f"the sqlite-vec extension failed to load: {exc}", None)
    return _probe


def _say_once(reason: str) -> None:
    if reason not in _logged:
        _logged.add(reason)
        log.warning("dense search: exact numpy backend in use - %s", reason)


def backend() -> tuple[str, str | None]:
    """(active backend, why it is not sqlite_vec - None when it is)."""
    requested = settings.vector_backend
    if requested == "numpy":
        return "numpy", "VECTOR_BACKEND=numpy"
    ok, why, _ = _extension()
    if requested not in BACKENDS:
        why = (f"VECTOR_BACKEND={requested!r} is not one of {', '.join(BACKENDS)}"
               + ("" if ok else f"; and {why}"))
        _say_once(why)
        return ("sqlite_vec" if ok else "numpy"), (why if not ok else None)
    if ok:
        return "sqlite_vec", None
    _say_once(why or "unknown")
    return "numpy", why


# ------------------------------------------------------------------ index


def index_path() -> Path:
    return settings.data_dir / "vector_index.sqlite"


def _index_conn() -> sqlite3.Connection:
    """This thread's connection to the index file, extension loaded."""
    path = index_path()
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == path:
        return conn
    if conn is not None:
        conn.close()
        _local.conn = None
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    _load_extension(conn)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    _local.conn, _local.path = conn, path
    return conn


def _wanted_meta() -> dict[str, str]:
    return {"format": INDEX_FORMAT, "embedding_tag": embedding_tag(),
            "dim": str(EMBEDDING_DIM), "source_db": str(Path(settings.db_path).resolve())}


def _ensure_schema(idx: sqlite3.Connection) -> None:
    idx.execute("CREATE TABLE IF NOT EXISTS index_meta"
                " (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    idx.execute("CREATE TABLE IF NOT EXISTS index_docs (document_id TEXT PRIMARY KEY,"
                " token INTEGER, vectors INTEGER NOT NULL, stale INTEGER NOT NULL)")
    # which chunk ids each document has in the vec0 table. vec0 answers a
    # non-KNN `WHERE document_id = ?` by scanning EVERY vector (measured: ~300
    # ms at 25k), so a document's rows are found here and deleted by primary
    # key instead (~2 ms per 100)
    idx.execute("CREATE TABLE IF NOT EXISTS index_rows (chunk_id TEXT PRIMARY KEY,"
                " document_id TEXT NOT NULL)")
    idx.execute("CREATE INDEX IF NOT EXISTS idx_index_rows_document"
                " ON index_rows(document_id)")
    want = _wanted_meta()
    have = dict(idx.execute("SELECT key, value FROM index_meta WHERE key != 'corpus_token'"))
    if have != want:
        # another model tag, layout or database: nothing in the file is
        # trusted - rebuild from chunk_vectors
        with idx:
            idx.execute(f"DROP TABLE IF EXISTS {TABLE}")
            idx.execute("DELETE FROM index_docs")
            idx.execute("DELETE FROM index_rows")
            idx.execute("DELETE FROM index_meta")
            idx.executemany("INSERT INTO index_meta (key, value) VALUES (?, ?)",
                            list(want.items()))
    idx.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING vec0("
        " chunk_id TEXT PRIMARY KEY,"
        f" embedding float[{EMBEDDING_DIM}] distance_metric=cosine,"
        " document_id TEXT PARTITION KEY,"
        f" chunk_size={CHUNK_SIZE})")
    idx.commit()


def _remove(idx: sqlite3.Connection, document_id: str, incoming: list[str]) -> None:
    """Delete a document's rows, and any row under an id about to be
    inserted (a chunk id is unique across the index), by primary key."""
    ids = {r[0] for r in idx.execute(
        "SELECT chunk_id FROM index_rows WHERE document_id = ?", (document_id,))}
    for at in range(0, len(incoming), 500):   # under SQLite's variable limit
        batch = incoming[at:at + 500]
        ids |= {r[0] for r in idx.execute(
            "SELECT chunk_id FROM index_rows WHERE chunk_id IN"
            f" ({','.join('?' * len(batch))})", batch)}
    idx.executemany(f"DELETE FROM {TABLE} WHERE chunk_id = ?", [(i,) for i in ids])
    idx.executemany("DELETE FROM index_rows WHERE chunk_id = ?", [(i,) for i in ids])


def sync() -> dict:
    """Bring the vec0 index level with `chunk_vectors`. Idempotent: the first
    run is the backfill (no re-embedding - it copies stored vectors); later
    runs touch only documents whose generation token changed."""
    main = connect()
    corpus_token = vectorcache.generation(main)
    key = _memo_key()
    with _lock:
        idx = _index_conn()
        _ensure_schema(idx)
        # tokens BEFORE rows: a write landing between the two leaves an older
        # token beside newer rows, which only costs one more sync, never a
        # stale index
        want = {r[0]: r[1] for r in main.execute(
            "SELECT document_id, token FROM vector_generation WHERE document_id != ''")}
        have = {r[0]: r[1] for r in idx.execute("SELECT document_id, token FROM index_docs")}
        dropped = [d for d in have if d not in want]
        todo = [d for d, t in want.items() if have.get(d) != t]
        tags = set(searchable_tags())
        with idx:
            for d in dropped:
                _remove(idx, d, [])
                idx.execute("DELETE FROM index_docs WHERE document_id = ?", (d,))
            for d in todo:
                rows = main.execute(
                    """SELECT v.chunk_id, v.vector, v.model FROM chunk_vectors v
                       JOIN chunks c ON c.id = v.chunk_id AND c.document_id = v.document_id
                       WHERE v.document_id = ? AND c.retrievable = 1""", (d,)).fetchall()
                fresh = [(r[0], r[1], d) for r in rows
                         if r[2] in tags and r[1] is not None
                         and len(r[1]) == EMBEDDING_DIM * 4]
                _remove(idx, d, [f[0] for f in fresh])
                idx.executemany(
                    f"INSERT INTO {TABLE} (chunk_id, embedding, document_id) VALUES (?, ?, ?)",
                    fresh)
                idx.executemany(
                    "INSERT INTO index_rows (chunk_id, document_id) VALUES (?, ?)",
                    [(f[0], d) for f in fresh])
                idx.execute(
                    "INSERT INTO index_docs (document_id, token, vectors, stale)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT(document_id) DO UPDATE SET"
                    " token = excluded.token, vectors = excluded.vectors,"
                    " stale = excluded.stale",
                    (d, want[d], len(fresh), len(rows) - len(fresh)))
            idx.execute("INSERT INTO index_meta (key, value) VALUES ('corpus_token', ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (json.dumps(corpus_token),))
        # a database with no token table cannot say when it changed: the memo
        # stays None and every query re-syncs rather than trusting the index
        _synced[key] = corpus_token
        vectors = idx.execute("SELECT COALESCE(SUM(vectors), 0) FROM index_docs").fetchone()[0]
        return {"documents_synced": len(todo), "documents_dropped": len(dropped),
                "vectors": int(vectors)}


def _memo_key() -> str:
    # the tag is part of the key: a vector is only current for one tag, and
    # an index synced under another one must be rebuilt, not trusted
    return f"{index_path()}|{embedding_tag()}"


def _ensure_synced() -> None:
    token = vectorcache.generation()
    if token is None or _synced.get(_memo_key()) != token:
        sync()


def _sqlite_vec_search(embed_query: Callable[[], np.ndarray], limit: int,
                       scope: frozenset[str]) -> list[dict]:
    _ensure_synced()
    idx = _index_conn()
    # ONE READ SNAPSHOT for the per-document counts and the KNN, so a sync
    # committing between the two cannot make the counts disagree with the
    # rows (the counts decide k, and a k too small would lose in-scope hits)
    idx.execute("BEGIN")
    try:
        documents = {r[0]: r[1] for r in idx.execute(
            "SELECT document_id, vectors FROM index_docs WHERE vectors > 0")}
        in_scope = [d for d in documents if d in scope]
        if not in_scope:
            return []
        n_in = sum(documents[d] for d in in_scope)
        n_out = sum(documents.values()) - n_in
        k = min(limit, n_in, KNN_MAX)
        q = np.ascontiguousarray(embed_query(), dtype=np.float32).tobytes()
        base = (f"SELECT chunk_id, document_id, distance FROM {TABLE}"
                " WHERE embedding MATCH ? AND k = ?")
        if n_out == 0:
            rows = idx.execute(base, (q, k)).fetchall()
        elif n_out <= n_in and k + n_out <= KNN_MAX:
            rows = idx.execute(base, (q, k + n_out)).fetchall()
        else:
            rows = idx.execute(
                base + " AND document_id IN (SELECT value FROM json_each(?))",
                (q, k, json.dumps(sorted(in_scope)))).fetchall()
    finally:
        idx.rollback()
    # the scope check on the way out: the post-filter of the wide path, and a
    # second line on every other path - a row outside the grant never leaves
    ranked = sorted((r for r in rows if r[1] in scope), key=lambda r: (r[2], r[0]))
    return [{"chunk_id": r[0], "cosine": 1.0 - float(r[2])} for r in ranked[:k]]


# -------------------------------------------------------------- interface


def search(embed_query: Callable[[], np.ndarray], *, limit: int,
           allowed_document_ids: frozenset[str],
           document_id: str | None = None) -> list[dict]:
    """Exact top-`limit` chunks by cosine, within the caller's scope.

    `embed_query` is called only when there is something in scope to search,
    so an empty scope or an unembedded corpus never loads the model.
    Returns `[{"chunk_id", "cosine"}]`, best first.
    """
    global _last_error
    # a document that stopped without being answerable is not searched
    # (states.NOT_SEARCHABLE_STATES) - narrowing only, like the access scope
    scope = states.searchable_scope(frozenset(allowed_document_ids))
    if document_id is not None:
        scope = scope & {document_id}   # a filter only ever NARROWS (rule 5)
    if not scope or limit <= 0:
        return []
    memo: list[np.ndarray] = []

    def once() -> np.ndarray:
        # a fallback after a failed index query must not embed twice
        if not memo:
            memo.append(embed_query())
        return memo[0]

    active, _ = backend()
    if active == "sqlite_vec":
        try:
            return _sqlite_vec_search(once, limit, scope)
        except (sqlite3.Error, OSError) as exc:
            # the index failed at run time (a corrupt or locked file): answer
            # exactly from the numpy path, and SAY so, once and on status
            _last_error = f"{type(exc).__name__}: {exc}"
            _say_once(f"the sqlite-vec index failed ({_last_error})")
    m = vectorcache.load()
    if not m.ids or not any(d in scope for d in m.documents):
        return []
    return vectorcache.search(once(), limit, scope)


def startup() -> dict:
    """At boot: say which backend is active, and backfill/sync the index so
    the first question does not pay for it. Never raises."""
    active, why = backend()
    out: dict = {"active": active, "reason": why}
    if active == "sqlite_vec":
        try:
            out |= sync()
            log.info("dense search: sqlite-vec %s, exact, %s vectors indexed",
                     _extension()[2], out.get("vectors"))
        except Exception as exc:  # noqa: BLE001 - a failed index must not stop boot
            global _last_error
            _last_error = f"{type(exc).__name__}: {exc}"
            _say_once(f"the sqlite-vec index could not be built ({_last_error})")
            out["error"] = _last_error
    return out


def status(include_counts: bool = False) -> dict:
    """What System Health shows. Counts are corpus-wide, so the caller asks
    for them only for an admin (the same gate as `metrics.system`)."""
    active, why = backend()
    ok, _, version = _extension()
    out: dict = {
        "requested": settings.vector_backend,
        "active": active,
        "fallback_reason": why,
        "sqlite_vec_version": version if ok else None,
        "exact": True,
        "embedding_tag": embedding_tag(),
        "last_error": _last_error,
        "current_vectors": None,
        "stale_vectors": None,
    }
    if include_counts:
        tags = searchable_tags()
        row = connect().execute(
            f"""SELECT COUNT(*), COALESCE(SUM(v.model IN ({",".join("?" * len(tags))})), 0)
               FROM chunk_vectors v
               JOIN chunks c ON c.id = v.chunk_id AND c.document_id = v.document_id
               WHERE c.retrievable = 1""", tags).fetchone()
        out["current_vectors"] = int(row[1])
        out["stale_vectors"] = int(row[0]) - int(row[1])
    return out


def reset() -> None:
    """Forget every memo (tests, and a changed data_dir). The extension probe
    is re-run on next use."""
    global _probe, _last_error
    with _lock:
        _probe = None
        _last_error = None
        _synced.clear()
        _logged.clear()
        conn = getattr(_local, "conn", None)
        if conn is not None:
            conn.close()
        _local.conn = None
        _local.path = None
    vectorcache.invalidate()
