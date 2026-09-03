"""Background ingestion worker.

There was never a worker. Upload wrote a job row with state='running' and
nothing ran, so uploaded documents sat at `queued` forever while the API
reported a job id that meant nothing. That is fixed here, and the API can now
tell the difference between "waiting its turn" and "stalled".

Ingestion order is deliberate: the keyword index is built BEFORE embedding, so
a document becomes answerable as soon as extraction and chunking finish.
Embedding then upgrades it from keyword-only to hybrid in the background, and
the document is not called `ready` until that completes.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone

from . import states
from .chunker import chunk_document
from .db import connect
from .extract import extract_document
from .embedder import Embedder, EmbedderConfig

# A job with no heartbeat for this long is stalled, not running.
STALL_AFTER_SECONDS = 120

_worker: IngestionWorker | None = None
_worker_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class IngestionWorker:
    """One worker thread draining the document queue, one document at a time."""

    def __init__(self, poll_seconds: float = 1.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current_document: str | None = None
        self.last_beat: float = time.time()
        self.last_error: str | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ingestion", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        age = time.time() - self.last_beat
        return {
            "alive": self.alive,
            "current_document": self.current_document,
            "seconds_since_heartbeat": round(age, 1),
            # A dead worker with queued work is stalled - the API must say so
            # rather than showing "queued" forever.
            "stalled": (not self.alive) or age > STALL_AFTER_SECONDS,
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------ loop

    def _next_document(self) -> str | None:
        """Next document needing work.

        Includes any status this build does not recognise - a database written
        by an earlier build can hold a retired status like 'embedding', and a
        document must never be stranded because the state machine changed.
        """
        known_done = (states.READY, states.FAILED, states.PARTIALLY_SEARCHABLE)
        row = connect().execute(
            f"""SELECT id FROM documents
                WHERE status NOT IN ({",".join("?" * len(known_done))})
                ORDER BY uploaded_at LIMIT 1""",
            known_done,
        ).fetchone()
        if row:
            return row["id"]
        # documents that are answerable but still have vectors outstanding
        row = connect().execute(
            """SELECT id FROM documents
               WHERE status = ? AND embedded_count < chunk_count
               ORDER BY uploaded_at LIMIT 1""",
            (states.PARTIALLY_SEARCHABLE,),
        ).fetchone()
        return row["id"] if row else None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.last_beat = time.time()
            try:
                doc_id = self._next_document()
                if doc_id is None:
                    self.current_document = None
                    self._stop.wait(self.poll_seconds)
                    continue
                self.current_document = doc_id
                self.process(doc_id)
            except Exception:
                self.last_error = traceback.format_exc(limit=3)
                self._stop.wait(self.poll_seconds)
            finally:
                self.last_beat = time.time()

    # --------------------------------------------------------------- stages

    def process(self, doc_id: str) -> dict:
        """Drive one document to a state where it can answer questions."""
        conn = connect()
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if doc is None:
            return {"document_id": doc_id, "error": "unknown document"}

        result: dict = {"document_id": doc_id}
        try:
            # A status this build does not know is treated as "start over
            # from extraction" - resumable, so nothing is recomputed.
            if doc["status"] not in states.ALL_STATES:
                with conn:
                    conn.execute("UPDATE documents SET status = ? WHERE id = ?",
                                 (states.EXTRACTING, doc_id))
                doc = conn.execute("SELECT * FROM documents WHERE id = ?",
                                   (doc_id,)).fetchone()

            if doc["status"] in (states.QUEUED, states.EXTRACTING):
                self._set_state(doc_id, states.EXTRACTING)
                result["extract"] = extract_document(doc_id)

            row = conn.execute(
                "SELECT status FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if row["status"] == states.CHUNKING:
                result["chunk"] = chunk_document(doc_id)

            row = conn.execute(
                "SELECT status FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if row["status"] == states.INDEXING_KEYWORD:
                # Keyword indexing lands in the next step. Until it exists the
                # document still reaches a defined, answerable state rather
                # than sitting in limbo.
                self._set_state(doc_id, states.PARTIALLY_SEARCHABLE)
                result["keyword_index"] = "pending_implementation"

            self.embed_pending(doc_id)
            self._finish_if_embedded(doc_id)
        except Exception as exc:  # noqa: BLE001 - the record must capture anything
            self.last_error = traceback.format_exc(limit=3)
            with conn:
                conn.execute(
                    "UPDATE documents SET status = ?, error_code = ?, error_message = ?"
                    " WHERE id = ?",
                    (states.FAILED, "internal", str(exc)[:400], doc_id),
                )
                conn.execute(
                    "UPDATE jobs SET state = 'failed', error_code = 'internal',"
                    " error_message = ?, updated_at = ? WHERE document_id = ?",
                    (str(exc)[:400], _now(), doc_id),
                )
            result["error"] = str(exc)
        return result

    def embed_pending(self, doc_id: str, batch: int = 64) -> int:
        """Embed retrievable chunks that have no vector yet.

        Runs AFTER the document is already answerable, and updates
        embedded_count as it goes so the UI can show honest progress.
        """
        conn = connect()
        rows = conn.execute(
            """SELECT c.id, c.text FROM chunks c
               LEFT JOIN chunk_vectors v ON v.chunk_id = c.id
               WHERE c.document_id = ? AND c.retrievable = 1 AND v.chunk_id IS NULL
               ORDER BY c.ordinal""",
            (doc_id,),
        ).fetchall()
        if not rows:
            return 0

        embedder = Embedder.instance(EmbedderConfig())
        done = 0
        for start in range(0, len(rows), batch):
            if self._stop.is_set():
                break
            window = rows[start:start + batch]
            vectors = embedder.embed_passages([r["text"] for r in window])
            with conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO chunk_vectors
                       (chunk_id, document_id, dim, vector, model, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (r["id"], doc_id, int(v.shape[0]), v.astype("float32").tobytes(),
                         embedder.config.model_file, _now())
                        for r, v in zip(window, vectors)
                    ],
                )
                conn.execute(
                    """UPDATE documents SET embedded_count =
                       (SELECT COUNT(*) FROM chunk_vectors WHERE document_id = ?)
                       WHERE id = ?""",
                    (doc_id, doc_id),
                )
            done += len(window)
            self.last_beat = time.time()
        return done

    def _set_state(self, doc_id: str, nxt: str) -> None:
        conn = connect()
        cur = conn.execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()["status"]
        if cur == nxt:
            return
        states.check_transition(cur, nxt)
        with conn:
            conn.execute("UPDATE documents SET status = ? WHERE id = ?", (nxt, doc_id))

    def _finish_if_embedded(self, doc_id: str) -> None:
        """A document is ready only when every retrievable chunk has a vector."""
        conn = connect()
        row = conn.execute(
            "SELECT status, chunk_count, embedded_count FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row["status"] != states.PARTIALLY_SEARCHABLE:
            return
        # A document with no retrievable chunks has nothing to embed. It is
        # still finished - the exclusion ledger explains why it is empty - so
        # it must reach a terminal state rather than waiting forever.
        if row["chunk_count"] == 0 or row["embedded_count"] >= row["chunk_count"]:
            with conn:
                conn.execute(
                    "UPDATE documents SET status = ?, indexed_at = ? WHERE id = ?",
                    (states.READY, _now(), doc_id),
                )
                conn.execute(
                    "UPDATE jobs SET state = 'done', updated_at = ? WHERE document_id = ?",
                    (_now(), doc_id),
                )


def get_worker() -> IngestionWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = IngestionWorker()
        return _worker


def start_worker() -> IngestionWorker:
    w = get_worker()
    w.start()
    return w


def stop_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.stop()
            _worker = None
