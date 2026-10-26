"""Order 228.5: a function word before "service" or "application" names no service.

On the owner's I-06 run at least 17 requirements were held as "applies only to 'into'"
because "put into service", "inspected before service", "maintained during service" and
"the following application" were read as conditions the datasheet had to state. A phrase
whose word right before "service"/"application" is a preposition, a participle or an
auxiliary names nothing; a real service ("sour", "cooling water", "offshore") still does.
Invented sentences only.
"""

from __future__ import annotations

import pytest

from app import clause_support as cs


def _req(text: str, **more) -> dict:
    return {"source_text": text, "requirement_type": "numeric_limit", **more}


@pytest.mark.parametrize(
    "text",
    [
        "The unit shall be tested before it is put into service.",
        "Seals shall be maintained during service.",
        "Equipment shall be inspected before service.",
        "The following application shall apply.",
        "Parts used after service shall be cleaned.",
        "Valves shall be checked prior to and while in service.",
        "Bearings shall be lubricated until service.",
        "The unit is suitable for service after the test.",
        "Equipment shall be ready for service.",
        "Coatings released for application shall be logged.",
    ],
)
def test_a_function_word_before_service_names_no_condition(text):
    assert cs.named_conditions(_req(text)) == []


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Seals for sour service shall be of alloy 625.", ["sour"]),
        ("The pump in cooling water service shall have a strainer.", ["cooling water"]),
        ("Machines for offshore application shall be painted.", ["offshore"]),
        ("Pumps in fire water service shall be listed.", ["fire water"]),
        ("Seal flush shall follow Plan 32.", ["plan 32"]),
        # only the words AFTER the last linking word name the service
        ("Parts used before lethal service shall be marked.", ["lethal"]),
        ("Seals subjected to sour service shall be of alloy 625.", ["sour"]),
    ],
)
def test_a_real_service_is_still_named(text, named):
    assert cs.named_conditions(_req(text)) == named


def test_a_requirement_with_only_a_function_word_phrase_is_kept_not_held():
    facts = [
        {"field_label": "Service", "field_value": "Cooling water", "is_blank": False}
    ]
    kept = cs.hold_unstated_services(
        [_req("The unit shall be tested before it is put into service.", id="r1")],
        facts=facts,
    )
    assert [r["id"] for r in kept["kept"]] == ["r1"] and kept["held"] == []
    held = cs.hold_unstated_services(
        [_req("Seals for sour service shall be of alloy 625.", id="r2")], facts=facts
    )
    assert [h["requirement"]["id"] for h in held["held"]] == ["r2"]
