"""Order 288.2 (PR 1421): a "should" sentence is recorded as a recommendation with no limit.
`standards.py` requirement extraction is danger zone by planner order. Ids M1421-01 onwards, phase 1421."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_288_recommendations.py"
_TAGS = ("honesty", "o288")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1421-{n:02d}",
        phase=1421,
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
        "a 'should' sentence is not recorded at all",
        APP / "standards.py",
        "if not mandatory and not recommendations.is_recommendation(sentence):",
        "if not mandatory:",
        "should_sentence_is_recorded",
    ),
    _m(
        2,
        "a recommendation keeps the number it parsed, so it can be read as a limit",
        APP / "standards.py",
        "if is_definition or not mandatory:",
        "if is_definition:",
        "no_limit",
    ),
    _m(
        3,
        "a sentence with 'shall' is no longer mandatory, so it is stored as a recommendation",
        APP / "standards.py",
        "mandatory = bool(_MANDATORY.search(sentence))",
        "mandatory = False",
        "shall_sentence_is_unchanged",
    ),
    _m(
        4,
        "a review may read a recommendation",
        APP / "standards.py",
        'if _column(row, "requirement_type") in recommendations.NOT_REVIEWED:',
        'if _column(row, "requirement_type") == requirement_quality.DEFINITION:',
        "no_existing_review_path",
    ),
    _m(
        5,
        "'should' alone is no longer a recommendation (only 'should not')",
        APP / "recommendations.py",
        r'_RECOMMEND = re.compile(r"\bshould(?:\s+not)?\b", re.IGNORECASE)',
        r'_RECOMMEND = re.compile(r"\bshould\s+not\b", re.IGNORECASE)',
        "which_words_make_a_recommendation",
    ),
    _m(
        6,
        "the type is not registered, so the API cannot return it",
        APP / "requirements_3b.py",
        "STORED_REQUIREMENT_TYPES += (recommendations.TYPE,)\n",
        "",
        "type_is_stored",
    ),
    _m(
        7,
        "'may' becomes a recommendation too",
        APP / "recommendations.py",
        r'_RECOMMEND = re.compile(r"\bshould(?:\s+not)?\b", re.IGNORECASE)',
        r'_RECOMMEND = re.compile(r"\b(?:should(?:\s+not)?|may)\b", re.IGNORECASE)',
        "may_is_still_not_recorded",
    ),
    _m(
        8,
        "a recommendation of a standard the sheet does not name takes part in the review",
        APP / "comparison.py",
        "if recommendations.left_out(r, standard_id, design_standards, held_back):",
        "if False:",
        "does_not_name",
    ),
    _m(
        9,
        "a recommendation left out of the review is not counted",
        APP / "recommendations.py",
        "    held_back[TYPE] = held_back.get(TYPE, 0) + 1\n",
        "",
        "does_not_name",
    ),
    _m(
        10,
        "the verification queue holds the recommendations",
        APP / "standards.py",
        "NOT IN ('definition', 'recommendation')\"\n        \" AND (r.confidence IS NULL OR r.confidence < ?\"",
        'NOT IN (\'definition\')"\n        " AND (r.confidence IS NULL OR r.confidence < ?"',
        "verification_queue",
    ),
    _m(
        11,
        "the library's requirement count includes the recommendations",
        APP / "standards.py",
        "NOT IN ('definition', 'recommendation')\"\n        \"       ) AS requirement_count,\"",
        'NOT IN (\'definition\')"\n        "       ) AS requirement_count,"',
        "verification_queue",
    ),
    _m(
        12,
        "the library's 'awaiting verification' count includes the recommendations",
        APP / "standards.py",
        "NOT IN ('definition', 'recommendation')\"\n        \"           AND (r.confidence IS NULL OR r.confidence < ?\"",
        'NOT IN (\'definition\')"\n        "           AND (r.confidence IS NULL OR r.confidence < ?"',
        "verification_queue",
    ),
    _m(
        13,
        "a recommendation that applies is not held as a query, so it vanishes",
        APP / "comparison.py",
        "    requirements = recommendations.hold_for_query(requirements, held_items)",
        "    requirements = [r for r in requirements if not recommendations.is_advice(r)]",
        "is_raised_as_a_query",
    ),
    _m(
        14,
        "the switch is ignored: every referenced standard raises its recommendations",
        APP / "recommendations.py",
        "    if not settings.recommendation_queries_enabled:\n        return set()\n",
        "",
        "switch_off",
    ),
    _m(
        15,
        "a recommendation query is grouped with the held rows, so 128 queries become one line",
        APP / "held_findings.py",
        'if len(group) > GROUP_ABOVE and kind != "recommendation":',
        "if len(group) > GROUP_ABOVE:",
        "its_own_query",
    ),
    _m(
        16,
        "a recommendation query carries the plain 'held' wording instead of the query",
        APP / "held_findings.py",
        'if kind == "recommendation":  # a query, never the "held" wording',
        "if False:",
        "is_raised_as_a_query",
    ),
)
