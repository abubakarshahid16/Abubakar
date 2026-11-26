"""The order of precedence decides (lead-4, 26 Nov 2026; the u6 miss list: "a precedence order compared but not decided"). A
comment that says two ranked parts conflict gets the contract's own deciding sentence; a comment whose ranking the list
contradicts gets the list's correction; nothing else changes; off (AIM_U13_ENABLED), no line changes. Invented contract only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.aim_review import contract_code, updates
from app.aim_review import contract_precedence as X

PAGES = {
    1: "Order of Precedence\n1. Schedule A\n2. Schedule B\n3. Schedule C\n\n4.1 Invented next clause"
}


def _decided(*comments):
    lines = [{"comment": c} for c in comments]
    return lines, X.decide(lines, PAGES)


def test_a_conflict_between_two_ranked_parts_is_decided_by_the_order_of_precedence():
    lines, n = _decided(
        "Schedule C states 30 days whereas Schedule A states 45 days; please confirm."
    )
    assert n == 1
    assert lines[0]["comment"].endswith(
        "The order of precedence (page 1) ranks Schedule A above Schedule C, so Schedule A governs where they differ."
    )


def test_a_ranking_the_list_contradicts_gets_the_lists_correction():
    lines, n = _decided(
        "Schedule C prevails over Schedule A for the invented payment terms."
    )
    assert n == 1 and lines[0]["comment"].endswith(
        "Note: The order of precedence on page 1 ranks Schedule A above Schedule C."
    )


@pytest.mark.parametrize(
    "comment",
    [
        "Schedule B is missing an invented date.",  # one ranked part: nothing to decide
        "Schedule A and Schedule C differ; Schedule A prevails over Schedule C.",  # already decided (and right)
        "Schedule A and Schedule Z differ on the invented rate.",  # Z is not on the list
        "Schedule A, Schedule B and Schedule C conflict on the invented rate.",  # three parts: not one pair
        "Schedule A and Schedule C agree on the invented rate.",  # no conflict
    ],
)
def test_anything_else_is_left_as_it_is(comment):
    lines, n = _decided(comment)
    assert n == 0 and lines[0]["comment"] == comment


def test_a_contract_with_no_order_of_precedence_changes_nothing():
    lines = [
        {"comment": "Schedule C states 30 days whereas Schedule A states 45 days."}
    ]
    assert X.decide(lines, {1: "Invented contract text with no ranked list."}) == 0


@pytest.mark.parametrize("on", [False, True])
def test_the_hook_decides_only_with_update_13s_switch_and_only_for_a_contract(
    monkeypatch, on
):
    monkeypatch.setattr(updates, "u13", lambda: on)
    monkeypatch.setattr(
        contract_code, "held_labels", lambda conn, paper_id, allowed: set()
    )
    monkeypatch.setattr(contract_code, "lines", lambda pages, identity, held=None: [])
    text = "Schedule C states 30 days whereas Schedule A states 45 days."
    for kind, changes in (("contract", on), ("datasheet", False)):
        state = SimpleNamespace(
            identity={"kind": kind},
            paper_id="doc_invented",
            decided=[{"comment": text}],
        )
        contract_code.add_lines(None, state, SimpleNamespace(pages=PAGES))
        assert (state.decided[0]["comment"] != text) is changes, kind
