# ruff: noqa: F811
"""The Claude account has no credit (or its usage limit is reached): the review that stopped for it says so in plain words at the top, is
listed as failed (never finished), the file's Summary says it, and the next plan says it before the start. A FAKED refusal: no call is made.
Invented values only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app import (
    aim_review,
    aim_review_gate,
    aim_review_runs,
    aim_review_sheet,
    aim_review_store,
    db,
)
from app.aim_review import engine as E
from tests.test_aim_method_helpers import PAPER as METHOD_PAPER
from tests.test_aim_method_helpers import MemoryStore, open_aim_db
from tests.test_aim_sheet_rule import (  # noqa: F401 - fixtures
    BOOK,
    PAPER,
    RUN,
    _sheet,
    client,
    make_run,
    world,
)
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

NO_CREDIT = "The AI account has no credit left, so the Claude steps cannot run. Choose Local only, or ask the owner to add credit."


class RefusedModel:
    """A model whose first call is refused by the account (the failure the real send path records as `stop account_no_credit`)."""

    def __init__(self, code="account_no_credit"):
        self.code = code

    def ask(self, **kw):
        raise E.StepFailed(f"{kw.get('step', 'aim_identify')}: stop {self.code}")


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def test_the_words_are_the_owners_sentence():
    assert aim_review_gate.NO_CREDIT_WORDS == NO_CREDIT
    assert (
        aim_review_gate.account_words("aim_judge: stop account_no_credit") == NO_CREDIT
    )
    assert "usage limit" in aim_review_gate.account_words(
        "aim_judge: stop account_usage_limit"
    )
    assert (
        aim_review_gate.account_words("aim_judge: no_json") is None
        and aim_review_gate.account_words(None) is None
    )


def test_a_review_refused_by_the_account_stops_with_that_code_and_no_other_cause(
    aim_db,
):
    result = aim_review.run(
        aim_db, run_id="run_nc1", paper_id=METHOD_PAPER, allowed_books=frozenset(), store=MemoryStore(), max_usd=5.0, model=RefusedModel(),
    )  # fmt: skip
    assert result.status == "stopped" and "account_no_credit" in result.stop_reason
    assert aim_review_gate.account_words(result.stop_reason) == NO_CREDIT


def _stopped(code="account_no_credit"):  # the `world` fixture made the run
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET status = 'stopped', stop_reason = ?, created_at = ? WHERE run_id = ?",
            (
                f"aim_judge: stop {code}",
                datetime.now(UTC).isoformat(timespec="seconds"),
                RUN,
            ),
        )


def test_the_results_page_says_it_in_plain_words_and_keeps_the_stop_code(world):
    _stopped()
    page = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert (
        page["status"] == "stopped"
        and page["stop_words"] == NO_CREDIT
        and "account_no_credit" in page["stop_reason"]
    )


def test_the_list_shows_such_a_review_as_failed_with_the_reason_never_as_finished(
    world,
):
    _stopped()
    (row,) = aim_review_runs.entries(db.connect(), frozenset({PAPER}))
    assert row["status"] == "failed" and row["failure_reason"] == NO_CREDIT
    with (
        db.connect() as conn
    ):  # any other stop stays a finished-with-lines review, as before
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET stop_reason = 'run_cap: x' WHERE run_id = ?",
            (RUN,),
        )
    (other,) = aim_review_runs.entries(db.connect(), frozenset({PAPER}))
    assert other["status"] == "completed" and other["failure_reason"] is None


def test_the_team_file_summary_says_it(world):
    _stopped()
    ws = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))[
        aim_review_sheet.SUMMARY
    ]
    cells = [str(c) for row in ws.iter_rows(values_only=True) for c in row if c]
    assert any(NO_CREDIT in c for c in cells)


def test_the_next_plan_says_the_last_review_was_refused_and_says_nothing_otherwise(
    world,
):
    from app import (
        review_engine,  # noqa: F401 - the engine module first (its general half is re-exported from it)
    )
    from app.review_engine_general import _recent_account_refusal

    assert _recent_account_refusal(db.connect()) is None
    _stopped()
    said = _recent_account_refusal(db.connect())
    assert said.startswith("A review's Claude call was refused") and said.endswith(NO_CREDIT)  # past tense, with the time
    with db.connect() as conn:  # a refusal older than a day is not repeated
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET created_at = '2026-01-01T00:00:00+00:00'"
        )
    assert _recent_account_refusal(db.connect()) is None


def test_the_note_clears_as_soon_as_a_later_review_spent_on_claude_and_finished(world):
    """Reviewer's M4: credit may have been added; the note is not kept for 24 hours."""
    from app import review_engine  # noqa: F401 - the engine module first
    from app.review_engine_general import _recent_account_refusal

    _stopped()
    assert _recent_account_refusal(db.connect()) is not None
    with db.connect() as conn:
        conn.execute(
            f"INSERT INTO {aim_review_store.RUNS} (run_id, paper_document_id, status, usd, created_at, finished_at) "
            "VALUES ('later', ?, 'done', 0.0, '2999-01-01T00:00:00+00:00', '2999-01-01T00:05:00+00:00')",
            (PAPER,),
        )
    assert _recent_account_refusal(db.connect()) is not None  # a later review that spent nothing (local) proves nothing about the account
    with db.connect() as conn:
        conn.execute(f"UPDATE {aim_review_store.RUNS} SET usd = 0.42 WHERE run_id = 'later'")
    assert _recent_account_refusal(db.connect()) is None
