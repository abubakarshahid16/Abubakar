"""#870: when the cloud model's call FAILS, the AI engineering check and the
CRS wording run on the local model and say so.

Found on the first live review with the Claude reader (12 Oct 2026): from one
moment on every Claude call was refused by the API with HTTP 400 - the
account's credit was finished. The check kept 0 items and the wording tried
0, although the local model had done both on the run before. #838 falls back
to the local model only when the call is refused as "not approved".

Now a failed call (an API error, a time-out) is followed by the local model,
labelled on the run. A budget cap is NOT a failed call: it is the owner's
limit, and it stays a stop that is shown and never replaced. What the cloud
model produced before it failed is kept.

Every provider is a fake. Synthetic sheet only.
"""
from __future__ import annotations

import json

import pytest

from app import ai_engineering_check as aic
from app import claude_spend, crs_wording, review_jobs
from app import reasoning_provider as rp
from app.config import settings
from tests.test_763_crs_ai_wording import GOOD as GOOD_WORDING
from tests.test_763_crs_ai_wording import ROW
from tests.test_838_local_when_not_approved import SHEET, STANDARD, Cloud, Local, _approve
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import ASKS_A_BLANK, BLANK_FIELD, GOOD, _ai_rows, _blank_fields  # noqa: F401
from tests.test_review_ai_check import _resolver, world  # noqa: F401 - fixtures

API_ERROR = rp.ProviderRefused("claude: HTTP 400")


@pytest.fixture
def lane(monkeypatch):
    """The cloud lane on for every step, every document of the review
    approved, and the local engine replaced by a recorder."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)
    monkeypatch.setattr(rp, "OllamaProvider", Local)
    _blank_fields(monkeypatch, {1: [BLANK_FIELD]})
    _approve(SHEET, STANDARD)
    Local.made, Local.answer = [], json.dumps({"items": [ASKS_A_BLANK]})

    def install(cloud):
        monkeypatch.setattr(rp, "get_provider", lambda *a, **k: cloud)
        monkeypatch.setattr(crs_wording, "_provider", lambda: cloud)
        return cloud
    return install


def _asked_locally() -> int:
    return sum(len(p.packets) for p in Local.made)


# ------------------------------------------------- the AI engineering check

def test_a_failed_cloud_call_is_followed_by_the_local_model_and_the_run_says_so(world, lane):  # noqa: F811
    _sub, run, scope = world
    cloud = lane(Cloud(raises=API_ERROR))
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 1 and _asked_locally() == 1          # asked once, failed, then local
    assert result["kept"] == 1 and result["complete"] is True and len(_ai_rows(run)) == 1
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["local_instead"] == rp.CLOUD_CALL_FAILED == result["local_instead"]
    assert status["model"].startswith(rp.OLLAMA + ":") and status["local_pages"]["done"] == [1]
    assert "ran on the local model: the cloud model's call failed" in status["plain"]
    assert status["calls_made"] == 2                                   # the failed one is counted


def test_a_budget_cap_is_not_a_failed_call_and_is_never_replaced(world, lane):  # noqa: F811
    _sub, run, scope = world
    cloud = lane(Cloud(raises=claude_spend.BudgetExceeded("the step cap of USD 5.00 would be crossed")))
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 1 and Local.made == []
    assert result["kept"] == 0 and result["local_instead"] is None
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert "a budget cap stopped the call" in status["plain"] and "local model" not in status["plain"]


def test_a_cloud_call_that_works_is_not_followed_by_anything(world, lane):  # noqa: F811
    _sub, run, scope = world
    cloud = lane(Cloud(answer=json.dumps({"items": [GOOD]})))
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 1 and Local.made == [] and result["local_instead"] is None


def test_what_the_cloud_model_kept_before_it_failed_is_not_thrown_away(world, lane):  # noqa: F811
    """A first reply cut off by the output cap (its complete item is kept),
    then the retry fails: the local model follows and the cloud item stays."""
    _sub, run, scope = world
    cut_off = '{"items": [' + json.dumps(GOOD) + ', {"topic": "cut'

    class CutThenFail(Cloud):
        def reason(self, packet):
            self.packets.append(packet)
            if len(self.packets) > 1:
                raise API_ERROR
            return rp.Response(text=cut_off, provider=rp.CLAUDE, model_tag="fake", digest="d",
                               finish_reason="length", prompt_sha256=packet.sha256,
                               schema_errors=rp.schema_errors(cut_off, packet.json_schema), cost_usd=0.0)

    cloud = lane(CutThenFail())
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 2 and _asked_locally() == 1
    assert result["kept"] == 2 and result["local_instead"] == rp.CLOUD_CALL_FAILED
    assert sorted(r["contractor_section"] for r in _ai_rows(run)) == sorted([GOOD["field"], BLANK_FIELD])


def test_an_injected_provider_is_never_swapped(world, lane):  # noqa: F811
    """A caller that hands in its own provider gets that provider's result."""
    _sub, run, scope = world
    lane(Cloud())
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"], provider=Cloud(raises=API_ERROR))
    assert Local.made == [] and result["kept"] == 0 and result["local_instead"] is None


def test_the_review_job_gets_drafts_although_the_cloud_is_down(world, lane):  # noqa: F811
    _sub, run, scope = world
    lane(Cloud(raises=API_ERROR))
    review_jobs._ai_check(run, scope, ["API 610"])
    assert len(_ai_rows(run)) == 1 and "Written by ollama:fake." in _ai_rows(run)[0]["ai_rationale"]


# ------------------------------------------------------------ the CRS wording

def test_the_wording_goes_on_with_the_local_model_after_a_failed_cloud_call(world, lane):  # noqa: F811
    _sub, run, _scope = world
    cloud = lane(Cloud(raises=API_ERROR))
    Local.answer = json.dumps({"comment": GOOD_WORDING})
    second = dict(ROW, crs_row_key="k2")
    summary = crs_wording.word_run(run, [ROW, second])
    assert len(cloud.packets) == 1 and _asked_locally() == 2          # the failed row again, and the next
    assert Local.made[0].timeout == settings.crs_ai_wording_timeout_s
    assert (summary["tried"], summary["accepted"], summary["stopped"]) == (2, 2, None)
    assert summary["local_instead"] == rp.CLOUD_CALL_FAILED and summary["model"].startswith(rp.OLLAMA + ":")


def test_the_wording_stops_on_a_budget_cap_as_before(world, lane):  # noqa: F811
    _sub, run, _scope = world
    cloud = lane(Cloud(raises=claude_spend.BudgetExceeded("cap")))
    summary = crs_wording.word_run(run, [ROW])
    assert len(cloud.packets) == 1 and Local.made == []
    assert summary["local_instead"] is None and "BudgetExceeded" in summary["stopped"]


def test_when_the_local_model_is_down_too_the_templates_are_kept(world, lane, monkeypatch):  # noqa: F811
    _sub, run, _scope = world
    lane(Cloud(raises=API_ERROR))

    class Down(Local):
        def reason(self, packet):
            raise rp.ProviderRefused("ollama: connection refused")
    monkeypatch.setattr(rp, "OllamaProvider", Down)
    summary = crs_wording.word_run(run, [ROW])
    assert summary["accepted"] == 0 and "templates kept" in summary["stopped"]
    assert crs_wording.stored(run) == {}
