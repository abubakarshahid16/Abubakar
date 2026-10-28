"""Order 291.1 point 4: the library order report counts, and prints no document text (invented standards)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "library_order_report.py"


@pytest.fixture(scope="module")
def report():
    spec = importlib.util.spec_from_file_location("library_order_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db(tmp_path: Path, rows) -> Path:
    path = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT,"
        " clause TEXT, page INTEGER, requirement_text TEXT, requirement_type TEXT, superseded_at TEXT)"
    )
    conn.executemany("INSERT INTO standard_requirements VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


ROWS = [
    ("r1", "stdA", "4.1", 3, "The vent shall be 2 m high.", "numeric_limit", None),
    ("r2", "stdA", "4.2", 3, "The line shall be insulated.", "statement", None),
    (
        "r3",
        "stdA",
        None,
        4,
        "The seat shall be tested.",
        "statement",
        None,
    ),  # no clause
    (
        "r4",
        "stdA",
        "4.2",
        5,
        "The  LINE shall be insulated.",
        "statement",
        None,
    ),  # duplicate of r2
    (
        "r5",
        "stdA",
        "3.9",
        6,
        "The pad shall be flat.",
        "statement",
        None,
    ),  # backward, page advances
    (
        "r6",
        "stdA",
        "4.4",
        None,
        "The lid shall be closed.",
        "statement",
        None,
    ),  # no page
    ("r7", "stdA", "4.5", 7, "The vent should be extended.", "recommendation", None),
    (
        "r8",
        "stdA",
        "4.6",
        7,
        "Superseded rule shall go.",
        "statement",
        "2026-10-01",
    ),  # not held
    ("r9", "stdB", "1.1", 1, "Another shall rule here.", "statement", None),
]


def test_the_counts_of_one_standard(report, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "rehearse_requirement_reextraction.refuse_live", lambda p: p, raising=False
    )
    counts, problems = report.run(_db(tmp_path, ROWS), ["stdA"])
    a = counts["stdA"]
    assert (
        a["rules"] == 6 and a["recommendations"] == 1
    )  # r8 superseded; r7 on its own line
    assert (a["without_clause"], a["without_page"], a["duplicate_rows"]) == (1, 1, 1)
    assert a["clause_backward_while_page_advances"] == 1
    assert a["by_type"]["recommendation"] == 1
    assert {why.split(" of ")[0] for _s, _i, why in problems} >= {
        "no clause number",
        "no page",
        "duplicate",
    }


def test_every_standard_is_reported_when_none_is_named(report, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "rehearse_requirement_reextraction.refuse_live", lambda p: p, raising=False
    )
    counts, _ = report.run(_db(tmp_path, ROWS))
    assert sorted(counts) == ["stdA", "stdB"] and counts["stdB"]["rules"] == 1


def test_no_sentence_is_printed(report, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "rehearse_requirement_reextraction.refuse_live", lambda p: p, raising=False
    )
    assert report.main(["--db", str(_db(tmp_path, ROWS))]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["stdA"]["rules"] == 6
    assert "vent" not in out and "insulated" not in out and "4.1" not in out


def test_a_live_shaped_path_is_refused(report, tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    with pytest.raises(SystemExit):
        report.run(live)


def test_the_csv_may_not_go_inside_the_repository(report, tmp_path):
    db = _db(tmp_path, ROWS)
    assert report.main(["--db", str(db), "--csv", str(report.REPO / "out.csv")]) == 2
    assert not (report.REPO / "out.csv").exists()
    out = tmp_path / "problems.csv"
    assert report.main(["--db", str(db), "--csv", str(out)]) == 0
    assert (
        out.read_text().splitlines()[0] == "standard_document_id,requirement_id,problem"
    )
