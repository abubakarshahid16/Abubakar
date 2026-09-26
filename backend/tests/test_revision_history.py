"""A standard's revision history is a record, not clauses and not requirements.

MEASURED on the ten real company standards before this fix: every one prints
a "Summary of Changes" table - (row, paragraph, change type, description) - in
front of its body, and most a dated "Document History" behind it. The
paragraph column is a column of clause NUMBERS, and the heading detector read
each row as a heading. On one standard that meant:

  * the top-level numbering ran into the teens inside the table, so the body's
    real "1 Scope", "2 Conflicts and Deviations", "3 References" read as a
    numbering restart and were refused;
  * the table's last row, "14.1.5 Editorial", stayed in force, and the Scope's
    requirements were published as clause 14.1.5 - a clause that does not exist;
  * a row's description, "No CSD recommendation is required to conduct
    retroactive PMI testing", was stored as a REQUIREMENT of the standard.

Every text here is synthetic. No client document is quoted.
"""

from __future__ import annotations

import pytest

from app import chunker as ch
from app import db, standards
from app.config import settings
from app.db import connect

NOW = "2026-09-26T00:00:00Z"

#: A two-page change table in the layout the real standards use: the header
#: row reprinted at the top of the second page, bare row numbers and clause
#: numbers in their own columns. Its bare "paragraph" numbers run 1, 3, 4, 8 -
#: past anything the body's first clauses could follow.
CHANGES_P1 = """Summary of Changes
Paragraph
Change Type
Technical Change
1
1
Modification
Scope was re-arranged and clarified.
2
3
Deletion
Removed a reference.
3
4
Addition
Added a definition.
4
8
Deletion
All requirements in section 8 were moved to section 6.
5
5.1.4
Deletion
No design review is required to conduct retroactive testing.
"""
CHANGES_P2 = """Paragraph
Change Type
Technical Change
6
9.2
Modification
Clarified the testing techniques.
7
14.1.5
Editorial
New paragraph number for an existing requirement.
"""
BODY = """1
Scope
This standard defines the minimum mandatory requirements for the identification
of alloy components before they are installed in pressure service.
2
Conflicts and Deviations
Any conflicts between this document and other requirements shall be resolved
in writing by the responsible engineering organisation before work starts.
3
References
All referenced specifications and codes shall apply in their latest edition
unless otherwise stated in the purchase order for the equipment.
"""


def _sections(blocks: list[ch.Block], page: int) -> list[str | None]:
    return [b.section for b in blocks if b.page_start == page]


def _segment(pages: list[tuple[int, str]]) -> list[ch.Block]:
    blocks, _ = ch.segment_document(pages, running=set())
    return blocks


# ---------------------------------------------------------------- chunker

def test_the_body_keeps_its_own_clause_numbers_after_a_change_table():
    """THE DEFECT. Without the region, the table's rows set the numbering and
    the body's 1, 2, 3 are refused - the Scope is filed under a table row."""
    blocks = _segment([(2, CHANGES_P1), (3, CHANGES_P2), (4, BODY)])
    body = [s for s in _sections(blocks, 4) if s]
    assert body[:3] == ["1 Scope", "2 Conflicts and Deviations", "3 References"]
    assert not any(s.startswith(("14.1.5", "5.1.4", "9.2")) for s in body)


def test_the_change_table_is_filed_under_its_own_title():
    blocks = _segment([(2, CHANGES_P1), (3, CHANGES_P2), (4, BODY)])
    table = [b for b in blocks if b.page_start == 2]
    assert [b.section for b in table] == ["Summary of Changes"]
    assert ch.is_revision_history(table[0].section)
    assert "5.1.4" in table[0].text  # kept, searchable - only not a clause


def test_a_change_table_continues_onto_a_page_that_reprints_its_header():
    """Page 3 carries no title, only the reprinted header: it is still the
    table. Read as body, its "14.1.5 Editorial" row would become a clause."""
    blocks = _segment([(2, CHANGES_P1), (3, CHANGES_P2), (4, BODY)])
    assert _sections(blocks, 3) == ["Summary of Changes"]


def test_a_page_that_does_not_reprint_the_header_ends_the_table():
    """The body page is not swallowed: the region ends where the header stops."""
    blocks = _segment([(2, CHANGES_P1), (4, BODY)])
    assert not any(ch.is_revision_history(s) for s in _sections(blocks, 4))


def test_a_history_at_the_back_ends_with_its_page():
    """A dated history, then a page of table figures. The figures belong to
    the clause in force before the history, not to the history."""
    last_body = ("4\nHose and Couplings\n4.1\nFire hose shall meet the listed "
                 "national standard for hose and its care and maintenance.\n"
                 "Revision Summary\n14 May 2011\nMajor revision.\n"
                 "17 June 2012\nMinor revision correcting an omitted column.\n")
    table_page = ("Table 1 continued\nHand type extinguisher rated 4.5 kg and "
                  "wheeled type extinguisher rated 56.7 kg shall be provided.\n")
    blocks = _segment([(10, BODY + last_body), (11, table_page)])
    page10 = [b for b in blocks if b.page_start == 10]
    assert page10[-1].section == "Revision Summary"
    before = page10[-2]
    assert "Fire hose" in before.text and before.section.startswith("4")
    assert _sections(blocks, 11) == [before.section]


def test_the_title_must_be_the_whole_line():
    """ "refer to summary of changes" in a sentence is prose, not a region."""
    text = BODY + "Major revision. Refer to summary of changes.\n"
    blocks = _segment([(4, text)])
    assert not any(ch.is_revision_history(b.section) for b in blocks)
    assert ch.revision_history_regions([(4, text)], set()) == {}


@pytest.mark.parametrize("title", [
    "Summary of Changes", "Document History", "Revision Summary", "Revision History",
    "Record of Revisions", "Change History", "SUMMARY OF CHANGES"])
def test_every_document_control_title_opens_a_region(title):
    regions = ch.revision_history_regions([(2, f"{title}\n1 January 2020\nMajor revision.\n")], set())
    assert regions == {2: (0, title)}


def test_an_ordinary_section_is_not_a_revision_history():
    assert not ch.is_revision_history("5.1.4 Deletion")
    assert not ch.is_revision_history(None)
    assert not ch.is_revision_history("1 Scope")


# ------------------------------------------------------ requirement extractor

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _standard(*chunks: tuple[str | None, str]) -> str:
    doc_id = "std_hist"
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES (?,?,?,1,?,'ready',?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"/tmp/{doc_id}", NOW))
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by,"
            " document_role) VALUES (?,'none','COMPANY_STANDARD')", (doc_id,))
        for n, (section, text) in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
                "page_end,section,text,token_count,content_hash,retrievable,kind)"
                " VALUES (?,?,?,?,1,1,?,?,?,?,1,'prose')",
                (f"{doc_id}:c{n}", doc_id, f"{doc_id}.pdf", n, section, text,
                 len(text.split()), f"hash-{doc_id}-{n}"))
    return doc_id


def test_a_change_description_is_never_stored_as_a_requirement(temp_db):
    """ "No design review is required ..." describes a DELETED paragraph. As a
    requirement it states the opposite of the standard's own rule."""
    doc = _standard(
        ("Summary of Changes", "5.1.4 Deletion No design review is required to "
                               "conduct retroactive testing of installed components."),
        ("1 Scope", "The manufacturer shall perform identification testing on every "
                    "alloy component before it is installed."))
    standards.extract_requirements(doc, allowed_document_ids=frozenset({doc}))
    stored = [dict(r) for r in connect().execute(
        "SELECT clause, source_text FROM standard_requirements")]
    assert [r["clause"] for r in stored] == ["1"]
    assert not any("design review" in r["source_text"] for r in stored)


# ------------------------------------------- a numbered requirement is not a title

def test_a_numbered_requirement_keeps_its_sentence_and_takes_its_number():
    """ "4.4 Design loads shall be as per the building code" passes every
    heading test. Taken as a titled heading, its line became the section label
    and never reached the text - seven real requirements were lost that way.
    It is a numbered paragraph: the number is the clause, the sentence stays."""
    page = ("4\nDesign\n4.1 General\nThe design shall be prepared by a qualified engineer.\n"
            "4.2 Design loads shall be as per the building code for all structures.\n")
    blocks = _segment([(7, page)])
    loads = [b for b in blocks if "Design loads shall" in b.text]
    assert len(loads) == 1 and loads[0].section == "4.2"
    # still a clause line wherever the chunker counts clauses (page kind)
    assert ch.looks_like_heading("4.4 Design loads shall be as per the building code")
    assert ch.count_clause_headings(page) >= 2


def test_a_parenthetical_obligation_is_still_a_titled_heading():
    blocks = _segment([(3, "A.1 Coating system no. 1 (shall be pre-qualified)\n"
                           "Surface preparation to the specified grade is required.\n")])
    assert blocks[0].section == "A.1 Coating system no. 1 (shall be pre-qualified)"


def test_a_change_table_vouches_for_numbers_the_body_prints_bare():
    """A body that prints "4.2" alone above its sentence leaves a gap in the
    4.x group the heading detector sees (4.1, 4.3, 4.4), and the gap refuses
    4.3 and 4.4. The change table names 4.2 - a paragraph of THIS revision -
    so it may vouch for the numbering, without ever setting a section."""
    changes = ("Summary of Changes\nParagraph\nChange Type\n1\n4.2\nModification\n"
               "Clarified the design basis.\n")
    body = ("4\nDesign\n4.1 General\nThe design shall be prepared by a qualified engineer.\n"
            "4.2\nDesign loads shall be taken from the governing building code.\n"
            "4.3 Connections\nConnection details shall allow for erection tolerances.\n"
            "4.4 Openings\nOpenings in panels shall be reinforced at their perimeter.\n")
    blocks = _segment([(2, changes), (3, body)])
    sections = {b.section for b in blocks if b.page_start == 3}
    assert {"4.3 Connections", "4.4 Openings"} <= sections
    assert not any(ch.is_revision_history(b.section) for b in blocks if b.page_start == 3)
