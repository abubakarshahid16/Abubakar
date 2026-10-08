"""Mutations for question filler and plain decimals in the lexical gate
(2026-10-02, M1960-M1966): filler words are not distinctive terms, a plain
decimal is not a named subject, a designation and a clause number still are.
File: backend/app/lexical.py. Target: tests/test_lexical_filler_and_decimals.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_lexical_filler_and_decimals.py"
_TAG = ("gate_filler",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1960", phase=1960,
             description="say / says / said are counted as distinctive terms again",
             path=APP / "lexical.py",
             anchor='    "say", "says", "said", "saying", "mention", "mentions", "mentioned",',
             replacement='    "mention", "mentions", "mentioned",',
             target=_T, keyword="filler", tags=_TAG),
    Mutation(id="M1961", phase=1961,
             description="according is counted as a distinctive term again",
             path=APP / "lexical.py",
             anchor='    "state", "states", "stated", "according", "describe", "describes",',
             replacement='    "state", "states", "stated", "describe", "describes",',
             target=_T, keyword="filler", tags=_TAG),
    Mutation(id="M1962", phase=1962,
             description="a plain decimal is added to the distinctive terms",
             path=APP / "lexical.py",
             anchor="        if _PLAIN_DECIMAL.fullmatch(ident):\n            continue",
             replacement="        if False:\n            continue",
             target=_T, keyword="decimal", tags=_TAG),
    Mutation(id="M1963", phase=1963,
             description="a plain decimal looks like a named subject again",
             path=APP / "lexical.py",
             anchor="    if _PLAIN_DECIMAL.fullmatch(term):\n        return False",
             replacement="    if False:\n        return False",
             target=_T, keyword="named_subject or refuse", tags=_TAG),
    Mutation(id="M1964", phase=1964,
             description="a three-part clause number is dropped as if it were a decimal",
             path=APP / "lexical.py",
             anchor='_PLAIN_DECIMAL = re.compile(r"\\d+\\.\\d+")',
             replacement='_PLAIN_DECIMAL = re.compile(r"\\d+(?:\\.\\d+)+")',
             target=_T, keyword="clause", tags=_TAG),
    Mutation(id="M1965", phase=1965,
             description="every identifier, designations included, is dropped as a decimal",
             path=APP / "lexical.py",
             anchor='_PLAIN_DECIMAL = re.compile(r"\\d+\\.\\d+")',
             replacement='_PLAIN_DECIMAL = re.compile(r".+")',
             target=_T, keyword="designation", tags=_TAG),
    Mutation(id="M1966", phase=1966,
             description="an engineering word (thickness) is swallowed as filler",
             path=APP / "lexical.py",
             anchor='    "provided", "regarding", "concerning", "concerns",',
             replacement='    "provided", "regarding", "concerning", "concerns", "thickness",',
             target=_T, keyword="engineering", tags=_TAG),
)
