"""A second look at G2's order-of-magnitude line (G2_SCALE, update 14, switch off; lead-4, 26 Nov 2026): can it fire on a NORMAL, correct
value? G2_SCALE asks the AI for "the plausible range from engineering knowledge". If the AI puts its plausible bound in `rule_value`,
code looks for that number in the judged paper quote (`steps._paper_limit`). When an UNRELATED value on the same line happens to carry
that number, code pairs the two, compares them, and sends a compare-backed sentence with both numbers: a false alarm on two correct
values of two different things. Invented values only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.aim_review import always, steps
from app.config import settings


@pytest.fixture
def u13(monkeypatch):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)


LINE = "Mean time between failures 200000 h; design life 20 years."
INTERVALS = "Proof test interval 120 months; visual inspection every 12 months."


def _g2() -> dict:
    return {
        "id": "G2",
        "topic": always.TOPIC,
        "what_to_check": always.G2_CHECK,
        "book": "",
        "clause": "",
        "rule_quote": "",
        "source": steps.KNOWLEDGE,
        "always_on": True,
        "kind": "limit",
        "named_books": [],
    }


def _judged(quote: str, value: str, unit: str, bound: str, bound_unit: str) -> dict:
    """The AI's answer as G2_SCALE asks for it: a single value judged implausible, its plausible bound from engineering knowledge."""
    return {
        "label": "Not met",
        "quote": quote,
        "page": 1,
        "field": "",
        "comment": "Implausible by an order of magnitude for this item (AI opinion, engineering knowledge).",
        "numbers": {
            "paper_value": value,
            "paper_unit": unit,
            "operator": "<=",
            "rule_value": bound,
            "rule_unit": bound_unit,
        },
    }


def _decide(text: str, j: dict) -> dict:
    return steps._decide(_g2(), j, SimpleNamespace(pages={1: text}), {}, "")


def test_a_knowledge_bound_that_matches_an_unrelated_number_on_the_line_is_never_a_compare_of_two_paper_values(
    u13,
):
    line = _decide(LINE, _judged(LINE, "200000", "h", "20", "years"))
    cmp_ = line.get("code_compare") or {}
    # an MTBF and a design life are two different properties: code must not compare them because the AI's bound was "20"
    assert cmp_.get("read_from") != "verified paper quotes", (
        line["label"],
        line["comment"],
        line["code"],
    )


def test_the_same_with_two_intervals_of_different_tasks_on_one_line(u13):
    line = _decide(INTERVALS, _judged(INTERVALS, "120", "months", "12", "months"))
    cmp_ = line.get("code_compare") or {}
    assert cmp_.get("read_from") != "verified paper quotes", (
        line["label"],
        line["comment"],
        line["code"],
    )


def test_a_real_second_value_the_ai_quotes_on_the_paper_is_still_compared(u13):
    """What G2_COUNTS asks for keeps working: the AI quotes one value and gives the other with ITS OWN quote (limit_quote)."""
    text = "Number of nozzles 6.\nNozzle schedule lists N1, N2, N3, N4, N5: 5 nozzles."
    j = {
        "label": "Not met",
        "quote": "Number of nozzles 6.",
        "page": 1,
        "field": "nozzles",
        "comment": "The count disagrees with the list.",
        "numbers": {
            "paper_value": "6",
            "paper_unit": "",
            "operator": "==",
            "rule_value": "5",
            "rule_unit": "",
            "limit_quote": "Nozzle schedule lists N1, N2, N3, N4, N5: 5 nozzles.",
            "limit_page": 1,
        },
    }
    line = _decide(text, j)
    assert (line.get("code_compare") or {}).get("read_from") == "verified paper quotes"


def test_the_switch_off_keeps_main_exactly(monkeypatch):
    """Claude reviews are the baseline: with the update switch off the pairing is as on main (the false alarm included)."""
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    line = _decide(INTERVALS, _judged(INTERVALS, "120", "months", "12", "months"))
    assert (line.get("code_compare") or {}).get("read_from") == "verified paper quotes"
