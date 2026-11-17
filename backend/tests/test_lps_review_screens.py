"""Order 14 LPS (17 Nov 2026): the review list's "Found by the review" number and the kind line of the review page. Invented data.

S2  the review list's number has ONE home, the paper's page (`review_points_service.found_of`): the page's tile totals with their
    boundary, for the runs the page is built from; an older run, or a paper the caller may not read, is absent (never 0).
S3  the page's kind line is the kind the review USED (`agent_review_run`), "guessed" only when that run used a guess.
"""

from __future__ import annotations

import pytest

from app import agent_review_kind, db
from app.config import settings
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, points_of
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)


def _paper_with_both():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    rc = _run(doc, recommended="Approved with Comments")
    _finding(doc, rc, "NON_COMPLIANT")
    ai = ai_run(doc, [mk("R-1", "Fail", "Fail"), mk("R-3", "Query", "Fail", why="no second opinion"), mk("R-8", "Query", None, why="x y")])
    with db.connect() as conn:  # an OLDER finished AI review of the same paper: its page is not this run's
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            ("old-ai", doc, "completed", "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, usd, started_at) VALUES (?,?,?,?,?,?)",
            ("old-ai", doc, "datasheet", "test", 0.1, "2020-01-01T00:00:00Z"),
        )
    return doc, rc, ai


def test_s2_the_list_number_is_the_pages_tiles_for_the_pages_runs_and_nothing_for_an_older_run():
    doc, rc, ai = _paper_with_both()
    client = _client(doc, "doc_std")
    listing = points_of(client, doc)
    tiles = listing["counts"]["tiles"]
    found = listing["found"]
    assert (found["not_met"], found["questions"], found["met"], found["does_not_apply"]) == (
        tiles["not_met"]["total"], tiles["questions"]["total"], tiles["met"]["total"], tiles["does_not_apply"]["total"],
    )
    assert found["questions"] > 0 and found["points"] == listing["of"] and found["undecided"] == listing["of"] - listing["decided"]
    r = client.get("/api/reviews/page-counts", params=[("ids", ai), ("ids", rc), ("ids", "old-ai"), ("ids", "no-such-run")])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["found"]) == {ai, rc}  # the page's two runs; the older run and an unknown id are absent, never 0
    assert body["found"][ai] == body["found"][rc] == found
    assert "page" in body["boundary"] and "you may read" in body["boundary"]
    # the run's own count said "0 findings" (an AI review's run holds no rule-check findings): it is now absent there (the older list
    # then says nothing), while the rule check's own count stays
    old = client.get("/api/reviews/runs/counts", params=[("ids", ai), ("ids", rc)]).json()["counts"]
    assert ai not in old and rc in old and found["not_met"] + found["questions"] > 0


def test_s2_a_paper_the_caller_may_not_read_is_absent_and_the_route_is_off_with_the_page():
    doc, _rc, ai = _paper_with_both()
    other = _client("doc_std")  # rule 5: may not read the paper
    assert other.get("/api/reviews/page-counts", params=[("ids", ai)]).json()["found"] == {}
    settings.review_page_v2_enabled = False
    assert _client(doc).get("/api/reviews/page-counts", params=[("ids", ai)]).status_code == 404


@pytest.mark.parametrize(
    ("source", "guess", "known"),
    [
        (agent_review_kind.SOURCE_READ, False, True),
        (agent_review_kind.SOURCE_CONFIRMED, False, True),
        (agent_review_kind.SOURCE_GUESS, True, True),
        (agent_review_kind.SOURCE_NONE, False, False),
    ],
)
def test_s3_the_kind_line_is_the_kind_the_run_used_and_a_guess_only_when_the_run_guessed(source, guess, known):
    doc, _rc, ai = _paper_with_both()
    with db.connect() as conn:
        conn.execute(
            "UPDATE agent_review_run SET paper_kind = ?, kind_source = ? WHERE run_id = ?",
            ("procedure" if known else agent_review_kind.UNKNOWN, source, ai),
        )
    used = points_of(_client(doc, "doc_std"), doc)["kind_used"]
    assert used["run_id"] == ai and used["guess"] is guess and used["known"] is known
    assert used["kind"] == ("procedure" if known else None)
    assert used["confirmed"] is (source == agent_review_kind.SOURCE_CONFIRMED)


def test_s3_without_an_ai_review_there_is_no_run_kind():
    doc = _submittal()
    rc = _run(doc)
    _finding(doc, rc, "NON_COMPLIANT")
    assert points_of(_client(doc), doc)["kind_used"] is None
