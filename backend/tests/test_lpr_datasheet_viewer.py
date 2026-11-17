"""Rule 5 on the AI run file, the lines tab and the trace (order 14, found on PR #1876): a DATASHEET line whose rule book the viewer
may not read shows him none of the book's words (its name, clause, rule words, the AI's free words about it), on every one of the
three surfaces, through the one guard `review_points.for_viewer`; a reader of the book gets exactly what he got before; both get the
same number of rows (a hidden line is counted, never named). Invented values only."""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app import agent_review_jobs
from app import review_points as rp
from app.config import settings
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, sheet_text
from tests.test_crs_endpoint import _client, _submittal, temp_db  # noqa: F401 - fixture

BOOK, RULE_WORDS, AI_WORDS = (
    "STD-1",
    "Nameplates shall be steel and fixed",
    "It is steel",
)
OTHER_BOOK = "STD-9"  # another name the hidden book is cited by (invented)
SECRETS = (BOOK, RULE_WORDS, AI_WORDS, OTHER_BOOK)
BOOK_DOC = "doc_std"


@pytest.fixture(autouse=True)
def on(monkeypatch, temp_db):  # noqa: F811
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)


def world() -> tuple[str, str]:
    """A paper and its AI run against the held book BOOK_DOC: a proven Fail, a query, and two lines with no field that one rule
    groups into one comment (invented)."""
    doc = _submittal()
    _submittal(BOOK_DOC, "STD-A-001.pdf")
    lines = [
        mk("R-1", "Fail", "Fail"),
        mk(
            "R-8",
            "Query",
            None,
            why=f"the clause of {BOOK} was not confirmed",  # the book's name inside another text
        ),
        mk("R-21", "Query", "Fail", why="no second opinion", field="", field_roles=[]),
        mk("R-22", "Query", "Fail", why="no second opinion", field="", field_roles=[]),
        # the same clause and words of ANOTHER name of the hidden book: its own comment for both viewers (numbered, never merged)
        mk(
            "R-23",
            "Query",
            "Fail",
            why="no second opinion",
            field="",
            field_roles=[],
            standard=OTHER_BOOK,
        ),
    ]
    return doc, ai_run(doc, lines, book_doc=BOOK_DOC)


def full():
    return _client(
        DOC[0], BOOK_DOC
    )  # the scope override is global: made again before each use


def restricted():
    return _client(DOC[0])


DOC: list[str] = []


def setup_world() -> str:
    doc, ai = world()
    DOC[:] = [doc]
    return ai


def sheet_rows(data: bytes) -> dict[str, int]:
    wb = load_workbook(io.BytesIO(data))
    return {
        ws.title: sum(
            1 for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)
        )
        for ws in wb.worksheets
    }


def test_the_run_file_shows_a_restricted_viewer_none_of_the_books_words_and_the_same_rows():
    ai = setup_world()
    url = f"/api/reviews/runs/{ai}/agent/crs?copy=internal"
    hidden = restricted().get(url)
    assert hidden.status_code == 200, hidden.text
    shown = full().get(url).content
    text = sheet_text(hidden.content)
    assert not any(s in text for s in SECRETS), text
    assert rp.HIDDEN_BOOK in text and "clause 4.1" not in text
    assert "clause 4.1" in sheet_text(shown)
    assert all(s in sheet_text(shown) for s in SECRETS)
    # counted, never named: the same rows on every sheet, and the two lines of one rule are one comment for both viewers
    assert sheet_rows(hidden.content) == sheet_rows(shown)
    assert "Part of comment" in sheet_text(shown) and "Part of comment" in text
    stored = (agent_review_jobs.run_dir(ai) / "crs-internal.xlsx").read_bytes()
    assert shown == stored  # the reader of the book gets the stored file, byte for byte


def test_the_lines_tab_and_the_trace_show_a_restricted_viewer_none_of_the_books_words():
    ai = setup_world()
    lines_url = f"/api/reviews/runs/{ai}/agent/lines"
    hidden, shown = restricted().get(lines_url), full().get(lines_url)
    assert hidden.status_code == 200, hidden.text
    assert not any(s in hidden.text for s in SECRETS), hidden.text
    assert BOOK in shown.text
    assert len(hidden.json()["lines"]) == len(shown.json()["lines"])
    for item in ("R-1", "R-8"):
        url = f"/api/reviews/runs/{ai}/agent/lines/{item}/trace"
        got = restricted().get(url)
        assert got.status_code == 200, got.text
        assert not any(s in got.text for s in SECRETS), (item, got.text)
        assert BOOK in full().get(url).text


def test_a_full_viewers_lines_tab_and_trace_are_unchanged_by_the_guard(monkeypatch):
    ai = setup_world()
    before = [
        full().get(f"/api/reviews/runs/{ai}/agent/lines").json(),
        full().get(f"/api/reviews/runs/{ai}/agent/lines/R-1/trace").json(),
    ]
    monkeypatch.setattr(rp, "for_viewer", lambda line, ctx: line)  # the guard off
    after = [
        full().get(f"/api/reviews/runs/{ai}/agent/lines").json(),
        full().get(f"/api/reviews/runs/{ai}/agent/lines/R-1/trace").json(),
    ]
    assert before == after


def test_two_viewers_of_one_run_file_never_share_a_file():
    from app import review_points_service as svc

    ai = setup_world()
    folder = agent_review_jobs.run_dir(ai)
    pid = next(
        p["id"]
        for p in full().get(f"/api/reviews/papers/{DOC[0]}/points").json()["points"]
        if p["id"].endswith(":R-8")
    )
    assert (
        full()
        .post(
            f"/api/reviews/papers/{DOC[0]}/points/decision",
            json={"point_id": pid, "state": "keep"},
        )
        .status_code
        == 200
    )
    mine = svc.decided_ai_sheet(
        ai, DOC[0], "internal", folder, frozenset({DOC[0], BOOK_DOC})
    )
    theirs = svc.decided_ai_sheet(ai, DOC[0], "internal", folder, frozenset({DOC[0]}))
    assert mine.name != theirs.name
    assert not any(s in sheet_text(theirs.read_bytes()) for s in SECRETS)
    assert all(s in sheet_text(mine.read_bytes()) for s in SECRETS)


def test_equal_hidden_values_keep_one_number_and_different_ones_differ():
    names = rp.HiddenNames()
    a, b = (
        names.of("book", "std 1", rp.HIDDEN_BOOK),
        names.of("book", "std 2", rp.HIDDEN_BOOK),
    )
    assert a != b and names.of("book", "std 1", rp.HIDDEN_BOOK) == a
