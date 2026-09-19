"""A number that belongs to a lookup table is not a limit.

THE DEFECT THIS EXISTS FOR, from the first end-to-end review. SAES-D-001 6.2.2
says the internal design pressure "shall be according to the following table",
and the table's first row boundary reads "Up to 6,900 kPa (1,000 psi)". The
parser read that as a limit of <= 6,900 kPa - which the standard does not state
anywhere - and it then MATCHED a real submitted pressure. Only a mismatch of
unit spellings stopped it becoming a confident wrong verdict, and the unit
guard was about to be relaxed.

So the rule is: a sentence that states its own comparator states its own limit;
anything else whose number sits in a table reference or a row boundary is
`table_row`, and `compare` refuses it with the row quoted so an engineer reads
the table rather than a verdict about it.

Every fixture is synthetic apart from the two clause texts, which are quoted
because they are the cases that were wrong in production.
"""

from __future__ import annotations

import pytest

from app import comparison, requirements_3b


# ------------------------------------------------- deferring to a table

@pytest.mark.parametrize("sentence", [
    "The internal design pressure shall be according to the following table.",
    "Wall thickness shall be per Table 5.",
    "Values shall be as given in Table 7.2.",
    "Corrosion allowance shall be in accordance with the table below is per Table 3.",
    "Ratings shall be as tabulated.",
    "See Table 12 for the applicable values.",
])
def test_a_sentence_that_defers_to_a_table_is_a_table_row(sentence):
    assert requirements_3b.is_table_row(sentence) is True


# ---------------------------------------------------- a row boundary

@pytest.mark.parametrize("fragment", [
    "Up to 6,900 kPa (1,000 psi)",
    "Over 1,100 kPa",
    "Above 50 mm",
    "Below 15 mm",
    "15 to 25 mm",
    "6,900 kPa and above",
    "1,100 kPa and below",
])
def test_a_row_boundary_fragment_is_a_table_row(fragment):
    """These are CELLS. A column heading that contains a number is not an
    obligation, and it is only ever a requirement by being read out of its
    table."""
    assert requirements_3b.is_table_row(fragment) is True


# --------------------------------------- the negatives that must not move

@pytest.mark.parametrize("sentence", [
    "The maximum solids loading limit shall not exceed 5 g/L.",
    "The thickness shall be 5 mm or less.",
    "The cover shall be at least 300 mm.",
    "The noise level shall not exceed 90 dB(A).",
    "Hardness shall be no more than 200 BHN.",
    "The depth shall be not less than 300 mm.",
])
def test_a_sentence_that_states_its_own_limit_stays_a_numeric_limit(sentence):
    """THE GUARD, and it is the more important half of this file.

    Over-classifying is how a real requirement stops being checked. A sentence
    carrying its own comparator states its own limit whatever else it mentions.
    """
    assert requirements_3b.is_table_row(sentence) is False


def test_a_limit_that_also_cites_a_table_is_still_a_limit():
    """"shall not exceed 5 g/L (see Table 3)" has both shapes, and the
    obligation and the number are in the same sentence. The comparator wins,
    which is why it is tested first."""
    assert requirements_3b.is_table_row(
        "The limit shall not exceed 5 g/L (see Table 3).") is False


def test_classify_prefers_table_row_over_numeric_limit():
    """`classify` checks the table shape BEFORE the parsed limit, because such
    a sentence DOES parse as a limit - that is the entire defect."""
    sentence = ("The internal design pressure shall be according to the "
                "following table: Up to 6,900 kPa")
    limit = requirements_3b.parse_limit(sentence)

    assert limit is not None, "the sentence still parses as a limit"
    assert requirements_3b.classify(sentence, limit) == requirements_3b.TABLE_ROW


def test_classify_still_returns_numeric_limit_for_a_real_limit():
    sentence = "The maximum solids loading limit shall not exceed 5 g/L."
    limit = requirements_3b.parse_limit(sentence)

    assert requirements_3b.classify(sentence, limit) == "numeric_limit"


# -------------------------------------------------- what compare() does

def test_compare_refuses_a_table_row_and_quotes_the_row():
    """The engineer needs the ROW, not a verdict about it.

    A status alone would say "needs review" and leave them to find the table;
    the fragment is carried verbatim so the finding shows what the standard
    actually printed.
    """
    requirement = {
        "requirement_type": requirements_3b.TABLE_ROW,
        "source_text": "Up to 6,900 kPa (1,000 psi)",
        "subject": "internal design pressure",
    }
    fact = {"raw_value": "2.2", "raw_unit": "bar", "unit": "bar", "is_blank": 0}

    verdict = comparison.compare(requirement, fact, subject=None)

    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert comparison.TABLE_ROW_REASON in verdict["rationale"]
    assert "Up to 6,900 kPa (1,000 psi)" in verdict["rationale"]


def test_a_table_row_is_refused_even_when_no_value_was_submitted():
    """Checked BEFORE the absent-fact branch: a table row is not a limit
    whether or not anything was submitted against it, and reporting it as
    MISSING_INFORMATION would blame the contractor for the parser."""
    requirement = {
        "requirement_type": requirements_3b.TABLE_ROW,
        "source_text": "Up to 6,900 kPa",
        "subject": "internal design pressure",
    }

    verdict = comparison.compare(requirement, None, subject=None)

    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert comparison.TABLE_ROW_REASON in verdict["rationale"]


def test_a_real_limit_still_produces_a_verdict():
    """The guard on both tests above. Without this they would pass against an
    engine that returned NEEDS_ENGINEER_REVIEW for everything."""
    requirement = {
        "requirement_type": "numeric_limit", "operator": "<=",
        "raw_value": "90", "raw_unit": "dB(A)", "subject": "noise level",
    }
    fact = {"raw_value": "95", "raw_unit": "dB(A)", "unit": "dB(A)", "is_blank": 0}

    assert comparison.compare(requirement, fact,
                              subject=None)["status"] == comparison.NON_COMPLIANT
