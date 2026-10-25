"""Orders 180.1 item 2: a plain statement supports a blank-field row only if it asks the sheet
to state something. `match_rules.py` is a verdict-path module (PR #1249: ids M1249-01 onwards,
phase 1249)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_180_support_asks.py"
_TAGS = ("honesty", "180")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1249-01",
        phase=1249,
        description="a statement that asks for no stated value still supports a blank field",
        path=APP / "match_rules.py",
        anchor='    if fact.get("is_blank") and not statement_asks.asks_to_state(requirement):\n        return NOT_ASKED\n',
        replacement="    pass\n",
        target=_T,
        keyword="only_a_blank_field",
        tags=_TAGS,
    ),
    Mutation(
        id="M1249-02",
        phase=1249,
        description="a requirement with its own value is judged like a plain statement",
        path=APP / "statement_asks.py",
        anchor='    if requirement.get("requirement_type") != "statement":\n        return True\n',
        replacement="    pass\n",
        target=_T,
        keyword="never_judged",
        tags=_TAGS,
    ),
    Mutation(
        id="M1249-03",
        phase=1249,
        description="every statement is taken as asking to state something",
        path=APP / "statement_asks.py",
        anchor="        _ASKS_TO_STATE.search(text) is not None\n",
        replacement="        True\n",
        target=_T,
        keyword="does_not_ask",
        tags=_TAGS,
    ),
)
