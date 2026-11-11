"""scripts/write_block_file.py: the register's hash goes into the block file without a name in the output. Invented data."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from app import claude_approved
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "write_block_file", REPO / "scripts" / "write_block_file.py"
)
cli = importlib.util.module_from_spec(_spec)
sys.modules["write_block_file"] = cli
_spec.loader.exec_module(cli)
REG, OTHER = "ab" * 32, "cd" * 32


def _db(tmp_path):
    p = tmp_path / "x.sqlite"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE documents (id TEXT, filename TEXT, sha256 TEXT)")
    c.executemany(
        "INSERT INTO documents VALUES (?,?,?)",
        [
            ("d1", f"Copy of {claude_approved.REGISTER_NAME_KEY.upper()} (1).pdf", REG),
            ("d2", "datasheet.pdf", OTHER),
        ],
    )
    c.commit()
    c.close()
    return p


def test_the_register_by_name_is_found_in_the_database_and_nothing_else(
    tmp_path, capsys
):
    assert cli.main(["--data-dir", str(tmp_path), "--db", str(_db(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert (
        "hashes found 1" in out
        and REG not in out
        and claude_approved.REGISTER_NAME_KEY[:8] not in out.lower()
    )  # no hash, no name in the output
    assert json.loads((tmp_path / claude_approved.BLOCK_FILE_NAME).read_text())[
        "blocked_sha256"
    ] == [REG]


def test_the_file_written_is_what_the_gate_reads_and_it_blocks_that_hash(
    tmp_path, monkeypatch
):
    cli.main(["--data-dir", str(tmp_path), "--db", str(_db(tmp_path))])
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    assert claude_approved.blocked_hashes() == frozenset({REG})


def test_a_file_is_hashed_and_old_hashes_are_kept(tmp_path, capsys):
    (tmp_path / claude_approved.BLOCK_FILE_NAME).write_text(
        json.dumps({"blocked_sha256": [OTHER]})
    )
    f = tmp_path / "any.bin"
    f.write_bytes(b"invented bytes")
    assert cli.main(["--data-dir", str(tmp_path), "--file", str(f)]) == 0
    got = json.loads((tmp_path / claude_approved.BLOCK_FILE_NAME).read_text())[
        "blocked_sha256"
    ]
    assert OTHER in got and len(got) == 2
    assert "hashes in the file now 2" in capsys.readouterr().out


def test_no_hash_found_writes_nothing_and_a_bad_hash_is_refused(tmp_path, capsys):
    db = tmp_path / "y.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE documents (id TEXT, filename TEXT, sha256 TEXT)")
    c.commit()
    c.close()
    assert cli.main(["--data-dir", str(tmp_path), "--db", str(db)]) == 1
    assert cli.main(["--data-dir", str(tmp_path), "--sha256", "nothex"]) == 1
    assert not (tmp_path / claude_approved.BLOCK_FILE_NAME).exists()
    assert "REFUSED" in capsys.readouterr().out
