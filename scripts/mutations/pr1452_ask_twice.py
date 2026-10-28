"""Order 305.4 part A (PR #1452): the converter's second question (converter_second.py, standards_converter.py,
converter_review.py). Ids M1452-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_S = APP / "converter_second.py"
_C = APP / "standards_converter.py"
_R = APP / "converter_review.py"
_T = "tests/test_305_ask_twice.py"
_TAG = ("converter", "ask-twice")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1452-01",
        phase=1452,
        description="a condition the first answer missed does not matter",
        path=_S,
        anchor="    if not only_when or not first:\n        return False, DISAGREES",
        replacement="    if not only_when or not first:\n        return True, None",
        target=_T,
        keyword="hidden_only_if_the_first_answer_missed",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-02",
        phase=1452,
        description="always yes is accepted beside a condition",
        path=_S,
        anchor="        return (False, DISAGREES) if first or only_when else (True, None)",
        replacement="        return (True, None)",
        target=_T,
        keyword="first_condition_the_second_answer_denies",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-03",
        phase=1452,
        description="a condition the clause does not say is accepted",
        path=_S,
        anchor="        or fold(only_when) not in fold(sentence)",
        replacement="        or False",
        target=_T,
        keyword="real_but_whose_words_are_invented",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-04",
        phase=1452,
        description="two different conditions agree",
        path=_S,
        anchor="    if not _same_words(first, only_when):\n        return False, DISAGREES",
        replacement="    if False:\n        return False, DISAGREES",
        target=_T,
        keyword="two_different_conditions_are_a_disagreement",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-05",
        phase=1452,
        description="an unreadable second answer keeps the row verified",
        path=_S,
        anchor="        return False, UNREADABLE",
        replacement="        return True, None",
        target=_T,
        keyword="unreadable_second_answer",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-06",
        phase=1452,
        description="the second question is not asked by default",
        path=_C,
        anchor="ASK_TWICE = True  #",
        replacement="ASK_TWICE = False  #",
        target=_T,
        keyword="shipped_default_is_to_ask_twice",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-07",
        phase=1452,
        description="the review reads a verified row that was not asked twice from a file that asked twice",
        path=_R,
        anchor='                and (e.get("asked_twice") is True or not asked)',
        replacement="",
        target=_T,
        keyword="review_refuses_a_verified_row",
        tags=_TAG,
    ),
    Mutation(
        id="M1452-08",
        phase=1452,
        description="a one-word condition agrees with anything that contains it",
        path=_S,
        anchor="(short in long_ and len(short.split()) >= 2)",
        replacement="(short in long_)",
        target=_T,
        keyword="one_word_condition_does_not_agree",
        tags=_TAG,
    ),
)
