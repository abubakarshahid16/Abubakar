"""Order 292.8: every stored rule's words must be on the page it cites. Invented standard only."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import db, standards
from tests.test_w6_640_requirements_supersede import (  # noqa: F401
    _standard,
    temp_storage,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import certificate_words as cw

LINES = [
    "5.3 Set pressure",
    "The set pressure shall not exceed the maximum allowable working pressure of 10 bar.",
    "The inlet piping shall be sized so that the pressure drop does not exceed 3 percent.",
    "Each valve shall be fitted with a nameplate showing the set pressure and the capacity.",
]


def fold(text: str) -> str:
    return standards._fold_for_page(text)


def row(i: str, text: str | None, page: int | None, quality: str | None = None) -> dict:
    return {"id": i, "source_text": text, "page": page, "quality_reason": quality}


PAGES = {
    1: fold("5.3 Set pressure. The set pressure shall not exceed the MAWP of 10 bar."),
    2: fold("the inlet piping shall be sized so that the pressure drop is small."),
}


def test_a_sentence_on_its_page_is_proven_whatever_the_spacing_and_hyphens():
    out = cw.check(
        [row("a", "The set  pressure shall not exceed\nthe MAWP of 10-bar.", 1)], PAGES
    )
    assert (
        out["state"] == "passed" and out["counts"]["proven"] == 1 and out["flags"] == []
    )


def test_a_sentence_that_is_not_on_its_page_is_flagged_not_matched_by_overlap():
    # most of the words are on page 2, but not the sentence: "70 percent alike" is not a pass
    cut = "The inlet piping shall be sized so that the pressure drop does not exceed 3 percent."
    out = cw.check([row("a", cut, 2)], PAGES)
    assert out["flags"] == [("a", cw.NOT_ON_PAGE)]
    assert out["state"] == "failed"  # 1 of 1 unproven is above the first-value share


def test_a_sentence_that_runs_over_a_page_break_is_proven_on_the_page_it_starts_on():
    pages = {
        1: fold("The vessel shall be designed for"),
        2: fold("full vacuum at the stated temperature."),
    }
    text = "The vessel shall be designed for full vacuum at the stated temperature."
    assert cw.check([row("a", text, 1)], pages)["state"] == "passed"
    assert cw.check([row("a", text, 2)], pages)["flags"] == [("a", cw.NOT_ON_PAGE)]


def test_a_rule_with_no_sentence_or_a_page_the_document_lacks_is_not_proven():
    out = cw.check(
        [
            row("a", "", 1),
            row("b", "The set pressure shall not exceed", 9),
            row("c", "x" * 20, None),
        ],
        PAGES,
    )
    assert sorted(out["flags"]) == [
        ("a", cw.NO_SENTENCE),
        ("b", cw.NO_PAGE),
        ("c", cw.NO_PAGE),
    ]


def test_unreadable_text_the_extractor_already_flagged_is_listed_apart_not_failed_twice():
    out = cw.check(
        [row("a", "garbled x7q text that is nowhere", 1, quality="text_quality")], PAGES
    )
    assert out["flags"] == [] and out["counts"]["unreadable_listed"] == 1
    assert any("unreadable" in g for g in out["gaps"])


def test_the_state_follows_the_share_of_unproven_rules():
    ok = "The set pressure shall not exceed the MAWP of 10 bar."
    bad = "A sentence the page never had at all."
    rows = [row(str(i), ok, 1) for i in range(19)] + [row("x", bad, 1)]
    assert (
        cw.check(rows, PAGES)["state"] == "gap"
    )  # 1 of 20 = 5 percent, at most the first value
    rows += [row("y", bad, 1), row("z", bad, 1)]
    assert cw.check(rows, PAGES)["state"] == "failed"  # 3 of 22 is more than 10 percent
    assert cw.check([], PAGES)["state"] == "not_run"


def test_the_whole_path_on_a_real_extraction_then_a_page_that_loses_its_text(
    temp_storage,  # noqa: F811
):
    std = _standard(lines=LINES)
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    conn = db.connect()
    first = cw.run(conn, std)
    assert first["state"] == "passed" and first["counts"]["rules"] >= 3
    with conn:
        conn.execute(
            "UPDATE pages SET text = 'nothing of the standard is here' WHERE document_id = ?",
            (std,),
        )
    second = cw.run(conn, std)
    assert second["state"] == "failed"
    assert second["counts"]["by_reason"] == {cw.NOT_ON_PAGE: second["counts"]["rules"]}
    # an OCR-recognised page is read through page_ocr, so recognised text restores the proof
    texts = [
        r[0]
        for r in conn.execute(
            "SELECT source_text FROM standard_requirements WHERE standard_document_id = ?",
            (std,),
        )
    ]
    with conn:
        conn.execute(
            "INSERT INTO page_ocr (document_id, page_no, text, char_count, engine, model, dpi, box_count,"
            " seconds, recognised_at, batch_no, error) VALUES (?, 1, ?, 10, 'e', 'm', 300, 1, 1.0, '2026-10-29', 1, NULL)",
            (std, " ".join(texts)),
        )
    assert cw.run(conn, std)["state"] == "passed"
    # a page whose recognition FAILED keeps an empty row; it must not hide the page's text layer
    with conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ?", (" ".join(texts), std)
        )
        conn.execute(
            "UPDATE page_ocr SET text = '', error = 'timeout' WHERE document_id = ?",
            (std,),
        )
    assert cw.run(conn, std)["state"] == "passed"


def test_the_printout_is_counts_only_and_the_database_is_not_written(tmp_path, capsys):
    import sqlite3

    path = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, page INTEGER,"
        " source_text TEXT, quality_reason TEXT, superseded_at TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, text TEXT, error TEXT);"
        "INSERT INTO standard_requirements VALUES ('r1','std',1,'The set pressure shall not exceed 10 bar.',NULL,NULL);"
        "INSERT INTO pages VALUES ('std',1,'The set pressure shall not exceed 10 bar.');"
    )
    conn.commit()
    conn.close()
    before = path.read_bytes()
    assert cw.main(["--db", str(path)]) == 0
    printed = capsys.readouterr().out
    assert '"state": "passed"' in printed and "set pressure" not in printed
    assert path.read_bytes() == before
    with pytest.raises(SystemExit):
        cw.main(["--db", str(tmp_path / "missing.sqlite")])
