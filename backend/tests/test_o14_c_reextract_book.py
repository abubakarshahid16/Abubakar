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
