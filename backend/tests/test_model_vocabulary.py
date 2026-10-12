"""STATED via approved vocabulary (owner decision 2026-09-25): a synonym
counts only in an evidence line (equipment title or tag/service line), never
anywhere on the page.

Mutations: M529 (verify the quote against the whole page, not one evidence
line), M530 (substring instead of whole-word synonym match)."""
import pytest

from app.model_evidence import (NEEDS_ENGINEER_REVIEW, STATED_VIA_VOCABULARY, UNKNOWN_TYPE,
                                classify_via_vocabulary, equipment_evidence_lines, stated_via_vocabulary)

# A SMALL TEST VOCABULARY - the real list is still a proposal awaiting owner
# approval, so the function takes the vocabulary as a parameter.
VOCAB = {
    "Pressure Vessel": ("pressure vessel", "vessel", "drum", "drums", "column", "columns"),
    "Storage Tank": ("tank", "tanks"),
}

TITLE = ["MECHANICAL DATASHEET", "ONSHORE FACILITY", "SOUR WATER DRUMS"]
BODY = ("NOZZLE SCHEDULE\n"
        "MARK | SIZE | COLUMN A | COLUMN B\n"
        "N1 | 4 | 150 | RF\n"
        "TAG NO.: 2003-47-V-0001A/B\n"
        "The tanker loading bay is outside this scope.\n")
LINES = equipment_evidence_lines(TITLE, [BODY])


def test_a_synonym_in_the_equipment_title_is_stated_via_vocabulary():
    rec = stated_via_vocabulary("Pressure Vessel", "SOUR WATER DRUMS",
                                vocabulary=VOCAB, evidence_lines=LINES)
    assert rec is not None
    assert rec["class"] == STATED_VIA_VOCABULARY
    assert rec["synonym"] == "drums"
    assert rec["evidence_line"] == "SOUR WATER DRUMS"


def test_column_in_a_table_header_never_produces_pressure_vessel():
    """THE OWNER'S TEST (M529): "COLUMN A" is verbatim on the page, but in a
    table header, not the equipment title or a tag/service line."""
    assert stated_via_vocabulary("Pressure Vessel", "COLUMN A",
                                 vocabulary=VOCAB, evidence_lines=LINES) is None


def test_a_synonym_inside_a_longer_word_does_not_count():
    """THE MUTATION TARGET (M530): "tanker" is not "tank"."""
    lines = LINES + ["TANKER LOADING ARM"]
    assert stated_via_vocabulary("Storage Tank", "TANKER LOADING ARM",
                                 vocabulary=VOCAB, evidence_lines=lines) is None


def test_a_tag_line_is_an_evidence_line_and_a_body_sentence_is_not():
    assert "TAG NO.: 2003-47-V-0001A/B" in LINES
    assert not any("tanker loading bay" in l for l in LINES)


def test_a_value_outside_the_vocabulary_is_never_stated():
    assert stated_via_vocabulary("SOUR WATER DRUMS", "SOUR WATER DRUMS",
                                 vocabulary=VOCAB, evidence_lines=LINES) is None


def test_a_right_line_without_a_synonym_of_that_value_is_not_stated():
    assert stated_via_vocabulary("Storage Tank", "SOUR WATER DRUMS",
                                 vocabulary=VOCAB, evidence_lines=LINES) is None


def test_no_quote_is_never_stated():
    assert stated_via_vocabulary("Pressure Vessel", None,
                                 vocabulary=VOCAB, evidence_lines=LINES) is None


# ------------------- addendum 4 (2026-09-25): adversarial titles, ambiguity
# Mutations M682-M686. The vocabulary below MIRRORS the PROPOSED v1 list
# (.cowork/equipment-type-vocabulary-PROPOSED-v1.md) as TEST DATA only; the
# `ambiguous` and `not_equipment` lists are proposals too. Nothing here is
# approved. Synthetic titles, no client documents.

PROPOSED = {
    "Centrifugal Pump": ("centrifugal pump",), "Pump (other)": ("pump",), "Compressor": ("compressor",),
    "Turbine": ("turbine", "steam turbine", "gas turbine"), "Diesel Engine": ("diesel engine",),
    "Gear / Gearbox": ("gear", "gearbox"), "Mixer / Agitator": ("mixer", "agitator"),
    "Fan / Blower": ("fan", "blower"),
    "Pressure Vessel": ("pressure vessel", "vessel", "drum", "column", "tower", "reactor"),
    "Storage Tank": ("storage tank", "tank"), "Heat Exchanger": ("heat exchanger", "exchanger"),
    "Air Cooler": ("air cooler", "air-cooled exchanger"), "Boiler": ("boiler",),
    "Fired Heater": ("fired heater", "heater", "furnace"),
    "Pressure Safety / Relief Valve": ("pressure safety valve", "safety valve", "relief valve", "psv", "prv"),
    "Control Valve": ("control valve",), "Valve (other)": ("valve",), "Piping": ("piping",),
    "Pipeline": ("pipeline",), "Flange / Gasket / Fitting": ("flange", "gasket", "fitting"),
    "Electric Motor": ("motor",), "Generator": ("generator",), "Transformer": ("transformer",),
    "Switchgear": ("switchgear",), "UPS / Battery": ("ups", "battery", "batteries"), "Cable": ("cable",),
    "Instrument": ("instrument", "transmitter", "gauge"), "Analyzer": ("analyzer", "analyser"),
    "Meter": ("meter", "metering"), "Flare": ("flare",),
}
#: the vocabulary proposal's AMBIGUOUS table, plus "vessel" (a ship - owner 4.7)
AMBIGUOUS = frozenset("column drum tank tower meter seal gear battery fan fitting instrument vessel".split())
NOT_EQUIPMENT = ("battery limit", "instrument air")

ADV_TITLE = ["PUMP MOTOR", "INSTRUMENT AIR COMPRESSOR", "SUPPLY VESSEL", "TANK HEATER",
             "EQUIPMENT WITHIN BATTERY LIMIT", "CENTRIFUGAL PUMP", "PRESSURE SAFETY VALVE", "SOUR WATER DRUMS"]
ADV_LINES = equipment_evidence_lines(ADV_TITLE, ["MARK | SIZE | COLUMN A | COLUMN B\nN1 | 4 | 150 | RF"])

#: (quote, the TRUE type or None, expected status, expected value)
ADVERSARIAL = [
    ("CENTRIFUGAL PUMP", "Centrifugal Pump", STATED_VIA_VOCABULARY, "Centrifugal Pump"),
    ("PRESSURE SAFETY VALVE", "Pressure Safety / Relief Valve", STATED_VIA_VOCABULARY,
     "Pressure Safety / Relief Valve"),
    ("INSTRUMENT AIR COMPRESSOR", "Compressor", STATED_VIA_VOCABULARY, "Compressor"),
    ("PUMP MOTOR", "Electric Motor", NEEDS_ENGINEER_REVIEW, None),
    ("TANK HEATER", None, NEEDS_ENGINEER_REVIEW, None),
    ("SUPPLY VESSEL", None, NEEDS_ENGINEER_REVIEW, "Pressure Vessel"),
    ("SOUR WATER DRUMS", "Pressure Vessel", NEEDS_ENGINEER_REVIEW, "Pressure Vessel"),
    ("EQUIPMENT WITHIN BATTERY LIMIT", None, UNKNOWN_TYPE, None),
    ("COLUMN A", None, UNKNOWN_TYPE, None),
]


def _classify(quote):
    return classify_via_vocabulary(quote, vocabulary=PROPOSED, evidence_lines=ADV_LINES,
                                   ambiguous=AMBIGUOUS, not_equipment=NOT_EQUIPMENT)


@pytest.mark.parametrize("quote,truth,status,value", ADVERSARIAL, ids=[a[0] for a in ADVERSARIAL])
def test_adversarial_titles_are_stated_only_when_one_unambiguous_value_names_them(quote, truth, status, value):
    """THE MUTATION TARGETS (M682 several values -> one picked; M683
    ambiguous word accepted; M684 non-equipment phrase kept; M685 any page
    line accepted; M686 'PRESSURE SAFETY VALVE' also counted as 'valve')."""
    r = _classify(quote)
    assert (r["status"], r["value"]) == (status, value)


def test_several_values_are_all_listed_for_the_engineer():
    assert _classify("PUMP MOTOR")["candidates"] == ["Electric Motor", "Pump (other)"]
    assert _classify("TANK HEATER")["candidates"] == ["Fired Heater", "Storage Tank"]
    no_filter = classify_via_vocabulary("INSTRUMENT AIR COMPRESSOR", vocabulary=PROPOSED,
                                        evidence_lines=ADV_LINES, ambiguous=AMBIGUOUS)
    assert no_filter["status"] == NEEDS_ENGINEER_REVIEW
    assert no_filter["candidates"] == ["Compressor", "Instrument"]


def test_measured_on_the_adversarial_set_no_wrong_type_is_ever_stated():
    """Addendum 4.7 measurement: correct classifications AND wrong ones. A
    STATED value that is not the true type is WRONG - it would become the
    submittal's profile and could exclude an applicable standard. REVIEW /
    UNKNOWN on a clear title is a MISS (safe, costs engineer time)."""
    correct = wrong = missed = 0
    for quote, truth, _, _ in ADVERSARIAL:
        r = _classify(quote)
        if r["status"] == STATED_VIA_VOCABULARY:
            correct += r["value"] == truth
            wrong += r["value"] != truth
        elif truth is None:
            correct += 1
        else:
            missed += 1
    assert (correct, wrong, missed) == (7, 0, 2)
    # the older gate alone cannot see the marine case: it accepts the model's pick
    assert stated_via_vocabulary("Pressure Vessel", "SUPPLY VESSEL", vocabulary=PROPOSED,
                                 evidence_lines=ADV_LINES) is not None
