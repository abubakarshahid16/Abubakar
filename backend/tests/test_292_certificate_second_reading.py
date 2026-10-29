"""Order 292.10: a second, independent reading of a sample of pages, compared with the stored rules. Invented text."""

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
import certificate_second_reading as sr

SET = "The set pressure shall not exceed the maximum allowable working pressure of 10 bar."
INLET = "The inlet piping shall be sized so that the pressure drop does not exceed 3 percent."
DEF = "A relief valve is a device that opens at a set pressure."


def row(i: str, text: str, page: int = 1) -> dict:
    return {"id": i, "page": page, "source_text": text}


PAGES = {1: f"5.3 Set pressure\n{SET} {INLET} {DEF}"}


def test_the_second_reader_keeps_only_normative_sentences_and_repairs_hyphens():
    got = sr.sentences(
        "The valve shall be fit-\nted with a name plate. A valve is a device."
    )
    assert len(got) == 1 and "fitted" in got[0]
    assert sr.sentences("Short shall.") == []  # too short to be a rule


def test_agreement_on_every_normative_sentence_passes_and_a_definition_is_out_of_scope():
    out = sr.check([row("a", SET), row("b", INLET), row("c", DEF)], PAGES)
    assert out["state"] == "passed" and out["flags"] == []
    assert out["counts"]["agreed"] == 2 and out["counts"]["out_of_scope_listed"] == 1
    assert out["counts"]["disagreement_rate"] == 0 and out["counts"]["of"] == 2


def test_a_stored_rule_the_second_reading_did_not_see_is_flagged():
    odd = "The vessel shall be painted in a colour the page never printed anywhere."
    out = sr.check([row("a", SET), row("b", INLET), row("x", odd)], PAGES)
    assert out["flags"] == [("x", sr.UNSEEN)]
    assert out["counts"]["unseen_by_second_reading"] == 1
    assert out["state"] == "failed"  # 1 of 3 is far above 2 percent


def test_a_normative_sentence_no_stored_rule_covers_is_counted_as_missed():
    out = sr.check([row("a", SET)], PAGES)
    assert out["counts"]["missed_by_store"] == 1 and out["flags"] == []
    assert out["counts"]["of"] == 2 and out["counts"]["disagreement_rate"] == 0.5
    assert out["state"] == "failed"


def test_a_disagreement_at_or_below_two_percent_is_a_gap_not_a_fail():
    texts = [
        f"Item number {i:03d} of the list shall be inspected before delivery."
        for i in range(60)
    ]
    pages = {1: " ".join(texts)}
    rows = [row(str(i), t) for i, t in enumerate(texts)]
    assert sr.check(rows, pages)["state"] == "passed"
    out = sr.check(
        rows[:-1], pages
    )  # one sentence missed by the store: 1 of 60 is 1.7 percent
    assert out["counts"]["disagreement_rate"] == pytest.approx(0.0167, abs=1e-4)
    assert out["state"] == "gap"


def test_a_rule_on_another_page_does_not_agree_with_this_pages_sentence():
    out = sr.check([row("a", SET, page=2)], {1: PAGES[1], 2: "Nothing here."})
    assert (
        out["counts"]["missed_by_store"] == 2
    )  # page 1's two sentences have no stored rule on page 1


def test_the_sample_is_evenly_spaced_and_the_same_every_time():
    pages = {n: f"page {n} text" for n in range(1, 101)}
    first = sr.sample(pages, 10)
    assert first == sr.sample(pages, 10) and len(first) == 10
    assert first[0] == 1 and first[-1] >= 90
    assert sr.sample({1: "a", 2: "  "}, 10) == [
        1
    ]  # a page without text is not compared
    assert sr.check([], {}, 10)["state"] == "not_run"


def test_the_whole_path_on_a_real_extraction(temp_storage):  # noqa: F811
    std = _standard(lines=["5.3 Set pressure", SET, INLET, DEF])
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    conn = db.connect()
    out = sr.run(conn, std)
    assert out["counts"]["pages_compared"] >= 1 and out["counts"]["agreed"] >= 2
    assert out["state"] in ("passed", "gap")


def test_the_printout_is_counts_only_and_the_database_is_not_written(tmp_path, capsys):
    import sqlite3

    path = tmp_path / "copy.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE standard_requirements (id TEXT, standard_document_id TEXT, page INTEGER,"
        " source_text TEXT, superseded_at TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, text TEXT, error TEXT);"
    )
    conn.execute(
        "INSERT INTO standard_requirements VALUES ('r1','std',1,?,NULL)", (SET,)
    )
    conn.execute("INSERT INTO pages VALUES ('std',1,?)", (SET,))
    conn.commit()
    conn.close()
    before = path.read_bytes()
    assert sr.main(["--db", str(path)]) == 0
    printed = capsys.readouterr().out
    assert '"state": "passed"' in printed and "set pressure" not in printed
    assert path.read_bytes() == before
    with pytest.raises(SystemExit):
        sr.main(["--db", str(tmp_path / "missing.sqlite")])
