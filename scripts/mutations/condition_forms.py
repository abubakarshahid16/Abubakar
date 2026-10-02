"""Mutations for the condition grammar (2026-10-02, M1970-M1977): commas inside
a circumstance, where/if/when/unless forms, long and unparseable conditions.
File: backend/app/requirements_3b.py (`parse_condition`). Target:
tests/test_condition_grammar_forms.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_condition_grammar_forms.py"
_TAG = ("condition_forms",)
_P = APP / "requirements_3b.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1970", phase=1970,
             description="the condition is cut at the first comma again",
             path=_P,
             anchor="            cut = max(i for i in commas if i < main.start())",
             replacement="            cut = commas[0]",
             target=_T, keyword="commas_inside or when_form", tags=_TAG),
    Mutation(id="M1971", phase=1971,
             description="an 'if' sentence is no longer read as conditional",
             path=_P,
             anchor='r"\\b(?P<kw>for|where|when|if|unless|in\\s+the',
             replacement='r"\\b(?P<kw>for|where|when|unless|in\\s+the',
             target=_T, keyword="if_form", tags=_TAG),
    Mutation(id="M1972", phase=1972,
             description="a condition with no obligation phrase is no longer split at its one comma",
             path=_P,
             anchor='        elif keyword in ("where", "when", "if", "unless") and len(commas) == 1:',
             replacement="        elif False:",
             target=_T, keyword="if_form", tags=_TAG),
    Mutation(id="M1973", phase=1973,
             description="'unless' is dropped from the condition, inverting its meaning",
             path=_P,
             anchor='    if keyword == "unless" and condition:',
             replacement="    if False:",
             target=_T, keyword="unless", tags=_TAG),
    Mutation(id="M1974", phase=1974,
             description="the length limit drops back to the old 80 characters",
             path=_P,
             anchor="_CONDITION_MAX = 240",
             replacement="_CONDITION_MAX = 80",
             target=_T, keyword="longer_than", tags=_TAG),
    Mutation(id="M1975", phase=1975,
             description="an obligation phrase inside the circumstance ends it",
             path=_P,
             anchor="        main = _MAIN_CLAUSE.search(rest, commas[0])",
             replacement="        main = _MAIN_CLAUSE.search(rest)",
             target=_T, keyword="modal_phrase", tags=_TAG),
    Mutation(id="M1976", phase=1976,
             description="a sentence whose circumstance cannot be separated gets the whole rest as its condition",
             path=_P,
             anchor="    if cut is None:\n        return None\n    condition = rest[:cut]",
             replacement="    if cut is None:\n        cut = len(rest)\n    condition = rest[:cut]",
             target=_T, keyword="never_invented", tags=_TAG),
    Mutation(id="M1977", phase=1977,
             description="an over-long circumstance is returned instead of refused",
             path=_P,
             anchor="    if len(condition) < 3 or len(condition) > _CONDITION_MAX:",
             replacement="    if len(condition) < 3:",
             target=_T, keyword="over_long", tags=_TAG),
)
