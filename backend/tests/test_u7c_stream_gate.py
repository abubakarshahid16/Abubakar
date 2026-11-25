"""Update 7, builder C (the integrator's review point on the upload lane): a streamed local model call never keeps the local
model gate after its caller is done with it, and a wait at the gate is bounded. A loopback server streams invented lines;
no model is run and nothing leaves the machine."""

from __future__ import annotations

import contextlib
import http.server
import json
import socket
import threading
import time

import pytest

from app import local_model_gate as G
from app import model_transport
from app.config import settings
from app.reasoning_provider import (
    OllamaProvider,
    Packet,
    ProviderRefused,
    _ollama_stream,
)


@pytest.fixture
def slow_stream(monkeypatch):
    """A loopback 'local engine' that streams ten NDJSON lines, 0.2 s apart."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            try:
                for i in range(10):
                    line = {"response": f"w{i} ", "model": "m", "done": i == 9}
                    self.wfile.write((json.dumps(line) + "\n").encode())
                    self.wfile.flush()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(settings, "ollama_url", f"http://127.0.0.1:{port}")
    yield
    server.shutdown()


def _upload_lane_call(seconds: float = 5.0) -> tuple[str, float]:
    """One upload-lane model call (the gate only) on its own thread: ('ok' | 'busy: <message>', seconds it took)."""
    out: dict = {}

    def call():
        start = time.monotonic()
        try:
            with G.lane(G.UPLOAD), G.holding():
                out["r"] = "ok"
        except G.LocalModelBusy as exc:
            out["r"] = f"busy: {exc}"
        out["t"] = time.monotonic() - start

    t = threading.Thread(
        target=call, daemon=True
    )  # a failing test never keeps pytest waiting
    t.start()
    t.join(seconds)
    return out.get("r", "still waiting"), out.get("t", seconds)


def _stream():
    return model_transport.stream_json(
        "/api/generate", {"model": "m", "prompt": "p"}, timeout=10
    )


def test_a_stream_dropped_half_way_frees_the_model_for_the_next_call(slow_stream):
    with G.lane(G.REVIEW), contextlib.closing(_stream()) as stream:
        first = next(stream)
        assert first["response"] == "w0 "
        assert (
            _upload_lane_call(0.5)[0] == "still waiting"
        )  # the review lane holds the model while it reads
    # the caller left half-way (eight lines unread): the stream was closed and the gate released
    result, took = _upload_lane_call()
    assert result == "ok" and took < 1.0


def test_the_local_reader_closes_its_stream_when_its_consumer_fails(slow_stream):
    """`reasoning_provider._ollama_stream` keeps no open stream when the text callback raises, even while the error (and its
    traceback) is still held."""
    provider = OllamaProvider("m", timeout=10)
    packet = Packet(prompt="p", num_ctx=1024, num_predict=16)

    def on_text(piece):
        raise ValueError("the reader of the text failed")

    kept = []
    with G.lane(G.REVIEW):
        try:
            _ollama_stream(provider, packet, on_text, None)
        except ProviderRefused as exc:
            kept.append(exc)  # the error and its traceback stay alive
    assert kept
    result, took = _upload_lane_call()
    assert result == "ok" and took < 1.0


def test_a_wait_at_the_gate_is_bounded_and_says_so_plainly(slow_stream, monkeypatch):
    monkeypatch.setattr(G, "WAIT_SECONDS", 0.3)
    stream = _stream()
    with G.lane(G.REVIEW):
        next(stream)  # a stream left open by a careless caller holds the model
    result, took = _upload_lane_call()
    assert (
        result.startswith("busy: The local model was busy with the review work")
        and "did not run" in result
    )
    assert took < 2.0
    stream.close()  # closed at last: the next call goes through
    assert _upload_lane_call()[0] == "ok"
