"""The claim table is mechanical. Each property here has its own test so a
regression says WHICH rule broke.

The rules under test, from docs/design-analysis-and-synthesis.md:
  - the exact sentence is carried, never a paraphrase;
  - an unknown unit is None (or raises, in the strict variant), never a guess;
  - Fahrenheit is refused outright - a wrong temperature is a safety defect;
  - clusters form on facet key (question term + unit dimension), never wording;
  - `possible_conflict` carries one mandated sentence, and `conflict` is never emitted;
  - system 1 vs system 9 is two things, not a conflict: `unresolved`.
"""

import json

import pytest

from app import claims, db, keyword
from app.config import settings
from app.claims import (
    Claim,
    Measurement,
    UnknownUnit,
    cluster,
    extract_claims,
    facet_key,
    label_cluster,
    normalise,
    normalise_strict,
    question_terms,
    split_sentences,
    to_api,
)



@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """`claims` reaches the database through `keyword` and `lexical`.

    Without this these tests passed on a development machine - which has a
    62 MB corpus at backend/data/rag_intelligence.sqlite - and failed in CI with
    `no such table`. The tables must be CREATED, not present by accident.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _evidence(evidence_id: str, text: str, filename: str = "spec.pdf", page: int = 1) -> dict:
    return {
        "evidence_id": evidence_id,
        "filename": filename,
        "page_start": page,
        "section": None,
        "exact_span": text,
    }


# ------------------------------------------------------------------ normalise


def test_comma_decimal_is_a_decimal_norsok_trap():
    m = normalise("9,0", "MPa")
    assert m.normalized_value == pytest.approx(9.0)
    assert m.normalized_unit == "MPa"
    assert m.raw_value == "9,0" and m.raw_unit == "MPa"


@pytest.mark.parametrize("value,unit", [("280", "µm"), ("280", "um"), ("280", "μm"), ("0.28", "mm")])
def test_length_spellings_normalise_to_280_um(value, unit):
    m = normalise(value, unit)
    assert m.normalized_unit == "um"
    assert m.normalized_value == pytest.approx(280.0)


@pytest.mark.parametrize("value,unit,micrometres", [
    ("1", "cm", 10_000.0),        # 1 cm is 10 mm, exactly
    ("1", "km", 1_000_000_000.0),
    ("1", "ft", 304_800.0),       # the foot is DEFINED as 0.3048 m
    ("1", "feet", 304_800.0),
    ("1", "mil", 25.4),           # a mil is 0.001 inch, and the inch is defined
    ("1", "nm", 0.001),
])
def test_the_length_spellings_moved_out_of_unconverted_convert_exactly(
        value, unit, micrometres):
    """These six were RECOGNISED but not converted, so a limit written in cm
    was stored with a null value and could not be compared against a datasheet
    value in mm - while 600 limits in mm, m and inch normalised fine.

    Every factor is exact by definition. A unit whose conversion would need
    rounding does not belong in this table, which is why °F is still refused
    by the test below: Fahrenheit to Celsius is affine, not multiplicative.
    """
    m = normalise(value, unit)
    assert m.normalized_unit == "um"
    assert m.normalized_value == pytest.approx(micrometres)


def test_a_length_limit_compares_across_those_spellings():
    """The point of converting them: before this, `<= 12 cm` against a
    submitted 150 mm could only be NEEDS_ENGINEER_REVIEW."""
    from app import comparison
    requirement = {"requirement_type": "numeric_limit",
                   "operator": "<=", "raw_value": "12", "raw_unit": "cm"}
    breach = comparison.compare(
        requirement, {"raw_value": "150", "raw_unit": "mm", "field_value": "150 mm"})
    passes = comparison.compare(
        requirement, {"raw_value": "100", "raw_unit": "mm", "field_value": "100 mm"})
    assert breach["status"] == comparison.NON_COMPLIANT
    assert passes["status"] == comparison.COMPLIANT


@pytest.mark.parametrize("unit", ["°F", "years", "dB(A)", "ppmw", "NPS"])
def test_the_units_deliberately_left_unconverted_are_still_refused(unit):
    """Widening the table must not widen it past what is exact. `years` is a
    duration the `time` dimension would turn into hours - a 25-year design
    life becoming 219,000 h, then comparable against a 24 h hold time.
    `ppmw` and `dB(A)` have sibling spellings that are NOT interchangeable,
    and NPS is a designation, not a measurement.
    """
    assert normalise("5", unit).normalized_value is None


def test_fahrenheit_is_refused_not_converted():
    m = normalise("350", "°F")
    assert m.normalized_value is None
    assert m.normalized_unit is None
    assert m.raw_value == "350" and m.raw_unit == "°F"
    with pytest.raises(UnknownUnit):
        normalise_strict("350", "°F")


def test_unknown_unit_is_none_and_strict_raises():
    m = normalise("3", "kfurlong")
    assert m.normalized_value is None and m.normalized_unit is None
    assert m.raw_unit == "kfurlong"
    with pytest.raises(UnknownUnit):
        normalise_strict("3", "kfurlong")


def test_unknown_unit_is_never_zero():
    assert normalise("3", "kfurlong").normalized_value != 0


def test_pressure_time_voltage_current_factors():
    assert normalise("10", "bar").normalized_value == pytest.approx(1.0)
    assert normalise("1000", "kPa").normalized_value == pytest.approx(1.0)
    assert normalise("30", "min").normalized_value == pytest.approx(0.5)
    assert normalise("30", "min").normalized_unit == "h"
    assert normalise("1", "kV").normalized_value == pytest.approx(1000.0)
    assert normalise("500", "mA").normalized_value == pytest.approx(0.5)
    assert normalise("120", "°C").normalized_unit == "C"
    assert normalise("120", "degC").normalized_value == pytest.approx(120.0)


@pytest.mark.parametrize("written", ["≥ 250", "not less than 250", "at least 250", ">= 250"])
def test_comparators_give_ge_and_value(written):
    m = normalise(written, "um")
    assert m.comparator == ">="
    assert m.normalized_value == pytest.approx(250.0)
    assert m.raw_value == written


def test_min_max_words_are_comparators():
    assert normalise("minimum 250", "um").comparator == "min"
    assert normalise("max. 200", "um").comparator == "max"
    assert normalise("≤ 200", "um").comparator == "<="


# ------------------------------------------------------------------ extraction


def test_sentence_without_measurement_identifier_or_designator_is_not_a_claim():
    out = extract_claims([_evidence("e1", "The coating shall be applied by a qualified applicator.")], allowed_document_ids=_scope())
    assert out == []


def test_exact_span_is_the_verbatim_sentence():
    s1 = "MDFT of complete coating system: 280 um for the exteriors described."
    s2 = "Cleanliness shall be ISO 8501-1 Sa 2 1/2 before application."
    out = extract_claims([_evidence("e1", s1 + " " + s2)], allowed_document_ids=_scope())
    spans = [c.exact_span for c in out]
    assert spans == [s1, s2]
    assert all(c.exact_span in (s1 + " " + s2) for c in out)


def test_abbreviation_no_does_not_split_a_sentence():
    s = "Coating system no. 1 shall have a MDFT of 280 um."
    out = extract_claims([_evidence("e1", s)], allowed_document_ids=_scope())
    assert len(out) == 1
    assert out[0].exact_span == s
    assert out[0].designators == ("system 1",)


def test_extraction_types_measurement_identifier_designator():
    s = "Coating system no. 1 to NORSOK M-501 shall have a MDFT of 280 um."
    (c,) = extract_claims([_evidence("e1", s)], allowed_document_ids=_scope())
    assert "NORSOK M-501" in c.identifiers
    assert c.designators == ("system 1",)
    assert len(c.measurements) == 1
    m = c.measurements[0]
    assert (m.raw_value, m.raw_unit, m.normalized_value, m.normalized_unit) == ("280", "um", 280.0, "um")


def test_clause_number_is_an_identifier_not_a_measurement():
    (c,) = extract_claims([_evidence("e1", "See clause 5.3.2 for adhesion requirements.")], allowed_document_ids=_scope())
    assert "5.3.2" in c.identifiers
    assert c.measurements == ()


def test_evidence_text_key_is_accepted():
    out = extract_claims([{"evidence_id": "e1", "filename": "a.pdf", "page_start": 2, "section": "4", "text": "Adhesion 9,0 MPa."}], allowed_document_ids=_scope())
    assert len(out) == 1 and out[0].page_start == 2 and out[0].section == "4"


def test_empty_evidence_gives_empty_clusters():
    assert extract_claims([], allowed_document_ids=_scope()) == []
    assert cluster([], frozenset({"adhesion"})) == []
    assert to_api([]) == []


# ------------------------------------------------------------------ facets and clustering


def test_facet_key_none_without_shared_term_or_designator_even_if_text_identical():
    text = "Pressure shall be 280 um."
    a, b = extract_claims([_evidence("e1", text), _evidence("e2", text)], allowed_document_ids=_scope())
    q = frozenset({"adhesion"})
    assert facet_key(a, q) is None
    assert facet_key(b, q) is None
    assert cluster([a, b], q) == []


def test_facet_key_is_terms_plus_dimension():
    (c,) = extract_claims([_evidence("e1", "Adhesion shall be 9,0 MPa.")], allowed_document_ids=_scope())
    assert facet_key(c, frozenset({"adhesion", "unrelated"})) == frozenset({"adhesion", "dim:pressure"})


def test_same_value_two_spellings_two_documents_is_agreement():
    ev = [
        _evidence("e1", "Adhesion shall be 9,0 MPa.", "norsok.pdf"),
        _evidence("e2", "Adhesion shall be 9.0 MPa.", "iso.pdf"),
    ]
    out = cluster(extract_claims(ev, allowed_document_ids=_scope()), frozenset({"adhesion"}))
    assert len(out) == 1
    assert out[0].label == "agreement"
    # "adhesion (MPa)", not "adhesion · MPa": the subject reads as a phrase
    # and the unit sits in brackets where a unit belongs. The old form joined
    # every term, designator and unit with " · " and produced things like
    # "coating · thickness · A · um", which names four things and therefore
    # names none of them.
    assert out[0].facet == "adhesion (MPa)"
    assert {r.filename for r in out[0].rows} == {"norsok.pdf", "iso.pdf"}


def test_incompatible_values_same_facet_is_possible_conflict_with_mandated_note():
    ev = [
        _evidence("e1", "MDFT 280 um."),
        _evidence("e2", "MDFT minimum 250 um.", "other.pdf"),
    ]
    # 280 satisfies "minimum 250" - so make the conflict real: a hard 280 vs a hard 250.
    ev2 = [_evidence("e1", "MDFT 280 um."), _evidence("e2", "MDFT 250 um.", "other.pdf")]
    out = cluster(extract_claims(ev2, allowed_document_ids=_scope()), frozenset({"mdft"}))
    assert len(out) == 1
    assert out[0].label == "possible_conflict"
    assert out[0].note == (
        "Values disagree. Whether one supersedes the other cannot be determined: "
        "documents carry no revision or approval status."
    )
    # And the compatible pair is agreement, not a conflict.
    (c,) = cluster(extract_claims(ev, allowed_document_ids=_scope()), frozenset({"mdft"}))
    assert c.label == "agreement"


def test_ge_250_vs_280_is_agreement_and_le_200_vs_280_is_possible_conflict():
    ok = cluster(extract_claims([_evidence("e1", "MDFT ≥ 250 um."), _evidence("e2", "MDFT 280 um.")], allowed_document_ids=_scope()), frozenset({"mdft"}))
    assert [c.label for c in ok] == ["agreement"]
    bad = cluster(extract_claims([_evidence("e1", "MDFT ≤ 200 um."), _evidence("e2", "MDFT 280 um.")], allowed_document_ids=_scope()), frozenset({"mdft"}))
    assert [c.label for c in bad] == ["possible_conflict"]
    assert bad[0].note == claims.POSSIBLE_CONFLICT_NOTE


def test_different_designators_is_unresolved_not_a_conflict():
    ev = [
        _evidence("e1", "Coating system no. 1: MDFT 280 um."),
        _evidence("e2", "Coating system no. 9: MDFT 250 um.", "other.pdf"),
    ]
    out = cluster(extract_claims(ev, allowed_document_ids=_scope()), frozenset({"mdft"}))
    assert len(out) == 1
    assert out[0].label == "unresolved"
    assert out[0].label != "possible_conflict"
    assert "system 1" in out[0].note and "system 9" in out[0].note


def test_unnormalisable_unit_makes_cluster_unresolved():
    ev = [_evidence("e1", "Temperature 120 °C."), _evidence("e2", "Temperature 350 °F.", "us.pdf")]
    out = cluster(extract_claims(ev, allowed_document_ids=_scope()), frozenset({"temperature"}))
    assert len(out) == 1
    assert out[0].label == "unresolved"
    assert "°F" in out[0].note


def test_addition_when_one_row_carries_an_identifier_the_other_lacks():
    ev = [_evidence("e1", "Adhesion 9,0 MPa."), _evidence("e2", "Adhesion 9.0 MPa per ISO 4624.", "b.pdf")]
    (c,) = cluster(extract_claims(ev, allowed_document_ids=_scope()), frozenset({"adhesion"}))
    assert c.label == "addition"


def test_plain_conflict_is_never_emitted():
    import itertools
    values = ["280 um", "250 um", "≥ 250 um", "≤ 200 um", "350 °F", "0.28 mm", "9,0 MPa", "3 kfurlong"]
    prefixes = ["MDFT ", "Coating system no. 1 MDFT ", "Coating system no. 9 MDFT "]
    for a, b in itertools.product([p + v for p in prefixes for v in values], repeat=2):
        for c in cluster(extract_claims([_evidence("e1", a + "."), _evidence("e2", b + ".")], allowed_document_ids=_scope()), frozenset({"mdft"})):
            assert c.label in {"agreement", "addition", "possible_conflict", "unresolved"}


def test_label_cluster_single_row_is_addition():
    (c,) = extract_claims([_evidence("e1", "Adhesion 9,0 MPa.")], allowed_document_ids=_scope())
    label, note = label_cluster([c])
    assert label == "addition" and note


# ------------------------------------------------------------------ API shape


def test_to_api_rows_carry_raw_and_normalized_and_round_trip_json():
    ev = [_evidence("e1", "Temperature 120 °C."), _evidence("e2", "Temperature 350 °F.", "us.pdf", 7)]
    api = to_api(cluster(extract_claims(ev, allowed_document_ids=_scope()), frozenset({"temperature"})))
    text = json.dumps(api)
    back = json.loads(text)
    assert back == api
    (cl,) = back
    assert set(cl) >= {"facet", "label", "rows"}
    for row in cl["rows"]:
        assert set(row) == {"evidence_id", "filename", "page_start", "section", "exact_span",
                            "raw_value", "raw_unit", "normalized_value", "normalized_unit"}
    by_id = {r["evidence_id"]: r for r in cl["rows"]}
    assert by_id["e1"]["raw_value"] == "120" and by_id["e1"]["normalized_value"] == 120.0
    assert by_id["e2"]["raw_value"] == "350" and by_id["e2"]["raw_unit"] == "°F"
    assert by_id["e2"]["normalized_value"] is None
    assert '"normalized_value": null' in text
    assert by_id["e2"]["page_start"] == 7


def test_claim_and_measurement_are_frozen():
    m = normalise("1", "MPa")
    with pytest.raises(Exception):
        m.normalized_value = 2.0  # type: ignore[misc]
    (c,) = extract_claims([_evidence("e1", "Adhesion 1 MPa.")], allowed_document_ids=_scope())
    with pytest.raises(Exception):
        c.exact_span = "paraphrase"  # type: ignore[misc]


def test_identifier_regex_does_not_swallow_a_measurement():
    """keyword.IDENTIFIER matches "MDFT 280" (its API-610 shape) and "9.0" (its
    clause shape). Both must come out as measurements, not codes."""
    (c,) = extract_claims([_evidence("e1", "MDFT 280 um for adhesion 9.0 MPa.")], allowed_document_ids=_scope())
    assert [m.raw_value for m in c.measurements] == ["280", "9.0"]
    assert c.identifiers == ()
    assert "mdft" in c.terms and "mdft 280" not in c.terms
    # A real code keeps its number.
    (d,) = extract_claims([_evidence("e2", "Pumps shall comply with API 610.")], allowed_document_ids=_scope())
    assert d.identifiers == ("API 610",) and d.measurements == ()


# ------------------------------------------- designators are not measurements


#: Verbatim from NORSOKM501Rev5.pdf p.13. Each carries a designator suffix AND
#: a real measurement, so a fix that suppresses the first must not lose the
#: second - which is what makes these better than a synthetic pair.
NORSOK_P13 = (
    "5A and 5B: Maximum 50 % reduction from original value, minimum 2,0 MPa "
    "for cement based products and minimum 3,0 MPa for epoxy based products.",
    "5A to be tested shall be 6 mm.",
    "Adhesion testing of coating system no. 5A and 5B shall be performed on "
    "material without reinforcement.",
)


def test_a_designator_suffix_is_not_a_measurement():
    """"5A" is coating system 5A. It was read as 5 AMPERES.

    A single letter glued to a digit with NO space is a designator suffix.
    The engine invented `raw_value 5, raw_unit A, normalized 5 A` from a
    sentence about a coating system, and an invented measurement is worse
    than a missing one: it enters a claim cluster and gets compared against
    real values.
    """
    for sentence in NORSOK_P13:
        for m in extract_claims([_evidence("e1", sentence)], allowed_document_ids=_scope())[0].measurements:
            assert m.raw_unit.lower() != "a", (
                f"{sentence[:40]!r} produced {m.raw_value} {m.raw_unit} - "
                f"a designator suffix read as amperes"
            )


def test_the_real_measurements_in_those_sentences_survive():
    """The half that makes the fix a fix rather than a mute button."""
    (first,) = extract_claims([_evidence("e1", NORSOK_P13[0])], allowed_document_ids=_scope())
    values = {(m.raw_value, m.raw_unit) for m in first.measurements}
    assert ("50", "%") in values
    assert ("2,0", "MPa") in values and ("3,0", "MPa") in values

    (second,) = extract_claims([_evidence("e2", NORSOK_P13[1])], allowed_document_ids=_scope())
    assert ("6", "mm") in {(m.raw_value, m.raw_unit) for m in second.measurements}


def test_a_unit_glued_to_a_number_is_still_a_unit_when_it_is_not_one_letter():
    """125μm and 280um are real. Only the SINGLE-letter suffix is suspect."""
    (c,) = extract_claims([_evidence("e1", "Minimum coating thickness 125μm.")], allowed_document_ids=_scope())
    assert [(m.raw_value, m.raw_unit) for m in c.measurements] == [("125", "μm")]
    (d,) = extract_claims([_evidence("e2", "A thickness of 280um applied.")], allowed_document_ids=_scope())
    assert [(m.raw_value, m.raw_unit) for m in d.measurements] == [("280", "um")]


def test_a_spaced_single_letter_unit_is_still_a_unit():
    """"5 A" with a space is amperes. The rule is about GLUING, not about the
    letter - an electrical spec must keep its current ratings."""
    (c,) = extract_claims([_evidence("e1", "Rated at 5 A continuous.")], allowed_document_ids=_scope())
    assert [(m.raw_value, m.raw_unit) for m in c.measurements] == [("5", "A")]


@pytest.mark.parametrize("prefix", ["no.", "No.", "system", "class", "type",
                                    "grade", "rev.", "Table"])
def test_a_number_introduced_as_a_designator_is_not_a_measurement(prefix):
    """"system 5 m" is not five metres. The word before the number says so.

    A sentence with no measurement and no identifier produces no claim ROW at
    all, which is why this asserts over the rows rather than unpacking one -
    "no. 5" yields nothing, "system 5" yields a row carrying an identifier,
    and both are correct.
    """
    # MPa, not m: an uppercase multi-letter unit with a space survives every
    # OTHER guard, so this can only pass because of the designator rule. The
    # first version used "5 m" and passed against a pattern that could never
    # match anything - a shell heredoc had eaten every backslash-b into a backspace,
    # and the lone-lowercase-unit guard was doing all the work.
    rows = extract_claims([_evidence("e1", f"Applies to {prefix} 5 MPa rating.")], allowed_document_ids=_scope())
    measured = [(m.raw_value, m.raw_unit) for r in rows for m in r.measurements]
    assert measured == [], f"{prefix!r} 5 was read as {measured}"


def test_the_designator_rule_is_what_saves_that_case():
    """Guard the guard: the same sentence without the designator word IS a
    measurement, so the rule is doing the work and not a side effect."""
    rows = extract_claims([_evidence("e1", "The strength shall be 5 MPa minimum.")], allowed_document_ids=_scope())
    measured = [(m.raw_value, m.raw_unit) for r in rows for m in r.measurements]
    assert measured == [("5", "MPa")]


def test_a_measurement_after_an_ordinary_word_is_untouched():
    """The guard must not swallow every number with a word in front of it."""
    (c,) = extract_claims([_evidence("e1", "The NDFT shall be 280 um minimum.")], allowed_document_ids=_scope())
    assert [(m.raw_value, m.raw_unit) for m in c.measurements] == [("280", "um")]


def test_a_run_of_dots_does_not_crash_extraction():
    """A table-of-contents leader is real corpus text.

    A chunk beginning ". A" - a sentence split across a page break, which is
    ordinary in extracted PDF text - leaves a piece that is exactly ".". It
    survives `prev.strip()`, becomes empty after `rstrip(".")`, and
    `rsplit()[-1]` then raised IndexError.

    MEASURED: 46 of 7187 retrievable chunks crashed claim extraction, and with
    it /api/analysis/gaps. Found by sweeping the real corpus - the first
    version of this test used "..." and passed against the unfixed code,
    proving nothing.
    """
    for text in (". A", ". A coating shall be applied.", ".", ". . ."):
        split_sentences(text)  # must not raise
    (c,) = extract_claims([_evidence("e1", ". A thickness of 280 um applies.")], allowed_document_ids=_scope())
    assert ("280", "um") in {(m.raw_value, m.raw_unit) for m in c.measurements}


def test_a_facet_names_one_dimension_a_reader_recognises():
    """"coating · thickness · A · um" names four things and so names none.

    The subject reads as a phrase; the unit goes in brackets. This is the
    string a reader scans a gap analysis by, so it has to say what is being
    compared.
    """
    rows = extract_claims([
        _evidence("e1", "Minimum coating thickness shall be 125 um."),
        _evidence("e2", "The coating thickness shall be 280 um.", filename="b.pdf"),
    ], allowed_document_ids=_scope())
    (c,) = cluster(rows, question_terms("what coating thickness is required", allowed_document_ids=_scope()))
    assert c.facet == "coating thickness (µm)", c.facet
    assert " · " not in c.facet
    assert "um" not in c.facet, "the reader's unit is µm, not the corpus's um"


# ------------------------------------- a submittal phase is not a percentage


@pytest.mark.parametrize("sentence", [
    "The model shall be submitted as 100% Design Documents.",
    "Submit at the 60% Design Submittal stage.",
    "The 100% Construction Documents phase shall include all drawings.",
    "Deliverables are due at the 30% Design Development milestone.",
    "Provide the 90 % Contract Documents for review.",
])
def test_a_submittal_phase_name_is_not_a_percentage(sentence):
    """"100% Design Documents" is the NAME OF A PHASE, not a quantity.

    Measured: it was extracted as the percentage 100, which then formed a facet
    of its own - the run that prompted this produced "documents (%)" beside
    "documents", splitting one subject in two on the strength of an invented
    measurement. A percentage nothing measured is worse than a missing one: it
    enters a cluster and gets compared against real values.
    """
    got = claims.extract_measurements(sentence)
    assert got == (), f"a submittal phase was read as a measurement: {got}"


@pytest.mark.parametrize("sentence,value", [
    ("Energy use shall be at least 30% below ASHRAE 90.1.", "30"),
    ("Adhesion shall show maximum 50 % reduction from the original value.", "50"),
    ("The coating shall cover 95% of the surface.", "95"),
    ("Humidity shall not exceed 85% during application.", "85"),
])
def test_a_real_percentage_is_still_extracted(sentence, value):
    """THE HALF THAT MATTERS. A rule that suppresses a phase name must not
    suppress a quantity - a false negative here loses a real requirement, and
    the gate exists to catch fabricated numbers, not to lose true ones."""
    got = claims.extract_measurements(sentence)
    assert [m.raw_value for m in got] == [value], (
        f"a real percentage was suppressed: {sentence!r} -> {got}")


def _scope():
    """Corpus-wide scope, stated explicitly.

    `extract_claims` and `question_terms` reach `lexical.distinctive_terms`,
    which consults the corpus for the multi-word expansions the documents
    themselves define - so it now REQUIRES a scope with no default. These
    tests run against an empty database, so the set is empty and the terms
    come from the question's own tokens exactly as before; saying so out loud
    is the point.
    """
    from app.search import every_document_id
    return every_document_id()
