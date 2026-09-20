"""The third outbound lane, held to the other two lanes' rules.

No test here touches a network. `httpx.Client` is replaced with a fake that
records what it was constructed with and what it was asked to post, which is
the whole point: the assertions are about what would have left the machine.
"""

from __future__ import annotations

import logging
from typing import ClassVar

import httpx
import pytest

from app import reader_api, reader_transport
from app.reader_api import API_KEY_ENV, ReaderRefused, ReaderSettings

URL = "https://api.anthropic.com/v1/messages"
HEADERS = {"x-api-key": "sk-test-not-real", "anthropic-version": "2023-06-01",
           "content-type": "application/json"}
BODY = {"model": "claude-test", "max_tokens": 8, "temperature": 0,
        "messages": [{"role": "user", "content": "one sentence"}]}


class FakeResponse:
    def __init__(self, status=200, payload=None, content=None):
        self.status_code = status
        self._payload = payload if payload is not None else {
            "content": [{"type": "text", "text": '{"proposals": []}'}],
            "usage": {"input_tokens": 40, "output_tokens": 7},
        }
        self.content = content if content is not None else b"x" * 64
        self.request = httpx.Request("POST", URL)

    def json(self):
        return self._payload


class FakeClient:
    """Records construction kwargs and the one post. Returns what the test
    put in `FakeClient.response`."""
    seen: ClassVar[dict] = {}
    response: ClassVar[FakeResponse] = FakeResponse()

    def __init__(self, **kwargs):
        FakeClient.seen = {"client_kwargs": kwargs}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, content=None):
        FakeClient.seen.update({"url": url, "headers": headers, "content": content})
        return FakeClient.response


@pytest.fixture
def lane_open(monkeypatch):
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "1")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "1")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    FakeClient.response = FakeResponse()
    FakeClient.seen = {}


# ------------------------------------------------------------- gate 1

@pytest.fixture
def lane_shut(monkeypatch):
    """Both flags absent from the environment AND false on the settings
    model. The second half is not optional: `ReaderSettings.from_env` falls
    back to `backend/.env` when the environment says nothing, so a test that
    only cleared the environment would pass or fail according to what the
    developer running it has in that file. It did - the day both flags were
    switched on there for the first real call, these two tests went red."""
    from app.config import settings as live
    monkeypatch.delenv("STANDARDS_READER_ENABLED", raising=False)
    monkeypatch.delenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", raising=False)
    monkeypatch.setattr(live, "standards_reader_enabled", False)
    monkeypatch.setattr(live, "standards_reader_allow_public_egress", False)


def test_with_the_flags_off_there_is_no_transport_at_all(lane_shut):
    """OFF MEANS NO CLIENT EXISTS. None, not a callable that refuses."""
    assert reader_transport.available() is False
    assert reader_transport.transport() is None


def test_one_flag_is_not_enough(lane_shut, monkeypatch):
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "1")
    assert reader_transport.transport() is None


def test_a_transport_kept_across_a_settings_change_still_refuses(monkeypatch, lane_open):
    """Belt and braces: the reference outlives the flags."""
    send = reader_transport.transport()
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "0")
    with pytest.raises(reader_transport.TransportRefused):
        send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    assert "url" not in FakeClient.seen, "a request was posted after egress was withdrawn"


# ------------------------------------------------------------- gate 2

@pytest.mark.parametrize("url", [
    "https://evil.test?@api.anthropic.com/v1/messages",
    "https://api.anthropic.com.evil.test/v1/messages",
    "http://api.anthropic.com/v1/messages",
])
def test_the_host_is_rechecked_at_the_socket(lane_open, url):
    """`build_request` checked the URL it built. This checks the URL that is
    about to be requested - the last thing before the socket - so a caller
    that hands this module a different URL gets nothing."""
    send = reader_transport.transport()
    with pytest.raises(ReaderRefused):
        send(url, headers=HEADERS, body=BODY, timeout=5.0)
    assert "url" not in FakeClient.seen


# ------------------------------------------------------ what leaves, exactly

def test_the_request_is_a_post_with_no_redirects_no_proxy_and_no_cookies(lane_open):
    send = reader_transport.transport()
    send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    kw = FakeClient.seen["client_kwargs"]
    assert kw["follow_redirects"] is False
    assert kw["trust_env"] is False
    assert kw["cookies"] is None
    assert FakeClient.seen["url"] == URL
    assert FakeClient.seen["headers"]["x-api-key"] == "sk-test-not-real"
    assert FakeClient.seen["headers"]["User-Agent"] == reader_transport.USER_AGENT
    assert b'"one sentence"' in FakeClient.seen["content"]


def test_the_key_never_reaches_a_log_or_an_error(lane_open, caplog):
    """A 4xx names the status, the host and the API's error TYPE - not the
    URL, not the headers, and not the provider's free-text message. The
    first real call answered a bare 400 that needed a second probe to read
    as "credit balance too low"; the type is the part that is safe to keep."""
    FakeClient.response = FakeResponse(status=401, payload={
        "type": "error",
        "error": {"type": "authentication_error",
                  "message": "invalid x-api-key: sk-test-not-real"}})
    send = reader_transport.transport()
    with caplog.at_level(logging.WARNING), pytest.raises(httpx.HTTPStatusError) as raised:
        send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    text = str(raised.value)
    assert "401 from api.anthropic.com (authentication_error)" == text
    assert "sk-test-not-real" not in text, "the provider's message was echoed"
    assert "sk-test-not-real" not in caplog.text


def test_every_request_is_logged_without_its_text(lane_open, caplog):
    send = reader_transport.transport()
    with caplog.at_level(logging.WARNING):
        send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    line = caplog.text
    assert "standards reader" in line and "api.anthropic.com" in line
    assert "one sentence" not in line, "clause text reached a log line"


def test_an_oversized_response_is_refused_not_read(lane_open):
    FakeClient.response = FakeResponse(content=b"x" * (reader_transport.MAX_RESPONSE_BYTES + 1))
    send = reader_transport.transport()
    with pytest.raises(reader_transport.TransportRefused):
        send(URL, headers=HEADERS, body=BODY, timeout=5.0)


# ------------------------------------------------------------- the cost

def test_usage_accumulates_so_one_standard_can_be_costed(lane_open):
    """"Do not run the corpus through Claude until one standard's cost is
    known" needs the transport to count. Tokens come from the API's own
    `usage` block; bytes from what was posted."""
    send = reader_transport.transport()
    send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    send(URL, headers=HEADERS, body=BODY, timeout=5.0)
    assert send.usage["calls"] == 2
    assert send.usage["input_tokens"] == 80
    assert send.usage["output_tokens"] == 14
    assert send.usage["bytes_sent"] > 0


# ---------------------------------------------- end to end, through reader_api

def test_reader_api_runs_end_to_end_through_this_transport(lane_open, monkeypatch):
    """`model_call_via(transport())` is the one seam; a sentence goes in, the
    gate's shape comes out, and only the fake client saw a request."""
    monkeypatch.setenv(API_KEY_ENV, "sk-test-not-real")
    FakeClient.response = FakeResponse(payload={
        "content": [{"type": "text", "text": (
            '{"proposals": [{"kind": "limit", "operator": "<=", "value": "90",'
            ' "unit": "dB(A)", "subject": "noise level",'
            ' "quote": "The noise level shall not exceed 90 dB(A)"}]}')}],
        "usage": {"input_tokens": 400, "output_tokens": 60},
    })
    send = reader_transport.transport()
    cfg = ReaderSettings(enabled=True, allow_public_egress=True)
    out = reader_api.read_sentence(
        "The noise level shall not exceed 90 dB(A).",
        reader_api.model_call_via(send, cfg=cfg))
    assert [p["value"] for p in out["accepted"]] == ["90"]
    assert send.usage["calls"] == 2, "rule 5 asks the model twice"
