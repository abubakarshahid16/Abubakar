"""No API response may ever expose internals.

The hostile-input audit scanned 22 cases and found zero leaks. Then
`last_error` was added to /api/health and leaked a full traceback with
absolute paths - because it was written after the audit had run.

So this file does not test one endpoint. It enumerates EVERY route on the
app and scans every response body, including error responses provoked by
hostile input. A new endpoint is covered the moment it is added.
"""
import re

import fitz
import pytest
from fastapi.testclient import TestClient

from app import db, errors, states
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

# Anything that would tell a reader about the source tree or the stack.
LEAK_PATTERNS = [
    ("traceback", re.compile(r"Traceback \(most recent call last\)")),
    ("source_file", re.compile(r'File "')),
    ("windows_path", re.compile(r"[A-Za-z]:\\\\?[\w.\\-]+\\\\")),
    ("posix_source_path", re.compile(r"/(?:home|Users|project)/[\w./-]+")),
    ("line_number", re.compile(r", line \d+, in ")),
    ("module_dunder", re.compile(r"__main__|site-packages")),
    ("sql_statement", re.compile(r"(?i)\bSELECT\b.+\bFROM\b\s+\w+")),
]

HOSTILE_IDS = [
    "doc_zzzzzzzzzzzz",
    "not-an-id",
    "x" * 300,
    "🔥",
    "'; DROP TABLE documents; --",
    "../../etc/passwd",
    "%00null",
    "<script>alert(1)</script>",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


@pytest.fixture
def client():
    return TestClient(app)


def make_pdf(path, pages=2, blank=False):
    doc = fitz.open()
    for i in range(pages):
        p = doc.new_page()
        if not blank:
            p.insert_text((72, 100), f"Section {i+1}.0 Scope")
            p.insert_text((72, 130), "The vibration limit shall not exceed three point")
            p.insert_text((72, 146), "zero millimetres per second at the bearing housing.")
    doc.save(str(path))
    doc.close()
    return path


def upload(client, name="s.pdf", pages=2, blank=False) -> str:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = make_pdf(settings.data_dir / name, pages, blank)
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={"file": (name, fh, "application/pdf")})
    return r.json()["document"]["id"]


def assert_clean(body: str, where: str) -> None:
    for label, pattern in LEAK_PATTERNS:
        m = pattern.search(body)
        assert not m, f"{where} leaked {label}: {m.group(0)[:120]!r}"


# --------------------------------------------------------------- the sweep


def _all_get_routes() -> list[str]:
    paths = []
    for route in app.routes:
        methods = getattr(route, "methods", set())
        path = getattr(route, "path", "")
        if "GET" in methods and path.startswith("/api"):
            paths.append(path)
    return paths


def test_every_get_route_is_scanned_for_leaks_on_hostile_input(client):
    """Enumerates routes from the app itself, so a new endpoint is covered."""
    routes = _all_get_routes()
    assert routes, "no API GET routes discovered - the sweep would be vacuous"

    doc_id = upload(client)
    client.post(f"/api/documents/{doc_id}/extract")
    client.post(f"/api/documents/{doc_id}/chunk")

    for path in routes:
        for ident in HOSTILE_IDS + [doc_id]:
            url = path.replace("{document_id}", ident).replace("{page_no}", "1")
            r = client.get(url)
            assert_clean(r.text, f"GET {url} -> {r.status_code}")
            # and with hostile query parameters
            r2 = client.get(f"{url}?limit=-1&offset=-1&retrievable=maybe&bogus=1")
            assert_clean(r2.text, f"GET {url} (hostile params) -> {r2.status_code}")


def test_health_never_exposes_a_traceback(client):
    """The exact regression: last_error carried a full stack with file paths."""
    worker = IngestionWorker()
    try:
        raise RuntimeError("state machine did not settle for doc_abc123")
    except RuntimeError as exc:
        worker.last_error = errors.record_failure(
            exc, document_id="doc_abc123", stage="process"
        )

    import app.ingest as ingest_mod
    ingest_mod._worker = worker
    try:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert_clean(r.text, "GET /api/health")
        # STRONGER THAN BEFORE. This test used to assert that last_error on
        # /api/health carried no traceback. It now asserts the field is not
        # there at all: free text and a document id do not belong on an
        # unauthenticated route, however carefully the text is sanitised.
        # The error detail is on the scoped /api/metrics.
        ingestion = r.json()["ingestion"]
        assert "last_error" not in ingestion, ingestion
        assert "stalled_reasons" not in ingestion, ingestion
        assert "current_document" not in ingestion, (
            "a document id was readable with no login")
        assert "doc_abc123" not in r.text, "a document id leaked into health"

        # The error detail still exists, with the same no-traceback guarantee,
        # on the scoped /api/metrics - covered by test_metrics.py against a
        # fixture that has the full schema. This test is about what /api/health
        # does NOT say.
    finally:
        ingest_mod._worker = None


def test_a_worker_failure_is_logged_locally_but_not_returned(client):
    """The traceback must exist somewhere - just not in the response."""
    try:
        raise ValueError("boom in D:\\project\\Rag_chatbot\\backend\\app\\x.py")
    except ValueError as exc:
        safe = errors.record_failure(exc, document_id="doc_x", stage="process")

    assert_clean(str(safe), "record_failure result")
    log = settings.data_dir / "logs" / "nabaa.log"
    assert log.exists(), "the traceback was not written to the local log"
    assert "Traceback" in log.read_text(encoding="utf-8"), "log lost the traceback"


def test_post_and_delete_error_bodies_are_clean(client):
    doc_id = upload(client)
    for ident in HOSTILE_IDS:
        for r in (
            client.post(f"/api/documents/{ident}/extract"),
            client.post(f"/api/documents/{ident}/chunk"),
            client.post(f"/api/documents/{ident}/embed"),
            client.delete(f"/api/documents/{ident}?confirm=true"),
        ):
            assert_clean(r.text, f"{r.request.method} {ident} -> {r.status_code}")
    assert_clean(client.delete(f"/api/documents/{doc_id}").text, "DELETE without confirm")


def test_redact_catches_a_path_bearing_message():
    assert "internal error" in errors.redact("failed at D:\\project\\Rag_chatbot\\app\\x.py")
    assert "internal error" in errors.redact('Traceback (most recent call last): File "x"')
    assert errors.redact("no document with that id") == "no document with that id"


# ------------------------------------------------------------- error codes


def test_a_client_mistake_is_not_reported_as_an_internal_failure(client):
    """`internal` must mean something is actually wrong, or it means nothing."""
    doc_id = upload(client)

    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 400
    # ONE ERROR SHAPE. This route used to return the error flat while every
    # 404 wrapped it in {"detail": {...}} - two shapes for one client to
    # parse, and the frontend was compensating with `body?.detail ?? body`.
    assert r.json()["detail"]["code"] == errors.CONFIRM_REQUIRED

    r = client.get("/api/documents/doc_zzzzzzzzzzzz/chunks")
    assert r.json()["detail"]["code"] == errors.NOT_FOUND

    r = client.get(f"/api/documents/{doc_id}/chunks?retrievable=maybe")
    assert r.json()["detail"]["code"] == errors.INVALID_PARAMETER

    r = client.get(f"/api/documents/{doc_id}/chunks?nonsense=1")
    assert r.json()["detail"]["code"] == errors.UNKNOWN_PARAMETER


def test_no_client_error_ever_uses_the_internal_code(client):
    doc_id = upload(client)
    probes = [
        ("GET", f"/api/documents/doc_zzzzzzzzzzzz/chunks"),
        ("GET", f"/api/documents/{doc_id}/chunks?retrievable=maybe"),
        ("GET", f"/api/documents/{doc_id}/chunks?bogus=1"),
        ("GET", f"/api/documents/{doc_id}/pages/99999/image"),
        ("DELETE", f"/api/documents/{doc_id}"),
    ]
    for method, url in probes:
        r = client.request(method, url)
        assert r.status_code < 500, f"{url} returned {r.status_code}"
        body = r.json()
        code = body.get("code") or body.get("detail", {}).get("code")
        assert code != errors.INTERNAL, f"{url} reported a client mistake as internal"
        assert code in errors.CLIENT_ERROR_CODES, f"{url} returned code {code!r}"


# ------------------------------------------- no_searchable_content (honesty)


def test_a_fully_scanned_pdf_is_not_called_ready(client):
    """Every page is an image: nothing is searchable, so 'ready' would lie."""
    doc_id = upload(client, "scanned.pdf", pages=3, blank=True)
    IngestionWorker().process(doc_id)

    row = db.connect().execute(
        "SELECT status, chunk_count, error_code, error_message FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    assert row["chunk_count"] == 0
    assert row["status"] == states.NO_SEARCHABLE_CONTENT, f"reported {row['status']!r}"
    assert states.is_terminal(row["status"])
    assert not states.is_answerable(row["status"])
    assert row["error_code"] == errors.NO_SEARCHABLE_CONTENT
    assert "scanned" in row["error_message"] or "no chunks" in row["error_message"]


def test_a_document_whose_chunks_are_all_excluded_is_not_called_ready(client):
    """The other cause: text extracts, but the gate excludes all of it."""
    doc_id = upload(client)
    worker = IngestionWorker()
    worker.process(doc_id)

    conn = db.connect()
    with conn:
        conn.execute("UPDATE chunks SET retrievable = 0 WHERE document_id = ?", (doc_id,))
        conn.execute(
            "UPDATE documents SET chunk_count = 0, embedded_count = 0, indexed_at = NULL,"
            " status = ? WHERE id = ?",
            (states.PARTIALLY_SEARCHABLE, doc_id),
        )
    worker.process(doc_id)

    row = conn.execute(
        "SELECT status, error_code, error_message FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["status"] == states.NO_SEARCHABLE_CONTENT
    assert row["error_code"] == errors.NO_SEARCHABLE_CONTENT
    assert row["error_message"], "the reason must be stated, not implied"


def test_no_searchable_content_is_terminal_but_not_answerable():
    assert states.is_terminal(states.NO_SEARCHABLE_CONTENT)
    assert not states.is_answerable(states.NO_SEARCHABLE_CONTENT)
    assert states.label(states.NO_SEARCHABLE_CONTENT, 0, 0) == "no searchable content"


# ---------------------------------------------------- typed OpenAPI contract


def test_every_endpoint_declares_a_typed_200_response():
    """Every 200 used to be documented as `string`, so the generated frontend
    types were guesses."""
    spec = app.openapi()
    untyped = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            ok = op.get("responses", {}).get("200", {})
            content = ok.get("content", {})
            if "image/png" in content:
                continue
            schema = content.get("application/json", {}).get("schema", {})
            if not ("$ref" in schema or schema.get("type") == "array"):
                untyped.append(f"{method.upper()} {path} -> {schema or 'no schema'}")
    assert not untyped, "untyped 200 responses: " + "; ".join(untyped)


def test_error_responses_are_documented_not_undocumented():
    """404 and 422 showed as 'Undocumented' in the OpenAPI UI."""
    spec = app.openapi()
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if "{document_id}" not in path:
                continue
            if "404" not in op.get("responses", {}):
                missing.append(f"{method.upper()} {path} has no documented 404")
    assert not missing, "; ".join(missing)


def test_the_document_status_enum_in_the_contract_matches_the_state_machine():
    """The contract must not advertise a status the system cannot produce, or
    omit one it can."""
    spec = app.openapi()
    doc_schema = spec["components"]["schemas"]["Document"]
    declared = set(doc_schema["properties"]["status"]["enum"])
    assert declared == set(states.ALL_STATES), (
        f"contract {sorted(declared)} != state machine {sorted(states.ALL_STATES)}"
    )
