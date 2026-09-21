"""Reading a standard's discipline from its own cover page.

WHY NOT THE LETTER IN THE DOCUMENT NUMBER, which is the rule anyone would
reach for first: measured against this corpus, SAES-A spans eleven committees,
L spans five, P six, K four. A letter map would give every one of those a
single confident value and `applicability` would then select standards by a
discipline the document does not belong to. The header states the answer, so
the header is read.

THE SHAPE OF EVERY TEST HERE IS THE SAME: a real string taken from the corpus,
and the value that must come out of it. Four forms exist in the 272 standards
and all four are represented - the ordinary one, the line-wrapped one, the one
with no "Committee" in it, and the revision-history prose that MUST NOT parse.

That last one is the test that matters. `applicability`'s docstring says a NULL
on either side is not a match, so a missing discipline WEAKENS selection while
a wrong one MISDIRECTS it - and the prose form names the SUPERSEDED committee
first, so a parser that accepted it would confidently record the wrong owner.
"""

from __future__ import annotations

import pytest

from app import classification, db, standards
from app.config import settings
from app.db import connect

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _standard(doc_id: str, *chunk_texts: str) -> str:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES (?,?,?,1,?,'ready',?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"/tmp/{doc_id}", NOW))
        for n, text in enumerate(chunk_texts):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
                "page_end,text,token_count,content_hash,retrievable,kind)"
                " VALUES (?,?,?,?,1,1,?,?,?,1,'prose')",
                (f"{doc_id}:c{n}", doc_id, f"{doc_id}.pdf", n, text,
                 len(text.split()), f"hash-{doc_id}-{n}"))
    return doc_id


def discipline_of(doc_id: str) -> str | None:
    row = connect().execute(
        "SELECT discipline FROM document_classification WHERE document_id = ?",
        (doc_id,)).fetchone()
    return row["discipline"] if row else None


# ------------------------------------------------------- the four real forms

def test_the_ordinary_header_yields_the_committee():
    assert standards.responsibility_in(
        "Saudi Aramco: Company General Use Engineering Standard 16 February 2021"
        " SAES-A-105 Noise Control"
        " Document Responsibility: Health Protection Standards Committee"
    ) == ["Health Protection Standards Committee"]


def test_a_header_wrapped_across_a_line_break_still_yields_the_whole_name():
    """Verbatim from SAES-P-100, one of nine in the corpus that wrap.

    A pattern that stopped at the newline read all nine as having no value -
    and "no value" is indistinguishable from a document that genuinely has no
    header, so the loss would have been invisible in the coverage count.
    """
    assert standards.responsibility_in(
        "Document Responsibility: Electrical Systems Designs and Automation"
        " Standards \nCommittee"
    ) == ["Electrical Systems Designs and Automation Standards Committee"]


def test_a_value_that_does_not_end_in_committee_is_still_read():
    """SAES-A-302, the only one in 272. It ends at the line, not at a word."""
    assert standards.responsibility_in(
        "Aviation Fuel Quality Assurance Design Requirement \n"
        "Document Responsibility:  Aviation Fuel Quality  \n \n \nContents "
    ) == ["Aviation Fuel Quality"]


def test_revision_history_prose_is_never_parsed():
    """THE ONE THAT MATTERS, verbatim from SAES-Q-014.

    "transfer document responsibility FROM the Offshore Structures Standards
    Committee TO the Geotechnical Standards Committee" - the first committee
    named is the one that no longer owns it. A parser that accepted this form
    would record the superseded owner as the discipline, confidently and
    wrongly, on four documents.

    The colon is what separates the header from the prose, and this asserts the
    prose yields NOTHING rather than asserting the header yields something -
    per M82, an "is not extracted" claim has to be made against an input the
    parser really ran on, so the same call is made on a string that DOES parse
    directly below.
    """
    prose = ("2) Editorial revision to transfer document responsibility from the"
             " Offshore Structures Standards Committee to the Geotechnical"
             " Standards Committee 17 October 2019")

    assert standards.responsibility_in(prose) == []
    # THE CODE PATH RAN. Same function, same call, one character different -
    # a colon - and it yields a value. Without this line the assertion above
    # would also pass against a parser that returns [] for everything.
    assert standards.responsibility_in(prose.replace(
        "document responsibility from the", "Document Responsibility: ")
    ) == ["Offshore Structures Standards Committee"]


def test_a_value_that_ran_into_the_issue_date_is_refused_rather_than_stored():
    """A cut that overran is worse than no value: it stores a string no filter
    matches while the document reads as classified."""
    assert standards.responsibility_in(
        "Document Responsibility:  Aviation Fuel Quality 15 March 2021 SAES-A-302"
    ) == []


# ------------------------------------------------------------ per document

def test_the_most_frequent_header_wins_over_a_single_garbled_page():
    """The cover block repeats; one bad page must not decide for the standard.

    THE GARBLED PAGE IS FIRST, deliberately. With it last, "the first value
    seen" and "the most frequent value" are the same answer, and the test
    passes against an implementation that simply takes the first - which is
    what the first version of this test did, and mutation M87 said so.
    """
    _standard(
        "doc_a",
        "Document Responsibility: Pip ing Standards Committee",
        "Document Responsibility: Piping Standards Committee",
        "Document Responsibility: Piping Standards Committee",
    )
    assert standards.responsibility_of("doc_a") == "Piping Standards Committee"


def test_two_committees_named_equally_often_yields_nothing():
    """A tie is a document this parser does not understand, and NULL says so.

    Picking either would be a coin toss recorded as a fact.
    """
    _standard(
        "doc_tie",
        "Document Responsibility: Piping Standards Committee",
        "Document Responsibility: Welding Standards Committee",
    )
    assert standards.responsibility_of("doc_tie") is None


def test_a_document_with_no_header_yields_nothing():
    _standard("doc_none", "1.1 Scope. This standard shall apply to all vessels.")
    assert standards.responsibility_of("doc_none") is None


# ------------------------------------------------------------- the backfill

def test_the_backfill_stores_what_it_read_and_names_what_it_could_not():
    _standard("doc_1", "Document Responsibility: Piping Standards Committee")
    _standard("doc_2", "Document Responsibility: Welding Standards Committee")
    _standard("doc_3", "no header here at all")

    result = standards.backfill_disciplines()

    assert result["documents"] == 3
    assert sorted(result["set"]) == ["doc_1.pdf", "doc_2.pdf"]
    # NAMED, not counted. A human has to classify these by hand, and a count
    # tells them how much work there is without telling them what it is.
    assert result["without"] == ["doc_3.pdf"]
    assert discipline_of("doc_1") == "Piping Standards Committee"
    assert discipline_of("doc_3") is None


def test_the_backfill_never_overwrites_a_discipline_a_person_set():
    """Same rule as the role fix, and it defaults ON here because the caller is
    a whole-corpus backfill that somebody will re-run."""
    _standard("doc_1", "Document Responsibility: Piping Standards Committee")
    classification.set_discipline("doc_1", "Process (AXENS)")

    result = standards.backfill_disciplines()

    assert discipline_of("doc_1") == "Process (AXENS)"
    assert result["set"] == []
    assert result["unchanged"] == ["doc_1.pdf"]


def test_the_backfill_leaves_equipment_type_alone():
    """No published scheme exists to parse it from. A guess in a column that
    reads like a fact is worse than an empty column."""
    _standard("doc_1", "Document Responsibility: Piping Standards Committee")

    standards.backfill_disciplines()

    row = connect().execute(
        "SELECT equipment_type FROM document_classification WHERE document_id='doc_1'"
    ).fetchone()
    assert row["equipment_type"] is None


def test_set_discipline_refuses_a_blank_value():
    """An empty string makes a document look classified while matching nothing.
    NULL is the honest value for "not known"."""
    _standard("doc_1", "x")
    with pytest.raises(ValueError):
        classification.set_discipline("doc_1", "   ")


def test_set_discipline_reports_whether_it_changed_anything():
    _standard("doc_1", "x")
    assert classification.set_discipline("doc_1", "Piping") is True
    assert classification.set_discipline("doc_1", "Piping") is False
    assert classification.set_discipline("doc_1", "Welding", only_if_unset=True) is False
    assert classification.set_discipline("doc_1", "Welding", only_if_unset=False) is True
    assert discipline_of("doc_1") == "Welding"
