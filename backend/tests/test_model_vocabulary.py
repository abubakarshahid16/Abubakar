"""STATED via approved vocabulary (owner decision 2026-09-25): a synonym
counts only in an evidence line (equipment title or tag/service line), never
anywhere on the page.

Mutations: M529 (verify the quote against the whole page, not one evidence
line), M530 (substring instead of whole-word synonym match)."""
from app.model_evidence import (STATED_VIA_VOCABULARY, equipment_evidence_lines,
                                stated_via_vocabulary)

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
