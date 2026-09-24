"""Issue #177 gaps 2-4: retry with backoff, poison, priority, provenance.

Every test here drives the real entry points - `standards.enqueue_extraction`
/ `next_extraction_job` / `run_extraction_job`, `IngestionWorker.
_next_document` / `process`, `upload.ingest`, `watcher.scan_once`,
`datasheets.extract_facts`, `standards.extract_requirements` - rather than
writing the new columns by hand, because a test that inserts its fixture
with SQL cannot see a defect in the code that normally does the inserting
(status-honesty-audit entry 43).
"""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import (datasheets, db, ingest, job_queue, keyword, metrics,
                 standards, states, submittal_review, upload)
from app import watcher as watcher_mod
from app.config import settings
from app.db import connect
from app.ingest import IngestionWorker


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "q.sqlite")
    monkeypatch.setattr(settings, "watch_folder", "")
    monkeypatch.setattr(settings, "watch_owner_email", "")
    monkeypatch.setattr(settings, "job_max_retries", 2)
    monkeypatch.setattr(settings, "job_retry_base_seconds", 60.0)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    keyword.ensure_schema()
    watcher_mod.reset_watcher()
    yield
    watcher_mod.reset_watcher()
    db.reset_connection()


def _iso(delta_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
            ).isoformat(timespec="seconds").replace("+00:00", "Z")


def _doc(doc_id: str, *, status: str = "ready", uploaded_at: str = "2026-09-24T00:00:00Z",
         role: str | None = standards.COMPANY_STANDARD) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status,
                page_count, uploaded_at)
               VALUES (?,?,?,?,?,?,1,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", 1, f"{doc_id}.pdf",
             status, uploaded_at))
        if role:
            conn.execute(
                """INSERT INTO document_classification
                   (document_id, suggested_by, document_role, discipline,
                    document_number) VALUES (?, 'test', ?, 'Mechanical', ?)""",
                (doc_id, role, f"NUM-{doc_id}"))


def _job(doc_id: str, stage: str = standards.EXTRACTION_STAGE) -> sqlite3.Row:
    return connect().execute(
        "SELECT * FROM jobs WHERE document_id = ? AND stage = ?"
        " ORDER BY rowid DESC LIMIT 1", (doc_id, stage)).fetchone()


def _make_due(doc_id: str) -> None:
    """Move a scheduled retry's time into the past - the clock, not the rule."""
    with connect() as conn:
        conn.execute("UPDATE jobs SET next_attempt_at = ? WHERE document_id = ?"
                     " AND state = 'retrying'", (_iso(-1), doc_id))


@pytest.fixture
def flaky_extraction(monkeypatch):
    """An extractor that fails `fail_times` times, then succeeds."""
    state = {"fail_times": 0, "calls": 0}

    def fake_requirements(document_id, *, allowed_document_ids):
        state["calls"] += 1
        if state["calls"] <= state["fail_times"]:
            raise RuntimeError(f"transient failure number {state['calls']}")
        return {"requirements": 3}

    monkeypatch.setattr(standards, "extract_requirements", fake_requirements)
    monkeypatch.setattr(standards, "extract_table_values",
                        lambda document_id, *, allowed_document_ids: {"values": 0})
    return state


def _attempt(doc_id: str) -> dict | None:
    got = standards.next_extraction_job(worker_id="w")
    if got is None:
        return None
    assert got == doc_id
    return standards.run_extraction_job(got, worker_id="w")


# ----------------------------------------------------------- retry: extraction

def test_a_failed_extraction_is_retried_after_a_backoff_then_succeeds(flaky_extraction):
    flaky_extraction["fail_times"] = 1
    _doc("doc_flaky")
    standards.enqueue_extraction("doc_flaky")

    first = _attempt("doc_flaky")
    assert first["state"] == job_queue.RETRYING
    job = _job("doc_flaky")
    assert job["state"] == job_queue.RETRYING
    assert job["retries"] == 1
    assert "transient failure number 1" in job["error_message"], "the error was not kept"
    assert job["next_attempt_at"] > _iso(30), "no backoff was scheduled"

    # BACKOFF IS HONOURED: not due yet, so nobody takes it.
    assert standards.next_extraction_job(worker_id="w") is None

    _make_due("doc_flaky")
    second = _attempt("doc_flaky")
    assert second["state"] == "done"
    job = _job("doc_flaky")
    assert job["state"] == "done"
    assert job["retries"] == 1, "the retry history was rewritten on success"
    assert job["error_message"] is None and job["next_attempt_at"] is None
    assert flaky_extraction["calls"] == 2


def test_the_backoff_grows_with_each_retry(flaky_extraction):
    flaky_extraction["fail_times"] = 10
    _doc("doc_backoff")
    standards.enqueue_extraction("doc_backoff")
    before = _iso()
    _attempt("doc_backoff")
    first_delay = _job("doc_backoff")["next_attempt_at"]
    _make_due("doc_backoff")
    _attempt("doc_backoff")
    second_delay = _job("doc_backoff")["next_attempt_at"]
    assert before < first_delay < second_delay


def test_retry_exhaustion_poisons_the_job_and_keeps_the_last_error(flaky_extraction):
    flaky_extraction["fail_times"] = 99
    _doc("doc_poison")
    standards.enqueue_extraction("doc_poison")

    outcomes = []
    for _ in range(settings.job_max_retries + 1):
        outcomes.append(_attempt("doc_poison")["state"])
        _make_due("doc_poison")

    assert outcomes == [job_queue.RETRYING] * settings.job_max_retries + [job_queue.POISONED]
    job = _job("doc_poison")
    assert job["state"] == job_queue.POISONED
    assert job["retries"] == settings.job_max_retries
    assert "transient failure number 3" in job["error_message"], (
        "the poisoned job lost its LAST error")
    assert job["next_attempt_at"] is None
    # Never picked up again, and never silently deleted.
    assert standards.next_extraction_job(worker_id="w") is None
    assert flaky_extraction["calls"] == settings.job_max_retries + 1
    assert connect().execute("SELECT COUNT(*) FROM jobs WHERE document_id = ?",
                             ("doc_poison",)).fetchone()[0] == 1


def test_a_poisoned_job_does_not_block_an_operator_re_request(flaky_extraction):
    """Poison ends the automatic retries, not the standard's life."""
    flaky_extraction["fail_times"] = 99
    monkeypatch_retries = settings.job_max_retries
    _doc("doc_rerequest")
    standards.enqueue_extraction("doc_rerequest")
    for _ in range(monkeypatch_retries + 1):
        _attempt("doc_rerequest")
        _make_due("doc_rerequest")
    poisoned_id = _job("doc_rerequest")["id"]
    new_id = standards.enqueue_extraction("doc_rerequest", actor=None)
    assert new_id != poisoned_id
    assert _job("doc_rerequest")["state"] == "queued"


def test_a_retrying_job_is_not_enqueued_twice(flaky_extraction):
    flaky_extraction["fail_times"] = 1
    _doc("doc_dedupe")
    first = standards.enqueue_extraction("doc_dedupe")
    _attempt("doc_dedupe")
    assert standards.enqueue_extraction("doc_dedupe") == first


# ------------------------------------------------------------ retry: ingestion

def _ingestable(doc_id: str, *, uploaded_at: str = "2026-09-24T00:00:00Z") -> None:
    _doc(doc_id, status=states.QUEUED, uploaded_at=uploaded_at, role=None)
    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at)"
            " VALUES (?, ?, 'extract', 'running', ?, ?)",
            (f"job_{doc_id}", doc_id, uploaded_at, uploaded_at))


def test_a_failed_ingestion_is_retried_then_poisoned_with_its_error(monkeypatch):
    calls = {"n": 0}

    def exploding_extract(doc_id):
        calls["n"] += 1
        raise RuntimeError(f"extraction blew up {calls['n']}")

    monkeypatch.setattr(ingest, "extract_document", exploding_extract)
    _ingestable("doc_ing")
    worker = IngestionWorker()

    for attempt in range(settings.job_max_retries + 1):
        assert worker._next_document() == "doc_ing", f"attempt {attempt} not claimed"
        worker.process("doc_ing")
        worker._release("doc_ing")
        job = _job("doc_ing", "extract")
        doc = connect().execute("SELECT status, error_message FROM documents WHERE id = ?",
                                ("doc_ing",)).fetchone()
        assert doc["status"] == states.FAILED
        if attempt < settings.job_max_retries:
            assert job["state"] == job_queue.RETRYING
            # Not due yet: the worker leaves it alone.
            assert worker._next_document() is None
            _make_due("doc_ing")

    assert job["state"] == job_queue.POISONED
    assert f"extraction blew up {settings.job_max_retries + 1}" in job["error_message"]
    assert worker._next_document() is None
    _make_due("doc_ing")
    assert worker._next_document() is None, "a poisoned document was picked up again"


def test_a_failed_ingestion_retry_resumes_and_finishes(monkeypatch):
    calls = {"n": 0}

    def once_then_ok(doc_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk hiccup")
        with connect() as conn:
            conn.execute("UPDATE documents SET status = 'no_searchable_content'"
                         " WHERE id = ?", (doc_id,))
        return {"pages_extracted_this_run": 0, "seconds": 0.0}

    monkeypatch.setattr(ingest, "extract_document", once_then_ok)
    _ingestable("doc_resume")
    worker = IngestionWorker()
    assert worker._next_document() == "doc_resume"
    worker.process("doc_resume")
    worker._release("doc_resume")
    _make_due("doc_resume")

    assert worker._next_document() == "doc_resume"
    doc = connect().execute("SELECT status FROM documents WHERE id = ?",
                            ("doc_resume",)).fetchone()
    assert doc["status"] == states.EXTRACTING, "a due retry was not revived"
    assert _job("doc_resume", "extract")["state"] == "running"
    worker.process("doc_resume")
    assert calls["n"] == 2


# ------------------------------------------------------ restart mid-job

def test_a_document_held_by_a_dead_worker_is_recovered_once(monkeypatch):
    _ingestable("doc_orphan")
    _ingestable("doc_live", uploaded_at="2026-09-24T00:00:01Z")
    with connect() as conn:
        conn.execute("UPDATE documents SET claimed_by = 'dead-worker', claimed_at = ?,"
                     " status = 'chunking' WHERE id = 'doc_orphan'",
                     (_iso(-(job_queue.CLAIM_STALE_SECONDS + 60)),))
        conn.execute("UPDATE documents SET claimed_by = 'live-worker', claimed_at = ?"
                     " WHERE id = 'doc_live'", (_iso(-5),))
    a, b = IngestionWorker(), IngestionWorker()
    assert a._next_document() == "doc_orphan"
    assert b._next_document() is None, (
        "the recovered document was handed out twice, or a live claim was stolen")


def test_a_running_extraction_left_by_a_dead_process_is_recovered_not_duplicated(
        flaky_extraction):
    _doc("doc_restart")
    standards.enqueue_extraction("doc_restart")
    assert standards.next_extraction_job(worker_id="dead") == "doc_restart"
    with connect() as conn:
        conn.execute("UPDATE jobs SET updated_at = ?, claimed_at = ?",
                     (_iso(-3600), _iso(-3600)))

    assert standards.recover_stale_extraction_jobs() == 1
    job = _job("doc_restart")
    assert job["state"] == "queued" and job["claimed_by"] is None

    assert standards.next_extraction_job(worker_id="new-a") == "doc_restart"
    assert standards.next_extraction_job(worker_id="new-b") is None
    assert standards.run_extraction_job("doc_restart", worker_id="dead")["state"] == "not_claimed"
    assert standards.run_extraction_job("doc_restart", worker_id="new-a")["state"] == "done"
    assert flaky_extraction["calls"] == 1


# -------------------------------------------------------------- priority

def _pdf(tag: bytes) -> io.BytesIO:
    return io.BytesIO(b"%PDF-1.4\n" + tag * 400 + b"\n%%EOF\n")


def test_an_interactive_upload_outranks_an_earlier_backfill():
    backfill, _, _ = upload.ingest(_pdf(b"historical"), "old.pdf",
                                   priority=job_queue.PRIORITY_BACKFILL)
    interactive, _, _ = upload.ingest(_pdf(b"urgent"), "new.pdf")
    assert backfill["uploaded_at"] <= interactive["uploaded_at"]
    assert interactive["priority"] > backfill["priority"]

    worker = IngestionWorker()
    assert worker._next_document() == interactive["id"], (
        "FIFO order: the backfill blocked the interactive upload")


def test_the_watched_folder_marks_its_documents_as_backfill(tmp_path, monkeypatch):
    folder = tmp_path / "dropbox"
    folder.mkdir()
    monkeypatch.setattr(settings, "watch_folder", str(folder))
    (folder / "bulk.pdf").write_bytes(_pdf(b"bulk").getvalue())
    watcher_mod.scan_once()
    assert watcher_mod.scan_once()["ingested"] == ["bulk.pdf"]
    row = connect().execute("SELECT priority FROM documents").fetchone()
    assert row["priority"] == job_queue.PRIORITY_BACKFILL
    later, _, _ = upload.ingest(_pdf(b"manual"), "manual.pdf")
    assert later["priority"] == job_queue.PRIORITY_INTERACTIVE


def test_an_admin_requested_extraction_outranks_hook_queued_backfill(flaky_extraction):
    _doc("doc_hooked")
    _doc("doc_requested")
    standards.enqueue_extraction("doc_hooked")                 # ingestion hook
    standards.enqueue_extraction("doc_requested",
                                 priority=job_queue.PRIORITY_INTERACTIVE)
    assert standards.next_extraction_job(worker_id="w") == "doc_requested"


def test_a_duplicate_upload_changes_nothing():
    first, job_id, dup = upload.ingest(_pdf(b"same"), "a.pdf",
                                       priority=job_queue.PRIORITY_BACKFILL)
    assert dup is None and job_id
    again, job_again, dup_again = upload.ingest(_pdf(b"same"), "b.pdf")
    assert dup_again == first["id"] and job_again is None
    row = connect().execute("SELECT priority, claimed_by FROM documents WHERE id = ?",
                            (first["id"],)).fetchone()
    assert row["priority"] == job_queue.PRIORITY_BACKFILL, (
        "a duplicate upload rewrote the existing document's priority")
    assert row["claimed_by"] is None
    assert connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


# ------------------------------------------------------------- migration

OLD_DOCUMENTS = """CREATE TABLE documents (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL, stored_path TEXT NOT NULL, page_count INTEGER,
    pages_done INTEGER NOT NULL DEFAULT 0, chunk_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued', error_code TEXT, error_message TEXT,
    uploaded_at TEXT NOT NULL, indexed_at TEXT)"""
OLD_JOBS = """CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'extract', state TEXT NOT NULL DEFAULT 'running',
    pages_total INTEGER, pages_done INTEGER NOT NULL DEFAULT 0,
    last_completed_batch INTEGER, retries INTEGER NOT NULL DEFAULT 0,
    error_code TEXT, error_message TEXT, started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL)"""


def test_the_migration_adds_columns_and_rewrites_no_historical_row(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute(OLD_DOCUMENTS)
    old.execute(OLD_JOBS)
    old.execute("INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
                " status, error_message, uploaded_at) VALUES"
                " ('doc_hist', 'h.pdf', 'abc', 10, 'h.pdf', 'failed', 'old error',"
                " '2025-01-01T00:00:00Z')")
    old.execute("INSERT INTO jobs (id, document_id, stage, state, retries, error_code,"
                " error_message, started_at, updated_at) VALUES"
                " ('job_hist', 'doc_hist', 'extract_requirements', 'failed', 0,"
                " 'ValueError', NULL, '2025-01-01T00:00:00Z', '2025-01-02T00:00:00Z')")
    old.commit()
    before_docs = old.execute("SELECT * FROM documents").fetchall()
    before_jobs = old.execute("SELECT * FROM jobs").fetchall()
    old.close()

    db.reset_connection()
    monkeypatch.setattr(settings, "db_path", path)
    db.init_db()
    db.init_db()   # idempotent: a second boot must not fail or change anything
    conn = connect()

    doc_cols = db.columns_of(conn, "documents")
    job_cols = db.columns_of(conn, "jobs")
    assert {"priority", "claimed_by", "claimed_at"} <= doc_cols
    assert {"priority", "claimed_by", "claimed_at", "next_attempt_at"} <= job_cols

    old_doc_names = [c[1] for c in sqlite3.connect(path).execute(
        "PRAGMA table_info(documents)")][:len(before_docs[0])]
    after_doc = conn.execute(
        f"SELECT {', '.join(old_doc_names)} FROM documents").fetchall()
    assert [tuple(r) for r in after_doc] == [tuple(r) for r in before_docs]
    after_job = conn.execute(
        "SELECT id, document_id, stage, state, pages_total, pages_done,"
        " last_completed_batch, retries, error_code, error_message, started_at,"
        " updated_at FROM jobs").fetchall()
    assert [tuple(r) for r in after_job] == [tuple(r) for r in before_jobs]

    new_values = conn.execute(
        "SELECT d.priority, d.claimed_by, d.claimed_at, j.priority, j.claimed_by,"
        " j.claimed_at, j.next_attempt_at FROM documents d JOIN jobs j"
        " ON j.document_id = d.id").fetchone()
    assert tuple(new_values) == (0, None, None, 0, None, None, None)
    # A historical 'failed' job is NOT reinterpreted as retryable: nothing
    # resurrects work an earlier build gave up on.
    assert standards.next_extraction_job(worker_id="w") is None


# ------------------------------------------------------------- provenance

def _chunk(doc_id: str, chunk_id: str, text: str, section: str = "1.1 Scope") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
            " page_end, section, kind, text, token_count, content_hash, retrievable)"
            " VALUES (?, ?, 'f.pdf', 0, 1, 1, ?, 'prose', ?, 10, ?, 1)",
            (chunk_id, doc_id, section, text, f"h-{chunk_id}"))


def test_requirement_extraction_records_its_version_and_input_hash():
    _doc("doc_req")
    _chunk("doc_req", "c_req",
           "1.1 The vessel design pressure shall not exceed 10 bar at any time.")
    every = frozenset({"doc_req"})
    assert standards.extract_requirements("doc_req", allowed_document_ids=every)["requirements"]
    row = connect().execute(
        "SELECT extractor_version, input_hash FROM standard_requirements").fetchone()
    assert row["extractor_version"] and row["extractor_version"].startswith("standards")
    assert len(row["input_hash"]) == 64
    first_hash = row["input_hash"]

    standards.extract_requirements("doc_req", allowed_document_ids=every)
    assert connect().execute("SELECT input_hash FROM standard_requirements"
                             ).fetchone()["input_hash"] == first_hash, (
        "the same input produced a different hash - not reproducible")

    with connect() as conn:
        conn.execute("UPDATE chunks SET text = ? WHERE id = 'c_req'",
                     ("1.1 The vessel design pressure shall not exceed 12 bar at any time.",))
    standards.extract_requirements("doc_req", allowed_document_ids=every)
    assert connect().execute("SELECT input_hash FROM standard_requirements"
                             ).fetchone()["input_hash"] != first_hash


def _datasheet(path) -> str:
    """A ruled two-column datasheet, the shape test_ingest_fact_extraction
    uses, so `extract_facts` reads a real page rather than a missing file."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(
            [("Design pressure", "23.5 barg"), ("Compressibility factor", "0.892")],
            start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def test_fact_extraction_records_its_version_and_input_hash(tmp_path):
    _doc("doc_fact", role="CONTRACTOR_SUBMITTAL")
    with connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = 'doc_fact'",
                     (_datasheet(tmp_path / "sheet.pdf"),))
    _chunk("doc_fact", "c_fact",
           "1 Design pressure 23.5 barg 2 Compressibility factor 0.892",
           section="Process Data")
    scope = frozenset({"doc_fact"})
    written = datasheets.extract_facts("doc_fact", allowed_document_ids=scope)
    assert written["facts"] >= 1, written
    rows = connect().execute(
        "SELECT DISTINCT extractor_version, input_hash FROM submittal_facts").fetchall()
    assert len(rows) == 1
    assert rows[0]["extractor_version"].startswith("datasheets")
    assert len(rows[0]["input_hash"]) == 64
    first = rows[0]["input_hash"]

    datasheets.extract_facts("doc_fact", allowed_document_ids=scope)
    assert connect().execute("SELECT DISTINCT input_hash FROM submittal_facts"
                             ).fetchall()[0][0] == first

    # A different file under the same chunks is a different input.
    with connect() as conn:
        conn.execute("UPDATE documents SET sha256 = 'other-bytes' WHERE id = 'doc_fact'")
    datasheets.extract_facts("doc_fact", allowed_document_ids=scope)
    assert connect().execute("SELECT DISTINCT input_hash FROM submittal_facts"
                             ).fetchall()[0][0] != first


# ------------------------------------------------------------ visibility

def test_queue_counts_reach_an_admin_and_nobody_else(flaky_extraction):
    flaky_extraction["fail_times"] = 99
    for doc_id in ("doc_q1", "doc_q2", "doc_q3"):
        _doc(doc_id)
        standards.enqueue_extraction(doc_id)
    _attempt("doc_q1")                           # -> retrying
    assert standards.next_extraction_job(worker_id="w2") in {"doc_q2", "doc_q3"}  # -> running
    status = IngestionWorker().status()

    admin_view = metrics.snapshot(status, None, True, True)
    assert admin_view["queue"] == {"queued": 1, "running": 1, "retrying": 1, "poisoned": 0}

    for corpus_wide in (False, True):
        other = metrics.snapshot(status, ["doc_q1"], corpus_wide, False)
        assert "queue" not in other, "queue counts reached a caller without admin"
