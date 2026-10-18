"""Order 79c (review path): no broad `except Exception` in the review modules
swallows an error without a trace, and where the error is knowable it is
caught exactly.

A fallback that is a named state stays (MODEL_UNAVAILABLE, "not tag-scoped",
"the page is recorded"); the log names the step and the error's TYPE only,
never its message, which can carry document text (the #655 pattern).
"""
from __future__ import annotations

import ast
import logging
import pathlib
import sqlite3

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
REVIEW = ("ai_engineering_check", "claude_datasheet", "comparison", "crs_wording",
          "datasheet_ai", "datasheets", "review_trace", "rule_eval", "rule_trust",
          "vision_reader")
LOGS = ("log.", "logger.", "logging.", "record_failure", "_say_once(", "log_exception",
        "fell_back(", "_page_failed(")


def _silent(module: str) -> list[int]:
    out = []
    for node in ast.walk(ast.parse((APP / f"{module}.py").read_text(encoding="utf-8"))):
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


@pytest.mark.parametrize("module", REVIEW)
def test_every_broad_catch_in_the_review_modules_logs_or_reraises(module):
    assert _silent(module) == [], f"{module}.py swallows errors silently at lines {_silent(module)}"


def test_every_page_reader_failure_passes_its_error_on():
    """datasheets' page readers record the page through `_page_failed`; each
    handler must hand it the error so its type is logged."""
    calls = []
    for node in ast.walk(ast.parse((APP / "datasheets.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.ExceptHandler):
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_page_failed":
                    calls.append((node.lineno, node.name,
                                  [getattr(a, "id", None) for a in call.args]))
    assert len(calls) >= 5
    assert all(name and name in args for _line, name, args in calls), calls


def _messages(caplog, logger):
    return [r.getMessage() for r in caplog.records if r.name == logger]


def test_fell_back_logs_the_type_only_and_returns_the_fallback(caplog):
    from app import errors

    with caplog.at_level(logging.INFO, logger="app.comparison"):
        got = errors.fell_back("comparison: a step failed; x instead",
                               KeyError("document text must not reach the log"), ("x", 1))
        assert errors.fell_back("comparison: nothing failed", None, 7) == 7
    assert got == ("x", 1)
    assert _messages(caplog, "app.comparison") == ["comparison: a step failed; x instead (KeyError)"]


def test_a_malformed_model_choice_is_still_malformed():
    """Narrowed to ValueError: bad JSON and the wrong shape both stay MODEL_MALFORMED."""
    from app import comparison

    candidates = [{"fact_key": "a"}]
    assert comparison._checked_choice("not json at all", candidates) == (None, comparison.MODEL_MALFORMED)
    assert comparison._checked_choice('{"choice": "first"}', candidates) == (None, comparison.MODEL_MALFORMED)


def test_a_failed_local_pair_choice_is_still_unavailable_and_says_why(caplog, monkeypatch):
    from app import comparison, model_transport

    def refused(*_a, **_k):
        raise ConnectionError("prompt text must not reach the log")

    monkeypatch.setattr(model_transport, "post_json", refused)
    with caplog.at_level(logging.INFO, logger="app.comparison"):
        got = comparison._ask_model_once({"text": "x", "page": 1}, [{"label": "y", "value": "1"}])
    assert got == (None, comparison.MODEL_UNAVAILABLE)
    messages = _messages(caplog, "app.comparison")
    assert any("local pair-choice call failed" in m and "ConnectionError" in m for m in messages)
    assert not any("prompt text" in m for m in messages)


def test_a_database_without_the_rejections_table_applies_none_and_says_why(caplog, monkeypatch):
    from app import comparison

    monkeypatch.setattr(comparison, "connect", lambda: sqlite3.connect(":memory:"))
    with caplog.at_level(logging.INFO, logger="app.comparison"):
        assert comparison._rejected_keys_for({"requirement_id": "r1"}) == set()
        assert comparison._document_is_tag_scoped("doc-1") is False
    messages = _messages(caplog, "app.comparison")
    assert any("pair rejections could not be read" in m and "OperationalError" in m for m in messages)
    assert any("equipment tags could not be counted" in m for m in messages)


def test_an_unexpected_database_error_is_no_longer_read_as_a_missing_table(monkeypatch):
    """Exact catch: only sqlite3.OperationalError means "no table yet"."""
    from app import comparison

    def refused():
        raise RuntimeError("live database refused")

    monkeypatch.setattr(comparison, "connect", refused)
    with pytest.raises(RuntimeError):
        comparison._rejected_keys_for({"requirement_id": "r1"})


def test_a_page_reader_failure_still_records_the_page_and_says_why(caplog):
    from app import datasheets

    with caplog.at_level(logging.INFO, logger="app.datasheets"):
        datasheets._page_failed(3, "grid", ValueError("cell text must not reach the log"))
    messages = _messages(caplog, "app.datasheets")
    assert messages == ["datasheets: the grid reader failed on a page; the page is recorded (ValueError)"]
