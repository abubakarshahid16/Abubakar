"""Order 292.9: which stored rules sit outside the main body of their standard. Invented standard only."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import certificate_scope as cs

PAGES = {
    1: "1 Scope\nThis standard covers relief valves.",
    2: "5 Sizing\nThe set pressure shall not exceed 10 bar.",
    3: "MANDATORY APPENDIX 9\nJACKETED VESSELS\nThe set pressure shall not exceed 5 bar.",
    4: "More text of the appendix.",
    5: "",
}


def row(i: str, page):
    return {"id": i, "page": page}


def test_rules_in_the_main_body_pass():
    out = cs.check([row("a", 1), row("b", 2)], PAGES)
    assert out["state"] == "passed" and out["counts"]["main_body"] == 2
    assert out["flags"] == [] and out["gaps"] == []


def test_a_rule_under_an_appendix_is_flagged_and_counted_by_region_never_failed():
    out = cs.check([row("a", 2), row("b", 3), row("c", 4)], PAGES)
    assert out["state"] == "gap"
    assert out["flags"] == [("b", cs.OUTSIDE), ("c", cs.OUTSIDE)]
    assert out["counts"]["by_region"] == {"Appendix 9": 2}
    assert out["gaps"] == ["2 rule(s) under Appendix 9"]


def test_a_rule_in_a_worked_example_is_flagged_apart():
    pages = {1: "5 Sizing\nExample 1: gas relief\nA vessel at 10 bar is relieved."}
    out = cs.check([row("a", 1)], pages)
    assert out["flags"] == [("a", cs.IN_EXAMPLE)] and out["state"] == "gap"


def test_a_rule_on_a_page_with_no_text_is_unknown_not_main_body():
    out = cs.check([row("a", 5), row("b", 2), row("c", 2), row("d", 2)], PAGES)
    assert out["flags"] == [("a", cs.NO_PAGE_TEXT)]
    assert out["counts"]["main_body"] == 3 and out["state"] == "gap"


def test_a_rule_with_no_page_or_a_page_the_document_lacks_is_unknown():
    out = cs.check(
        [
            row("a", None),
            row("b", 99),
            row("c", 1),
            row("d", 1),
            row("e", 1),
            row("f", 1),
        ],
        PAGES,
    )
    assert set(out["flags"]) == {("a", cs.NO_PAGE_TEXT), ("b", cs.NO_PAGE_TEXT)}


def test_when_too_many_rules_have_no_page_text_the_check_fails():
    out = cs.check([row("a", 5), row("b", 99), row("c", 1)], PAGES)
    assert out["state"] == "failed"  # 2 of 3 unknown is above the first-value share
    assert out["counts"]["no_page_text_share"] == 0.6667


def test_a_standard_with_no_rules_is_not_run():
    assert cs.check([], PAGES)["state"] == "not_run"


def test_the_read_functions_use_the_text_layer_and_prefer_recognised_text():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);
           CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, text TEXT, error TEXT);
           CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, page INTEGER, superseded_at TEXT);"""
    )
    conn.execute("INSERT INTO pages VALUES ('d', 1, '1 Scope\nText.')")
    conn.execute("INSERT INTO pages VALUES ('d', 2, '')")
    conn.execute(
        "INSERT INTO page_ocr VALUES ('d', 2, 'ANNEX A (normative)\nRecognised text.', NULL)"
    )
    conn.execute("INSERT INTO page_ocr VALUES ('d', 1, '', 'failed')")
    conn.execute("INSERT INTO standard_requirements VALUES ('r1', 'd', 2, NULL)")
    conn.execute("INSERT INTO standard_requirements VALUES ('r2', 'd', 1, NULL)")
    conn.execute(
        "INSERT INTO standard_requirements VALUES ('r3', 'd', 1, '2026-10-28')"
    )
    out = cs.run(conn, "d")
    assert out["flags"] == [("r1", cs.OUTSIDE)]
    assert out["counts"] == {
        **out["counts"],
        "rules": 2,
        "main_body": 1,
        "outside_main_body": 1,
    }
    assert out["counts"]["by_region"] == {"Annex A": 1}
