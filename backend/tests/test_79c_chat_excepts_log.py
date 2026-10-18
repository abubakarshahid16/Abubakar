"""Order 79c (chat): no broad `except Exception` in the chat and answer modules
swallows an error without a trace.

Each handler either re-raises or logs what failed and the error's TYPE (the
#655 pattern; never the question, the answer or document text). The fallbacks
stay: a failed model call is still "model unavailable", a failed highlight
search is still a miss.
"""

from __future__ import annotations

import ast
import logging
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
CHAT = (
    "answer",
    "chat",
    "chat_answers",
    "chat_comparison",
    "chat_model",
    "chat_tools",
    "family_search",
    "highlight",
    "intent",
    "market_providers",
    "reranker",
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


@pytest.mark.parametrize("module", CHAT)
def test_every_broad_catch_in_the_chat_modules_logs_or_reraises(module):
    assert _silent(module) == [], (
        f"{module}.py swallows errors silently at lines {_silent(module)}"
    )


def test_an_unreadable_provider_still_reports_local_and_says_why(caplog, monkeypatch):
    """The fallback is unchanged; the log names the step and the error type only."""
    from app import chat_model
    from app import reasoning_provider as rp

    def broken(preference=None):
        raise RuntimeError("secret detail must not reach the log")

    monkeypatch.setattr(chat_model, "provider", broken)
    with caplog.at_level(logging.DEBUG, logger="app.chat_model"):
        assert chat_model.engine_name("auto") == rp.OLLAMA
    messages = [r.getMessage() for r in caplog.records if r.name == "app.chat_model"]
    assert any(
        "reasoning provider could not be read" in m and "RuntimeError" in m
        for m in messages
    )
    assert not any("secret detail" in m for m in messages)
