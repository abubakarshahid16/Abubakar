"""Order 258.1: pump wording a standard's sentence uses meets the caption a pump datasheet prints.

On the owner's M-03 run, 27 of 28 unpaired numeric limits of the pump standard named a quantity no
sheet field name appeared in (s2's count). The fix is DATA, not code: spellings added to
`reference/field_synonyms.json`, applied on both sides before the whole-word containment test.
Invented sentences and captions only; each pairing says it rests on the table (`synonym`)."""

from __future__ import annotations

import pytest

from app import comparison, field_links

#: (the sentence's words, the sheet's caption, the unit both state)
PAIRS = [
    ("the pump speed shall not exceed", "Rated speed", "rpm"),
    ("the rotating speed shall be at most", "Speed rated", "rpm"),
    ("the liquid relative density shall be at least", "Specific gravity", "kg/m3"),
    ("the brake horsepower shall not exceed", "Absorbed power", "kW"),
    ("the driver power shall be at least", "Motor rating", "kW"),
    ("the npsha margin shall be at least", "NPSH margin", "m"),
    ("the total differential head shall be at least", "Differential head", "m"),
    ("the rated capacity shall be at least", "Rated flow", "m3/h"),
]


def requirement(subject, unit):
    return {
        "requirement_type": "numeric_limit",
        "value": 3.5,
        "unit": unit,
        "raw_value": "3.5",
        "raw_unit": unit,
        "subject": subject,
    }


def fact(caption, unit):
    return {
        "id": f"fact-{caption}",
        "field_name": caption,
        "raw_value": "2.2",
        "raw_unit": unit,
        "unit": unit,
    }


@pytest.mark.parametrize(("sentence", "caption", "unit"), PAIRS)
def test_the_pump_wording_pairs_with_the_sheets_caption_through_the_table(
    sentence, caption, unit
):
    result = comparison.match_by_containment(
        requirement(sentence, unit), [fact(caption, unit)]
    )
    assert result["fact"] is not None, (sentence, caption, result.get("reason"))
    assert result["fact"]["field_name"] == caption


@pytest.mark.parametrize(("sentence", "caption", "unit"), PAIRS)
def test_without_the_added_spellings_the_same_pair_did_not_meet(
    sentence, caption, unit, monkeypatch
):
    """The data change is what pairs them: with an empty table the pair is not made."""
    monkeypatch.setattr(field_links, "_table", lambda *a, **k: (None, {}, frozenset()))
    result = comparison.match_by_containment(
        requirement(sentence, unit), [fact(caption, unit)]
    )
    assert result["fact"] is None or caption.lower() in sentence.lower()


def test_a_different_quantity_with_a_shared_word_is_not_paired():
    """'wind speed' is not the pump's speed; 'speed' alone was never a synonym."""
    result = comparison.match_by_containment(
        requirement("the wind speed shall not exceed", "rpm"),
        [fact("Rated speed", "rpm")],
    )
    assert result["fact"] is None


def test_absorbed_power_and_driver_rating_stay_two_quantities():
    absorbed = comparison.match_by_containment(
        requirement("the absorbed power shall not exceed", "kW"),
        [fact("Motor rating", "kW")],
    )
    driver = comparison.match_by_containment(
        requirement("the driver rating shall be at least", "kW"),
        [fact("Absorbed power", "kW")],
    )
    assert absorbed["fact"] is None and driver["fact"] is None


def test_the_spellings_are_written_once_in_the_data_file():
    canon = field_links.canonical
    assert canon("pump speed") == canon("rated speed")
    assert canon("relative density") == canon("specific gravity")
    assert canon("npsha margin") == "npsh margin" != canon("npsha")


def test_operating_speed_and_shaft_power_are_not_synonyms_of_the_rated_quantities():
    """Reviewers (s1, cloud-2): an operating speed is not the rated speed, and a shaft power may be a
    driver's: both stay apart until a real sheet shows otherwise."""
    canon = field_links.canonical
    assert canon("operating speed") != canon("rated speed")
    assert canon("shaft power") != canon("absorbed power")
