"""Update 13's method part (planner, 26 Nov 2026): the always-on items G2 (values that must agree) and G3 (required entries left blank)
read the app's OWN data, the consistency pairs and the type's mandatory entries, only with AIM_U13_ENABLED on. Off: exactly as before.
No paper words; invented types only where a real key is not needed."""

from __future__ import annotations

from app.aim_review import always
from app.config import settings


def test_off_the_always_on_items_read_nothing_new(monkeypatch):
    monkeypatch.setattr(settings, "aim_u13_enabled", False)
    assert always.form_context({"equipment_type": "centrifugal_pump"}) == ("", "")


def test_on_g2_gets_the_apps_consistency_pairs_and_g3_the_types_required_entries(
    monkeypatch,
):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    pairs, entries = always.form_context({"equipment_type": "pressure_vessel"})
    assert pairs.startswith("PAIRS THAT MUST AGREE") and pairs.count("\n- ") >= 3
    assert entries.startswith("THE FORM OF THIS KIND OF PAPER requires these entries: ")
    assert "test pressure" in entries and "corrosion allowance" in entries


def test_a_review_key_reaches_its_form_through_the_taxonomy_and_an_unknown_type_gets_no_entries(
    monkeypatch,
):
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    assert (
        "rated flow" in always.form_context({"equipment_type": "centrifugal_pump"})[1]
    )
    assert always.form_context({"equipment_type": "invented_thing"})[1] == ""
    assert always.form_context({})[1] == ""
