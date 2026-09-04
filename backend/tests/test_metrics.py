"""The dashboard shows measured values, or says a value is not measured.

This build has already shipped a rate of 1,021,658,887 pages/sec from a
divide-by-almost-zero, a worker reporting healthy with a full queue, and a
"ready" document search could not see. A number on a dashboard is read as a
fact, so an unmeasured one is the most expensive thing that can be put there.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, metrics, states, telemetry
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

PROSE = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow.",
    "Any exceedance shall be reported to the area engineer before the pump is",
    "returned to service under the procedure given in this specification.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def upload(client, blocks=(PROSE,), name="spec.pdf") -> str:
    path = settings.data_dir / name
    doc = fitz.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


# ------------------------------------------------------- unmeasured is null


def test_a_stage_that_has_never_run_reports_null_not_zero():
    """Zero is a measurement. "No measurement" is not, and a dashboard that
    shows 0 chunks/sec for a stage that never ran is stating a false fact."""
    assert telemetry.throughput() == {
        "extract": None,
        "chunk": None,
        "keyword_index": None,
        "embed": None,
    }


def test_retrieval_latency_is_null_until_a_question_is_asked():
    assert telemetry.retrieval_latency() is None


def test_a_rate_is_never_derived_from_an_unmeasurable_interval():
    """The 1,021,658,887 pages/sec bug, guarded at the source."""
    telemetry.record(telemetry.EXTRACT, 5, 0.0001)
    assert telemetry.throughput()["extract"] is None

    telemetry.record(telemetry.EXTRACT, 320, 1.05)
    measured = telemetry.throughput()["extract"]
    assert measured is not None
    # the unmeasurable sample is excluded, not averaged in
    assert measured["samples"] == 1
    assert 250 < measured["median"] < 400


def test_the_median_is_used_so_one_throttled_batch_is_not_the_headline():
    """A single batch that ran while the laptop was thermally throttled should
    not become the number on the screen, and nor should the fastest one."""
    for seconds in (1.0, 0.8, 1.2, 8.0):
        telemetry.record(telemetry.EMBED, 64, seconds)
    measured = telemetry.throughput()["embed"]
    assert measured["samples"] == 4
    # the throttled 8s batch scores 8 chunks/s; the median must ignore it
    assert measured["median"] > 30
    # and the best is faster than the median, so neither is the other
    assert measured["best"] > measured["median"]


def test_telemetry_never_raises_into_the_pipeline(monkeypatch):
    """Losing a dashboard sample must not fail an ingestion."""
    monkeypatch.setattr(telemetry, "connect", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    telemetry.record(telemetry.EXTRACT, 10, 1.0)  # must not raise


def test_samples_are_trimmed_so_the_table_cannot_grow_without_bound(monkeypatch):
    monkeypatch.setattr(telemetry, "KEEP_PER_STAGE", 5)
    for _ in range(20):
        telemetry.record(telemetry.CHUNK, 100, 1.0)
    n = db.connect().execute(
        "SELECT COUNT(*) FROM stage_runs WHERE stage = ?", (telemetry.CHUNK,)
    ).fetchone()[0]
    assert n == 5


# ------------------------------------------------------------- real values


def test_processing_a_document_records_every_stage():
    """Each stage is recorded as it happens. Whether a RATE can be derived from
    it is a separate question - a one-page document indexes in under 50ms, and
    the rate guard correctly refuses to divide by that. The recording is what
    must always happen; the rate is reported only when it is real."""
    client = TestClient(app)
    upload(client)
    stages = {
        r["stage"]
        for r in db.connect().execute("SELECT DISTINCT stage FROM stage_runs")
    }
    assert {telemetry.EXTRACT, telemetry.CHUNK, telemetry.KEYWORD_INDEX} <= stages

    # and a stage too fast to measure reports no rate rather than a wrong one
    measured = telemetry.throughput()
    for stage, value in measured.items():
        if value is not None:
            assert value["median"] > 0
            assert value["samples"] >= 1


def test_a_document_large_enough_to_time_produces_a_real_rate():
    """The complement of the test above: given work that takes measurable
    time, a rate does appear. Without this the pair could both pass while
    throughput never worked at all."""
    client = TestClient(app)
    upload(client, blocks=[PROSE] * 40, name="long.pdf")
    measured = telemetry.throughput()
    assert any(v is not None for v in measured.values()), measured


def test_asking_a_question_populates_real_retrieval_latency():
    client = TestClient(app)
    upload(client)
    client.get("/api/answer?q=what is the vibration limit for pump P-101A")
    latency = telemetry.retrieval_latency()
    assert latency is not None
    assert latency["samples"] >= 1
    assert latency["p50"] is not None and latency["p50"] > 0
    assert latency["worst"] >= latency["p50"]


def test_the_corpus_counts_distinguish_retrievable_from_stored():
    client = TestClient(app)
    upload(client)
    body = TestClient(app).get("/api/metrics").json()["corpus"]
    assert body["documents"] == 1
    assert body["pages_extracted"] >= 1
    assert body["chunks_total"] >= body["chunks_retrievable"]
    assert body["chunks_excluded"] == body["chunks_total"] - body["chunks_retrievable"]
    assert body["chunks_indexed_keyword"] == body["chunks_retrievable"]


def test_the_model_status_is_read_from_the_modules_not_reimplemented():
    """The reranker first reported absent while it was working, because this
    module had its own hand-written copy of the directory layout."""
    from app import reranker

    status = metrics.models()
    assert status["reranker_model"] == reranker.model_dir().name
    assert status["reranker_present"] == reranker.available()


def test_a_stopped_ollama_is_reported_as_a_state_not_a_crash(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:9")
    status = metrics.models()
    assert status["answer_model_reachable"] is False
    assert status["ollama_error"]
    # and the configured name is still reported, so the screen can say what is
    # missing rather than just that something is
    assert status["answer_model"] == settings.answer_model


def test_system_metrics_are_present_and_plausible():
    s = metrics.system()
    assert s["ram_total_bytes"] > 0
    assert 0 <= s["ram_percent"] <= 100
    assert s["process_rss_bytes"] > 0
    assert s["disk_total_bytes"] > 0
    assert s["disk_free_bytes"] <= s["disk_total_bytes"]
    assert 0 <= s["cpu_percent_since_last_call"] <= 100 * (s["cpu_logical_cores"] or 1)


# ---------------------------------------------------------------- warnings


def test_no_searchable_content_is_reported_as_a_warning():
    """The document finished, so every progress bar reads complete, and search
    can see none of it. That must not have to be inferred from the numbers."""
    client = TestClient(app)
    doc_id = upload(client)
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, error_message = ? WHERE id = ?",
            (states.NO_SEARCHABLE_CONTENT, "every page was a scanned image", doc_id),
        )
    body = client.get("/api/metrics").json()
    warning = next(
        (w for w in body["warnings"] if w["code"] == states.NO_SEARCHABLE_CONTENT), None
    )
    assert warning is not None
    assert warning["severity"] == "warning"
    assert warning["document_id"] == doc_id
    assert "search can see none of it" in warning["message"]
    assert "scanned image" in warning["message"]


def test_a_failed_document_is_reported_as_an_error():
    client = TestClient(app)
    doc_id = upload(client)
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, error_code = ?, error_message = ? WHERE id = ?",
            (states.FAILED, "extract_failed", "the PDF is malformed", doc_id),
        )
    body = client.get("/api/metrics").json()
    assert any(w["severity"] == "error" for w in body["warnings"])
    assert body["jobs"]["failed_documents"] == 1
    assert body["jobs"]["failures"][0]["error_code"] == "extract_failed"


def test_undetected_ocr_is_stated_rather_than_implied():
    client = TestClient(app)
    doc_id = upload(client)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET needs_ocr_pages = 12 WHERE id = ?", (doc_id,))
    body = client.get("/api/metrics").json()
    warning = next((w for w in body["warnings"] if w["code"] == "needs_ocr"), None)
    assert warning is not None
    assert "NOT implemented" in warning["message"]


def test_a_healthy_corpus_raises_no_warnings():
    """The warnings list must mean something. If it is never empty, it is
    decoration rather than a signal."""
    client = TestClient(app)
    upload(client)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET needs_ocr_pages = 0, equation_pages = 0")
    assert client.get("/api/metrics").json()["warnings"] == []


# ---------------------------------------------------------------- endpoint


def test_the_metrics_endpoint_declares_its_refresh_and_its_timestamp():
    client = TestClient(app)
    body = client.get("/api/metrics").json()
    assert body["refresh_seconds"] == 15
    assert body["at"].endswith("Z")


def test_the_metrics_endpoint_rejects_unknown_parameters():
    assert TestClient(app).get("/api/metrics?bogus=1").status_code == 422


def test_the_metrics_endpoint_works_on_an_empty_corpus():
    """A fresh install must render, not 500."""
    body = TestClient(app).get("/api/metrics")
    assert body.status_code == 200
    data = body.json()
    assert data["corpus"]["documents"] == 0
    assert data["retrieval"] is None
    assert data["exclusions"] == []


def test_the_first_cpu_reading_is_null_rather_than_a_false_zero():
    """psutil.cpu_percent(interval=None) reports usage since the PREVIOUS call,
    so the first call has no baseline and returns exactly 0.0. Putting that on
    the screen would state "CPU 0%" as a fact on first render."""
    metrics._cpu_measured_once = False
    assert metrics.system()["cpu_percent_since_last_call"] is None
    second = metrics.system()["cpu_percent_since_last_call"]
    assert second is not None
    assert 0 <= second <= 100 * (metrics.psutil.cpu_count(logical=True) or 1)
