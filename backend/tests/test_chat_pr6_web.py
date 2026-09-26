"""Chat redesign PR 6 (owner order 2026-09-26): the web lane in chat.

What these tests hold, each against the transport itself:
  * off unless `chat_web_enabled` AND the market lane's two egress flags;
  * a web question produces a consent turn and SENDS NOTHING;
  * "Search once" sends only the whitelisted phrase built from the reader's
    one stored question - no filename, no history, no document text, and
    nothing the client supplies;
  * every query is audited; a search runs once;
  * the answer cites the web as the web.

No network: the transport is replaced by a recorder.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat_web, db, intent, market_providers, market_transport
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse

QUESTION = "is there a newer edition of ISO 12944 online"


@pytest.fixture
def sent(monkeypatch):
    """Every URL the transport was asked to fetch. Nothing leaves the test."""
    urls: list[str] = []

    def fetch(url, headers, timeout):
        urls.append(url)
        if "openalex" in url:
            return {"results": [{
                "display_name": "ISO 12944 coating edition review",
                "publication_date": "2025-01-01",
                "primary_location": {"landing_page_url": "https://example.org/iso-12944",
                                     "source": {"display_name": "Example Journal"}}}]}
        return {}

    monkeypatch.setattr(market_transport, "transport", lambda: fetch)
    # the market lane's own rate limit is per process; each test starts fresh
    market_providers.reset_rate_limits()
    yield urls
    market_providers.reset_rate_limits()


@pytest.fixture
def lane_on(monkeypatch):
    monkeypatch.setattr(settings, "chat_web_enabled", True)
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)


def _ask(client, convo, question, **extra):
    return client.post(f"/api/conversations/{convo}/ask", json={"question": question, **extra}).json()


def _audit_rows() -> list:
    return db.connect().execute(
        "SELECT action, detail FROM audit_events WHERE resource_type LIKE '%market%' OR action LIKE '%market%'"
    ).fetchall()


# ---------------------------------------------------------------- routing

def test_web_words_route_to_the_web_only_when_the_reader_switched_web_on():
    assert intent.route(QUESTION, web_enabled=True)["kind"] == "web"
    assert intent.route(QUESTION, web_enabled=False)["kind"] != "web"
    assert intent.route("what does the datasheet say about hydrotest", web_enabled=True)["kind"] != "web"


# ---------------------------------------------------------------- consent

def test_a_web_question_asks_first_and_sends_nothing(lane_on, sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, QUESTION, web=True)
    assert body["answer_type"] == "web_consent"
    assert body["answer_kind"] == "web"
    assert sent == [], "a consent turn sent something"
    assert "12944" in body["answer"] and "Search once?" in body["answer"]


def test_with_the_lane_off_no_search_is_offered(sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, QUESTION, web=True)
    assert body["answer_type"] == "web_consent"
    assert "can't check the web" in body["answer"]
    r = client.post(f"/api/conversations/{convo}/messages/{body['assistant_message']['id']}/web-search")
    assert r.status_code == 409
    assert sent == []


def test_web_is_not_offered_by_default():
    body = TestClient(app).get("/api/chat/models").json()
    assert body["web_available"] is False
    assert body["web_reason"]


# ------------------------------------------------------------ search once

def test_search_once_sends_only_the_phrase_and_cites_the_web(lane_on, sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    consent = _ask(client, convo, QUESTION, web=True)
    r = client.post(f"/api/conversations/{convo}/messages/{consent['assistant_message']['id']}/web-search")
    assert r.status_code == 200, r.text
    message = r.json()
    assert message["answer_type"] == "web"
    assert message["sources"] and all(s["kind"] == "web" for s in message["sources"])
    assert message["sources"][0]["url"] == "https://example.org/iso-12944"
    assert all(s["document_id"] is None for s in message["sources"])
    assert "not your documents" in message["text"]
    assert "only this phrase was sent" in message["used_line"]
    assert sent, "the approved search did not run"
    for url in sent:
        assert "12944" in url
        assert "newer" not in url.lower() or "edition" in url.lower()


def test_the_phrase_carries_no_filename_no_history_and_no_document_text(lane_on, sent):
    client = TestClient(app)
    doc = upload(client)
    name = db.connect().execute("SELECT filename FROM documents WHERE id = ?", (doc,)).fetchone()[0]
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "what is the dry film thickness for coating system no. 1")  # history
    stem = name.rsplit(".", 1)[0].lower()
    # typed WITHOUT its extension, the way a reader names a file in a sentence:
    # only the caller's filename list can strip it (market_phrase)
    consent = _ask(client, convo, f"is there a newer edition of ISO 12944 online, and of {stem}", web=True)
    client.post(f"/api/conversations/{convo}/messages/{consent['assistant_message']['id']}/web-search")
    assert sent
    for url in sent:
        low = url.lower()
        assert stem not in low, "a corpus filename left the machine"
        assert "thickness" not in low and "coating+system" not in low, "the history left the machine"


def test_every_search_is_audited_with_the_phrase_that_left(lane_on, sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    consent = _ask(client, convo, QUESTION, web=True)
    before = len(_audit_rows())
    client.post(f"/api/conversations/{convo}/messages/{consent['assistant_message']['id']}/web-search")
    rows = _audit_rows()
    assert len(rows) > before
    assert any("12944" in (r["detail"] or "") for r in rows[before:])


def test_a_consent_runs_one_search_only(lane_on, sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    consent = _ask(client, convo, QUESTION, web=True)
    url = f"/api/conversations/{convo}/messages/{consent['assistant_message']['id']}/web-search"
    assert client.post(url).status_code == 200
    count = len(sent)
    assert client.post(url).status_code == 409
    assert len(sent) == count


def test_only_a_consent_turn_can_be_searched(lane_on, sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "hi")
    r = client.post(f"/api/conversations/{convo}/messages/{body['assistant_message']['id']}/web-search")
    assert r.status_code == 404
    assert sent == []


def test_the_phrase_is_rebuilt_from_the_stored_question_not_the_consent_copy(lane_on, sent):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    consent = _ask(client, convo, QUESTION, web=True)
    # tamper with what the consent turn stored: it must not be what is sent
    conn = db.connect()
    with conn:
        conn.execute("UPDATE messages SET payload = json_set(payload, '$.web_phrase', 'secret plant name') "
                     "WHERE id = ?", (consent["assistant_message"]["id"],))
    r = client.post(f"/api/conversations/{convo}/messages/{consent['assistant_message']['id']}/web-search")
    assert r.status_code == 200, r.text
    assert sent and all("secret" not in u.lower() for u in sent)


def test_a_question_with_nothing_safe_to_send_offers_no_search(lane_on, sent):
    # a quoted span never reaches a payload (market_phrase), and nothing else is left
    body = chat_web.consent('"ZQX plant"', allowed_document_ids=frozenset())
    assert body["web_phrase"] is None
    assert "won't search" in body["answer"]
    assert sent == []


def test_a_search_every_provider_refused_can_be_tried_again(lane_on, monkeypatch):
    calls = []

    def failing(url, headers, timeout):
        calls.append(url)
        raise RuntimeError("provider down")

    monkeypatch.setattr(market_transport, "transport", lambda: failing)
    market_providers.reset_rate_limits()
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    consent = _ask(client, convo, QUESTION, web=True)
    url = f"/api/conversations/{convo}/messages/{consent['assistant_message']['id']}/web-search"
    first = client.post(url)
    assert first.status_code == 200 and "try the search again" in first.json()["text"]
    market_providers.reset_rate_limits()
    assert client.post(url).status_code == 200, "a failed search locked the reader out"
    market_providers.reset_rate_limits()


def test_the_chat_switch_alone_sends_nothing(monkeypatch, sent):
    """chat_web_enabled on, but the market lane's egress flags off."""
    monkeypatch.setattr(settings, "chat_web_enabled", True)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, QUESTION, web=True)
    assert "can't check the web" in body["answer"]
    r = client.post(f"/api/conversations/{convo}/messages/{body['assistant_message']['id']}/web-search")
    assert r.status_code == 409
    assert sent == []


def test_the_market_flags_alone_do_not_open_chat_to_the_web(monkeypatch, sent):
    """Egress permitted for the market screen does not switch the chat lane on."""
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, QUESTION, web=True)
    assert "switched off for chat" in body["answer"]
    r = client.post(f"/api/conversations/{convo}/messages/{body['assistant_message']['id']}/web-search")
    assert r.status_code == 409
    assert sent == []
    assert TestClient(app).get("/api/chat/models").json()["web_available"] is False
