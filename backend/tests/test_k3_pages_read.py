"""K3 (12 Nov 2026, owner: "5 of 5 pages were not fully read ... is a false statement about reading"), with R53's findings.

A page the AI page reader was NEVER RUN on (the local engine is barred in a Claude-lane run) is read from its own text and is not
an unread page; a page the reader tried and failed on, a page no reader read, a thin page and a missing record keep their words.
The records are built by the REAL writers (`datasheet_ai.read_pages` under the bar, `datasheets.reader_summary`). INVENTED text."""

from __future__ import annotations

from app import (
    comparison,
    crs_issue,
    datasheet_ai,
    datasheets,
    local_engine_bar,
    page_ledger,
)
from app.config import settings

TEXT = "Design pressure 12 bar. Design temperature 80 C. Material carbon steel. " * 3
COVERAGE = {
    "pages_total": 5,
    "pages_read": [1, 2, 3, 4, 5],
    "pages_not_read_into_fields": [],
    "native": {"text": 5},
    "fact_pages": [1, 2, 3, 4, 5],
}


def real_reader(pages: dict[int, str] | None = None) -> dict:
    """The record the app really writes for a run whose AI page reader was barred: the writer's output, then the summary."""
    pages = pages or dict.fromkeys(range(1, 6), TEXT)
    with local_engine_bar.bar():
        ai_run = datasheet_ai.read_pages(pages, "ollama")
    return datasheets.reader_summary(ai_run, {}, pages=sorted(pages))


def outage_reader() -> dict:
    """A reader that really failed (not barred): the same summary shape, no skip marker, an outage as the reason."""
    return {
        **real_reader(),
        "skipped_on_purpose": [],
        "code_only": {},
        "unavailable": "ollama engine unavailable (ConnectionError)",
    }


# ---- point 1: one predicate, a structured marker from the writer, the text as the fallback in one place


def test_the_writer_marks_the_pages_it_never_ran_on_and_the_summary_carries_the_marker():
    reader = real_reader()
    assert reader["skipped_on_purpose"] == [1, 2, 3, 4, 5]
    assert reader["unavailable"] == local_engine_bar.NOTE and set(
        reader["code_only"].values()
    ) == {local_engine_bar.NOTE}


def test_the_bars_exact_words_are_pinned_so_a_reworded_note_fails_here():
    assert (
        local_engine_bar.NOTE == "skipped: local engine not loaded in a Claude-lane run"
    )
    assert local_engine_bar.is_bar_note(
        f"x ({local_engine_bar.NOTE})"
    ) and not local_engine_bar.is_bar_note("the reader timed out")
    assert not local_engine_bar.is_bar_note(None) and not local_engine_bar.is_bar_note(
        ""
    )


def test_the_real_barred_record_is_complete_with_nothing_unread_and_says_so_once():
    got = page_ledger.reading_gaps(real_reader(), COVERAGE)
    assert got["pages_ai_not_read"] == [] and got["pages_ai_skipped"] == [1, 2, 3, 4, 5]
    assert (
        got["reading"]["status"] == page_ledger.READING_COMPLETE
        and got["reading"]["incomplete_pages"] == []
    )
    assert page_ledger.run_unread_pages({**COVERAGE, **got}, real_reader()) == []
    assert got["ai_skipped_line"] == (
        "The AI page reader did not run on 5 pages in this review (skipped: local engine not loaded in a Claude-lane run); "
        "they were read from their own text."
    )


def test_a_record_stored_before_the_marker_is_told_apart_by_the_text_in_the_one_fallback():
    old = {k: v for k, v in real_reader().items() if k != "skipped_on_purpose"}
    got = page_ledger.reading_gaps(old, COVERAGE)
    assert (
        got["pages_ai_not_read"] == []
        and got["reading"]["status"] == page_ledger.READING_COMPLETE
    )
    assert "ai_skipped_line" in got


def test_a_failure_stays_a_failure_even_beside_pages_skipped_on_purpose():
    reader = {
        **real_reader(),
        "code_only": {"1": local_engine_bar.NOTE, "2": "an unusable answer"},
        "unavailable": None,
        "timed_out": [3],
        "skipped_on_purpose": [1],
    }
    got = page_ledger.reading_gaps(reader, COVERAGE)
    assert got["pages_ai_not_read"] == [2, 3] and got["pages_ai_skipped"] == [1]
    assert got["reading"]["status"] == page_ledger.READING_INCOMPLETE and got[
        "reading"
    ]["incomplete_pages"] == [2, 3]
    other = {
        **outage_reader(),
        "unavailable": "ollama engine unavailable (ConnectionError)",
    }
    assert page_ledger.reading_gaps(other, COVERAGE)["reading"]["incomplete_pages"] == [
        1,
        2,
        3,
        4,
        5,
    ]  # a real outage is not a skip


# ---- point 2: the Pass is not held, the sign gate and How-reviewed list nothing unread


def test_a_pass_is_not_held_by_a_barred_ai_reader_but_is_held_by_a_real_failure():
    codes = comparison.review_codes()
    complete = {**COVERAGE, **page_ledger.reading_gaps(real_reader(), COVERAGE)}
    findings = [
        {
            "compliance_status": "COMPLIANT",
            "requirement_id": "r1",
            "severity": "major",
            "origin": "rule",
        }
    ]
    kept = comparison.recommend_code(
        findings,
        {
            "basis": comparison.BASIS_REQUIRED_FIELDS,
            "fields_required": 1,
            "fields_answered": 1,
            "sufficient": True,
            "extraction_coverage": 1.0,
        },
        page_coverage=complete,
    )
    assert "the reading is incomplete" not in kept["reason"]
    failed_reader = {
        **outage_reader(),
        "unavailable": "ollama engine unavailable (ConnectionError)",
    }
    incomplete = {**COVERAGE, **page_ledger.reading_gaps(failed_reader, COVERAGE)}
    held = comparison.recommend_code(
        findings,
        {
            "basis": comparison.BASIS_REQUIRED_FIELDS,
            "fields_required": 1,
            "fields_answered": 1,
            "sufficient": True,
            "extraction_coverage": 1.0,
        },
        page_coverage=incomplete,
    )
    assert held["code"] == codes[3] and "the reading is incomplete" in held["reason"]


def test_the_sign_gate_asks_no_tick_for_pages_that_were_read_and_one_line_when_the_record_is_missing():
    cov = {**COVERAGE, **page_ledger.reading_gaps(real_reader(), COVERAGE)}
    assert crs_issue.pages_to_check(cov, real_reader()) == []
    gate = crs_issue.open_items("run-k3", [], cov, real_reader())
    assert (
        gate["unread_pages"] == []
        and crs_issue.NO_PAGE_COVERAGE not in gate["blockers"]
    )
    missing = crs_issue.open_items("run-k3", [], None, None)
    assert (
        crs_issue.NO_PAGE_COVERAGE in missing["blockers"]
        and missing["unread_pages"] == []
    )  # one line, not N ticks


def test_the_run_stored_before_the_fix_in_the_live_shape_counts_zero_unread():
    stored = {
        **COVERAGE,
        "pages_ai_not_read": [1, 2, 3, 4, 5],
        "ai_not_read_reasons": {
            str(
                p
            ): f"the ollama reader did not read this page ({local_engine_bar.NOTE})"
            for p in range(1, 6)
        },
    }
    assert page_ledger.run_unread_pages(stored, real_reader()) == []
    assert page_ledger.run_unread_pages(
        {**stored, "pages_not_read_into_fields": [2]}, None
    ) == [2]


# ---- point 4: the unsafe side: a page counts as read from its text only by a stated measure


def test_a_five_character_page_with_the_ai_reader_skipped_is_not_fully_read_with_one_tick():
    cov = {**COVERAGE, "pages_thin": [3]}
    got = page_ledger.reading_gaps(
        real_reader({1: TEXT, 2: TEXT, 3: "12 bar", 4: TEXT, 5: TEXT}), cov
    )
    assert (
        got["pages_ai_not_read"] == [3]
        and got["ai_not_read_reasons"]["3"] == page_ledger.LITTLE_TEXT
    )
    assert got["reading"]["incomplete_pages"] == [3] and got["pages_ai_skipped"] == [
        1,
        2,
        4,
        5,
    ]
    assert page_ledger.run_unread_pages({**cov, **got}, None) == [3]


def test_a_title_block_only_page_with_no_field_found_and_the_ai_reader_skipped_is_not_fully_read():
    cov = {**COVERAGE, "fact_pages": [1, 2, 3, 5], "pages_read_no_field": [4]}
    got = page_ledger.reading_gaps(real_reader(), cov)
    assert (
        got["pages_ai_not_read"] == [4]
        and got["ai_not_read_reasons"]["4"] == page_ledger.LITTLE_TEXT
    )


def test_a_scan_stays_unread_by_the_ledger_whatever_the_ai_reader_did():
    cov = {
        **COVERAGE,
        "pages_not_read_into_fields": [2],
        "native": {"needs_ocr": 1, "text": 4},
    }
    got = page_ledger.reading_gaps(real_reader(), cov)
    assert got["reading"]["incomplete_pages"] == [2] and page_ledger.run_unread_pages(
        {**cov, **got}, None
    ) == [2]


def test_the_thin_measure_is_the_apps_own_minimum_and_the_ledger_reports_it(
    tmp_path, monkeypatch
):
    from app import db
    from tests import agent_review_support as s

    s.setup_world(tmp_path, monkeypatch)
    conn = db.connect()
    s.add_document(conn, "doc_k3", "k3.pdf", "x" * 5)
    conn.execute("UPDATE pages SET needs_ocr = 0 WHERE document_id = 'doc_k3'")
    conn.commit()
    page_ledger.refresh("doc_k3")
    assert settings.ocr_min_usable_chars > 5
    cov = page_ledger.coverage("doc_k3")
    assert cov.get("pages_thin") == [1]


def test_the_pages_line_says_it_once_where_the_reason_is_built():
    got = page_ledger.reading_gaps(real_reader(), COVERAGE)
    line = page_ledger.every_page_read({**COVERAGE, **got}, "5", 5)
    assert line.startswith(
        "fields were read from every page (5 of 5). The AI page reader did not run on 5 pages in this review"
    )
    assert (
        page_ledger.every_page_read(COVERAGE, "5", 5)
        == "fields were read from every page (5 of 5)"
    )  # no skip: as it was
