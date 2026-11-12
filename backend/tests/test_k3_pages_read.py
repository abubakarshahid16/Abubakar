"""K3 (12 Nov 2026, owner: "5 of 5 pages were not fully read ... is a false statement about reading").

A page the AI page reader was NEVER RUN on (the local engine is barred in a Claude-lane run) is not a page nobody read: the code
readers' reading stands. A page the reader tried and failed on, a page no reader read, and a missing record keep saying so.
INVENTED records; counts and words only."""

from __future__ import annotations

from app import crs_issue, local_engine_bar, page_ledger

SKIP = local_engine_bar.NOTE
COVERAGE = {
    "pages_total": 5,
    "pages_read": [1, 2, 3, 4, 5],
    "pages_not_read_into_fields": [],
    "native": {"text": 5},
}
READER_BARRED = {
    "engine": "ollama",
    "pages": 5,
    "pages_read": 0,
    "code_only": {str(p): SKIP for p in range(1, 6)},
    "timed_out": [],
}


def test_pages_the_ai_reader_was_never_run_on_are_not_unread():
    got = page_ledger.reading_gaps(READER_BARRED, COVERAGE)
    assert got["pages_ai_not_read"] == [] and got["pages_ai_skipped"] == [1, 2, 3, 4, 5]
    assert (
        got["reading"]["status"] == page_ledger.READING_COMPLETE
        and got["reading"]["incomplete_pages"] == []
    )
    assert all(
        "not run" in why for why in got["ai_skipped_reasons"].values()
    )  # said once, in words, as not run


def test_pages_the_ai_reader_tried_and_failed_on_stay_unread():
    reader = {
        **READER_BARRED,
        "code_only": {"1": SKIP, "2": "an unusable answer"},
        "timed_out": [3],
    }
    got = page_ledger.reading_gaps(reader, COVERAGE)
    assert got["pages_ai_not_read"] == [2, 3] and got["pages_ai_skipped"] == [1]
    assert got["reading"]["status"] == page_ledger.READING_INCOMPLETE and got[
        "reading"
    ]["incomplete_pages"] == [2, 3]


def test_a_page_no_code_reader_read_stays_unread_even_when_the_ai_was_not_run():
    cov = {**COVERAGE, "pages_not_read_into_fields": [4]}
    got = page_ledger.reading_gaps(READER_BARRED, cov)
    assert got["reading"]["incomplete_pages"] == [4]
    assert page_ledger.run_unread_pages({**cov, **got}, READER_BARRED) == [4]


def test_a_run_stored_before_the_fix_is_counted_by_what_it_recorded():
    """The shape of the live record that said "5 of 5": pages read natively, the AI reader barred on all five."""
    stored = {
        **COVERAGE,
        "pages_ai_not_read": [1, 2, 3, 4, 5],
        "ai_not_read_reasons": {
            str(p): f"the ollama reader did not read this page ({SKIP})"
            for p in range(1, 6)
        },
    }
    assert page_ledger.run_unread_pages(stored, READER_BARRED) == []
    mixed = {
        **stored,
        "ai_not_read_reasons": {
            **stored["ai_not_read_reasons"],
            "3": "the ollama reader timed out on this page",
        },
    }
    assert page_ledger.run_unread_pages(mixed, None) == [
        3
    ]  # a failure on the same record still counts
    both = {**stored, "pages_not_read_into_fields": [2]}
    assert page_ledger.run_unread_pages(both, None) == [
        2
    ]  # a page no reader read is unread whatever else was skipped


def test_the_sign_gate_asks_no_tick_for_pages_that_were_read_and_one_line_when_the_record_is_missing():
    stored = {
        **COVERAGE,
        "pages_ai_not_read": [1, 2, 3, 4, 5],
        "ai_not_read_reasons": {
            str(p): f"the ollama reader did not read this page ({SKIP})"
            for p in range(1, 6)
        },
    }
    assert crs_issue.pages_to_check(stored, READER_BARRED) == []
    gate = crs_issue.open_items("run-k3", [], stored, READER_BARRED)
    assert (
        gate["unread_pages"] == []
        and crs_issue.NO_PAGE_COVERAGE not in gate["blockers"]
    )
    missing = crs_issue.open_items("run-k3", [], None, None)
    assert (
        crs_issue.NO_PAGE_COVERAGE in missing["blockers"]
        and missing["unread_pages"] == []
    )  # one line, not N ticks


def test_skipped_on_purpose_names_only_the_bars_own_words():
    assert page_ledger.skipped_on_purpose(
        f"x ({SKIP})"
    ) and not page_ledger.skipped_on_purpose("the reader timed out")
    assert not page_ledger.skipped_on_purpose(
        None
    ) and not page_ledger.skipped_on_purpose("")
