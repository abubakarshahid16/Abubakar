"""#1682 (lane 6): the AI-created Pass is accepted only when code verifies both quotes. Danger zone: a Pass is created here."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_pass.py"
_V = APP / "ai_pass_verifier.py"
_TAGS = ("honesty", "critical", "pass")


def _m(n: int, desc: str, anchor: str, repl: str, kw: str) -> Mutation:
    return Mutation(
        id=f"M1682-{n:02d}",
        phase=1682,
        description=desc,
        path=_V,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the switch is not read: a Pass is created with AI_REVIEW_PASS_ENABLED off",
        "    if not settings.ai_review_pass_enabled:",
        "    if False:",
        "off_by_default",
    ),
    _m(
        2,
        "a value that does not satisfy the clause is accepted as a Pass",
        "        if verdict is not True:",
        "        if verdict is None:",
        "5_bar_against",
    ),
    _m(
        3,
        "a unit that cannot be compared is accepted",
        "        if verdict is None:\n            return no(PassReason.NOT_COMPARABLE)",
        "        if False:\n            return no(PassReason.NOT_COMPARABLE)",
        "cannot_be_compared",
    ),
    _m(
        4,
        "a scope the AI is unsure of is accepted",
        '    if str(proposal.get("scope_applies") or "").strip().lower() != "yes":',
        "    if False:",
        "scope_that_is_unsure",
    ),
    _m(
        5,
        "a Fail on the sheet for the same field no longer blocks a Pass",
        "and arp.is_fail_row(row):",
        "and False:",
        "fail_on_the_sheet",
    ),
    _m(
        6,
        "two values for the field no longer block a Pass",
        "    if len(_field_values(field, ctx)) > 1:",
        "    if False:",
        "two_values_for_the_field",
    ),
    _m(
        7,
        "a second reading that disagrees is accepted",
        '    if not _same_reading(proposal, proposal.get("second")):',
        "    if False:",
        "second_reading",
    ),
    _m(
        8,
        "negation or silence in the document quote is accepted",
        "    if _NEGATION.search(_fold(doc_quote)):",
        "    if False:",
        "silence_and_negation",
    ),
    _m(
        9,
        "a clause quote not in the stored clause text is accepted",
        "    if len(clause_quote) < arp.MIN_QUOTE_CHARS or _fold(clause_quote) not in _fold(\n        clause_text\n    ):",
        "    if False:",
        "clause_quote_that_is_not",
    ),
    _m(
        10,
        "a document quote on another page is accepted",
        '        or evidence[0].get("page") != page',
        "        or False",
        "stands_on_another_page",
    ),
)
