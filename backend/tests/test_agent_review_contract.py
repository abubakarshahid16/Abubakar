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
    if base["verdict_class"] in ar.GENERAL_ONLY and "part" not in base:
        base["part"] = (
            "engineering comment"  # a general review line always names its part
        )
    return ar.AgentLine(**base)


def test_vocabularies_are_exactly_the_owner_words():
    assert CLASSES == [
        "Proven by code",
        "AI verdict, two readers agree",
        "Not checked on this paper",
        "AI opinion, engineer to confirm",
        "AI opinion, rule not yet approved",
        "Query for the engineer",
        "Not applicable",
        "Not reviewed",
        "Not checked: rule book not held",
        "AI note, no rule book",
    ]
    assert WORDS == [
        "Pass",
        "Fail",
        "AI verdict: met",
        "AI verdict: not met",
        "AI verdict: not stated",
        "Needs a drawing or a calculation",
        "AI thinks: met",
        "AI thinks: not met",
        "Query",
        "Not applicable",
        "Not reviewed",
        "Not checked",
        "AI note",
    ]
    assert TIERS == ["Owner", "Engineer", "AI approved", "Not AI approved"]
    assert REASONS == [
        "needs another paper",
        "needs a human",
        "quote not found",
        "not labelled yet",
        "another equipment type",
        "rule book not held",
        "the paper names no equipment",
        "the paper names equipment the equipment list does not know",
        "the paper's equipment could not be read",
        "a part excluded by a value the paper states",
        "both labelling readers named other equipment",
    ]


TIERS_OR_NONE = [*TIERS, None]
OK_TIERS = ("Owner", "Engineer", "AI approved")
ALLOWED = {
    "Proven by code": ({"Pass", "Fail"}, {*OK_TIERS, None}),
    "Not checked on this paper": (
        {"Needs a drawing or a calculation"},
        {*OK_TIERS, None},
    ),
    "AI verdict, two readers agree": (
        {"AI verdict: met", "AI verdict: not met", "AI verdict: not stated"},
        {*OK_TIERS, None},
    ),
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
    "Not reviewed": ({"Not reviewed"}, {*TIERS, None}),
    # general review: no rule, so the tier is null only
    "Not checked: rule book not held": ({"Not checked"}, {None}),
    "AI note, no rule book": ({"AI note"}, {None}),
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


def test_not_reviewed_is_its_own_class_and_never_a_query_or_a_verdict():
    line = _line(verdict_class="Not reviewed", word="Not reviewed", rule_tier=None)
    assert line.word == "Not reviewed"
    for word in ("Query", "Pass", "Fail", "AI thinks: not met"):
        with pytest.raises(ValidationError):
            _line(verdict_class="Not reviewed", word=word)
    with pytest.raises(ValidationError):
        _line(verdict_class="Query for the engineer", word="Not reviewed")


def test_summary_counts_not_reviewed_and_rules_used_carries_coverage_and_read_from():
    assert (
        ar.AgentRunSummary(paper_kind="datasheet", paper_kind_source="x").not_reviewed
        == 0
    )
    book = ar.AgentBookCoverage(rule_book="Book A")
    assert book.model_dump() == {
        "rule_book": "Book A",
        "requirement_sentences": None,
        "covered_sentences": None,
        "unreadable_pages": None,
        "weak_pages": None,
        "below_half": None,
    }  # no coverage row: null, never 0
    rules = ar.AgentRulesUsed(paper_kind="datasheet", books=[book])
    assert rules.books[0].rule_book == "Book A"
    rule = ar.AgentAskedRule(
        rule_book="b", clause="1", quote="q", paper_kind="datasheet", tier="Owner"
    )
    assert rule.read_from == "text"
    assert (
        ar.AgentAskedRule(
            rule_book="b",
            clause="1",
            quote="q",
            paper_kind="datasheet",
            tier="Owner",
            read_from="scan",
        ).read_from
        == "scan"
    )
    with pytest.raises(ValidationError):
        ar.AgentAskedRule(
            rule_book="b",
            clause="1",
            quote="q",
            paper_kind="datasheet",
            tier="Owner",
            read_from="photo",
        )


def test_summary_and_rules_used_carry_the_equipment_state_and_notes():
    assert (
        ar.AgentRunSummary(paper_kind="d", paper_kind_source="x").equipment_notes == []
    )
    got = ar.AgentRulesUsed(
        paper_kind="d", equipment_state="usable", equipment_notes=["a"]
    )
    assert (got.equipment_state, got.equipment_notes) == ("usable", ["a"])
    assert ar.AgentLeftOutRule(
        rule_book="b", clause="1", reason="the paper names no equipment"
    )


# ---------------------------------------------------------------- general review (procedures and contracts, #781)

PARTS = list(ar.Part.__args__)
SOURCES = [*ar.TextSource.__args__, None]


def test_general_review_vocabularies_are_the_owner_words():
    assert PARTS == [
        "not held",
        "checklist",
        "paper against itself",
        "against project papers",
        "engineering comment",
    ]
    assert list(ar.TextSource.__args__) == ["quote", "the model's words"]
    assert list(ar.Mode.__args__) == ["rule review", "general review"]


@pytest.mark.parametrize(
    "klass,part,source", list(itertools.product(CLASSES, [None, *PARTS], SOURCES))
)
def test_part_and_text_source_go_with_the_classes_of_a_general_review_only(
    klass, part, source
):
    word = sorted(ALLOWED[klass][0])[0]
    tier = "Not AI approved" if klass == "AI opinion, rule not yet approved" else None
    build = lambda: ar.AgentLine(  # noqa: E731
        item_id="i",
        verdict_class=klass,
        word=word,
        clause="",
        rule_book="",
        reason="r",
        rule_tier=tier,
        part=part,
        text_source=source,
    )
    rule_only = klass in ar.RULE_REVIEW_ONLY
    needs_part = klass in ar.GENERAL_ONLY
    ok = not ((rule_only and (part or source)) or (needs_part and part is None))
    if ok:
        assert build().part == part
    else:
        with pytest.raises(ValidationError):
            build()


def test_a_rule_review_line_is_unchanged_and_carries_no_part():
    line = json.loads(_line().model_dump_json())
    assert line["part"] is None and line["text_source"] is None
    assert (line["verdict_class"], line["word"], line["rule_tier"]) == (
        "Proven by code",
        "Pass",
        "Owner",
    )


def test_a_general_review_line_never_carries_pass_fail_or_a_tier():
    for word in ("Pass", "Fail", "AI thinks: met", "AI thinks: not met"):
        for klass in ar.GENERAL_ONLY:
            with pytest.raises(ValidationError):
                _line(verdict_class=klass, word=word)
    for klass in ar.GENERAL_ONLY:
        for tier in TIERS:
            with pytest.raises(ValidationError):
                _line(
                    verdict_class=klass, word=ar.LINE_TABLE[klass][0][0], rule_tier=tier
                )


def test_the_summary_says_its_mode_and_the_project_papers_used():
    base = {"paper_kind": "procedure", "paper_kind_source": "s"}
    assert ar.AgentRunSummary(**base).mode == "rule review"
    assert ar.AgentRunSummary(**base).project_papers_used == []
    got = ar.AgentRunSummary(
        **base,
        mode="general review",
        project_papers_used=[{"document_id": "d", "name": "n"}],
        counts_by_class={
            "AI note, no rule book": 2,
            "Not checked: rule book not held": 1,
        },
    )
    assert got.project_papers_used[0].name == "n"
    with pytest.raises(ValidationError):
        ar.AgentRunSummary(**base, mode="guess")


def test_the_run_request_takes_an_optional_short_list_of_project_papers():
    assert ar.AgentRunRequest(submittal_document_id="d").project_document_ids == []
    assert ar.AgentRunRequest(
        submittal_document_id="d", project_document_ids=["a"]
    ).project_document_ids == ["a"]
    with pytest.raises(ValidationError):
        ar.AgentRunRequest(
            submittal_document_id="d", project_document_ids=[str(i) for i in range(11)]
        )
