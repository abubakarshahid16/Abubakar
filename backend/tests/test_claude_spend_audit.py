"""Audit 2026-09-30: the Claude USD caps (USD 5 per step / USD 20 in total,
`claude_spend`) must count EVERY call that may have been sent, and the check
must hold when several callers race for the last dollars.

  1. A single call or a stream that fails AFTER it may have reached the API (a
     read timeout, a dropped stream, the 1 MB stream cap) is charged: its
     reported final usage when known, otherwise its worst case. Before, both
     paths turned the error into `ProviderRefused` and wrote nothing.
  2. The check and the ledger line are one locked step (`reserve`): ten
     threads - or four processes - at $4.90 with a $0.09 worst case each let
     exactly one call through. Before, all ten passed and the step reached
     $5.80.
  3. Claude-first chat reports the cost of the whole turn, and says "spending
     cap" only when the spending cap is what stopped it.

No network: every transport is a fake.
"""
from __future__ import annotations

import json
import multiprocessing
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import claude_spend, reader_transport
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import KEY, _stream_events

pytestmark = pytest.mark.usefixtures("temp_storage")

MODEL = "claude-sonnet-5"
STEP = "audit-step"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY",
                 "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _packet(**kw):
    base = {"prompt": "Is it?", "num_ctx": 4096, "num_predict": 200, "step": STEP}
    base.update(kw)
    return rp.Packet(**base)


def _worst(provider: rp.ClaudeProvider, packet: rp.Packet) -> float:
    _request, _body, prompt = provider._request(packet)
    return round(claude_spend.worst_case_usd(provider.requested_model, len(packet.system) + len(prompt),
                                             packet.num_predict), 6)


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.HTTPStatusError(f"{status} from api.anthropic.com", request=request,
                                 response=httpx.Response(status, request=request))


# ------------------------------------------- 1. a failed call is still counted

def test_a_read_timeout_in_reason_is_charged_its_worst_case():
    """THE MUTATION TARGET (M1470): `reason` used to turn this into
    ProviderRefused and write no ledger line at all."""
    def send(url, *, headers, body, timeout):
        raise httpx.ReadTimeout("read timed out")
    provider = rp.ClaudeProvider(MODEL, transport=send)
    packet = _packet(num_predict=4000)
    with pytest.raises(rp.ProviderRefused) as caught:
        provider.reason(packet)
    [entry] = claude_spend.entries()
    assert entry["finish_reason"] == "failed:ReadTimeout"
    assert entry["estimated"] is True and not entry.get("reserved")
    assert entry["cost_usd"] == _worst(provider, packet) > 0
    assert caught.value.cost_usd == entry["cost_usd"]
    assert claude_spend.spent(STEP) == entry["cost_usd"]


def test_a_call_the_api_provably_rejected_is_not_charged():
    def send(url, *, headers, body, timeout):
        raise _status_error(400)
    with pytest.raises(rp.ProviderRefused) as caught:
        rp.ClaudeProvider(MODEL, transport=send).reason(_packet())
    assert claude_spend.entries() == [] and caught.value.cost_usd == 0.0


def _stream_that_fails(exc, *, final_usage: dict | None):
    def stream(url, *, headers, body, timeout, cancel=None):
        yield {"type": "message_start", "message": {"model": MODEL, "usage": {"input_tokens": 900}}}
        yield {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}
        yield {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello " * 50}}
        if final_usage is not None:
            yield {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": final_usage}
        raise exc
    return stream


@pytest.mark.parametrize("exc", [
    ConnectionResetError("dropped"),
    reader_transport.TransportRefused("stream passed the 1048576 byte limit", sent=True),
], ids=["dropped-mid-stream", "1MB-stream-cap"])
def test_a_stream_that_fails_before_its_final_usage_is_charged_its_worst_case(exc):
    """THE MUTATION TARGET (M1471)."""
    provider = rp.ClaudeProvider(MODEL, stream_transport=_stream_that_fails(exc, final_usage=None))
    packet = _packet(num_predict=4000)
    with pytest.raises(rp.ProviderRefused) as caught:
        provider.stream(packet, lambda _piece: None)
    [entry] = claude_spend.entries()
    assert entry["finish_reason"] == f"failed:{type(exc).__name__}"
    assert entry["estimated"] is True and not entry.get("reserved")
    assert entry["cost_usd"] == _worst(provider, packet)
    assert caught.value.cost_usd == entry["cost_usd"]


def test_a_stream_that_fails_after_its_final_usage_is_charged_that_usage():
    """THE MUTATION TARGET (M1472): the API already reported the bill - charge
    that, not the worst case and not nothing."""
    usage = {"output_tokens": 300}
    provider = rp.ClaudeProvider(MODEL, stream_transport=_stream_that_fails(
        ConnectionResetError("dropped"), final_usage=usage))
    with pytest.raises(rp.ProviderRefused):
        provider.stream(_packet(num_predict=4000), lambda _piece: None)
    [entry] = claude_spend.entries()
    assert entry["finish_reason"] == "failed:ConnectionResetError"
    assert not entry.get("estimated")
    assert (entry["input_tokens"], entry["output_tokens"]) == (900, 300)
    assert entry["cost_usd"] == round(claude_spend.cost_usd(MODEL, {"input_tokens": 900,
                                                                      "output_tokens": 300}), 6)


def test_a_call_in_flight_already_counts_at_its_worst_case():
    """The reservation is in the ledger BEFORE the call leaves, so a process
    that dies mid-call can never leave it uncounted."""
    seen = {}

    def send(url, *, headers, body, timeout):
        seen["during"] = claude_spend.entries()
        return {"model": MODEL, "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    provider = rp.ClaudeProvider(MODEL, transport=send)
    packet = _packet(num_predict=4000)
    provider.reason(packet)
    [during] = seen["during"]
    assert during["reserved"] is True and during["cost_usd"] == _worst(provider, packet)
    [after] = claude_spend.entries()
    assert after["finish_reason"] == "stop" and after["cost_usd"] < during["cost_usd"]


# -------------------------------------------- 2. the check is atomic

def _seed(step: str, usd: float) -> None:
    with open(settings.claude_spend_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"step": step, "cost_usd": usd}) + "\n")


def _slow_reads(monkeypatch):
    """Widen the window between reading the ledger and writing it, so a
    check that is not atomic is caught every time, not by luck."""
    real = claude_spend.entries

    def slow():
        out = real()
        time.sleep(0.05)
        return out
    monkeypatch.setattr(claude_spend, "entries", slow)


def test_ten_threads_racing_for_the_last_dollars_let_exactly_one_call_through(monkeypatch):
    """THE MUTATION TARGET (M1473): the audit's reproduction - ten threads,
    $4.90 spent, $0.09 worst case each. Before: all ten passed, $5.80."""
    _seed(STEP, 4.90)
    _slow_reads(monkeypatch)
    barrier = threading.Barrier(10)
    passed, refused = [], []

    def go():
        barrier.wait()
        try:
            passed.append(claude_spend.reserve(STEP, 0.09, model=MODEL))
        except claude_spend.BudgetExceeded:
            refused.append(1)
    threads = [threading.Thread(target=go) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert (len(passed), len(refused)) == (1, 9)
    assert claude_spend.spent(STEP) == pytest.approx(4.99)
    assert claude_spend.spent(STEP) <= 5.0


def _child(path: str, barrier, results) -> None:
    settings.claude_spend_log = __import__("pathlib").Path(path)
    barrier.wait()
    try:
        claude_spend.reserve(STEP, 0.09, model=MODEL)
        results.put("passed")
    except claude_spend.BudgetExceeded:
        results.put("refused")


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="needs the POSIX 'fork' start method; runs on the Linux CI runner",
)
def test_four_processes_sharing_one_ledger_let_exactly_one_call_through(monkeypatch):
    """THE MUTATION TARGET (M1474): the thread lock alone does not reach
    another process; the OS lock on `<ledger>.lock` does."""
    _seed(STEP, 4.90)
    _slow_reads(monkeypatch)      # inherited by the forked children
    ctx = multiprocessing.get_context("fork")
    barrier, results = ctx.Barrier(4), ctx.Queue()
    procs = [ctx.Process(target=_child, args=(str(settings.claude_spend_log), barrier, results))
             for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    outcomes = sorted(results.get(timeout=5) for _ in procs)
    assert outcomes == ["passed", "refused", "refused", "refused"]
    assert claude_spend.spent(STEP) == pytest.approx(4.99)


def test_a_batch_is_reserved_as_a_whole_not_one_request_at_a_time(monkeypatch):
    """THE MUTATION TARGET (M1478): two requests that each fit alone but not
    together are refused together, and nothing is held."""
    with pytest.raises(claude_spend.BudgetExceeded):
        claude_spend.reserve_all([(STEP, 3.0), (STEP, 3.0)], model=MODEL)
    assert claude_spend.entries() == []
    with pytest.raises(claude_spend.BudgetExceeded, match="total"):
        claude_spend.reserve_all([(f"s{i}", 4.0) for i in range(6)], model=MODEL)
    assert claude_spend.entries() == []


# -------------------------------- 3. Claude-first chat: whole turn, true cause

def _chat_on(monkeypatch, send):
    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))


def _tool_use(name: str, input: dict) -> dict:
    return {"model": MODEL, "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": name, "input": input}],
            "usage": {"input_tokens": 2000, "output_tokens": 40}}


def _ask(client, convo, question, **extra):
    return client.post(f"/api/conversations/{convo}/ask", json={"question": question, **extra}).json()


def test_a_chat_turn_reports_the_cost_of_every_call_not_the_last_one(monkeypatch):
    """THE MUTATION TARGET (M1475)."""
    client = TestClient(app)
    doc = upload(client)
    payloads = [_tool_use("read_document", {"document_id": doc}),
                {"model": MODEL, "stop_reason": "end_turn",
                 "content": [{"type": "text", "text": "This document covers coating systems."}],
                 "usage": {"input_tokens": 100, "output_tokens": 10}}]
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        n["i"] += 1
        yield from _stream_events(payloads[n["i"] - 1])
    _chat_on(monkeypatch, send)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "tell me about this document", document_id=doc, tier="generated")
    assert n["i"] == 2
    ledger = sum(e["cost_usd"] for e in claude_spend.entries())
    assert body["cost_usd"] == pytest.approx(ledger)
    assert body["cost_usd"] > round(claude_spend.cost_usd(MODEL, payloads[1]["usage"]), 6)


def test_a_network_failure_mid_loop_is_not_called_the_spending_cap(monkeypatch):
    """THE MUTATION TARGET (M1476): the reason names the real cause, and the
    turn's cost includes the failed call that may have been billed."""
    client = TestClient(app)
    doc = upload(client)
    n = {"i": 0}

    def send(url, *, headers, body, timeout, cancel=None):
        n["i"] += 1
        if n["i"] == 1:
            yield from _stream_events(_tool_use("read_document", {"document_id": doc}))
            return
        raise httpx.ReadTimeout("read timed out")
    _chat_on(monkeypatch, send)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "tell me about this document", document_id=doc, tier="generated")
    assert body["answer_type"] == "model_unavailable"
    assert "spending cap" not in body["reason"]
    assert "failed" in body["reason"] and "ReadTimeout" in body["reason"]
    assert body["cost_usd"] == pytest.approx(sum(e["cost_usd"] for e in claude_spend.entries()))
    assert any(e.get("estimated") for e in claude_spend.entries())


def test_a_consent_exit_mid_loop_still_reports_what_the_turn_cost(monkeypatch):
    """THE MUTATION TARGET (M1477)."""
    monkeypatch.setattr(settings, "chat_web_enabled", True)
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    client = TestClient(app)
    doc = upload(client)

    def send(url, *, headers, body, timeout, cancel=None):
        yield from _stream_events(_tool_use("web_search", {"query": "newer edition of ISO 12944"}))
    _chat_on(monkeypatch, send)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what does this datasheet cover", document_id=doc, web=True)
    assert body["answer_type"] == "web_consent"
    assert body["cost_usd"] > 0
    assert body["cost_usd"] == pytest.approx(sum(e["cost_usd"] for e in claude_spend.entries()))
