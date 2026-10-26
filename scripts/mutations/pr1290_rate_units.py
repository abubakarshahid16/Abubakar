"""PR 1290: a mass or volume flow converts across its time part (kg/s, t/h, l/min, m3/s);
a rate whose unit is not exact stays unconverted."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1290_rate_units.py"
_R = APP / "rate_units.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1290-01",
        phase=1290,
        description="the flow rows are not in the unit table: kg/s against kg/h is 'not the same quantity' again",
        path=APP / "claims.py",
        anchor="    **rate_units.TABLE,",
        replacement="    **{},  # rate_units.TABLE",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1290-02",
        phase=1290,
        description="a minute counts as one hour: 60 l/min is read as 60 times too large a flow",
        path=_R,
        anchor='    "min": Fraction(60),\n',
        replacement='    "min": Fraction(1),\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1290-03",
        phase=1290,
        description="a second counts as a minute: 1 kg/s is read as 60 kg/h, a limit met by 60 times too little",
        path=_R,
        anchor='    "s": Fraction(3600),\n',
        replacement='    "s": Fraction(60),\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1290-04",
        phase=1290,
        description="a normal cubic metre is read as a cubic metre: Nm3/h compares with m3/h",
        path=_R,
        anchor='    "m3": Fraction(1),\n',
        replacement='    "m3": Fraction(1),\n    "nm3": Fraction(1),\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1290-05",
        phase=1290,
        description="a month is given a made-up number of hours: kg/month is converted",
        path=_R,
        anchor='    "day": Fraction(1, 24),\n',
        replacement='    "day": Fraction(1, 24),\n    "month": Fraction(1, 730),\n',
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1290-06",
        phase=1290,
        description="a pound is rounded to half a kilogram: lb/h converts wrongly",
        path=_R,
        anchor='    "lb": Fraction(45359237, 100000000),\n',
        replacement='    "lb": Fraction(1, 2),\n',
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1290-07",
        phase=1290,
        description="a mass flow is filed under the volume flow dimension: kg/s compares with m3/h",
        path=_R,
        anchor='        ("mass_flow", "kg/h", _MASS),\n',
        replacement='        ("volumetric_flow", "kg/h", _MASS),\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
)
