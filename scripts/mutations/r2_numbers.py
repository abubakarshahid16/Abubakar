"""Mutations for the round-2 number-reading fixes (M1990-M1999): signs, space
groups, ambiguous EU decimals, compound units, tolerant field names, the
figure checker's unit/sign/polarity layer and cluster labels.
Files: backend/app/claims.py, comparison.py, answer.py. Targets:
tests/test_r2_numbers_*.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_P = "tests/test_r2_numbers_parse.py"
_F = "tests/test_r2_numbers_figures.py"
_C = "tests/test_r2_numbers_clusters.py"
_TAG = ("r2_numbers",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1990", phase=1990,
             description="U+2212 is no longer normalised to a minus, so a negative value reads positive",
             path=APP / "claims.py",
             anchor='    s = (value_str or "").strip().replace(_MINUS_SIGN, "-")',
             replacement='    s = (value_str or "").strip()',
             target=_P, keyword="unicode_minus or the_minus_survives", tags=_TAG),
    Mutation(id="M1991", phase=1991,
             description="an en/em dash glued to its digits is no longer read as a minus",
             path=APP / "claims.py",
             anchor="            negative_dash = True",
             replacement="            negative_dash = False",
             target=_P, keyword="dash_directly", tags=_TAG),
    Mutation(id="M1992", phase=1992,
             description="whitespace-separated digit groups are joined again without the strict thousands form",
             path=APP / "claims.py",
             anchor='        if not _SPACE_GROUPED.fullmatch(num.lstrip("+-")):',
             replacement='        if False and not _SPACE_GROUPED.fullmatch(num.lstrip("+-")):',
             target=_P, keyword="digit_groups", tags=_TAG),
    Mutation(id="M1993", phase=1993,
             description="d.ddd (three decimals) is read as a decimal again instead of being ambiguous",
             path=APP / "claims.py",
             anchor='    elif re.fullmatch(r"[1-9]\\d{0,2}\\.\\d{3}", num):',
             replacement='    elif re.fullmatch(r"[1-9]\\d{0,2}\\.\\d{3}x", num):',
             target=_P, keyword="three_decimals or ambiguous_fact", tags=_TAG),
    Mutation(id="M1994", phase=1994,
             description="abbreviation / generic-word tolerance in field-name matching is removed",
             path=APP / "comparison.py",
             anchor="        elif (_contains_words(subject_form, _match_form(name))",
             replacement="        elif (False and _contains_words(subject_form, _match_form(name))",
             target=_P, keyword="abbreviation_and_generic", tags=_TAG),
    Mutation(id="M1995", phase=1995,
             description="a compound unit is cut at the slash again",
             path=APP / "claims.py",
             anchor='    r"(?:\\([A-Za-z]\\)|/[A-Za-zµμ][A-Za-z]*(?:[0-9²³](?![0-9]))?)?)"',
             replacement='    r"(?:\\([A-Za-z]\\))?)"',
             target=_P, keyword="compound_units or speed_is_never or unknown_compound", tags=_TAG),
    Mutation(id="M1996", phase=1996,
             description="the figure checker no longer holds a figure to its unit and sign",
             path=APP / "answer.py",
             anchor="                wrong = figure_conflict(segment, claimed, page_text)",
             replacement="                wrong = None",
             target=_F, keyword="unit or minus or dual_unit or hyphenated or rounding", tags=_TAG),
    Mutation(id="M1997", phase=1997,
             description="a sentence may contradict the polarity of the quote it cites",
             path=APP / "answer.py",
             anchor="            if polarity_conflict(plain, quoted_text) is not None:",
             replacement="            if False:",
             target=_F, keyword="shall_exceed or shall_be_used or no_more_than", tags=_TAG),
    Mutation(id="M1998", phase=1998,
             description="two different upper limits are labelled agreement again",
             path=APP / "claims.py",
             anchor="                    if row_a != row_b and _distinct_same_direction_limits(a, b):",
             replacement="                    if False and _distinct_same_direction_limits(a, b):",
             target=_C, keyword="upper_limits or lower_limits", tags=_TAG),
    Mutation(id="M1999", phase=1999,
             description="one dual-unit value printed twice is a conflict again",
             path=APP / "claims.py",
             anchor="                    if _same_printed_quantity(a, b):",
             replacement="                    if False:",
             target=_C, keyword="dual_unit_value_printed_twice", tags=_TAG),
)
