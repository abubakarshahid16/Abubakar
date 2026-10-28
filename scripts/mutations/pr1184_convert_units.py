"""Order 141 B: two units of one quantity are converted, then compared
(`claims.compare_across_units`, `comparison.compare`, the run's unit guard).
Danger zone: a wrong conversion reaches an engineer as a pass or a finding.
Placeholder ids M1184-NN, phase 141: the lead renames them to the PR number."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_141b_convert_units.py"
_CL = APP / "claims.py"
_CO = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1184-01",
        phase=1184,
        description="a temperature is read only as a temperature, never as a difference (a rise)",
        path=_CL,
        anchor='        ("as temperature differences", rise, rise, lim * scale_l[0]),\n',
        replacement="",
        target=_T,
        keyword="rise_in_kelvin",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-02",
        phase=1184,
        description="gauge against absolute is decided at the standard atmosphere alone",
        path=_CL,
        anchor="    low, high = (o, o + standard) if gauge_is_observed else (o - standard, o)\n",
        replacement=(
            "    low, high = (o + standard, o + standard) if gauge_is_observed"
            " else (o - standard, o - standard)\n"
        ),
        target=_T,
        keyword="atmosphere_decides",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-03",
        phase=1184,
        description="a value that is the limit printed in another unit gets a verdict",
        path=_CL,
        anchor="    if abs(point - lim) <= tolerance * (1 + 1e-9) and at_limit != answer:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="at_the_limit_goes or near_its_limit or inches",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-04",
        phase=1184,
        description="the review stops converting two units of one quantity",
        path=_CO,
        anchor="    crossed = claims.compare_across_units(observed, limit)\n",
        replacement="    crossed = None\n",
        target=_T,
        keyword="fahrenheit_limit or celsius_limit or absolute_limit_and_a_gauge",
        tags=("units",),
    ),
    Mutation(
        id="M1184-05",
        phase=1184,
        description="the run's unit guard calls °F and °C 'not the same quantity' again",
        path=_CO,
        anchor=(
            "            claims.is_temperature_scale(requirement_unit.raw_unit)\n"
            "            and claims.is_temperature_scale(fact_unit.raw_unit)\n"
        ),
        replacement="            False\n",
        target=_T,
        keyword="lets_two_temperature_scales_through",
        tags=("units", "honesty"),
    ),
    Mutation(
        id="M1184-06",
        phase=1184,
        description="a converted breach is reported compliant",
        path=_CL,
        anchor="    return CrossUnit(answer, note=note)\n",
        replacement="    return CrossUnit(True, note=note)\n",
        target=_T,
        keyword="fahrenheit_limit or celsius_limit or psi_bar_and_kpa",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-07",
        phase=1184,
        description="Fahrenheit is converted without its offset in the review",
        path=_CL,
        anchor='"f": (1 / 1.8, 459.67 / 1.8),',
        replacement='"f": (1 / 1.8, 0.0),',
        target=_T,
        keyword="fahrenheit_limit",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-08",
        phase=1184,
        description="temperature and temperature-difference readings that disagree get a verdict",
        path=_CL,
        anchor="    if None in answers or len(set(answers)) > 1:\n",
        replacement="    if None in answers:\n",
        target=_T,
        keyword="readings_that_disagree or rise_in_kelvin",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-09",
        phase=1184,
        description="an absolute pressure is converted against a limit that states no reference",
        path=_CL,
        anchor='        or references == {"absolute", None}\n    ):\n',
        replacement="    ):\n",
        target=_T,
        keyword="no_reference_is_still_not_compared",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-10",
        phase=1184,
        description="a range of values is tested at its low end only, missing a limit between",
        path=_CL,
        anchor=(
            "    if not below_hi(low) or not above_lo(high):\n"
            "        return False\n"
            "    return None\n"
        ),
        replacement="    return _compatible(_bare(observed, low), limit)\n",
        target=_T,
        keyword="atmosphere_decides",
        tags=("units", "critical"),
    ),
    Mutation(
        id="M1184-11",
        phase=1184,
        description="a whole number is held as +-half a unit (the coarser printing, not the finer)",
        path=_CL,
        anchor="    tolerance = min(half_o * factor_o, half_l * factor_l)\n",
        replacement="    tolerance = max(half_o * factor_o, half_l * factor_l)\n",
        target=_T,
        keyword="whole_numbers",
        tags=("units",),
    ),
    Mutation(
        id="M1184-12",
        phase=1184,
        description="a temperature clear of the limit by more than the finer printing is held",
        path=_CL,
        anchor="        tolerance = min(half_o * scale_o[0], half_l * scale_l[0])\n",
        replacement="        tolerance = max(half_o * scale_o[0], half_l * scale_l[0])\n",
        target=_T,
        keyword="clear_of_the_limit",
        tags=("units",),
    ),
)
