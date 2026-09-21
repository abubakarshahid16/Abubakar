"""Two different physical dimensions are NO comparison, never a failed one.

`1.6 mm` and `60 degC` both normalise. Comparing their numbers returned False,
and `comparison.compare` rendered that as NON_COMPLIANT with the rationale "the
submitted value 60 degC is outside the required >= 1.6 mm". A length is not
outside a temperature limit - there is no limit for it to be outside of.

The guard lives in `claims._compatible`, which is the one boundary every
comparison crosses. `match_rules.refusal` also refuses these pairings, earlier
and for its own reasons, but it is a separate module and a caller reaching
`comparison.compare` directly never consults it. Hence
`test_compare_is_safe_without_the_upstream_matcher` below: the safety property
must hold at the boundary, not only on the pipeline's happy path.

MUTATION-PROVEN. Deleting the two-line dimension guard makes
`test_incompatible_dimensions_abstain` and
`test_compare_is_safe_without_the_upstream_matcher` fail. The harness that
proves it, and its verbatim output, are recorded in
`CURRENT_STATE_AND_BLOCKERS.md` section 14.

Nothing here claims engineering accuracy. It asserts that the engine declines to
compare quantities it cannot compare.
"""

from __future__ import annotations

import pytest

from app import claims, comparison

# ------------------------------------------------------------------ helpers

def m(value: str, unit: str) -> claims.Measurement:
    return claims.normalise(value, unit)


def requirement(raw_value="1.6", raw_unit="mm", **over) -> dict:
    base = {
        "id": "req-dimension-guard",
        "clause": "7.1.2.1",
        "page": 48,
        "subject": "minimum C.A",
        "operator": ">=",
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "requirement_text": "a minimum C.A. of at least 1.6 mm shall be used",
        "source_text": "a minimum C.A. of at least 1.6 mm shall be used",
        "requirement_type": "numeric_limit",
    }
    base.update(over)
    return base


def fact(raw_value="0", raw_unit="mm", **over) -> dict:
    base = {
        "id": "fact-dimension-guard",
        "field_name": "design corrosion allowance for welded internal parts",
        "field_value": f"{raw_value} {raw_unit}".strip(),
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "page": 4,
        "is_blank": False,
        "blank_marker": None,
    }
    base.update(over)
    return base


DECIDED = {comparison.COMPLIANT, comparison.NON_COMPLIANT}


# ----------------------------------------------- 1. incompatible dimensions

@pytest.mark.parametrize("v1,u1,v2,u2,what", [
    ("1.6", "mm",  "60", "degC", "length vs temperature"),
    ("10",  "bar", "60", "degC", "pressure vs temperature"),
    ("1.6", "mm",  "10", "bar",  "length vs pressure"),
    ("25",  "h",   "1.6", "mm",  "time vs length"),
])
def test_incompatible_dimensions_abstain(v1, u1, v2, u2, what):
    """MUTATION TARGET. None means undecidable; False would mean "not within"."""
    got = claims._compatible(m(v1, u1), m(v2, u2))
    assert got is None, f"{what}: expected None (undecidable), got {got!r}"


def test_a_dimension_mismatch_is_not_reported_as_a_conflict_either():
    """False is what the claim-conflict detector reads as a real disagreement.

    Two measurements in different dimensions do not disagree; they are about
    different things. `is False` must not be reachable for them.
    """
    assert claims._compatible(m("1.6", "mm"), m("60", "degC")) is not False


# ---------------------------------------------------- 2. unknown units

@pytest.mark.parametrize("v1,u1,v2,u2,what", [
    ("60", "kg",       "1.6", "mm", "mass, absent from the unit table"),
    ("60", "zorkmids", "1.6", "mm", "a unit that does not exist"),
    ("60", "",         "1.6", "mm", "missing unit on one side"),
    ("60", "",         "1.6", "",   "missing unit on both sides"),
])
def test_unknown_or_missing_units_abstain(v1, u1, v2, u2, what):
    got = claims._compatible(m(v1, u1), m(v2, u2))
    assert got is None, f"{what}: expected None, got {got!r}"


# ------------------------------------------- 3. valid conversions still work

@pytest.mark.parametrize("v1,u1,v2,u2,expected,what", [
    ("10",   "bar", "1000",   "kPa", True,  "10 bar == 1000 kPa"),
    ("10",   "bar", "2000",   "kPa", False, "10 bar != 2000 kPa"),
    ("1.6",  "mm",  "0.0016", "m",   True,  "1.6 mm == 0.0016 m"),
    ("1.6",  "mm",  "0.1",    "m",   False, "1.6 mm != 0.1 m"),
    ("60",   "C",   "60",     "C",   True,  "same unit, same value"),
    ("95",   "dB(A)", "90",   "dB(A)", False, "dB(A) has no dimension; the "
                                              "same-unit path must survive"),
])
def test_compatible_units_still_compare(v1, u1, v2, u2, expected, what):
    """The guard must not turn working conversions into abstentions."""
    got = claims._compatible(m(v1, u1), m(v2, u2))
    assert got is expected, f"{what}: expected {expected}, got {got!r}"


def test_celsius_against_fahrenheit_abstains_and_that_is_deliberate():
    """NOT changed by the dimension guard, and NOT a regression.

    Both are `temperature`, so the guard does not fire. `degF` is absent from
    `_UNIT_TABLE` on purpose - the table's own comment says "a wrong temperature
    conversion is a safety defect, so F must raise / give None" - so it carries
    a dimension but no convertible value and the comparison is undecidable.

    Asserted here so that if anyone ever adds an F conversion, this test states
    what the current contract was and forces the decision to be explicit.
    """
    assert m("140", "degF").dimension == "temperature"
    assert m("140", "degF").normalized_value is None
    assert claims._compatible(m("60", "degC"), m("140", "degF")) is None


# -------------------------- 5. compare() safe without the upstream matcher

def test_compare_is_safe_without_the_upstream_matcher():
    """MUTATION TARGET. `comparison.compare` called directly, as any caller may.

    `match_rules.refusal` is NOT consulted here, deliberately: this asserts the
    boundary itself is safe, not that the pipeline happens to guard it.
    """
    out = comparison.compare(requirement("1.6", "mm"), fact("60", "degC"))
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW, (
        f"expected abstention, got {out['status']}: {out['rationale']}")
    assert out["status"] not in DECIDED
    assert "cannot be compared" in out["rationale"]
    assert "no conversion is guessed" in out["rationale"]


@pytest.mark.parametrize("ru,fu,what", [
    ("mm",  "degC", "length limit vs temperature value"),
    ("bar", "degC", "pressure limit vs temperature value"),
    ("mm",  "kg",   "length limit vs an unknown unit"),
    ("mm",  "",     "length limit vs a value with no unit"),
])
def test_compare_never_returns_a_verdict_across_dimensions(ru, fu, what):
    out = comparison.compare(requirement("1.6", ru), fact("60", fu))
    assert out["status"] not in DECIDED, f"{what} produced {out['status']}"
    assert out["rationale"], f"{what} abstained without saying why"


def test_compare_still_decides_when_the_units_do_match():
    """The control. Without this, every test above could pass by abstaining
    always, which is the vacuous-test failure mode this project has shipped
    before."""
    breach = comparison.compare(requirement("1.6", "mm"), fact("0", "mm"))
    assert breach["status"] == comparison.NON_COMPLIANT

    passing = comparison.compare(requirement("1.6", "mm"), fact("3", "mm"))
    assert passing["status"] == comparison.COMPLIANT

    converted = comparison.compare(requirement("1.6", "mm"), fact("0.003", "m"))
    assert converted["status"] == comparison.COMPLIANT, (
        "3 mm expressed as 0.003 m must still convert and compare")
