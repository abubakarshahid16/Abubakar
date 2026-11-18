# ruff: noqa: F811
"""The Review dashboard counts a paper's NEWEST review, general reviews included; a signed one is done (order 14, owner 18 Nov 2026).
Invented papers only."""

from __future__ import annotations

import pytest

from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import (
    BOOK,
    PAPER,
    _accept_all,
    _page,
    _sign,
    client,
    world,  # noqa: F401 - fixture
)

DASH = "/api/reviews/dashboard"


def dash(c):
    r = c.get(DASH)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_general_review_is_the_papers_newest_and_awaits_its_sign_off(world):
    c = client(PAPER, BOOK)
    d = dash(c)
    (row,) = d["recent"]
    assert row["method"] == "general" and row["submittal_document_id"] == PAPER
    page = _page(c)
    # the counts are the results page's own
    assert row["general_counts"]["comments"] == page["counts"]["comments"]
    assert row["general_counts"].get("confirmations") == page["counts"].get(
        "confirmations"
    )
    assert row["general_signoff"] == "not_signed"
    assert (
        d["reviews_awaiting_decision"],
        d["reviews_signed"],
        d["reviews_running"],
    ) == (1, 0, 0)
    assert (
        d["papers_with_a_review"] == d["reviews_total"] == 1
        and d["earlier_runs_not_counted"] == 0
    )


def test_a_signed_general_review_is_done_not_awaiting(world):
    c = client(PAPER, BOOK)
    _accept_all(c)
    assert _sign(c, statement="Checked against the datasheet.").status_code == 200
    d = dash(c)
    assert d["recent"][0]["general_signoff"] == "signed"
    assert (d["reviews_awaiting_decision"], d["reviews_signed"]) == (0, 1)


def test_a_decision_after_the_sign_off_makes_it_awaiting_again(world):
    from tests.test_g_signoff import BASE, RUN

    c = client(PAPER, BOOK)
    _accept_all(c)
    assert _sign(c, statement="Checked against the datasheet.").status_code == 200
    first = _page(c)["comments"][0]["n"]
    r = c.post(
        f"{BASE}/decision",
        json={
            "run_id": RUN,
            "comment": first,
            "state": "reject",
            "reason": "Invented reason for the test.",
        },
    )
    assert r.status_code == 200, r.text
    d = dash(c)
    assert d["recent"][0]["general_signoff"] == "changed"
    assert (d["reviews_awaiting_decision"], d["reviews_signed"]) == (1, 0)


@pytest.mark.parametrize("allowed", [(), ("doc_some_other_paper",)])
def test_a_reader_who_may_not_open_the_paper_sees_no_trace_of_its_review(
    world, allowed
):
    d = dash(client(*allowed))
    assert d["recent"] == [] and d["reviews_total"] == 0 and d["reviews_signed"] == 0
    assert d["reviews_awaiting_decision"] == 0 and d["papers_with_a_review"] == 0


def test_a_failed_or_stopped_general_review_is_a_reason_to_look(world):
    from app import db

    with db.connect() as conn:
        conn.execute(
            "UPDATE aim_runs SET status = 'stopped', stop_reason = 'invented stop'"
        )
    d = dash(client(PAPER, BOOK))
    assert d["needs_attention_reasons"].get("the review stopped early") == 1
    assert d["needs_attention"] == sum(d["needs_attention_reasons"].values())
