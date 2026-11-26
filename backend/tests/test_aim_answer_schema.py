"""The answer shape of each model step as a JSON schema (forced on the local engine): it says what the prompt asks, so a
valid answer of the method's own shape passes it and the judge is asked for "numbers" on every item. Invented answers only."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import answer_schema as A
from app.aim_review import prompts as P


class Invalid(ValueError):
    pass


def validate(value, s: dict) -> None:
    """The few schema words the shapes use (type, enum, required, properties, items, anyOf): enough to test them here."""
    if "anyOf" in s:
        for option in s["anyOf"]:
            try:
                validate(value, option)
            except Invalid:
                continue
            return
        raise Invalid("no option fits")
    if "enum" in s and value not in s["enum"]:
        raise Invalid(f"{value!r} not in the enum")
    kind = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }.get(s.get("type", ""), object)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise Invalid(f"{value!r} is not a {s.get('type')}")
    if isinstance(value, dict):
        for k in s.get("required", []):
            if k not in value:
                raise Invalid(f"{k} missing")
        for k, sub in s.get("properties", {}).items():
            if k in value and sub:
                validate(value[k], sub)
    if isinstance(value, list) and "items" in s:
        for v in value:
            validate(v, s["items"])


def test_only_a_step_with_a_full_shape_is_forced_and_every_other_step_keeps_plain_json():
    """26 Nov 2026: a schema naming only the answer keys let the 14B write the paper's identity as its kind alone (30 tokens
    against 741), so the review lost the equipment type and subject: such a step gets no schema."""
    forced = {s for s in P.ANSWER_KEYS if A.for_step(s)}
    assert forced == {
        "aim_judge",
        "aim_second_read",
        "aim_checklist",
        "aim_checklist_retry",
        "aim_checklist_knowledge",
    }
    for step in forced:
        assert A.for_step(step)["type"] == "object" and set(
            A.for_step(step)["required"]
        ) == set(P.ANSWER_KEYS[step])
    assert A.for_step("aim_identify") is None and A.for_step("not_a_step") is None


def test_the_judges_labels_are_the_methods_and_numbers_is_asked_on_every_item():
    s = A.for_step("aim_judge")
    one = s["properties"]["judgments"]["items"]
    assert (
        one["properties"]["label"]["enum"] == list(aim_review.LABELS)
        and "numbers" in one["required"]
    )


@pytest.mark.parametrize(
    "step,answer",
    [
        ("aim_judge", {"judgments": [{"id": "C001", "label": "Not met", "field": "Invented field", "page": 2,
                                      "quote": "Invented allowance: 1.5 mm", "comment": "Please revise.",
                                      "numbers": {"paper_value": "1.5", "paper_unit": "mm", "operator": ">=",
                                                  "rule_value": "3", "rule_unit": "mm"}}]}),
        ("aim_judge", {"judgments": [{"id": "C002", "label": "Question", "field": "f", "page": None, "quote": "",
                                      "numbers": None, "comment": "Please state it.", "deferred": True, "ask": "confirm"}]}),
        ("aim_second_read", {"reads": [{"n": 3, "label": "Question", "page": 1, "quote": "q", "reason": "r"}]}),
        ("aim_checklist", {"items": [{"topic": "t", "what_to_check": "w", "applies_when": "always", "paper_fields": ["f"],
                                      "kind": "limit", "paper_pages": [1], "book": "B1", "clause": "4.1", "page": 3,
                                      "rule_quote": "invented rule words", "source": "held standard"}]}),
        # rule_quote and source are required since F's 9B run 91f40e4f (left out, ~190 items had nothing to find)
    ],
)  # fmt: skip
def test_an_answer_of_the_methods_own_shape_passes_its_schema(step, answer):
    validate(answer, A.for_step(step))


def test_a_label_outside_the_methods_or_a_judgment_without_numbers_fails_the_schema():
    s = A.for_step("aim_judge")
    base = {
        "id": "C1",
        "label": "Question",
        "field": "f",
        "page": 1,
        "quote": "q",
        "numbers": None,
        "comment": "c",
    }
    with pytest.raises(Invalid):
        validate({"judgments": [{**base, "label": "Compliant"}]}, s)
    with pytest.raises(Invalid):
        validate({"judgments": [{k: v for k, v in base.items() if k != "numbers"}]}, s)
