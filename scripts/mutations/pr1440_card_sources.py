"""Order 301.1 (PR #1440): the relief-valve checklist cards cite the clause that REQUIRES the value, the weak
sources are marked, and a card waiting for a standard we do not hold says so (reference/datasheet_checks.json,
danger zone). Ids M1440-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_296_rule_cards.py"
_J = APP / "reference" / "datasheet_checks.json"
_TAG = ("checklist", "rule-cards")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1440-01",
        phase=1440,
        description="the inlet-size card goes back to citing a definition",
        path=_J,
        anchor='"text": "The inlet size is stated.",\n          "source": {\n            "standard": "SAES-J-600",\n            "clause": "4.1.2"',
        replacement='"text": "The inlet size is stated.",\n          "source": {\n            "standard": "API 520-I",\n            "clause": "3.20"',
        target=_T,
        keyword="the_nine_cards_cite_the_clause_that_requires_the_value",
        tags=_TAG,
    ),
    Mutation(
        id="M1440-02",
        phase=1440,
        description="the design-pressure card loses its weak-source mark",
        path=_J,
        anchor='"field": "design_pressure"\n          },\n          "weak_source": true,\n',
        replacement='"field": "design_pressure"\n          },\n',
        target=_T,
        keyword="the_weak_sources_are_marked_on_the_card",
        tags=_TAG,
    ),
    Mutation(
        id="M1440-03",
        phase=1440,
        description="the MAWP-vs-design card stops saying it needs a standard we do not hold",
        path=_J,
        anchor='"needs": "a standard we do not hold",\n          "severity": "major"',
        replacement='"severity": "major"',
        target=_T,
        keyword="every_relief_valve_card_is_tested_except_the_two",
        tags=_TAG,
    ),
)
