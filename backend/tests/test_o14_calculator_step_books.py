"""Order 14, lane A: the calculator STEP of the AI review job passes its book lookup to the checklist lines, so a checklist result
that cites a book the library does not hold reaches the run as "book missing", with no clause, no rule words and no verdict.
An invented paper, book name and result; no network, no model."""

from __future__ import annotations

import json

import pytest
from app import checklist_scope
from app.config import settings
from tests.test_agent_review_job import (  # noqa: F401 - fixture
    lines_of,
    run_job,
    start,
    world,
)
from tests.test_b1_calculator_step import fact, frame_item


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_calculator_enabled", True)


def test_a_checklist_line_of_a_book_not_held_is_book_missing_in_the_run(
    world, on, monkeypatch
):  # noqa: F811
    frame_item()
    f = fact(label="Coating thickness", raw="0.35", unit="mm")
    result = {
        "rule_id": "INVENTED-01", "status": "NON_COMPLIANT", "fact_id": f["id"], "value": "0.35 mm", "page": 1,
        "field": "Coating thickness", "text": "Our own words for the check.", "detail": "0.35 mm is below the limit.",
        "standard": "INVENTED BOOK 999", "clause": "7.1",
    }  # fmt: skip
    monkeypatch.setattr(checklist_scope, "evaluate", lambda *a, **k: [dict(result)])
    run_id, job_id = start()
    run_job(job_id)
    rows = [
        json.loads(v["line_json"])
        for k, v in lines_of(run_id).items()
        if k.startswith("C-INVENTED-01")
    ]
    assert rows
    for x in rows:
        assert (
            x["standard"] == "book missing: INVENTED BOOK 999"
            and x["clause"] == ""
            and x["clause_quote"] == ""
        )
        assert (
            x["verdict"] == "Query"
            and x["check_words"] == "Our own words for the check."
        )
