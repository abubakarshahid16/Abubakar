"""The transport: inert by default, allowlisted when live, audited when used.

NO TEST HERE MAKES A NETWORK CALL. The two that exercise the request path
substitute a fake `httpx.Client`, so the whole file runs air-gapped - which is
the deployment target and also the only honest way to test a thing whose
failure mode is "it reached the internet when it should not have".

THE PROPERTY THIS FILE EXISTS FOR: on the day the client approves egress,
flipping two flags is the entire change. So "flags off" must be provably
inert - no client, no request, no partial behaviour - and "flags on" must
already work end to end. Both halves are asserted.
"""

from __future__ import annotations

import sqlite3
from typing import ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db, market_providers, market_transport
from app.config import settings
from app.db import connect
from app.main import app


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Its own database. This suite writes audit rows and must not touch the
    developer's - a test that used the real one would pass only here."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    market_providers.reset_rate_limits()
    yield
    db.reset_connection()
    market_providers.reset_rate_limits()


@pytest.fixture
def live(monkeypatch):
    """Both flags on. Tier 1 stays unconfigured - no vendor is chosen."""
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 0)
    monkeypatch.setattr(settings, "market_search_api_key", "")
    monkeypatch.setattr(settings, "market_search_provider", "")
    monkeypatch.setattr(settings, "market_search_endpoint", "")
    market_providers.reset_rate_limits()


# ------------------------------------------------- OFF is the absence of one


@pytest.mark.parametrize("live_flag,egress_flag", [
    (False, False), (True, False), (False, True),
])
def test_no_transport_exists_unless_both_flags_are_true(monkeypatch, live_flag,
                                                        egress_flag):
    """OFF MEANS NO CLIENT OBJECT, not an unused one.

    All three not-both combinations, because a transport built on one flag
    would pass a test that only checked (False, False).
    """
    monkeypatch.setattr(settings, "market_live_enabled", live_flag)
    monkeypatch.setattr(settings, "market_allow_public_egress", egress_flag)

    assert market_transport.available() is False
    assert market_transport.transport() is None


def test_a_transport_exists_when_both_flags_are_true(live):
    assert market_transport.available() is True
    assert callable(market_transport.transport())


def test_the_route_sends_nothing_with_the_flags_off(monkeypatch):
    """END TO END, through the real route. With the flags off the samples come
    back and `httpx.Client` is never constructed - asserted by making its
    construction an error."""
    def explode(*a, **k):
        raise AssertionError("a client was constructed with egress disabled")

    monkeypatch.setattr(httpx, "Client", explode)
    client = TestClient(app)

    body = client.post("/api/market/search",
                       json={"phrase": "what is ISO 12944"}).json()
    assert body["enabled"] is False
    assert body["rows"], "the flag-off answer is still the labelled samples"
    assert all(r["is_sample"] for r in body["rows"])
    assert body["failure"] is None


def test_a_retained_fetch_refuses_after_the_flags_go_off(live, monkeypatch):
    """Belt and braces on gate 1. A caller holding a reference to the fetch
    across a settings change must not keep sending."""
    fetch = market_transport.transport()
    assert fetch is not None

    monkeypatch.setattr(settings, "market_allow_public_egress", False)
    with pytest.raises(market_transport.TransportRefused, match="disabled"):
        fetch("https://api.openalex.org/works?search=x", {}, 1.0)


# ------------------------------------------------- the allowlist, at the socket


class _FakeResponse:
    """`request.url` is THE URL THAT WAS ASKED FOR, query string and all.

    It used to be a fixed `https://<host>/x`, and that unfaithfulness hid a
    mutation: putting the full URL into the HTTP error message instead of just
    the host did not fail the test, because the fake's URL had no query string
    for a secret to hide in. A fake that differs from the real client in the
    exact dimension under test proves nothing - the same failure as a
    fabricated fixture agreeing with itself.
    """

    def __init__(self, payload, url, status=200, body=b"{}"):
        self._payload = payload
        self.status_code = status
        self.content = body
        self.request = httpx.Request("GET", url)

    def json(self):
        return self._payload


class _FakeClient:
    """Records what would have been requested. Constructs no socket."""

    calls: ClassVar[list[tuple[str, dict]]] = []
    payload: ClassVar[object] = {"results": []}
    status: ClassVar[int] = 200
    body: ClassVar[bytes] = b"{}"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).init_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        type(self).calls.append((url, dict(headers or {})))
        return _FakeResponse(type(self).payload, url, type(self).status,
                             type(self).body)


@pytest.fixture
def fake_http(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.payload = {"results": []}
    _FakeClient.status = 200
    _FakeClient.body = b"{}"
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return _FakeClient


def test_a_host_outside_the_allowlist_never_reaches_the_client(live, fake_http):
    """GATE 2. The provider checks the URL it builds; this is the check
    immediately before the request, which a bug in a provider cannot bypass."""
    fetch = market_transport.transport()
    with pytest.raises(market_providers.HostNotAllowed):
        fetch("https://evil.test/search?q=x", {}, 1.0)
    assert fake_http.calls == [], "a refused host still reached the client"


def test_an_allowlisted_host_does_reach_the_client(live, fake_http):
    fetch = market_transport.transport()
    fetch("https://api.openalex.org/works?search=iso%2012944", {}, 2.0)
    assert len(fake_http.calls) == 1
    url, headers = fake_http.calls[0]
    assert url.startswith("https://api.openalex.org/")
    assert "rag-intelligence" in headers["User-Agent"]


def test_the_client_follows_no_redirects_and_carries_no_cookies(live,
                                                                fake_http):
    """A 302 is a host the allowlist never saw. Following one would move the
    destination outside the check that had just passed."""
    fetch = market_transport.transport()
    fetch("https://en.wikipedia.org/w/api.php?action=query", {}, 1.0)
    kwargs = fake_http.init_kwargs
    assert kwargs["follow_redirects"] is False
    assert kwargs["cookies"] is None
    assert kwargs["trust_env"] is False


def test_the_user_agent_names_the_software_and_not_the_client(live, fake_http):
    """OpenAlex and Wikipedia both ask a caller to identify itself. It must not
    identify the CLIENT: which organisation is researching which standards is
    exactly the inference this product exists to prevent."""
    fetch = market_transport.transport()
    fetch("https://api.openalex.org/works?search=x", {}, 1.0)
    agent = fake_http.calls[0][1]["User-Agent"]
    for leak in ("aramco", "nabaa", "saudi", "@"):
        assert leak not in agent.lower(), agent


def test_an_http_error_names_the_host_and_never_the_url(live, fake_http):
    """A URL can carry a key in a query parameter and this string reaches a
    log, so the message carries the host only."""
    fake_http.status = 503
    fetch = market_transport.transport()
    with pytest.raises(httpx.HTTPStatusError) as caught:
        fetch("https://api.openalex.org/works?search=x&secret=abc123", {}, 1.0)
    assert "secret=abc123" not in str(caught.value), str(caught.value)
    assert "api.openalex.org" in str(caught.value)


def test_an_oversized_response_is_refused_rather_than_read(live, fake_http):
    """An unbounded read on a 15 W machine holding a client's corpus is a
    denial of service waiting for a bad day. The cap is asserted rather than
    described - and now that the fake carries a real body, it can be."""
    fake_http.body = b"x" * (market_transport.MAX_RESPONSE_BYTES + 1)
    fetch = market_transport.transport()
    with pytest.raises(market_transport.TransportRefused, match="over the"):
        fetch("https://api.openalex.org/works?search=x", {}, 1.0)


# ------------------------------------------------------------- the audit rows


def _audit_rows() -> list[sqlite3.Row]:
    return list(connect().execute(
        "SELECT * FROM audit_events WHERE action = 'market.outbound_query'"
        " ORDER BY id"))


def test_no_audit_row_is_written_when_nothing_was_sent(monkeypatch):
    """The flags are off, no query left, so there is nothing to record. An
    audit table that logs queries that never happened is as misleading as one
    that misses queries that did."""
    TestClient(app).post("/api/market/search", json={"phrase": "iso 12944"})
    assert _audit_rows() == []


def test_one_audit_row_per_outbound_query_is_persisted(live, fake_http):
    """The rows `market_providers` builds are actually STORED now. They were
    returned and dropped before a transport existed, and an audit trail nobody
    persists is not an audit trail."""
    fake_http.payload = {
        "results": [], "query": {"search": []},
    }
    client = TestClient(app)
    body = client.post("/api/market/search",
                       json={"phrase": "what is ISO 12944"}).json()

    assert body["tiers_attempted"] == ["literature", "reference"]
    rows = _audit_rows()
    assert len(rows) == 2, [dict(r) for r in rows]
    assert {r["resource_id"] for r in rows} == {"literature", "reference"}
    for row in rows:
        assert row["action"] == "market.outbound_query"
        assert row["resource_type"] == "market_query"
        assert row["outcome"] == "ok"
        # The phrase VERBATIM - the one question this row exists to answer is
        # what exactly left the machine.
        assert row["detail"] == "iso 12944"
        assert row["at"].endswith("Z")


def test_a_failed_tier_is_audited_as_an_error_not_omitted(live, fake_http):
    """A query that left and failed still left. Recording only successes would
    make the trail useless for the question it exists for."""
    fake_http.status = 500
    TestClient(app).post("/api/market/search", json={"phrase": "iso 12944"})

    rows = _audit_rows()
    assert len(rows) == 2, [dict(r) for r in rows]
    assert {r["outcome"] for r in rows} == {"error"}


def test_the_audit_row_never_carries_document_text_or_a_filename(live,
                                                                 fake_http):
    """The audit table is, in this codebase's own words, the one most likely to
    be exported. It records the phrase because the phrase already left the
    machine; it must never acquire anything that did not."""
    fake_http.payload = {"results": [], "query": {"search": []}}
    TestClient(app).post(
        "/api/market/search",
        json={"phrase": "compare design requirements in doc13.pdf and doc16.pdf"})

    for row in _audit_rows():
        blob = " ".join(str(v) for v in tuple(row))
        for leak in ("doc13", "doc16", ".pdf"):
            assert leak not in blob, f"{leak!r} reached the audit row: {blob}"


def test_an_unwritable_audit_does_not_fail_the_request(live, fake_http,
                                                       monkeypatch):
    """Same discipline as `admin._audit`. A request that has already been made
    must not be reported as failed because a log row could not be stored - the
    query left either way, and a 500 here would tell the reader the opposite.
    """
    fake_http.payload = {"results": [], "query": {"search": []}}
    from app import main as main_mod

    def broken():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(main_mod, "connect", broken)
    response = TestClient(app).post("/api/market/search",
                                    json={"phrase": "iso 12944"})
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True
