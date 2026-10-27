"""Order 228.1-228.3 (the owner's I-06 walk-through): the program's own names stay internal.

A checklist row's Standard Reference cites its source ("API 520-I 3.20 (p.12)") instead of the
program's check id; an AI draft's Standard Reference is the standard it relates to, never the
engine that wrote it; the program's bookkeeping sentences do not reach a contractor's copy.
Invented data only.
"""

from __future__ import annotations

import pytest

from app import crs_machine_words, crs_mapping, crs_reference


def _check(**more):
    return {
        "id": "c1",
        "origin": "datasheet_check",
        "compliance_status": "NON_COMPLIANT",
        "requirement_source_text": "Datasheet check PSV-14: relieving capacity not below required",
        "ai_rationale": "Datasheet check PSV-14: capacity 90 below 100",
        "contractor_section": "Rated capacity",
        "contractor_page": 2,
        "standard_clause": "API 520-I 3.20",
        **more,
    }


def test_a_checklist_row_cites_its_source_not_the_program_check_id():
    assert crs_mapping._standard_reference(_check()) == "API 520-I 3.20"
    assert "PSV" not in crs_mapping._standard_reference(_check())


def test_the_page_is_added_once_it_is_located():
    row = _check(standard_page=12)
    assert crs_mapping._standard_reference(row) == "API 520-I 3.20 (p.12)"


def test_a_check_with_no_source_prints_no_id():
    row = _check(standard_clause=None, standard_page=None)
    assert crs_mapping._standard_reference(row) == "Datasheet check"


def test_the_check_id_is_kept_in_the_internal_reasoning_cell():
    reasoning = crs_mapping.reasoning_text([_check()])
    assert "Check: PSV-14" in reasoning and "Clause: API 520-I 3.20" in reasoning


WRITTEN = (
    "AI engineering check. Relates to: API 520-I. Written by "
    "ollama:hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_M, from the datasheet alone - no standard's "
    "text was sent."
)


def test_an_ai_draft_relates_to_the_standard_not_the_engine_that_wrote_it():
    finding = {"origin": "ai_engineering_check", "ai_rationale": WRITTEN}
    assert crs_mapping._ai_relates_to(finding) == "API 520-I"


@pytest.mark.parametrize(
    "rationale, name",
    [
        (
            "AI engineering check. Relates to: ISO 9001:2015. Written by claude:fake.",
            "ISO 9001:2015",
        ),
        ("AI engineering check. Relates to: API 520 Part I.", "API 520 Part I"),
        (
            "AI engineering check. Relates to: no standard named. Written by ollama:x.",
            "no standard named",
        ),
    ],
)
def test_the_name_stops_before_the_engine_sentence(rationale, name):
    assert crs_reference.relates_to(rationale) == name


def test_the_engine_is_kept_in_the_internal_reasoning_cell_only():
    finding = {"origin": "ai_engineering_check", "ai_rationale": WRITTEN}
    assert (
        crs_reference.engine_of(finding)
        == "ollama:hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_M"
    )
    assert (
        "Written by: ollama:hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_M"
        in crs_mapping.reasoning_text([finding])
    )
    assert crs_reference.engine_of({"ai_rationale": "Relates to: X."}) == ""


@pytest.mark.parametrize(
    "sentence",
    [
        "the requirement states no numeric limit this engine can evaluate; it needs a human reading",
        "3 drafts about this field differ; all are kept.",
        "4 blanks, one answer",
        "3 places, one answer",
        "Paired by model-assigned field name; engineer must confirm",
    ],
)
def test_the_programs_bookkeeping_sentences_are_machine_words(sentence):
    assert crs_machine_words.find_machine_words(sentence)


def test_a_plain_engineering_sentence_is_not_flagged():
    text = "The contractor can evaluate the answer once per place."
    assert crs_machine_words.find_machine_words(text) == []


@pytest.mark.parametrize("clause", ["", "   ", "\t\n", None])
def test_a_blank_or_whitespace_clause_is_no_source(clause):
    row = _check(standard_clause=clause, standard_page=3)
    assert crs_mapping._standard_reference(row) == "Datasheet check"


def test_a_clause_with_stray_spaces_prints_once_tidy():
    row = _check(standard_clause="  API 520-I   3.20 ", standard_page=3)
    assert crs_mapping._standard_reference(row) == "API 520-I 3.20 (p.3)"


@pytest.mark.parametrize(
    "rationale, engine",
    [
        (
            "AI engineering check. Relates to: X. Written by an unnamed engine.",
            "an unnamed engine",
        ),
        (
            "AI engineering check. Relates to: X. Written by a local model.",
            "a local model",
        ),
        ("AI engineering check. Relates to: X. Written by claude:fake.", "claude:fake"),
        (
            "AI engineering check. Relates to: X. Written by ollama:hf.co/a/Qwen3.6-35B:Q4, "
            "from the datasheet alone - no standard's text was sent.",
            "ollama:hf.co/a/Qwen3.6-35B:Q4",
        ),
        ("AI engineering check. Relates to: X.", ""),
    ],
)
def test_the_engine_is_the_whole_name_in_the_engine_sentence(rationale, engine):
    assert crs_reference.engine_of({"ai_rationale": rationale}) == engine
