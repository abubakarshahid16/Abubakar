"""Order 117 item 5, part 3: the deliverable, reminder, admin, template and
baseline-rule lists take an optional page and carry `total` beside their rows.

Without `limit`/`offset` every row comes back, as before. Invented rows only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, db, deliverables, paging, review
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "pages.sqlite")
    db.reset_connection()
    db.init_db()
    deliverables.ensure_schema()
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset({"doc_x"})
    )
    yield
    app.dependency_overrides.pop(access.current_scope, None)
    db.reset_connection()


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def test_page_body_keeps_the_rows_key_and_states_the_total():
    body = paging.page_body("rules", list(range(5)), 2, 2)
    assert body == {"rules": [2, 3], "total": 5, "limit": 2, "offset": 2}
    assert paging.page_body("rules", [1], None, 0)["rules"] == [1]


def test_templates_page_in_list_order_with_their_total():
    for i in range(5):
        review.create_template(
            {"name": f"Template {i}", "version": "1.0", "discipline": "civil"},
            created_by="admin-1",
        )
    client = _client()
    whole = client.get("/api/reviews/templates").json()
    assert whole["total"] == 5 and whole["limit"] is None
    ids = [t["id"] for t in whole["templates"]]
    pages = [
        client.get(f"/api/reviews/templates?limit=2&offset={o}").json()
        for o in (0, 2, 4)
    ]
    assert [t["id"] for p in pages for t in p["templates"]] == ids
    assert {p["total"] for p in pages} == {5}


def test_baseline_rules_and_deliverables_state_their_total():
    for i in range(3):
        review.create_baseline_rule(
            {
                "submittal_doc_type": f"T{i}",
                "submittal_discipline": "Civil",
                "baseline_doc_type": "Document",
                "baseline_discipline": "Civil",
                "priority": i,
                "active": True,
            }
        )
        deliverables.create(
            {
                "wbs_code": f"1.{i}",
                "title": f"Item {i}",
                "deliverable_type": "report",
                "org_wide": True,
            },
            created_by=None,
        )
    client = _client()
    rules = client.get("/api/reviews/baseline-rules?limit=1").json()
    assert len(rules["rules"]) == 1 and rules["total"] == 3
    items = client.get("/api/deliverables?limit=2&offset=2").json()
    assert len(items["deliverables"]) == 1 and items["total"] == 3
    for path, key in (
        ("/api/deliverables/alerts", "alerts"),
        ("/api/deliverables/expected", "deliverables"),
        ("/api/management/reminders", "reminders"),
    ):
        body = client.get(f"{path}?limit=1").json()
        assert body["total"] >= len(body[key]), path


def test_a_bad_page_is_refused():
    client = _client()
    for path in (
        "/api/reviews/templates",
        "/api/deliverables",
        "/api/management/reminders",
    ):
        for query in ("limit=0", "limit=1001", "offset=-1"):
            assert client.get(f"{path}?{query}").status_code == 422, (path, query)
