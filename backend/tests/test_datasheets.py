"""Phase 4: datasheet facts, blanks, units, referenced standards.

EVERY TEST GOES THROUGH THE PIPELINE, NOT THE HELPER, and asserts something
positive before asserting an absence - honesty-audit entries 6, 11 and 13. A
test that calls a predicate directly proves the predicate and nothing about
whether the extractor uses it.

The datasheets here are built by the fixture with real ruled geometry and real
label-value text, because the repository must not depend on the client's files:
the two real KOC sheets live outside it and `CLAUDE.md` rule 3 forbids a test
depending on confidential client material. Phase 4's measurements against those
real sheets are recorded in the progress file instead.

Mutations: M49-M55, `python scripts/mutation_check.py --phase 5`.
"""

from __future__ import annotations

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
    rows = [("Design pressure", "23.5 barg"), ("340 psig", "0.892")]
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
    """THE MUTATION TARGET (M52). The stack both real KOC sheets name."""
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
