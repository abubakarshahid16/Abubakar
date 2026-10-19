"""Order 141 B: two units of one quantity are converted, then compared
(`claims.compare_across_units`, `comparison.compare`, the run's unit guard).
Danger zone: a wrong conversion reaches an engineer as a pass or a finding.
Placeholder ids M141B-NN, phase 141: the lead renames them to the PR number."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_141b_convert_units.py"
_CL = APP / "claims.py"
_CO = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M141B-01", phase=141,
             description="a temperature is read only as a temperature, never as a difference (a rise)",
             path=_CL,
             anchor='                    ("as temperature differences", obs * scale_o[0], lim * scale_l[0])]\n',
             replacement="                    ]\n",
             target=_T, keyword="rise_in_kelvin", tags=("units", "critical")),
    Mutation(id="M141B-02", phase=141,
             description="gauge against absolute is decided at the standard atmosphere alone",
             path=_CL,
             anchor='                                  ("with a lower atmospheric pressure (a site above sea level)", 0.0)):\n',
             replacement="                                  ):\n",
             target=_T, keyword="atmosphere_decides", tags=("units", "critical")),
    Mutation(id="M141B-03", phase=141,
             description="a converted value within its printed precision of the limit gets a verdict",
             path=_CL,
             anchor="             for _label, o, lim in readings for shift in (-step, step)\n",
             replacement="             for _label, o, lim in readings for shift in ()\n",
             target=_T, keyword="at_the_limit_goes or near_its_limit or inches", tags=("units", "critical")),
    Mutation(id="M141B-04", phase=141,
             description="the review stops converting two units of one quantity",
             path=_CO,
             anchor="    crossed = claims.compare_across_units(observed, limit)\n",
             replacement="    crossed = None\n",
             target=_T, keyword="fahrenheit_limit or celsius_limit or absolute_limit_and_a_gauge",
             tags=("units",)),
    Mutation(id="M141B-05", phase=141,
             description="the run's unit guard calls °F and °C 'not the same quantity' again",
             path=_CO,
             anchor=("        claims.is_temperature_scale(requirement_unit.raw_unit)\n"
                     "        and claims.is_temperature_scale(fact_unit.raw_unit))"),
             replacement="        False)",
             target=_T, keyword="lets_two_temperature_scales_through", tags=("units", "honesty")),
    Mutation(id="M141B-06", phase=141,
             description="a converted breach is reported compliant",
             path=_CL, anchor="    return CrossUnit(centre[0], note=note)\n",
             replacement="    return CrossUnit(True, note=note)\n",
             target=_T, keyword="fahrenheit_limit or celsius_limit or psi_bar_and_kpa",
             tags=("units", "critical")),
    Mutation(id="M141B-07", phase=141,
             description="Fahrenheit is converted without its offset in the review",
             path=_CL, anchor='"f": (1 / 1.8, 459.67 / 1.8),',
             replacement='"f": (1 / 1.8, 0.0),',
             target=_T, keyword="fahrenheit_limit", tags=("units", "critical")),
    Mutation(id="M141B-08", phase=141,
             description="readings that disagree are not named as the reason",
             path=_CL, anchor="    if len(set(centre)) > 1:\n",
             replacement="    if False:\n",
             target=_T, keyword="readings_that_disagree or rise_in_kelvin", tags=("units", "honesty")),
    Mutation(id="M141B-09", phase=141,
             description="an absolute pressure is converted against a limit that states no reference",
             path=_CL,
             anchor=('    if fold_o == fold_l or (entry_o is not None and entry_o == entry_l)'
                     ' or references == {"absolute", None}:\n'),
             replacement="    if fold_o == fold_l or (entry_o is not None and entry_o == entry_l):\n",
             target=_T, keyword="no_reference_is_still_not_compared", tags=("units", "critical")),
    Mutation(id="M141B-10", phase=141,
             description="a value exactly at the limit after an exact conversion goes to an engineer",
             path=_CL,
             anchor="             if not math.isclose(o, lim, rel_tol=1e-9, abs_tol=1e-12)}\n",
             replacement="             }\n",
             target=_T, keyword="exactly_at_the_limit", tags=("units",)),
)
