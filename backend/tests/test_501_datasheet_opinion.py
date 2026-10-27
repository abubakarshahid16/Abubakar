"""#501: the AI engineering check's datasheet-only opinion on the Claude lane.

Owner decision, 12 Oct 2026: Claude may be used for the AI engineering check
on the approved test datasheets, and no standard's text may go. The check
itself lists the held standards and their clauses, so the approved-document
lock refuses it on the cloud lane and it runs locally (#838, #844). This is
a SECOND opinion beside it: the same instructions and the same gate, a packet
that carries the datasheet alone, declared as carrying only the submittal.

What holds:
  * off by default (`REVIEW_AI_CHECK_ENGINE=ollama`): nothing is asked;
  * asked only under REASONING_PROVIDER=per_task (or claude) with the lane
    open - `ollama` refuses it whatever the setting says;
  * the packet names no held standard and no clause, and the call is
    declared as carrying the submittal ONLY - so a sheet on the approved list
    goes although the review's standards are not on it, and a sheet that is
    not on the list is refused;
  * a draft that cites a clause is refused; a kept one is a pending draft
    that says which engine wrote it and from what;
  * the local check still runs, and its drafts say which engine wrote them.

Every provider here is a fake. Synthetic sheet only.
"""
from __future__ import annotations

import json

import pytest

from app import ai_engineering_check as aic
from app import fallback_note
from app import claude_approved, claude_spend, review_jobs
from app import reasoning_provider as rp
from app.config import Settings, settings
from tests.test_838_local_when_not_approved import SHEET, STANDARD, _approve
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import GOOD, _ai_rows, _blank_fields, _resolver, world  # noqa: F401


class Lane:
    """Stands where `ClaudeProvider` stands. Before answering it reserves on
    the real ledger - the one place every Claude call is checked against the
    approved-document list - and records what was declared and sent."""

    made: list = []
    answer = None

    def __init__(self, model=None, *, step=None):
        self.model, self.step, self.packets, self.declared = model, step, [], []
        Lane.made.append(self)

    def reason(self, packet):
        self.declared.append(claude_approved.carried())
        held = claude_spend.reserve(self.step or aic.STEP, 0.01, model="claude-test")
        claude_spend.release(held, "test double: nothing was sent")
        self.packets.append(packet)
        text = Lane.answer
        return rp.Response(text=text, provider=rp.CLAUDE, model_tag="fake", digest="d",
                           finish_reason="stop", prompt_sha256=packet.sha256,
                           schema_errors=rp.schema_errors(text, packet.json_schema), cost_usd=0.02)


@pytest.fixture
def lane(monkeypatch, tmp_path):
    """per_task, the lane open, the opinion asked for, the approved list
    enforced, and `ClaudeProvider` replaced by `Lane`."""
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "review_ai_check_engine", "claude")
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-invented-key")
    monkeypatch.setattr(rp, "ClaudeProvider", Lane)
    Lane.made, Lane.answer = [], json.dumps({"items": [GOOD]})


def _opinion(world):  # noqa: F811
    _sub, run, scope = world
    return aic.run_datasheet_opinion(run, allowed_document_ids=scope, cited=["API 610"])


def test_the_opinion_is_off_by_default():
    assert Settings.model_fields["review_ai_check_engine"].default == "ollama"


def test_with_its_engine_local_nothing_is_asked_and_nothing_is_recorded(world, lane, monkeypatch):  # noqa: F811
    _sub, run, scope = world
    monkeypatch.setattr(settings, "review_ai_check_engine", "ollama")
    out = _opinion(world)
    assert out["ran"] is False and Lane.made == []
    assert "claude_datasheet" not in (aic.ai_check_status(run, allowed_document_ids=scope) or {})


def test_an_approved_sheet_gets_the_opinion_though_the_standards_are_not_approved(world, lane):  # noqa: F811
    sub, run, scope = world
    _approve(SHEET)                                     # the review's standard is NOT on the list
    out = _opinion(world)
    asked = Lane.made[0]
    assert out["ran"] and (out["proposed"], out["kept"], out["stored"]) == (1, 1, 1)
    assert asked.declared == [frozenset({sub})]         # the submittal ONLY: no standard declared
    assert out["engine"] == "claude:fake" and asked.step == aic.STEP
    row = _ai_rows(run)[0]
    assert row["approval_status"] == "pending" and row["compliance_status"] is None
    assert "Written by claude:fake" in row["ai_rationale"] and aic.DATASHEET_ONLY in row["ai_rationale"]
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["claude_datasheet"]["kept"] == 1
    assert status["plain"].endswith("Datasheet-only opinion by claude:fake: 1 of 1 proposed item(s) kept.")


def test_the_packet_carries_the_datasheet_and_no_standard(world, lane):  # noqa: F811
    _sub, run, _scope = world
    _approve(SHEET)
    assert aic._held_standards(run)                     # the review DOES hold a standard with a clause
    _opinion(world)
    packet = Lane.made[0].packets[0]
    assert "Design pressure" in packet.prompt and "--- page 1 ---" in packet.prompt
    assert "- API 610" in packet.prompt                 # a name the datasheet itself cites
    assert "(none: cite no clause)" in packet.prompt
    for name, clauses in aic._held_standards(run).items():
        assert name not in packet.prompt
        assert not any(clause in packet.prompt.split("FIELDS READ FROM")[0] for clause in clauses)
    assert packet.prompt_version.endswith("+datasheet-only")


def test_a_sheet_that_is_not_approved_is_refused_and_the_run_says_so(world, lane):  # noqa: F811
    _sub, run, scope = world
    _approve(STANDARD)                                  # the sheet itself is not on the list
    out = _opinion(world)
    assert out["ran"] is False and "not approved for the cloud model" in out["reason"]
    assert Lane.made[0].packets == [] and _ai_rows(run) == []
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert "Datasheet-only opinion by the cloud model did not run" in status["plain"]


@pytest.mark.parametrize("provider, code", [("ollama", rp.UNAVAILABLE_PROVIDER_OFF), ("", rp.UNAVAILABLE_PROVIDER_OFF)])
def test_the_master_switch_refuses_the_opinion(world, lane, monkeypatch, provider, code):  # noqa: F811
    _approve(SHEET)
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    out = _opinion(world)
    assert out["ran"] is False and code in out["reason"] and Lane.made == []


def test_a_draft_that_cites_a_clause_is_refused(world, lane):  # noqa: F811
    _sub, run, _scope = world
    _approve(SHEET)
    held = aic._held_standards(run)
    clause = next(iter(held.values()))[0]
    Lane.answer = json.dumps({"items": [GOOD, dict(GOOD, topic="Noise", clause=clause)]})
    out = _opinion(world)
    assert out["kept"] == 1 and out["rejected"] == {"clause_not_verified": 1}


def test_a_draft_already_raised_is_not_stored_twice(world, lane):  # noqa: F811
    _sub, run, _scope = world
    _approve(SHEET)
    first = _opinion(world)
    again = _opinion(world)
    assert (first["stored"], again["kept"], again["stored"]) == (1, 1, 0)
    assert len(_ai_rows(run)) == 1


def test_the_review_job_runs_the_local_check_and_then_the_opinion(world, lane, monkeypatch):  # noqa: F811
    """The check is not replaced: it runs on the local model as before (the
    standards are not approved), and its drafts say which engine wrote them."""
    from tests.test_review_ai_check import ASKS_A_BLANK, BLANK_FIELD
    from tests.test_838_local_when_not_approved import Local
    _sub, run, scope = world
    _approve(SHEET)
    _blank_fields(monkeypatch, {1: [BLANK_FIELD]})
    monkeypatch.setattr(rp, "OllamaProvider", Local)
    Local.made, Local.answer = [], json.dumps({"items": [ASKS_A_BLANK]})
    review_jobs._ai_check(run, scope, ["API 610"])
    written = sorted(r["ai_rationale"].split("Written by ")[1].split(",")[0].rstrip(".") for r in _ai_rows(run))
    # the local draft names why it is local (#555: Claude was asked for, a document is not approved)
    assert written == ["claude:fake", f"ollama:fake (Claude not used: {fallback_note.NOT_APPROVED})"]
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["local_scope"] and status["claude_datasheet"]["stored"] == 1
    assert "Scope on this run - local model" in status["plain"]
    assert "Datasheet-only opinion by claude:fake" in status["plain"]
    assert [d for d in Lane.made[0].declared] == [frozenset({_sub})]
