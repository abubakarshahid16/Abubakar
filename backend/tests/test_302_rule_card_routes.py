"""Order 302.4: the rule-approval screen's routes. Super user only, audited, a stale screen writes nothing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import admin as admin_mod
from app import db
from app.main import app
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

CARD = "PSV-24"
ADMIN = {"id": None, "email": "engineer@example.test"}


@pytest.fixture()
def client():
    app.dependency_overrides[admin_mod.current_admin] = lambda: ADMIN
    yield TestClient(app)


def _seen(client, card=CARD):
    body = client.get(f"/api/rule-cards/{card}").json()
    return {"version": body["version"], "content_hash": body["content_hash"]}


def _audit_rows():
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT action, outcome, resource_id, detail, actor_username FROM audit_events"
            " WHERE action LIKE 'rule_card.%' ORDER BY id"
        )
    ]


def test_the_listing_counts_states_against_each_types_own_cards(client):
    body = client.get("/api/rule-cards").json()
    psv = body["Pressure Safety Valve"]
    assert psv["total"] == 47 and sum(psv["counts"].values()) == 47
    assert psv["counts"]["draft"] == 2 and psv["counts"]["approved"] == 0


def test_a_card_opens_with_its_cases_and_state(client):
    body = client.get(f"/api/rule-cards/{CARD}").json()
    assert body["state"] == "tested" and body["version"] == 1
    assert {c["case"] for c in body["cases"]} >= {
        "meets",
        "breaks",
        "unclear",
        "at the limit",
    }
    assert all(c["passed"] for c in body["cases"])
    assert client.get("/api/rule-cards/NO-SUCH").status_code == 404


def test_approve_writes_who_and_when_and_an_audit_row(client):
    r = client.post(
        f"/api/rule-cards/{CARD}/decision",
        json={"decision": "approved", **_seen(client)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["state"], body["decided_by"]) == ("approved", "engineer@example.test")
    assert body["decided_at"].endswith("Z")
    assert _audit_rows() == [
        {
            "action": "rule_card.decision",
            "outcome": "ok",
            "resource_id": CARD,
            "detail": "approved v1",
            "actor_username": "engineer@example.test",
        }
    ]


def test_a_stale_screen_is_409_writes_nothing_and_is_audited_as_refused(client):
    r = client.post(
        f"/api/rule-cards/{CARD}/decision",
        json={"decision": "approved", "version": 1, "content_hash": "0" * 64},
    )
    assert r.status_code == 409
    assert client.get(f"/api/rule-cards/{CARD}").json()["state"] == "tested"
    assert [a["outcome"] for a in _audit_rows()] == ["refused"]


def test_a_draft_card_cannot_be_approved(client):
    r = client.post(
        "/api/rule-cards/PSV-05/decision",
        json={"decision": "approved", **_seen(client, "PSV-05")},
    )
    assert r.status_code == 422 and "only a tested card" in r.text


def test_an_edit_makes_a_new_version_without_a_decision(client):
    client.post(
        f"/api/rule-cards/{CARD}/decision",
        json={"decision": "approved", **_seen(client)},
    )
    r = client.post(
        f"/api/rule-cards/{CARD}/edit",
        json={"changes": {"severity": "minor"}, **_seen(client)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["version"], body["state"], body["decided_by"]) == (2, "tested", None)
    assert [a["action"] for a in _audit_rows()] == [
        "rule_card.decision",
        "rule_card.edit",
    ]


def test_an_edit_the_rule_does_not_allow_is_422(client):
    r = client.post(
        f"/api/rule-cards/{CARD}/edit",
        json={"changes": {"values": ["x"]}, **_seen(client)},
    )
    assert r.status_code == 422


def test_nobody_signed_in_writes_nothing():
    app.dependency_overrides[admin_mod.current_admin] = lambda: None
    c = TestClient(app)
    seen = c.get(f"/api/rule-cards/{CARD}").json()
    r = c.post(
        f"/api/rule-cards/{CARD}/decision",
        json={
            "decision": "approved",
            "version": 1,
            "content_hash": seen["content_hash"],
        },
    )
    assert r.status_code == 422 and "nobody is signed in" in r.text
    assert (
        db.connect().execute("SELECT COUNT(*) FROM rule_card_versions").fetchone()[0]
        == 0
    )


def test_a_user_who_is_not_a_super_user_gets_the_admin_404(monkeypatch):
    from app import access
    from app.config import settings

    app.dependency_overrides.pop(admin_mod.current_admin, None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    r = TestClient(app).get("/api/rule-cards")
    assert r.status_code in (401, 404)
