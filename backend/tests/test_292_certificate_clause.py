"""Order 292.7: a rule's clause number is printed on its cited page, in the standard's style. Invented text."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import certificate_clause as cc

PAGES = {
    1: "5.3 Set pressure\nThe valve is set per 5.4 below.\n 5.3.1 Sizing\ntext",
    2: "5.4.2 Nameplate\ntext",
}


def row(i: str, clause: str | None, page: int | None = 1, quality=None) -> dict:
    return {"id": i, "clause": clause, "page": page, "quality_reason": quality}


def test_a_number_printed_at_a_line_start_is_proven_one_inside_a_sentence_is_not():
    assert cc.printed_on("5.3", PAGES[1])
    assert cc.printed_on("5.3.1", PAGES[1])
    assert not cc.printed_on("5.4", PAGES[1])  # only "per 5.4 below" inside a sentence


def test_a_number_is_not_the_front_of_a_longer_number():
    assert not cc.printed_on("5.3.1", "5.3.10 Other\n")
    assert not cc.printed_on("5.3", "5.3-2 Other\n")
    assert cc.printed_on("5.3", "5.3. Heading\n")


def test_a_clause_on_the_next_page_counts_for_a_heading_that_ends_the_page():
    out = cc.check([row("a", "5.4.2", page=1)], PAGES)
    assert out["flags"] == [] and out["state"] == "passed"


def test_flags_are_named_not_printed_and_missing_pages():
    out = cc.check([row("a", "9.9"), row("b", "5.3", page=7)], PAGES)
    assert sorted(out["flags"]) == [("a", cc.NOT_PRINTED), ("b", cc.NO_PAGE)]
    assert out["state"] == "failed"


def test_a_clause_in_another_style_than_the_standards_is_flagged():
    pages = {1: "\n".join(f"5.{i} Heading" for i in range(1, 8)) + "\n2. Item\n"}
    rows = [row(str(i), f"5.{i}") for i in range(1, 8)] + [row("x", "2.", 1)]
    assert cc.dominant_style(rows) == "decimal"
    pages[1] += "UG-22 text\n"
    assert cc.check(rows + [row("y", "UG-22")], pages)["flags"] == [
        ("y", cc.WRONG_STYLE)
    ]


def test_no_dominant_style_means_the_style_test_is_not_run_and_says_so():
    pages = {1: "5.1 a\nUG-22 b\n1-1 c\n"}
    rows = [row("a", "5.1"), row("b", "UG-22"), row("c", "1-1")]
    out = cc.check(rows, pages)
    assert out["flags"] == [] and out["counts"]["dominant_style"] is None
    assert any("style test was not run" in g for g in out["gaps"])


def test_a_rule_with_no_clause_is_listed_apart_not_failed():
    out = cc.check([row("a", None), row("b", ""), row("c", "5.3")], PAGES)
    assert out["flags"] == [] and out["counts"]["no_clause_listed"] == 2
    assert out["state"] == "passed"


def test_unreadable_text_is_listed_apart():
    out = cc.check([row("a", "9.9", quality="text_quality")], PAGES)
    assert out["flags"] == [] and out["counts"]["unreadable_listed"] == 1


def test_the_state_follows_the_share_and_nothing_judged_is_not_run():
    rows = [row(str(i), "5.3") for i in range(19)] + [row("x", "9.9")]
    assert cc.check(rows, PAGES)["state"] == "gap"
    rows += [row("y", "9.9"), row("z", "9.9")]
    assert cc.check(rows, PAGES)["state"] == "failed"
    assert cc.check([row("a", None)], PAGES)["state"] == "not_run"


def test_the_printout_is_counts_only_and_the_database_is_not_written(tmp_path, capsys):
    path = tmp_path / "copy.sqlite"
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, page INTEGER,"
        " clause TEXT, quality_reason TEXT, superseded_at TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, text TEXT, error TEXT);"
        "INSERT INTO standard_requirements VALUES ('r1','std',1,'5.3',NULL,NULL);"
        "INSERT INTO pages VALUES ('std',1,'5.3 Secret heading words');"
    )
    conn.commit()
    conn.close()
    before = path.read_bytes()
    assert cc.main(["--db", str(path)]) == 0
    printed = capsys.readouterr().out
    assert '"state": "passed"' in printed and "Secret" not in printed
    assert path.read_bytes() == before
    with pytest.raises(SystemExit):
        cc.main(["--db", str(tmp_path / "missing.sqlite")])
