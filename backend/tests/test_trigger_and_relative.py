"""Two shapes that parse as a limit and are not one.

BOTH WERE FOUND BY THE MODEL TIER'S EVALUATION, and both produced a confident
verdict about a contractor from a number the standard never stated as a limit:

  APPLICABILITY TRIGGER. SAES-D-001 9.2.5 - "temperatures greater than 260°C
  (500°F) shall be in accordance with PIP VEFV1100". The parser read
  `> 260 °C`, the tier paired it with a datasheet field reading 60 °C, and the
  engine reported NON_COMPLIANT because 60 is not greater than 260. The
  standard says that IF the temperature is above 260 °C, another document
  governs. The 260 is a threshold of applicability. There is no limit here.

  RELATIVE LIMIT. SAES-D-001 14.3 - "temperature of vessel wall is at least
  28°C (50°F) warmer than the calculated dew point". The parser read
  `>= 28 °C`, the tier paired it with an internal design temperature of 95 °C,
  and the engine reported COMPLIANT because 95 >= 28. The 28 is a MARGIN. The
  dew point it is a margin from is computed from the process stream and is
  nowhere in the submittal.

Neither defect needed the model: both numbers were stored as limits by the
extractor, and containment could have paired either of them on another sheet.
The model tier is what made them visible.

The negative fixtures are the point of this file. A condition that carries a
number, a limit that cites a document, and a sentence that mentions a margin
while stating its own limit must all stay exactly what they were - these
checks run BEFORE `numeric_limit` and a loose one silently deletes real
requirements.

Mutations: M159-M166, `python scripts/mutation_check.py --phase 12`.
"""

from __future__ import annotations

import pytest

from app import comparison, requirements_3b


def classify(sentence: str) -> str:
    return requirements_3b.classify(sentence, requirements_3b.parse_limit(sentence))


# ================================================ applicability triggers

#: The production case, quoted, because it is the one that was wrong.
TRIGGER = ("temperatures greater than 260°C (500°F) shall be in accordance "
           "with PIP VEFV1100 and dimensions that meet the intent of reducing "
           "the thermal gradient at the skirt-to-vessel junction.")


@pytest.mark.parametrize("sentence", [
    TRIGGER,
    # The comparator wording is `_LIMIT`'s vocabulary on purpose: a fixture
    # whose condition the parser does not read as a limit would pass this
    # file while proving nothing, because the defect only exists where a
    # limit WAS parsed.
    "For services greater than 45 barg, the vessel shall be in accordance "
    "with ASME Section VIII Division 2.",
    "When the design temperature is greater than 400°C, the flange rating "
    "shall conform to API 660.",
    "If the chloride content is greater than 50 ppm, materials shall be as "
    "specified in NACE MR0175.",
    "Insulation for lines operating at less than 10°C shall be per "
    "paragraph 7.4.4.",
])
def test_a_condition_that_defers_to_another_document_is_a_trigger(sentence):
    """THE NUMBER IS THE THRESHOLD OF APPLICABILITY, NOT A LIMIT.

    Every one of these parses as a limit today, which is exactly why the check
    has to run before `numeric_limit`.
    """
    assert requirements_3b.parse_limit(sentence), (
        "this fixture proves nothing unless the sentence really does parse as "
        "a limit - that is the defect being prevented")
    assert classify(sentence) == requirements_3b.APPLICABILITY_TRIGGER


@pytest.mark.parametrize("sentence", [
    # A CONDITION PLUS ITS OWN LIMIT. The obligation states a quantity, so the
    # sentence is a requirement however conditional its opening is.
    "For design temperatures above 260°C, wall thickness shall be at least "
    "12 mm.",
    # A LIMIT THAT HAPPENS TO CITE A DOCUMENT. The citation is where the
    # method lives; the limit is stated here.
    "The maximum solids loading limit shall not exceed 5 g/L (see Table 3).",
    "Surface roughness shall not exceed 3.2 µm when measured per ASME B46.1.",
    # A DEFERRAL WITH NO CONDITION AND NO NUMBER is a statement, and was
    # already one.
    "Welding shall be in accordance with ASME Section IX.",
    # A DEFERRAL TO NOTHING IN PARTICULAR. "in accordance with good
    # engineering practice" hands the question to no document at all, so
    # there is nothing for the reader to go and read - the condition and its
    # number are all this sentence states, and it stays what it was.
    "For temperatures greater than 100\u00b0C, the vessel shall be insulated in "
    "accordance with good engineering practice.",
])
def test_a_sentence_that_states_its_own_quantity_is_not_a_trigger(sentence):
    assert classify(sentence) != requirements_3b.APPLICABILITY_TRIGGER


def test_a_deferral_to_a_table_stays_a_table_row():
    """THE GUARD BETWEEN THE TWO CHECKS. A table is not another document, and
    `table_row` already exists for it - it is decided first, and a trigger
    check that swallowed it would undo the previous task."""
    sentence = ("Internal design pressure shall be in accordance with the "
                "following table. Up to 6,900 kPa (1,000 psi)")

    assert requirements_3b.parse_limit(sentence)
    assert classify(sentence) == requirements_3b.TABLE_ROW


def test_the_predicate_itself_refuses_a_deferral_to_a_table():
    """THE GUARD INSIDE `is_applicability_trigger`, ASKED DIRECTLY.

    `classify` checks `is_table_row` first, so through that door the guard
    never decides anything and a mutation of it changes no classification.
    That makes the guard invisible from `classify` and only from `classify` -
    the predicate is a module-level function, the rule it states is real ("a
    table is not another document"), and the next caller reaches it without
    the ordering that currently protects it.
    """
    # A TABLE INSIDE ANOTHER DOCUMENT is where the guard actually decides.
    # "in accordance with the following table" is refused by the
    # document-reference test anyway - it names no document - so the guard
    # only ever changes the answer where BOTH are present.
    table = ("Internal design pressure shall be in accordance with the "
             "table in ASME Section VIII.")
    document = ("Internal design pressure shall be in accordance with "
                "ASME Section VIII.")

    assert requirements_3b.is_applicability_trigger(table) is False
    # AND THE SAME SENTENCE DEFERRING TO A DOCUMENT IS ONE, so this is not
    # passing because the predicate refuses everything.
    assert requirements_3b.is_applicability_trigger(document) is True


def test_a_trigger_is_outside_the_matcher_and_is_never_compared():
    """NEVER COMPARED means never matched either: the matcher's scope is
    `numeric_limit` and `table_row`, and a trigger is neither. Without this a
    trigger could still be paired and `compare` would evaluate its threshold
    as a limit - which is the production defect, reached by another road.
    """
    requirement = {
        "id": "req-1", "requirement_type": requirements_3b.APPLICABILITY_TRIGGER,
        "subject": "the maximum operating temperature of the vessel",
        "raw_value": "260", "raw_unit": "°C", "operator": ">",
    }
    facts = [{"id": "f1", "field_name": "maximum operating temperature",
              "raw_value": "60", "raw_unit": "°C", "unit": "°C",
              "submittal_document_id": "sub"}]

    assert comparison.match_by_containment(requirement, facts)["fact"] is None
    assert comparison.candidate_facts(requirement, facts) == []
    # AND THE SAME FIXTURE PAIRS WHEN IT IS A LIMIT, so this is not passing
    # because the fixture could never match anything.
    assert comparison.match_by_containment(
        {**requirement, "requirement_type": "numeric_limit"},
        facts)["fact"]["id"] == "f1"


# ==================================================== relative limits

#: The production case, quoted.
RELATIVE = ("14.3 Design of refractory lining shall be such that temperature "
            "of vessel wall is at least 28°C (50°F) warmer than the calculated "
            "dew point of the process stream to prevent condensation corrosion.")


@pytest.mark.parametrize("sentence", [
    RELATIVE,
    "Materials of construction shall have yield strength at least 10% greater "
    "than their specified minimum values.",
    "The shell shall be at least 3 mm thicker than the nozzle neck.",
    "Outlet temperature shall be no more than 5°C higher than the inlet "
    "temperature.",
])
def test_a_margin_from_a_reference_is_a_relative_limit(sentence):
    assert requirements_3b.parse_limit(sentence), (
        "this fixture proves nothing unless the sentence parses as a limit")
    assert classify(sentence) == requirements_3b.RELATIVE_LIMIT


@pytest.mark.parametrize("sentence", [
    "The skirt shall be at least 300 mm.",
    "The noise level shall not exceed 90 dB(A).",
    "Wall thickness shall be a minimum of 12 mm.",
])
def test_an_absolute_limit_is_not_a_relative_one(sentence):
    assert classify(sentence) == "numeric_limit"


def test_a_relative_phrase_elsewhere_in_the_sentence_does_not_move_the_limit():
    """THE OVER-REACH THIS CHECK WAS WRITTEN WITH, caught on the corpus.

    "In areas within 100 m of a platform structure, submarine cable shall be
    buried a minimum of 1 m" - the parsed limit is the 1 m burial depth, an
    ordinary absolute limit, and the relative phrase belongs to a condition
    about WHERE the rule applies. Searched anywhere in the sentence the check
    reclassified it and deleted a real requirement; anchored at the number the
    parser actually took, it does not.
    """
    sentence = ("In areas within 100 m of a platform structure, submarine "
                "cable shall be buried a minimum of 1 m.")
    limit = requirements_3b.parse_limit(sentence)

    assert limit["raw_value"] == "1" and limit["raw_unit"] == "m"
    assert classify(sentence) == "numeric_limit"


def test_a_comparative_phrase_before_the_limit_does_not_move_it():
    """THE ANCHORING, WHERE IT ACTUALLY DECIDES.

    Here the sentence really does contain the comparative shape - "100 m
    lower than the platform" - and the limit the parser took is the 1 m
    burial depth further along. Searched anywhere, the check reclassifies a
    real absolute limit and it stops being compared at all; anchored at the
    number that was taken, it does not.
    """
    sentence = ("In areas 100 m lower than the platform, submarine cable "
                "shall be buried a minimum of 1 m.")
    limit = requirements_3b.parse_limit(sentence)

    assert limit["raw_value"] == "1", "the fixture must parse the LATER number"
    assert classify(sentence) == "numeric_limit"
    # AND THE COMPARATIVE PHRASE IS GENUINELY THERE, so this is not passing
    # because the sentence never had the shape.
    assert requirements_3b._RELATIVE_TAIL.search(sentence) is not None


def test_compare_refuses_a_relative_limit_and_quotes_the_sentence():
    """MATCHED BUT NOT COMPARED. The engineer gets the sentence, because the
    reference it is a margin from is not on the datasheet - and 95 >= 28 is
    arithmetic that means nothing."""
    requirement = {
        "requirement_type": requirements_3b.RELATIVE_LIMIT,
        "operator": ">=", "raw_value": "28", "raw_unit": "°C",
        "source_text": RELATIVE,
    }
    fact = {"id": "f1", "field_name": "internal maximum design temperature",
            "raw_value": "95", "raw_unit": "°C", "unit": "°C"}

    verdict = comparison.compare(requirement, fact)

    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert comparison.RELATIVE_LIMIT_REASON in verdict["rationale"]
    assert "warmer than the calculated dew point" in verdict["rationale"], \
        "the engineer must be given the sentence, not a verdict about it"
    # AND THE SAME NUMBERS PRODUCE A VERDICT WHEN THE REQUIREMENT IS ABSOLUTE,
    # so this is not passing because `compare` stopped comparing.
    assert comparison.compare(
        {**requirement, "requirement_type": "numeric_limit"},
        fact)["status"] == comparison.COMPLIANT


def test_a_relative_limit_with_nothing_submitted_is_missing_information():
    """An unmatched relative limit is an unmatched requirement like any other.
    Raising every one to the reviewer's queue would bury the ones that carry
    something to act on - the same rule table rows already follow."""
    requirement = {
        "requirement_type": requirements_3b.RELATIVE_LIMIT,
        "operator": ">=", "raw_value": "28", "raw_unit": "°C",
        "source_text": RELATIVE,
    }

    assert comparison.compare(requirement, None)["status"] == \
        comparison.MISSING_INFORMATION


def test_a_relative_limit_is_matchable_so_the_reviewable_case_can_arise():
    """`compare` only reaches its refusal when a value was matched, so a
    matcher that skipped relative limits would leave that branch dead and
    every one of them reported as the contractor's missing information."""
    requirement = {
        "id": "req-1", "requirement_type": requirements_3b.RELATIVE_LIMIT,
        "subject": "the internal maximum design temperature of the vessel",
        "operator": ">=", "raw_value": "28", "raw_unit": "°C",
    }
    facts = [{"id": "f1", "field_name": "internal maximum design temperature",
              "raw_value": "95", "raw_unit": "°C", "unit": "°C",
              "submittal_document_id": "sub"}]

    assert comparison.match_by_containment(
        requirement, facts)["fact"]["id"] == "f1"
