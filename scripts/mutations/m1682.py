"""#1682 (lane 6): the AI-created Pass is accepted only when code verifies both quotes. Danger zone: a Pass is created here."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_pass.py"
_A = "tests/test_ai_pass_attacks.py"
_V = APP / "ai_pass_verifier.py"
_TAGS = ("honesty", "critical", "pass")


def _m(
    n: int, desc: str, anchor: str, repl: str, kw: str, target: str = _T
) -> Mutation:
    return Mutation(
        id=f"M1682-{n:02d}",
        phase=1682,
        description=desc,
        path=_V,
        anchor=anchor,
        replacement=repl,
        target=target,
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
        "    if verdict is not True:",
        "    if verdict is None:",
        "5_bar_against",
    ),
    _m(
        3,
        "a unit that cannot be compared is accepted",
        "    if verdict is None:\n        return None, PassReason.NOT_COMPARABLE",
        "    if False:\n        return None, PassReason.NOT_COMPARABLE",
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
        7,
        "the second reading may be the same call or an id the AI made up",
        "if not isinstance(second, dict) or not first_id or first_id not in ids:",
        "if not isinstance(second, dict):",
        "second_reading_must_be_a_different_call",
        _A,
    ),
    _m(
        8,
        "a document value qualified by a comparator or a range is read as a plain value",
        '    m = re.fullmatch(rf"{re.escape(_fold(field))}\\s*[:=]?\\s*(?P<v>\\S.*)", _fold(quote))',
        '    m = re.search(rf"{re.escape(_fold(field))}\\s*[:=]?\\s*(?P<v>\\S.*)", _fold(quote))',
        "right_number_under_the_wrong_label",
        _A,
    ),
    _m(
        10,
        "a document quote on another page is accepted",
        '        or evidence[0].get("page") != page',
        "        or False",
        "stands_on_another_page",
    ),
    _m(
        11,
        "an ambiguous thousands separator is read as a decimal",
        "    if _UNREADABLE.search(folded):\n        return None",
        "    if False:\n        return None",
        "thousands_separator_is_never_read",
        _A,
    ),
    _m(
        13,
        "a term is accepted when it is only part of the value",
        "    if _squash(cell) != _squash(term):",
        "    if _squash(term) not in _squash(cell):",
        "whole_affirmative_value",
        _A,
    ),
    _m(
        18,
        "a Fail on the same clause under another label no longer blocks a Pass",
        "        ) and re.search(_REF_NUMBER.format(re.escape(clause_number)), about):",
        "        ) and False and re.search(_REF_NUMBER.format(re.escape(clause_number)), about):",
        "same_clause_under_another_label",
        _A,
    ),
    _m(
        19,
        "a Fail on the same field role no longer blocks a Pass",
        "        if _overlap(mine, _words(about)):\n            return PassReason.FAIL_PRESENT",
        "        if False:\n            return PassReason.FAIL_PRESENT",
        "fail_on_a_field_with_an_overlapping_name",
        _A,
    ),
    _m(
        20,
        "two values for the field in the document no longer block a Pass",
        "    if len(figures) > 1:",
        "    if len(figures) > 99:",
        "second_value_under_an_overlapping_name",
        _A,
    ),
    _m(
        21,
        "the clause subject only has to share a word with the field",
        "    if not mine or mine != theirs:",
        "    if not mine or not (mine & theirs):",
        "same_words_both_ways",
        _A,
    ),
    _m(
        22,
        "the clause text may hold more than the one closed sentence",
        "    number = _SHAPE_NUMBER.fullmatch(plain)",
        "    number = _SHAPE_NUMBER.match(plain)",
        "not_exactly_the_closed_shape",
        _A,
    ),
    _m(
        23,
        "a placeholder in the label's block no longer blocks a Pass",
        "            if any(_PLACEHOLDER.search(_fold(b)) for b in block):",
        "            if False:",
        "whole_label_block_on_every_page",
        _A,
    ),
    _m(
        24,
        "the term path loses its whole-document guard",
        "    if not dimension and (len(cells) > 1",
        "    if False and (len(cells) > 1",
        "term_path_has_the_same",
        _A,
    ),
)
