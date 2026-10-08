"""ONE matcher for standard identifiers (W3, #452; audit A02, A03).

The live app check of 2026-10-08: a PSV datasheet cited "API RP 520 Pt-1", the
library held API 520 Part I, and the review never used it - the two keys
("APIRP520PT1", "API520I...") were not prefixes of each other. The same prefix
rule, the other way round, made "API 65" and "API 6500" the held API 650.

These tests pin the four acceptance rules of #452 through the functions every
caller now uses (`applicability.find_standard`, `missing_references`, `select`)
and through each caller that used to keep its own matcher. Every library entry
is invented test data (a filename and a document number, no document text).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import (
    applicability,
    chat_comparison,
    chat_tools,
    claude_selection,
    db,
    keyword,
    standard_ids,
    standards,
    submittal_review,
    understanding,
)
from app.config import settings


def _entry(doc_id: str, filename: str, document_number: str | None = None) -> dict:
    return {"id": doc_id, "filename": filename, "document_number": document_number}


#: Part II BEFORE Part I, and API 6500 / API 65-like neighbours present, so a
#: matcher that ignored the part or matched a prefix would return the WRONG
#: entry first instead of merely returning one.
LIBRARY = [
    _entry("api520_2", "API-520-II.pdf"),
    _entry("api520_1", "API-520-I.pdf"),
    _entry("api650", "API-650.pdf"),
    _entry("b165", "ASME B16.5-2020.pdf"),
    _entry("viii2", "BPVC-8-2.pdf", "ASME BPVC Section VIII Division 2"),
    _entry("viii1", "BPVC-8-1.pdf", "ASME BPVC Section VIII Division 1"),
    _entry("iso15156", "ISO-15156-2.pdf"),
    _entry("saes", "SAES-B-14 -Final Draft 01-29-23.pdf"),
    _entry("samss", "32-SAMSS-004 Rev 3.pdf"),
]


def _found(identifier: str, library=LIBRARY) -> str | None:
    entry = applicability.find_standard(library, identifier)
    return entry["id"] if entry else None


# ======================================== 1. every common spelling finds it

@pytest.mark.parametrize(("cited", "expected"), [
    ("API RP 520 Pt-1", "api520_1"),
    ("API RP 520 Part I", "api520_1"),
    ("API 520-1", "api520_1"),
    ("API-520-I", "api520_1"),
    ("API 520 Part 1", "api520_1"),
    ("API RP 520 Part II", "api520_2"),
    ("ASME B16.5", "b165"),
    ("ANSI/ASME B16.5", "b165"),
    ("ASME Sec VIII Div 1", "viii1"),
    ("ASME Section VIII Division 1", "viii1"),
    ("ASME BPVC VIII-1", "viii1"),
    ("ASME Sec. VIII Div. 2", "viii2"),
    ("ISO 15156-2", "iso15156"),
    ("NACE MR0175", "iso15156"),
    ("NACE MR0175/ISO 15156", "iso15156"),
    ("SAES-B-014", "saes"),
    ("SAES B 14", "saes"),
    ("32-SAMSS-004", "samss"),
    ("32 SAMSS 004", "samss"),
])
def test_every_common_spelling_finds_the_right_library_document(cited, expected):
    assert _found(cited) == expected



def test_a_dropped_leading_zero_is_the_same_saes_number_everywhere():
    """SAES-B-14 (a filename with the zero dropped) is SAES-B-014 (the
    citation) in the matcher itself, not only where the library side is
    padded first - the chat gate and the compare check call it directly."""
    assert standard_ids.same_standard("SAES-B-14", "SAES-B-014")
    assert standard_ids.names_standard("what does SAES-B-014 require?", "SAES-B-14")
    assert claude_selection.is_referenced("SAES-B-14", {"referenced_standards": ["SAES-B-014"]})

# ======================================== 2. numbers are matched WHOLE

@pytest.mark.parametrize("cited", ["API 65", "API 6500", "API RP 65", "API 650A"])
def test_a_different_number_never_matches_api_650(cited):
    only_650 = [_entry("api650", "API-650.pdf", "API 650")]
    assert _found("API 650", only_650) == "api650"  # positive control first
    assert _found(cited, only_650) is None


@pytest.mark.parametrize(("a", "b"), [
    ("ASME B16.5", "ASME B16.50"), ("ASME B16.5", "ASME B16.47"),
    ("SAES-A-133", "SAES-A-13"), ("32-SAMSS-004", "32-SAMSS-040"),
    ("NFPA 20", "NFPA 200"), ("STD-A-001", "STD-A-0012"),
])
def test_numbers_are_compared_whole_in_every_family(a, b):
    assert standard_ids.same_standard(a, a)
    assert not standard_ids.same_standard(a, b)
    assert not standard_ids.same_standard(b, a)


# ======================================== 3. a part or division must agree

def test_part_one_never_matches_part_two():
    only_part_two = [_entry("api520_2", "API-520-II.pdf")]
    assert _found("API RP 520 Part II", only_part_two) == "api520_2"  # control
    for cited in ("API RP 520 Pt-1", "API 520 Part I", "API 520-1"):
        assert _found(cited, only_part_two) is None
    assert not standard_ids.same_standard("ASME Sec VIII Div 1", "ASME Sec VIII Div 2")
    assert not standard_ids.same_standard("ISO 15156-2", "ISO 15156-3")


def test_a_part_stated_on_one_side_only_still_matches():
    """A citation of part of a standard is a citation of that standard - the
    case the old prefix rule existed for, kept without the prefix."""
    whole = [_entry("whole_520", "API-RP-520.pdf", "API RP 520")]
    assert _found("API RP 520 Pt-1", whole) == "whole_520"
    assert _found("API 520", [_entry("api520_1", "API-520-I.pdf")]) == "api520_1"


# ================= 4. the missing-standards list uses the same matcher

def test_missing_references_no_longer_lists_api_520_part_1_when_it_is_held():
    held = [_entry("api520_1", "API-520-I.pdf")]
    assert applicability.missing_references(held, ["API RP 520 Pt-1", "API 650"]) == ["API 650"]


def test_two_spellings_of_one_missing_standard_are_listed_once():
    assert applicability.missing_references(
        [], ["API RP 520 Pt-1", "API 520 Part 1", "API 650"]) == ["API RP 520 Pt-1", "API 650"]


# ---------------------------------------------------- through the database

@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "") -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-10-08T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        conn.execute("INSERT INTO document_classification (document_id, suggested_by, document_role)"
                     " VALUES (?, 'test', ?)", (doc_id, role))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename, f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def test_a_datasheet_citing_api_rp_520_pt_1_uses_the_held_api_520_part_1(temp_storage):
    """The live failure, end to end through `select`: API 520 Part I is
    selected as referenced, and the missing list does not name it."""
    std = _doc("std_520_1", "API-520-I.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL",
               text="Relief valve sizing per API RP 520 Pt-1 and API 650.")
    result = applicability.select(sub, allowed_document_ids=frozenset({std, sub}), persist=False)
    referenced = [s for s in result["selected"] if s["method"] == applicability.METHOD_REFERENCED]
    assert [s["standard_document_id"] for s in referenced] == [std]
    assert [m["identifier"] for m in result["missing_references"]] == ["API 650"]


def test_the_chat_tool_reports_a_held_standard_as_held(temp_storage):
    """`list_cited_standards` used to look an IDENTIFIER up in a dict keyed by
    DOCUMENT ID, so every cited standard came back "cited but not held"."""
    std = _doc("std_520_1", "API-520-I.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL",
               text="Relief valve sizing per API RP 520 Pt-1 and API 650.")
    assert {e["id"] for e in standards.list_standards(
        allowed_document_ids=frozenset({std, sub}), include_superseded=True)} == {std}
    run = chat_tools.run_list_cited_standards(
        {"document_id": sub}, allowed_document_ids=frozenset({std, sub}))
    assert "API RP 520 Pt-1: held (API-520-I.pdf)" in run.note
    assert "API 650: cited but not held in this library" in run.note


# ---------------------------------------------- the chat-side callers

def test_a_question_naming_api_520_part_1_is_scoped_to_that_file():
    docs = {"d1": "API-520-I.pdf", "d2": "API-520-II.pdf", "d3": "API-650.pdf"}
    named = understanding.named_documents(
        "Per API 520 Part I, at what overpressure must the valve reach rated capacity?", docs)
    assert sorted(i for ids in named.values() for i in ids) == ["d1"]
    assert understanding.named_documents("What does API 65 require?", docs) == {}


def test_a_compare_naming_api_65_says_api_65_is_not_held():
    assert chat_comparison.missing_designations(
        "Compare API-65 and API-650", ["API-650"]) == ["API-65"]
    assert chat_comparison.missing_designations(
        "Compare API-520-1 and API-650", ["API-520-I", "API-650"]) == []


def test_the_contractual_gate_matches_the_cited_spelling_not_a_prefix():
    summary = {"referenced_standards": ["API RP 520 Pt-1", "API 65"]}
    assert claude_selection.is_referenced("API 520 Part I", summary)
    assert not claude_selection.is_referenced("API 650", summary)


# ============ generic: bodies the matcher has no special case for (#621 review)
#
# None of these is in the library fixture above or in any bug report: they
# prove the GENERAL shape (issuing body + number + optional part, year
# ignored) and the vocabulary file, not a list of remembered spellings.

UNSEEN = [
    # (cited as, family, number, part)
    ("IEC 61511-1", "IEC", "61511", "1"),
    ("IEC 61511 Part 1", "IEC", "61511", "1"),
    ("BS EN 13445-3", "EN", "13445", "3"),
    ("EN 13445 Part 3", "EN", "13445", "3"),
    ("ISA 84.00.01", "ISA", "84.00.01", None),
    ("ANSI/ISA-84.00.01", "ISA", "84.00.01", None),
    ("ISO 10418:2019", "ISO", "10418", None),
    ("ASME B31.3-2022", "ASME B", "31.3", None),
]


@pytest.mark.parametrize(("cited", "family", "number", "part"), UNSEEN)
def test_an_unseen_standard_is_recognised_as_an_identifier(cited, family, number, part):
    assert standard_ids.parse(cited) == standard_ids.StandardId(family, number, part)


#: Invented library files for those standards, each named the way a file is
#: usually saved - not the way it is cited.
UNSEEN_LIBRARY = [
    _entry("iec_2", "IEC-61511-2.pdf"),
    _entry("iec_1", "IEC 61511-1 Ed2 2016.pdf"),
    _entry("en_4", "BS EN 13445-4 2021.pdf"),
    _entry("en_3", "BS EN 13445-3 2021.pdf"),
    _entry("isa", "ANSI-ISA-84.00.01-2004.pdf", "ISA 84.00.01"),
    _entry("iso", "ISO 10418 2019.pdf"),
    _entry("b313", "ASME B31.3-2022 Process Piping.pdf"),
]
_UNSEEN_EXPECTED = {"IEC 61511-1": "iec_1", "IEC 61511 Part 1": "iec_1", "BS EN 13445-3": "en_3",
                    "EN 13445 Part 3": "en_3", "ISA 84.00.01": "isa", "ANSI/ISA-84.00.01": "isa",
                    "ISO 10418:2019": "iso", "ASME B31.3-2022": "b313"}


@pytest.mark.parametrize("cited", [row[0] for row in UNSEEN])
def test_an_unseen_standard_finds_its_document_when_one_is_held(cited):
    assert _found(cited, UNSEEN_LIBRARY) == _UNSEEN_EXPECTED[cited]


@pytest.mark.parametrize("cited", [row[0] for row in UNSEEN])
def test_an_unseen_standard_is_listed_missing_when_no_document_is_held(cited):
    unrelated = [_entry("api650", "API-650.pdf"), _entry("iec_2", "IEC-61511-2.pdf"),
                 _entry("en_4", "BS EN 13445-4.pdf"), _entry("b314", "ASME B31.4.pdf")]
    assert applicability.missing_references(unrelated, [cited]) == [cited]
    assert applicability.missing_references(UNSEEN_LIBRARY, [cited]) == []


# ============ the equivalences are DATA, not code

def test_no_equivalence_is_written_in_the_matcher_code():
    source = (Path(standard_ids.__file__)).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    code_without_docstrings = re.sub(r'"""[\s\S]*?"""', "", code)
    for token in ("MR0175", "15156", "BS EN", "DIN EN", "ANSI/ISA", '"RP"', '"STD"'):
        assert token not in code_without_docstrings, f"{token} is hard-coded in standard_ids.py"


@pytest.fixture
def vocabulary_file(tmp_path, monkeypatch):
    """A copy of the vocabulary file the test may edit; caches reset around it."""
    original = json.loads(standard_ids.VOCABULARY_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "standard_identifiers.json"
    monkeypatch.setattr(standard_ids, "VOCABULARY_PATH", path)

    def write(data):
        path.write_text(json.dumps(data), encoding="utf-8")
        standard_ids.reload_vocabulary()
    write(original)
    yield original, write
    monkeypatch.undo()
    standard_ids.reload_vocabulary()


def test_editing_the_vocabulary_file_changes_what_is_one_standard(vocabulary_file):
    original, write = vocabulary_file
    assert standard_ids.same_standard("NACE MR0175", "ISO 15156")
    assert standard_ids.same_standard("BS EN 13445-3", "EN 13445 Part 3")
    write({**original, "equivalent": [], "body_aliases": {}})
    assert not standard_ids.same_standard("NACE MR0175", "ISO 15156")
    assert not standard_ids.same_standard("BS EN 13445-3", "EN 13445 Part 3")
    write({**original, "equivalent": [["IEC 61511", "ISA 84.00.01"]]})
    assert standard_ids.same_standard("ANSI/ISA-84.00.01", "IEC 61511")


def test_the_api_document_words_come_from_the_vocabulary_file(vocabulary_file):
    original, write = vocabulary_file
    assert standard_ids.same_standard("API RP 520 Pt-1", "API 520 Part 1")
    write({**original, "api_document_words": []})
    assert standard_ids.parse("API RP 520 Pt-1") is None or not standard_ids.same_standard(
        "API RP 520 Pt-1", "API 520 Part 1")
