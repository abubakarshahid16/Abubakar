"""#1512: a fraction printed under a % label is never decided on a percent card."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1512_percent_kind.py"
_M = APP / "datasheet_checks.py"
_P = APP / "percent_kind.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1514-01",
        phase=1514,
        description="the percent-kind check ignores its switch (always on)",
        path=_P,
        anchor="    if not (settings.percent_kind_check_enabled and is_percent):\n",
        replacement="    if not is_percent:\n",
        target=_T,
        keyword="today_a_fraction_under_a_percent_label",
        tags=_TAGS,
    ),
    Mutation(
        id="M1514-02",
        phase=1514,
        description="a number of exactly 1 under a % label is decided again",
        path=_P,
        anchor="    if number is None or not 0 < abs(number) <= 1:\n",
        replacement="    if number is None or not 0 < abs(number) < 1:\n",
        target=_T,
        keyword="switch_on_a_fraction_sized_percent",
        tags=_TAGS,
    ),
    Mutation(
        id="M1514-03",
        phase=1514,
        description="a non-percent rule is also held for a fraction-sized number",
        path=_P,
        anchor="    if rule is not None and not (\n",
        replacement="    if False and not (\n",
        target=_T,
        keyword="helper_is_silent",
        tags=_TAGS,
    ),
    Mutation(
        id="M1514-04",
        phase=1514,
        description="the verdict path never asks the percent-kind check",
        path=_M,
        anchor="    if (doubt := _kind_doubt(fact, rule, _is_percent(fact))) is not None:  # #1512\n",
        replacement="    if False:  # #1512\n",
        target=_T,
        keyword="switch_on_a_fraction_sized_percent",
        tags=_TAGS,
    ),
    Mutation(
        id="M1514-05",
        phase=1514,
        description="the area calculation uses a fraction-sized percent again",
        path=_M,
        anchor="        if (doubt := _kind_doubt(fact)) is not None:  # #1512\n",
        replacement="        if False:  # #1512\n",
        target=_T,
        keyword="area_calculation_does_not_use",
        tags=_TAGS,
    ),
    Mutation(
        id="M1514-06",
        phase=1514,
        description="a plain number with no % label is held as a fraction too",
        path=_P,
        anchor='    number = claims.parse_value(str(fact.get("raw_value")))\n',
        replacement="    number = 0.5\n",
        target=_T,
        keyword="unambiguous_values_decide_the_same",
        tags=_TAGS,
    ),
)
