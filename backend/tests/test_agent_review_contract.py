"""The AI reviewer contract (#1690, PR-b0): closed words, the Pass/Fail rule,
null stays null, and the generated TypeScript is in step with the models."""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api import agent_review_schemas as ar

REPO = Path(__file__).resolve().parents[2]

CLASSES = list(ar.VerdictClass.__args__)
WORDS = list(ar.VerdictWord.__args__)
TIERS = list(ar.RuleTier.__args__)
REASONS = list(ar.LeftOutReason.__args__)


def _line(**over):
    base = {
        "item_id": "i1",
        "verdict_class": "Proven by code",
        "word": "Pass",
        "page": 3,
        "clause": "1.2",
        "rule_book": "Book A",
        "reason": "r",
        "rule_tier": "Owner",
    }
    base.update(over)
    return ar.AgentLine(**base)


def test_vocabularies_are_exactly_the_owner_words():
    assert CLASSES == [
        "Proven by code",
        "AI opinion, engineer to confirm",
        "AI opinion, rule not yet approved",
        "Query for the engineer",
        "Not applicable",
    ]
    assert WORDS == [
        "Pass",
        "Fail",
        "AI thinks: met",
        "AI thinks: not met",
        "Query",
        "Not applicable",
    ]
    assert TIERS == ["Owner", "Engineer", "AI approved", "Not AI approved"]
    assert REASONS == [
        "needs another paper",
        "needs a human",
        "quote not found",
        "not labelled yet",
        "another equipment type",
        "rule book not held",
    ]


TIERS_OR_NONE = [*TIERS, None]
OK_TIERS = ("Owner", "Engineer", "AI approved")
ALLOWED = {
    "Proven by code": ({"Pass", "Fail"}, {*OK_TIERS, None}),
    "AI opinion, engineer to confirm": (
        {"AI thinks: met", "AI thinks: not met"},
        {*OK_TIERS, None},
    ),
    "AI opinion, rule not yet approved": (
        {"AI thinks: met", "AI thinks: not met"},
        {"Not AI approved"},
    ),
    "Query for the engineer": ({"Query"}, {*TIERS, None}),
    "Not applicable": ({"Not applicable"}, {*TIERS, None}),
}


@pytest.mark.parametrize(
    "klass,word,tier", list(itertools.product(CLASSES, WORDS, TIERS_OR_NONE))
)
def test_only_the_closed_table_of_class_word_tier_can_be_built(klass, word, tier):
    words, tiers = ALLOWED[klass]
    if word in words and tier in tiers:
        assert _line(verdict_class=klass, word=word, rule_tier=tier).word == word
    else:
        with pytest.raises(ValidationError):
            _line(verdict_class=klass, word=word, rule_tier=tier)


def test_pass_fail_and_proven_class_go_together_both_ways():
    for word in ("Pass", "Fail"):
        for klass in CLASSES[1:]:
            with pytest.raises(ValidationError):
                _line(verdict_class=klass, word=word)
    with pytest.raises(ValidationError):
        _line(verdict_class="Proven by code", word="Query")
    with pytest.raises(ValidationError):
        _line(verdict_class="Proven by code", rule_tier="Not AI approved")


def test_a_checklist_line_has_a_null_tier_but_an_unapproved_rule_does_not():
    assert _line(rule_tier=None).rule_tier is None
    assert json.loads(_line(rule_tier=None).model_dump_json())["rule_tier"] is None
    with pytest.raises(ValidationError):
        _line(
            verdict_class="AI opinion, rule not yet approved",
            word="AI thinks: met",
            rule_tier=None,
        )
    with pytest.raises(ValidationError):
        ar.AgentLine.model_validate(
            {
                "item_id": "i",
                "verdict_class": "Not applicable",
                "word": "Not applicable",
                "clause": "c",
                "rule_book": "b",
                "reason": "r",
            }
        )


def test_pass_cannot_be_built_from_an_ai_opinion_even_via_validate():
    with pytest.raises(ValidationError):
        ar.AgentLine.model_validate(
            {
                "item_id": "i",
                "verdict_class": "AI opinion, engineer to confirm",
                "word": "Fail",
                "clause": "c",
                "rule_book": "b",
                "reason": "r",
                "rule_tier": "AI approved",
            }
        )


def test_every_literal_rejects_an_unknown_word():
    with pytest.raises(ValidationError):
        _line(verdict_class="High confidence")
    with pytest.raises(ValidationError):
        _line(word="Compliant", verdict_class="Not applicable")
    with pytest.raises(ValidationError):
        _line(rule_tier="Verified")
    with pytest.raises(ValidationError):
        ar.AgentLeftOutRule(rule_book="b", clause="c", reason="boring")
    with pytest.raises(ValidationError):
        ar.AgentAskedRule(
            rule_book="b", clause="c", quote="q", paper_kind="k", tier="Machine"
        )
    with pytest.raises(ValidationError):
        ar.AgentRunSummary(
            paper_kind="k", paper_kind_source="s", counts_by_class={"Maybe": 1}
        )
    with pytest.raises(ValidationError):
        ar.AgentRulesUsed(paper_kind="k", left_out_counts={"other": 1})


def test_counts_are_not_negative():
    with pytest.raises(ValidationError):
        ar.AgentRunSummary(
            paper_kind="k",
            paper_kind_source="s",
            counts_by_class={"Proven by code": -1},
        )
    with pytest.raises(ValidationError):
        ar.AgentRunSummary(paper_kind="k", paper_kind_source="s", usd=-0.5)


def test_null_stays_null_in_json_never_zero():
    summary = json.loads(
        ar.AgentRunSummary(paper_kind="k", paper_kind_source="s").model_dump_json()
    )
    assert summary["usd"] is None
    assert summary["equipment_type"] is None
    assert summary["stop_reason"] is None
    line = json.loads(_line(page=None).model_dump_json())
    assert line["page"] is None
    with pytest.raises(ValidationError):
        _line(page=0)
    assert json.loads(ar.AgentLineList().model_dump_json())["next"] is None
    used = json.loads(ar.AgentRulesUsed(paper_kind="k").model_dump_json())
    assert used["rule_set_changed_by"] is None and used["equipment_type"] is None
    rule = json.loads(
        ar.AgentAskedRule(
            rule_book="b", clause="c", quote="q", paper_kind="k", tier="Owner"
        ).model_dump_json()
    )
    assert rule["field"] is None and rule["equipment"] is None
    trace = json.loads(
        ar.AgentTrace(
            item_id="i",
            paper_quote="p",
            rule_quote="r",
            rule_book="b",
            clause="c",
            model="m",
            reason="x",
        ).model_dump_json()
    )
    assert trace["page"] is None


def test_no_percentage_field_anywhere():
    for model in vars(ar).values():
        if isinstance(model, type) and issubclass(model, ar.BaseModel):
            for name in model.model_fields:
                assert "percent" not in name and "pct" not in name


def _gen():
    spec = importlib.util.spec_from_file_location(
        "gen_contract_types", REPO / "scripts" / "gen_contract_types.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_typescript_is_in_step_with_the_models():
    gen = _gen()
    module = next(m for m in gen.modules() if m.filename == "agent_review.ts")
    assert gen.drift(module) == []
    text = (REPO / "contracts" / "generated" / "agent_review.ts").read_text()
    for word in (*CLASSES, *WORDS, *TIERS, *REASONS):
        assert f'"{word}"' in text
    assert gen.main(["--check"]) == 0


def test_generated_typescript_drifts_when_a_word_is_added(tmp_path):
    gen = _gen()
    module = next(m for m in gen.modules() if m.filename == "agent_review.ts")
    stale = gen.render(module).replace('"Query"', '"Query" | "Extra"', 1)
    assert stale != gen.render(module)
    (tmp_path / "agent_review.ts").write_text(stale)
    assert gen.drift(module, tmp_path) != []
