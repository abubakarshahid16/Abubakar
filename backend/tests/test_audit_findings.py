"""Regression tests for the browser-audit findings.

Each test names the defect it prevents, because several of these are the same
mistake recurring: a field or a record that claims something the system is not
actually doing.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, states
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.ingest import IngestionWorker
from app.main import app

BODY = [
    "The vibration limit shall not exceed three point zero millimetres per",
    "second measured at the bearing housing during normal operation, and any",
    "reading above that value shall be reported to the area engineer before",
    "the pump is returned to service under the maintenance procedure.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def build_pdf(path, pages):
    """pages: list of "prose" | "sparse" | "blank"."""
    doc = fitz.open()
    for i, kind in enumerate(pages):
        page = doc.new_page()
        if kind == "prose":
            page.insert_text((72, 100), f"{i + 1}.1 Scope")
            for n, line in enumerate(BODY):
                page.insert_text((72, 130 + n * 14), line)
        elif kind == "sparse":
            page.insert_text((72, 100), "x")
    doc.save(str(path))
    doc.close()
    return path


def upload(client, name, pages):
    path = build_pdf(settings.data_dir / name, pages)
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={"file": (name, fh, "application/pdf")})
    return r.json()["document"]["id"]


# ------------------------------------------------------------------- BUG 1


def test_every_terminal_status_is_excluded_from_the_work_queue():
    """`no_searchable_content` was terminal but absent from a hand-maintained
    tuple in _next_document, so the worker re-selected such a document forever,
    held it as current_document, kept pending_count at 1, and thereby DISABLED
    the stall detector built to catch exactly that.

    This asserts the queue is derived from states.py, so a new terminal state
    can never reintroduce the bug.
    """
    client = TestClient(app)
    doc_id = upload(client, "a.pdf", ["prose", "prose"])
    conn = db.connect()
    worker = IngestionWorker()

    for terminal in sorted(states.TERMINAL_STATES):
        with conn:
            conn.execute(
                "UPDATE documents SET status = ?, indexed_at = ? WHERE id = ?",
                (terminal, "2026-09-04T00:00:00Z", doc_id),
            )
        assert worker._next_document() is None, (
            f"a document in terminal state {terminal!r} is still selected for work; "
            "it will be held forever and the stall detector disabled"
        )
        assert worker.status()["pending_count"] == 0, (
            f"terminal state {terminal!r} still counts towards the backlog"
        )


def test_a_no_searchable_content_document_is_released_immediately():
    """The reproduction: it stayed as current_document with the age climbing."""
    client = TestClient(app)
    doc_id = upload(client, "scan.pdf", ["blank", "blank"])
    worker = IngestionWorker()
    worker.process(doc_id)

    row = db.connect().execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["status"] == states.NO_SEARCHABLE_CONTENT

    assert worker._next_document() is None
    status = worker.status()
    assert status["pending_count"] == 0
    assert status["oldest_pending_age_seconds"] is None


# ------------------------------------------------------------------- BUG 2


def test_documents_completed_counts_documents_not_stage_invocations():
    """It jumped 2 -> 8 -> 12 while no document completed, because re-running a
    stage produced another terminal transition on the SAME document. This field
    was added to fix that class of dishonesty, and had it."""
    client = TestClient(app)
    doc_id = upload(client, "a.pdf", ["prose", "prose"])
    worker = IngestionWorker()
    conn = db.connect()

    def cycle(target: str) -> None:
        before = worker._is_finished(target)
        worker.process(target)
        if not before and worker._is_finished(target):
            worker._completed.add(target)

    assert worker.documents_completed == 0
    cycle(doc_id)
    assert worker.documents_completed == 1

    for _ in range(4):
        with conn:
            conn.execute(
                "UPDATE documents SET status = ?, indexed_at = NULL WHERE id = ?",
                (states.CHUNKING, doc_id),
            )
        cycle(doc_id)

    assert worker.documents_completed == 1, (
        f"one document processed but the counter reads {worker.documents_completed} "
        "- it is counting stage invocations"
    )

    other = upload(client, "b.pdf", ["prose"])
    cycle(other)
    assert worker.documents_completed == 2


# ------------------------------------------------------------- BUG 3 and 4


def test_every_page_without_a_chunk_has_an_exclusion_record():
    """'Nothing is dropped silently' is the promise /excluded exists to keep.
    11 pages produced no chunks and had NO exclusion row - four held real text,
    including book1 p158's 'Chapter 3 Freedom of Speech'."""
    client = TestClient(app)
    doc_id = upload(client, "mixed.pdf", ["prose", "sparse", "blank"])
    extract_document(doc_id)
    chunk_document(doc_id)

    conn = db.connect()
    covered: set[int] = set()
    for r in conn.execute(
        "SELECT page_start, page_end FROM chunks WHERE document_id = ?", (doc_id,)
    ):
        covered.update(range(r["page_start"], r["page_end"] + 1))
    all_pages = {
        r["page_no"]
        for r in conn.execute("SELECT page_no FROM pages WHERE document_id = ?", (doc_id,))
    }
    without_chunks = all_pages - covered
    assert without_chunks, "the fixture must contain a page that yields nothing"

    recorded = {
        r["page_start"]
        for r in conn.execute(
            "SELECT page_start FROM exclusions WHERE document_id = ? AND scope = 'page'",
            (doc_id,),
        )
    }
    missing = without_chunks - recorded
    assert not missing, f"pages dropped with no exclusion record: {sorted(missing)}"


def test_every_recorded_page_exclusion_states_a_reason():
    client = TestClient(app)
    doc_id = upload(client, "mixed.pdf", ["prose", "sparse", "blank"])
    extract_document(doc_id)
    chunk_document(doc_id)

    rows = list(
        db.connect().execute(
            "SELECT rule, reason FROM exclusions WHERE document_id = ? AND scope = 'page'",
            (doc_id,),
        )
    )
    assert rows
    for r in rows:
        assert r["rule"], "an exclusion without a rule is not a record"
        assert r["reason"], f"rule {r['rule']!r} recorded without a reason"


def test_needs_ocr_pages_are_recorded_not_just_flagged():
    """A flag nobody acts on is not a record. Scanned pages must appear in
    /excluded with a stated reason so the count is visible and honest."""
    client = TestClient(app)
    doc_id = upload(client, "scan.pdf", ["blank", "blank", "blank"])
    extract_document(doc_id)
    chunk_document(doc_id)

    rows = list(
        db.connect().execute(
            "SELECT rule, reason FROM exclusions WHERE document_id = ? AND scope = 'page'",
            (doc_id,),
        )
    )
    assert len(rows) == 3, f"expected 3 recorded pages, got {len(rows)}"
    assert all(r["rule"] == "needs_ocr_not_implemented" for r in rows)
    assert all("OCR is not implemented" in r["reason"] for r in rows)


# ------------------------------------------------------------------- BUG 6


def test_exclusion_text_length_matches_page_char_count():
    """text_length was always 1-2 greater than char_count - a trailing-newline
    miscount, never zero, so the two endpoints disagreed by construction."""
    client = TestClient(app)
    doc_id = upload(client, "mixed.pdf", ["prose", "sparse", "blank"])
    extract_document(doc_id)
    chunk_document(doc_id)

    conn = db.connect()
    pages = {
        r["page_no"]: r["char_count"]
        for r in conn.execute(
            "SELECT page_no, char_count FROM pages WHERE document_id = ?", (doc_id,)
        )
    }
    mismatches = []
    for r in conn.execute(
        "SELECT page_start, text_length FROM exclusions"
        " WHERE document_id = ? AND scope = 'page'",
        (doc_id,),
    ):
        expected = pages.get(r["page_start"])
        if expected is not None and expected != r["text_length"]:
            mismatches.append((r["page_start"], expected, r["text_length"]))
    assert not mismatches, f"char_count != text_length for pages: {mismatches}"


# ------------------------------------------------------------------- BUG 5


def test_a_marks_rubric_is_not_classified_as_an_index():
    """OS_Term p12 - a 'Project Rubric' table of criteria against marks - was
    classified page_classified_index and dropped. Aramco specifications are
    full of tables of codes and numbers that would trip the same rule."""
    from app.chunker import classify_page

    rubric = "\n".join(
        [
            "Project Rubric",
            "Component",
            "Marks",
            "Understanding of Problem and Viva",
            "60",
            "Clear explanation of process and thread mapping",
            "20",
            "Accurate answers to questions during viva",
            "40",
            "Design and Architecture",
            "45",
            "Correct mapping of components to processes",
            "10",
            "Dynamic creation of processes at runtime",
            "15",
            "Inter-process communication design",
            "20",
            "Implementation Quality",
            "35",
            "Correct synchronisation and absence of deadlock",
            "25",
        ]
    )
    # near the end of a short document - exactly where the index rule looks
    assert classify_page(rubric, page_no=12, total_pages=13) == "prose"


def test_a_real_contents_page_is_still_detected():
    """The rubric fix must not blind the contents detector: a genuine
    two-column contents page has ASCENDING numbers bounded by the document."""
    from app.chunker import classify_page

    toc_lines = []
    page = 20
    for i in range(1, 16):
        toc_lines.append(f"{i}.1 Section title number {i}")
        toc_lines.append(str(page))
        page += 12
    contents = "\n".join(toc_lines)
    assert classify_page(contents, page_no=6, total_pages=400) == "toc"


def test_page_number_column_detection_rejects_scores():
    from app.chunker import _is_page_number_column

    # marks: out of range for a 13-page document, and not ascending
    marks = ["60", "20", "40", "45", "10", "15", "20", "35", "25", "30", "12"]
    assert not _is_page_number_column(marks, total_pages=13)

    # page numbers: in range and ascending
    numbers = [str(n) for n in range(10, 210, 15)]
    assert _is_page_number_column(numbers, total_pages=400)


def test_embedded_count_never_exceeds_the_chunk_count_after_rechunking():
    """Re-chunking changes chunk ids, orphaning the vectors keyed on the old
    ones. embedded_count counted vector ROWS, so book2 read 1448 embedded
    against 1356 chunks - progress above 100%."""
    client = TestClient(app)
    doc_id = upload(client, "a.pdf", ["prose", "prose", "prose"])
    worker = IngestionWorker()
    worker.process(doc_id)

    conn = db.connect()
    first = conn.execute(
        "SELECT chunk_count, embedded_count FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert first["embedded_count"] == first["chunk_count"]

    # force a rebuild, which regenerates chunk ids
    chunk_document(doc_id, force=True)
    worker.process(doc_id)

    row = conn.execute(
        "SELECT chunk_count, embedded_count FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["embedded_count"] <= row["chunk_count"], (
        f"embedded_count {row['embedded_count']} exceeds chunk_count "
        f"{row['chunk_count']} - orphaned vectors are being counted"
    )

    orphans = conn.execute(
        """SELECT COUNT(*) FROM chunk_vectors v
           WHERE v.document_id = ?
             AND v.chunk_id NOT IN (SELECT id FROM chunks WHERE document_id = ?)""",
        (doc_id, doc_id),
    ).fetchone()[0]
    assert orphans == 0, f"{orphans} orphaned vectors survived re-chunking"
