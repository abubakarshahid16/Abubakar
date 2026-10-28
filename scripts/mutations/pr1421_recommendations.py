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
        "if is_definition or not mandatory:    # advice states no limit",
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
        'if _column(row, "requirement_type") in (requirement_quality.DEFINITION, recommendations.TYPE):',
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
        "CROSS_FIELD_LIMIT,\n                           recommendations.TYPE)",
        "CROSS_FIELD_LIMIT)",
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
)
