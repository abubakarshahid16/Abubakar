"""ONE REVIEWER: the trace of a code line is its stored proof, and a line id with a "/" (a tag like "A/B") answers 200. Invented data only."""

from __future__ import annotations

import urllib.parse

from app import agent_review_calculator as calc
from app import agent_review_jobs
from tests.test_agent_review_routes import client, finished_run  # noqa: F401 - fixture
from tests.test_b1_calculator import CLAUSE, ITEM, exit_of, fact, line


def _stored(run_id, ln):
    agent_review_jobs.store_line(run_id, ln, None)
    return ln["item_id"]


def test_a_code_line_trace_is_its_proof_in_plain_fields_and_a_slash_in_the_id_is_200(
    client,
):  # noqa: F811
    run_id = finished_run(client)
    f = fact("85", tag="PSV-1 A/B")
    ln = calc.numeric_line(
        ITEM, calc.requirement_from_item(ITEM), {**f, "id": "x/1"}, submittal_facts=[f],
        page_text="Noise level 85 dB(A)", clause_quote=CLAUSE, clause_text=CLAUSE, page_count=3,
    )  # fmt: skip
    ln = exit_of(ln)
    item = _stored(run_id, ln)
    assert "/" in item and ln["verdict_class"] == "Proven by code"
    got = client.get(
        f"/api/reviews/runs/{run_id}/agent/lines/{urllib.parse.quote(item, safe='')}/trace"
    )
    assert got.status_code == 200, got.text
    body = got.json()
    steps = {g["step"]: g for g in body["gate"]}
    assert (
        body["paper_quote"].endswith("85 dB(A)")
        and body["rule_quote"] == CLAUSE
        and body["page"] == 1
    )
    assert (
        steps["the value and its unit stated inside the paper quote"]["outcome"]
        == "yes"
    )
    assert (
        steps["the value and its unit stated inside the paper quote"]["reason"]
        == "85 dB(A)"
    )
    assert (
        steps["the limit and its unit stated inside the clause quote"]["reason"]
        == "<= 90 dB(A)"
    )
    assert (
        steps["compared by code"]["outcome"] == "meets"
        and steps["decision"]["outcome"] == "Pass"
    )


def test_a_query_code_line_says_which_test_failed(client):  # noqa: F811
    run_id = finished_run(client)
    ln = exit_of(
        line(
            "85", page_text="Noise level 95 dB(A).", source_text="Noise level 95 dB(A)"
        )
    )
    item = _stored(run_id, ln)
    body = client.get(f"/api/reviews/runs/{run_id}/agent/lines/{item}/trace").json()
    steps = {g["step"]: g for g in body["gate"]}
    assert (
        steps["the value and its unit stated inside the paper quote"]["outcome"] == "no"
    )
    assert steps["decision"]["outcome"] != "Pass"
