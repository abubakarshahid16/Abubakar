"""#897 (Stage C, PF2, part of #882): the title block names ANY equipment type
of the equipment vocabulary, not only the handful the cover-sheet patterns
carry.

Seen on the bench: the title-block reader found the type for the pump, the
pressure vessel, the heat exchanger, the compressor and the PSV, but for
"CONTROL VALVE DATASHEET" and "PRESSURE TRANSMITTER DATASHEET" it stayed
empty, so the mandatory-field check fell back to "any datasheet" and no
type-based standard could be selected.

The fix is generic (CLAUDE.md rule 13): the reader falls back to
`reference/equipment_vocabulary.json` through `subject_scope.title_equipment`,
longest spelling first, case- and spacing-insensitive, tolerant of the sheet
words around the name. One type named: that is the reading. None, or two
different types: UNKNOWN, reported as unknown, never a guess. All data here
is invented; no client file is read.
"""

from __future__ import annotations

import pytest

from app import classification, subject_scope

VOCAB = subject_scope.vocabulary()


def _read(*lines: str) -> classification.EquipmentTypeEvidence | None:
    return classification.suggest_equipment_type_from_title(
        [(1, line) for line in lines])


# ------------------------------------------------- the two titles the bench missed

@pytest.mark.parametrize("title, expected, quote", [
    ("CONTROL VALVE DATASHEET", "Control Valve", "CONTROL VALVE"),
    ("PRESSURE TRANSMITTER DATA SHEET", "Pressure Transmitter", "PRESSURE TRANSMITTER"),
    ("Control Valve Specification", "Control Valve", "Control Valve"),
    ("Pressure  Transmitter\tDataSheet", "Pressure Transmitter", "Pressure Transmitter"),
])
def test_a_title_naming_a_vocabulary_type_is_read_as_that_type(title, expected, quote):
    """Fails without the fix: these titles match none of the cover-sheet
    patterns, so the reader returned None and the type stayed empty."""
    evidence = _read("EXAMPLE OPERATING COMPANY", title, "Doc No. 1234-A  Rev 2")
    assert evidence is not None, f"{title!r} was not read"
    assert evidence.equipment_type == expected
    assert evidence.method == "title_phrase_match"
    assert evidence.page == 1
    assert evidence.quote == quote, "the quote is the title's own spelling"
    assert evidence.confidence < 0.9, "confidence is never high (rule 4)"
    assert evidence.classifier_version == classification.EQUIPMENT_TYPE_CLASSIFIER_VERSION


def test_the_type_read_from_the_title_is_one_the_vocabulary_names():
    """The label the reader stores is the vocabulary's own type, so every
    reader of `equipment_type` (standards by subject, the review gate) can
    resolve it - nothing hard-coded for two titles."""
    for title in ("CONTROL VALVE DATASHEET", "PRESSURE TRANSMITTER DATA SHEET"):
        label = _read(title).equipment_type
        assert VOCAB.equipment_in(label) == {label.lower()}, label


# ------------------------------------------------------------ no regression

@pytest.mark.parametrize("title, expected, confidence", [
    ("PRESSURE SAFETY VALVE DATASHEET", "Pressure Safety Valve", 0.85),
    ("DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)", "Pressure Safety Valve", 0.85),
    ("CENTRIFUGAL PUMP DATA SHEET", "Centrifugal Pump", 0.85),
    ("RECYCLE BRINE PUMPS DATA SHEET", "Pump", 0.75),
    ("SHELL AND TUBE HEAT EXCHANGER DATA SHEET", "Heat Exchanger", 0.8),
])
def test_the_cover_sheet_patterns_still_decide_first(title, expected, confidence):
    """The specific labels the mandatory tables are keyed by keep their
    priority and their confidence; "pressure safety valve" is never shortened
    to "valve", and "centrifugal pump" is never read as a bare pump."""
    evidence = _read(title)
    assert evidence is not None
    assert evidence.equipment_type == expected
    assert evidence.confidence == confidence


# ------------------------------------------------------------ unknown stays unknown

@pytest.mark.parametrize("lines", [
    ("GENERAL NOTES AND LEGEND", "Doc No. 1234-A"),
    ("INSTRUMENT INDEX", "Rev 0"),
    ("VALVE DATA SHEET",),                       # "valve" could be three types
    ("DATA SHEET", "Pressure 10 barg", "Flow 20 m3/h"),
])
def test_a_title_with_no_equipment_word_stays_unknown(lines):
    assert _read(*lines) is None


@pytest.mark.parametrize("lines", [
    # an unlabelled "pumps" in a sentence on the cover, even beside "datasheet"
    ("This datasheet supports the piping package for the new transfer pumps.",),
    # a bare equipment word on its own cover line, with no sheet word or label
    ("MECHANICAL DATASHEET", "SOUR SERVICE DRUM", "Rev. 00"),
    ("PUMP", "Doc No. 1234-A"),
    # a near-miss label: only "Equipment:" and "Title:" fields are read
    ("SERVICE: booster pump", "NOTE: see pump curve"),
])
def test_an_unlabelled_equipment_word_in_free_text_is_not_read(lines):
    """Rule 4: a word in body or cover text is not a title-block reading.
    Only a labelled "Equipment:"/"Title:" field, or a line that is nothing
    but the name and the sheet words, names the type; anything else stays
    unknown rather than being shown as if it had been read."""
    assert _read(*lines) is None


@pytest.mark.parametrize("line, expected", [
    ("Equipment: Pressure Transmitter", "Pressure Transmitter"),
    ("TITLE: CONTROL VALVE DATA SHEET", "Control Valve"),
    ("Data Sheet for Level Transmitters", "Level Transmitter"),
])
def test_a_labelled_title_field_is_read(line, expected):
    evidence = _read("EXAMPLE OPERATING COMPANY", line)
    assert evidence is not None, line
    assert evidence.equipment_type == expected


def test_a_title_naming_two_different_types_stays_unknown():
    """Neither the first nor the longest: a sheet that calls itself both is
    not decidable from its title, and an undecidable type is reported as
    unknown (rule 4: a guess is shown as a guess, so no guess is stored)."""
    assert _read("CONTROL VALVE AND PRESSURE TRANSMITTER DATA SHEET") is None
    assert _read("CONTROL VALVE DATA SHEET", "PRESSURE TRANSMITTER DATA SHEET") is None
    assert _read("LEVEL TRANSMITTER", "FLOW TRANSMITTER", "DATASHEET") is None


def test_the_sheet_line_decides_before_the_other_edge_lines():
    """The page edge that names the sheet is the document naming itself; a
    footer line naming the equipment beside it is not a second type."""
    evidence = _read("CONTROL VALVE DATA SHEET", "Service: motor cooling water return")
    assert evidence is not None
    assert evidence.equipment_type == "Control Valve"


# ------------------------------------------------------------ the vocabulary reader

def test_title_equipment_reads_the_longest_spelling_and_keeps_case():
    typ, page, quote = subject_scope.title_equipment(
        [(3, "Differential Pressure Transmitter Datasheet")], VOCAB)
    assert (typ, page, quote) == ("pressure transmitter", 3,
                                  "Differential Pressure Transmitter")


def test_title_equipment_with_an_edited_vocabulary(tmp_path):
    """Generic: a type added to the data file is read on the next call, with
    no code change (rule 13)."""
    import json
    path = tmp_path / "vocab.json"
    path.write_text(json.dumps({"types": {
        "widget skid": {"kind": "equipment", "synonyms": ["widget skids"]},
        "skid": {"kind": "component"},
    }}), encoding="utf-8")
    vocab = subject_scope.vocabulary(path)
    assert subject_scope.title_equipment([(1, "WIDGET SKIDS DATA SHEET")], vocab) == (
        "widget skid", 1, "WIDGET SKIDS")
    assert subject_scope.title_equipment([(1, "SKID DATA SHEET")], vocab) is None
    assert subject_scope.title_equipment([], vocab) is None
