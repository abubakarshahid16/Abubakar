"""Order 117 item 5: the structured search no longer drops matches past 100.

It ended in `out[:100]`, so the 101st match vanished unannounced, the route had
no way to say so, and `/records` in chat reported "Found 100" for more. Now the
search returns every match in a stable order, the route pages it (100 when no
page is asked for, as before) and states the total. Invented records only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, chat_answers, db, risks, structured_search
from app.main import app

EVERYTHING = frozenset({"doc_a"})
MATCHES = 105


@pytest.fixture()
def many_risks(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "structured-total.sqlite")
    db.reset_connection()
    db.init_db()
    risks.ensure_schema()
    for i in range(MATCHES):
        risks.create(
            {
                "risk_type": "schedule",
                "title": f"Late package {i}",
                "description": "invented",
            }
        )
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=EVERYTHING, unrestricted=True
    )
    yield
    app.dependency_overrides.pop(access.current_scope, None)
    db.reset_connection()


def test_the_search_returns_every_match_in_a_stable_order(many_risks):
    found = structured_search.search(
        "late package",
        kind="risk",
        allowed_document_ids=EVERYTHING,
        include_unowned=True,
    )
    assert len(found) == MATCHES
    assert [r["id"] for r in found] == sorted(r["id"] for r in found)


def test_the_route_keeps_its_page_of_100_and_states_the_total(many_risks):
    client = TestClient(app, base_url="http://localhost")
    first = client.get("/api/search/structured?q=late%20package&kind=risk")
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["results"]) == 100
    assert (body["total"], body["limit"], body["offset"]) == (MATCHES, 100, 0)
    rest = client.get(
        "/api/search/structured?q=late%20package&kind=risk&offset=100"
    ).json()
    assert rest["total"] == MATCHES and len(rest["results"]) == MATCHES - 100
    ids = [r["id"] for r in body["results"] + rest["results"]]
    assert len(set(ids)) == MATCHES
    small = client.get(
        "/api/search/structured?q=late%20package&kind=risk&limit=7&offset=7"
    ).json()
    assert [r["id"] for r in small["results"]] == ids[7:14]


def test_chat_records_states_the_true_count(many_risks):
    answer = chat_answers.records(
        "late package", allowed_document_ids=EVERYTHING, include_unowned=True
    )
    assert answer["answer"].startswith(f"Found {MATCHES} workflow records")
    assert len(answer["records"]) == 10
