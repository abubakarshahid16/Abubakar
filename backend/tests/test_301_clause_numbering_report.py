"""Order 301.3: the clause-numbering report counts clause STYLES, read-only, on a copy. Invented rows only."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import clause_numbering_report as report  # noqa: E402


@pytest.mark.parametrize(
    ("clause", "style"),
    [
        (None, "none"),
        ("", "none"),
        ("  ", "none"),
        ("7.16", "decimal"),
        ("5.3.4.1", "decimal"),
        ("7.", "decimal"),
        ("UG-22", "dashed"),
        ("UW-12", "dashed"),
        ("A-1", "dashed"),
        ("UG-99(c)", "dashed"),
        ("1-1", "number_dash_number"),
        ("13-5", "number_dash_number"),
        ("Appendix 6", "other"),
        ("7", "other"),
    ],
)
def test_a_clause_is_classified_by_its_shape_alone(clause, style):
    assert report.style_of(clause) == style


def _db(path: Path, clauses: list[str | None], superseded_last: bool = False) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE standard_requirements (standard_document_id TEXT, clause TEXT, superseded_at TEXT)"
    )
    for i, clause in enumerate(clauses):
        stamp = "2026-10-28" if superseded_last and i == len(clauses) - 1 else None
        conn.execute(
            "INSERT INTO standard_requirements VALUES ('std-1', ?, ?)", (clause, stamp)
        )
    conn.commit()
    conn.close()
    return path


def test_the_report_counts_each_style_and_leaves_out_superseded_rows(tmp_path):
    db = _db(
        tmp_path / "copy.sqlite",
        [
            "UG-22",
            "UG-22",
            "UW-12",
            "7.16",
            "7.16",
            "7.16",
            None,
            "1-1",
            "Appendix 6",
            "5.5",
        ],
        superseded_last=True,
    )
    conn = sqlite3.connect(db)
    out = report.report_document(conn, "std-1", top=2)
    assert out["requirements"] == 9
    assert out["by_style"] == {
        "dashed": 3,
        "decimal": 3,
        "none": 1,
        "number_dash_number": 1,
        "other": 1,
    }
    assert out["distinct_clauses"]["dashed"] == 2
    assert out["most_common"]["decimal"][0] == ("7.16", 3)


def test_the_report_refuses_a_live_shaped_path_and_a_missing_file(tmp_path, capsys):
    with pytest.raises(SystemExit):
        report.main(["--db", str(tmp_path / "nope.sqlite")])
    live = tmp_path / "backend" / "data"
    live.mkdir(parents=True)
    _db(live / "rag_intelligence.sqlite", ["UG-22"])
    with pytest.raises(SystemExit):
        report.main(["--db", str(live / "rag_intelligence.sqlite")])


def test_the_report_prints_json_with_clause_numbers_and_counts_only(tmp_path, capsys):
    db = _db(tmp_path / "copy.sqlite", ["UG-22", "7.16"])
    assert report.main(["--db", str(db)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["std-1"]["by_style"] == {"dashed": 1, "decimal": 1}
    assert set(out["std-1"]) == {
        "requirements",
        "by_style",
        "distinct_clauses",
        "most_common",
    }


def test_the_database_is_opened_read_only(tmp_path):
    db = _db(tmp_path / "copy.sqlite", ["UG-22"])
    before = db.read_bytes()
    report.main(["--db", str(db)])
    assert db.read_bytes() == before
