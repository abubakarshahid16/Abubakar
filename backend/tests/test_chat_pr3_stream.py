"""Chat redesign PR 3 (owner order 2026-09-26): streaming, progress, Stop.

What these tests hold:
  * the stream's events come in order - turn, steps, deltas, sources,
    verification, notices, then done - and `done` IS the non-streaming answer;
  * on the Claude lane a document sentence is streamed only once its quote
    verified: an unverified claim never appears in ANY delta;
  * Stop stops: the provider call ends within two seconds even before the
    first byte (a real loopback server that never answers), the ledger records
    the stopped call, and the turn is stored cancelled with only what was shown;
  * only the turn's owner can stop it; budget caps still refuse before a byte.

No network beyond a loopback test server. Synthetic documents only.
"""
from __future__ import annotations

import http.server
import json
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import chat, chat_model, chat_stream, claude_spend, db, model_transport
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import KEY


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def _stream(client, convo, question, **extra):
    r = client.post(f"/api/conversations/{convo}/ask/stream", json={"question": question, **extra})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return _events(r.text)


def _local_stream(monkeypatch, pieces, gate=None):
    """A fake local engine that streams `pieces`; waits on `gate` between them."""
    calls = []

    def stream_json(path, body, *, timeout, cancel=None):
        calls.append(body)
        for piece in pieces:
            if cancel is not None and cancel.is_set():
                return
            if gate is not None:
                gate(cancel)
            yield {"response": piece, "done": False}
        yield {"response": "", "done": True, "done_reason": "stop", "model": "qwen3.5:4b"}

    monkeypatch.setattr(model_transport, "stream_json", stream_json)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    return calls


def _claude_stream(monkeypatch, tmp_path, pieces, calls=None):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY",
                 "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)

    def send(url, *, headers, body, timeout, cancel=None):
        if calls is not None:
            calls.append(body)
        yield {"type": "message_start", "message": {"model": "claude-sonnet-5",
                                                    "usage": {"input_tokens": 900}}}
        for piece in pieces:
            if cancel is not None and cancel.is_set():
                return
            yield {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}
        yield {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
               "usage": {"output_tokens": 60}}

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))


# ------------------------------------------------------------------ order

def test_a_streamed_answer_arrives_in_order_and_done_is_the_answer():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    events = _stream(client, convo, "what is the NDFT for coating system no. 1")
    names = [e for e, _ in events]
    assert names[0] == "turn" and names[-1] == "done"
    assert "step" in names and names.index("step") < names.index("sources") < names.index("done")
    assert names.index("verification") < names.index("done")
    done = events[-1][1]
    assert done["answer_type"] == "extract" and done["used_line"].startswith("Checked")
    assert [s["label"] for e, s in events if e == "step"][0] == "Searching your documents"
    # the same answer the non-streaming route stores and replays
    reopened = client.get(f"/api/conversations/{convo}").json()["messages"][-1]
    assert reopened["text"] == done["answer"]


def test_general_text_streams_as_it_arrives(monkeypatch):
    _local_stream(monkeypatch, ["Sulfidation is sulfur ", "attack on steel. ", "It thins the wall [S1]."])
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    events = _stream(client, convo, "What is sulfidation? Explain it simply.")
    deltas = [d["text"] for e, d in events if e == "delta"]
    assert deltas == ["Sulfidation is sulfur attack on steel. ", "It thins the wall. "]
    assert events[-1][1]["answer_type"] == "general"
    assert ("step", {"label": "Writing the answer", "count": None, "done": False}) in events


def test_on_the_claude_lane_an_unverified_claim_is_never_streamed(monkeypatch, tmp_path):
    """THE MUTATION TARGET: stream a document sentence only after its quote verifies."""
    _claude_stream(monkeypatch, tmp_path, [
        "**Partly.** The NDFT is 280 um [S1 \"NDFT nominal dry film ",
        "thickness of 280 um\"]. It needs five coats [S1 \"applied as five coats\"]. ",
        "What I'd do: check the coating plan."])
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    events = _stream(client, convo, "what is the NDFT for coating system no. 1", tier="generated")
    streamed = " ".join(d["text"] for e, d in events if e == "delta")
    assert "280 um [S1]" in streamed
    assert "five coats" not in streamed
    assert '"' not in streamed
    assert events[-1][1]["verification"] == {"verified": 1, "total": 2,
                                             "method": "quote found on the page"}


# ------------------------------------------------------------------- Stop

def _slow_ollama_server():
    """A loopback server that accepts the request and never answers - a model
    still reading a long prompt."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            time.sleep(30)

        def log_message(self, *args):
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def test_stop_ends_a_call_within_two_seconds_even_before_the_first_byte(monkeypatch):
    """THE MUTATION TARGET: Stop really stops the provider call."""
    server, port = _slow_ollama_server()
    monkeypatch.setattr(settings, "ollama_url", f"http://127.0.0.1:{port}")
    cancel = threading.Event()
    got: list = []

    def consume():
        got.extend(model_transport.stream_json("/api/generate", {"model": "m", "prompt": "p"},
                                               timeout=60, cancel=cancel))

    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    time.sleep(0.3)
    stopped_at = time.time()
    cancel.set()
    worker.join(timeout=5)
    server.shutdown()
    assert not worker.is_alive(), "the call was still running after Stop"
    assert time.time() - stopped_at < 2.0
    assert got == []


def _answer_in_thread(convo, question, turn, **kw):
    out = {}

    def run():
        token = chat_stream.bind(turn)
        try:
            everything = frozenset(r["id"] for r in db.connect().execute("SELECT id FROM documents"))
            out["result"] = chat.ask(convo, question, allowed_document_ids=everything, **kw)
        finally:
            chat_stream.unbind(token)
            turn.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def test_a_stopped_turn_is_stored_cancelled_with_only_what_was_shown(monkeypatch, tmp_path):
    first_shown = threading.Event()

    def gate(cancel):
        if first_shown.is_set():
            cancel.wait(5)

    calls: list = []
    _claude_stream(monkeypatch, tmp_path, [], calls)
    # a Claude stream that shows one sentence, then waits for Stop
    def send(url, *, headers, body, timeout, cancel=None):
        calls.append(body)
        yield {"type": "message_start", "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 900}}}
        yield {"type": "content_block_delta", "delta": {"text": "Sulfidation is sulfur attack on steel. "}}
        yield {"type": "content_block_delta", "delta": {"text": "It "}}
        first_shown.set()
        cancel.wait(5)
        if not cancel.is_set():
            yield {"type": "content_block_delta", "delta": {"text": "never stopped."}}

    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    turn = chat_stream.open_turn(owner=None, conversation_id=convo)
    thread, out = _answer_in_thread(convo, "What is sulfidation? Explain it simply.", turn)
    assert first_shown.wait(5)
    started = time.time()
    turn.cancel.set()
    thread.join(5)
    assert time.time() - started < 2.0
    result = out["result"]
    assert result["answer_type"] == "cancelled"
    assert result["answer"] == "Sulfidation is sulfur attack on steel."
    stored = client.get(f"/api/conversations/{convo}").json()["messages"][-1]
    assert stored["answer_type"] == "cancelled" and stored["used_line"].startswith("Stopped")
    ledger = claude_spend.entries()
    assert ledger and ledger[-1]["finish_reason"] == "cancelled" and ledger[-1]["cost_usd"] > 0


def test_stop_before_the_model_sends_nothing(monkeypatch, tmp_path):
    calls: list = []
    _claude_stream(monkeypatch, tmp_path, ["anything."], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    turn = chat_stream.open_turn(owner=None, conversation_id=convo)
    turn.cancel.set()
    thread, out = _answer_in_thread(convo, "What is sulfidation? Explain it simply.", turn)
    thread.join(5)
    assert calls == [], "a stopped turn still reached the provider"
    assert out["result"]["answer_type"] == "cancelled"
    assert claude_spend.entries() == []


def test_the_cancel_route_stops_only_the_owners_turn():
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    other = client.post("/api/conversations").json()["id"]
    turn = chat_stream.open_turn(owner=None, conversation_id=convo)
    # a turn id from another conversation is not found here
    assert client.post(f"/api/conversations/{other}/ask/{turn.id}/cancel").status_code == 404
    assert not turn.cancel.is_set()
    assert client.post(f"/api/conversations/{convo}/ask/nope/cancel").status_code == 404
    ok = client.post(f"/api/conversations/{convo}/ask/{turn.id}/cancel")
    assert ok.status_code == 200 and ok.json() == {"turn_id": turn.id, "cancelled": True}
    assert turn.cancel.is_set()


def test_a_turn_is_found_only_by_its_owner():
    turn = chat_stream.open_turn(owner="alice", conversation_id="c")
    assert chat_stream.find(turn.id, owner="alice") is turn
    assert chat_stream.find(turn.id, owner="bob") is None
    assert chat_stream.find(turn.id, owner=None, unrestricted=True) is turn


def test_a_streamed_call_over_the_budget_is_refused_before_a_byte(monkeypatch, tmp_path):
    calls: list = []
    _claude_stream(monkeypatch, tmp_path, ["anything."], calls)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    events = _stream(client, convo, "What is the difference between barg and bara?")
    assert calls == []
    assert events[-1][0] == "done" and events[-1][1]["answer_type"] == "model_unavailable"
    assert "spending cap" in events[-1][1]["reason"]


def test_a_failure_ends_the_stream_with_an_error_not_a_hang(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("SECRET INTERNAL DETAIL")

    monkeypatch.setattr(chat, "ask", boom)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    events = _stream(client, convo, "anything")
    assert events[-1][0] == "error"
    assert "SECRET INTERNAL DETAIL" not in json.dumps(events)


def test_the_claude_stream_keeps_the_transports_gates(monkeypatch):
    """The stream is the same lane, not a second one: egress flags off means
    no request is built; a host off the allowlist is refused before a socket."""
    from app import reader_api, reader_transport

    monkeypatch.setattr(settings, "standards_reader_enabled", False)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(reader_transport.TransportRefused):
        next(reader_transport.stream("https://api.anthropic.com/v1/messages",
                                     headers={}, body={"model": "m"}, timeout=5))
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    with pytest.raises(reader_api.ReaderRefused):
        next(reader_transport.stream("https://evil.example.com/v1/messages",
                                     headers={}, body={"model": "m"}, timeout=5))
