"""Order 88a: the risk register is read one page at a time, and the per-finding
rows written before #924 are shown as one row per document with a count.

The owner's register held 147,770 open "review" risks, one per finding; the
route built and sent every one (53 to 86 s) and the screen drew them all.
"""
from __future__ import annotations

import uuid

import pytest

from app import access, db, risks
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    risks.ensure_schema()
    from app import deliverables
    deliverables.ensure_schema()
    risks._page_cache.clear()
    yield
    db.reset_connection()


def _row(**kw):
    base = {"id": str(uuid.uuid4()), "risk_type": "review", "title": "Review response overdue",
            "description": "one finding", "severity": "minor", "status": "open",
            "deliverable_id": None, "document_id": "doc-a", "owner_user_id": None, "due_date": None,
            "source_finding_id": None, "created_at": "2026-09-30T00:00:00Z",
            "updated_at": "2026-09-30T00:00:00Z"}
    base.update(kw)
    return base


def _insert(rows):
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO risks (" + ",".join(risks._COLUMNS) + ") VALUES ("
            + ",".join(":" + c for c in risks._COLUMNS) + ")", rows)
    risks._page_cache.clear()


def test_per_finding_rows_from_before_924_read_as_one_row_per_document():
    _insert([_row(source_finding_id=f"f{i}", document_id="doc-a",
                  severity="critical" if i == 3 else "minor") for i in range(30)]
            + [_row(source_finding_id=f"g{i}", document_id="doc-b") for i in range(5)]
            + [_row(risk_type="schedule", title="Overdue deliverable", document_id=None)])
    page = risks.list_page()
    assert page["total"] == 3
    grouped = {r["document_id"]: r for r in page["risks"] if r["finding_count"] > 1}
    assert grouped["doc-a"]["finding_count"] == 30
    assert grouped["doc-a"]["severity"] == "critical"          # the worst of the group
    assert grouped["doc-a"]["source_finding_id"] is None       # not one finding
    assert "30 findings on this document" in grouped["doc-a"]["description"]
    assert grouped["doc-b"]["finding_count"] == 5
    # the stored rows are untouched
    assert len(risks.list_items()) == 36


def test_a_page_is_at_most_the_limit_and_the_total_counts_every_row():
    _insert([_row(risk_type="schedule", document_id=None, title=f"r{i}",
                  updated_at=f"2026-10-01T00:{i:02d}:00Z") for i in range(60)])
    first = risks.list_page(limit=50)
    assert len(first["risks"]) == 50 and first["total"] == 60
    assert first["risks"][0]["title"] == "r59"                 # newest first
    rest = risks.list_page(limit=50, offset=50)
    assert len(rest["risks"]) == 10
    assert {r["id"] for r in first["risks"]}.isdisjoint({r["id"] for r in rest["risks"]})
    assert risks.list_page(limit=10_000)["limit"] == risks.MAX_PAGE_SIZE


def test_the_page_never_shows_a_document_the_caller_may_not_read():
    _insert([_row(source_finding_id=f"f{i}", document_id="doc-a") for i in range(4)]
            + [_row(source_finding_id=f"g{i}", document_id="doc-secret") for i in range(4)])
    page = risks.list_page(allowed_document_ids=frozenset({"doc-a"}))
    assert [r["document_id"] for r in page["risks"]] == ["doc-a"] and page["total"] == 1
    assert risks.list_page(allowed_document_ids=frozenset())["total"] == 0


def test_a_new_risk_shows_on_the_next_read_although_pages_are_cached():
    risks.create({"risk_type": "schedule", "title": "first", "description": "x"})
    assert risks.list_page()["total"] == 1
    risks.create({"risk_type": "schedule", "title": "second", "description": "x"})
    assert risks.list_page()["total"] == 2


def test_the_route_returns_a_page_and_the_total():
    from fastapi.testclient import TestClient

    from app.main import app

    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, uploaded_at)"
                     " VALUES ('doc-a', 'a.pdf', 'x', 1, '/x', '2026-09-01T00:00:00Z')")
    _insert([_row(risk_type="schedule", document_id="doc-a", title=f"r{i}") for i in range(3)])
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = client.get("/api/risks", params={"limit": 2}).json()
        assert len(body["risks"]) == 2 and body["total"] == 3 and body["limit"] == 2
        assert client.get("/api/risks", params={"limit": 0}).status_code == 422
