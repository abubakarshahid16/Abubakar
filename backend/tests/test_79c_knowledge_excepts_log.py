"""Order 79c (knowledge): no broad `except Exception` in the standards-library
modules swallows an error without a trace.

Each handler either re-raises or logs what failed and the error's TYPE (the
#655 pattern; never document text). The fallbacks stay: a scope decision that
fails is still "not decided", a failed web fetch is still "no requirement".
"""
from __future__ import annotations

import ast
import logging
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
KNOWLEDGE = ("standards", "applicability", "okf", "field_naming", "acronyms", "web_standards")
LOGS = ("log.", "logger.", "logging.", "record_failure", "_say_once(", "log_exception", "fell_back(")


def _silent(module: str) -> list[int]:
    out = []
    for node in ast.walk(ast.parse((APP / f"{module}.py").read_text())):
        if not isinstance(node, ast.ExceptHandler):
            continue
        t = node.type
        names = [] if t is None else ([t] if not isinstance(t, ast.Tuple) else list(t.elts))
        broad = t is None or any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException")
                                 for n in names)
        if not broad or any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            continue
        if not any(word in ast.unparse(node) for word in LOGS):
            out.append(node.lineno)
    return out


@pytest.mark.parametrize("module", KNOWLEDGE)
def test_every_broad_catch_in_the_knowledge_modules_logs_or_reraises(module):
    assert _silent(module) == [], f"{module}.py swallows errors silently at lines {_silent(module)}"


def test_a_failed_web_fetch_is_still_no_requirement_and_says_why(caplog, monkeypatch):
    """The fallback is unchanged; the log names the step and the error type only."""
    from app import web_standards

    monkeypatch.setattr(web_standards, "search", lambda identifier, topic=None, fetch=None: {
        "rows": [{"url": "https://example.org/std", "publisher": "Example",
                  "text": "the wall shall be 6 mm", "published": None}]})

    def fetch(url, timeout):
        raise ConnectionError("page body must not reach the log")

    with caplog.at_level(logging.INFO, logger="app.web_standards"):
        found = web_standards.build_requirement("STD-1", fetch_text=fetch)
    assert found is None
    messages = [r.getMessage() for r in caplog.records if r.name == "app.web_standards"]
    assert any("could not be fetched" in m and "ConnectionError" in m for m in messages)
    assert not any("page body" in m for m in messages)
