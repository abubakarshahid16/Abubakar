"""#819: with the owner's approval of standards text for the cloud model
(12 Oct 2026, under the approved-documents list), the two review steps whose
prompts carry a standard can run on Claude per task.

Before: the full AI engineering check (it lists the held standards and their
clauses) and the CRS wording followed the GLOBAL provider only, so under
REASONING_PROVIDER=per_task they could never use Claude - whatever was
approved.

Now, under `per_task` and with the step's own engine setting on claude:
  * the FULL check runs on Claude for a review whose documents - standards
    included - are ALL on the approved list; one unapproved standard keeps
    it local (and the datasheet-only opinion of #855 follows, as before);
  * the CRS wording runs on Claude under the same condition, with its own
    setting `CRS_AI_WORDING_ENGINE` (default local);
  * `ollama` as the provider refuses both, whatever the settings say.

The matcher needed no change: `MATCH_ENGINE=claude` already declares the
review's standards (#854). Every provider here is a fake that reserves on the
real ledger, so the approved-list check is the production one.
"""
from __future__ import annotations

import json

import pytest

from app import ai_engineering_check as aic
from app import claude_approved, crs_wording, review_jobs
from app import reasoning_provider as rp
from app.config import Settings, settings
from tests.test_501_datasheet_opinion import Lane, lane  # noqa: F401 - fixture
from tests.test_763_crs_ai_wording import GOOD as GOOD_WORDING
from tests.test_763_crs_ai_wording import ROW
from tests.test_838_local_when_not_approved import SHEET, STANDARD, Local, _approve
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import ASKS_A_BLANK, BLANK_FIELD, GOOD, _ai_rows, _blank_fields  # noqa: F401
from tests.test_review_ai_check import _resolver, world  # noqa: F401 - fixtures


@pytest.fixture
def local(monkeypatch):
    """The local engine replaced by a recorder (`Local`)."""
    monkeypatch.setattr(rp, "OllamaProvider", Local)
    _blank_fields(monkeypatch, {1: [BLANK_FIELD]})
    Local.made, Local.answer = [], json.dumps({"items": [ASKS_A_BLANK]})


def _asked_locally() -> int:
    return sum(len(p.packets) for p in Local.made)


def _asked_cloud() -> int:
    return sum(len(p.packets) for p in Lane.made)


# ------------------------------------------------------------- the question

def test_the_wording_engine_ships_local():
    assert Settings.model_fields["crs_ai_wording_engine"].default == "ollama"


def test_the_cloud_provider_for_a_task_needs_its_setting_the_lane_and_every_document_approved(world, lane):  # noqa: F811
    sub, _run, _scope = world
    _approve(SHEET)
    with claude_approved.carrying([sub]):
        assert isinstance(rp.claude_for_task("claude"), Lane)                # declared and approved
        assert rp.claude_for_task("ollama") is None                          # the step's own setting
        assert rp.claude_for_task(None) is None
    with claude_approved.carrying([sub, "doc_std"]):
        assert rp.claude_for_task("claude") is None                          # one document is not approved
    assert rp.claude_for_task("claude") is None                              # nothing declared: fail closed
    _approve(SHEET, STANDARD)
    with claude_approved.carrying([sub, "doc_std"]):
        assert isinstance(rp.claude_for_task("claude"), Lane)
        assert rp.claude_for_task("claude", "labelling").model == settings.claude_labelling_model


@pytest.mark.parametrize("provider", ["ollama", "", "off"])
def test_the_master_switch_refuses_whatever_is_approved(world, lane, monkeypatch, provider):  # noqa: F811
    sub, _run, _scope = world
    _approve(SHEET, STANDARD)
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    with claude_approved.carrying([sub, "doc_std"]):
        assert rp.claude_for_task("claude") is None


# ------------------------------------------------- the AI engineering check

def test_the_full_check_runs_on_claude_when_the_standard_is_approved_too(world, lane, local):  # noqa: F811
    sub, run, scope = world
    _approve(SHEET, STANDARD)
    review_jobs._ai_check(run, scope, ["API 610"])
    assert _asked_cloud() == 1 and _asked_locally() == 0
    asked = next(p for p in Lane.made if p.packets)
    assert asked.declared == [frozenset({sub, "doc_std"})]                   # the review's documents, all of them
    held = aic._held_standards(run)
    assert held and all(name in asked.packets[0].prompt for name in held)    # the FULL packet: the clause list
    assert not asked.packets[0].prompt_version.endswith("+datasheet-only")
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["model"] == "claude:fake" and status["local_instead"] is None and status["local_pages"] is None
    assert "claude_datasheet" not in status                                   # no second, narrower opinion
    assert "Written by claude:fake." in _ai_rows(run)[0]["ai_rationale"]


def test_one_unapproved_standard_keeps_the_check_local_and_the_opinion_follows(world, lane, local):  # noqa: F811
    sub, run, scope = world
    _approve(SHEET)                                                           # the standard is not on the list
    review_jobs._ai_check(run, scope, ["API 610"])
    assert _asked_locally() == 1 and _asked_cloud() == 1
    opinion = next(p for p in Lane.made if p.packets)
    assert opinion.declared == [frozenset({sub})]                             # the datasheet-only opinion (#855)
    assert opinion.packets[0].prompt_version.endswith("+datasheet-only")
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["model"].startswith(rp.OLLAMA + ":") and status["claude_datasheet"]["ran"] is True


def test_with_its_engine_local_the_check_never_asks_claude(world, lane, local, monkeypatch):  # noqa: F811
    _sub, run, scope = world
    _approve(SHEET, STANDARD)
    monkeypatch.setattr(settings, "review_ai_check_engine", "ollama")
    review_jobs._ai_check(run, scope, ["API 610"])
    assert _asked_cloud() == 0 and _asked_locally() == 1


# ------------------------------------------------------------ the CRS wording

def _wording(monkeypatch, engine="claude"):
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)
    monkeypatch.setattr(settings, "crs_ai_wording_engine", engine)
    Lane.answer = Local.answer = json.dumps({"comment": GOOD_WORDING})


def test_the_wording_runs_on_claude_when_every_document_is_approved(world, lane, local, monkeypatch):  # noqa: F811
    sub, run, _scope = world
    _approve(SHEET, STANDARD)
    _wording(monkeypatch)
    summary = crs_wording.word_run(run, [ROW])
    assert _asked_cloud() == 1 and _asked_locally() == 0
    asked = next(p for p in Lane.made if p.packets)
    assert asked.declared == [frozenset({sub, "doc_std"})] and asked.model == settings.claude_labelling_model
    assert summary["accepted"] == 1 and summary["model"] == "claude:fake" and summary["local_instead"] is None


def test_the_wording_stays_local_when_a_standard_is_not_approved(world, lane, local, monkeypatch):  # noqa: F811
    _sub, run, _scope = world
    _approve(SHEET)
    _wording(monkeypatch)
    summary = crs_wording.word_run(run, [ROW])
    assert _asked_cloud() == 0 and _asked_locally() == 1
    assert summary["accepted"] == 1 and summary["model"].startswith(rp.OLLAMA + ":")


def test_the_wording_stays_local_by_default_and_under_the_master_switch(world, lane, local, monkeypatch):  # noqa: F811
    _sub, run, _scope = world
    _approve(SHEET, STANDARD)
    _wording(monkeypatch, engine="ollama")
    crs_wording.word_run(run, [ROW])
    assert _asked_cloud() == 0 and _asked_locally() == 1
    _wording(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    crs_wording.word_run(run, [ROW])
    assert _asked_cloud() == 0 and _asked_locally() == 2
