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
    # ---- b5-quality 2026-09-25: v4 finder, cue context, batch read ----------
    Mutation(
        id="M660", phase=62,
        description="the scope finder looks for headings on pages 1-10 only (a scope on page 18 is missed)",
        path=APP / "scope_records.py",
        anchor='    rows = list(connect().execute("SELECT page_no, text FROM pages WHERE document_id=? ORDER BY page_no",\n',
        replacement='    rows = list(connect().execute("SELECT page_no, text FROM pages WHERE document_id=? AND page_no <= 10 ORDER BY page_no",\n',
        target="tests/test_scope_records.py",
        keyword="late_in_a_long_standard",
        tags=("applicability",),
    ),
    Mutation(
        id="M661", phase=62,
        description="a heading with its text on the same line ('Scope. This code applies ...') is not a heading",
        path=APP / "scope_records.py",
        anchor='(?:[:;.][ \\t]*(?=\\S)|:?[ \\t]*$)")\n',
        replacement=':?[ \\t]*$)")\n',
        target="tests/test_scope_records.py",
        keyword="same_line_is_found",
        tags=("applicability",),
    ),
    Mutation(
        id="M662", phase=62,
        description="a scope that runs off the end of its page does not bring the next page",
        path=APP / "scope_records.py",
        anchor="            if (primary and nxt and len(text) - m.end() < PASSAGE_CHARS\n",
        replacement="            if (False and nxt and len(text) - m.end() < PASSAGE_CHARS\n",
        target="tests/test_scope_records.py",
        keyword="runs_off_its_page",
        tags=("applicability",),
    ),
    Mutation(
        id="M663", phase=62,
        description="the cue context loses the list intro ('excluded from the scope are:')",
        path=APP / "scope_records.py",
        anchor="    if colon >= 0 and colon < (start if start >= 0 else 0):\n",
        replacement="    if False:\n",
        target="tests/test_scope_records.py",
        keyword="cue_context_is_the_list_intro",
        tags=("applicability",),
    ),
    Mutation(
        id="M664", phase=62,
        description="the batch read never retries an invalid answer",
        path=APP / "scope_records.py",
        anchor="        todo = [d for d in ids if responses[d] and usable(responses[d][-1]) is None] if retry else ids\n",
        replacement="        todo = [] if retry else ids\n",
        target="tests/test_scope_records.py",
        keyword="retries_only_the_invalid",
        tags=("applicability",),
    ),
    Mutation(
        id="M676", phase=62,
        description="a batch round the budget check refused is sent anyway",
        path=APP / "scope_records.py",
        anchor="        if may_send is not None and not may_send(packets):\n            continue\n",
        replacement="",
        target="tests/test_scope_records.py",
        keyword="budget_refuses_is_not_sent",
        tags=("safety", "budget"),
    ),
)
