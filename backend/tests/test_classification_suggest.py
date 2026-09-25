"""The three suggestion tiers, and the NULL that is a real answer.

TIER ORDER IS THE WHOLE DESIGN. A register hit is the client's own official
answer; a filename pattern is this system's inference. When both are available
the register wins, and when neither is the answer is NULL rather than a guess -
a discipline inferred from one word in a filename routes searches confidently
to the wrong place, and nobody discovers it by reading the value.

Nothing here reads the client's register or the real corpus. The register rows
are written directly, which is also what lets each tier be exercised in
isolation: the importer is tested separately and is not a dependency of these.
"""

from __future__ import annotations

import pytest

from app import classification, db
from app.config import settings
from app.db import connect

REVISION = "rev-T"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _register(title: str, doc_type: str, discipline: str) -> str:
    reg_id = classification.new_id("reg")
    with connect() as conn:
        conn.execute(
            "INSERT INTO deliverables_register (id, doc_type, discipline,"
            " vendor, title, register_revision, imported_at)"
            " VALUES (?,?,?,NULL,?,?, '2026-09-07T00:00:00Z')",
            (reg_id, doc_type, discipline, title, REVISION))
    return reg_id


def _subject(name: str, kind: str = "system") -> str:
    sub_id = classification.new_id("sub")
    with connect() as conn:
        conn.execute(
            "INSERT INTO subjects (id, name, kind, register_revision)"
            " VALUES (?,?,?,?)", (sub_id, name, kind, REVISION))
    return sub_id


@pytest.fixture
def vocabulary():
    """One register row, a handful of subjects, and Project-wide."""
    ids = {
        "hot_oil": _subject("hot oil"),
        "firewater": _subject("firewater"),
        "substation": _subject("substation"),
        "facility_a": _subject("Example Bay", "facility"),
        "project_wide": _subject(classification.PROJECT_WIDE, "project_wide"),
    }
    ids["register"] = _register(
        "Hot Oil System P&ID", "Drawing", "Process (AXENS)")
    ids["philosophy"] = _register(
        "Overall Project Execution Philosophy", "Document", "Process")
    ids["criteria"] = _register(
        "HVAC Design Criteria", "Document", "Mechanical")
    return ids


# ------------------------------------------------------- TIER 1: the register


def test_a_register_match_takes_type_and_discipline_from_the_client(vocabulary):
    """TIER 1. AUTHORITATIVE. The register is the client's official
    deliverables list, so a matched row's type and discipline are their answer
    and not this system's inference."""
    got = classification.suggest("Hot Oil System P&ID.pdf", "", REVISION)

    assert got.doc_type == "Drawing"
    assert got.discipline == "Process (AXENS)"
    assert got.register_id == vocabulary["register"]
    assert got.source["doc_type"] == classification.SOURCE_REGISTER
    assert got.source["discipline"] == classification.SOURCE_REGISTER


@pytest.mark.parametrize("filename", [
    "Hot Oil System P&ID.pdf",
    "hot oil system p&id.pdf",
    "HOT-OIL-SYSTEM-PID.pdf",
    "  Hot   Oil  System  P&ID  ",
    "Hot_Oil_System_PID.PDF",
])
def test_the_match_is_on_case_punctuation_and_whitespace_only(filename,
                                                              vocabulary):
    """NORMALISED, NEVER ON MEANING. A register title and an uploaded filename
    differ in punctuation and capitalisation constantly, and matching those is
    the point."""
    got = classification.suggest(filename, "", REVISION)
    assert got.discipline == "Process (AXENS)", filename


def test_a_near_miss_is_not_a_match(vocabulary):
    """No fuzzy distance and no partial credit. A near-miss would attach the
    wrong deliverable's OFFICIAL discipline to a document, which is worse than
    leaving it NULL - the value would carry the register's authority while
    being about a different document."""
    got = classification.suggest("Hot Oil System P&ID Rev B.pdf", "", REVISION)
    assert got.discipline is None, got
    assert got.doc_type is None
    assert got.register_id is None


def test_the_register_beats_the_pattern(vocabulary):
    """THE TIER ORDER, asserted directly. The filename says P&ID, which the
    pattern tier would also find; the register says Drawing / Process (AXENS),
    and that is what the type and discipline come from."""
    got = classification.suggest(
        "Hot Oil System P&ID.pdf",
        "This document is a PHILOSOPHY for the firewater system.", REVISION)

    # From the register, not from the words on the page.
    assert got.doc_type == "Drawing"
    assert got.discipline == "Process (AXENS)"
    assert got.source["doc_type"] == classification.SOURCE_REGISTER


# ------------------------------------------------------- TIER 2: the patterns


def test_a_title_with_two_subjects_yields_two(vocabulary):
    """MANY, NOT ONE. A firewater layout for the substation has two subjects,
    and picking the "best" would make the document appear under one and vanish
    from the other - handing a reader an incomplete comparison set with no sign
    that it was incomplete."""
    got = classification.suggest(
        "Firewater Ring Main Layout - Substation.pdf", "", REVISION)

    assert set(got.subject_ids) == {vocabulary["firewater"],
                                    vocabulary["substation"]}, got.subject_ids
    assert got.source["subjects"] == classification.SOURCE_PATTERN
    # ...and no discipline was invented from those words.
    assert got.discipline is None


def test_a_subject_in_the_first_page_text_counts(vocabulary):
    """The first page is matched as well as the title: a drawing whose
    filename is a document number still says what it is about on its face."""
    got = classification.suggest(
        "DWG-11223.pdf", "FIREWATER RING MAIN — Example Bay terminal", REVISION)
    assert set(got.subject_ids) == {vocabulary["firewater"],
                                    vocabulary["facility_a"]}


@pytest.mark.parametrize("text,expected", [
    ("Hot Oil P&ID sheet 1", "P&ID"),
    ("Pump Datasheet rev A", "DATASHEET"),
    ("Substation Single Line Diagram", "SLD"),
    ("Firewater Pump House Plot Plan", "PLOT PLAN"),
    ("Operating Philosophy", "PHILOSOPHY"),
    ("Piping Material Specification", "SPECIFICATION"),
    ("Flare Header Sizing Calculation", "CALCULATION"),
    ("Produced Water Treatment Report", "REPORT"),
    ("Onshore Facility Scope of Work", "SCOPE OF WORK"),
])
def test_the_document_class_is_recognised_for_the_chip(text, expected,
                                                       vocabulary):
    got = classification.suggest(text + ".pdf", "", REVISION)
    assert got.doc_class == expected, (text, got.doc_class)


def test_the_longest_class_pattern_wins(vocabulary):
    """"Scope of Work" is not "Work", and "Plot Plan" is not "Plan"."""
    assert classification.suggest("Scope of Work.pdf", "", REVISION).doc_class \
        == "SCOPE OF WORK"
    assert classification.suggest("Plot Plan.pdf", "", REVISION).doc_class \
        == "PLOT PLAN"


def test_the_class_is_never_a_filter_axis():
    """MEASURED DECISION: 88% derivable and nobody searches by it, so it is
    recorded and shown as a chip. Asserted structurally - `ScopeFilter` has no
    field for it - because a filter axis added later would silently change
    what a saved filter means."""
    assert not hasattr(classification.ScopeFilter(), "doc_class")
    assert not hasattr(classification.ScopeFilter(), "classes")


def test_a_subject_is_not_matched_inside_another_word(vocabulary):
    """THE RESTRICTION ON THE TIGHT NORMALISATION, as an assertion.

    `normalise_tight` removes separators so "HOT-OIL-SYSTEM-PID" can equal
    "Hot Oil System P&ID". Used for SUBSTRING search it would be dangerous:
    tight("omega values") is "omegavalues", which contains "meg". So subject
    matching uses the spaced form with word boundaries, and this pins it -
    a future change to tight matching for subjects fails here rather than
    quietly attaching a MEG subject to a document about omega values.
    """
    meg = _subject("MEG")
    got = classification.suggest("Omega Values Table.pdf",
                                 "omega values for the vessel", REVISION)
    assert meg not in got.subject_ids, (
        "MEG was matched inside another word - subject matching has started "
        "using the tight normalisation")
    assert got.subject_ids == ()

    # ...and MEG still matches when it is genuinely there.
    hit = classification.suggest("MEG Regeneration Package.pdf", "", REVISION)
    assert meg in hit.subject_ids


# ------------------------------------------------ the one inference: Project-wide


def test_a_philosophy_with_no_subject_term_yields_project_wide(vocabulary):
    """THE ONE INFERENCE, and it needs all three conditions: a register hit,
    no subject term found, and the document reading as a philosophy / design
    basis / criteria / overall. That combination is what the register's 18%
    project-wide group looks like."""
    got = classification.suggest(
        "Overall Project Execution Philosophy.pdf", "", REVISION)

    assert got.subject_ids == (vocabulary["project_wide"],)
    assert got.source["subjects"] == classification.SOURCE_REGISTER
    assert got.doc_class == "PHILOSOPHY"
    assert got.discipline == "Process"


def test_design_criteria_also_reads_as_project_wide(vocabulary):
    got = classification.suggest("HVAC Design Criteria.pdf", "", REVISION)
    assert got.subject_ids == (vocabulary["project_wide"],)


def test_a_philosophy_that_names_a_subject_gets_the_subject_not_project_wide(
        vocabulary):
    """A found subject term BEATS the inference. "MEG Injection Philosophy" is
    about MEG; calling it Project-wide would put it among the baselines
    everything else is compared against, which is expensive to be wrong
    about."""
    _register("Firewater Injection Philosophy", "Document", "Process")
    got = classification.suggest(
        "Firewater Injection Philosophy.pdf", "", REVISION)

    assert got.subject_ids == (vocabulary["firewater"],)
    assert got.source["subjects"] == classification.SOURCE_PATTERN


def test_a_philosophy_with_no_register_hit_gets_no_subject(vocabulary):
    """Without a register hit the inference would be a guess. A wrong
    Project-wide is expensive: gap analysis holds those as the documents
    everything else is compared against."""
    got = classification.suggest(
        "Some Vendor Operating Philosophy.pdf", "", REVISION)

    assert got.subject_ids == (), got.subject_ids
    assert got.doc_class == "PHILOSOPHY"      # the chip still fires
    assert got.discipline is None             # but nothing was invented


# ------------------------------------------------------------ TIER 3: NULL


def test_nothing_matched_gives_every_field_null(vocabulary):
    """A REAL ANSWER, and the needs-classification queue is built from it."""
    got = classification.suggest("IMG_20260907_113244.pdf", "", REVISION)

    assert got.doc_type is None
    assert got.discipline is None
    assert got.doc_class is None
    assert got.register_id is None
    assert got.subject_ids == ()
    assert got.is_empty
    assert got.source == {"doc_type": classification.SOURCE_NONE,
                          "discipline": classification.SOURCE_NONE}


def test_a_discipline_is_never_guessed_from_one_word(vocabulary):
    """The register has "Process (AXENS)" and "Process". A filename
    containing the word "process" must not acquire either."""
    got = classification.suggest("process notes scan.pdf", "", REVISION)
    assert got.discipline is None, got.discipline


def test_no_register_loaded_means_no_suggestion_at_all():
    """With no register there is no vocabulary to match against, so the honest
    answer is NULL rather than a pattern-only guess at a discipline."""
    got = classification.suggest("Hot Oil System P&ID.pdf", "", None)
    assert got.doc_type is None and got.discipline is None
    assert got.subject_ids == ()
    # The class chip is text-only and still works - it needs no register.
    assert got.doc_class == "P&ID"


# --------------------------------------------- a suggestion stays a suggestion


def test_a_suggestion_is_never_auto_confirmed(vocabulary):
    """NOTHING HERE AUTO-CONFIRMS. A wrong classification misroutes searches
    for everyone, so confirmation needs a role that answers for everyone."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES ('d1','Hot Oil System P&ID.pdf','s',1,"
            "'/tmp/d1','ready','2026-09-07T00:00:00Z')")

    got = classification.suggest("Hot Oil System P&ID.pdf", "", REVISION)
    classification.write_suggestion("d1", got, suggested_by="register")

    stored = classification.of_document("d1")
    assert stored["confirmed_by"] is None
    assert stored["confirmed_at"] is None
    assert stored["confirmed"] is False
    assert all(s["confirmed_by"] is None for s in stored["subjects"])


def test_a_re_suggest_never_un_confirms_a_human_decision(vocabulary):
    """Re-running ingestion must not quietly undo what an administrator
    decided - otherwise a re-index would silently empty the confirmed set."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES ('d2','x.pdf','s2',1,'/tmp/d2',"
            "'ready','2026-09-07T00:00:00Z')")
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('admin1','a@example.test','a','h','2026-09-07T00:00:00Z')")

    classification.confirm("d2", doc_type="Document", discipline="Piping",
                           doc_class=None,
                           subject_ids=[vocabulary["firewater"]],
                           confirmed_by="admin1")

    classification.write_suggestion(
        "d2", classification.Suggestion(doc_type="Drawing",
                                        discipline="Civil",
                                        subject_ids=(vocabulary["hot_oil"],)),
        suggested_by="pattern")

    after = classification.of_document("d2")
    assert after["confirmed_by"] == "admin1"
    assert after["discipline"] == "Piping", "a re-suggest overwrote a decision"
    assert [s["id"] for s in after["subjects"]] == [vocabulary["firewater"]]
