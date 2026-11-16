"""Order 14, lane A for lane D: the pump datasheet's own words for speed and power find their fields (RPM, nameplate power), the driver's
speed and the hydraulic power are their own fields (never the pump's rated speed or absorbed power), and "Rated power", often the driver's,
is not read as absorbed power: the label search still finds it, so the check asks the engineer instead of calling the field missing."""

from __future__ import annotations

from app import datasheet_checks as dc
from app.datasheets import normalise_field_name

RULES = dc.load_rules()


def role(label):
    return dc.role_of(normalise_field_name(label), RULES)


def test_speed_words():
    assert role("RPM") == role("Rated RPM") == role("Speed (rpm)") == "rated_speed"
    assert role("Nominal RPM") == role("RATED LOAD RPM") == "driver_speed"
    assert (
        role("Specific speed") is None and role("Speed") is None
    )  # a bare "Speed" is usually a type, not the figure


def test_power_words():
    assert role("NAMEPLATE POWER") == role("Motor rated power") == "driver_rating"
    assert role("HYDRAULIC POWER") == "hydraulic_power"
    assert role("Pump power") == "absorbed_power"
    assert (
        role("RATED POWER") is None
    )  # often the driver's: never compared as absorbed power


def test_rated_power_on_the_sheet_is_a_question_not_a_missing_value():
    pages = {1: "PERFORMANCE\nRATED POWER 55 kW\nEFFICIENCY 70 %"}
    assert dc.label_search("absorbed_power", RULES, pages) == [1]
