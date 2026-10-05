"""Chunker round 3 (CHUNKER_VERSION 10): three defects proven on a real
18-page engineering standard, reproduced here on INVENTED text only.

1. A numbered clause whose first line reads like a sentence was taken as a
   HEADING: the section label became "12.1.4 When heat treating is performed
   ..., the identification marking must be" and the chunk kept only the tail.
2. A "Summary of Changes" table (Paragraph | Change Type | Technical Change)
   was indexed as requirements, each row filed under "6.5 Addition".
3. The title block on page 1 was excluded as front matter, so the document's
   own title and number could not be found inside it.

Mutations: M2010-M2019, `python scripts/mutation_check.py --only M2010`.
"""

from __future__ import annotations

import pytest

from app import chunker as ch
from app import db
from app.config import settings

NOW = "2026-10-06T00:00:00Z"

#: Enough numbered clauses that 12.1.4 belongs to the document's hierarchy.
LEAD = """12 Marking
12.1 General
This clause describes how every component is marked before it leaves the shop.
12.1.1 Marking shall be applied to every component.
12.1.2 Marks shall be legible.
12.1.3 Marks shall be durable.
"""
SENTENCE = "When heat treating is performed after PMI, the identification marking must be"
TAIL = "recognizable after heat treatment."
NEXT = "12.1.5 Marking shall be applied to every component.\n"


def _segment(pages):
    blocks, _ = ch.segment_document(pages, running=set())
    return blocks


# ------------------------------------------------------ 1. heading vs clause

def test_a_clause_split_by_a_page_break_keeps_its_sentence_in_the_body():
    """THE DEFECT: number alone on its line, the sentence's first part on the
    next, the rest on the next page. The first part became the section."""
    blocks = _segment([(1, LEAD + f"12.1.4\n{SENTENCE}\n"), (2, TAIL + "\n" + NEXT)])
    sections = [b.section for b in blocks]
    assert not any(s and "identification marking" in s for s in sections)
    clause = [b for b in blocks if "identification marking" in b.text]
    assert clause and all(b.section == "12.1.4" for b in clause)
    assert TAIL in " ".join(b.text for b in blocks if b.page_start == 2)


def test_a_clause_opening_in_capitals_on_the_next_line_is_not_a_heading():
    """The lower-case continuation test cannot see this one: the sentence
    carries on with a capital. The line itself must say it is a sentence."""
    text = LEAD + "12.1.4 When heat treating is done, marks must be\nRecognizable afterwards.\n" + NEXT
    blocks = _segment([(1, text)])
    assert not any(b.section and "heat treating" in b.section for b in blocks)
    assert any("heat treating is done" in b.text and b.section == "12.1.4" for b in blocks)


@pytest.mark.parametrize("title", [
    "Marks must be legible after treatment",            # modal verb only
    "Unless otherwise stated, mark every part",         # sentence opener + comma only
    "Marks on welds that are made in the shop",         # linking verb only
    "One two three four five six seven eight nine ten eleven twelve thirteen",  # too long
])
def test_a_title_that_reads_as_a_sentence_is_a_clause(title):
    assert ch._reads_as_sentence(title)
    assert ch._obliges(f"12.1.4 {title}")


@pytest.mark.parametrize("title", [
    "Acronyms", "Marking", "What you must know", "Materials that are covered",
    "Piping and fittings", "Addition of new materials", "Requirements (shall be met)",
])
def test_a_genuine_short_title_is_still_a_heading(title):
    assert not ch._reads_as_sentence(title) or "shall" in title
    assert ch.looks_like_heading(f"4.1 {title}") == f"4.1 {title}"


def test_genuine_headings_keep_their_label_and_a_long_clause_stays_whole():
    text = (LEAD + "12.2 Acronyms\n"
            "Alpha Marking Standard terms are listed here for the reader.\n"
            "12.3\nMarking\nThe marking of every item is described below.\n"
            "12.3.1 Stud bolts for flanges in hydrocarbon service shall be marked "
            "with the grade and the heat number on the head of the bolt.\n")
    blocks = _segment([(1, text)])
    sections = [b.section for b in blocks]
    assert "12.2 Acronyms" in sections
    assert "12.3 Marking" in sections
    whole = [b for b in blocks if "Stud bolts" in b.text]
    assert whole and whole[0].section == "12.3.1"
    assert "heat number on the head of the bolt." in whole[0].text


# -------------------------------------------------- 2. change-table rows

CHANGES = """Summary of Changes
Paragraph Change Type Technical Change
6.5 Addition PMI application responsibilities.
7.2 Deletion Removed the retest rule for small bore pipe.
9.1 Modification Clarified the marking wording.
4.3 Editorial New wording only, no change of meaning.
5.4 Exceptions Added an exception for cast items.
"""


def test_a_number_followed_by_a_change_type_word_is_never_a_section_label():
    for line in ("6.5 Addition PMI application responsibilities.",
                 "7.2 Deletion Removed the retest rule.", "9.1 Modification",
                 "4.3 Editorial New wording."):
        assert ch.looks_like_heading(line) is None
    # a real title that merely starts with the word is still a title
    assert ch.looks_like_heading("6.5 Addition of new materials") == "6.5 Addition of new materials"
    # and "Exceptions" alone is a common genuine title
    assert ch.looks_like_heading("5.4 Exceptions") == "5.4 Exceptions"


def test_the_split_line_form_cannot_build_the_fake_label_either():
    assert ch._split_line_heading(["6.5", "Addition", "PMI application."], 0) == (None, 1)


def test_a_change_table_page_is_classified_revision_history():
    pages = [(1, LEAD), (2, CHANGES), (3, LEAD)]
    kinds = ch.classify_document_pages(pages, 18)
    assert kinds[2] == ch.HISTORY_KIND
    assert kinds[3] == "prose"
    assert ch.HISTORY_KIND not in ch.SEARCHED_PAGE_KINDS


def test_the_table_is_detected_by_its_columns_when_the_title_line_is_missing():
    no_title = CHANGES.replace("Summary of Changes\n", "")
    assert ch.is_change_table_page(no_title)  # "Paragraph" + "Change Type" columns
    assert not ch.is_change_table_page(no_title.replace("Paragraph Change Type", "Item Kind"))


def test_a_continuation_page_with_only_rows_follows_the_history_before_it():
    rows_only = "\n".join(CHANGES.splitlines()[2:]) + "\n"
    pages = [(2, CHANGES), (3, rows_only), (5, rows_only)]
    kinds = ch.classify_document_pages(pages, 18)
    assert kinds[3] == ch.HISTORY_KIND          # page 3 follows page 2
    assert kinds[5] != ch.HISTORY_KIND          # page 5 follows nothing, no cue


def test_a_page_with_the_cue_but_too_few_rows_is_not_a_change_table():
    two_rows = "\n".join(CHANGES.splitlines()[:4]) + "\n"
    assert not ch.is_change_table_page(two_rows)


def test_change_rows_among_many_other_numbered_clauses_are_not_a_change_table():
    """The cue is there and so are three rows - but the page is mostly body."""
    body = "\n".join(f"8.{n} Marking shall be applied to item {n} of the list." for n in range(1, 11))
    assert not ch.is_change_table_page(CHANGES.split("\n5.4")[0] + "\n" + body + "\n")
    assert ch.is_change_table_page(CHANGES)


def test_body_numbered_clauses_are_not_a_change_table():
    body = LEAD + "6.5 Addition of heat treatment steps is allowed by the owner.\n"
    assert not ch.is_change_table_page(body)
    assert ch.classify_document_pages([(2, body)], 18)[2] == "prose"


# ------------------------------------------------------- 3. title page

TITLE = "Engineering Standard\nSTD-A-001\nPositive Material Identification\nAlpha Group\n"


def test_page_one_title_block_becomes_one_searchable_chunk():
    assert ch.classify_page(TITLE, 1, 18) == "frontmatter"  # the premise
    kinds = ch.classify_document_pages([(1, TITLE), (2, LEAD)], 18)
    assert kinds[1] == ch.TITLE_KIND
    blocks = _segment_with_kinds([(1, TITLE), (2, LEAD)], kinds)
    title = [b for b in blocks if b.page_start == 1]
    assert len(title) == 1 and title[0].kind == "prose"
    assert title[0].section == "title page"
    assert "Positive Material Identification" in title[0].text
    chunks = ch.build_chunks(blocks)
    first = [c for c in chunks if c.section == "title page"]
    assert len(first) == 1 and first[0].kind in ch.RETRIEVABLE_KINDS


def _segment_with_kinds(pages, kinds):
    blocks, _ = ch.segment_document(pages, running=set(), page_kinds=kinds)
    return blocks


def _title_kind(page_text, page_no=1):
    return ch.classify_document_pages([(page_no, page_text), (page_no + 1, LEAD)], 18)[page_no]


def test_a_contents_page_never_becomes_a_title_page():
    contents = "Contents\nScope 3\nReferences 4\nDefinitions 5\n"
    assert ch.classify_page(contents, 1, 18) == "frontmatter"  # the premise
    assert _title_kind(contents) != ch.TITLE_KIND
    dotted = "Engineering Standard\nScope ........ 3\nReferences ........ 4\n"
    assert ch.classify_page(dotted, 1, 18) == "frontmatter"
    assert _title_kind(dotted) != ch.TITLE_KIND


def test_a_books_credits_page_never_becomes_a_title_page():
    credits = "Alpha Marking Standard\nISBN 000-0\nEditor in chief A. Person\n"
    assert ch.classify_page(credits, 1, 18) == "frontmatter"
    assert _title_kind(credits) != ch.TITLE_KIND
    # a plain rights line on a standard's cover is allowed
    assert _title_kind(TITLE + "All rights reserved\n") == ch.TITLE_KIND


def test_the_title_page_is_page_one_only():
    assert ch.classify_document_pages([(2, TITLE)], 18)[2] == "frontmatter"


def test_a_long_first_page_is_not_a_title_page():
    wordy = TITLE + "All rights reserved\n" + " ".join(["word"] * 70) + "\n"
    assert ch.classify_page(wordy, 1, 18) == "frontmatter"  # the premise
    assert ch._is_title_page(TITLE, 1)
    assert not ch._is_title_page(wordy, 1)
    many = "\n".join(["Alpha"] * (ch._TITLE_PAGE_MAX_LINES + 1))
    assert not ch._is_title_page(many, 1)


# ------------------------------------------- recorded through chunk_document

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def test_the_change_table_is_excluded_with_a_recorded_reason(temp_db):
    doc = "std_r3"
    body = LEAD * 3
    pages = [(1, TITLE), (2, CHANGES), (3, body)]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'chunking',3,?)",
            (doc, "std.pdf", "sha-r3", "/tmp/std", NOW))
        for n, text in pages:
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)", (doc, n, text, len(text)))
    ch.chunk_document(doc)
    conn = db.connect()
    hist = conn.execute("SELECT * FROM exclusions WHERE document_id=? AND page_start=2",
                        (doc,)).fetchall()
    assert [r["rule"] for r in hist] == ["page_classified_revision_history"]
    assert "not a requirement" in hist[0]["reason"]
    assert "6.5 Addition" in hist[0]["text_sample"]      # kept, visible, not dropped
    assert hist[0]["clause_headings"] == 0
    rows = conn.execute("SELECT kind, retrievable, section, text FROM chunks"
                        " WHERE document_id=? AND page_start=2", (doc,)).fetchall()
    assert rows and all(r["retrievable"] == 0 for r in rows)
    assert not any((r["section"] or "").startswith("6.5") for r in rows)
    title = conn.execute("SELECT retrievable, section FROM chunks WHERE document_id=?"
                         " AND page_start=1", (doc,)).fetchall()
    assert [(t["retrievable"], t["section"]) for t in title] == [(1, "title page")]
    assert conn.execute("SELECT COUNT(*) FROM exclusions WHERE document_id=? AND page_start=1",
                        (doc,)).fetchone()[0] == 0
