"""#838: a review step whose documents are NOT APPROVED for the cloud model
runs on the local model, and says so.

F9 on the live app (11 Oct): with the Claude lane on and only the datasheets
on the approved list, the AI engineering check, the AI wording and the
re-check were refused - correctly, and visibly - because their prompts also
carry standards. So the AI check was effectively off. Planner decision: for
THAT refusal only, the step runs on the local model (nothing leaves the
machine) and the run names why. A budget refusal, an undeclared prompt and an
unknown document stay refusals: shown, never replaced.

Every model here is a fake. The cloud fake fails the test if it is asked at
all on the local path, and so do the cloud transport and the spend ledger's
reservation - nothing of the cloud lane is touched.
Synthetic sheet only (tests/test_b3_page_ledger.py).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ai_engineering_check as aic
from app import claude_api, claude_approved, claude_spend, crs_wording
from app import reader_transport
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_763_crs_ai_wording import GOOD as GOOD_WORDING
from tests.test_763_crs_ai_wording import ROW
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import GOOD, _ai_rows, _resolver, world  # noqa: F401 - fixtures

SHEET, STANDARD = "sha-doc_sheet", "sha-std"      # the hashes test_b3_page_ledger gives its documents


def _approve(*hashes):
    claude_approved.list_path().write_text(json.dumps({"documents": [
        {"sha256": sha, "status": "approved", "label": "invented"} for sha in hashes]}), encoding="utf-8")


class Cloud(rp.ClaudeProvider):
    """Stands where the Claude provider stands. Records what it was asked."""

    def __init__(self, answer=None, raises=None):
        self.answer, self.raises, self.packets = answer, raises, []

    def reason(self, packet):
        self.packets.append(packet)
        if self.raises:
            raise self.raises
        return _response(self.answer, packet, rp.CLAUDE)


class Local:
    """Stands where `OllamaProvider` stands; every instance is remembered."""

    made: list = []
    answer = None

    def __init__(self, model=None, *, timeout=900.0):
        self.timeout, self.packets = timeout, []
        Local.made.append(self)

    def reason(self, packet):
        self.packets.append(packet)
        return _response(Local.answer, packet, rp.OLLAMA)


def _response(text, packet, provider):
    return rp.Response(text=text, provider=provider, model_tag="fake", digest="d",
                       finish_reason="stop", prompt_sha256=packet.sha256,
                       schema_errors=rp.schema_errors(text, packet.json_schema), cost_usd=0.0)


def _asked_locally() -> int:
    return sum(len(p.packets) for p in Local.made)


@pytest.fixture
def lane(monkeypatch):
    """The Claude lane 'on' with the approved list enforced, and the local
    engine replaced by `Local`. Returns a function that installs the cloud
    fake the steps will be handed."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)
    monkeypatch.setattr(rp, "OllamaProvider", Local)
    Local.made, Local.answer = [], json.dumps({"items": [GOOD]})

    def install(cloud):
        monkeypatch.setattr(rp, "get_provider", lambda *a, **k: cloud)
        return cloud
    return install


@pytest.fixture
def no_cloud(monkeypatch):
    """Anything of the cloud lane being touched fails the test: the
    transport, and the reservation every Claude call makes before it leaves."""
    def touched(*a, **k):
        raise AssertionError("the cloud lane was reached on the local path")
    monkeypatch.setattr(reader_transport, "transport", touched)
    monkeypatch.setattr(claude_spend, "reserve_all", touched)
    monkeypatch.setattr(claude_spend, "reserve", touched)


# ------------------------------------------------------------- the question

def test_only_a_not_approved_refusal_is_answered_with_the_local_model(world, lane):
    sub, _run, _scope = world
    _approve(SHEET)
    with claude_approved.carrying([sub, "doc_std"]):
        assert claude_approved.local_instead() == (
            "ran on the local model: 1 of 2 document(s) in its prompt are not approved for the cloud model")
    with claude_approved.carrying([sub]):
        assert claude_approved.local_instead() is None             # all approved: the cloud model
    assert claude_approved.local_instead() is None                 # undeclared: a refusal, not a fallback
    with claude_approved.carrying([sub, "doc_not_in_library"]):
        assert claude_approved.local_instead() is None             # unknown document: a refusal too
    with claude_approved.carrying(()):
        assert claude_approved.local_instead() is None


def test_the_sentence_names_counts_and_never_a_document(world, lane):
    sub, _run, _scope = world
    with claude_approved.carrying([sub, "doc_std"]):
        said = claude_approved.local_instead()
    assert said.startswith("ran on the local model: 2 of 2 ")
    assert "doc_" not in said and ".pdf" not in said


# ------------------------------------------------- the AI engineering check

def test_the_ai_check_runs_locally_and_says_so_when_a_standard_is_not_approved(world, lane, no_cloud):
    _sub, run, scope = world
    _approve(SHEET)                                                 # the standard is not on the list
    cloud = lane(Cloud())
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert cloud.packets == [] and _asked_locally() == 1
    assert result["ran"] and result["kept"] == 1 and len(_ai_rows(run)) == 1
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["local_instead"] == result["local_instead"] == (
        "ran on the local model: 1 of 2 document(s) in its prompt are not approved for the cloud model")
    assert status["model"].startswith(rp.OLLAMA + ":")
    assert status["plain"].endswith("The check " + status["local_instead"] + ".")


def test_the_ai_check_uses_the_cloud_model_when_every_document_is_approved(world, lane):
    _sub, run, scope = world
    _approve(SHEET, STANDARD)
    cloud = lane(Cloud(answer=json.dumps({"items": [GOOD]})))
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 1 and Local.made == []
    assert result["local_instead"] is None
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["local_instead"] is None and "local model" not in status["plain"]


def test_a_budget_refusal_is_shown_and_never_replaced_by_the_local_model(world, lane):
    _sub, run, scope = world
    _approve(SHEET, STANDARD)
    cloud = lane(Cloud(raises=claude_spend.BudgetExceeded("the step cap of USD 5.00 would be crossed")))
    result = aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 1 and Local.made == []            # no local substitute
    assert result["complete"] is False and result["kept"] == 0 and result["local_instead"] is None
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert "a budget cap stopped the call" in status["plain"] and "local model" not in status["plain"]


def test_with_the_list_not_enforced_nothing_changes(world, lane, monkeypatch):
    _sub, run, scope = world
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    cloud = lane(Cloud(answer=json.dumps({"items": [GOOD]})))
    aic.run_check(run, allowed_document_ids=scope, cited=["API 610"])
    assert len(cloud.packets) == 1 and Local.made == []


# ------------------------------------------------------------ the AI wording

def test_the_wording_runs_locally_and_says_so(world, lane, no_cloud, monkeypatch):
    _sub, run, _scope = world
    _approve(SHEET)
    cloud = Cloud()
    monkeypatch.setattr(crs_wording, "_provider", lambda: cloud)
    Local.answer = json.dumps({"comment": GOOD_WORDING})
    summary = crs_wording.word_run(run, [ROW])
    assert cloud.packets == [] and _asked_locally() == 1
    assert Local.made[0].timeout == settings.crs_ai_wording_timeout_s
    assert summary["accepted"] == 1 and summary["model"].startswith(rp.OLLAMA + ":")
    assert summary["local_instead"].startswith("ran on the local model: 1 of 2 ")
    assert crs_wording.summary_of(run)["local_instead"] == summary["local_instead"]


def test_the_wording_keeps_the_cloud_model_for_approved_documents_and_stops_on_a_budget_cap(
        world, lane, monkeypatch):
    _sub, run, _scope = world
    _approve(SHEET, STANDARD)
    cloud = Cloud(raises=claude_spend.BudgetExceeded("cap"))
    monkeypatch.setattr(crs_wording, "_provider", lambda: cloud)
    summary = crs_wording.word_run(run, [ROW])
    assert len(cloud.packets) == 1 and Local.made == []
    assert summary["local_instead"] is None and "BudgetExceeded" in summary["stopped"]


# --------------------------------------------------------------- the re-check

def _cloud_route(monkeypatch):
    """The route's cloud `model_call`, as `_model_call_or_409` hands it over
    when the lane is on - here a recorder."""
    asked: list[str] = []

    def call(prompt):
        asked.append(prompt)
        return "{}"
    budget = claude_api.claude_budget.Budget(call)
    budget.step = claude_api.STEP_RECHECK
    monkeypatch.setattr(claude_api, "_model_call_or_409", lambda step: (budget, None))
    return asked


def test_the_recheck_route_asks_the_local_model_and_says_so(world, lane, no_cloud, monkeypatch):
    _sub, run, _scope = world
    _approve(SHEET)
    asked_cloud = _cloud_route(monkeypatch)
    Local.answer = "{}"
    body = TestClient(app).post(f"/api/reviews/runs/{run}/claude/recheck").json()
    assert asked_cloud == [] and _asked_locally() >= 1
    assert body["local_instead"].startswith("ran on the local model: 1 of 2 ")
    assert Local.made[0].timeout == settings.claude_recheck_local_timeout_s


def test_the_recheck_route_keeps_the_cloud_model_for_approved_documents(world, lane, monkeypatch):
    _sub, run, _scope = world
    _approve(SHEET, STANDARD)
    asked_cloud = _cloud_route(monkeypatch)
    body = TestClient(app).post(f"/api/reviews/runs/{run}/claude/recheck").json()
    assert len(asked_cloud) >= 1 and Local.made == []
    assert body["local_instead"] is None


def test_the_local_recheck_stops_when_its_time_is_spent_and_counts_what_is_left(
        world, lane, no_cloud, monkeypatch):
    _sub, run, _scope = world
    _approve(SHEET)
    _cloud_route(monkeypatch)
    monkeypatch.setattr(settings, "claude_recheck_local_max_seconds", 0.0)
    body = TestClient(app).post(f"/api/reviews/runs/{run}/claude/recheck").json()
    assert _asked_locally() == 0
    assert body["complete"] is False and body["counts"].get("local_time_budget") == 1
    assert body["left_unchecked"] == body["total"] >= 1


def test_the_time_limit_is_a_stop_the_loop_understands():
    assert issubclass(claude_api.LocalTimeUp, claude_spend.StopRun)
    assert not issubclass(claude_api.LocalTimeUp, claude_spend.BudgetExceeded)
    assert SimpleNamespace(key=claude_api.LocalTimeUp.count_key).key == "local_time_budget"
