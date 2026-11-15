"""V2: every CRS route takes the same copy words. company = internal; contractor = issue. Invented data."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import crs_copy_words as words
from tests.test_crs_endpoint import _client, _run, _submittal, temp_db  # noqa: F401


def test_both_spellings_reach_the_copy_each_route_already_knew():
    assert [words.rule_check_copy(w) for w in ("internal", "company", "Company", " INTERNAL ")] == ["internal"] * 4
    assert [words.rule_check_copy(w) for w in ("issue", "contractor", "Contractor")] == ["issue"] * 3
    assert [words.agent_copy(w) for w in ("internal", "company")] == ["internal"] * 2
    assert [words.agent_copy(w) for w in ("contractor", "issue")] == ["contractor"] * 2


@pytest.mark.parametrize("bad", ["", "draft", "contract", "internal;issue"])
def test_any_other_word_is_still_refused(bad):
    for fn in (words.rule_check_copy, words.agent_copy):
        with pytest.raises(HTTPException) as caught:
            fn(bad)
        assert caught.value.status_code == 422 and "company" in caught.value.detail


def test_the_routes_answer_company_like_internal_and_contractor_like_issue(temp_db):  # noqa: F811
    doc = _submittal()
    run_id = _run(doc)
    client = _client(doc)
    base = client.get(f"/api/reviews/runs/{run_id}/crs?copy=internal")
    assert base.status_code == 200
    same = client.get(f"/api/reviews/runs/{run_id}/crs?copy=company")
    assert same.status_code == 200 and same.headers["content-type"] == base.headers["content-type"]
    issue = client.get(f"/api/reviews/runs/{run_id}/crs?copy=issue")
    contractor = client.get(f"/api/reviews/runs/{run_id}/crs?copy=contractor")
    assert contractor.status_code == issue.status_code and contractor.text == issue.text  # same gate, same sentence
    assert client.get(f"/api/reviews/runs/{run_id}/crs?copy=nonsense").status_code == 422
    prev_a = client.get(f"/api/reviews/runs/{run_id}/crs/preview?copy=internal").json()
    prev_b = client.get(f"/api/reviews/runs/{run_id}/crs/preview?copy=company").json()
    assert prev_a == prev_b
