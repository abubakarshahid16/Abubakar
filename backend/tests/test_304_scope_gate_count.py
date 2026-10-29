"""Order 304.1: the read-only counter of what the scope gate would hold back. Invented rows in a throwaway copy."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import scope_gate_count


def _copy(tmp_path, rows):
    path = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, chunk_id TEXT, clause TEXT, page INTEGER,"
        " requirement_text TEXT, source_text TEXT, requirement_type TEXT, superseded_at TEXT);"
        "CREATE TABLE chunks (id TEXT, text TEXT, section TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, text TEXT, error TEXT);"
        "CREATE TABLE documents (id TEXT, filename TEXT);"
        "CREATE TABLE document_classification (document_id TEXT, document_number TEXT);"
        "INSERT INTO documents VALUES ('d1', 'f.pdf');"
        "INSERT INTO document_classification VALUES ('d1', 'INVENTED-1');"
    )
    for n, (clause, chunk_text, section, rtype) in enumerate(rows):
        conn.execute(
            "INSERT INTO chunks VALUES (?,?,?)", (f"c{n}", chunk_text, section)
        )
        conn.execute(
            "INSERT INTO standard_requirements VALUES (?,?,?,?,1,?,?,?,NULL)",
            (
                f"r{n}",
                "d1",
                f"c{n}",
                clause,
                "The casing pressure shall not exceed 25 bar.",
                None,
                rtype,
            ),
        )
    conn.commit()
    conn.close()
    return path


def test_counts_each_outcome_and_prints_no_text(tmp_path, capsys):
    sentence = "The casing pressure shall not exceed 25 bar."
    path = _copy(
        tmp_path,
        [
            ("6.1", f"6.1 Casing\n{sentence}", None, "statement"),
            (
                "6.1",
                f"Mandatory Appendix 6\n6.1 Windows\n{sentence}",
                None,
                "statement",
            ),
            ("2.5", f"Rules for windows\n{sentence}", None, "statement"),
            ("6.1", "", None, "statement"),
            ("6.1", f"6.1 Casing\n{sentence}", None, "recommendation"),
        ],
    )
    assert scope_gate_count.main(["--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert (
        "INVENTED-1: 4 rules (ok: 1, scope_in_appendix: 1, scope_clause_not_printed: 1, no_chunk_text: 1)"
        in out
    )
    assert "shall not exceed" not in out and "2.5" not in out


def test_like_filters_by_label_and_the_database_is_opened_read_only(tmp_path, capsys):
    path = _copy(tmp_path, [("6.1", "6.1 Casing\nText.", None, "statement")])
    scope_gate_count.main(["--db", str(path), "--like", "no such standard"])
    assert capsys.readouterr().out == ""
    before = path.read_bytes()
    scope_gate_count.main(["--db", str(path)])
    assert path.read_bytes() == before


def test_a_missing_database_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        scope_gate_count.main(["--db", str(tmp_path / "nope.sqlite")])


def test_it_says_where_the_clause_is_printed_so_the_title_cannot_hide_a_layout_number(
    tmp_path, capsys
):
    """A clause printed only in the chunk's TITLE counts under "title", not under "chunk text" or "page text"."""
    path = _copy(
        tmp_path,
        [
            (
                "6.1",
                "6.1 Casing\nThe casing pressure shall not exceed 25 bar.",
                "6.1 Casing",
                "statement",
            ),
            (
                "2.5",
                "Rules for windows\nThe casing pressure shall not exceed 25 bar.",
                "2.5 Windows",
                "statement",
            ),
        ],
    )
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO pages VALUES ('d1', 1, '6.1 Casing\nSome text.')")
    conn.commit()
    conn.close()
    scope_gate_count.main(["--db", str(path)])
    out = capsys.readouterr().out
    assert (
        "of 2 rules with a clause: in the chunk's title 2, in the chunk text 1, in the cited page text 1"
        in out
    )


def test_a_scanned_page_is_read_from_its_recognised_text(tmp_path, capsys):
    """The count must read the cited page the way the gates do: recognised text first (s2 on #1454: 146 pages of
    API-520-I are in page_ocr only, so the count could not show the fix)."""
    path = _copy(
        tmp_path,
        [
            (
                "6.1",
                "Rules\nThe casing pressure shall not exceed 25 bar.",
                "Rules",
                "statement",
            )
        ],
    )
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO pages VALUES ('d1', 1, '')")
    conn.execute(
        "INSERT INTO page_ocr VALUES ('d1', 1, '6.1 Casing\nSome text.', NULL)"
    )
    conn.commit()
    conn.close()
    scope_gate_count.main(["--db", str(path)])
    assert "in the cited page text 1" in capsys.readouterr().out
