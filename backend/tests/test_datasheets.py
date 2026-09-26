"""Phase 4: datasheet facts, blanks, units, referenced standards.

EVERY TEST GOES THROUGH THE PIPELINE, NOT THE HELPER, and asserts something
positive before asserting an absence - honesty-audit entries 6, 11 and 13. A
test that calls a predicate directly proves the predicate and nothing about
whether the extractor uses it.

The datasheets here are built by the fixture with real ruled geometry and real
label-value text, because the repository must not depend on the client's files:
the two real client sheets live outside it and `CLAUDE.md` rule 3 forbids a test
depending on confidential client material. Phase 4's measurements against those
real sheets are recorded in the progress file instead.

Mutations: M49-M55, `python scripts/mutation_check.py --phase 5`.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app import claims, datasheets, db, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "ds.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    # The same two calls main.lifespan makes, in the same order. The
    # structural migration is a startup step, not something a read path
    # repairs, so a test that needs the migrated shape asks for it explicitly.
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _datasheet_pdf(path, rows, *, ruled: bool = True) -> str:
    """A one-page datasheet: numbered label-value rows, optionally ruled.

    `ruled=False` gives a form with no lines, which is what the real PSV sheet
    is and what the text-block path exists for.
    """
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(rows, start=1):
        if ruled:
            page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
            page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _ingest(path, doc_id="doc_ds", filename="EF-DAS-TEST.pdf", text=""):
    import pymupdf
    doc = pymupdf.open(path); pages = len(doc)
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,?)""",
            (doc_id, filename, f"sha-{doc_id}", str(path), pages,
             "2026-09-18T00:00:00Z"))
        for page in range(1, pages + 1):
            body = text or doc[page - 1].get_text()
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)""",
                (f"{doc_id}-c{page}", doc_id, filename, page, page, page, body,
                 f"h{doc_id}{page}"))
    doc.close()
    return doc_id


def _scope(*ids): return frozenset(ids)


ROWS = [
    ("Set pressure", "340 psig By Contractor"),
    ("Density at relieving temper.", "23.55 Kg/m3"),
    ("Design pressure", "23.5 barg"),
    ("Compressibility factor", "0.892"),
    ("Casing material", "____________"),
]


# ===================================================== facts from a datasheet

def test_a_value_with_its_unit_is_extracted_from_a_datasheet_page(tmp_path):
    """THE MUTATION TARGET (M49). Through `extract_facts`, end to end."""
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    result = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    assert result["facts"] > 0, "the extractor read nothing from a real page"

    rows = datasheets.list_facts(doc, allowed_document_ids=_scope(doc))
    by_field = {r["field_name"]: r for r in rows}
    density = by_field["density at relieving temper"]
    assert density["raw_value"] == "23.55"
    assert density["raw_unit"] == "Kg/m3"
    assert density["is_blank"] == 0
    # It resolves: a fact without a chunk and a page is an assertion.
    assert density["chunk_id"]
    assert density["page"] == 1
    assert density["citation_resolves"] is True
    # The document's own words are kept beside the parsed pair.
    assert density["field_label"] == "Density at relieving temper."


def test_a_by_contractor_field_is_recorded_as_blank_never_as_zero(tmp_path):
    """THE MUTATION TARGET (M50). MISSING_INFORMATION, not NON_COMPLIANT."""
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    rows = {r["field_name"]: r for r in
            datasheets.list_facts(doc, allowed_document_ids=_scope(doc))}

    blank = rows["set pressure"]
    assert blank["is_blank"] == 1
    assert "contractor" in (blank["blank_marker"] or "").lower()
    # NEVER A ZERO, and never a parsed value: the 340 is provisional and the
    # sheet says the vendor must confirm it.
    assert blank["normalized_value"] is None
    assert blank["raw_value"] is None
    assert blank["field_value"] != 0
    # The sheet's own words survive, so a reader can see what it said.
    assert "340 psig" in blank["field_value"]


def test_a_drawn_placeholder_rule_is_a_blank(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    rows = {r["field_name"]: r for r in
            datasheets.list_facts(doc, allowed_document_ids=_scope(doc))}
    assert rows["casing material"]["is_blank"] == 1
    assert rows["casing material"]["blank_marker"] == "placeholder"


def test_blanks_only_returns_the_missing_information(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    blanks = datasheets.list_facts(
        doc, allowed_document_ids=_scope(doc), blanks_only=True)
    assert blanks, "no blanks found on a sheet that has two"
    assert all(r["is_blank"] == 1 for r in blanks)


def test_an_unknown_unit_yields_none_and_never_zero(tmp_path):
    """A unit the table does not know gives None - never 0, never a guess.

    THIS TEST USED TO USE Kg/m3, WHICH IS NOW IN THE TABLE. It was added as a
    density with an identity conversion, so it normalises and this assertion
    correctly went red. Re-pointed at `cP`, which is genuinely absent, rather
    than loosened - the property under test is the honesty rule, not the
    particular unit that happened to demonstrate it.

    Both halves are asserted on the same sheet so the test cannot pass by
    everything normalising OR by nothing doing.
    """
    rows_with_viscosity = [*ROWS, ("Viscosity at 40 C", "12.4 cP")]
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", rows_with_viscosity))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    rows = {r["field_name"]: r for r in
            datasheets.list_facts(doc, allowed_document_ids=_scope(doc))}

    viscosity = rows["viscosity at 40 c"]
    # The value and the spelling survive...
    assert viscosity["raw_value"] == "12.4"
    assert viscosity["raw_unit"] == "cP"
    # ...and the normalised pair is None, not 0.
    assert viscosity["normalized_value"] is None
    assert viscosity["normalized_unit"] is None

    # AND A UNIT THE TABLE DOES KNOW STILL NORMALISES, on the same sheet.
    # Without this the test would pass against a build that normalised nothing.
    density = rows["density at relieving temper"]
    assert density["raw_unit"] == "Kg/m3"
    assert density["normalized_value"] == 23.55
    assert density["normalized_unit"] == "kg/m3"


def test_prose_is_not_recorded_as_a_measurement(tmp_path):
    """Found on the real sheet: "2nd Stage Desalter" parsed as value 2 unit
    "nd", and a P&ID number "10-05-498 & 556-05-513" as the value 10."""
    rows = [("Location", "2nd Stage Desalter"),
            ("P&ID Reference", "10-05-498 & 556-05-513"),
            ("Design pressure", "23.5 barg")]
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", rows))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    found = {r["field_name"]: r for r in
             datasheets.list_facts(doc, allowed_document_ids=_scope(doc))}
    # The real measurement IS there - assert the positive first.
    assert found["design pressure"]["raw_value"] == "23.5"
    # And the prose did not become one.
    assert "location" not in found
    assert "p/id reference" not in found and "p id reference" not in found


def test_a_value_is_never_promoted_into_a_field_label(tmp_path):
    """THE MUTATION TARGET (M56), and the first version of this file missed it.

    `test_prose_is_not_recorded_as_a_measurement` above is defended by the FACT
    GATE, not by `is_field_label` - prose with no number and no blank marker is
    dropped either way - so deleting the label guard left it passing.

    The case the label guard actually prevents is TWO VALUE CELLS SIDE BY SIDE.
    The first becomes the "label" and the second parses, so the fact gate lets
    it through and a row appears whose field name is a number. On the real PSV
    sheet that produced field labels like `0.01cP By Contractor` and
    `23.5 / 11.03 barg`, and 375 phantom blank fields with them.
    """
    # "340 psig" alone is now ALSO refused by row_noise's number-keyed rule
    # (it runs on the default path since 2026-09-25), which masked the label
    # guard under mutation (M56). A decimal first cell - "0.01 cP" - has no
    # such shape, so only `is_field_label` stops it becoming a field name.
    rows = [("Design pressure", "23.5 barg"), ("340 psig", "0.892"), ("0.01 cP", "0.892")]
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", rows))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    found = datasheets.list_facts(doc, allowed_document_ids=_scope(doc))

    # POSITIVE FIRST: the genuine label-value row was read.
    assert any(f["field_name"] == "design pressure" for f in found)
    # And no fact has a measurement for a field name.
    for fact in found:
        assert datasheets.measure_value(fact["field_label"])[0] is None, \
            f"a value was promoted into a field label: {fact['field_label']!r}"


def test_a_fact_cannot_be_created_without_a_resolving_citation(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    other = _ingest(_datasheet_pdf(tmp_path / "o.pdf", ROWS), doc_id="doc_other",
                    filename="OTHER.pdf")
    with pytest.raises(datasheets.FactError):
        datasheets.create_fact(submittal_document_id=doc, chunk_id="nope",
                               field_label="x", raw_value="1", page=1)
    with pytest.raises(datasheets.FactError):
        datasheets.create_fact(submittal_document_id=doc,
                               chunk_id=f"{other}-c1", field_label="x",
                               raw_value="1", page=1)
    with pytest.raises(datasheets.FactError):
        datasheets.create_fact(submittal_document_id=doc,
                               chunk_id=f"{doc}-c1", field_label="x",
                               raw_value="1", page=99)


# ============================================================ unparsed pages

def test_an_unparsed_page_lowers_completeness_and_says_why(tmp_path):
    """THE MUTATION TARGET (M51). A page with nothing readable is reported."""
    import pymupdf
    path = tmp_path / "mixed.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=600, height=400)
    page.insert_text((44, 60), "1"); page.insert_text((64, 60), "Design pressure")
    page.insert_text((304, 60), "23.5 barg")
    blank_page = doc_pdf.new_page(width=600, height=400)
    blank_page.insert_text((50, 100), "This page is narrative text with no fields.")
    doc_pdf.save(str(path)); doc_pdf.close()

    doc = _ingest(path)
    result = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    # POSITIVE FIRST: page 1 was read.
    assert result["facts"] >= 1
    assert result["pages_read"] == 2
    # And page 2 is reported as unparsed, with a reason, lowering the fraction.
    assert result["pages_unparsed"] == 1
    assert result["parsed_fraction"] == 0.5
    assert result["unparsed"][0]["page"] == 2
    assert result["unparsed"][0]["reason"]


def test_a_document_with_no_chunks_reports_a_null_fraction(tmp_path):
    """None is "nothing to read", not "read nothing of what was there"."""
    result = datasheets.extract_facts("doc_missing",
                                      allowed_document_ids=_scope("doc_missing"))
    assert result["facts"] == 0
    assert result["parsed_fraction"] is None


# ====================================================== referenced standards

def test_a_referenced_standard_named_in_the_datasheet_is_detected(tmp_path):
    """THE MUTATION TARGET (M52). The stack both real client sheets name."""
    text = ("Design Standard: API RP 520 Pt-1&2, KOC-MP-027 Pt-1. "
            "Materials per NACE MR-0175 / ISO 15156 and ASTM A216. "
            "Pump per API 610 and KOC-ME-008.")
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS), text=text)
    result = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    found = {s.upper().replace(" ", "") for s in result["referenced_standards"]}
    # Matched on the BASE identifier, because the part suffix belongs to the
    # citation: the sheet wrote "KOC-MP-027 Pt-1" and the extractor keeps the
    # part rather than truncating it. A citation is quoted, not canonicalised.
    for expected in ("APIRP520", "KOC-MP-027", "NACEMR-0175", "ISO15156",
                     "API610", "KOC-ME-008"):
        assert any(f.startswith(expected) for f in found), \
            f"{expected} was not detected; found {sorted(found)}"


def test_a_tag_number_is_not_mistaken_for_a_standard():
    """PSV-4303 and 10-05-498 are tags, not standards."""
    found = datasheets.referenced_standards(
        "Tag No. PSV-4303 A/B, P&ID 10-05-498, per API 610.")
    assert found == ["API 610"]


# ========================================== same-unit comparison (claims.py)

def test_same_unit_dba_values_compare():
    """THE MUTATION TARGET (M53). The master plan's flagship case.

    dB has no dimension and `claims` rightly refuses to convert it. But "is 95
    dB(A) above a 90 dB(A) limit" needs no conversion, only unit equality - and
    without this, phase 5 cannot evaluate the one requirement the plan is
    written around.
    """
    limit = claims.normalise("90", "dB(A)", "<=")
    breach = claims.normalise("95", "dB(A)")
    compliant = claims.normalise("85", "dB(A)")
    assert claims.same_unit(limit, breach) is True
    # False == the ranges do not overlap == 95 breaches a <= 90 limit.
    assert claims._compatible(breach, limit) is False
    assert claims._compatible(compliant, limit) is True
    # The PSV exception's own limit works the same way.
    assert claims._compatible(claims.normalise("115", "dB(A)"), limit) is False


def test_different_units_still_refuse_to_compare():
    """THE MUTATION TARGET (M54). The ScaleMismatch discipline is intact."""
    a = claims.normalise("90", "dB(A)")
    b = claims.normalise("90", "pcf")
    assert claims.same_unit(a, b) is False
    assert claims._compatible(a, b) is None
    # dB(A) and dB are NOT the same unit: A-weighting is part of the meaning.
    assert claims.same_unit(claims.normalise("1", "dB(A)"),
                            claims.normalise("1", "dB")) is False


def test_conversion_between_unknown_units_still_raises():
    with pytest.raises(claims.UnknownUnit):
        claims.normalise_strict("90", "dB(A)")
    with pytest.raises(claims.UnknownUnit):
        claims.normalise_strict("90", "F")      # Fahrenheit, refused by design
    # A known unit still converts.
    assert claims.normalise("12", "mm").normalized_value == 12000.0


# ================================================================ permissions

def test_an_unauthorised_user_sees_no_facts(tmp_path):
    """THE MUTATION TARGET (M55)."""
    mine = _ingest(_datasheet_pdf(tmp_path / "m.pdf", ROWS), doc_id="doc_mine")
    theirs = _ingest(_datasheet_pdf(tmp_path / "t.pdf", ROWS), doc_id="doc_theirs",
                     filename="THEIRS.pdf")
    datasheets.extract_facts(theirs, allowed_document_ids=_scope(theirs))
    # POSITIVE FIRST: the facts exist and are readable by their owner.
    assert datasheets.list_facts(theirs, allowed_document_ids=_scope(theirs))
    # And are invisible to someone granted only their own document.
    assert datasheets.list_facts(theirs, allowed_document_ids=_scope(mine)) == []
    assert datasheets.extract_facts(
        theirs, allowed_document_ids=_scope(mine))["facts"] == 0


def test_an_empty_grant_set_sees_nothing(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    assert datasheets.list_facts(doc, allowed_document_ids=frozenset()) == []
    assert datasheets.extract_facts(
        doc, allowed_document_ids=frozenset())["facts"] == 0


@pytest.mark.parametrize("call", [
    lambda: datasheets.extract_facts("d"),
    lambda: datasheets.list_facts("d"),
])
def test_a_caller_that_forgets_the_filter_raises_typeerror(call):
    with pytest.raises(TypeError):
        call()


# ============================================== facts are reusable per document

def test_facts_survive_without_a_review_run_and_are_reused(tmp_path):
    """THE PHASE 1 SCHEMA DECISION, REVERSED DELIBERATELY.

    `review_run_id` was NOT NULL, which forced a full re-extraction of a
    datasheet on every review. Master plan section 24 asks the opposite on a
    16 GB machine: reuse cached extraction. A fact is now a property of the
    DOCUMENT and the run id is nullable.
    """
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    result = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    assert result["facts"] > 0
    rows = datasheets.list_facts(doc, allowed_document_ids=_scope(doc))
    # Extracted outside any run, and stored.
    assert all(r["review_run_id"] is None for r in rows)
    columns = {r[1]: r for r in db.connect().execute(
        "PRAGMA table_info(submittal_facts)")}
    assert columns["review_run_id"][3] == 0, "review_run_id is still NOT NULL"
    assert "chunk_id" in columns


def test_re_extracting_does_not_double_the_facts(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    first = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    assert len(datasheets.list_facts(
        doc, allowed_document_ids=_scope(doc))) == first["facts"]


# ======================================================================= B44
#
# A FILE NOBODY COULD OPEN WAS REPORTED AS A PAGE WITH NO VALUES ON IT.
#
# The bare `except Exception` around the PDF open meant a missing, damaged,
# empty or encrypted file came back as an empty pair list, which reached
# `_unparsed_reason` and produced "no label-value pairs recovered from this
# page" - the sentence that function's own docstring warns is an OCR question.
# The page was counted as READ as well, because `pages_read` is keyed off chunk
# spans rather than parse success, so `parsed_fraction` was computed over pages
# that were never opened.
#
# Every case below was reproduced against PyMuPDF 1.28.2 before it was written.


def _unreadable_doc(tmp_path, blob: bytes, doc_id: str):
    """A document row whose stored file is damaged in some specific way.

    The chunks are real, because that is the situation: the file was readable
    when it was ingested and is not readable now. A test that also removed the
    chunks would prove nothing - the no-chunks path returns early.
    """
    good = _datasheet_pdf(tmp_path / f"{doc_id}-good.pdf", ROWS, ruled=False)
    _ingest(good, doc_id=doc_id, filename=f"{doc_id}.pdf")
    broken = tmp_path / f"{doc_id}-broken.pdf"
    broken.write_bytes(blob)
    with db.connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (str(broken), doc_id))
    return doc_id


def _valid_pdf_bytes(tmp_path) -> bytes:
    return pathlib.Path(
        _datasheet_pdf(tmp_path / "source.pdf", ROWS, ruled=False)).read_bytes()


@pytest.mark.parametrize("case,blob_kind,rule", [
    ("missing", "absent", "pdf_missing"),
    ("empty", "zero_bytes", "pdf_empty_file"),
    ("garbage", "not_a_pdf", "pdf_damaged"),
])
def test_b44_an_unreadable_file_is_named_not_called_a_page_with_no_values(
        tmp_path, case, blob_kind, rule):
    """THE DEFECT, once per measured case. The reason names the FILE."""
    doc_id = f"doc_{case}"
    if blob_kind == "absent":
        good = _datasheet_pdf(tmp_path / "g.pdf", ROWS, ruled=False)
        _ingest(good, doc_id=doc_id, filename=f"{doc_id}.pdf")
        with db.connect() as conn:
            conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                         (str(tmp_path / "not_here.pdf"), doc_id))
    else:
        blob = b"" if blob_kind == "zero_bytes" else b"this is not a pdf at all"
        _unreadable_doc(tmp_path, blob, doc_id)

    out = datasheets.extract_facts(doc_id, allowed_document_ids=_scope(doc_id))

    assert [u["rule"] for u in out["unreadable"]] == [rule], \
        f"the file's condition was not named: {out['unreadable']}"
    assert out["unreadable"][0]["reason"] == datasheets.UNREADABLE[rule]
    assert "no label-value pairs recovered" not in str(out["unreadable"]), \
        "an unopenable file was reported as a page that printed nothing"


@pytest.mark.parametrize("case,blob_kind,rule", [
    ("missing2", "absent", "pdf_missing"),
    ("empty2", "zero_bytes", "pdf_empty_file"),
    ("garbage2", "not_a_pdf", "pdf_damaged"),
])
def test_b44_a_page_that_was_never_opened_is_not_counted_as_read(
        tmp_path, case, blob_kind, rule):
    """It lowered completeness with the wrong reason AND inflated the
    denominator. `parsed_fraction` is None, not 0.0: nothing was read, so there
    is no fraction to state - the same distinction the no-chunks path makes."""
    doc_id = f"doc_{case}"
    if blob_kind == "absent":
        good = _datasheet_pdf(tmp_path / "g2.pdf", ROWS, ruled=False)
        _ingest(good, doc_id=doc_id, filename=f"{doc_id}.pdf")
        with db.connect() as conn:
            conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                         (str(tmp_path / "gone.pdf"), doc_id))
    else:
        blob = b"" if blob_kind == "zero_bytes" else b"%NOT-A-PDF"
        _unreadable_doc(tmp_path, blob, doc_id)

    out = datasheets.extract_facts(doc_id, allowed_document_ids=_scope(doc_id))

    assert out["pages_read"] == 0, "a page nobody opened was counted as read"
    assert out["parsed_fraction"] is None, \
        "a fraction was stated over pages that were never read"
    assert out["pages_unreadable"] >= 1
    assert out["facts"] == 0


def test_b44_an_encrypted_file_is_named_before_a_page_is_touched(tmp_path):
    """An encrypted PDF OPENS: it reports its page count happily and only
    raises a bare ValueError when a page is touched. So it is detected by
    `needs_pass`, not by catching a message."""
    import pymupdf
    doc_id = "doc_encrypted"
    good = _datasheet_pdf(tmp_path / "plain.pdf", ROWS, ruled=False)
    _ingest(good, doc_id=doc_id, filename="locked.pdf")
    locked = tmp_path / "locked.pdf"
    src = pymupdf.open(good)
    src.save(str(locked), encryption=pymupdf.PDF_ENCRYPT_AES_256,
             owner_pw="owner-secret", user_pw="user-secret")
    src.close()
    with db.connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (str(locked), doc_id))

    out = datasheets.extract_facts(doc_id, allowed_document_ids=_scope(doc_id))

    assert [u["rule"] for u in out["unreadable"]] == ["pdf_encrypted"]
    assert out["pages_read"] == 0
    assert out["facts"] == 0


def test_b44_a_truncated_file_that_opens_anyway_is_reported_as_repaired(tmp_path):
    """THE CASE NO `except` CLAUSE CAN CATCH. MuPDF rebuilds the cross-
    reference table, opens the file, returns FEWER blocks than the document
    has, and raises nothing at all. `is_repaired` is the only signal.

    0.70 is measured for THIS fixture's shape, not a round number: at 1.00 it
    is False, from 0.99 to 0.70 it opens repaired, at 0.70 one of five text
    blocks is already silently gone, and by 0.60 it will not open at all
    (FileDataError, which is the `pdf_damaged` case two tests up). The exact
    fraction depends on the file's object layout, so the assertions below pin
    the BEHAVIOUR - opens, and is flagged - rather than the number.
    """
    doc_id = "doc_truncated"
    good = _datasheet_pdf(tmp_path / "whole.pdf", ROWS, ruled=False)
    _ingest(good, doc_id=doc_id, filename="truncated.pdf")
    whole = pathlib.Path(good).read_bytes()
    cut = tmp_path / "cut.pdf"
    cut.write_bytes(whole[:int(len(whole) * 0.7)])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (str(cut), doc_id))

    out = datasheets.extract_facts(doc_id, allowed_document_ids=_scope(doc_id))

    assert out["repaired"] is True, \
        "a file MuPDF had to repair to open was reported as intact"
    assert out["unreadable"] == [], "a repaired file is readable, not unreadable"


def test_b44_an_intact_file_is_never_called_repaired(tmp_path):
    """The control. Without it the flag could be hardcoded True and every test
    above would still pass - and every real datasheet would carry a damage
    warning nobody could act on."""
    doc_id = "doc_intact"
    good = _datasheet_pdf(tmp_path / "intact.pdf", ROWS, ruled=False)
    _ingest(good, doc_id=doc_id, filename="intact.pdf")

    out = datasheets.extract_facts(doc_id, allowed_document_ids=_scope(doc_id))

    assert out["repaired"] is False
    assert out["unreadable"] == [] and out["pages_unreadable"] == 0
    assert out["facts"] > 0, "the control must still extract, or it proves nothing"


# ==================================================================== #175
#
# CASCADED EXTRACTOR (layout/table tier), CONFIDENCE ROUTING, and REVISION
# TRACEABILITY. Cause 2 (table-reading rule fix, formerly parked on
# `parked/cause2-rule-based-fix` as B58) is reused here rather than
# reinvented: `tables.parse_page_tables` already finds a ruled table's shape
# correctly, but every row - header AND data - was run through
# `split_label_value`'s ALTERNATING-PAIR assumption, which is right for a
# "two forms side by side" text block and wrong for "one row label, several
# values under several column headers". `pairs_from_table_shape` scopes each
# value to its own row label and column header instead.
#
# No client content: labels, headers and values below are invented, but the
# SHAPE - a two-line header with a spanning cell, several data rows, some
# with blank cells - reproduces what was measured on a real regression
# document's ruled table.


TWO_LINE_HEADER_SHAPE = [
    ["INSPECTION TYPE", "METHOD", "CRITERIA", ""],
    ["", "", "NEW BUILD", "REPAIR"],
    ["MAGNETIC PARTICLE", "ASTM E709", "ASTM E125 grade 2", "ASTM E125 grade 1"],
    ["ULTRASONIC", "", "", ""],
    ["DYE PENETRANT", "ASTM E165", "", "ASTM E125 grade 1"],
]

SINGLE_HEADER_SHAPE = [
    ["Size", "Facing", "Rating", "Position"],
    ["2 in", "RF", "150", "TOP"],
    ["4 in", "RF", "300", "END"],
]


def test_175_a_row_labels_its_own_values_under_their_own_column_headers():
    """THE DEFECT. Two real values on one row must not be cross-paired
    against each other - each belongs to the ROW's label, scoped by its own
    column."""
    pairs = datasheets.pairs_from_table_shape(TWO_LINE_HEADER_SHAPE)
    by_label = dict(pairs)

    assert by_label.get("MAGNETIC PARTICLE - METHOD") == "ASTM E709"
    assert by_label.get("MAGNETIC PARTICLE - CRITERIA - NEW BUILD") == "ASTM E125 grade 2"
    assert by_label.get("MAGNETIC PARTICLE - CRITERIA - REPAIR") == "ASTM E125 grade 1"
    assert "ASTM E125 grade 2" not in by_label, (
        "a value was cross-paired against its neighbour instead of scoped "
        f"to its row label: {pairs}")


def test_175_a_spanning_header_cell_is_carried_to_every_column_beneath_it():
    """The CRITERIA super-header is written once, over two sub-columns. Read
    literally, REPAIR would lose that it is a criteria column at all."""
    pairs = datasheets.pairs_from_table_shape(TWO_LINE_HEADER_SHAPE)
    by_label = dict(pairs)

    assert "MAGNETIC PARTICLE - REPAIR" not in by_label, (
        "the spanning header was not carried forward - REPAIR lost its "
        f"parent header CRITERIA: {pairs}")
    assert by_label.get("DYE PENETRANT - CRITERIA - REPAIR") == "ASTM E125 grade 1"


def test_175_a_blank_row_produces_no_pairs():
    """ULTRASONIC has a label and nothing else. No value, no pair."""
    pairs = datasheets.pairs_from_table_shape(TWO_LINE_HEADER_SHAPE)
    assert not any(label.startswith("ULTRASONIC") for label, _ in pairs)


def test_175_a_single_line_header_needs_no_carry_forward():
    """The common case: one header row, no spanning cells."""
    pairs = datasheets.pairs_from_table_shape(SINGLE_HEADER_SHAPE)
    by_label = dict(pairs)

    assert by_label.get("2 in - Facing") == "RF"
    assert by_label.get("2 in - Rating") == "150"
    assert by_label.get("2 in - Position") == "TOP"
    assert by_label.get("4 in - Position") == "END"


def test_175_a_narrow_shape_falls_through_to_split_label_value_unchanged():
    """Under three columns wide, this is exactly the row split_label_value
    was built for - the new function must not touch it."""
    two_col = [["Design pressure", "23.5 barg"]]
    assert (datasheets.pairs_from_table_shape(two_col)
           == datasheets.split_label_value(["Design pressure", "23.5 barg"]))


def test_175_wired_into_extract_facts_not_just_the_function():
    """The function alone proves nothing about the product until something
    calls it. The CALL FORM, not the bare name - a comment naming the
    function would satisfy a bare-substring check without ever calling it."""
    import inspect
    source = inspect.getsource(datasheets.extract_facts)
    assert "pairs_from_table_shape(" in source, (
        "extract_facts's ruled-table loop still calls split_label_value "
        "directly - the fix exists but was never wired in")


# ==================================================================== #179
#
# Two real regression documents, re-audited independently after #175
# shipped: `pairs_from_table_shape` treated column 0 as THE row's one label
# in every case, which is wrong whenever column 0 is actually a bare KOC-
# style row/line number rather than a name for the row. No client content:
# the labels, headers and values below are invented, but each SHAPE - a
# ruled row that packs two independent label:value sub-forms side by side
# behind their own line numbers, and a ruled table whose row 0 is the
# page's own repeating title rather than a real column header - reproduces
# exactly what was measured on the two real regression documents' pages.

# A pressure-safety-valve sheet's row: a PROCESS DATA sub-form and a
# SPRING AND BONNET sub-form share one physical row, each introduced by its
# own line number, with a blank spacer column on either side of each value.
DUAL_SUBFORM_ROW_SHAPE = [
    ["MAKE / MFR. MODEL NO.", "", "", "", "", "Design Standard: X", "", ""],
    ["1", "Fluid", "", "Crude Oil/Gas (Dual Service)", "", "42",
     "Bonnet type/ style", "Bolted/ closed"],
]

# A ruled table whose row 0 is the page's own repeating title (the actual
# column header - "Ref. Clause | Description | Purchaser requirement |
# Unit" - sits several rows further down and is itself introduced by a row
# number, exactly like every other row on this sheet).
ROW_NUMBERED_FORM_SHAPE = [
    ["Row", "COMPANY NAME PROJECT TITLE", "", "", "", "", "", "", "Issue"],
    ["4", "Identifier", "", "", "", "", "", "", ""],
    ["5", "", "Tag number :", "TAG-0001A/B", "", "", "", "", ""],
]


def test_179_a_dual_subform_row_keeps_each_side_s_own_label():
    """THE DEFECT. Column 0 ('1') is a row number, not a label - pairing
    every value on the row against it turned the row's two REAL labels
    ('Fluid', 'Bonnet type/ style') into values and left every fact on the
    row named after a bare digit."""
    pairs = datasheets.pairs_from_table_shape(DUAL_SUBFORM_ROW_SHAPE)
    by_label = dict(pairs)

    assert by_label.get("Fluid") == "Crude Oil/Gas (Dual Service)", pairs
    assert by_label.get("Bonnet type/ style") == "Bolted/ closed", pairs
    assert not any(re.fullmatch(r"\d{1,3}", label) for label, _ in pairs), (
        f"a row number survived as a field_name: {pairs}")


def test_179_a_row_numbered_form_does_not_quote_the_page_s_own_title():
    """THE DEFECT. Row 0 is the page's own repeating title, not a column
    header - scoping every value to it quoted the title text into
    field_label instead of the real row label."""
    pairs = datasheets.pairs_from_table_shape(ROW_NUMBERED_FORM_SHAPE)
    by_label = dict(pairs)

    assert by_label.get("Tag number :") == "TAG-0001A/B", pairs
    assert not any("COMPANY NAME" in label for label, _ in pairs), (
        f"the page's own title leaked into a field_label: {pairs}")
    assert not any(re.fullmatch(r"\d{1,3}", label) for label, _ in pairs), (
        f"a row number survived as a field_name: {pairs}")


# --------------------------------------------------- OCR fallback (tier 2)

def test_175_a_page_with_no_native_pairs_falls_back_to_its_ocr_text(tmp_path):
    """A page that yields NOTHING from the text/table tier (a real scanned
    page has no drawable text at all) still recovers a fact when `ocr.py`
    has already recognised it into `page_ocr` - the cascade's second tier,
    read for the first time here."""
    import pymupdf
    doc = pymupdf.open()
    doc.new_page(width=600, height=500)   # genuinely blank: no text, no table
    blank_path = tmp_path / "scanned.pdf"
    doc.save(str(blank_path)); doc.close()
    doc_id = _ingest(blank_path, doc_id="doc_scan", filename="scan.pdf", text=" ")

    with db.connect() as conn:
        conn.execute(
            """INSERT INTO page_ocr
               (document_id, page_no, text, char_count, engine, model, dpi,
                box_count, seconds, recognised_at, batch_no)
               VALUES (?,1,?,?, 'rapidocr-3.9.2', 'test-model', 200, 1,
                       0.1, '2026-09-23T00:00:00Z', 0)""",
            (doc_id, "Design pressure: 23.5 barg", 26))

    out = datasheets.extract_facts(doc_id, allowed_document_ids=_scope(doc_id))
    assert out["facts"] > 0, "the OCR fallback tier never fired"

    facts = datasheets.list_facts(doc_id, allowed_document_ids=_scope(doc_id))
    ocr_facts = [f for f in facts if f["extraction_method"] == "ocr_fallback"]
    assert ocr_facts, f"no fact was attributed to the OCR tier: {facts}"
    assert all(f["confidence"] < datasheets.LOW_CONFIDENCE_THRESHOLD for f in ocr_facts)
    assert all(f["validation_state"] == datasheets.NEEDS_ENGINEER_REVIEW
              for f in ocr_facts), (
        "a low-confidence, OCR-sourced fact was accepted as confident "
        "instead of routed to NEEDS_ENGINEER_REVIEW")


def test_175_a_page_with_native_pairs_never_reaches_the_ocr_tier(tmp_path):
    """The cascade STOPS at the first tier with evidence. A page the
    text/table tier already read must not also be re-read from OCR, or a
    confident native fact could be overwritten by a low-confidence guess."""
    doc = _ingest(_datasheet_pdf(tmp_path / "native.pdf", ROWS), doc_id="doc_native")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO page_ocr
               (document_id, page_no, text, char_count, engine, model, dpi,
                box_count, seconds, recognised_at, batch_no)
               VALUES (?,1,'Poison field: 999 barg',23,'rapidocr-3.9.2',
                       'test-model',200,1,0.1,'2026-09-23T00:00:00Z',0)""",
            (doc,))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    facts = datasheets.list_facts(doc, allowed_document_ids=_scope(doc))
    assert not any(f["field_label"] == "Poison field" for f in facts), (
        "a page with native text/table evidence was also read from OCR")


# ----------------------------------------------- vision fallback (tier 3)

def test_175_vision_fallback_is_a_documented_no_op_when_unconfigured():
    """No vision-capable provider is implemented or configured anywhere on
    this branch (`reasoning_provider.OllamaProvider` is text-only). The tier
    must not invent an answer - it returns nothing, honestly."""
    assert datasheets._pairs_from_vision_fallback("/no/such/file.pdf", 1) == []


# --------------------------------------------- confidence routing (item 2)

def test_175_a_low_confidence_fact_is_routed_to_needs_engineer_review(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d2.pdf", ROWS), doc_id="doc_conf")
    chunk = db.connect().execute(
        "SELECT id FROM chunks WHERE document_id = ? LIMIT 1", (doc,)).fetchone()

    fact = datasheets.create_fact(
        submittal_document_id=doc, chunk_id=chunk["id"], field_label="Guessed field",
        raw_value="12 barg", page=1, confidence=0.3)
    assert fact["validation_state"] == datasheets.NEEDS_ENGINEER_REVIEW


def test_175_a_confident_fact_is_never_marked_needs_engineer_review(tmp_path):
    """THE CONTROL. Without it `validation_state` could be hardcoded to
    NEEDS_ENGINEER_REVIEW and the test above would still pass."""
    doc = _ingest(_datasheet_pdf(tmp_path / "d3.pdf", ROWS), doc_id="doc_conf2")
    chunk = db.connect().execute(
        "SELECT id FROM chunks WHERE document_id = ? LIMIT 1", (doc,)).fetchone()

    fact = datasheets.create_fact(
        submittal_document_id=doc, chunk_id=chunk["id"], field_label="Solid field",
        raw_value="12 barg", page=1, confidence=0.6)
    assert fact["validation_state"] is None


# ------------------------------------------- revision traceability (item 3)

def test_175_a_fact_traces_to_the_exact_document_revision_it_came_from(tmp_path):
    """`list_facts` names the document row's own `sha256` - the content
    fingerprint of the exact revision this fact was read from - via the
    existing foreign key, no new column required."""
    doc = _ingest(_datasheet_pdf(tmp_path / "d4.pdf", ROWS), doc_id="doc_rev")
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))
    facts = datasheets.list_facts(doc, allowed_document_ids=_scope(doc))
    assert facts, "fixture produced no facts to check"
    assert all(f["document_sha256"] == f"sha-{doc}" for f in facts)
