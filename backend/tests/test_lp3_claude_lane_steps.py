"""LP3 (order 14 live proof, 17 Nov 2026): in a Claude-lane review run every rule-check AI step runs on the engine its own
setting names, or the run and the sheet say plainly why it did not run. Never a silent skip, never the local engine.

The live pump and HAZOP runs skipped `clause_check_proposal` (20 calls) and the field naming with "local engine not loaded",
although the owner had switched the rule check's steps to Claude. Invented sentences and labels; a fake Claude transport;
no socket, no paid call.
"""

# ruff: noqa: F811 - pytest fixtures imported, then taken as parameters
from __future__ import annotations

import pytest

from app import (
    absence,
    ai_requirements,
    ai_task_runner,
    claude_approved,
    field_naming,
    local_engine_bar,
    reader_transport,
)
from app import reasoning_provider as rp
from app.config import settings
from tests.test_claude_lane_no_local_engine import (  # noqa: F401 - fixtures
    engine_calls,
    lane,
)
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    temp_storage,
    world,
)

SENTENCE = "The design pressure shall not exceed 10 bar."
CLAUSE_STEP = f"ai_task:{ai_requirements.CLAUSE_TASK.name}"


def _claude(text: str):
    def send(url, *, headers, body, timeout):
        send.models.append(body["model"])
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    send.models = []
    return send


PROPOSAL = (
    '{"has_limit": true, "field": "design pressure", "operator": "<=", "value": "10", "unit": "bar",'
    ' "condition": null, "quote": "The design pressure shall not exceed 10 bar."}'
)


@pytest.fixture
def declared(lane):
    """The review's documents declared (none here) and the owner's list not in the way: the gates under test are the step's."""
    lane.setattr(settings, "claude_approved_list_enforced", False)
    with claude_approved.carrying([]):
        yield lane


def _lines(outcome: dict) -> list[str]:
    parts = absence.unchecked_parts(run_status="completed", outcome=outcome)
    return [p["line"] for p in parts if p["part"].startswith("skipped:")]


# ------------------------------------------------------------- the clause-check proposal


def test_the_clause_check_runs_on_claude_when_its_own_setting_says_claude(
    declared, engine_calls
):
    declared.setattr(settings, "ai_clause_review_engine", "claude")
    fake = _claude(PROPOSAL)
    declared.setattr(reader_transport, "transport", lambda: fake)
    with local_engine_bar.bar():
        result = ai_task_runner.run_task(ai_requirements.CLAUSE_TASK, SENTENCE)
        stated = local_engine_bar.stated()
    assert result.state == ai_task_runner.STATE_OK and result.data["value"] == "10"
    assert fake.models == [settings.claude_reasoning_model]
    assert stated == [] and engine_calls == []
    check, why = ai_requirements.verify_proposal(result.data, SENTENCE)
    assert why is None and check["value"] == "10"  # code still verifies every part


def test_the_review_step_proposes_its_checks_on_claude(declared, engine_calls, world):
    declared.setattr(settings, "ai_clause_review_engine", "claude")
    declared.setattr(reader_transport, "transport", lambda: _claude(PROPOSAL))
    with local_engine_bar.bar():
        report = ai_requirements.propose_checks(
            [
                {
                    "id": "lp3-r1",
                    "requirement_type": "statement",
                    "source_text": SENTENCE,
                }
            ],
            limit=5,
        )
        stated = local_engine_bar.stated()
    assert (
        report["asked"] == 1
        and report["could_not_read"] == 0
        and report["proposed"] == 1
    )
    assert stated == [] and engine_calls == []


def test_with_its_setting_local_it_does_not_run_and_says_which_setting(
    declared, engine_calls
):
    declared.setattr(settings, "ai_clause_review_engine", "ollama")
    with local_engine_bar.bar():
        result = ai_task_runner.run_task(ai_requirements.CLAUSE_TASK, SENTENCE)
        stated = local_engine_bar.stated()
    assert result.state == ai_task_runner.STATE_COULD_NOT_READ
    assert result.reason.startswith(
        "not run: its own engine setting AI_CLAUSE_REVIEW_ENGINE is not claude"
    )
    assert stated == [{"step": CLAUSE_STEP, "calls_not_made": 1, "note": result.reason}]
    lines = _lines({local_engine_bar.OUTCOME_KEY: stated})
    assert lines == [
        "AI clause check proposal: not checked: its own engine setting AI_CLAUSE_REVIEW_ENGINE is not claude, "
        "and a Claude-lane run does not load the local engine."
    ]
    assert engine_calls == []


def test_a_document_claude_may_not_take_is_named_as_the_reason(declared, engine_calls):
    declared.setattr(settings, "ai_clause_review_engine", "claude")
    declared.setattr(claude_approved, "refusal", lambda: ("NOT_APPROVED", "invented"))
    with local_engine_bar.bar():
        result = ai_task_runner.run_task(ai_requirements.CLAUSE_TASK, SENTENCE)
    assert result.reason == (
        "not run: its own engine setting AI_CLAUSE_REVIEW_ENGINE is claude, but a document in its prompt may not be sent "
        "to Claude (NOT_APPROVED)"
    )
    assert engine_calls == []


def test_a_task_with_no_engine_setting_says_so(declared, engine_calls):
    spec = ai_task_runner.TaskSpec(
        name="lp3_invented", version="v1", instruction="i", schema={"type": "object"}
    )
    with local_engine_bar.bar():
        result = ai_task_runner.run_task(spec, "some text")
        stated = local_engine_bar.stated()
    assert result.reason == "not run: this step has no Claude setting"
    assert stated[0]["note"] == "not run: this step has no Claude setting"
    assert _lines({local_engine_bar.OUTCOME_KEY: stated}) == [
        "AI lp3 invented: not checked: this step has no Claude setting."
    ]
    assert engine_calls == []


def test_a_local_lane_run_is_unchanged(lane, monkeypatch):
    """Outside a Claude-lane run a task asked with no provider stays on the local model, whatever its setting says."""
    lane.setattr(settings, "ai_clause_review_engine", "claude")
    asked = []

    class Local:
        name = "ollama"
        requested_model = "local-invented"

        def reason(self, packet):
            asked.append(packet.step)
            raise rp.ProviderRefused("invented: stopped engine")

    monkeypatch.setattr(ai_task_runner, "make_provider", lambda model=None: Local())
    result = ai_task_runner.run_task(ai_requirements.CLAUSE_TASK, SENTENCE)
    assert asked == [CLAUSE_STEP] and result.model == "local-invented"


# ------------------------------------------------------------------- the field naming


def _naming(lane):
    lane.setattr(field_naming, "build_dictionary", lambda *a: ["noise level"])
    lane.setattr(field_naming, "stored_names", lambda *a, **k: {})
    requirement = {
        "id": "lp3-r1",
        "requirement_type": "numeric_limit",
        "requirement_text": "Noise level shall not exceed 90 dB(A)",
    }
    fact = {"id": "lp3-f1", "field_label": "Noise level", "raw_value": "95"}
    return [requirement], [fact]


def test_field_naming_runs_on_claude_under_the_matchers_setting(declared, engine_calls):
    declared.setattr(settings, "match_engine", "claude")
    fake = _claude('{"names": []}')
    declared.setattr(reader_transport, "transport", lambda: fake)
    requirements, facts = _naming(declared)
    with local_engine_bar.bar():
        provider = field_naming.naming_provider()
        assert provider.name == rp.CLAUDE
        field_naming.ensure_names(requirements, facts)
        stated = local_engine_bar.stated()
    assert fake.models and set(fake.models) == {settings.claude_labelling_model}
    assert field_naming.NAMING_STEP not in {r["step"] for r in stated}
    assert engine_calls == []


def test_field_naming_with_the_matcher_local_says_which_setting(declared, engine_calls):
    declared.setattr(settings, "match_engine", "ollama")
    requirements, facts = _naming(declared)
    with local_engine_bar.bar():
        field_naming.ensure_names(requirements, facts)
        stated = {r["step"]: r["note"] for r in local_engine_bar.stated()}
    assert stated[field_naming.NAMING_STEP].startswith(
        "not run: its own engine setting MATCH_ENGINE is not claude"
    )
    assert engine_calls == []


def test_field_naming_outside_a_claude_lane_run_is_unchanged(lane):
    lane.setattr(settings, "match_engine", "claude")
    assert (
        field_naming.naming_provider().name == rp.OLLAMA
    )  # per_task: no setting of its own, as before


def test_the_sheet_names_a_task_step_in_plain_words():
    assert local_engine_bar.step_words(CLAUSE_STEP) == "AI clause check proposal"
    assert local_engine_bar.step_words(field_naming.NAMING_STEP) == "AI field naming"


# ------------------------------------------------------------- the whole review, end to end


def test_a_claude_lane_review_runs_both_steps_on_claude_and_skips_neither(
    declared, engine_calls, world
):
    """The live case: every rule-check engine on claude. The run asks Claude for the clause-check proposal and for the field
    names, the local engine is never reached, and neither step is listed as skipped."""
    from tests.test_claude_lane_no_local_engine import _outcome, _review

    for name in local_engine_bar.REVIEW_ENGINE_SETTINGS:
        declared.setattr(settings, name, "claude")
    declared.setattr(settings, "field_naming_enabled", True)
    declared.setattr(settings, "geometry_reader_enabled", True)
    declared.setattr(settings, "ai_clause_checks_enabled", True)
    declared.setattr(
        ai_requirements,
        "undecided_statements",
        lambda requirements, status_of: [
            {"id": "lp3-r1", "requirement_type": "statement", "source_text": SENTENCE}
        ],
    )
    asked = []

    def send(url, *, headers, body, timeout):
        prompt = str(body.get("messages")) + str(body.get("system"))
        if "ONE sentence of an engineering standard" in prompt:
            asked.append("clause_check_proposal")
            text = PROPOSAL
        elif "You name engineering fields" in prompt:
            asked.append("naming")
            text = '{"names": []}'
        else:
            text = '{"comment": "Noise level exceeds the limit."}'
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    declared.setattr(reader_transport, "transport", lambda: send)
    run_id, state = _review(world)
    assert state == "done" and engine_calls == []
    assert {"clause_check_proposal", "naming"} <= set(asked)
    skipped = {
        r["step"] for r in _outcome(run_id).get(local_engine_bar.OUTCOME_KEY) or []
    }
    assert CLAUSE_STEP not in skipped and field_naming.NAMING_STEP not in skipped
