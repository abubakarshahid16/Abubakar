"""#1475 finding: a value exactly AT a percent / factor limit can read just under
it in some units (float rounding) and get a wrong Fail. Invented values only.

Live rules that carry the arithmetic: PSV-S03 (above the operating pressure by
the greater of 10 % or 100 kPa), PSV-S04 (set pressure at most 110 % of the
MAWP), PSV-27 / PSV-28 (overpressure as a percentage of the set pressure),
PSV-29 (back pressure stated as a percentage).
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app.config import settings
from tests.test_746_relief_valve_checklist import fact, results

# (unit, rule, the base value) - every one of these is EXACTLY at the limit and
# fails today with the switch off (found by sweeping each unit).
AT_LIMIT = [
    ("kPag", "PSV-S04", 37),
    ("barg", "PSV-S04", 0.7),
    ("MPag", "PSV-S04", 0.565),
    ("psig", "PSV-S04", 293),
    ("kPag", "PSV-S03", 1001),
    ("barg", "PSV-S03", 10.4),
    ("MPag", "PSV-S03", 1.018),
    ("psig", "PSV-S03", 202),
]


def sheet(rule, unit, base, set_value):
    if rule == "PSV-S04":
        return [
            fact("set pressure", str(set_value), unit),
            fact("max allow working pressure", str(base), unit),
            fact("relief case", "Thermal"),
        ]
    return [
        fact("set pressure", str(set_value), unit),
        fact("operating pressure", str(base), unit),
    ]


@pytest.mark.parametrize("unit,rule,base", AT_LIMIT)
def test_today_a_value_at_the_limit_fails_wrongly(monkeypatch, unit, rule, base):
    monkeypatch.setattr(settings, "at_limit_precision_enabled", False)
    r = results(sheet(rule, unit, base, round(base * 1.1, 6)))[rule]
    assert (
        r["status"] == "NON_COMPLIANT"
    )  # the bug, pinned: the switch off keeps today's answer


@pytest.mark.parametrize("unit,rule,base", AT_LIMIT)
def test_switch_on_a_value_at_the_limit_complies_and_just_under_fails(
    monkeypatch, unit, rule, base
):
    monkeypatch.setattr(settings, "at_limit_precision_enabled", True)
    at = round(base * 1.1, 6)
    assert results(sheet(rule, unit, base, at))[rule]["status"] == "COMPLIANT"
    if rule == "PSV-S04":  # at most: just OVER is the failing side
        assert (
            results(sheet(rule, unit, base, round(base * 1.1001, 6)))[rule]["status"]
            == "NON_COMPLIANT"
        )
    else:  # at least: just UNDER is the failing side
        assert (
            results(sheet(rule, unit, base, round(base * 1.0999, 6)))[rule]["status"]
            == "NON_COMPLIANT"
        )


def test_the_overpressure_and_back_pressure_percent_rules_at_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "at_limit_precision_enabled", True)
    base = [
        fact("set pressure", "7", "barg"),
        fact("relief case", "Fire"),
        fact("valve type", "Conventional"),
    ]
    # 1.47 barg over a 7 barg set pressure is exactly 21 % (float: 21.000000000000004 or 20.99999...)
    r = results([*base, *[fact("over pressure", "1.47", "barg")]])["PSV-27"]
    assert r["status"] == "COMPLIANT"
    r = results([*base, *[fact("over pressure", "1.48", "barg")]])["PSV-27"]
    assert r["status"] == "NON_COMPLIANT"
    assert (
        results([*base, *[fact("built up back pressure", "10", "%")]])["PSV-29"][
            "status"
        ]
        == "COMPLIANT"
    )
    assert (
        results([*base, *[fact("built up back pressure", "10.01", "%")]])["PSV-29"][
            "status"
        ]
        == "NON_COMPLIANT"
    )


@pytest.mark.parametrize(
    "op,expected", [(">=", True), ("<=", True), (">", False), ("<", False)]
)
def test_hold_at_the_limit_follows_the_operator(monkeypatch, op, expected):
    monkeypatch.setattr(settings, "at_limit_precision_enabled", True)
    assert dc._hold(op, 1155.0000000000002, 1155.0, dc._OPS) is expected
    assert dc._hold(op, 1154.9999999999998, 1155.0, dc._OPS) is expected


def test_hold_never_widens_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "at_limit_precision_enabled", True)
    assert dc._hold("<=", 1155.01, 1155.0, dc._OPS) is False  # one printed digit over is over
    assert dc._hold(">=", 1154.99, 1155.0, dc._OPS) is False
    monkeypatch.setattr(settings, "at_limit_precision_enabled", False)
    assert (
        dc._hold(">=", 1154.9999999999998, 1155.0, dc._OPS) is False
    )  # off: today's plain comparison


def test_a_percent_print_never_passes_as_a_bare_number(monkeypatch):
    """What a live card does with a bare "70" vs "0.70" vs "70 %": a bare number
    with no percent sign or label never reaches the percentage compare."""
    monkeypatch.setattr(settings, "at_limit_precision_enabled", True)
    base = [fact("set pressure", "10", "barg"), fact("valve type", "Conventional")]
    for printed in ("70", "0.70"):
        r = results([*base, *[fact("built up back pressure", printed)]])["PSV-29"]
        assert r["status"] == "NEEDS_ENGINEER_REVIEW"
    r = results([*base, *[fact("built up back pressure", "70", "%")]])["PSV-29"]
    assert r["status"] == "NON_COMPLIANT"  # 70 % > 10 %


@pytest.mark.parametrize("on,status", [(False, "NON_COMPLIANT"), (True, "COMPLIANT")])
def test_the_pair_consistency_rules_use_the_same_comparison(monkeypatch, on, status):
    """DS-C1 (design pressure at least the operating pressure): two figures that are the
    same pressure to float noise are equal."""
    from tests.test_datasheet_checks import full_vessel
    from tests.test_datasheet_checks import run as run_checks

    monkeypatch.setattr(settings, "at_limit_precision_enabled", on)
    real = dc._number
    noise = {"design pressure": 1154.9999999999998, "operating pressure": 1155.0}

    def fake(f):
        got = real(f)
        if got is not None and f.get("field_name") in noise:
            return (noise[f["field_name"]], got[1], got[2])
        return got

    monkeypatch.setattr(dc, "_number", fake)
    assert run_checks(full_vessel())["DS-C1"]["status"] == status


@pytest.mark.parametrize("on", [False, True])
def test_a_slipped_operator_is_still_seen_at_the_limit(monkeypatch, on):
    """The operator table is looked up at call time, switch on or off, so a boundary
    slip in it ("at most" made "below") is not hidden by the at-limit equality."""
    monkeypatch.setattr(settings, "at_limit_precision_enabled", on)
    ops = dict(dc._OPS)
    ops["<="] = ops["<"]
    monkeypatch.setattr(dc, "_OPS", ops)
    assert dc._hold("<=", 5.0, 5.0, dc._OPS) is False
