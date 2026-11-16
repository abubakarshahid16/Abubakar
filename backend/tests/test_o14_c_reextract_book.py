"""Order 14 lane C: scripts/reextract_book.py refuses a live database without the owner's yes, and stops on any NO-GO
before writing. Invented files only; nothing is opened for writing."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location(
        "reextract_book", ROOT / "scripts" / "reextract_book.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_live_shaped_database_is_refused_without_the_owners_yes(tmp_path):
    live = tmp_path / "x" / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    assert _script().main(["--db", str(live), "--doc", "doc_any"]) == 3
    assert live.read_bytes() == b""  # untouched


def test_a_no_go_writes_nothing(tmp_path):
    db = tmp_path / "copy.sqlite"
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT);"
    )
    c.close()
    before = db.read_bytes()
    assert (
        _script().main(["--db", str(db), "--doc", "doc_missing"]) == 2
    )  # the book does not exist
    assert db.read_bytes() == before


def test_the_network_block_ends_with_the_run(tmp_path):
    import socket

    before = socket.socket.connect
    _script().main(["--db", str(tmp_path / "none.sqlite"), "--doc", "d"])
    assert socket.socket.connect is before


# ---- the apply path (R89 item 5): steps stubbed, the orchestration and its checks are real ------------------------------


def _counts(orphaned=0, rows=10, cells="aaa"):
    return {
        "findings_orphaned": orphaned,
        "rules_total": 1,
        "crs": {
            "p1": {
                "page": rows,
                "database": rows,
                "team_rows": rows,
                "contractor_rows": 0,
                "agree": True,
            }
        },
        "crs_cells": {"p1": {"team": {"CRS": {"2|Comment": cells}}}},
    }


def _apply(monkeypatch, tmp_path, before, after, seen=None):
    import socket

    from app import chunker, standards
    from app import db as app_db

    mod = _script()
    db = tmp_path / "copy.sqlite"
    sqlite3.connect(db).close()
    monkeypatch.setattr(mod, "go_no_go", lambda *a, **k: [("all", True, "")])
    monkeypatch.setattr(mod, "backup", lambda *a, **k: {"backup": "b.sqlite"})
    seq = iter([before, after])
    monkeypatch.setattr(mod, "counts", lambda *a, **k: next(seq))

    def step(*_a, **_k):
        try:
            socket.create_connection(("127.0.0.1", 9))
            (seen if seen is not None else []).append("network open")
        except RuntimeError:
            (seen if seen is not None else []).append("network refused")
        return {}

    monkeypatch.setattr(chunker, "chunk_document", step)
    monkeypatch.setattr(standards, "extract_requirements", step)
    monkeypatch.setattr(standards, "extract_table_values", step)

    def fake_connect(*_a, **_k):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")
        return c

    monkeypatch.setattr(app_db, "connect", fake_connect)
    report = tmp_path / "r.json"
    code = mod.main(
        ["--db", str(db), "--doc", "d", "--paper", "p1", "--report", str(report)]
    )
    import json

    return code, json.loads(report.read_text())


def test_the_steps_run_with_the_network_refused(monkeypatch, tmp_path):
    seen: list = []
    code, _ = _apply(monkeypatch, tmp_path, _counts(), _counts(), seen)
    assert code == 0 and seen == ["network refused"] * 3


def test_an_orphaned_finding_fails_the_run_and_prints_the_way_back(
    monkeypatch, tmp_path
):
    code, rep = _apply(monkeypatch, tmp_path, _counts(), _counts(orphaned=2))
    assert (
        code == 1
        and any("no longer resolve" in p for p in rep["problems"])
        and rep["restore"]
    )


def test_a_crs_count_change_fails_the_run(monkeypatch, tmp_path):
    code, rep = _apply(monkeypatch, tmp_path, _counts(), _counts(rows=9))
    assert code == 1 and any("CRS counts" in p for p in rep["problems"])


def test_crs_cell_changes_are_reported_without_text(monkeypatch, tmp_path):
    code, rep = _apply(monkeypatch, tmp_path, _counts(), _counts(cells="bbb"))
    assert code == 0  # reported for the owner, not a failure: counts hold
    assert rep["crs_cell_changes"] == {
        "p1": {
            "team": {
                "CRS": {
                    "rows_changed": 1,
                    "rows": [2],
                    "cells_by_column": {"Comment": 1},
                }
            }
        }
    }
