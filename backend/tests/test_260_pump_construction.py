"""Order 260.5 (service_unknown): a sentence that names a pump CONSTRUCTION ("for between-bearing
pumps") is decided by the sheet's pump-type line, not held. It does not apply only when a stated
pump-type field names ANOTHER construction; a type line that names none of them stays unknown and
the requirement stays a check/hold. Invented sentences and sheets only (rule 13)."""

from __future__ import annotations

import pytest

from app import service_scope


def req(rid, text):
    return {
        "id": rid,
        "requirement_type": "statement",
        "source_text": text,
        "requirement_text": text,
    }


def fact(label, value):
    return {
        "field_label": label,
        "field_name": label,
        "field_value": value,
        "raw_value": value,
    }


BB = req("bb", "Bearing housings shall be oil lubricated for between-bearing pumps.")
OH = req("oh", "The shaft shall be rigid for overhung pumps and shall not deflect.")
BOTH = req(
    "both",
    "Seal chambers shall be vented, for overhung pumps and for between bearing pumps.",
)
PLAIN = req("plain", "Vents shall be provided at every high point.")


def run(requirements, facts):
    out = service_scope.gate(requirements, facts=facts)
    return (
        [r["id"] for r in out["kept"]],
        {i["requirement"]["id"] for i in out["items"]},
        {h["requirement"]["id"] for h in out["held"]},
    )


@pytest.mark.parametrize("type_line", ["API 610 OH2", "overhung, API type OH2"])
def test_a_sheet_that_says_overhung_makes_the_between_bearing_sentence_not_apply(
    type_line,
):
    kept, not_applied, held = run([BB, OH, PLAIN], [fact("Pump type", type_line)])
    assert not_applied == {"bb"}
    assert (
        "oh" in kept and "plain" in kept and "bb" not in held
    )  # the sheet's own is checked


def test_a_sheet_that_says_between_bearings_makes_the_overhung_sentence_not_apply():
    kept, not_applied, _held = run([BB, OH], [fact("API pump type", "BB2")])
    assert not_applied == {"oh"}
    assert kept == ["bb"]


def test_a_type_line_that_names_no_construction_decides_nothing():
    """ "Centrifugal, single stage" is a stated pump-type field naming neither: unknown, so the
    sentence is never dropped (it was not named, so it also stays out of the new vocabulary)."""
    kept, not_applied, held = run(
        [BB, OH], [fact("Pump type", "Centrifugal, single stage")]
    )
    assert not_applied == set()
    assert kept == [] and held == {"bb", "oh"}


def test_no_pump_type_field_decides_nothing():
    kept, not_applied, held = run([BB, OH], [fact("Service", "Crude oil")])
    assert not_applied == set()
    assert kept == [] and held == {"bb", "oh"}


def test_a_sentence_that_also_names_the_sheets_own_construction_is_kept():
    """ "for overhung pumps and for between bearing pumps" applies to the overhung pump on the sheet."""
    kept, not_applied, _held = run([BOTH], [fact("Pump type", "OH1")])
    assert not_applied == set()
    assert kept == ["both"]


def test_a_blank_pump_type_field_decides_nothing():
    kept, not_applied, held = run(
        [BB],
        [{**fact("Pump type", ""), "is_blank": True}, fact("Service", "Crude oil")],
    )
    assert not_applied == set()
    assert kept == [] and held == {"bb"}


def test_the_not_applied_item_cites_the_sheets_own_field_and_value():
    out = service_scope.gate(
        [BB], facts=[{**fact("Pump type", "API 610 OH2"), "page": 3}]
    )
    [item] = out["items"]
    assert "Pump type: API 610 OH2" in item["detail"]
    assert "page 3" in item["detail"]
