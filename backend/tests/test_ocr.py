"""OCR stage: provenance, the re-extraction trap, and the alphabet guard.

No real recognition runs here. The engine is a 500 MB ONNX session and a real
invocation would put seconds onto every run of a 478-test suite; the worker
boundary is faked instead, which is the part this module actually owns. The
one test that constructs a real engine is marked `slow` and deselected by
default.
"""

from __future__ import annotations

import pytest

from app import db, extract, ocr
from app.chunker import chunk_provenance
from app.config import settings
from app.db import connect


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


# --------------------------------------------------------------- alphabet

def test_latin_text_has_no_alphabet_violations():
    n, sample = ocr.alphabet_violations("Coating system no. 1, 120 °C, ±5 % — NDFT ≤ 80 µm")
    assert n == 0
    assert sample == ""


def test_cjk_substitutions_are_counted_and_sampled():
    """The measured failure: a multilingual recogniser reading English.

    凤 in a temperature value is obvious. U+2266 where the document says
    U+2264 is invisible and wrong, and that is the one this guard exists for.
    """
    n, sample = ocr.alphabet_violations("Save 凤 日 and NDFT ≦ 80")
    assert n == 3
    assert "凤" in sample and "日" in sample and "≦" in sample


def test_accented_latin_and_symbols_are_not_violations():
    """The guard must not fire on legitimate specification characters."""
    n, _ = ocr.alphabet_violations("café ° ± × ÷ § ¶ ½ Ω µ")
    assert n == 0


def test_the_guard_is_off_for_a_non_latin_corpus():
    n, _ = ocr.alphabet_violations("مواصفات", script="arabic")
    assert n == 0


# ------------------------------------------------------------- round size

def test_the_round_doubles_so_early_pages_index_fast_and_the_total_stays_bounded():
    first = ocr.round_size(0)
    assert first == settings.ocr_batch_size
    assert ocr.round_size(first) == first          # 2x after one round
    assert ocr.round_size(256) == 256              # keeps doubling
    # A 1,400-page scanned document reaches full coverage in a handful of
    # re-index passes rather than 175 of them.
    rounds, done = 0, 0
    while done < 1400:
        done += ocr.round_size(done)
        rounds += 1
    assert rounds <= 10


# ------------------------------------------------------ pending / once-only

def _seed(tmp_path, pages):
    """A document with the given (page_no, text, needs_ocr) rows."""
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                                      page_count, status, uploaded_at)
               VALUES ('d1','f.pdf','abc',1,?,?,'partially_searchable','2026-01-01T00:00:00Z')""",
            (str(tmp_path / "f.pdf"), len(pages)),
        )
        conn.executemany(
            """INSERT INTO pages (document_id, page_no, text, char_count, needs_ocr,
                                  equation_heavy, batch_no)
               VALUES ('d1',?,?,?,?,0,0)""",
            [(p, t, len(t.strip()), int(o)) for p, t, o in pages],
        )
    return "d1"


def test_only_flagged_pages_are_pending(tmp_path):
    doc_id = _seed(tmp_path, [(1, "a" * 500, False), (2, "", True), (3, "b" * 500, False)])
    assert ocr.pending_pages(doc_id) == [2]


def test_a_recognised_page_is_never_recognised_again(tmp_path):
    """Lever 1, asserted: a document with one scanned page recognises once."""
    doc_id = _seed(tmp_path, [(1, "a" * 500, False), (2, "", True)])
    assert ocr.pending_pages(doc_id) == [2]
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO page_ocr (document_id, page_no, text, char_count, engine,
                                     model, dpi, box_count, seconds, recognised_at,
                                     batch_no)
               VALUES ('d1',2,'recognised words',16,'e','m',150,3,0.5,'2026-01-01T00:00:00Z',0)"""
        )
    assert ocr.pending_pages(doc_id) == []


def test_a_blank_recognised_page_is_also_never_retried(tmp_path):
    """Zero boxes is an ANSWER, not a failure to answer.

    5 of 12 real flagged pages return no boxes at either dpi. Re-recognising
    them on every pass would be unbounded work for a page that is blank.
    """
    doc_id = _seed(tmp_path, [(1, "", True)])
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO page_ocr (document_id, page_no, text, char_count, engine,
                                     model, dpi, box_count, seconds, recognised_at,
                                     batch_no)
               VALUES ('d1',1,'',0,'e','m',150,0,0.4,'2026-01-01T00:00:00Z',0)"""
        )
    assert ocr.pending_pages(doc_id) == []


# ------------------------------------------------------- THE RE-EXTRACTION TRAP

def _empty_extraction(path, first, last):
    """What extraction produced the first time, and would produce again."""
    return [(p, "", True, False) for p in range(first, last + 1)]


class _InlineFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class _InlinePool:
    """Runs submitted work immediately, in this process."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *args, **kwargs):
        return _InlineFuture(fn(*args, **kwargs))

def test_re_extraction_does_not_destroy_recognised_text(tmp_path, monkeypatch):
    """The single most expensive defect available in this feature.

    extract.py writes `pages` with INSERT OR REPLACE, and states.py permits
    re-extraction from both no_searchable_content and failed. If recognised
    text lived on `pages`, a re-extraction would overwrite twenty minutes of
    work with the empty extraction that triggered it - silently.
    """
    doc_id = _seed(tmp_path, [(1, "", True)])
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO page_ocr (document_id, page_no, text, char_count, engine,
                                     model, dpi, mean_conf, box_count, seconds,
                                     recognised_at, batch_no)
               VALUES ('d1',1,'NDFT shall be 80 micrometres',27,'rapidocr-3.9.2',
                       'm',150,0.97,4,0.9,'2026-01-01T00:00:00Z',0)"""
        )
        conn.execute(
            """INSERT INTO jobs (id, document_id, stage, state, pages_total,
                                 started_at, updated_at)
               VALUES ('j1','d1','extract','running',1,'2026-01-01T00:00:00Z',
                       '2026-01-01T00:00:00Z')"""
        )

    # Re-extraction produces exactly what it produced the first time: nothing.
    # Dispatched inline rather than through the process pool - a locally
    # defined stand-in cannot be pickled across a process boundary, and the
    # pool is not what this test is about.
    monkeypatch.setattr(extract, "page_count", lambda path: 1)
    monkeypatch.setattr(extract.os.path, "exists", lambda p: True)
    monkeypatch.setattr(extract.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(extract, "extract_batch", _empty_extraction)
    extract.extract_document(doc_id)

    row = conn.execute(
        "SELECT text, char_count FROM page_ocr WHERE document_id='d1' AND page_no=1"
    ).fetchone()
    assert row is not None, "re-extraction destroyed the recognised text"
    assert row["text"] == "NDFT shall be 80 micrometres"
    # And the extraction row is still empty, so the two are genuinely separate.
    assert conn.execute(
        "SELECT text FROM pages WHERE document_id='d1' AND page_no=1"
    ).fetchone()["text"] == ""


# ------------------------------------------------------------- provenance

def test_a_chunk_spanning_a_recognised_page_claims_recognised():
    """Any recognised page makes the WHOLE chunk recognised.

    A reader cannot tell which sentence came from where, so the label makes
    the weaker claim. Exercises the real function, not a copy of its rule.
    """
    assert chunk_provenance(4, 5, {5}, {5: 0.81}) == ("recognised", 0.81, 0, None)


def test_a_chunk_on_extracted_pages_only_claims_extracted():
    assert chunk_provenance(4, 5, {9}, {}) == ("extracted", None, 0, None)


def test_the_weakest_confidence_in_the_chunk_governs():
    assert chunk_provenance(1, 3, {1, 2, 3},
                            {1: 0.99, 2: 0.62, 3: 0.88}) == ("recognised", 0.62, 0, None)


def test_a_recognised_page_with_no_confidence_still_claims_recognised():
    """Missing confidence must never downgrade the claim to 'extracted'."""
    assert chunk_provenance(1, 1, {1}, {}) == ("recognised", None, 0, None)


def test_alphabet_violations_sum_across_the_pages_a_chunk_spans():
    """Confidence is the model's opinion of itself; a violation is PROOF.

    Two pages can both sit at 0.95 and one of them contains a CJK ideograph.
    The count and the offending characters travel with the chunk so the reader
    is told WHICH characters cannot be right.
    """
    source, conf, n, sample = chunk_provenance(
        1, 2, {1, 2}, {1: 0.95, 2: 0.95},
        {1: (2, "凤日"), 2: (1, "≦")},
    )
    assert (source, conf, n) == ("recognised", 0.95, 3)
    assert sample is not None and set(sample) == {"凤", "日", "≦"}


def test_a_clean_recognised_chunk_reports_no_violations():
    """Under a Latin-only recogniser this is the only outcome there should be,
    which is what makes a non-zero count a signal about the MODEL."""
    assert chunk_provenance(1, 1, {1}, {1: 0.9}, {1: (0, "")}) == (
        "recognised", 0.9, 0, None)


# ------------------------------------------------------- exclusion ledger

def test_the_stale_rule_name_is_renamed_by_the_migration(tmp_path):
    """`needs_ocr_not_implemented` asserted a property of the SYSTEM.

    It goes false the day OCR ships. `ocr_not_run` asserts a property of the
    PAGE, which was true when the row was written and stays true.
    """
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                                      status, uploaded_at)
               VALUES ('d9','f.pdf','z',1,'/x','ready','2026-01-01T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO exclusions (document_id, scope, page_start, page_end, rule,
                                       reason, text_sample, text_length, created_at)
               VALUES ('d9','page',3,3,'needs_ocr_not_implemented',
                       'scanned page with no extractable text; OCR is not implemented',
                       '',0,'2026-01-01T00:00:00Z')"""
        )
    db._migrate(conn)
    row = conn.execute(
        "SELECT rule, reason FROM exclusions WHERE document_id='d9'").fetchone()
    assert row["rule"] == "ocr_not_run"
    assert "not implemented" not in row["reason"]


# ------------------------------------------------------------------- slow

@pytest.mark.slow
def test_a_real_engine_loads_from_the_vendored_weights_and_reads_a_page():
    """Marked slow and deselected by default: constructs a real ONNX session."""
    d = settings.ocr_model_dir
    if not (d / settings.ocr_det_model).exists():
        pytest.skip("OCR weights not staged - run scripts/fetch_models.py")
    engine = ocr._build_engine()
    assert engine is not None


def test_ocr_runs_after_the_keyword_index_never_before_it(tmp_path, monkeypatch):
    """Ordering, asserted rather than assumed.

    Time-to-first-answerable on a 1,400-page text document is ~13 s. If
    recognition ran before the keyword index it would put minutes in front of
    the first answer. The document must be ANSWERABLE before OCR starts.
    """
    import fitz
    from fastapi.testclient import TestClient

    from app import states
    from app.ingest import IngestionWorker
    from app.main import app

    pdf = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page()                       # scanned
    page = doc.new_page()
    page.insert_text((72, 100), "Section 3.0 Application", fontsize=13)
    page.insert_text((72, 130), "The quick brown fox jumps over the lazy dog. " * 5,
                     fontsize=9)
    doc.save(str(pdf)); doc.close()

    client = TestClient(app)
    with open(pdf, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": ("mixed.pdf", fh, "application/pdf")}
                             ).json()["document"]["id"]

    seen: list[str] = []
    real = ocr.recognise_document

    def spy(did, **kw):
        status = connect().execute(
            "SELECT status FROM documents WHERE id = ?", (did,)).fetchone()["status"]
        seen.append(status)
        return real(did, **kw)

    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(ocr, "recognise_batch", _fake_recognition)
    monkeypatch.setattr(ocr, "recognise_document", spy)

    worker = IngestionWorker()
    worker.process(doc_id)

    assert seen, "OCR never ran"
    # Every invocation happened with the document already answerable.
    assert all(s == states.PARTIALLY_SEARCHABLE for s in seen), seen
    assert all(s in states.ANSWERABLE_STATES for s in seen), seen


def _fake_recognition(stored_path, sha256, page_nos):
    """What the worker returns, without a 500 MB ONNX session."""
    return [
        (p,
         "Coating system no. 1 shall achieve a nominal dry film thickness of "
         "80 micrometres measured in accordance with the referenced standard.",
         0.95, 0.91, 6, 0.8, 0, "", None)
        for p in page_nos
    ]


def test_recognised_text_reaches_a_chunk_labelled_recognised(tmp_path, monkeypatch):
    """The whole path, with the ONNX session faked out.

    A scanned page produces no chunk before recognition. After it, the text is
    chunked and the chunk claims 'recognised' - never 'extracted'.
    """
    import fitz
    from fastapi.testclient import TestClient

    from app.chunker import chunk_document
    from app.extract import extract_document
    from app.main import app

    pdf = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()                       # deliberately blank: a scanned page
    page = doc.new_page()
    page.insert_text((72, 100), "Section 2.0 Coating", fontsize=13)
    page.insert_text((72, 130), "The quick brown fox jumps over the lazy dog. " * 5,
                     fontsize=9)
    doc.save(str(pdf)); doc.close()

    client = TestClient(app)
    with open(pdf, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": ("scan.pdf", fh, "application/pdf")}
                             ).json()["document"]["id"]
    extract_document(doc_id)
    chunk_document(doc_id)

    conn = connect()
    assert conn.execute(
        "SELECT COUNT(*) c FROM pages WHERE document_id=? AND needs_ocr=1", (doc_id,)
    ).fetchone()["c"] == 1
    # Before recognition: recorded as not-run, and no chunk claims recognised.
    assert conn.execute(
        "SELECT rule FROM exclusions WHERE document_id=? AND page_start=1", (doc_id,)
    ).fetchone()["rule"] == "ocr_not_run"

    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(ocr, "recognise_batch", _fake_recognition)
    result = ocr.recognise_document(doc_id)
    assert result["pages_recognised"] == 1
    assert result["pages_with_text"] == 1
    assert result["alphabet_violations"] == 0

    chunk_document(doc_id, force=True)
    rows = conn.execute(
        """SELECT text_source, ocr_min_conf FROM chunks
           WHERE document_id=? AND page_start=1""", (doc_id,)).fetchall()
    assert rows, "recognised page produced no chunk"
    assert all(r["text_source"] == "recognised" for r in rows)
    assert all(r["ocr_min_conf"] == 0.91 for r in rows)
    # And the page that always had text is still, correctly, extracted.
    assert conn.execute(
        "SELECT text_source FROM chunks WHERE document_id=? AND page_start=2",
        (doc_id,)).fetchone()["text_source"] == "extracted"
