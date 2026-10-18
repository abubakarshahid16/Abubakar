"""Order 79c (infrastructure): no broad `except Exception` in the server,
metrics, lock and budget modules swallows an error without a trace.

Each handler either re-raises or logs what failed and the error's TYPE (the
#655 pattern; never document text). Where the error is knowable it is caught
exactly: the chat stream's poll catches `queue.Empty`, not every error.
"""

from __future__ import annotations

import ast
import logging
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
INFRA = (
    "auth",
    "chat_web",
    "claude_spend",
    "db",
    "heavy_lock",
    "job_queue",
    "live_guard",
    "main",
    "metrics",
    "model_memory",
    "notifications",
    "progress",
    "risks",
    "telemetry",
    "warmup",
)
LOGS = (
    "log.",
    "logger.",
    "logging.",
    "record_failure",
    "_say_once(",
    "log_exception",
    "fell_back(",
)


def _silent(module: str) -> list[int]:
    out = []
    for node in ast.walk(ast.parse((APP / f"{module}.py").read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ExceptHandler):
            continue
        t = node.type
        names = (
            [] if t is None else ([t] if not isinstance(t, ast.Tuple) else list(t.elts))
        )
        broad = t is None or any(
            isinstance(n, ast.Name) and n.id in ("Exception", "BaseException")
            for n in names
        )
        if not broad or any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            continue
        if not any(word in ast.unparse(node) for word in LOGS):
            out.append(node.lineno)
    return out


@pytest.mark.parametrize("module", INFRA)
def test_every_broad_catch_in_the_infrastructure_modules_logs_or_reraises(module):
    assert _silent(module) == [], (
        f"{module}.py swallows errors silently at lines {_silent(module)}"
    )


def test_the_chat_stream_poll_catches_only_an_empty_queue():
    tree = ast.parse((APP / "main.py").read_text(encoding="utf-8"))
    polls = [
        h
        for h in ast.walk(tree)
        if isinstance(h, ast.Try) and "get_nowait" in ast.unparse(h.body[0])
    ]
    assert polls, "the chat stream's queue poll was not found"
    assert all(ast.unparse(h.handlers[0].type) == "chat_stream.Empty" for h in polls)
    import queue

    from app import chat_stream

    assert chat_stream.Empty is queue.Empty


def test_an_unknown_lock_holder_is_still_unknown_and_says_why(caplog, monkeypatch):
    """The fallback is unchanged (None = cannot tell); the log names the step
    and the error type only."""
    import psutil

    from app import heavy_lock

    def broken(pid):
        raise PermissionError("detail must not reach the log")

    monkeypatch.setattr(psutil, "pid_exists", broken)
    with caplog.at_level(logging.DEBUG, logger="app.heavy_lock"):
        assert heavy_lock._pid_alive(4242) is None
    messages = [r.getMessage() for r in caplog.records if r.name == "app.heavy_lock"]
    assert any("could not be checked" in m and "PermissionError" in m for m in messages)
    assert not any("detail" in m for m in messages)
