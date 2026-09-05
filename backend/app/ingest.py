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
from . import telemetry
from .db import connect
from . import keyword
from . import ocr
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


def _stuck_reason(conn, doc_id: str, row, status: str) -> str:
    """Say what actually stopped, not that a loop noticed.

    "state machine did not settle" names the mechanism that detected the
    problem and nothing about the problem, which is the same defect the status
    honesty audit catalogues: a message derived from something adjacent to the
    truth. The stage that is stuck, and what it was still waiting for, is what
    an operator needs.
    """
    detail = f"stalled in {status!r} with no further progress"
    try:
        pending = conn.execute(
            """SELECT COUNT(*) c FROM pages p
               LEFT JOIN page_ocr o ON o.document_id = p.document_id
                                   AND o.page_no = p.page_no
               WHERE p.document_id = ? AND p.needs_ocr = 1 AND o.page_no IS NULL""",
            (doc_id,),
        ).fetchone()["c"]
        if pending:
            detail = (f"recognition stalled in {status!r}: {pending} scanned "
                      f"page(s) still unread and no round is making progress")
        elif row["chunk_count"] and row["embedded_count"] < row["chunk_count"]:
            detail = (f"embedding stalled in {status!r}: "
                      f"{row['chunk_count'] - row['embedded_count']} of "
                      f"{row['chunk_count']} chunks still have no vector")
        elif not row["chunk_count_total"]:
            detail = (f"stalled in {status!r}: the document produced no chunks")
    except Exception:  # noqa: BLE001 - a diagnostic must never mask the failure
        pass
    return detail


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
        # CHURN, NOT ITERATIONS. The old guard counted loop passes and allowed
        # about ten, which was right when every document walked the states once
        # and wrong the moment OCR arrived: one recognition round costs three
        # passes (partially_searchable -> chunking -> indexing_keyword -> back),
        # and ocr.round_size doubles each round, so a heavily scanned document
        # legitimately needs far more than ten. A document that was progressing
        # correctly reached `failed` after three rounds, and the recorded reason
        # blamed the state machine without ever naming OCR.
        #
        # The guard still has to catch a real non-settling loop, so the fix is
        # not a bigger number - it is telling PROGRESS from CHURN. A pass that
        # advanced the document's measurable work is progress and costs nothing.
        # A pass that returns to a (status, work) signature already seen has
        # done nothing, and only those count against the budget. A genuine loop
        # repeats a signature immediately and still trips in a few passes.
        seen: set[tuple] = set()
        churn = 0
        churn_budget = len(states.ALL_STATES) + 2

        try:
            while True:
                row = conn.execute(
                    "SELECT * FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
                if row is None:
                    return {"document_id": doc_id, "error": "unknown document"}
                status = row["status"]

                signature = (
                    status,
                    row["pages_done"],
                    row["chunk_count"],
                    row["chunk_count_total"],
                    row["embedded_count"],
                    row["recognised_pages"] if "recognised_pages" in row.keys() else 0,
                )
                if signature in seen:
                    churn += 1
                    if churn > churn_budget:
                        raise RuntimeError(_stuck_reason(conn, doc_id, row, status))
                else:
                    seen.add(signature)

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
                    telemetry.record(
                        telemetry.EXTRACT,
                        result["extract"].get("pages_extracted_this_run", 0),
                        result["extract"].get("seconds", 0.0),
                        doc_id,
                    )
                    result["stages"].append("extract")
                    continue

                if status == states.CHUNKING:
                    result["chunk"] = chunk_document(doc_id)
                    telemetry.record(
                        telemetry.CHUNK,
                        result["chunk"].get("chunks_this_run", 0),
                        result["chunk"].get("seconds", 0.0),
                        doc_id,
                    )
                    result["stages"].append("chunk")
                    continue

                if status == states.INDEXING_KEYWORD:
                    # Keyword search needs no vectors, so it is built FIRST and
                    # the document becomes answerable here - seconds after
                    # upload rather than after the whole corpus is embedded.
                    # The index write and the state advance happen in ONE
                    # transaction: a stage that finishes its work without
                    # advancing the state strands the document, which is how a
                    # fully searchable 1,200-page index sat at
                    # `indexing_keyword` with embedding never starting.
                    result["keyword_index"] = keyword.index_document(
                        doc_id,
                        advance_to=states.PARTIALLY_SEARCHABLE,
                        expect_status=states.INDEXING_KEYWORD,
                    )
                    telemetry.record(
                        telemetry.KEYWORD_INDEX,
                        result["keyword_index"].get("indexed", 0),
                        result["keyword_index"].get("seconds", 0.0),
                        doc_id,
                    )
                    result["stages"].append("keyword_index")
                    continue

                if status == states.PARTIALLY_SEARCHABLE:
                    # OCR runs HERE - after the keyword index, never before it.
                    # A text document must stay answerable in ~13 seconds, so
                    # recognition can never sit in front of the first answer.
                    #
                    # One ROUND per pass, then back through chunking and the
                    # keyword index, so a scanned document becomes
                    # progressively searchable: page 40 answerable while page
                    # 900 is still being read. The round doubles each time
                    # because re-chunking is whole-document - re-indexing after
                    # every batch would cost more than the recognition does.
                    pending = ocr.pending_pages(doc_id)
                    if pending:
                        already = conn.execute(
                            "SELECT COUNT(*) c FROM page_ocr WHERE document_id = ?",
                            (doc_id,),
                        ).fetchone()["c"]
                        result["ocr"] = ocr.recognise_document(
                            doc_id, max_pages=ocr.round_size(already))
                        telemetry.record(
                            telemetry.OCR,
                            result["ocr"].get("pages_recognised", 0),
                            result["ocr"].get("seconds", 0.0),
                            doc_id,
                        )
                        result["stages"].append("ocr")
                        if self._stop.is_set():
                            return result
                        # Recognised text changes the chunk signature, so
                        # chunking rebuilds on its own rather than being told
                        # to. Going back through CHUNKING is what makes the new
                        # pages searchable.
                        if result["ocr"].get("pages_with_text"):
                            self._set_state(doc_id, states.CHUNKING)
                            continue
                        if result["ocr"].get("pages_remaining"):
                            # This round found only blank pages. They are
                            # consumed either way, so the next round makes
                            # progress - but falling through here would embed
                            # and mark the document ready with scanned pages
                            # still unread.
                            continue

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
        # Timed per batch, not per call: a call that embeds 1400 chunks over
        # several minutes while the laptop throttles is one useless average,
        # where per-batch samples give a median that survives a throttle.
        batch_timer = time.time()
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
            now = time.time()
            telemetry.record(
                telemetry.EMBED, len(window), now - batch_timer, doc_id
            )
            batch_timer = now
            self.last_beat = now
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
            "SELECT page_count, needs_ocr_pages, recognised_pages,"
            " chunk_count_total FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        pages = doc["page_count"] or 0
        if pages and doc["needs_ocr_pages"] >= pages:
            # "OCR is not implemented" was true when this string was written
            # and is now false. The reason must distinguish recognition having
            # not run from recognition having run and found nothing - those are
            # different facts and an operator needs to know which one they
            # have. See ADR-0006.
            unread = conn.execute(
                "SELECT COUNT(*) c FROM page_ocr WHERE document_id = ?", (doc_id,)
            ).fetchone()["c"]
            if unread == 0:
                return (
                    f"all {pages} pages are scanned images with no extractable "
                    "text; recognition has not run on them yet"
                )
            return (
                f"all {pages} pages are scanned images; recognition ran on "
                f"{unread} of them and found no usable text"
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
                    " error_code = ?, error_message = ? WHERE id = ? AND status = ?",
                    (states.NO_SEARCHABLE_CONTENT, _now(),
                     errors.NO_SEARCHABLE_CONTENT, reason, doc_id,
                     states.PARTIALLY_SEARCHABLE),
                )
                conn.execute(
                    "UPDATE jobs SET state = 'done', updated_at = ? WHERE document_id = ?",
                    (_now(), doc_id),
                )
            return

        if row["embedded_count"] >= row["chunk_count"]:
            with conn:
                # Recount and advance in ONE transaction, guarded by the status
                # we expect, so the terminal stamp can never be applied on the
                # strength of a count that changed underneath it.
                conn.execute(
                    """UPDATE documents SET
                         embedded_count = (SELECT COUNT(*) FROM chunk_vectors v
                                           JOIN chunks c ON c.id = v.chunk_id
                                           WHERE v.document_id = ?),
                         status = ?, indexed_at = ?
                       WHERE id = ? AND status = ?""",
                    (doc_id, states.READY, _now(), doc_id, states.PARTIALLY_SEARCHABLE),
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
