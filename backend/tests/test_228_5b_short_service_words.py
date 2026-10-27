"""Order 228.5b: a service named in three letters ("wet", "dry", "gas", "oil") is a service.

`clause_support._significant` kept only words of four letters or more, so "applies
only in wet service" named no service: the requirement was not held and was compared
on a sheet that may be of the other service. Now a short word names one too, minus a
short stop list (new, own, our, one, two ...). Invented sentences and sheets only.
"""

from __future__ import annotations

import pytest

from app import clause_support as cs


def _req(text: str) -> dict:
    return {"id": "r", "source_text": text, "requirement_type": "numeric_limit"}


def _fact(label: str, value: str) -> dict:
    return {"field_label": label, "raw_value": value, "is_blank": False}


@pytest.mark.parametrize(
    ("text", "service"),
    [
        ("Valves shall be of steel for wet service.", "wet"),
        ("This applies only in dry service.", "dry"),
        ("Seals for gas service shall be double.", "gas"),
        ("Pumps in oil service shall have a baseplate.", "oil"),
        ("Bearings in hot service shall be cooled.", "hot"),
    ],
)
def test_a_three_letter_service_is_named(text, service):
    assert cs.named_conditions(_req(text)) == [service]


@pytest.mark.parametrize(
    "text",
    [
        "Equipment in new service shall be marked.",
        "It applies to its own service.",
        "For any service the plate shall be fixed.",
        "Parts put into service shall be tested.",
        "Units in our service shall be logged.",
        "Both units in one service shall match.",
        "Put back into use service shall be recorded.",
        "The top service level shall be marked.",
        "At the pre service inspection the seal shall be checked.",
    ],
)
def test_a_short_word_that_names_no_service_still_names_none(text):
    assert cs.named_conditions(_req(text)) == []


def test_a_wet_service_clause_is_held_on_a_sheet_that_does_not_state_wet():
    clause = _req("Valves shall be of steel for wet service.")
    out = cs.gate([clause], facts=[_fact("Fluid", "Lube oil, clean")])
    assert out["kept"] == []
    [held] = out["held"]
    assert held["code"] == "service_unknown" and '"wet"' in held["detail"]


def test_the_same_clause_is_kept_when_the_sheet_states_the_service():
    clause = _req("Valves shall be of steel for wet service.")
    out = cs.gate([clause], facts=[_fact("Service", "Wet gas")])
    assert [r["id"] for r in out["kept"]] == ["r"] and out["held"] == []


def test_a_short_word_inside_a_longer_word_is_not_stated():
    clause = _req("Seals for gas service shall be double.")
    assert cs.gate([clause], facts=[_fact("Fluid", "Gasoline")])["held"]


def test_a_number_word_is_not_part_of_a_service_name():
    # "month" was already read on main; the number word must not join it.
    found = cs.named_conditions(_req("A six month service interval shall apply."))
    assert "six month" not in found
