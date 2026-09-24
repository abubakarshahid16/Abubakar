"""Standards inventory (B5 part 2): family, licence status, cover-page
backfill, and which held standards a submittal cites.

Mutations: `python scripts/mutation_check.py --phase 61`.
"""
from __future__ import annotations

import pytest

from app import db, keyword, standards_inventory, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename,
             f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def _scope(*ids): return frozenset(ids)


# ===================================================== family_from_identifier

@pytest.mark.parametrize("identifier,family", [
    ("SAES-D-001", "SAES"),
    ("02-SAMSS-014", "SAMSS"),      # number-first spelling - THE MUTATION TARGET
    ("API 610", "API"),
    ("ASME B31.3", "ASME"),
    ("ASTM A516", "ASTM"),
    ("ISO 15156", "ISO"),
    ("IEC 60079", "IEC"),
    ("NFPA 70", "NFPA"),
    ("NACE MR0175", "NACE"),
    ("KOC-ME-001", "KOC"),
])
def test_a_known_family_is_read_from_the_identifier(identifier, family):
    assert standards_inventory.family_from_identifier(identifier) == family


def test_an_unrecognised_identifier_is_other_not_unknown():
    """OTHER means "looked, found nothing"; UNKNOWN means "have not looked".
    Given real text, this function has always looked."""
    assert standards_inventory.family_from_identifier("TAG-1234-PV") == "OTHER"
    assert standards_inventory.family_from_identifier("") == "OTHER"
    assert standards_inventory.family_from_identifier(None) == "OTHER"


# =================================================== default_licence_status

def test_a_held_standard_is_always_held_regardless_of_family():
    for family in standards_inventory.FAMILIES:
        assert standards_inventory.default_licence_status(
            family, held=True) == standards_inventory.LICENCE_HELD


@pytest.mark.parametrize("family", sorted(standards_inventory.COPYRIGHTED_FAMILIES))
def test_a_missing_copyrighted_standard_is_licensed_not_held(family):
    """THE MUTATION TARGET: a missing API/ASME/ASTM/ISO/IEC/NFPA/NACE standard
    must never default to `held` or to silent `unknown` - the owner's
    instruction is explicit that these need a supplied licence."""
    assert standards_inventory.default_licence_status(
        family, held=False) == standards_inventory.LICENCE_LICENSED_NOT_HELD


@pytest.mark.parametrize("family", ["SAES", "SAMSS", "KOC", "OTHER"])
def test_a_missing_own_or_unrecognised_standard_is_unknown_not_licensed_not_held(family):
    """A missing SAES/SAMSS/KOC standard is not a copyright gap - this system
    has no basis to claim a licence position, so it must not borrow the
    copyrighted-family answer."""
    assert standards_inventory.default_licence_status(
        family, held=False) == standards_inventory.LICENCE_UNKNOWN


# ===================================================== extract_cover_metadata

def _page(page_no: int, text: str) -> dict:
    return {"page_no": page_no, "text": text}


def test_a_document_number_and_revision_are_read_with_their_page_and_quote():
    pages = [
        _page(1, "SAUDI ARAMCO\nENGINEERING STANDARD\nSAES-D-001\n"
                 "Design Criteria - Piping Systems"),
        _page(2, "Revision: 03\nEffective Date: 15 March 2023"),
    ]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.document_number is not None
    assert meta.document_number.value == "SAES-D-001"
    assert meta.document_number.page == 1
    assert "SAES-D-001" in meta.document_number.quote
    assert meta.revision is not None
    assert meta.revision.value == "03"
    assert meta.revision.page == 2


@pytest.mark.parametrize("label,date_text", [
    ("Issue Date", "18 August 2019"),
    ("Effective Date", "18 August 2019"),
])
def test_an_issue_or_effective_date_is_read_with_its_page_and_quote(label, date_text):
    pages = [_page(1, f"SAES-A-007\n{label}:   {date_text}")]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.effective_date is not None
    assert meta.effective_date.value == date_text
    assert meta.effective_date.page == 1


def test_previous_issue_is_not_read_as_the_effective_date():
    """THE MUTATION TARGET: "Previous Issue" names the PRIOR revision's
    date, a real date but the wrong one - found on the real corpus's newer
    cover format ("Previous Issue: 1 January 2018   Next Planned Update:
    18 August 2024") which states no bare revision number at all. Recording
    the previous issue's date as if it were the current effective date
    would be a wrong claim, not a missing one."""
    pages = [_page(1, "Previous Issue:  1 January 2018    "
                      "Next Planned Update:  18 August 2024")]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.effective_date is None


def test_next_planned_update_is_not_read_as_the_effective_date():
    """THE MUTATION TARGET: "Next Planned Update" is a FUTURE date that has
    not happened yet - reading it as the effective date would claim a
    revision that does not exist yet."""
    pages = [_page(1, "Next Planned Update:  18 August 2024")]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.effective_date is None


def test_a_two_digit_series_number_is_zero_padded_to_three():
    pages = [_page(1, "SAES-A-4 General Requirements")]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.document_number.value == "SAES-A-004"


def test_no_recognisable_number_on_the_cover_pages_stays_unknown():
    """THE MUTATION TARGET: a document with no SAES number on its first two
    pages must report None, never invent one from a later page or a
    filename."""
    pages = [
        _page(1, "GENERAL NOTES\nSee attached drawings for details."),
        _page(2, "This page intentionally left blank."),
        _page(3, "SAES-D-001 is mentioned here but this is page 3."),
    ]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.document_number is None
    assert meta.revision is None


@pytest.mark.parametrize("text", [
    "This standard is currently under REVIEW by the discipline committee.",
    "The attached drawing was REVISED after the site inspection.",
    "Management REVIEW meeting scheduled for next quarter.",
])
def test_an_ordinary_english_word_containing_rev_is_not_read_as_a_revision(text):
    """THE MUTATION TARGET: real false positives found on the 272-standard
    corpus - "REVIEW"/"REVISED" are not "REV" plus a revision code."""
    meta = standards_inventory.extract_cover_metadata([_page(1, text)])
    assert meta.revision is None


def test_the_plural_revisions_in_ordinary_prose_is_not_read_as_a_revision():
    """THE MUTATION TARGET: a real false positive found on the 272-standard
    corpus - "revisions, addenda and supplements unless superseded" was
    read as revision "S", the plural's own trailing letter, because
    "revision" is a PREFIX of "revisions" and nothing required a boundary
    after it."""
    meta = standards_inventory.extract_cover_metadata(
        [_page(1, "This standard reflects revisions, addenda and "
                  "supplements unless superseded by a later issue.")])
    assert meta.revision is None


def test_a_revision_history_tables_to_column_is_not_read_as_the_revision():
    """A genuine revision-log table header ("FROM REV TO REV") matches the
    REV pattern just as legitimately as a real "Rev: C" statement - "TO"
    must be rejected as a revision code even though it is syntactically
    identical."""
    meta = standards_inventory.extract_cover_metadata(
        [_page(1, "REVISION HISTORY\nFROM REV TO REV DESCRIPTION")])
    assert meta.revision is None


def test_a_body_reference_on_a_later_page_is_not_read_as_the_covers_own_number():
    """Only the first two pages are read - a standard with no number on its
    own cover, but a body citing another standard on page 3, must report
    UNKNOWN rather than picking up the page-3 reference. THE MUTATION
    TARGET: widening the page window to 3 would read SAES-Z-999 as this
    document's own number."""
    pages = [
        _page(1, "GENERAL NOTES\nSee attached drawings for details."),
        _page(2, "This page intentionally left blank."),
        _page(3, "SAES-Z-999 governs this special case."),
    ]
    meta = standards_inventory.extract_cover_metadata(pages)
    assert meta.document_number is None


# ==================================================== backfill_cover_metadata

def _doc_with_pages(doc_id: str, filename: str, pages: list[tuple[int, str]]) -> str:
    _doc(doc_id, filename, "COMPANY_STANDARD")
    with db.connect() as conn:
        for page_no, text in pages:
            conn.execute(
                "INSERT INTO pages"
                " (document_id, page_no, text, char_count, batch_no)"
                " VALUES (?, ?, ?, ?, 0)", (doc_id, page_no, text, len(text)))
    return doc_id


def test_a_document_number_is_backfilled_with_its_page_and_family():
    _doc_with_pages("std_1", "std1.pdf", [
        (1, "SAES-D-001 Design Criteria"), (2, "Revision: 02")])
    result = standards_inventory.backfill_cover_metadata("std_1")
    assert result["changed"] is True
    assert result["document_number"] == "SAES-D-001"
    assert result["document_number_page"] == 1
    assert result["revision"] == "02"
    row = dict(db.connect().execute(
        "SELECT document_number, revision, standard_family,"
        " document_number_evidence FROM document_classification"
        " WHERE document_id = 'std_1'").fetchone())
    assert row["document_number"] == "SAES-D-001"
    assert row["standard_family"] == "SAES"
    assert "SAES-D-001" in row["document_number_evidence"]


def test_an_already_confirmed_document_number_is_never_overwritten():
    """THE MUTATION TARGET: a human-confirmed or previously-set field must
    survive a re-run even when the cover page parses to something else."""
    _doc_with_pages("std_2", "std2.pdf", [(1, "SAES-Z-999 Different Number")])
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET document_number = ?"
                     " WHERE document_id = ?", ("SAES-D-001", "std_2"))
    result = standards_inventory.backfill_cover_metadata("std_2")
    assert "document_number" not in result
    row = dict(db.connect().execute(
        "SELECT document_number FROM document_classification"
        " WHERE document_id = 'std_2'").fetchone())
    assert row["document_number"] == "SAES-D-001"


def test_an_effective_date_is_backfilled_from_the_cover():
    _doc_with_pages("std_4", "std4.pdf", [
        (1, "SAES-A-007"), (2, "Issue Date:   18 August 2019")])
    result = standards_inventory.backfill_cover_metadata("std_4")
    assert result["effective_date"] == "18 August 2019"
    assert result["effective_date_page"] == 2
    row = dict(db.connect().execute(
        "SELECT effective_date, effective_date_evidence"
        " FROM document_classification WHERE document_id = 'std_4'").fetchone())
    assert row["effective_date"] == "18 August 2019"
    assert "Issue Date" in row["effective_date_evidence"]


def test_an_already_set_effective_date_is_never_overwritten():
    _doc_with_pages("std_5", "std5.pdf", [
        (1, "SAES-A-007"), (2, "Issue Date:   18 August 2019")])
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET effective_date = ?"
                     " WHERE document_id = ?", ("1 January 2000", "std_5"))
    result = standards_inventory.backfill_cover_metadata("std_5")
    assert "effective_date" not in result
    row = dict(db.connect().execute(
        "SELECT effective_date FROM document_classification"
        " WHERE document_id = 'std_5'").fetchone())
    assert row["effective_date"] == "1 January 2000"


def test_no_cover_evidence_leaves_the_field_null_and_reports_no_change():
    _doc_with_pages("std_3", "std3.pdf", [(1, "No recognisable number here.")])
    result = standards_inventory.backfill_cover_metadata("std_3")
    assert result["changed"] is False
    row = dict(db.connect().execute(
        "SELECT document_number FROM document_classification"
        " WHERE document_id = 'std_3'").fetchone())
    assert row["document_number"] is None


# ========================================================== inventory_rows

def test_a_held_standard_reports_family_and_held_licence_status():
    std = _doc("std_d001", "SAES-D-001.pdf", "COMPANY_STANDARD",
               document_number="SAES-D-001", discipline="Piping")
    rows = standards_inventory.inventory_rows(allowed_document_ids=_scope(std))
    assert len(rows) == 1
    assert rows[0]["standard_family"] == "SAES"
    assert rows[0]["licence_status"] == standards_inventory.LICENCE_HELD
    assert rows[0]["source_file_sha256"] == "sha-std_d001"


def test_a_standard_cited_by_a_submittal_is_flagged_cited():
    """THE MUTATION TARGET: the cited flag must reflect a REAL citation in a
    submittal this caller may read, not just any submittal in the database."""
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
               document_number="API 610", discipline="Mechanical")
    sub = _doc("sub1", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
               text="Pump shall comply with API 610.", discipline="Mechanical")
    rows = standards_inventory.inventory_rows(
        allowed_document_ids=_scope(std, sub))
    assert rows[0]["cited_by_submittal"] is True


def test_a_standard_not_cited_by_any_readable_submittal_is_not_flagged():
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
               document_number="API 610", discipline="Mechanical")
    sub = _doc("sub1", "unrelated.pdf", "CONTRACTOR_SUBMITTAL",
               text="No standards named here at all.", discipline="Mechanical")
    rows = standards_inventory.inventory_rows(
        allowed_document_ids=_scope(std, sub))
    assert rows[0]["cited_by_submittal"] is False


def test_a_citation_in_a_submittal_outside_the_callers_grants_does_not_count():
    """CLAUDE.md rule 5: a filter may only NARROW what a caller may already
    read. A submittal the caller cannot see must not leak into the cited
    flag of a standard the caller CAN see."""
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
               document_number="API 610", discipline="Mechanical")
    _doc("sub1", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
         text="Pump shall comply with API 610.", discipline="Mechanical")
    rows = standards_inventory.inventory_rows(allowed_document_ids=_scope(std))
    assert rows[0]["cited_by_submittal"] is False
