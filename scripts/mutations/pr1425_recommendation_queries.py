"""Order 288.2 step 2 (PR 1425): a recommendation of a named standard is raised as an engineer's query.
`comparison.py` is danger zone. Ids M1425-01 onwards, phase 1425. M1421-08 and -09 (the earlier `apart` step)
are replaced by -01 and -02 here: the code they anchored is gone."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_288_recommendations.py"
_TAGS = ("honesty", "o288")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1425-{n:02d}",
        phase=1425,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a recommendation of a standard the sheet does not name takes part in the review",
        APP / "comparison.py",
        "if recommendations.left_out(r, standard_id, design_standards, held_back):",
        "if False:",
        "does_not_name",
    ),
    _m(
        2,
        "a recommendation left out of the review is not counted",
        APP / "recommendations.py",
        "    held_back[TYPE] = held_back.get(TYPE, 0) + 1\n",
        "",
        "does_not_name",
    ),
    _m(
        3,
        "a recommendation that applies is not held as a query, so it vanishes",
        APP / "comparison.py",
        "    requirements = recommendations.hold_for_query(requirements, held_items)",
        "    requirements = [r for r in requirements if not recommendations.is_advice(r)]",
        "is_raised_as_a_query",
    ),
    _m(
        4,
        "the switch is ignored: every referenced standard raises its recommendations",
        APP / "recommendations.py",
        "    if not settings.recommendation_queries_enabled:\n        return set()\n",
        "",
        "switch_off",
    ),
    _m(
        5,
        "a recommendation query is grouped with the held rows, so 128 queries become one line",
        APP / "held_findings.py",
        'if len(group) > GROUP_ABOVE and kind != "recommendation":',
        "if len(group) > GROUP_ABOVE:",
        "its_own_query",
    ),
    _m(
        6,
        "a recommendation query carries the plain 'held' wording instead of the query",
        APP / "held_findings.py",
        'if kind == "recommendation":  # a query, never the "held" wording',
        "if False:",
        "is_raised_as_a_query",
    ),
    _m(
        7,
        "a recommendation is no longer kept apart from the shall rules at load, so the review compares it",
        APP / "recommendations.py",
        '    advice = [r for r in requirements if r.get("requirement_type") == TYPE]\n',
        "    advice = []\n",
        "is_raised_as_a_query",
    ),
    _m(
        8,
        "recommendation queries count in the standard's rules 'applies, not checked' (the headline moves)",
        APP / "requirement_split.py",
        '        if item.get("code") == recommendations.CODE:\n            queries.add(requirement_key(item["requirement"]))\n            continue\n',
        "",
        "is_raised_as_a_query",
    ),
    _m(
        9,
        "recommendation queries count in the clause-coverage denominator",
        APP / "clause_coverage.py",
        "    applicable = sum(counts[s] for s in STATES)\n",
        "    applicable = sum(counts[s] for s in STATES) + queries\n",
        "is_raised_as_a_query",
    ),
    _m(
        10,
        "recommendation queries move the unchecked share and the run's code (the whole-review check)",
        APP / "requirement_split.py",
        '        if item.get("code") == recommendations.CODE:\n            queries.add(requirement_key(item["requirement"]))\n            continue\n',
        "",
        "headline_numbers",
    ),
    _m(
        11,
        "a recommendation whose text failed the quality gate is admitted: the ledger no longer adds up",
        APP / "recommendations.py",
        "    if standard_id in design_standards and not unreadable:\n",
        "    if standard_id in design_standards:\n",
        "quality_gate",
    ),
)
