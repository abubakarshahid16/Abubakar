"""ONE REVIEWER (lead A): the calculator never runs on values of an earlier text of the paper, and a page with no usable value is read first by the one datasheet
reader. Invented data only."""

from __future__ import annotations

import hashlib
import json

import pytest

from app import agent_review_calculator_reader as R
from app import datasheet_ai, datasheets, db
from app.config import settings
from tests import agent_review_support as s
from tests.test_b1_calculator_step import (  # noqa: F401 - fixtures and helpers
    code_lines,
    frame_item,
    lines_of,
    on,
    outcome,
    run_job,
    start,
    world,
)

PAGES = {1: "Coating thickness: 0.35 mm\nMarking blue", 2: "Other page"}


def sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ current or stale


def test_a_fact_is_current_while_its_page_has_the_checksum_it_was_read_from():
    f = {"page": 1, "page_text_sha": sha(PAGES[1]), "source_text": "anything"}
    assert R.is_current(f, PAGES)
    assert not R.is_current({**f, "page_text_sha": sha("an earlier text")}, PAGES)


def test_a_fact_without_a_checksum_is_current_only_while_its_quote_is_on_the_page():
    assert R.is_current({"page": 1, "source_text": "Coating thickness: 0.35 mm"}, PAGES)
    assert not R.is_current(
        {"page": 1, "source_text": "Coating thickness: 0.2 mm"}, PAGES
    )
    assert not R.is_current(
        {"page": 3, "source_text": "x"}, PAGES
    )  # the page has no text now


def test_a_blank_fact_is_kept_and_the_split_counts_the_stale_ones():
    blank = {"page": 1, "is_blank": 1, "page_text_sha": sha("old")}
    old = {"page": 2, "page_text_sha": sha("old")}
    now = {"page": 1, "page_text_sha": sha(PAGES[1])}
    keep, stale = R.split_current([blank, old, now], PAGES)
    assert len(keep) == 2 and stale == 1


def test_pages_with_text_and_no_current_value_are_the_ones_to_read():
    assert R.pages_to_read([{"page": 1, "raw_value": "5"}], PAGES) == [2]
    assert R.pages_to_read([{"page": 1, "is_blank": 1}], PAGES) == [
        1,
        2,
    ]  # a blank is no value
    assert R.pages_to_read([], {1: "  ", 2: "x"}) == [2]


# ------------------------------------------------------------------------------------------------ the reader


def fake_reader(facts_by_page, engine="ollama"):
    def read_pages(page_texts, engine_or_callable=None):
        return {
            "engine": engine,
            "pages": {p: {"facts": facts_by_page.get(p, [])} for p in page_texts},
            "reasons": {},
            "stopped": None,
        }

    return read_pages


def test_off_it_reads_nothing_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_reader_first_enabled", False)
    got, note = R.read_missing("d", PAGES, [])
    assert got == [] and note["ran"] is False and note["reason"] == "reading first is off"


def test_on_the_reader_engine_off_says_so_and_reads_nothing(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_reader_first_enabled", True)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    got, note = R.read_missing("d", PAGES, [])
    assert (
        got == [] and note["ran"] is False and "DATASHEET_AI_READER" in note["reason"]
    )


def test_on_the_pages_without_a_value_are_read_and_come_back_as_in_memory_facts(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ai_review_reader_first_enabled", True)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    fact = {
        "field": "Coating thickness",
        "value": "0.35",
        "unit": "mm",
        "quote": "Coating thickness: 0.35 mm",
        "kind": "offered",
    }
    monkeypatch.setattr(datasheet_ai, "read_pages", fake_reader({1: [fact]}))
    got, note = R.read_missing("d", PAGES, [])
    assert (
        note["ran"] is True
        and note["facts"] == 1
        and note["pages_wanted"] == 2
        and note["engine"] == "ollama"
    )
    f = got[0]
    assert (f["id"], f["page"], f["raw_value"], f["raw_unit"], f["source_text"]) == (
        "ai:1:0",
        1,
        "0.35",
        "mm",
        "Coating thickness: 0.35 mm",
    )
    assert (
        json.loads(f["bbox"])["quote_on_page"] is True
        and f["extraction_method"] == "model"
    )


def test_a_reader_that_fails_never_fails_the_review(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_reader_first_enabled", True)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(datasheet_ai, "read_pages", boom)
    got, note = R.read_missing("d", PAGES, [])
    assert got == [] and note["ran"] is False and "RuntimeError" in note["reason"]


def test_when_every_page_has_a_current_value_nothing_is_read(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_reader_first_enabled", True)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    got, note = R.read_missing(
        "d", PAGES, [{"page": 1, "raw_value": "5"}, {"page": 2, "raw_value": "6"}]
    )
    assert got == [] and note["reason"] == "every page has a current value"


# ------------------------------------------------------------------------------------------------ in the job


def test_a_stored_fact_gets_the_checksum_of_its_page_when_it_is_made(world):
    f = datasheets.create_fact(
        submittal_document_id=s.PAPER, chunk_id=f"{s.PAPER}:c0", field_label="Coating thickness", raw_value="0.35", page=1, unit="mm",
        source_text="Coating thickness: 0.35 mm",
    )  # fmt: skip
    row = (
        db.connect()
        .execute("SELECT page_text_sha FROM submittal_facts WHERE id = ?", (f["id"],))
        .fetchone()
    )
    text = (
        db.connect()
        .execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = 1", (s.PAPER,)
        )
        .fetchone()[0]
    )
    assert row[0] == sha(text)


def _fact(**kw):
    return datasheets.create_fact(
        submittal_document_id=s.PAPER, chunk_id=f"{s.PAPER}:c0", field_label="Coating thickness", raw_value="0.35", page=1, unit="mm",
        source_text="Coating thickness: 0.35 mm", **kw,
    )  # fmt: skip


def test_a_stale_value_is_not_compared_and_the_run_says_how_many(world, on):
    frame_item()
    f = _fact()
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET page_text_sha = ? WHERE id = ?",
            (sha("an earlier text of this page"), f["id"]),
        )
    run_id, job_id = start()
    run_job(job_id)
    note = outcome(run_id)["calculator"]
    assert (
        note["stale_values"] == 1
        and note["stale_note"]
        == "1 stored values belong to an earlier text of this paper and were not used"
    )
    assert not [
        k for k in code_lines(run_id) if k.startswith("C-R-frame")
    ]  # nothing was compared


def test_a_current_value_is_compared_as_before(world, on):
    frame_item()
    f = _fact()
    run_id, job_id = start()
    run_job(job_id)
    assert outcome(run_id)["calculator"]["stale_values"] == 0
    assert lines_of(run_id)[f"C-R-frame-{f['id']}"]["verdict_class"] == "Proven by code"


def test_with_reading_first_on_a_page_with_no_stored_value_is_read_and_proven(
    world, on, monkeypatch
):
    frame_item()
    monkeypatch.setattr(settings, "ai_review_reader_first_enabled", True)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    fact = {
        "field": "Coating thickness",
        "value": "0.35",
        "unit": "mm",
        "quote": "Coating thickness: 0.35 mm",
        "kind": "offered",
    }
    monkeypatch.setattr(datasheet_ai, "read_pages", fake_reader({1: [fact]}))
    run_id, job_id = start()
    run_job(job_id)
    note = outcome(run_id)["calculator"]
    assert note["reader_first"]["ran"] is True and note["reader_first"]["facts"] == 1
    got = [v for k, v in code_lines(run_id).items() if k.startswith("C-R-frame-ai:1:0")]
    assert got and got[0]["verdict_class"] == "Proven by code"
    assert (
        db.connect().execute("SELECT COUNT(*) FROM submittal_facts").fetchone()[0] == 0
    )  # nothing was written to the facts table


def test_with_reading_first_off_the_calculator_uses_the_stored_facts_only(
    world, on, monkeypatch
):
    frame_item()
    called = []
    monkeypatch.setattr(
        datasheet_ai, "read_pages", lambda *a, **k: called.append(1) or {}
    )
    run_id, job_id = start()
    run_job(job_id)
    assert (
        called == [] and outcome(run_id)["calculator"]["reader_first"]["ran"] is False
    )
