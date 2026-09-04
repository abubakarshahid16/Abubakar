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
from datetime import datetime, timezone

from . import errors, states
from .chunker import chunk_document
from .db import connect
from .extract import extract_document
from .embedder import Embedder, EmbedderConfig

# A worker with no heartbeat for this long has died or hung.
STALL_AFTER_SECONDS = 120
# Work is waiting but nothing has completed for this long: the queue is stuck
# even though the worker is alive and looping.
NO_PROGRESS_SECONDS = 180

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
        # Last time a document actually reached a terminal state. Heartbeat
        # freshness only proves the loop is spinning, not that work is moving.
        self.last_progress: float = time.time()
        # Distinct documents that have reached a terminal state since this
        # worker started. Counting transitions instead inflated the number
        # every time a stage was re-run on an already-finished document.
        self._completed: set[str] = set()
        # Response-safe only: code, short message, document id, timestamp.
        # The full traceback goes to the local log, never to the API.
        self.last_error: dict | None = None

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

    @property
    def documents_completed(self) -> int:
        """Distinct documents finished, not stage invocations."""
        return len(self._completed)

    def backlog(self) -> tuple[int, float | None]:
        """How much non-terminal work is waiting, and how old the oldest is."""
        row = connect().execute(
            f"""SELECT COUNT(*) AS n, MIN(uploaded_at) AS oldest FROM documents
                WHERE status NOT IN ({",".join("?" * len(states.TERMINAL_STATES))})
                   OR (status = ? AND (embedded_count < chunk_count
                                       OR indexed_at IS NULL))""",
            (*sorted(states.TERMINAL_STATES), states.PARTIALLY_SEARCHABLE),
        ).fetchone()
        pending = row["n"] or 0
        if not pending or not row["oldest"]:
            return pending, None
        try:
            oldest = datetime.fromisoformat(row["oldest"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - oldest).total_seconds()
        except ValueError:
            return pending, None
        return pending, round(age, 1)

    def status(self) -> dict:
        """Health that reflects whether work is MOVING, not just whether the
        loop is spinning.

        An alive worker ignoring a full queue previously reported
        `stalled: false`. Heartbeat freshness proves only that the thread is
        running; it says nothing about progress. Stalled now means: there is
        work waiting AND nothing has completed for a while.
        """
        now = time.time()
        beat_age = now - self.last_beat
        progress_age = now - self.last_progress
        pending, oldest_age = self.backlog()

        dead = not self.alive
        hung = beat_age > STALL_AFTER_SECONDS
        ignoring_work = pending > 0 and progress_age > NO_PROGRESS_SECONDS

        reasons = []
        if dead:
            reasons.append("worker_not_running")
        if hung:
            reasons.append(f"no_heartbeat_for_{beat_age:.0f}s")
        if ignoring_work:
            reasons.append(f"{pending}_pending_but_no_progress_for_{progress_age:.0f}s")

        return {
            "alive": self.alive,
            "current_document": self.current_document,
            "seconds_since_heartbeat": round(beat_age, 1),
            "seconds_since_progress": round(progress_age, 1),
            "documents_completed": len(self._completed),
            "pending_count": pending,
            "oldest_pending_age_seconds": oldest_age,
            "stalled": dead or hung or ignoring_work,
            "stalled_reasons": reasons,
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------ loop

    def _next_document(self) -> str | None:
        """Next document needing work.

        Includes any status this build does not recognise - a database written
        by an earlier build can hold a retired status like 'embedding', and a
        document must never be stranded because the state machine changed.
        """
        # Derived from states.py, never hand-maintained. A previous version
        # listed (ready, failed, partially_searchable) literally, so when
        # no_searchable_content was added later it was NOT excluded: the
        # worker re-selected such a document forever, held it as
        # current_document, and kept pending_count at 1 - which disabled the
        # stall detector built to catch exactly that.
        settled = tuple(states.TERMINAL_STATES | {states.PARTIALLY_SEARCHABLE})
        row = connect().execute(
            f"""SELECT id FROM documents
                WHERE status NOT IN ({",".join("?" * len(settled))})
                ORDER BY uploaded_at LIMIT 1""",
            settled,
        ).fetchone()
        if row:
            return row["id"]
        # Answerable documents that are not finished: vectors still
        # outstanding, or never stamped terminal at all (a document with zero
        # retrievable chunks has nothing to embed but is still finished).
        row = connect().execute(
            """SELECT id FROM documents
               WHERE status = ?
                 AND (embedded_count < chunk_count OR indexed_at IS NULL)
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
                before = self._is_finished(doc_id)
                self.process(doc_id)
                if not before and self._is_finished(doc_id):
                    self.last_progress = time.time()
                    self._completed.add(doc_id)
            except Exception as exc:  # noqa: BLE001
                self.last_error = errors.record_failure(exc, stage="worker_loop")
                self._stop.wait(self.poll_seconds)
            finally:
                self.last_beat = time.time()

    # --------------------------------------------------------------- stages

    def process(self, doc_id: str) -> dict:
        """Drive one document forward from wherever it currently is.

        Written as a loop over the CURRENT status rather than a fall-through
        chain, so every non-terminal state is resumable. A document abandoned
        mid-pipeline - at chunking, at indexing, part-way through embedding -
        is picked up and finished, not stranded. An earlier version only
        recovered *unrecognised* statuses, which meant a recognised one that
        was interrupted fell straight through and never resumed.
        """
        conn = connect()
        result: dict = {"document_id": doc_id, "stages": []}
        guard = 0

        try:
            while True:
                guard += 1
                if guard > len(states.ALL_STATES) + 2:
                    raise RuntimeError(f"state machine did not settle for {doc_id}")

                row = conn.execute(
                    "SELECT * FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
                if row is None:
                    return {"document_id": doc_id, "error": "unknown document"}
                status = row["status"]

                # A status this build does not know (written by an earlier
                # build) restarts from extraction. Extraction is resumable, so
                # nothing already done is recomputed.
                if status not in states.ALL_STATES:
                    with conn:
                        conn.execute(
                            "UPDATE documents SET status = ? WHERE id = ?",
                            (states.EXTRACTING, doc_id),
                        )
                    result["stages"].append(f"unknown_status:{status}->extracting")
                    continue

                if status in (states.FAILED, states.NO_SEARCHABLE_CONTENT):
                    result["stages"].append(status)
                    return result

                if status == states.QUEUED:
                    self._set_state(doc_id, states.EXTRACTING)
                    continue

                if status == states.EXTRACTING:
                    result["extract"] = extract_document(doc_id)
                    result["stages"].append("extract")
                    continue

                if status == states.CHUNKING:
                    result["chunk"] = chunk_document(doc_id)
                    result["stages"].append("chunk")
                    continue

                if status == states.INDEXING_KEYWORD:
                    # Keyword indexing lands in the next step. Until it exists
                    # the document still reaches a defined answerable state.
                    self._set_state(doc_id, states.PARTIALLY_SEARCHABLE)
                    result["stages"].append("keyword_index:pending_implementation")
                    continue

                if status == states.PARTIALLY_SEARCHABLE:
                    # never trust the stored count as the gate on its own repair
                    embedded = self._recount_embedded(doc_id)
                    if embedded < row["chunk_count"]:
                        result["embedded"] = self.embed_pending(doc_id)
                        result["stages"].append("embed")
                        if self._stop.is_set():
                            return result
                    self._finish_if_embedded(doc_id)
                    after = conn.execute(
                        "SELECT status FROM documents WHERE id = ?", (doc_id,)
                    ).fetchone()["status"]
                    if after == states.PARTIALLY_SEARCHABLE:  # nothing more to do now
                        # nothing further can be done in this pass
                        return result
                    continue

                if status == states.READY:
                    result["stages"].append("ready")
                    return result

        except Exception as exc:  # noqa: BLE001 - the record must capture anything
            self.last_error = errors.record_failure(
                exc, code=errors.INTERNAL, document_id=doc_id, stage="process"
            )
            safe_message = self.last_error["message"]
            with conn:
                conn.execute(
                    "UPDATE documents SET status = ?, error_code = ?, error_message = ?"
                    " WHERE id = ?",
                    (states.FAILED, errors.INTERNAL, safe_message, doc_id),
                )
                conn.execute(
                    "UPDATE jobs SET state = 'failed', error_code = 'internal',"
                    " error_message = ?, updated_at = ? WHERE document_id = ?",
                    (safe_message, _now(), doc_id),
                )
            result["error"] = self.last_error
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
                       (SELECT COUNT(*) FROM chunk_vectors v
                        JOIN chunks c ON c.id = v.chunk_id
                        WHERE v.document_id = ?)
                       WHERE id = ?""",
                    (doc_id, doc_id),
                )
            done += len(window)
            self.last_beat = time.time()
        return done

    def _is_finished(self, doc_id: str) -> bool:
        row = connect().execute(
            "SELECT status, indexed_at FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return True
        if row["status"] in (states.FAILED, states.NO_SEARCHABLE_CONTENT):
            return True
        return row["status"] == states.READY and row["indexed_at"] is not None

    def _no_content_reason(self, doc_id: str) -> str:
        """Why this document produced nothing searchable - stated, not implied."""
        conn = connect()
        doc = conn.execute(
            "SELECT page_count, needs_ocr_pages, chunk_count_total FROM documents"
            " WHERE id = ?", (doc_id,)
        ).fetchone()
        pages = doc["page_count"] or 0
        if pages and doc["needs_ocr_pages"] >= pages:
            return (
                f"all {pages} pages are scanned images with no extractable text; "
                "OCR is not implemented"
            )
        if doc["chunk_count_total"]:
            top = conn.execute(
                """SELECT rule, COUNT(*) n FROM exclusions
                   WHERE document_id = ? GROUP BY rule ORDER BY n DESC LIMIT 1""",
                (doc_id,),
            ).fetchone()
            rule = top["rule"] if top else "unknown"
            return (
                f"all {doc['chunk_count_total']} chunks were excluded from search "
                f"(most common rule: {rule}); see /excluded"
            )
        return "the document produced no chunks at all"

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

    def _recount_embedded(self, doc_id: str) -> int:
        """Recompute embedded_count from the vectors that actually exist.

        The stored value can be stale-high after a re-chunk (vectors orphaned
        by new chunk ids), and because it is itself the gate on whether
        embedding re-runs, a stale-high value permanently blocks its own
        correction. Derive it from the join before trusting it.
        """
        conn = connect()
        actual = conn.execute(
            """SELECT COUNT(*) FROM chunk_vectors v
               JOIN chunks c ON c.id = v.chunk_id
               WHERE v.document_id = ?""",
            (doc_id,),
        ).fetchone()[0]
        with conn:
            conn.execute(
                "UPDATE documents SET embedded_count = ? WHERE id = ?", (actual, doc_id)
            )
        return actual

    def _finish_if_embedded(self, doc_id: str) -> None:
        """A document is ready only when every retrievable chunk has a vector."""
        conn = connect()
        self._recount_embedded(doc_id)
        row = conn.execute(
            "SELECT status, chunk_count, embedded_count FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row["status"] != states.PARTIALLY_SEARCHABLE:
            return
        # A document with no retrievable chunks is finished, but calling it
        # "ready" tells an operator it is usable when it can answer nothing.
        # A fully scanned PDF, or one whose every chunk was excluded, gets its
        # own terminal state and a reason.
        if row["chunk_count"] == 0:
            reason = self._no_content_reason(doc_id)
            with conn:
                conn.execute(
                    "UPDATE documents SET status = ?, indexed_at = ?,"
                    " error_code = ?, error_message = ? WHERE id = ?",
                    (states.NO_SEARCHABLE_CONTENT, _now(),
                     errors.NO_SEARCHABLE_CONTENT, reason, doc_id),
                )
                conn.execute(
                    "UPDATE jobs SET state = 'done', updated_at = ? WHERE document_id = ?",
                    (_now(), doc_id),
                )
            return

        if row["embedded_count"] >= row["chunk_count"]:
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
