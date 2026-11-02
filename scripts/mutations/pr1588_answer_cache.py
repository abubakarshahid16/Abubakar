"""PR 1588: the answer cache's door in `claude_spend` (the budget gate) and the bar on the local
engine in `model_transport` and `comparison`. Ids M1588-01 onwards, phase 1588."""

from __future__ import annotations

from ._base import APP, Mutation

_CACHE = "tests/test_claude_answer_cache.py"
_BAR = "tests/test_claude_lane_no_local_engine.py"
_REVIEW = "tests/test_1588_review_findings.py"
_S = APP / "claude_spend.py"
_TAGS = ("budget", "answer_cache")


def _m(n, description, path, anchor, replacement, keyword, target=_CACHE, tags=_TAGS):
    return Mutation(
        id=f"M1588-{n}",
        phase=1588,
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
        "the metered lane ignores its stored answer, so a repeat is bought again",
        _S,
        "        if stored is not None:\n            asked[digest] = nth + 1\n",
        "        if False:\n            asked[digest] = nth + 1\n",
        "second_identical_call_on_the_metered_lane",
    ),
    _m(
        "02",
        "a stored answer is served without the approved-list gate",
        _S,
        "    _refuse_unapproved([step], model=model, prompt_sha256=prompt_sha256, batch=False)\n",
        "",
        "undeclared_caller",
    ),
    _m(
        "03",
        "a hit's ledger line does not say it was cached",
        _S,
        '    line["cached"] = True\n',
        "",
        "second_identical_call_on_the_metered_lane or spend_reports",
    ),
    _m(
        "04",
        "the ledger does not say what a hit saved",
        _S,
        '    line["saved_usd"] = round(float(stored.get("cost_usd") or 0.0), 6)\n',
        '    line["saved_usd"] = 0.0\n',
        "spend_reports",
    ),
    _m(
        "05",
        "the second ask of a stability check is served the first answer",
        _S,
        '        slot = f"{version}#{nth}" if nth else version\n',
        "        slot = version\n",
        "stability_check",
    ),
    _m(
        "06",
        "the metered lane never keeps an answer",
        _S,
        '        if keep_answer(key, step, answer, cost_usd=entry["cost_usd"], valid=valid):\n',
        "        if False:\n",
        "second_identical_call_on_the_metered_lane",
    ),
    _m(
        "07",
        "misses are not counted, so the report reads as all hits",
        APP / "claude_answer_cache.py",
        "            misses += 1\n",
        "            misses += 0\n",
        "spend_reports",
    ),
    _m(
        "08",
        "the gate lets a Claude-lane review reach the local engine",
        APP / "model_transport.py",
        '    if local_engine_bar.refuses(f"local engine {path}"):\n'
        "        raise LocalEngineNotLoaded(local_engine_bar.NOTE)\n",
        "",
        "gate_holds",
        target=_BAR,
        tags=("egress", "memory"),
    ),
    _m(
        "09",
        "the matcher's second ask is served the first answer",
        APP / "match_claude.py",
        '                version=f"{comparison.MATCH_PROMPT_VERSION}#{nth}",\n',
        "                version=comparison.MATCH_PROMPT_VERSION,\n",
        "matchers_two_asks",
    ),
    _m(
        "10",
        "the matcher keeps a choice its own check refuses",
        APP / "match_claude.py",
        "                keep_if=keep_if if candidates is not None else None,\n",
        "                keep_if=None,\n",
        "matcher_keeps_only",
    ),
    _m(
        "11",
        "the matcher on the local engine loads it in a Claude-lane run",
        APP / "comparison.py",
        "    if local_engine_bar.refuses(MATCH_STEP):\n        return None, MODEL_UNAVAILABLE\n",
        "",
        "matcher_on_the_local_engine",
        target=_BAR,
        tags=("egress", "memory"),
    ),
    _m(
        "12",
        "ledger lines do not name their run, so a run's figures read as nothing",
        _S,
        '    if (run := _RUN.get()) is not None:\n        entry["run"] = run\n',
        "",
        "cache_figures_cover",
        target=_REVIEW,
    ),
    _m(
        "13",
        "a run's cache figures count a chat and other runs",
        APP / "claude_answer_cache.py",
        '        if run_id is not None and entry.get("run") != run_id:\n            continue\n',
        "",
        "cache_figures_cover",
        target=_REVIEW,
    ),
)
