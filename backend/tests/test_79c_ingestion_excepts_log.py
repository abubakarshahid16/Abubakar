"""Order 79c (ingestion): no broad `except Exception` in the ingestion
modules swallows an error without a trace.

Each such handler either re-raises or logs - the #655 pattern: what failed and
the error's TYPE, never document text. The fallbacks stay (a page that defeats
the table finder still keeps no table); only the silence goes. Invented data.
"""
from __future__ import annotations

import ast
import logging
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
INGESTION = ("datasheet_inputs", "extract", "form_reader", "geometry_reader", "ocr",
             "page_ledger", "tables", "upload", "vector_store", "vectorcache",
             "ingest", "watcher", "classification")
LOGS = ("log.", "logger.", "logging.", "record_failure", "_say_once(", "log_exception")


def _broad(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True
    names = [t] if not isinstance(t, ast.Tuple) else list(t.elts)
    return any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException") for n in names)


def _silent(module: str) -> list[int]:
    tree = ast.parse((APP / f"{module}.py").read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _broad(node):
            if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
                continue
            if any(word in ast.unparse(node) for word in LOGS):
                continue
            out.append(node.lineno)
    return out


@pytest.mark.parametrize("module", INGESTION)
def test_every_broad_catch_in_ingestion_logs_or_reraises(module):
    assert _silent(module) == [], f"{module}.py swallows errors silently at lines {_silent(module)}"


def test_a_page_whose_drawings_cannot_be_read_still_keeps_no_table_and_says_why(caplog):
    """The fallback is unchanged; the log names what failed and the error type only."""
    from app import extract

    class Page:
        def get_drawings(self):
            raise RuntimeError("secret page text must not reach the log")

    with caplog.at_level(logging.DEBUG, logger="app.extract"):
        result = extract.page_tables_checked(Page(), "")
    assert result == ([], "table_get_drawings_failed")
    messages = [r.getMessage() for r in caplog.records if r.name == "app.extract"]
    assert any("get_drawings failed" in m and "RuntimeError" in m for m in messages)
    assert not any("secret page text" in m for m in messages)
