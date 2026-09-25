"""Mutations of `backend/app/scope_records.py` (B5 scope records)."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M603", phase=61,
        description="min/max/unit required again on every limit - non-numeric limits "
                    "are rejected as invalid output (2 of 8 in the M-03 run)",
        path=APP / "scope_records.py",
        anchor='    "required": ["kind", "term", "quote", "page"]}\n',
        replacement='    "required": ["kind", "term", "min", "max", "unit", "quote", "page"]}\n',
        target="tests/test_scope_records.py",
        keyword="non_numeric_limit_needs_no",
        tags=("applicability",),
    ),
    Mutation(
        id="M604", phase=61,
        description="the 3-re-read confirmation of NOT_APPLICABLE is skipped",
        path=APP / "scope_records.py",
        anchor="    if decision[\"decision\"] != applicability_v2.NOT_APPLICABLE:\n"
               "        return {**decision, \"confirmations\": None}\n",
        replacement="    return {**decision, \"confirmations\": None}\n",
        target="tests/test_scope_records.py",
        keyword="three_rereads_agree",
        tags=("honesty", "applicability"),
    ),
    Mutation(
        id="M605", phase=61,
        description="an item whose quote is not on its page is kept",
        path=APP / "scope_records.py",
        anchor="            if isinstance(it, dict) and it.get(\"page\") in texts and quote_verified(it.get(\"quote\"), texts[it[\"page\"]]):\n",
        replacement="            if isinstance(it, dict):\n",
        target="tests/test_scope_records.py",
        keyword="unverifiable_quote_is_dropped",
        tags=("honesty", "applicability"),
    ),
)
