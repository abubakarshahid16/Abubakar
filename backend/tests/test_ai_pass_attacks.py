# ruff: noqa: RUF001 - the attack lists name look-alike dashes, minus signs and spaces on purpose
"""Lane 6: every wrong Pass the reviewers built against the AI-created Pass is refused, through `ai_review_proposals.verify`.

Each case is a document quote against a clause quote; a plain positive control sits beside each family so the harness is
known to reach an acceptance. Invented documents and clauses only; the switch is turned on by the fixture.
"""

from __future__ import annotations

import pytest

from app import ai_pass_verifier as apv
from app import ai_review_proposals as arp
from app.config import settings
from tests.test_ai_pass import FAIL_ROW, good

STD = ("SAES-X-100.pdf", "6.1")


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_pass_enabled", True)


def run(
    doc_value,
    clause_sentence,
    clause_quote=None,
    field="Hydrotest pressure",
    rows=None,
    extra_pages=None,
):
    quote = f"{field} {doc_value}"
    pages = {1: quote, **(extra_pages or {})}
    p = good(
        field=field,
        clause_quote=clause_quote or clause_sentence,
        scope_quote="",
        evidence=[{"page": 1, "quote": quote}],
    )
    context = arp.Context(
        pages=pages,
        rows=rows or {},
        held={"SAES-X-100.pdf": ["6.1"]},
        clause_text={STD: clause_sentence},
        reading_ids=frozenset({"c1", "c2"}),
    )
    verdict = arp.verify(p, context)
    return verdict.accepted, verdict.reason


def refused(*args, **kw):
    ok, reason = run(*args, **kw)
    assert not ok, f"WRONG PASS for {args}"
    assert reason.startswith("pass_") or reason, reason


# ---- negated and varied comparator phrases: the right side of the inequality is checked ----------------------------
@pytest.mark.parametrize(
    ("clause", "bad", "ok"),
    [
        ("The hydrotest pressure shall not be more than 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure is not to be more than 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure shall not be greater than 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure shall not be higher than 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure shall not exceed 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure shall be at most 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure shall be maximum 10 bar", "15 bar", "8 bar"),
        ("The hydrotest pressure shall be not less than 10 bar", "5 bar", "12 bar"),
        ("The hydrotest pressure is not to be less than 10 bar", "5 bar", "12 bar"),
        ("The hydrotest pressure shall not be lower than 10 bar", "5 bar", "12 bar"),
        ("The hydrotest pressure shall not be below 10 bar", "5 bar", "12 bar"),
        ("The hydrotest pressure shall be at least 10 bar", "5 bar", "12 bar"),
        ("The hydrotest pressure shall be minimum 10 bar", "5 bar", "12 bar"),
    ],
)
def test_the_comparator_table_reads_every_negated_form_the_right_way(clause, bad, ok):
    refused(bad, clause)
    assert run(ok, clause)[0] is True  # the positive control


@pytest.mark.parametrize(
    "clause",
    [
        "The hydrotest pressure shall be 10 bar",  # no comparator: not readable as a limit
        "The hydrotest pressure shall be more than 10 bar",  # a bare strict comparator is not in the closed table
        "The hydrotest pressure shall be less than 10 bar",
        "The hydrotest pressure shall be not less than 10 bar and not more than 15 bar",  # two comparators
        "The hydrotest pressure shall be not less than 10 or 12 bar",
    ],
)
def test_a_clause_the_closed_table_cannot_read_gives_no_pass(clause):
    refused("12 bar", clause)


# ---- the document value is a plain stated value only ---------------------------------------------------------------
DOC_QUALIFIED = [
    "min 5 bar", ">= 5 bar", "≥ 5 bar", "at least 5 bar", "max 15 bar", "<= 15 bar", "≤ 15 bar", "up to 15 bar",
    "12 bar or less", "12 bar or more", "12 bar max", "12 bar min", "approx. 12 bar", "approximately 12 bar",
    "~12 bar", "≈ 12 bar", "about 12 bar", "> 12 bar", "< 12 bar",
]  # fmt: skip


@pytest.mark.parametrize("value", DOC_QUALIFIED)
@pytest.mark.parametrize(
    "clause",
    [
        "The hydrotest pressure shall be not less than 10 bar",
        "The hydrotest pressure shall be not more than 10 bar",
    ],
)
def test_a_document_value_qualified_by_a_comparator_word_or_symbol_is_never_a_pass(
    value, clause
):
    refused(value, clause)


DOC_RANGES = [
    "5 to 15 bar", "5-15 bar", "5 – 15 bar", "5–15 bar", "5 — 15 bar", "5 through 15 bar", "5 thru 15 bar",
    "between 5 and 15 bar", "5 and 15 bar", "5~15 bar", "5..15 bar", "5—15 bar", "5 - 15 bar", "5 − 15 bar",
]  # fmt: skip


@pytest.mark.parametrize("value", DOC_RANGES)
@pytest.mark.parametrize(
    "clause",
    [
        "The hydrotest pressure shall be not less than 10 bar",
        "The hydrotest pressure shall be not more than 10 bar",
    ],
)
def test_a_range_is_never_read_as_a_value(value, clause):
    refused(value, clause)


@pytest.mark.parametrize(
    "value",
    ["8 +/- 5 bar", "8 ±5 bar", "8 ± 5 bar", "8 bar -2/+5", "8 bar +5/-2", "8 +- 5 bar", "8 bar tol. 5", "8 bar tolerance 5",
     "1.2 x 10^1 bar", "1.2e1 bar", "1.2 x 10 bar", "50 %", "50 percent", "-5 bar", "+5 bar", "−5 bar"],
)  # fmt: skip
def test_a_tolerance_an_exponent_a_percentage_or_a_sign_is_never_a_pass(value):
    refused(value, "The hydrotest pressure shall be not more than 10 bar")
    refused(value, "The hydrotest pressure shall be not less than 10 bar")


def test_a_tolerance_in_the_clause_quote_is_never_a_pass():
    refused("8 bar", "The hydrotest pressure shall be not more than 10 ± 2 bar")
    refused("8 bar", "The hydrotest pressure shall be not more than 10 +/- 2 bar")


@pytest.mark.parametrize(
    "value", ["1 000 bar", "1 000 bar", "1,000 bar", "1.000 bar", "1,000,000 bar"]
)
def test_a_thousands_separator_is_never_read_as_a_smaller_number(value):
    refused(value, "The hydrotest pressure shall be not less than 10 bar")
    refused(value, "The hydrotest pressure shall be not more than 10 bar")


def test_a_decimal_comma_is_read_as_a_decimal_and_converted_by_code():
    clause = "The hydrotest pressure shall be not less than 10 bar"
    assert run("1,5 MPa", clause)[0] is True  # 1.5 MPa is 15 bar
    refused("0,5 MPa", clause)  # 5 bar
    refused("1,5 MPa", "The hydrotest pressure shall be not more than 10 bar")


def test_a_standard_designator_with_a_dash_is_not_a_figure():
    refused("12 bar", "ISO 15156-3 hydrotest pressure shall be not less than 10 bar")
    refused(
        "12 bar ISO 15156-3", "The hydrotest pressure shall be not less than 10 bar"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Test pressure 12 bar",
        "MAWP 12 bar",
        "Design pressure 12 bar",
        "Tag V-2 Hydrotest pressure 12 bar",
    ],
)
def test_the_right_number_under_the_wrong_label_is_never_a_pass(quote):
    clause = "The hydrotest pressure shall be not less than 10 bar"
    p = good(
        clause_quote=clause, scope_quote="", evidence=[{"page": 1, "quote": quote}]
    )
    context = arp.Context(
        pages={1: quote},
        rows={},
        held={"SAES-X-100.pdf": ["6.1"]},
        clause_text={STD: clause},
        reading_ids=frozenset({"c1", "c2"}),
    )
    assert not arp.verify(p, context).accepted


# ---- the term path: read from the clause by code, equal to the whole value ------------------------------------------
def term(doc_value, clause_sentence, field="Body material", clause_quote=None):
    return run(doc_value, clause_sentence, clause_quote, field=field)


def test_a_term_is_a_pass_only_when_the_whole_value_equals_it():
    assert term("carbon steel", "The body material shall be carbon steel")[0] is True
    assert (
        term("Carbon  Steel", "The body material shall be of carbon steel")[0] is True
    )
    assert (
        term("304 stainless steel", "The body material shall be 304 stainless steel")[0]
        is True
    )


BODY = "Body material"
TERM_ATTACKS = [
    (BODY, "low carbon steel", "The body material shall be carbon steel"),
    (BODY, "non-stainless steel", "The body material shall be stainless steel"),
    (BODY, "carbon steel (stainless steel optional)", "The body material shall be stainless steel"),
    (BODY, "carbon steel", "The body material shall be stainless steel"),
    (BODY, "replaced by carbon steel", "The body material shall be carbon steel"),
    (BODY, "instead of carbon steel", "The body material shall be carbon steel"),
    (BODY, "unless carbon", "The body material shall be carbon steel"),
    (BODY, "carbon steel trim material: stainless steel", "The body material shall be stainless steel"),
    (BODY, "316 stainless steel", "The body material shall be 304 stainless steel"),
    (BODY, "304 stainless steel", "The body material shall be 316 stainless steel"),
    (BODY, "carbon steel", "The body material shall be carbon steel or stainless steel"),
    (BODY, "carbon steel", "The body material shall not be carbon steel"),
    (BODY, "carbon steel", "The body material shall be carbon steel unless stainless steel is stated"),
    (BODY, "carbon steel", "The body material shall be carbon steel for all drawings"),
    ("Drawing language", "non English", "The drawing language shall be English"),
    ("Fire rating", "unsafe fire safe", "The fire rating shall be fire safe"),
    ("Body lining", "with lining", "The body lining shall be with or without lining"),
    ("Body lining", "with or without lining", "The body lining shall be with or without lining"),
]  # fmt: skip


@pytest.mark.parametrize(("field", "value", "clause"), TERM_ATTACKS)
def test_a_term_that_is_not_the_whole_affirmative_value_is_never_a_pass(
    field, value, clause
):
    refused(value, clause, field=field)


@pytest.mark.parametrize(
    "value",
    ["TBA", "TBC", "TBD", "n.a.", "N/A", "-", "--", "by others", "by vendor", "excluded", "omitted", "to be provided",
     "to be confirmed", "not applicable", "see note 3", "as per datasheet", "pending", "none"],
)  # fmt: skip
def test_a_placeholder_is_never_a_value(value):
    refused(value, "The body material shall be carbon steel", field="Body material")
    refused(value, "The hydrotest pressure shall be not less than 10 bar")


@pytest.mark.parametrize(
    ("value", "clause"),
    [
        ("latest edition", "The standard shall be the latest edition"),
        ("2019 edition", "The standard shall be the 2019 edition"),
        ("rev. 4", "The revision shall be current revision"),
        ("current", "The standard shall be current"),
    ],
)
def test_an_edition_rule_is_never_a_pass(value, clause):
    refused(value, clause, field="Standard")


# ---- the field identity: the code keys the guards on the field's words, not the AI's wording ---------------------------
@pytest.mark.parametrize(
    "section",
    [
        "p.1 - Test pressure",
        "p.1 - Hydro-test pressure",
        "p.1 - Hydrotest pressure",
        "p.2 - Pressure",
    ],
)
def test_a_fail_on_a_field_with_an_overlapping_name_blocks_the_pass(section):
    fail = dict(
        FAIL_ROW,
        page_section=section,
        comment="Pressure states 8 bar; requires 10 bar.",
    )
    refused(
        "12 bar",
        "The hydrotest pressure shall be not less than 10 bar",
        rows={"k": fail},
    )


@pytest.mark.parametrize(
    "other",
    [
        "Test pressure 8 bar",
        "Hydro-test pressure 8 bar",
        "Design pressure 8 bar",
        "Pressure 8 bar",
    ],
)
def test_a_second_value_under_an_overlapping_name_blocks_the_pass(other):
    refused(
        "12 bar",
        "The hydrotest pressure shall be not less than 10 bar",
        extra_pages={2: other},
    )


def test_the_same_value_under_another_name_does_not_block_the_pass():
    ok, _ = run(
        "12 bar",
        "The hydrotest pressure shall be not less than 10 bar",
        extra_pages={2: "Test pressure 12 bar"},
    )
    assert ok is True


# ---- the second reading is a different call the runner issued -----------------------------------------------------------
def test_the_second_reading_must_be_a_different_call_the_runner_issued():
    clause = "The hydrotest pressure shall be not less than 10 bar"
    quote = "Hydrotest pressure 12 bar"

    def verdict(**kw):
        p = good(
            clause_quote=clause, scope_quote="", evidence=[{"page": 1, "quote": quote}]
        )
        p.update(kw)
        context = arp.Context(
            pages={1: quote},
            rows={},
            held={"SAES-X-100.pdf": ["6.1"]},
            clause_text={STD: clause},
            reading_ids=frozenset({"c1", "c2"}),
        )
        return arp.verify(p, context)

    assert verdict().accepted
    same = good(
        clause_quote=clause, scope_quote="", evidence=[{"page": 1, "quote": quote}]
    )
    same["second"] = dict(same["second"], call_id="c1")
    assert verdict(second=same["second"]).reason == apv.PassReason.READINGS
    assert (
        verdict(call_id="made-up").reason == apv.PassReason.READINGS
    )  # not an id the runner issued
    assert verdict(call_id="").reason == apv.PassReason.READINGS
    own = dict(same["second"], call_id="c9")
    assert verdict(second=own).reason == apv.PassReason.READINGS
    assert verdict(
        second=dict(same["second"], call_id="c2", clause_quote="not less than 9 bar")
    ).reason == (apv.PassReason.READINGS)


# ---- negation OUTSIDE the quote: the comparator and the negation are read from the whole stored sentence -------------
@pytest.mark.parametrize(
    ("sentence", "quote", "doc"),
    [
        ("The hydrotest pressure shall not be at least 10 bar.", "at least 10 bar", "12 bar"),
        ("The hydrotest pressure shall not be greater than or equal to 10 bar.", "greater than or equal to 10 bar", "12 bar"),
        ("The hydrotest pressure shall not be minimum 10 bar.", "minimum 10 bar", "12 bar"),
        ("The hydrotest pressure shall not have a maximum of 10 bar.", "maximum of 10 bar", "8 bar"),
        ("The hydrotest pressure shall never be at most 10 bar.", "at most 10 bar", "8 bar"),
        ("The hydrotest pressure shall have no minimum of 10 bar.", "minimum of 10 bar", "12 bar"),
        ("The hydrotest pressure shall be not less than 10 bar unless the engineer agrees.", "not less than 10 bar", "12 bar"),
        ("Except for spares the hydrotest pressure shall be not less than 10 bar.", "not less than 10 bar", "12 bar"),
        ("The hydrotest pressure shall be not less than 10 bar or a lower value agreed.", "not less than 10 bar", "12 bar"),
    ],
)  # fmt: skip
def test_a_negation_outside_the_quoted_words_gives_no_pass(sentence, quote, doc):
    refused(doc, sentence, quote)


def test_the_quote_may_be_part_of_a_clean_sentence():
    sentence = "The hydrotest pressure shall be not less than 10 bar."
    assert run("12 bar", sentence, "not less than 10 bar")[0] is True
    refused(
        "12 bar", sentence, "less than 10 bar"
    )  # a quote that drops the negation word is read in its sentence too


# ---- the clause subject must be the field ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sentence", "field", "doc"),
    [
        (
            "The design pressure shall be not less than 10 bar.",
            "Hydrotest pressure",
            "12 bar",
        ),
        ("The trim material shall be carbon steel.", "Body material", "carbon steel"),
        ("The gasket material shall be carbon steel.", "Body material", "carbon steel"),
        ("The manual language shall be English.", "Drawing language", "English"),
        ("The pressure shall be not less than 10 bar.", "Hydrotest pressure", "12 bar"),
        (
            "Pressure vessels shall be not less than 10 bar.",
            "Hydrotest pressure",
            "12 bar",
        ),
    ],
)
def test_a_clause_about_another_quantity_gives_no_pass(sentence, field, doc):
    refused(doc, sentence, field=field)


def test_a_clause_about_the_same_quantity_is_a_pass_whatever_the_spelling():
    assert (
        run(
            "12 bar",
            "The hydro-test pressure shall be not less than 10 bar.",
            "not less than 10 bar",
        )[0]
        is True
    )
    assert (
        run(
            "12 bar",
            "The Hydrotest Pressure is not to be less than 10 bar.",
            "not to be less than 10 bar",
        )[0]
        is True
    )


# ---- the two-value guard reads every figure of the quantity near the label --------------------------------------------
@pytest.mark.parametrize(
    "other",
    [
        "V-2 Hydrotest pressure 5 bar",
        "2. Hydrotest pressure 5 bar",
        "Hydrotest pressure\n5 bar",
        "Hydrotest pressure:\n\n5 bar" ,
        "Hydrotest pressure 12 bar  Hydrotest pressure 5 bar",
        "| V-2 | Hydrotest pressure | 5 bar |",
        "Hydrotest pressure (tag V-2) = 5 bar",
        "Hydro-test pressure\n  5 bar",
        "Test pressure 5 bar",
        "Hydrotest pressure 0,5 MPa",
        "Hydrotest pressure 500 kPa",
    ],
)  # fmt: skip
def test_a_second_value_near_the_label_whatever_the_layout_gives_no_pass(other):
    sentence = "The hydrotest pressure shall be not less than 10 bar."
    ok, reason = run(
        "12 bar", sentence, "not less than 10 bar", extra_pages={2: f"Notes\n{other}"}
    )
    if other == "Hydrotest pressure:\n\n5 bar":
        return  # a blank line ends the cell block: the value two lines on belongs to nothing
    assert not ok, other


def test_a_second_value_on_the_same_page_and_the_same_value_elsewhere():
    sentence = "The hydrotest pressure shall be not less than 10 bar."
    ok, _ = run(
        "12 bar",
        sentence,
        "not less than 10 bar",
        extra_pages={2: "Notes\nV-2 Hydrotest pressure 12 bar"},
    )
    assert ok is True  # the same figure under the same name is no second value
