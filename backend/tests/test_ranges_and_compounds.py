"""Two numbers in one cell, and two fields in one label.

MEASURED ON THE CLIENT PSV SHEET. Seventeen values on it are range-shaped and
none of them parsed: `-3 to 55 C & 0 to 100%` is two quantities sharing a row,
`23.5 / 11.03 barg` is the design pressure and the operating pressure, and
`-3 to 121OC` writes its degree sign as a letter. Every one was recorded as
free text or dropped, so nothing on that sheet could be compared against a
rule that mentions temperature or pressure.

THREE SHAPES, EACH A RULE ABOUT FORM AND NOT ABOUT THIS SHEET:

  COMPOUND LABELS. `A/B <noun>` against a value carrying the same separator
  the same number of times becomes two facts. The shared noun travels to the
  half that lacks it. If the counts disagree the cell is NOT guessed at: one
  fact, raw text, no parsed value.

  RANGES. `A to B unit` and `A-B unit` keep both ends in `value_min` and
  `value_max`. A unit is required - a unitless `8 to 9` beside `Mechanical
  Notes` is the drum sheet's own table of contents, and it cost two junk
  facts before the rule was tightened. Nothing comparable is lost: `compare`
  needs a dimension, so a unitless range could never have been evaluated.

  DEGREE GLYPHS. `121OC` is 121 °C, and only immediately after a digit.

AND THE COMPARISON NEVER AVERAGES. A range is compared at the end the RULE
asks about - the top for "shall not exceed", the bottom for "shall be at
least" - because that is where the band would breach it. Against an
exact-equality rule there is no such end and the answer is a person.

Mutations: M181-M192, `python scripts/mutation_check.py --phase 14`.
"""

from __future__ import annotations

import pytest

from app import comparison, datasheets, db, submittal_review


# ==================================================== compound labels

@pytest.mark.parametrize("label,value,expected", [
    # The worked case: the trailing unit reaches the half that has none.
    ("Design/Operating pressure", "23.5 / 11.03 barg",
     [("Design pressure", "23.5 barg"), ("Operating pressure", "11.03 barg")]),
    # A bracketed note rides along on the half it was written against.
    ("Design/Operating pressure", "23.5 / 11.03 barg (Note - 3)",
     [("Design pressure", "23.5 barg"),
      ("Operating pressure", "11.03 barg (Note - 3)")]),
    # `&` pairs: each half already carries its own unit, nothing distributes.
    ("Ambient Temperature & Rel. humidity", "-3 to 55 C & 0 to 100%",
     [("Ambient Temperature", "-3 to 55 C"), ("Rel. humidity", "0 to 100%")]),
    # THE NOUN TRAVELS THE OTHER WAY when the bare word is on the right.
    ("Back press. Constant/Variable", "10.15psig/97.18psig",
     [("Back press. Constant", "10.15psig"),
      ("Back press. Variable", "97.18psig")]),
])
def test_a_compound_label_with_a_matching_value_becomes_two_facts(
        label, value, expected):
    assert datasheets.split_compound_pair(label, value) == expected


def test_a_unit_is_never_added_to_a_half_that_has_its_own():
    """THE WORST OUTCOME AVAILABLE HERE would be inventing a unit onto a
    number that already had one. `psig` on both halves, nothing appended."""
    pairs = datasheets.split_compound_pair(
        "Back press. Constant/Variable", "10.15psig/97.18psig")

    assert [v for _label, v in pairs] == ["10.15psig", "97.18psig"]


def test_a_mismatched_separator_count_is_one_fact_and_is_never_parsed():
    """TWO FIELDS, ONE NUMBER, NO WAY TO TELL WHICH IT ANSWERS.

    `Design/Operating pressure` beside a single `23.5 barg` could be either.
    Recording it against the compound label would attach a real number to a
    field that is half wrong, so the row keeps its text and no parsed value.
    """
    assert datasheets.split_compound_pair(
        "Design/Operating pressure", "23.5 barg") == [
        ("Design/Operating pressure", "23.5 barg")]
    # AND THE VALUE IS REFUSED, not merely left compound: `create_fact` drops
    # the parse for any label that still names two fields.
    assert datasheets.compound_label_parts("Design/Operating pressure")


@pytest.mark.parametrize("label", [
    # `&` tight inside a word is not a separator - splitting it produced a
    # field called `P`.
    "P&ID Reference",
    # A separator inside brackets belongs to what is bracketed. Splitting
    # this one turned a real value into an unparsed compound.
    "Specific heat ratio (Cp/Cv)",
    # Nothing to split.
    "Set pressure",
])
def test_a_label_that_is_not_compound_is_left_alone(label):
    assert datasheets.compound_label_parts(label) is None
    assert datasheets.split_compound_pair(label, "1.233") == [(label, "1.233")]


def test_a_compound_split_requires_both_halves_to_be_field_labels():
    """A split that produces something that is not a field name is not a
    split. `12/24` is a value written with a solidus, not two labels."""
    assert datasheets.compound_label_parts("12/24") is None


# ============================================================= ranges

@pytest.mark.parametrize("raw,low,high,unit", [
    ("-3 to 55 C", "-3", "55", "C"),
    ("4-28 cP", "4", "28", "cP"),
    ("21 to 60OC", "21", "60", "°C"),
    ("0.5 to 1.5 bar", "0.5", "1.5", "bar"),
])
def test_a_range_keeps_both_ends(raw, low, high, unit):
    assert datasheets.parse_range(raw) == (low, high, unit)


def test_a_negative_start_works():
    """`-3 to 121OC` is the sheet's design temperature. A pattern that read
    the minus as the separator would give 3 to 121 and lose the sign, which
    is the difference between a vessel rated for frost and one that is not."""
    assert datasheets.parse_range("-3 to 121OC") == ("-3", "121", "°C")


def test_a_bare_symbol_counts_as_a_unit():
    """THE GUARD ON THE UNIT REQUIREMENT. `0 to 100%` is the only genuine
    range on either sheet whose unit is a symbol rather than a word, so a
    unit test that demanded letters would drop it."""
    assert datasheets.parse_range("0 to 100%") == ("0", "100", "%")


@pytest.mark.parametrize("raw", ["8 to 9", "4 to 5", "1-3"])
def test_a_unitless_range_is_not_a_range(raw):
    """THE DRUM SHEET'S TABLE OF CONTENTS. `Mechanical Notes` against
    `8 to 9` means sheets 8 to 9. Two junk facts came from reading those as
    quantities, and requiring a unit loses nothing comparable - `compare`
    needs a dimension, so a unitless range could never be evaluated."""
    assert datasheets.parse_range(raw) is None


@pytest.mark.parametrize("raw", [
    "10-05-497",       # a P&ID reference: the trailing -497 refuses the match
    "10-05",           # low above high
    "340 psig",        # a single value
    "",
])
def test_what_is_not_a_range(raw):
    assert datasheets.parse_range(raw) is None


def test_a_descending_pair_is_refused_even_with_a_unit():
    """THE LOW-ABOVE-HIGH GUARD, WHERE IT ACTUALLY DECIDES. `10-05` is
    already refused for having no unit, so a fixture without one tests the
    unit rule twice and this guard not at all."""
    assert datasheets.parse_range("55 to -3 C") is None
    # AND THE SAME PAIR THE RIGHT WAY ROUND IS A RANGE, so this is not
    # passing because the parser stopped working.
    assert datasheets.parse_range("-3 to 55 C") == ("-3", "55", "C")


def test_prose_after_a_range_refuses_it_even_with_a_unit():
    """THE REMAINDER GUARD, WHERE IT ACTUALLY DECIDES. A measurement is the
    whole cell; words after it mean the cell was a sentence. `10-05-497` has
    no unit and so never reaches this check."""
    assert datasheets.parse_range("4 to 28 cP and rising") is None
    assert datasheets.parse_range("4 to 28 cP") == ("4", "28", "cP")
    # A BRACKETED NOTE IS NOT PROSE, for the same reason `measure_value`
    # allows one: datasheets write "(Note - 3)" after a real quantity.
    assert datasheets.parse_range("4 to 28 cP (Note - 3)") == ("4", "28", "cP")


def test_a_pid_reference_never_becomes_a_quantity_at_all():
    """IT MUST STAY OUT, not merely stay out of the range columns. The P&ID
    number is not a value by any path, and it was read as one - as the number
    10 - before `measure_value` learned to refuse prose."""
    assert datasheets.parse_range("10-05-497 & 556-05-512") is None
    assert datasheets.measure_value("10-05-497 & 556-05-512")[0] is None


def test_a_single_value_is_untouched_by_the_range_path():
    """min and max stay NULL and `value` carries the number, as before."""
    assert datasheets.parse_range("23.5 barg") is None
    assert datasheets.measure_value("23.5 barg")[:2] == ("23.5", "barg")


# ==================================================== degree glyphs

@pytest.mark.parametrize("raw,expected", [
    ("121OC", "121°C"),
    ("121oC", "121°C"),
    ("93.3OC", "93.3°C"),
    ("-3 to 121OC / 77oC", "-3 to 121°C / 77°C"),
    ("100OF", "100°F"),
])
def test_the_degree_glyph_is_recovered_after_a_number(raw, expected):
    assert datasheets.normalise_degree_glyph(raw) == expected


@pytest.mark.parametrize("raw", [
    "a doc and a bloc", "Proc. OC review", "OCTG casing", "block OC",
])
def test_a_word_ending_in_oc_is_left_alone(raw):
    """ONLY IMMEDIATELY AFTER A DIGIT. Without the lookbehind this rule
    rewrites prose, and a document number becomes a temperature."""
    assert datasheets.normalise_degree_glyph(raw) == raw


def test_the_glyph_reaches_measure_value():
    """The rule is no use in a helper nobody calls. `121OC` must read as a
    temperature through the ordinary path."""
    assert datasheets.measure_value("121OC")[:2] == ("121", "°C")


# ============================================ comparing against a range

RANGE_FACT = {
    "field_name": "ambient temperature", "field_value": "-3 to 55 C",
    "raw_value": None, "raw_unit": "C", "unit": "C",
    "value_min": -3.0, "value_max": 55.0,
}


def _rule(operator: str, value: str) -> dict:
    return {"requirement_type": "numeric_limit", "operator": operator,
            "raw_value": value, "raw_unit": "C",
            "source_text": "The ambient temperature shall be within range."}


def test_an_upper_limit_is_compared_against_the_top_of_the_range():
    """`shall not exceed` is about where the band WOULD breach it."""
    assert comparison.compare(_rule("<=", "60"), RANGE_FACT)["status"] == \
        comparison.COMPLIANT
    assert comparison.compare(_rule("<=", "50"), RANGE_FACT)["status"] == \
        comparison.NON_COMPLIANT


def test_a_lower_limit_is_compared_against_the_bottom_of_the_range():
    assert comparison.compare(_rule(">=", "-10"), RANGE_FACT)["status"] == \
        comparison.COMPLIANT
    assert comparison.compare(_rule(">=", "0"), RANGE_FACT)["status"] == \
        comparison.NON_COMPLIANT


def test_an_exact_equality_rule_against_a_range_is_a_question_for_a_person():
    """The band CONTAINS 50 and is not EQUAL to it. Neither COMPLIANT nor
    NON_COMPLIANT is true, so neither is claimed."""
    verdict = comparison.compare(_rule("=", "50"), RANGE_FACT)

    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert comparison.RANGE_VS_EQUALITY in verdict["rationale"]
    assert "-3 to 55 C" in verdict["rationale"], \
        "the engineer must be shown the range, not a verdict about it"


def test_the_mean_of_a_range_is_never_compared():
    """THE RULE STATED AS A TEST. The mean of -3 and 55 is 26. A rule capping
    the ambient at 30 is met by the mean and breached by the band, so a
    mean-based engine returns COMPLIANT where the truth is NON_COMPLIANT -
    and nothing on the finding would say a number was invented.
    """
    verdict = comparison.compare(_rule("<=", "30"), RANGE_FACT)

    assert verdict["status"] == comparison.NON_COMPLIANT
    assert "55" in verdict["rationale"], "the top of the band decided it"
    assert "26" not in verdict["rationale"]


def test_the_finding_says_which_end_was_compared():
    """A reviewer checking `55 C` against a sheet reading `-3 to 55 C` needs
    to know where the 55 came from."""
    rationale = comparison.compare(_rule("<=", "60"), RANGE_FACT)["rationale"]

    assert "highest" in rationale and "-3 to 55 C" in rationale


def test_a_range_fact_can_be_matched_at_all():
    """`raw_value` is NULL on a range by design, and the matcher tested that
    column alone - so every range was skipped and `compare` could never reach
    the code that reads one."""
    requirement = {
        "id": "r", "requirement_type": "numeric_limit",
        "subject": "the ambient temperature shall not exceed",
        "operator": "<=", "raw_value": "60", "raw_unit": "C",
    }
    facts = [{**RANGE_FACT, "id": "f1", "submittal_document_id": "sub"}]

    assert comparison.fact_has_number(facts[0]) is True
    assert comparison.match_by_containment(
        requirement, facts)["fact"]["id"] == "f1"


def test_a_single_value_still_compares_exactly_as_before():
    """The guard on all of the above: nothing in the range path may change
    what an ordinary value does."""
    single = {"field_name": "x", "field_value": "40 C", "raw_value": "40",
              "raw_unit": "C", "unit": "C", "value_min": None,
              "value_max": None}

    verdict = comparison.compare(_rule("<=", "60"), single)

    assert verdict["status"] == comparison.COMPLIANT
    assert "compared at the" not in verdict["rationale"]


# ================================== through the pipeline, not the helper

def _datasheet_pdf(path, rows) -> str:
    """A one-page ruled form, the shape `split_label_value` reads."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(rows, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _ingest(path, doc_id="doc_rng"):
    import pymupdf

    doc = pymupdf.open(path)
    pages = len(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',?,?)",
            (doc_id, "RANGE-TEST.pdf", f"sha-{doc_id}", str(path), pages,
             "2026-09-19T00:00:00Z"))
        for page in range(1, pages + 1):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,"
                "page_start,page_end,section,kind,text,token_count,"
                "content_hash,retrievable) VALUES (?,?,?,?,?,?,NULL,'prose',"
                "?,1,?,1)",
                (f"{doc_id}-c{page}", doc_id, "RANGE-TEST.pdf", page, page,
                 page, doc[page - 1].get_text(), f"h{doc_id}{page}"))
    doc.close()
    return doc_id


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "rng.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def test_a_range_survives_the_value_gate_and_is_stored(temp_storage, tmp_path):
    """END TO END, BECAUSE THE GATE IS WHERE RANGES DIED.

    `measure_value` reads one number and a unit, so `-3 to 55 C` came back as
    nothing and the value gate in `extract_facts` discarded the row as free
    text - before `create_fact`, which is the only thing that knows about
    ranges, was ever reached. Every range on the PSV sheet was lost there.
    """
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", [
        ("Ambient temperature", "-3 to 55 C"),
        ("Design pressure", "23.5 barg"),
    ]))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = {f["field_name"]: f for f in datasheets.list_facts(
        doc, allowed_document_ids=frozenset({doc}))}

    ambient = facts["ambient temperature"]
    assert ambient["value_min"] == -3.0 and ambient["value_max"] == 55.0
    assert ambient["raw_unit"] == "C"
    assert ambient["field_value"] == "-3 to 55 C", "the raw text is kept"
    # AND AN ORDINARY VALUE ON THE SAME PAGE IS UNCHANGED, so this is not
    # passing because everything became a range.
    single = facts["design pressure"]
    assert single["raw_value"] == "23.5"
    assert single["value_min"] is None and single["value_max"] is None


def test_a_compound_label_that_did_not_split_stores_no_parsed_value(
        temp_storage, tmp_path):
    """THE REFUSAL, THROUGH `create_fact`.

    `Design/Operating pressure` beside a single number could be either of the
    two fields it names. The row is kept with its text and no parsed value,
    because recording the number against the compound label would attach a
    real quantity to a field that is half wrong.
    """
    doc = _ingest(_datasheet_pdf(tmp_path / "c.pdf", [
        ("Design/Operating pressure", "23.5 barg"),
        ("Set pressure", "340 psig"),
    ]))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = {f["field_name"]: f for f in datasheets.list_facts(
        doc, allowed_document_ids=frozenset({doc}))}

    compound = facts["design/operating pressure"]
    assert compound["field_value"] == "23.5 barg", "the raw text is kept"
    assert compound["raw_value"] is None, "a number was attached to two fields"
    assert compound["value_min"] is None and compound["value_max"] is None
    # AND A PLAIN ROW ON THE SAME PAGE STILL PARSES.
    assert facts["set pressure"]["raw_value"] == "340"


def test_a_compound_row_becomes_two_facts_through_the_pipeline(
        temp_storage, tmp_path):
    """The positive, end to end: two fields out of one row, each with the
    unit that was written once."""
    doc = _ingest(_datasheet_pdf(tmp_path / "s.pdf", [
        ("Design/Operating pressure", "23.5 / 11.03 barg"),
    ]))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = {f["field_name"]: f for f in datasheets.list_facts(
        doc, allowed_document_ids=frozenset({doc}))}

    assert facts["design pressure"]["raw_value"] == "23.5"
    assert facts["design pressure"]["raw_unit"] == "barg"
    assert facts["operating pressure"]["raw_value"] == "11.03"
    assert facts["operating pressure"]["raw_unit"] == "barg"
