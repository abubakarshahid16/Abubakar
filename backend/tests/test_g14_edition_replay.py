"""Order 14 lane G: `scripts/edition_replay.py` on an invented stored run (invented books, dates and cutoff)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "edition_replay", REPO / "scripts" / "edition_replay.py"
)
er = importlib.util.module_from_spec(_SPEC)
sys.modules["edition_replay"] = er
_SPEC.loader.exec_module(er)  # type: ignore[union-attr]


def _copy(tmp_path) -> Path:
    db = tmp_path / "copy.sqlite"
    c = sqlite3.connect(db)
    c.executescript(
        """CREATE TABLE documents (id TEXT, filename TEXT);
        CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);
        CREATE TABLE standard_requirements (standard_document_id TEXT);
        CREATE TABLE review_runs (id TEXT, submittal_document_id TEXT);
        CREATE TABLE agent_review_line (run_id TEXT, rule_book TEXT);
        CREATE TABLE agent_review_missing_book (run_id TEXT, name TEXT);"""
    )
    c.executemany(
        "INSERT INTO documents VALUES (?, ?)",
        [("b1", "API-9991.pdf"), ("b2", "API-9992.pdf"), ("p", "paper.pdf")],
    )
    c.executemany(
        "INSERT INTO pages VALUES (?, ?, ?)",
        [
            ("b1", 1, "Issue Date: 14 March 2007"),
            ("b2", 1, "Issue Date: 2 May 2012"),
            ("p", 1, "Built to API 9991 (2007)."),
        ],
    )
    c.executemany("INSERT INTO standard_requirements VALUES (?)", [("b1",), ("b2",)])
    c.execute("INSERT INTO review_runs VALUES ('r', 'p')")
    c.executemany(
        "INSERT INTO agent_review_line VALUES ('r', ?)",
        [("API-9991",), ("API-9991",), ("API-9992",)],
    )
    c.execute("INSERT INTO agent_review_missing_book VALUES ('r', 'API-9999')")
    c.commit()
    c.close()
    return db


def test_the_replay_judges_each_cited_book_against_the_local_cutoff_and_writes_nothing(
    tmp_path, monkeypatch
):
    db = _copy(tmp_path)
    cutoff = tmp_path / "local.json"
    cutoff.write_text(
        json.dumps(
            {
                "contracts": {
                    "project-contract": {"rule": "in_effect_on", "date": "2011-03"}
                }
            }
        )
    )
    monkeypatch.setenv("EDITION_CUTOFF_FILE", str(cutoff))
    before = db.stat().st_mtime_ns
    rep = er.replay(str(db), "r")
    by = {r["book"]: r for r in rep["books"]}
    assert [r["book"] for r in rep["books"]] == [
        "API-9991",
        "API-9992",
        "API-9999",
    ]  # most cited first, then not held
    assert (
        by["API-9991"]["status"] == "held edition binds"
        and by["API-9991"]["printed"]["page"] == 1
    )
    assert (
        by["API-9992"]["status"]
        == "held edition is later than the cutoff: for information only"
    )
    assert by["API-9999"]["status"] == "book not held: edition not known"
    assert by["API-9991"]["paper_cites"] == "2007"
    assert rep["counts"] == {"held edition binds": 1, "held edition is later than the cutoff: for information only": 1,
                             "book not held: edition not known": 1}  # fmt: skip
    assert db.stat().st_mtime_ns == before
