"""#645 slice 3: a requirement quoted from a chunk ACROSS pages. Slices 1-2
refused it (no guessed page). With `ai_requirement_quote_page_enabled`, code
cites it to the ONE page whose own text holds the whole quote; none (the quote
crosses the page break) or several: refused, as before. Accept checks the
quote on that page again. A fake model stands in for the local one. Invented
clauses only."""

from __future__ import annotations

import pytest

from app import ai_requirement_chunks as arc
from app import ai_requirement_tables as art
from app import ai_requirements as air
from app.config import settings
from app.db import connect
from tests.test_645_chunk_extraction import TEXT, drafts, item, reply
from tests.test_645_chunk_extraction import run as run_chunk
from tests.test_645_table_comparators import MIN_MAX, raw_page, row_item
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixture
    _doc,
    review_run,
    temp_storage,
)

OTHER = "Section 4 covers the scope of the coating work."


@pytest.fixture
def standard(monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", True)
    monkeypatch.setattr(settings, "ai_requirement_quote_page_enabled", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    _doc("std", "STD-1.pdf", "COMPANY_STANDARD")
    return "std"


def run(model_reply, text, pages: dict[int, str]):
    """A chunk over pages 1..N, each page stored with its own text."""
    with connect() as conn:
        for no, page in pages.items():
            conn.execute(
                "INSERT OR REPLACE INTO pages (document_id, page_no, text, char_count,"
                " batch_no) VALUES ('std', ?, ?, 1, 0)",
                (no, page),
            )
    return run_chunk(model_reply, text, page_end=max(pages))


def stored_pages() -> set[int]:
    return {
        r["page"]
        for r in connect().execute(
            "SELECT page FROM standard_requirements WHERE extraction_method = 'extracted'"
        )
    }


def accept(draft_id: str) -> dict:
    return air.decide_draft(
        draft_id,
        decision="accept",
        allowed_document_ids=frozenset({"std"}),
        actor={"id": None},
    )


def test_a_sentence_on_the_second_page_is_cited_to_that_page(standard):
    report = run(reply(item()), OTHER + "\n" + TEXT, {1: OTHER, 2: TEXT})
    assert report["proposed"] == 1 and report["refused"] == {}
    assert stored_pages() == {2}
    [draft] = drafts()
    assert (draft["operator"], draft["value"], draft["unit"]) == ("<=", "10", "bar")


def test_switch_off_a_chunk_across_pages_is_refused_as_before(standard, monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_quote_page_enabled", False)
    report = run(reply(item()), OTHER + "\n" + TEXT, {1: OTHER, 2: TEXT})
    assert report["proposed"] == 0 and report["refused"] == {arc.PAGE_UNCERTAIN: 1}
    assert drafts() == []


def test_a_quote_that_crosses_the_page_break_is_refused(standard):
    first, second = (
        "The hydrostatic test pressure shall",
        "not exceed 10 bar.",
    )
    report = run(reply(item()), first + "\n" + second, {1: first, 2: second})
    assert report["proposed"] == 0 and report["refused"] == {arc.PAGE_UNCERTAIN: 1}
    assert drafts() == []


def test_a_quote_on_two_pages_is_refused_not_cited_to_either(standard):
    report = run(reply(item()), TEXT + "\n" + TEXT, {1: TEXT, 2: TEXT})
    assert report["proposed"] == 0 and report["refused"] == {arc.PAGE_UNCERTAIN: 1}


def test_a_page_with_no_stored_text_is_not_a_page_of_the_quote(standard):
    report = run(reply(item()), OTHER + "\n" + TEXT, {1: OTHER, 2: ""})
    assert report["proposed"] == 0 and report["refused"] == {arc.PAGE_UNCERTAIN: 1}


def test_a_single_page_chunk_is_unchanged(standard):
    report = run(reply(item()), TEXT, {1: TEXT})
    assert report["proposed"] == 1 and stored_pages() == {1}
    version = connect().execute(
        "SELECT extractor_version FROM standard_requirements"
    ).fetchone()[0]
    assert version is None  # the slice-1 sentence draft, no page re-check added


def test_accept_checks_the_sentence_on_its_page_again(standard):
    run(reply(item()), OTHER + "\n" + TEXT, {1: OTHER, 2: TEXT})
    [draft] = drafts()
    with connect() as conn:
        conn.execute("UPDATE pages SET text = ? WHERE page_no = 2", (OTHER,))
    with pytest.raises(air.DraftError, match=art.QUOTE_NOT_ON_PAGE):
        accept(draft["id"])


def test_an_accepted_draft_keeps_its_page(standard):
    run(reply(item()), OTHER + "\n" + TEXT, {1: OTHER, 2: TEXT})
    [draft] = drafts()
    done = accept(draft["id"])
    page = (
        connect()
        .execute(
            "SELECT page FROM standard_requirements WHERE id = ?",
            (done["new_requirement_id"],),
        )
        .fetchone()[0]
    )
    assert done["status"] == air.ACCEPTED and page == 2


def test_a_table_on_the_second_page_is_cited_to_that_page(standard):
    report = run(
        reply(row_item()), OTHER + "\n" + MIN_MAX, {1: OTHER, 2: raw_page(MIN_MAX)}
    )
    assert report["proposed"] == 2 and stored_pages() == {2}
    maximum = next(d for d in drafts() if d["operator"] == "<=")
    assert accept(maximum["id"])["status"] == air.ACCEPTED


def test_a_table_whose_header_and_row_are_on_different_pages_is_refused(standard):
    header, rows = MIN_MAX.split("\n", 1)
    report = run(
        reply(row_item()),
        MIN_MAX,
        {1: raw_page(header), 2: raw_page(rows)},
    )
    assert report["proposed"] == 0 and arc.PAGE_UNCERTAIN in report["refused"]
    assert drafts() == []


def test_a_table_refusal_that_needs_no_page_keeps_its_own_reason(standard):
    report = run(
        reply(row_item(operator=">=", value="10")),
        OTHER + "\n" + MIN_MAX,
        {1: OTHER, 2: raw_page(MIN_MAX)},
    )
    assert report["refused"] == {air.OPERATOR_DISAGREED: 1}


@pytest.mark.parametrize(
    ("quote", "page", "want"),
    [
        ("shall not exceed 10 bar", "It  SHALL not\nexceed 10 bar.", True),
        ("shall not exceed 10 bar", "shall not exceed 100 bar", False),
        ("", "anything", False),
        ("shall not exceed 10 bar", None, False),
    ],
)
def test_quote_on_page_reading(quote, page, want):
    assert art.quote_on_page(quote, page) is want
