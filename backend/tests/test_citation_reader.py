"""The citation reader: which standards a datasheet's text cites (#623).

`datasheets.referenced_standards` used to be a list of families, so an IEC,
EN, ISA or ISO-with-a-part citation was never detected - and the one matcher
(#621) never saw it, so it was neither matched to a held standard nor listed
missing. The reader is now `standard_ids.find_citations`: the matcher's own
grammar (issuing body + series + number + part/division/year), with the
issuing bodies, aliases and class letters in the editable vocabulary file.

All text here is invented datasheet wording; no client data.
"""

from __future__ import annotations

import json

import pytest

from app import applicability, datasheets, db, keyword, standard_ids, submittal_review
from app.config import settings

SHEET = ("Safety instrumented system per IEC 61511-1. Vessel design to BS EN 13445-3. "
         "SIL verification per ANSI/ISA-84.00.01. Offshore process safety per ISO 10418:2019.")


# ---------------------------------------------- detected: any issuing body

def test_iec_en_isa_and_iso_citations_are_detected():
    assert datasheets.referenced_standards(SHEET) == [
        "IEC 61511-1", "BS EN 13445-3", "ANSI/ISA-84.00.01", "ISO 10418"]


def test_each_citation_is_located_where_it_is_printed():
    for raw, start, end in datasheets.referenced_standard_spans(SHEET):
        assert " ".join(SHEET[start:end].split()) == raw


@pytest.mark.parametrize(("text", "expected"), [
    ("SIS to IEC 61511 Part 1", ["IEC 61511 Part 1"]),
    ("shell to EN 13445 Part 3", ["EN 13445 Part 3"]),
    ("SIL per ISA 84.00.01", ["ISA 84.00.01"]),
    ("piping to ASME B31.3-2022", ["ASME B31.3"]),
    ("flanges to DIN EN 1092-1", ["DIN EN 1092-1"]),
    ("actuators per IEC 60534-2-1 and NORSOK M-001", ["IEC 60534-2-1", "NORSOK M-001"]),
])
def test_other_unseen_citations_are_detected(text, expected):
    assert datasheets.referenced_standards(text) == expected


def test_two_equivalent_standards_both_cited_are_both_listed():
    """NACE MR0175 and ISO 15156 are one standard to the matcher, but a sheet
    that cites both cited both - the citation list is what was printed."""
    assert datasheets.referenced_standards("materials per NACE MR0175 and ISO 15156") == [
        "NACE MR0175", "ISO 15156"]


def test_two_spellings_of_one_code_are_one_citation():
    assert datasheets.referenced_standards(
        "per ASME Sec VIII Div 1; see also ASME VIII DIV. 1") == ["ASME Sec VIII Div 1"]


# ---------------------------------------------- not detected: false positives

@pytest.mark.parametrize("text", [
    "Tag 21-PV-1234 and 22-PV-1234",             # equipment tags
    "PSV tag 10-IEC-1234 and spare 10-EN-1234",    # a body name inside a tag
    "Doc. No. P-1234-0001-SP-9999-0001",        # a document number
    "Ref. doc EN-12345-B rev 2",                   # a body name glued into a code
    "Line 6-PL-1234-A1, LINE 12, DWG 4501, REV 3",  # line, drawing and revision numbers
    "Flow 1200 m3/h at 25 bar, item 25, 3 off",    # plain numbers
    "SS 316 body, IP 66 enclosure, sized as 25 mm",  # material, ingress rating, a word
    "rated en 1200 rpm",                           # a lower-case word is never a body
    "API 20 units and SAES-B-14 in prose",         # short numbers stay numbers
])
def test_tags_document_numbers_and_plain_numbers_are_not_citations(text):
    assert datasheets.referenced_standards(text) == []


def test_a_citation_next_to_a_tag_is_still_read():
    """Asserted as a presence on the same input as an absence, so the negative
    cases cannot pass by the reader having stopped reading anything."""
    assert datasheets.referenced_standards(
        "Tag 21-PV-1234, relief per IEC 61511-1, doc P-1234-0001-SP-9999-0001") == ["IEC 61511-1"]


# ---------------------------------------------- the bodies are data

@pytest.fixture
def vocabulary_file(tmp_path, monkeypatch):
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


def test_the_issuing_bodies_come_from_the_vocabulary_file(vocabulary_file):
    original, write = vocabulary_file
    assert datasheets.referenced_standards("per IEC 61511-1 and GOST 12345") == ["IEC 61511-1"]
    write({**original, "citation_bodies": ["GOST"]})
    assert datasheets.referenced_standards("per IEC 61511-1 and GOST 12345") == ["GOST 12345"]


def test_the_class_letters_come_from_the_vocabulary_file(vocabulary_file):
    original, write = vocabulary_file
    assert datasheets.referenced_standards("Design Standard: TEMA Class R") == ["TEMA Class R"]
    write({**original, "class_designations": {}})
    assert datasheets.referenced_standards("Design Standard: TEMA Class R") == []


# ---------------------------------------------- end to end: the matcher sees it

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


def test_a_cited_iec_standard_is_selected_when_held_and_listed_missing_when_not(temp_storage):
    std = _doc("std_iec", "IEC 61511-1 Ed2 2016.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sis.pdf", "CONTRACTOR_SUBMITTAL", text=SHEET)
    result = applicability.select(sub, allowed_document_ids=frozenset({std, sub}), persist=False)
    referenced = [s["standard_document_id"] for s in result["selected"]
                  if s["method"] == applicability.METHOD_REFERENCED]
    assert referenced == [std]
    assert [m["identifier"] for m in result["missing_references"]] == [
        "BS EN 13445-3", "ANSI/ISA-84.00.01", "ISO 10418"]
