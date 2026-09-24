"""Phase 3B: table extraction, numeric limits, conditions, exceptions, queue.

TABLE EXTRACTION IS TESTED AGAINST A PDF WITH REAL RULED GEOMETRY, drawn here
rather than shipped, because the repository's corpus contains no standard whose
tables are machine-readable. That is a measured fact, not an assumption - see
`docs/AI_SUBMITTAL_REVIEW_PROGRESS.md` section 37 - and the fixture exists so
that the parser is proven against a table PyMuPDF can actually see.

The worked case throughout is the master plan's own: a 90 dB(A) general noise
limit with a 115 dB(A) exception for pressure relief valves. An exception that
is dropped turns a compliant PSV into a false finding.

Mutations: M39-M46, `python scripts/mutation_check.py --phase 4`.
"""

from __future__ import annotations

import pytest

from app import claims, db, requirements_3b, search as search_mod, standards, submittal_review, tables
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "s3b.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _ruled_table_pdf(path, header, rows) -> str:
    """A one-page PDF with a REAL ruled table: drawn lines and placed text.

    The ruling lines are what `find_tables` needs. A scanned page has none,
    which is exactly why 79% of this corpus's table chunks cannot be parsed.
    """
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    all_rows = [header, *rows]
    x0, y0, cw, rh = 40, 60, 130, 30
    for r, row in enumerate(all_rows):
        for c, cell in enumerate(row):
            rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh,
                             x0 + (c + 1) * cw, y0 + (r + 1) * rh)
            page.draw_rect(rect, color=(0, 0, 0), width=0.7)
            page.insert_text((rect.x0 + 4, rect.y0 + 19), str(cell), fontsize=9)
    doc.save(str(path))
    doc.close()
    return str(path)


def _doc(doc_id: str, stored_path: str, filename: str = "STD-1.pdf") -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,?,?,'ready',1,?)""",
            (doc_id, filename, f"sha-{doc_id}", 1, stored_path,
             "2026-09-18T00:00:00Z"))
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,document_role,discipline,document_number)
            VALUES (?,?,?,?,?)""",
            (doc_id, "test", standards.COMPANY_STANDARD, "Mechanical",
             f"NUM-{doc_id}"))
    return doc_id


def _chunk(chunk_id, doc_id, text, *, kind="prose", section=None, page=1, ordinal=0):
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
            (chunk_id, doc_id, "STD-1.pdf", ordinal, page, page, section, kind,
             text, len(text.split()), f"h-{chunk_id}"))
    return chunk_id


def _scope(*ids): return frozenset(ids)


NOISE = ("The noise level shall not exceed 90 dB(A), except for pressure "
         "relief valves, which shall not exceed 115 dB(A).")


# ============================================================== table extraction

def test_a_numeric_value_is_extracted_from_a_real_table_with_its_unit(tmp_path):
    """THE MUTATION TARGET (M39). A real ruled table, read end to end."""
    pdf = _ruled_table_pdf(
        tmp_path / "t.pdf",
        ["Pile Use Category", "Southern Pine Creosote (pcf)"],
        [["Foundation", "12"], ["Marine", "20"]])
    doc = _doc("doc_t", pdf)
    _chunk("c1", doc, "table text", kind="table", page=1)

    parses = tables.parse_document_tables("doc_t", allowed_document_ids=_scope(doc))
    assert len(parses) == 1
    assert parses[0].parsed is True, parses[0].unparsed_reason
    assert parses[0].columns[0] == "Pile Use Category"

    standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    rows = standards.list_requirements("doc_t", allowed_document_ids=_scope(doc))
    values = {r["raw_value"] for r in rows}
    assert "12" in values and "20" in values
    row = next(r for r in rows if r["raw_value"] == "12")
    assert row["requirement_type"] == "table_value"
    assert row["field"] == "Southern Pine Creosote"
    # THE UNIT, taken from the header the document wrote.
    assert row["raw_unit"] == "pcf"
    assert row["condition"] == "Foundation"
    # And it still resolves.
    assert row["chunk_id"] == "c1"
    assert row["page"] == 1
    assert row["citation_resolves"] is True


def test_an_unknown_unit_yields_none_and_never_zero(tmp_path):
    """THE MUTATION TARGET (M40). `pcf` is not in claims.py's table.

    None is the honest answer and 0 is a lie that reads as a limit of zero -
    a real and very different requirement.
    """
    pdf = _ruled_table_pdf(tmp_path / "t.pdf",
                           ["Category", "Retention (pcf)"], [["Foundation", "12"]])
    doc = _doc("doc_t", pdf)
    _chunk("c1", doc, "table", kind="table", page=1)
    standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    row = standards.list_requirements("doc_t", allowed_document_ids=_scope(doc))[0]
    assert row["raw_value"] == "12"
    assert row["raw_unit"] == "pcf"
    assert row["value"] is None, "an unknown unit produced a normalised value"
    assert row["value"] != 0
    assert row["unit"] is None


def test_a_known_unit_is_normalised_by_claims(tmp_path):
    """The control for the test above: mm IS known, and converts."""
    measurement = requirements_3b.measure("12", "mm")
    assert measurement.normalized_value == 12000.0
    assert measurement.normalized_unit == "um"
    # And the raw spelling survives, so the document is still quotable.
    assert measurement.raw_value == "12"
    assert measurement.raw_unit == "mm"


def test_an_unparsed_table_lowers_completeness_rather_than_passing(tmp_path):
    """THE MUTATION TARGET (M41).

    A PDF with no ruling lines has no recoverable geometry. It is reported as
    unparsed WITH A REASON and drags the parsed fraction down - it does not
    quietly contribute nothing and leave the standard looking complete.
    """
    import pymupdf
    path = tmp_path / "flat.pdf"
    doc_pdf = pymupdf.open(); page = doc_pdf.new_page()
    page.insert_text((50, 100), "12 17 0.8 1.0 Foundation Marine")
    doc_pdf.save(str(path)); doc_pdf.close()

    doc = _doc("doc_f", str(path))
    _chunk("c1", doc, "flattened table text", kind="table", page=1)
    report = standards.table_report("doc_f", allowed_document_ids=_scope(doc))
    assert report["tables_total"] == 1
    assert report["tables_parsed"] == 0
    assert report["tables_unparsed"] == 1
    assert report["parsed_fraction"] == 0.0
    assert report["tables"][0]["parsed"] is False
    assert report["tables"][0]["unparsed_reason"]
    # And nothing was invented from it.
    standards.extract_table_values("doc_f", allowed_document_ids=_scope(doc))
    assert standards.list_requirements("doc_f", allowed_document_ids=_scope(doc)) == []


def test_a_standard_with_no_tables_has_a_null_fraction_not_zero(tmp_path):
    """None is "nothing to read"; 0.0 is "read nothing of what was there"."""
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_n", pdf)
    _chunk("c1", doc, "just prose", kind="prose", page=1)
    report = standards.table_report("doc_n", allowed_document_ids=_scope(doc))
    assert report["tables_total"] == 0
    assert report["parsed_fraction"] is None


def test_character_fragmentation_is_not_accepted_as_a_table(tmp_path):
    """The measured failure that made the quality gate necessary: a scanned
    page recovers `['DE','F','I','N','IT','I','O','N']` - the word DEFINITION
    cut into columns by letter spacing.

    THIS GOES THROUGH `parse_document_tables`, NOT THROUGH THE PREDICATE. The
    first version of this test called `_is_fragmented` directly, which proved
    the predicate works and nothing about whether the pipeline uses it -
    mutation M47 deleted the call site and the test still passed. A unit test
    of a helper is not a test of the behaviour that depends on it.
    """
    pdf = _ruled_table_pdf(tmp_path / "frag.pdf",
                           ["D", "E", "F", "I"], [["N", "I", "T", "I"]])
    doc = _doc("doc_frag", pdf)
    _chunk("c1", doc, "fragments", kind="table", page=1)
    parses = tables.parse_document_tables("doc_frag", allowed_document_ids=_scope(doc))
    assert len(parses) == 1
    assert parses[0].parsed is False, "letter fragments were accepted as a table"
    assert parses[0].unparsed_reason
    # And a genuine table on the same code path IS accepted, so the gate is
    # not simply refusing everything.
    good = _ruled_table_pdf(tmp_path / "good.pdf",
                            ["Pile Use Category", "Retention (pcf)"],
                            [["Foundation", "12"]])
    doc2 = _doc("doc_good", good, "GOOD.pdf")
    _chunk("c2", doc2, "table", kind="table", page=1)
    good_parses = tables.parse_document_tables(
        "doc_good", allowed_document_ids=_scope(doc2))
    assert good_parses[0].parsed is True, good_parses[0].unparsed_reason


def test_a_cell_that_is_not_a_number_is_not_recorded_as_a_value(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf",
                           ["Category", "Note (pcf)"], [["Foundation", "see 5.2"]])
    doc = _doc("doc_t", pdf)
    _chunk("c1", doc, "table", kind="table", page=1)
    standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    assert standards.list_requirements("doc_t", allowed_document_ids=_scope(doc)) == []


def _ruled_grid_pdf(path, all_rows) -> str:
    """A one-page PDF with a REAL ruled grid drawn exactly as given - no
    header/data split, so a MULTI-ROW header (a merged span written once and
    left blank under the rest of its width, continued on a second and third
    line) can be reproduced faithfully instead of forced through
    `_ruled_table_pdf`'s single-header-row shape.
    """
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=900, height=400)
    x0, y0, cw, rh = 40, 60, 90, 30
    for r, row in enumerate(all_rows):
        for c, cell in enumerate(row):
            rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh,
                             x0 + (c + 1) * cw, y0 + (r + 1) * rh)
            page.draw_rect(rect, color=(0, 0, 0), width=0.7)
            if cell:
                page.insert_text((rect.x0 + 4, rect.y0 + 19), str(cell), fontsize=9)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_a_merged_multi_row_header_still_names_its_column(tmp_path):
    """THE MUTATION TARGET (M370). Measured on the live corpus: of the 4,246
    table-derived requirements that carry a `table_row`, 2,983 (70%) have no
    `field` at all - `standard_requirements.field IS NULL` - because a wide
    table's header spans more than one physical column (a super-header like
    "Red Sea" over "Marine"/"High value"/"Industrial", itself over region
    codes "(C1)"/"(C2)"/"(C3)") and PyMuPDF's `find_tables` repeats a merged
    cell's text once and leaves every column beneath it BLANK in that row.
    Reading row 0 alone as "the header" (the old behaviour) hands
    `requirements_3b.field_name` an empty string for every column after the
    first in each span, and it correctly refuses to invent a name from
    nothing - so the column identity that WAS on the page is lost before it
    ever reaches `field_name`.

    This is the same shape as B175's `pairs_from_table_shape` fix for
    datasheets (`datasheets.py`, carry-forward + second-header-line merge,
    M366/M367) - ported here for STANDARDS documents, where it was still
    missing.
    """
    pdf = _ruled_grid_pdf(tmp_path / "region.pdf", [
        ["Parameter", "Unit", "Red Sea", "", "Gulf", ""],
        ["", "", "Marine", "Industrial", "Marine", "Industrial"],
        ["Xylenes", "mg/L", "12", "20", "14", "22"],
    ])
    doc = _doc("doc_region", pdf)
    _chunk("c1", doc, "table", kind="table", page=1)

    parses = tables.parse_document_tables("doc_region", allowed_document_ids=_scope(doc))
    assert len(parses) == 1
    assert parses[0].parsed is True, parses[0].unparsed_reason
    # Every column after the label carries the region it actually belongs to
    # - not a blank cut off by the merge.
    assert all(c for c in parses[0].columns[1:]), parses[0].columns

    standards.extract_table_values("doc_region", allowed_document_ids=_scope(doc))
    rows = standards.list_requirements("doc_region", allowed_document_ids=_scope(doc))
    assert rows, "no requirements were written from a real ruled table"
    fields = {r["field"] for r in rows}
    assert None not in fields, "a table cell was recorded with no column identity"
    # The two "Marine" columns (Red Sea and Gulf) must not collapse into one
    # indistinguishable field - the super-header disambiguates them.
    marine_fields = {f for f in fields if "Marine" in f}
    assert len(marine_fields) == 2, marine_fields
    assert any("Red Sea" in f for f in marine_fields)
    assert any("Gulf" in f for f in marine_fields)


# ========================================================= limits and exceptions

@pytest.mark.parametrize(
    ("sentence", "operator", "value"),
    [
        # The four wordings found flipped in the live corpus, one per spelling
        # of the negation the pattern used to walk past.
        ("The closure door clearance shall not be less than 45 m.", ">=", "45"),
        ("The lifting capacity shall be not less than 900 kg.", ">=", "900"),
        ("Availability shall be no less than 99.95% per component.", ">=", "99.95"),
        ("Dead-end lines shall not be greater than 20.7 meters.", "<=", "20.7"),
        ("The wall thickness shall not be more than 12 mm.", "<=", "12"),
        # A negation four words away from the comparative it negates. Nothing
        # between them is a comparator, so the phrase has to match whole.
        ("The flow, but in no case shall it be less than 190 l/s.", ">=", "190"),
        ("The pressure, in no case shall it be more than 222 kPa.", "<=", "222"),
        ("The stress shall in no case shall exceed 100% of the BSL.", "<=", "100"),
        # ... and the BARE comparisons, which must keep pointing the other way.
        ("The gap shall be less than 5 mm.", "<", "5"),
        ("The pressure shall be greater than 300 kPa.", ">", "300"),
    ],
)
def test_a_negated_comparison_is_not_read_as_the_bare_one(sentence, operator, value):
    """A flipped operator passes a non-compliant value and fails a compliant
    one, with a citation attached - worse than extracting no rule at all.

    "shall not be less than 45 m" was stored as `< 45`: no alternative in
    `_LIMIT` covered the "be", so the scan walked past the negation and matched
    the bare "less than" behind it. 129 of 1,731 stored limits across 79
    standards carried a flipped operator. The bare rows are here too, because
    a fix that swallowed them would be the same defect pointing the other way.
    """
    limit = requirements_3b.parse_limit(sentence)
    assert limit is not None, sentence
    assert limit["operator"] == operator
    assert limit["raw_value"] == value


@pytest.mark.parametrize(
    ("phrase", "operator"),
    [
        ("not be less than", ">="), ("no less than", ">="), ("not less than", ">="),
        ("not be greater than", "<="), ("no more than", "<="),
        ("in no case shall it be less than", ">="),
        ("in no case shall exceed", "<="),
        ("less than", "<"), ("greater than", ">"),
    ],
)
def test_the_comparator_vocabulary_reads_the_negation_too(phrase, operator):
    """The same gap lived in `claims`, which anchors this vocabulary at the end
    of the text before a measurement. Fixed in one home only, a limit parsed
    through `claims.measurements` would still come out inverted.
    """
    assert claims.parse_comparator(phrase) == operator


@pytest.mark.parametrize(("sentence", "operator", "value", "unit"), [
    # SAES-A-105 5.3.3 - the standard's PRIMARY limit. The corpus held its
    # four exceptions ("may not exceed 105/97/105/115 dB(A)") and not the rule
    # they are exceptions to.
    ("New equipment shall not generate noise in excess of 90 dB(A) at a"
     " distance of one meter.", "<=", "90", "dB(A)"),
    # The same comparison with different prose in the middle.
    ("The design pressure shall not be in excess of 6,900 kPa.",
     "<=", "6,900", "kPa"),
    # `claims` already read this through its bare "not exceed"; `_LIMIT` did not.
    ("The coating thickness should not exceed 12 mm.", "<=", "12", "mm"),
])
def test_a_negated_in_excess_of_is_the_limit_it_states(
        sentence, operator, value, unit):
    limit = requirements_3b.parse_limit(sentence)
    assert limit is not None, sentence
    assert limit["operator"] == operator
    assert limit["raw_value"] == value
    assert limit["raw_unit"] == unit


@pytest.mark.parametrize("sentence", [
    # THE NEGATIVE CONTROLS, AND THE REAL RISK IN THE CHANGE. Bare "in excess
    # of" is a TRIGGER: it says what to do WHEN a value is exceeded, and
    # forbids nothing. Reading one as a limit invents a ceiling no standard
    # states - a false rule, which is worse than a missing one because it
    # fails a compliant submittal with a citation attached.
    #
    # 1. Obliges a SUBMISSION, not a maximum.
    "Equipment that will generate noise in excess of 85 dB(A) shall have a"
    " Noise Control Data Sheet, Form 7305-ENG, submitted for review.",
    # 2. Obliges a JUSTIFICATION, not a maximum.
    "Oxygen transfer rates in excess of 1.22 kg/kWh shall be justified.",
    # 3. NEGATED, and still not a rule: it states no number of its own, the
    #    limit being in a table it points at.
    #
    #    WHAT ACTUALLY HOLDS THIS ONE BACK is the requirement that a digit
    #    follow the comparator, NOT the four-word bound between the negation
    #    and the phrase - seven words sit in this sentence, but "of those
    #    listed" is what stops it. Proven by mutation: widening the gap to
    #    twelve words leaves this test green. Said plainly here because a
    #    comment claiming the wrong guard is how a check gets deleted later
    #    on the grounds that something else covers it.
    "Personnel shall not be exposed to continuous occupational noise levels"
    " in excess of those listed in Table 3.",
])
def test_a_bare_in_excess_of_is_a_trigger_and_never_becomes_a_rule(sentence):
    assert requirements_3b.parse_limit(sentence) is None, sentence


@pytest.mark.parametrize(("sentence", "comparator"), [
    ("New equipment shall not generate noise in excess of 90 dB.", "<="),
    ("The design pressure shall not be in excess of 6900 kPa.", "<="),
    ("The coating thickness should not exceed 12 mm.", "<="),
    # The negative control again, through the OTHER home: the trigger sentence
    # must yield a measurement with NO comparator, not a maximum.
    ("Equipment that will generate noise in excess of 85 dB shall have a"
     " data sheet submitted for review.", None),
    ("Oxygen transfer rates in excess of 1.22 kg shall be justified.", None),
])
def test_the_second_home_reads_the_same_phrases(sentence, comparator):
    """Both homes, because eddf080 established that one is never enough.

    Through `extract_measurements` rather than `parse_comparator`: the latter
    full-matches a phrase handed to it, while the real path anchors the
    vocabulary at the end of the text before a number. A test of the first
    would pass or fail for reasons the pipeline never encounters.
    """
    found = claims.extract_measurements(sentence)
    assert len(found) == 1, f"expected one measurement in {sentence!r}"
    assert found[0].comparator == comparator


@pytest.mark.parametrize(("sentence", "limit", "contradicts"), [
    # The shape that cost this corpus 129 rows.
    ("The clearance shall not be less than 45 m.", {"operator": "<", "raw_value": "45"}, True),
    ("The clearance shall not be less than 45 m.", {"operator": ">=", "raw_value": "45"}, False),
    ("In no case shall exceed 100% of the BSL.", {"operator": ">", "raw_value": "100"}, True),
    # TWO LIMITS IN ONE SENTENCE, both directions. This is the case that makes
    # the check read the phrase before its OWN value instead of scanning the
    # sentence: scanning found 129 rows of which 25 were correct rows like
    # this one, flagged because the other half of their sentence disagreed.
    ("The flow shall not be less than 63 L/s but shall not exceed 252 L/s.",
     {"operator": ">=", "raw_value": "63"}, False),
    ("The flow shall not be less than 63 L/s but shall not exceed 252 L/s.",
     {"operator": "<=", "raw_value": "63"}, True),
    # SILENT WHEN IT CANNOT TELL, rather than firing on uncertainty.
    ("The pressure is 300 kPa.", {"operator": "<=", "raw_value": "300"}, False),
    ("The level shall not exceed 90 dB(A).", {"operator": "<=", "raw_value": "90"}, False),
    # A FLATTENED TABLE states one number in BOTH directions. Measured: these
    # were the only four rows the check reported across 272 standards on its
    # first run, and every one of them was correct - the row came from the
    # second occurrence. One reading that supports the row clears it.
    ("Carbon Steels P-1 Less than or equal to 5 None. Greater than 5 and equal"
     " to or less than 10 PWHT per the applicable Code.",
     {"operator": ">", "raw_value": "5"}, False),
    ("Applicable for fluid internal temperature up to 50 C, it shall be"
     " adjusted for fluid temperature more than 50 C.",
     {"operator": "<=", "raw_value": "50"}, False),
    # ... and it stays silent on that sentence in the OTHER direction too,
    # because "up to" is in this module's vocabulary and not in `claims`', so
    # the first occurrence reads as no comparator at all - a reading that
    # cannot be ruled out. Silence is the honest answer until the two
    # vocabularies are made one; firing here would be a guess dressed as a
    # finding.
    ("Applicable for fluid internal temperature up to 50 C, it shall be"
     " adjusted for fluid temperature more than 50 C.",
     {"operator": ">=", "raw_value": "50"}, False),
])
def test_a_limit_that_contradicts_its_own_sentence_is_detected(
        sentence, limit, contradicts):
    assert requirements_3b.contradicts_source(limit, sentence) is contradicts


def test_a_contradicted_limit_is_held_below_the_verification_threshold(tmp_path):
    """NOT DROPPED, and not published either.

    Dropping it would lose a real obligation and say nothing about it.
    Publishing it puts a rule in the library that passes a non-compliant value
    and fails a compliant one, with a correct clause and page attached - the
    one failure checking the citation cannot catch.
    """
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_contra", pdf)
    # A sentence whose own parser gets it RIGHT, so the fixture proves the
    # wiring rather than a parser bug: the check is driven directly below.
    _chunk("c1", doc, "The clearance shall not be less than 45 m.",
           section="9.2.2 Clearance", page=12)

    original = requirements_3b.contradicts_source
    try:
        requirements_3b.contradicts_source = lambda limit, sentence: True
        result = standards.extract_requirements("doc_contra", allowed_document_ids=_scope(doc))
    finally:
        requirements_3b.contradicts_source = original

    assert result["contradicted_source"] == 1
    rows = standards.list_requirements("doc_contra", allowed_document_ids=_scope(doc))
    assert len(rows) == 1
    assert rows[0]["confidence"] == standards.CONTRADICTED_CONFIDENCE
    assert rows[0]["confidence"] < standards.VERIFICATION_THRESHOLD
    assert standards.needs_verification(rows[0]) is True


def test_an_ordinary_limit_is_not_held_back(tmp_path):
    """The control. A check that holds everything back is not a check."""
    pdf = _ruled_table_pdf(tmp_path / "t2.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_clean", pdf)
    _chunk("c1", doc, "The clearance shall not be less than 45 m.",
           section="9.2.2 Clearance", page=12)

    result = standards.extract_requirements("doc_clean", allowed_document_ids=_scope(doc))

    assert result["contradicted_source"] == 0
    rows = standards.list_requirements("doc_clean", allowed_document_ids=_scope(doc))
    assert rows[0]["confidence"] > standards.CONTRADICTED_CONFIDENCE
    assert rows[0]["operator"] == ">="


def test_the_psv_exception_is_preserved_beside_the_general_limit():
    """THE MUTATION TARGET (M42). The master plan's worked case.

    An exception that is dropped turns a compliant pressure relief valve into
    a false finding.
    """
    limit = requirements_3b.parse_limit(NOISE)
    assert limit["operator"] == "<="
    assert limit["raw_value"] == "90"
    assert limit["raw_unit"] == "dB(A)"

    exceptions = requirements_3b.parse_exceptions(NOISE)
    assert len(exceptions) == 1
    assert "pressure relief valve" in exceptions[0]["applies_to"].lower()
    # THE EXCEPTION CARRIES ITS OWN LIMIT, which is the whole point.
    assert exceptions[0]["raw_value"] == "115"
    assert exceptions[0]["operator"] == "<="


def test_the_exception_is_stored_and_read_back_on_the_requirement(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_s", pdf)
    _chunk("c1", doc, NOISE, section="5.3.3 Noise", page=9)
    standards.extract_requirements("doc_s", allowed_document_ids=_scope(doc))
    row = standards.list_requirements("doc_s", allowed_document_ids=_scope(doc))[0]
    assert row["requirement_type"] == "numeric_limit"
    assert row["raw_value"] == "90"
    assert len(row["exceptions"]) == 1
    assert row["exceptions"][0]["raw_value"] == "115"
    assert "pressure relief valve" in row["exceptions"][0]["applies_to"].lower()


def test_may_not_exceed_is_a_numeric_prohibition_with_no_space_before_unit(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_prohibition", pdf)
    source = "The safety alarm may not exceed 115dB(A)."
    _chunk("c-prohibition", doc, source, section="5.3.3 Noise", page=9)

    result = standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    rows = standards.list_requirements(doc, allowed_document_ids=_scope(doc))

    assert result["requirements"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "prohibition"
    assert row["clause"] == "5.3.3"
    assert row["page"] == 9
    assert row["operator"] == "<="
    assert row["raw_value"] == "115"
    assert row["raw_unit"] == "dB(A)"
    assert row["source_text"] == source


def test_numbered_prohibitions_keep_inline_clause_and_spaced_acoustic_unit(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_numbered_prohibition", pdf)
    source = (
        "5.3.3 Equipment shall meet the general noise criterion. "
        "Exceptions are: 1) Fans may not exceed 105 dB(A); "
        "2) Emergency vents may not exceed 115dB (A)."
    )
    _chunk("c-numbered", doc, source, section="5.3.1 Noise", page=9)

    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    rows = standards.list_requirements(doc, allowed_document_ids=_scope(doc))
    prohibition = next(row for row in rows if row["raw_value"] == "115")

    assert prohibition["category"] == "prohibition"
    assert prohibition["clause"] == "5.3.3"
    assert prohibition["page"] == 9
    assert prohibition["operator"] == "<="
    assert prohibition["raw_unit"] == "dB(A)"
    assert prohibition["source_text"].startswith("2) Emergency vents")


def test_must_not_is_recorded_as_a_prohibition(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_must_not", pdf)
    _chunk("c-must-not", doc, "The vessel must not exceed 12 bar.",
           section="6.1 Pressure", page=7)

    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    assert row["category"] == "prohibition"
    assert row["operator"] == "<="
    assert row["raw_value"] == "12"
    assert row["raw_unit"] == "bar"


# ============================================== required evidence type (new field)

def test_a_requirement_that_names_evidence_records_its_type(tmp_path):
    """THE MUTATION TARGET (M371). Part 3's contract review: no existing
    column says what document satisfies a clause - `category` is only ever
    'prohibition' or None, `requirement_type` is the clause's SHAPE. This is
    genuinely additive.

    Populated only because the sentence itself both names a submission verb
    and a document noun from the fixed vocabulary.
    """
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_evidence", pdf)
    source = ("The pressure test relief valve shall be accompanied with a "
               "calibration certificate that includes the test date.")
    _chunk("c-evidence", doc, source, section="7.1 Testing", page=4)

    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    assert row["required_evidence_type"] == "certificate"
    # And it still resolves like every other field.
    assert row["source_text"] == source


def test_a_requirement_with_no_evidence_noun_stays_null_not_guessed(tmp_path):
    """A limit with nothing to submit must not be handed a fabricated type."""
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_no_evidence", pdf)
    _chunk("c-no-evidence", doc, "The vessel must not exceed 12 bar.",
           section="6.1 Pressure", page=7)

    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    assert row["required_evidence_type"] is None


def test_a_submission_verb_alone_with_no_named_document_stays_null(tmp_path):
    """"Shall be verified" has an obligation but nothing to hand over - not a
    submission verb from this vocabulary, and no document noun either."""
    assert requirements_3b.required_evidence_type(
        "The weld quality shall be verified prior to installation.") is None


def test_an_evidence_noun_with_no_submission_verb_is_not_enough_alone():
    """THE MUTATION TARGET for the verb gate specifically. "have a valid
    certificate" names the noun but uses none of this vocabulary's
    submission verbs - the sentence never says anything must be HANDED OVER,
    so this must stay None rather than firing off the noun alone.
    """
    assert requirements_3b.required_evidence_type(
        "The vessel shall have a valid certificate of conformance.") is None


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("The vendor shall submit vendor drawings for approval.", "drawing"),
        ("The contractor shall provide a hydrotest report.", "report"),
        ("Material shall be traceable to manufacturer's test certificates.",
         "certificate"),
        ("The supplier shall furnish a data sheet for each item.", "data_sheet"),
        ("A welding procedure shall be submitted for review.", "procedure"),
    ],
)
def test_required_evidence_type_across_the_fixed_vocabulary(sentence, expected):
    assert requirements_3b.required_evidence_type(sentence) == expected


@pytest.mark.parametrize("description", [
    "This arrangement may not be practical in all locations.",
    "The final information may not be available before design review.",
])
def test_descriptive_may_not_is_not_a_requirement(tmp_path, description):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_description", pdf)
    _chunk("c-description", doc, description, section="6.2 Commentary", page=8)

    result = standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    assert result["requirements"] == 0
    assert standards.list_requirements(doc, allowed_document_ids=_scope(doc)) == []


def test_a_condition_is_the_circumstance_not_the_subject():
    """A wrong condition NARROWS a requirement and silently excuses a real
    deviation - the opposite failure from a wrong limit, and harder to see."""
    assert requirements_3b.parse_condition(
        "For new equipment, the noise level shall not exceed 90 dB(A).") == "new equipment"
    # A purpose is not a condition.
    assert requirements_3b.parse_condition(
        "The coating shall be applied for corrosion protection.") is None


def test_an_obligation_with_no_recognised_limit_is_a_statement(tmp_path):
    """No requirement_type is invented for text the parser did not understand."""
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_s", pdf)
    _chunk("c1", doc, "The surface shall be prepared in accordance with Sa 2.5.",
           section="5.1 Preparation", page=2)
    standards.extract_requirements("doc_s", allowed_document_ids=_scope(doc))
    row = standards.list_requirements("doc_s", allowed_document_ids=_scope(doc))[0]
    assert row["requirement_type"] == "statement"
    # NOT a numeric_limit carrying a null value, which reads as a limit nobody
    # bothered to record.
    assert row["value"] is None
    assert row["operator"] is None


def test_the_discipline_is_stamped_from_the_classification(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_s", pdf)
    _chunk("c1", doc, NOISE, section="5.3.3 Noise", page=9)
    standards.extract_requirements("doc_s", allowed_document_ids=_scope(doc))
    row = standards.list_requirements("doc_s", allowed_document_ids=_scope(doc))[0]
    assert row["discipline"] == "Mechanical"


# ================================================================== conflicts

def test_two_standards_limiting_the_same_field_differently_is_a_conflict(tmp_path):
    """THE MUTATION TARGET (M43). Surfaced, never resolved."""
    a = _doc("doc_a", _ruled_table_pdf(tmp_path / "a.pdf", ["Field (mm)"], [["1"]]),
             "A.pdf")
    b = _doc("doc_b", _ruled_table_pdf(tmp_path / "b.pdf", ["Field (mm)"], [["1"]]),
             "B.pdf")
    _chunk("ca", a, "x", section="5.1 T", page=1)
    _chunk("cb", b, "x", section="5.1 T", page=1)
    for doc, chunk, value in ((a, "ca", 12.0), (b, "cb", 20.0)):
        standards.create_requirement(
            standard_document_id=doc, chunk_id=chunk,
            requirement_text="t", source_text="t", clause="5.1", page=1,
            structured={"field": "coating thickness", "operator": ">=",
                        "value": value, "unit": "um",
                        "requirement_type": "numeric_limit"})
    found = standards.conflicts(allowed_document_ids=_scope(a, b))
    assert len(found) == 1
    assert found[0]["field"] == "coating thickness"
    assert {r["standard_document_id"] for r in found[0]["requirements"]} == {a, b}
    # NOT RESOLVED: both sides are returned, neither is marked the winner.
    assert len(found[0]["requirements"]) == 2
    assert all("winner" not in r for r in found[0]["requirements"])


def test_the_same_limit_in_two_standards_is_not_a_conflict(tmp_path):
    a = _doc("doc_a", _ruled_table_pdf(tmp_path / "a.pdf", ["A"], [["1"]]), "A.pdf")
    b = _doc("doc_b", _ruled_table_pdf(tmp_path / "b.pdf", ["A"], [["1"]]), "B.pdf")
    _chunk("ca", a, "x", page=1); _chunk("cb", b, "x", page=1)
    for doc, chunk in ((a, "ca"), (b, "cb")):
        standards.create_requirement(
            standard_document_id=doc, chunk_id=chunk, requirement_text="t",
            source_text="t", clause=None, page=1,
            structured={"field": "thickness", "operator": ">=", "value": 12.0,
                        "unit": "um"})
    assert standards.conflicts(allowed_document_ids=_scope(a, b)) == []


def test_values_that_cannot_be_compared_are_not_called_a_conflict(tmp_path):
    """An unknown unit leaves value NULL. Two numbers this system cannot
    compare are not evidence of disagreement, and claiming one would invent a
    finding."""
    a = _doc("doc_a", _ruled_table_pdf(tmp_path / "a.pdf", ["A"], [["1"]]), "A.pdf")
    b = _doc("doc_b", _ruled_table_pdf(tmp_path / "b.pdf", ["A"], [["1"]]), "B.pdf")
    _chunk("ca", a, "x", page=1); _chunk("cb", b, "x", page=1)
    standards.create_requirement(
        standard_document_id=a, chunk_id="ca", requirement_text="t",
        source_text="t", clause=None, page=1,
        structured={"field": "noise", "operator": "<=", "value": None,
                    "raw_value": "90", "raw_unit": "dB(A)"})
    standards.create_requirement(
        standard_document_id=b, chunk_id="cb", requirement_text="t",
        source_text="t", clause=None, page=1,
        structured={"field": "noise", "operator": "<=", "value": 85.0,
                    "unit": "dB"})
    assert standards.conflicts(allowed_document_ids=_scope(a, b)) == []


def test_one_standard_restating_itself_is_not_a_conflict(tmp_path):
    a = _doc("doc_a", _ruled_table_pdf(tmp_path / "a.pdf", ["A"], [["1"]]), "A.pdf")
    _chunk("ca", a, "x", page=1)
    for value in (12.0, 20.0):
        standards.create_requirement(
            standard_document_id=a, chunk_id="ca", requirement_text="t",
            source_text="t", clause=None, page=1,
            structured={"field": "thickness", "operator": ">=", "value": value,
                        "unit": "um"})
    assert standards.conflicts(allowed_document_ids=_scope(a)) == []


# ========================================================== verification queue

def _user(uid="u1"):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users"
            " (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,?,1,?)",
            (uid, f"{uid}@example.test", uid, "x", "2026-09-18T00:00:00Z"))
    return uid


def _one_low_confidence(tmp_path, doc_id="doc_q"):
    pdf = _ruled_table_pdf(tmp_path / f"{doc_id}.pdf", ["A"], [["1"]])
    doc = _doc(doc_id, pdf)
    _chunk(f"c-{doc_id}", doc, "x", page=1)
    return doc, standards.create_requirement(
        standard_document_id=doc, chunk_id=f"c-{doc_id}",
        requirement_text="The valve shall be rated.", source_text="src",
        clause=None, page=1, confidence=0.5)


def test_a_low_confidence_requirement_is_in_the_queue(tmp_path):
    doc, row = _one_low_confidence(tmp_path)
    queue = standards.verification_queue(allowed_document_ids=_scope(doc))
    assert [q["id"] for q in queue] == [row["id"]]
    assert queue[0]["needs_verification"] is True


def test_an_engineer_correction_flips_extraction_method_to_human_and_audits(tmp_path):
    """THE MUTATION TARGET (M44). A guess becomes a person's statement."""
    doc, row = _one_low_confidence(tmp_path)
    user = _user()
    before = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]
    assert before["extraction_method"] == "extracted"

    updated = standards.decide_requirement(
        row["id"], decision="edit", allowed_document_ids=_scope(doc),
        actor={"id": user, "email": "eng@example.test"},
        edits={"requirement_text": "The valve shall be rated for 10 bar.",
               "field": "rating", "operator": ">=", "value": 10.0, "unit": "bar"})

    assert updated["extraction_method"] == "human"
    assert updated["confirmed_by"] == user
    assert updated["requirement_text"].endswith("10 bar.")
    assert updated["value"] == 10.0
    # AUDITED.
    audit = db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'standard.requirement_edited'"
    ).fetchone()
    assert audit is not None, "an engineer correction wrote no audit row"
    assert audit["resource_id"] == doc
    # And it leaves the queue.
    assert standards.verification_queue(allowed_document_ids=_scope(doc)) == []


def test_confirming_leaves_the_queue_without_changing_the_text(tmp_path):
    doc, row = _one_low_confidence(tmp_path)
    user = _user()
    updated = standards.decide_requirement(
        row["id"], decision="confirm", allowed_document_ids=_scope(doc),
        actor={"id": user, "email": "e@example.test"})
    assert updated["extraction_method"] == "human"
    assert updated["requirement_text"] == "The valve shall be rated."
    assert standards.verification_queue(allowed_document_ids=_scope(doc)) == []


def test_rejecting_deletes_the_row_and_keeps_the_audit(tmp_path):
    doc, row = _one_low_confidence(tmp_path)
    user = _user()
    standards.decide_requirement(
        row["id"], decision="reject", allowed_document_ids=_scope(doc),
        actor={"id": user, "email": "e@example.test"})
    assert standards.list_requirements(doc, allowed_document_ids=_scope(doc)) == []
    audit = db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'standard.requirement_rejected'"
    ).fetchone()
    assert audit is not None, "the record that somebody looked and said no is gone"


def test_an_unknown_decision_is_refused(tmp_path):
    doc, row = _one_low_confidence(tmp_path)
    with pytest.raises(standards.RequirementError):
        standards.decide_requirement(row["id"], decision="approve",
                                     allowed_document_ids=_scope(doc))


# ================================================================ permissions

def test_an_unauthorised_user_sees_no_requirement_no_conflict_no_queue(tmp_path):
    """THE MUTATION TARGET (M45)."""
    mine, _ = _one_low_confidence(tmp_path, "doc_mine")
    theirs, their_row = _one_low_confidence(tmp_path, "doc_theirs")
    for doc, chunk in ((mine, "c-doc_mine"), (theirs, "c-doc_theirs")):
        standards.create_requirement(
            standard_document_id=doc, chunk_id=chunk, requirement_text="t",
            source_text="t", clause=None, page=1,
            structured={"field": "thickness", "operator": ">=",
                        "value": 12.0 if doc == mine else 20.0, "unit": "um"})

    only_mine = _scope(mine)
    assert standards.list_requirements(theirs, allowed_document_ids=only_mine) == []
    assert standards.verification_queue(allowed_document_ids=only_mine) and all(
        q["standard_document_id"] == mine
        for q in standards.verification_queue(allowed_document_ids=only_mine))
    # A conflict needs BOTH sides; with only one readable there is nothing to
    # report - and reporting one side would disclose that the other exists.
    assert standards.conflicts(allowed_document_ids=only_mine) == []
    assert standards.table_report(theirs, allowed_document_ids=only_mine)["tables_total"] == 0
    with pytest.raises(standards.RequirementError):
        standards.decide_requirement(their_row["id"], decision="confirm",
                                     allowed_document_ids=only_mine)


def test_an_empty_grant_set_sees_nothing(tmp_path):
    doc, _ = _one_low_confidence(tmp_path)
    empty = frozenset()
    assert standards.verification_queue(allowed_document_ids=empty) == []
    assert standards.conflicts(allowed_document_ids=empty) == []
    assert standards.table_report(doc, allowed_document_ids=empty)["tables_total"] == 0
    assert tables.parse_document_tables(doc, allowed_document_ids=empty) == []


@pytest.mark.parametrize("call", [
    lambda: standards.verification_queue(),
    lambda: standards.conflicts(),
    lambda: standards.table_report("d"),
    lambda: standards.extract_table_values("d"),
    lambda: standards.decide_requirement("r", decision="confirm"),
    lambda: tables.parse_document_tables("d"),
])
def test_a_caller_that_forgets_the_filter_raises_typeerror(call):
    with pytest.raises(TypeError):
        call()


# =========================================================== background job

def test_extraction_can_be_queued_and_drained_by_the_existing_worker(tmp_path):
    """THE MUTATION TARGET (M46). One worker, lowest priority."""
    pdf = _ruled_table_pdf(tmp_path / "t.pdf",
                           ["Category", "Retention (pcf)"], [["Foundation", "12"]])
    doc = _doc("doc_j", pdf)
    _chunk("c1", doc, NOISE, section="5.3.3 Noise", page=1)
    _chunk("c2", doc, "table", kind="table", page=1)

    job_id = standards.enqueue_extraction(doc)
    assert job_id
    state = standards.extraction_job_state(doc, allowed_document_ids=_scope(doc))
    assert state["state"] == "queued"

    # Queuing does not extract. The work happens on the worker.
    assert standards.list_requirements(doc, allowed_document_ids=_scope(doc)) == []

    assert standards.next_extraction_job() == doc
    standards.run_extraction_job(doc)

    rows = standards.list_requirements(doc, allowed_document_ids=_scope(doc))
    assert rows, "the drained job produced no requirements"
    assert any(r["requirement_type"] == "numeric_limit" for r in rows)
    assert any(r["requirement_type"] == "table_value" for r in rows)
    assert standards.extraction_job_state(
        doc, allowed_document_ids=_scope(doc))["state"] == "done"


def test_queuing_twice_does_not_stack_two_jobs(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["A"], [["1"]])
    doc = _doc("doc_j", pdf)
    assert standards.enqueue_extraction(doc) == standards.enqueue_extraction(doc)
    n = db.connect().execute(
        "SELECT COUNT(*) FROM jobs WHERE document_id = ? AND stage = ?",
        (doc, standards.EXTRACTION_STAGE)).fetchone()[0]
    assert n == 1


def test_no_second_worker_was_added():
    """Section 24 allows ONE ingestion/review worker. The standards queue is
    drained by that worker, not by a thread of its own."""
    import inspect

    from app import ingest
    source = inspect.getsource(ingest)
    assert "_drain_standard_extraction" in source
    # One Thread construction in the module, and it is the ingestion worker's.
    assert source.count("threading.Thread(") == 1


def test_the_job_state_is_not_readable_outside_the_callers_grants(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["A"], [["1"]])
    doc = _doc("doc_j", pdf)
    standards.enqueue_extraction(doc)
    assert standards.extraction_job_state(doc, allowed_document_ids=frozenset()) is None


# --------------------------------------------- the subject of a comparator-less
#
# `subject_phrase` used to open with `if not _LIMIT.search(sentence)` and a
# mandatory sentence stating a flat value - "shall be 8,300 kPa" - therefore
# lost its subject as well as its operator, value and unit. The subject is the
# key `comparison.match_by_containment` joins on, so a null one is a row that
# can never match a datasheet however well the rest of it is stored.

_NO_COMPARATOR = [
    # The worked case: a flat value, no comparator word anywhere.
    # The worked case. The subject is the WHOLE noun phrase, not a trimmed
    # head: `subject_of` is documented as "allowed to be long", and length is
    # what lets `match_by_containment` find a field name inside it.
    ("The allowable concrete bearing stress to be used for the design of base "
     "plates shall be 8,300 kPa.",
     "allowable concrete bearing stress to be used for the design of base plates"),
    # A leading circumstance. `subject_of` keeps the LAST comma-separated part,
    # so the rule is about the cables, not about the trench.
    ("For buried installations in open trench, the power cables shall be "
     "installed in conduit.", "power cables"),
    # A clause number in front of the subject, which `_SUBJECT_LEAD` strips.
    ("14.2 Backfill shall be free of material that may damage coatings.",
     "Backfill"),
    # "must", not "shall".
    ("The bend radius must follow the manufacturer's published minima.",
     "bend radius"),
    # "is to be", the third mandatory spelling `_MANDATORY_HERE` admits.
    ("The design life is to be stated in the purchase order.", "design life"),
]


@pytest.mark.parametrize("sentence,expected", _NO_COMPARATOR)
def test_a_sentence_with_no_comparator_still_has_a_subject(sentence, expected):
    assert requirements_3b.subject_phrase(sentence) is not None
    assert standards.subject_of(sentence) == expected


def test_the_first_mandatory_verb_ends_the_subject_not_the_last():
    """A subordinate clause carries its own "shall". Splitting on the last one
    would make the sentence about the container it describes rather than about
    the sample the obligation is on."""
    sentence = ("The drain sample shall be taken into an open container, such "
                "as a glass jar, which shall be internally coated.")
    assert requirements_3b.subject_phrase(sentence) == "The drain sample"


def test_a_flattened_heading_is_not_part_of_the_subject():
    """The extractor flattens a heading and the clause under it into one
    string. The subject is the clause's, and it starts after the heading."""
    sentence = ("Commentary Note: Cables and pipes shall be sleeved where they "
                "are incorporated in the foundation.")
    assert requirements_3b.subject_phrase(sentence) == "Cables and pipes"


def test_a_clause_number_is_not_cut_in_half_by_the_boundary_rule():
    """The stop inside "10.1" sits between two digits and is not a sentence
    boundary. Cutting there would leave a subject beginning "1 The"."""
    sentence = "10.1 The selection of the coating shall be by the proponent."
    assert requirements_3b.subject_phrase(sentence) == "10.1 The selection of the coating"
    assert standards.subject_of(sentence) == "selection of the coating"


_NO_SUBJECT = [
    # A cross-reference the extractor emitted without its noun phrase: the
    # obligation is "read that other document", and there is nothing in front
    # of the verb to be about.
    "shall be in accordance with SAEP-35.",
    "Shall conform to API 650 Section 5.",
    # A process instruction, same shape: the sentence says where the answer
    # lives, not what the rule is on.
    "shall be specified on the data sheet.",
    # Nothing but furniture before the verb. A bullet and a clause number are
    # not things a requirement can be about.
    "• shall be provided.",
    "7.3.3 shall apply.",
    # No mandatory verb at all: a flattened table cell.
    "Chromium (total) - : 0.5",
    "",
]


@pytest.mark.parametrize("sentence", _NO_SUBJECT)
def test_a_sentence_with_no_subject_gets_none_not_a_garbage_phrase(sentence):
    assert requirements_3b.subject_phrase(sentence) is None
    assert standards.subject_of(sentence) is None


_WITH_COMPARATOR = [
    "The noise level shall not exceed 90 dB(A).",
    "The scale density shall be less than 50 g/m2.",
    "Wall thickness shall be at least 12 mm.",
    "For new equipment, the sound pressure shall not exceed 85 dB(A).",
    "In no case shall it be less than 190 L/s.",
    "The maximum solids loading limit shall not exceed 5 g/L.",
    "New equipment shall not generate noise in excess of 90 dB(A).",
    "Burial depth shall be a minimum of 1 m.",
]


@pytest.mark.parametrize("sentence", _WITH_COMPARATOR)
def test_a_comparator_sentence_splits_exactly_where_it_always_did(sentence):
    """THE CONSTRAINT ON THE CHANGE, restated as a test. A sentence `_LIMIT`
    matches must take the branch it always took, character for character.

    Proven over the corpus as well as here: of the 34,938 stored requirement
    texts, 1,761 match `_LIMIT` and 1,742 produced a subject before this
    change; all 1,742 produce the identical string after it, and `subject_of`
    differs on none of the 1,761.
    """
    head = requirements_3b._LIMIT.split(sentence)[0]
    # `or None` is part of the old contract: "In no case shall it be less than
    # 190 L/s" has nothing before the comparator, and an empty head has always
    # been None rather than "". The new branch must not rescue it either - the
    # sentence matched `_LIMIT`, so it never reaches that branch at all.
    assert requirements_3b.subject_phrase(sentence) == (
        " ".join(head.split()).strip() or None)


def test_the_mandatory_verb_branch_is_unreachable_for_a_comparator_sentence():
    """The new branch cannot change an existing answer because it is only
    reached where the old function had already returned None."""
    sentence = "The vent shall be at least 300 mm above the platform."
    assert requirements_3b._LIMIT.search(sentence)
    # The head stops at "at least", not at "shall" - the comparator wins.
    assert requirements_3b.subject_phrase(sentence) == "The vent shall be"


# ================================================= requirement-level retrieval

def _classify(doc_id: str, **fields):
    """Set document_classification fields beyond `_doc`'s defaults, for the
    structured pre-filter tests."""
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db.connect() as conn:
        conn.execute(f"UPDATE document_classification SET {cols} "
                     "WHERE document_id = ?", [*fields.values(), doc_id])


def test_search_requirements_reuses_the_existing_hybrid_search(tmp_path, monkeypatch):
    """THE MUTATION TARGET (M372). Not a second search stack: this must call
    the SAME `search.search` everything else (Chat, Analysis) already uses -
    lexical + dense fused by RRF - rather than reimplementing ranking over
    `standard_requirements` directly. Proven by substituting the shared
    entrypoint and confirming the substitute is what actually ran.
    """
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_hybrid", pdf)
    _chunk("c1", doc, NOISE, section="5.3.3 Noise", page=9)
    standards.extract_requirements(doc, allowed_document_ids=_scope(doc))
    row = standards.list_requirements(doc, allowed_document_ids=_scope(doc))[0]

    calls = []

    def fake_search(query, *, limit, allowed_document_ids, **kw):
        calls.append({"query": query, "limit": limit,
                       "allowed_document_ids": allowed_document_ids, **kw})
        return {"hits": [{"chunk_id": row["chunk_id"], "score": 0.9,
                          "bm25": 1.2, "cosine": 0.5}]}

    monkeypatch.setattr(search_mod, "search", fake_search)
    results = standards.search_requirements(
        "noise limit", allowed_document_ids=_scope(doc))

    assert len(calls) == 1, "search_requirements did not call the shared hybrid search"
    # dense is never disabled - the same hybrid path everything else uses.
    assert calls[0].get("dense", True) is not False
    assert len(results) == 1
    assert results[0]["id"] == row["id"]
    assert results[0]["retrieval"]["chunk_id"] == row["chunk_id"]


def test_a_prefilter_narrows_the_scope_handed_to_retrieval_before_ranking(tmp_path, monkeypatch):
    """THE MUTATION TARGET (M373). CLAUDE.md rule 5: a filter may only
    NARROW what the caller already may read - intersection, never union.
    `discipline="Civil"` must remove the Mechanical standard from the id set
    retrieval is even given, not filter results after the fact.
    """
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    mech = _doc("doc_mech", pdf, "MECH.pdf")
    civil_pdf = _ruled_table_pdf(tmp_path / "c.pdf", ["a", "b"], [["1", "2"]])
    civil = _doc("doc_civil", civil_pdf, "CIVIL.pdf")
    _classify(civil, discipline_canonical="Civil")
    _chunk("c-mech", mech, NOISE, section="5.3.3 Noise", page=9)
    _chunk("c-civil", civil, NOISE, section="5.3.3 Noise", page=9)
    standards.extract_requirements(mech, allowed_document_ids=_scope(mech))
    standards.extract_requirements(civil, allowed_document_ids=_scope(civil))

    captured = {}

    def fake_search(query, *, limit, allowed_document_ids, **kw):
        captured["allowed_document_ids"] = allowed_document_ids
        return {"hits": []}

    monkeypatch.setattr(search_mod, "search", fake_search)
    standards.search_requirements(
        "noise limit", allowed_document_ids=_scope(mech, civil),
        discipline="Civil")

    assert captured["allowed_document_ids"] == frozenset({civil})


def test_an_empty_grant_and_an_empty_query_both_return_nothing(tmp_path):
    """1=0, never a permissive default - the same rule every other read in
    this module follows."""
    assert standards.search_requirements("noise", allowed_document_ids=frozenset()) == []
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["a", "b"], [["1", "2"]])
    doc = _doc("doc_q", pdf)
    assert standards.search_requirements("   ", allowed_document_ids=_scope(doc)) == []
