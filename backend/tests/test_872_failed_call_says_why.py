"""#872: a failed Claude call says why - the HTTP status, the API's error
class, and "no credit" in plain words - and never the API's message.

Live run of 12 Oct 2026: from one moment on every Claude call failed with
HTTP 400 and the spend ledger said only "unbilled:HTTPStatusError". The
cause (the account's credit was finished) had to be read from the provider's
console. The API answers an empty balance with the generic type
`invalid_request_error`; only its free-text message says "credit balance".

The message is free text the provider writes and could echo a request field,
so it is TESTED for that one case and never stored. Invented responses only.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import claude_spend
from app import reasoning_provider as rp
from app.config import settings

SECRET_IN_MESSAGE = "Your credit balance is too low. Request field echoed: PRESSURE-IS-23.5-BARG sk-ant-NOT-A-KEY"


def _api_error(status: int, kind: str | None = "invalid_request_error", message: str = "nope"):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": kind, "message": message}} if kind is not None else {"oops": 1}
    return httpx.HTTPStatusError(f"{status} from api.anthropic.com", request=request,
                                 response=httpx.Response(status, request=request, json=body))


@pytest.mark.parametrize("exc, word", [
    (_api_error(400, message=SECRET_IN_MESSAGE), "HTTPStatusError:http_400:no_credit"),
    (_api_error(400, message="max_tokens: must be positive"), "HTTPStatusError:http_400:invalid_request_error"),
    (_api_error(401, "authentication_error"), "HTTPStatusError:http_401:authentication_error"),
    (_api_error(429, "rate_limit_error"), "HTTPStatusError:http_429:rate_limit_error"),
    (_api_error(529, "overloaded_error"), "HTTPStatusError:http_529:overloaded_error"),
    (_api_error(500, None), "HTTPStatusError:http_500"),                      # not the API's JSON
    (httpx.ReadTimeout("read timed out"), "ReadTimeout"),
    (httpx.ConnectError("no route"), "ConnectError"),
    (ValueError("anything"), "ValueError"),
])
def test_the_closed_description_of_a_failed_call(exc, word):
    assert claude_spend.failure_word(exc) == word


@pytest.mark.parametrize("kind", [
    "Invalid Request", "invalid-request", "x" * 41, "error: see https://example.invalid/?key=1",
    "<script>", "", 7,
])
def test_an_error_type_that_is_not_the_apis_enum_is_not_copied(kind):
    assert claude_spend.failure_word(_api_error(403, kind)) == "HTTPStatusError:http_403"


def test_a_402_or_a_credit_word_elsewhere_is_not_called_no_credit():
    """Only the API's own shape: HTTP 400 with the words in its message."""
    assert not claude_spend.failure_word(_api_error(500, "api_error", SECRET_IN_MESSAGE)).endswith("no_credit")
    assert claude_spend.failure_words(_api_error(500, "api_error", SECRET_IN_MESSAGE)) is None
    assert claude_spend.failure_words(httpx.ReadTimeout("credit balance")) is None


def test_no_credit_is_said_in_plain_words_and_nothing_of_the_message_is_kept():
    exc = _api_error(400, message=SECRET_IN_MESSAGE)
    words = claude_spend.failure_words(exc)
    assert words == claude_spend.NO_CREDIT_WORDS and "no credit" in words
    for text in (words, claude_spend.failure_word(exc)):
        assert "PRESSURE" not in text and "sk-ant" not in text and "too low" not in text


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    return tmp_path / "spend.jsonl"


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_ledger_line_of_an_unbilled_failure_says_why(ledger):
    held = claude_spend.reserve("s872", 0.01, model="claude-test")
    exc = _api_error(400, message=SECRET_IN_MESSAGE)
    assert claude_spend.settle_failure(held, exc, unbilled=lambda e: True) is None
    released = [line for line in _lines(ledger) if line.get("releases") == held.id]
    assert [line["reason"] for line in released] == ["unbilled:HTTPStatusError:http_400:no_credit"]
    assert "PRESSURE" not in ledger.read_text(encoding="utf-8") and "sk-ant" not in ledger.read_text(encoding="utf-8")


def test_the_ledger_line_of_a_charged_failure_says_why_too(ledger):
    held = claude_spend.reserve("s872", 0.01, model="claude-test")
    claude_spend.settle_failure(held, _api_error(529, "overloaded_error"), unbilled=lambda e: False)
    [entry] = claude_spend.entries()
    assert entry["finish_reason"] == "failed:HTTPStatusError:http_529:overloaded_error" and entry["estimated"] is True


def test_the_runs_own_message_names_no_credit(ledger, monkeypatch):
    """What the AI check and the wording record when the cloud call fails."""
    def send(url, *, headers, body, timeout):
        raise _api_error(400, message=SECRET_IN_MESSAGE)
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-invented-key")
    provider = rp.ClaudeProvider("claude-test", step="s872", transport=send)
    with pytest.raises(rp.ProviderRefused) as caught:
        provider.reason(rp.Packet(prompt="hello", num_ctx=1024, num_predict=16, step="s872"))
    said = str(caught.value)
    assert said.endswith(claude_spend.NO_CREDIT_WORDS) and "HTTPStatusError" in said
    assert "PRESSURE" not in said and "sk-ant" not in said and caught.value.cost_usd == 0.0
