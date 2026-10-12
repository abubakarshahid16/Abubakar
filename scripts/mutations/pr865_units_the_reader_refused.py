"""PR #865 (#830, R27): the units the AI reader's readings were refused for
on two real sheets - centipoise and standard cubic feet per hour. The unit
code in `claims.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_830_units_the_reader_refused.py"
_C = APP / "claims.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M865-01", phase=865,
             description="centipoise and SCFH are not units: a correctly read value is thrown away over its unit",
             path=_C,
             anchor='    "cp": "viscosity", "scfh": None,\n',
             replacement="",
             target=_T, keyword="units_now or beside_the_number or same_spelling or accepted_and_the_others",
             tags=("honesty",)),
    Mutation(id="M865-02", phase=865,
             description="a viscosity carries no dimension, so it would compare with any other unit-less quantity",
             path=_C,
             anchor='    "cp": "viscosity", "scfh": None,\n',
             replacement='    "cp": None, "scfh": None,\n',
             target=_T, keyword="units_now", tags=("honesty", "critical")),
)
