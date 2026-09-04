"""API correctness: an unknown request must never look like a valid one."""
import io

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api_utils import MAX_LIMIT
from app.config import settings
from app.main import app

UNKNOWN_IDS = [
    "doc_zzzzzzzzzzzz",
    "not-an-id",
    "x" * 500,
    "🔥emoji",
    "'; DROP TABLE documents; --",
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


def make_doc(client) -> str:
    import fitz
    path = settings.upload_dir.parent / "s.pdf"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"Section {i+1}.0 Scope")
        page.insert_text((72, 130), "The vibration limit shall not exceed three point zero.")
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={"file": ("s.pdf", fh, "application/pdf")})
    return r.json()["document"]["id"]


# ------------------------------------------------------------------ P1-1


@pytest.mark.parametrize("bad_id", UNKNOWN_IDS)
def test_get_endpoints_404_on_unknown_ids(client, bad_id):
    """GET returned 200 [] - indistinguishable from a real empty document."""
    for path in ("chunks", "pages", "excluded"):
        r = client.get(f"/api/documents/{bad_id}/{path}")
        assert r.status_code == 404, f"{path} returned {r.status_code} for {bad_id!r}"


def test_get_and_post_agree_on_unknown_ids(client):
    bad = "doc_zzzzzzzzzzzz"
    assert client.get(f"/api/documents/{bad}/chunks").status_code == 404
    assert client.post(f"/api/documents/{bad}/extract").status_code == 404
    assert client.post(f"/api/documents/{bad}/chunk").status_code == 404


# ------------------------------------------------------------ P1-2 / P1-3


def test_absurd_limit_is_422_not_500(client):
    doc = make_doc(client)
    r = client.get(f"/api/documents/{doc}/chunks?limit=999999999999999999999")
    assert r.status_code == 422, f"got {r.status_code}"


def test_limit_is_capped(client):
    doc = make_doc(client)
    assert client.get(f"/api/documents/{doc}/chunks?limit={MAX_LIMIT + 1}").status_code == 422
    assert client.get(f"/api/documents/{doc}/chunks?limit={MAX_LIMIT}").status_code == 200


def test_negative_limit_is_422(client):
    doc = make_doc(client)
    assert client.get(f"/api/documents/{doc}/chunks?limit=-1").status_code == 422
    assert client.get(f"/api/documents/{doc}/chunks?limit=0").status_code == 422


# ------------------------------------------------------------------ P1-4


def test_negative_offset_is_422(client):
    doc = make_doc(client)
    assert client.get(f"/api/documents/{doc}/chunks?offset=-1").status_code == 422


# ------------------------------------------------------------ P1-5 / P1-6


def test_unknown_query_params_are_rejected(client):
    """A client that mistypes a filter must not believe it filtered."""
    doc = make_doc(client)
    r = client.get(f"/api/documents/{doc}/chunks?retreivable=false")   # typo
    assert r.status_code == 422
    assert "retreivable" in r.text


def test_retrievable_filter_accepts_only_three_values(client):
    doc = make_doc(client)
    for value in ("true", "false", "all"):
        assert client.get(f"/api/documents/{doc}/chunks?retrievable={value}").status_code == 200
    assert client.get(f"/api/documents/{doc}/chunks?retrievable=maybe").status_code == 422


def test_excluded_chunks_are_reachable_and_carry_their_reason(client):
    doc = make_doc(client)
    client.post(f"/api/documents/{doc}/extract")
    client.post(f"/api/documents/{doc}/chunk")

    all_r = client.get(f"/api/documents/{doc}/chunks?retrievable=all&limit=200").json()
    yes = client.get(f"/api/documents/{doc}/chunks?retrievable=true&limit=200").json()
    no = client.get(f"/api/documents/{doc}/chunks?retrievable=false&limit=200").json()

    assert all_r["total_matching"] == yes["total_matching"] + no["total_matching"]
    for c in no["chunks"]:
        assert c["retrievable"] is False
        assert "quality_flags" in c
    for c in yes["chunks"]:
        assert c["retrievable"] is True


# ------------------------------------------------------------------ P1-7


def test_chunk_short_circuits_on_a_second_call(client):
    """/extract resumes rather than redoing work; /chunk must match."""
    doc = make_doc(client)
    client.post(f"/api/documents/{doc}/extract")

    first = client.post(f"/api/documents/{doc}/chunk").json()
    assert first["skipped"] is False
    assert first["chunks_this_run"] > 0

    second = client.post(f"/api/documents/{doc}/chunk").json()
    assert second["skipped"] is True
    assert second["chunks_this_run"] == 0
    assert second["chunks_per_sec"] is None

    forced = client.post(f"/api/documents/{doc}/chunk?force=true").json()
    assert forced["skipped"] is False


# --------------------------------------------------------------- security


def test_security_headers_are_present(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_the_launcher_suppresses_the_uvicorn_server_banner():
    """uvicorn writes `Server: uvicorn` at the HTTP protocol layer, AFTER the
    ASGI app returns, so response middleware cannot remove it - and TestClient
    never goes through that layer, which is how this was reported fixed while
    still being sent over the wire.

    The only place it can be suppressed is the server config, so that is what
    is asserted here.
    """
    import inspect

    import run

    source = inspect.getsource(run.main)
    assert "server_header=False" in source, (
        "run.py must start uvicorn with server_header=False"
    )
    assert "settings.host" in source, "the launcher must bind the configured loopback host"


# ------------------------------------------------------------ page images


def test_page_image_renders_and_is_cached(client):
    doc = make_doc(client)
    client.post(f"/api/documents/{doc}/extract")
    r = client.get(f"/api/documents/{doc}/pages/1/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    # second call is served from cache and is identical
    again = client.get(f"/api/documents/{doc}/pages/1/image")
    assert again.content == r.content


def test_page_image_404s_out_of_range(client):
    doc = make_doc(client)
    client.post(f"/api/documents/{doc}/extract")
    assert client.get(f"/api/documents/{doc}/pages/9999/image").status_code == 404
    assert client.get(f"/api/documents/{doc}/pages/0/image").status_code == 404
