"""PR 1586: the 5.5 Claude models. `claude_spend.py` is the budget gate and `comparison.py` the run
record's writer, so both get entries (the request shape in `reasoning_provider` and `claude_models`
has ordinary tests). Ids M1586-01 onwards, phase 1586."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_claude_5_5_models.py"
_S = APP / "claude_spend.py"
_TAGS = ("budget", "claude_5_5")


def _m(n, description, path, anchor, replacement, keyword, target=_T, tags=_TAGS):
    return Mutation(
        id=f"M1586-{n}",
        phase=1586,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=target,
        keyword=keyword,
        tags=tags,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "Haiku 5.5 has no price, so it falls to the dearest family (50x)",
        _S,
        '    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),\n',
        "",
        "each_id_finds_its_own_family_price",
    ),
    _m(
        "02",
        "a Haiku prompt of exactly 100K tokens is charged the long rate card",
        _S,
        "            if prompt_tokens > LONG_PROMPT_TOKENS and key in LONG_PROMPT_PRICES:\n",
        "            if prompt_tokens >= LONG_PROMPT_TOKENS and key in LONG_PROMPT_PRICES:\n",
        "prompt_at_100k_tokens",
    ),
    _m(
        "03",
        "cached tokens no longer count towards the prompt length, so a long prompt is underpriced",
        _S,
        '        + int(usage.get("cache_read_input_tokens") or 0)\n    )\n    p_in, p_out, p_write, p_read',
        "    )\n    p_in, p_out, p_write, p_read",
        "cached_tokens_count",
    ),
    _m(
        "04",
        "the worst case of a long Haiku prompt uses the cheap card, so a cap can be crossed",
        _S,
        "    p_in, p_out, p_write, _ = price_for(model, tokens_in)\n",
        "    p_in, p_out, p_write, _ = price_for(model)\n",
        "haiku_worst_case",
    ),
    _m(
        "05",
        "a run record names the model that was only asked for (an open or estimated ledger line)",
        _S,
        '        answered = entry.get("settles") and not entry.get("estimated")\n',
        "        answered = True\n",
        "models_used",
    ),
    _m(
        "06",
        "the metered call forgets the model that answered, so the datasheet run names the one asked for",
        _S,
        '        _metered.last_model = str(answer.get("model") or "") or _metered.last_model\n',
        "",
        "keeps_the_model_that_answered or datasheet_reader_names",
    ),
    _m(
        "07",
        "a finished run no longer records which models answered: model_name stays NULL",
        APP / "comparison.py",
        "    claude_models.record_run(review_run_id, match_step=MATCH_STEP)\n",
        "",
        "run_record_and_audit_name",
        target="tests/test_1525_review_audit.py",
        tags=("honesty", "claude_5_5"),
    ),
    _m(
        "08",
        "the budget gate prices the short cap asked for, not the raised cap the request carries",
        _S,
        "    max_tokens = output_cap(model, max_tokens)  # what the request will actually carry\n",
        "",
        "budget_gate_sees_the_raised_limit",
    ),
    _m(
        "09",
        "a large cap is lowered to the floor on a model that thinks by default",
        _S,
        "        return max(int(max_tokens), int(settings.claude_min_output_tokens))\n",
        "        return int(settings.claude_min_output_tokens)\n",
        "cap_above_the_floor",
    ),
)
