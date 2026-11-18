# ruff: noqa: F811
"""The Review page lists general reviews (order 14, #1899 blocker). Before this a general review never showed in the runs list and the
counts said "0 findings". Invented papers only. A general run is listed beside the earlier reviews, newest first, with its OWN numbers;
a caller sees it only when the caller may read its paper (rule 5)."""

from __future__ import annotations

import pytest

from app import db
from tests.test_aim_sheet_rule import BOOK, PAPER, client, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_aim_sheet_rule import _doc


@pytest.fixture
def world(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run("gen_old", created="2026-11-17T10:00:00Z")
    make_run("gen_new", created="2026-11-18T17:44:00Z")
    _earlier("rr_between", "2026-11-18T09:00:00Z")


def _earlier(run_id: str, created: str, paper: str = PAPER) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, paper, "completed", created, created, created),
        )


def _runs(*allowed, **params):
    r = client(*allowed).get("/api/reviews/runs", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_list_holds_general_and_earlier_reviews_newest_first(world):
    got = _runs(PAPER, BOOK)
    ids = [r["review_run_id"] for r in got["runs"]]
    assert ids == ["gen_new", "rr_between", "gen_old"] and got["total"] == 3


def test_a_general_review_carries_its_own_numbers_not_tiers(world):
    row = {r["review_run_id"]: r for r in _runs(PAPER, BOOK)["runs"]}["gen_new"]
    assert row["method"] == "general" and row["status"] == "completed"
    counts = row["general_counts"]
    assert counts["points"] >= counts["comments"] >= 0 and counts["points"] > 0
    assert (
        row["findings_total"] == 0 and row["by_status"] == {}
    )  # no earlier-method tiers


def test_an_earlier_review_keeps_its_own_summary_and_no_general_numbers(world):
    row = {r["review_run_id"]: r for r in _runs(PAPER, BOOK)["runs"]}["rr_between"]
    assert row["method"] is None and row["general_counts"] is None


def test_a_caller_who_may_not_read_the_paper_sees_no_general_review(world):
    got = _runs(BOOK)  # may read only the book
    assert got["runs"] == [] and got["total"] == 0


def test_the_per_file_history_narrows_to_that_paper_and_keeps_both_methods(world):
    _doc("doc_inv_other", "other.pdf")
    make_run("gen_other", paper="doc_inv_other", created="2026-11-18T12:00:00Z")
    got = _runs(PAPER, BOOK, "doc_inv_other", document_id=PAPER)
    assert [r["review_run_id"] for r in got["runs"]] == [
        "gen_new",
        "rr_between",
        "gen_old",
    ]


def test_a_general_run_that_has_not_ended_has_no_numbers_never_zero(world):
    make_run("gen_running", status="running", created="2026-11-18T18:00:00Z")
    row = {r["review_run_id"]: r for r in _runs(PAPER, BOOK)["runs"]}["gen_running"]
    assert row["status"] == "running" and row["general_counts"] is None


def test_the_counts_route_gives_a_general_review_its_own_numbers_apart_from_the_tiers(
    world,
):
    r = client(PAPER, BOOK).get(
        "/api/reviews/runs/counts", params={"ids": ["gen_new", "rr_between"]}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "gen_new" not in body["counts"] and body["general"]["gen_new"]["points"] > 0
    assert "rr_between" in body["counts"] and "rr_between" not in body["general"]


def test_the_counts_route_leaves_out_a_general_review_the_caller_may_not_read(world):
    body = (
        client(BOOK).get("/api/reviews/runs/counts", params={"ids": ["gen_new"]}).json()
    )
    assert body["counts"] == {} and body["general"] == {}


def test_the_counts_route_says_the_earlier_ai_reviewers_lines_apart_from_the_findings(world):
    """Those lines are stored outside the findings table, so the earlier counter said 0 for them: the route now gives their count
    (only for a run that has some), and the tier counts stay as they were."""
    with db.connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS agent_review_line (run_id TEXT NOT NULL)")
        conn.executemany("INSERT INTO agent_review_line (run_id) VALUES (?)", [("rr_between",)] * 55)
    body = client(PAPER, BOOK).get("/api/reviews/runs/counts", params={"ids": ["rr_between"]}).json()
    assert body["ai_lines"] == {"rr_between": 55}
    assert body["counts"]["rr_between"]["total"] == 0  # the findings count is unchanged: it is truly 0 for that table


def test_a_run_with_no_ai_line_is_absent_from_the_ai_lines_never_zero(world):
    body = client(PAPER, BOOK).get("/api/reviews/runs/counts", params={"ids": ["rr_between"]}).json()
    assert body["ai_lines"] == {}
