"""Worker resume and honest health reporting.

Two bugs this file exists to prevent:

BUG 1 - a document abandoned mid-pipeline at a RECOGNISED status fell straight
        through the resume logic, because only *unrecognised* statuses were
        recovered.
BUG 2 - `stalled` was decided by heartbeat freshness alone, so a worker that
        was alive, looping, and ignoring a full queue reported perfectly
        healthy. Health must reflect whether work is MOVING.
"""
import time

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, states
from app.config import settings
from app.ingest import NO_PROGRESS_SECONDS, IngestionWorker
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


_BODY = [
    "The vibration limit shall not exceed three point zero millimetres per",
    "second measured at the bearing housing during normal operation, and any",
    "reading above that value shall be reported to the area engineer before",
    "the pump is returned to service under the maintenance procedure.",
]


def upload(client, name="s.pdf", pages=2) -> str:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / name
    doc = fitz.open()
    for i in range(pages):
        p = doc.new_page()
        p.insert_text((72, 100), f"Section {i+1}.0 Scope")
        for n, line in enumerate(_BODY):
            p.insert_text((72, 130 + n * 14), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={"file": (name, fh, "application/pdf")})
    return r.json()["document"]["id"]


# ------------------------------------------------------------------- BUG 1


@pytest.mark.parametrize(
    "abandoned_status",
    [states.QUEUED, states.EXTRACTING, states.CHUNKING, states.INDEXING_KEYWORD],
)
def test_every_non_terminal_status_resumes_to_terminal(abandoned_status):
    """A document abandoned at ANY recognised non-terminal status must finish."""
    client = TestClient(app)
    doc_id = upload(client)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", (abandoned_status, doc_id))

    IngestionWorker().process(doc_id)

    row = conn.execute(
        "SELECT status, indexed_at FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert states.is_terminal(row["status"]), (
        f"abandoned at {abandoned_status!r} -> stuck at {row['status']!r}"
    )
    if row["status"] == states.READY:
        assert row["indexed_at"] is not None


def test_a_partially_embedded_document_resumes_embedding():
    """Interrupted part-way through embedding, it must pick up where it left off."""
    client = TestClient(app)
    doc_id = upload(client)
    w = IngestionWorker()
    w.process(doc_id)

    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM chunk_vectors WHERE document_id = ?", (doc_id,))
        conn.execute(
            "UPDATE documents SET embedded_count = 0, indexed_at = NULL, status = ?"
            " WHERE id = ?",
            (states.PARTIALLY_SEARCHABLE, doc_id),
        )

    w.process(doc_id)
    row = conn.execute(
        "SELECT status, chunk_count, embedded_count, indexed_at FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    assert row["embedded_count"] == row["chunk_count"]
    assert row["status"] == states.READY
    assert row["indexed_at"] is not None


def test_the_queue_is_polled_not_only_read_at_startup():
    """Work uploaded after the worker started must still be picked up."""
    client = TestClient(app)
    w = IngestionWorker()
    assert w._next_document() is None          # empty queue
    doc_id = upload(client)                    # arrives afterwards
    assert w._next_document() == doc_id


# ------------------------------------------------------------------- BUG 2


def test_health_reports_a_backlog_rather_than_hiding_it():
    client = TestClient(app)
    w = IngestionWorker()
    assert w.status()["pending_count"] == 0

    upload(client, "a.pdf")
    upload(client, "b.pdf", pages=3)

    s = w.status()
    assert s["pending_count"] == 2, "a waiting queue must be visible in health"
    assert s["oldest_pending_age_seconds"] is not None


def test_an_alive_worker_ignoring_a_full_queue_reports_stalled():
    """The exact defect: alive, looping, doing nothing, reporting healthy."""
    client = TestClient(app)
    upload(client)

    w = IngestionWorker()
    # Simulate the worker being alive and heartbeating but making no progress.
    w._thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    w.last_beat = time.time()
    w.last_progress = time.time() - (NO_PROGRESS_SECONDS + 10)

    s = w.status()
    assert s["alive"] is True
    assert s["seconds_since_heartbeat"] < 5      # heartbeat looks perfectly fine
    assert s["pending_count"] >= 1
    assert s["stalled"] is True, "alive + backlog + no progress must be stalled"
    assert any("no_progress" in r for r in s["stalled_reasons"])


def test_a_fresh_worker_with_no_work_is_not_stalled():
    w = IngestionWorker()
    w._thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    w.last_beat = time.time()
    w.last_progress = time.time() - (NO_PROGRESS_SECONDS + 10)
    s = w.status()
    assert s["pending_count"] == 0
    assert s["stalled"] is False, "idle with an empty queue is healthy, not stalled"


def test_a_dead_worker_is_stalled():
    w = IngestionWorker()
    s = w.status()
    assert s["alive"] is False
    assert s["stalled"] is True
    assert "worker_not_running" in s["stalled_reasons"]


# ------------------------------------------------------------- P2-2 delete


def test_delete_requires_confirmation():
    client = TestClient(app)
    doc_id = upload(client)
    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 400
    assert client.get(f"/api/documents/{doc_id}").status_code == 200


def test_delete_removes_the_document_and_everything_derived_from_it():
    client = TestClient(app)
    doc_id = upload(client)
    IngestionWorker().process(doc_id)
    client.get(f"/api/documents/{doc_id}/pages/1/image")     # populate the image cache

    conn = db.connect()
    before = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE document_id = ?", (doc_id,)).fetchone()[0]
        for t in ("chunks", "pages", "chunk_vectors", "jobs")
    }
    assert before["chunks"] > 0 and before["chunk_vectors"] > 0

    r = client.delete(f"/api/documents/{doc_id}?confirm=true")
    assert r.status_code == 200
    assert r.json()["files_removed"] >= 1

    for t in ("chunks", "pages", "chunk_vectors", "jobs", "exclusions"):
        n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE document_id = ?", (doc_id,)).fetchone()[0]
        assert n == 0, f"{t} still has {n} rows"
    assert client.get(f"/api/documents/{doc_id}").status_code == 404


def test_delete_404s_on_unknown_id():
    client = TestClient(app)
    assert client.delete("/api/documents/doc_zzzzzzzzzzzz?confirm=true").status_code == 404


def test_chunk_short_circuit_still_advances_the_state():
    """The P1-7 short-circuit returned early without moving the document on,
    so the state loop revisited 'chunking' until its guard tripped and the
    document was marked failed."""
    from app.chunker import chunk_document

    client = TestClient(app)
    doc_id = upload(client)
    w = IngestionWorker()
    w.process(doc_id)                     # first pass: extract + chunk + embed

    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, indexed_at = NULL WHERE id = ?",
            (states.CHUNKING, doc_id),
        )

    # chunking is a no-op because nothing changed - but the state must move
    result = chunk_document(doc_id)
    assert result["skipped"] is True
    status = conn.execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()["status"]
    assert status == states.INDEXING_KEYWORD, f"stuck at {status!r} after a skipped chunk"


def test_a_document_reset_to_queued_after_completion_reaches_ready_again():
    """Re-running a finished document must converge, not exhaust the guard."""
    client = TestClient(app)
    doc_id = upload(client)
    w = IngestionWorker()
    w.process(doc_id)

    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, indexed_at = NULL WHERE id = ?",
            (states.QUEUED, doc_id),
        )

    result = w.process(doc_id)
    assert "error" not in result, result.get("error")
    row = conn.execute(
        "SELECT status, indexed_at FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["status"] == states.READY
    assert row["indexed_at"] is not None


# ------------------------------------------- live worker, no restart allowed

def _wait_until(predicate, timeout=90.0, interval=0.25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.mark.parametrize(
    "injected_status",
    [states.QUEUED, states.EXTRACTING, states.CHUNKING, states.INDEXING_KEYWORD],
)
def test_a_running_worker_picks_up_work_without_a_restart(injected_status):
    """The question this answers: does the queue drain because the worker
    POLLS, or only because the process restarted?

    A worker thread is started FIRST and left running. A document is then
    moved to a non-terminal status behind its back. It must reach a terminal
    state on its own - no restart, no notification, no manual nudge.
    """
    client = TestClient(app)
    doc_id = upload(client)

    worker = IngestionWorker(poll_seconds=0.2)
    worker.start()
    try:
        assert worker.alive
        # let it settle the document once, so the injection below is a genuine
        # mid-flight regression rather than first-time processing
        assert _wait_until(
            lambda: db.connect().execute(
                "SELECT status FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()["status"] in (states.READY, states.FAILED)
        ), "worker never processed the document at all"

        conn = db.connect()
        with conn:
            conn.execute(
                "UPDATE documents SET status = ?, indexed_at = NULL WHERE id = ?",
                (injected_status, doc_id),
            )

        reached = _wait_until(
            lambda: db.connect().execute(
                "SELECT status FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()["status"] in (states.READY, states.FAILED)
        )
        row = db.connect().execute(
            "SELECT status, indexed_at FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        assert reached, (
            f"injected at {injected_status!r} and the RUNNING worker never picked it up "
            f"- still {row['status']!r}. The queue only drains on restart."
        )
        assert row["status"] == states.READY, f"ended {row['status']!r}: not recovered cleanly"
        assert row["indexed_at"] is not None
    finally:
        worker.stop()


def test_a_running_worker_picks_up_a_document_uploaded_after_it_started():
    """The demo scenario: the worker is idle, a client uploads, nobody restarts
    anything."""
    client = TestClient(app)
    worker = IngestionWorker(poll_seconds=0.2)
    worker.start()
    try:
        assert _wait_until(lambda: worker.status()["pending_count"] == 0, timeout=15)
        doc_id = upload(client, "arrives-later.pdf")     # uploaded while idle
        reached = _wait_until(
            lambda: db.connect().execute(
                "SELECT status FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()["status"] in (states.READY, states.FAILED)
        )
        row = db.connect().execute(
            "SELECT status, indexed_at FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        assert reached, "a document uploaded while the worker was idle was never picked up"
        assert row["status"] == states.READY and row["indexed_at"] is not None
    finally:
        worker.stop()
