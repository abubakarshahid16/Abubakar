"""The copy words of the CRS routes, in ONE home (V2, audit item 13).

The rule-check routes said `internal` or `issue`; the AI-review route said `internal` or `contractor`; the screens and the
owner say "company copy" and "contractor copy". A natural word answered 422. Now every route takes the same four words and
maps them to the copy it already knew:

    internal, company     -> the company's internal copy
    contractor, issue     -> the copy that goes to the contractor (the rule-check route calls it `issue`)

Any other word is refused (422) exactly as before. Nothing about WHAT a copy holds changes here: only the spelling.
"""

from __future__ import annotations

from fastapi import HTTPException

INTERNAL_WORDS = ("internal", "company")
CONTRACTOR_WORDS = ("contractor", "issue")
ALL_WORDS = INTERNAL_WORDS + CONTRACTOR_WORDS


def _check(word: str) -> str:
    low = (word or "").strip().lower()
    if low not in ALL_WORDS:
        raise HTTPException(
            status_code=422,
            detail=f"copy must be one of: {', '.join(ALL_WORDS)}",
        )
    return low


def rule_check_copy(word: str) -> str:
    """`internal` or `issue`: the words the rule-check CRS code uses."""
    return "internal" if _check(word) in INTERNAL_WORDS else "issue"


def agent_copy(word: str) -> str:
    """`internal` or `contractor`: the words the AI-review CRS code uses."""
    return "internal" if _check(word) in INTERNAL_WORDS else "contractor"
