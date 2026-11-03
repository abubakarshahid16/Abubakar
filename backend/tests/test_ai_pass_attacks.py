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
        ("The pressure shall not be more than 10 bar", "15 bar", "8 bar"),
        ("The pressure is not to be more than 10 bar", "15 bar", "8 bar"),
        ("The pressure shall not be greater than 10 bar", "15 bar", "8 bar"),
        ("The pressure shall not be higher than 10 bar", "15 bar", "8 bar"),
        ("The pressure shall not exceed 10 bar", "15 bar", "8 bar"),
        ("The pressure shall be at most 10 bar", "15 bar", "8 bar"),
        ("The pressure shall be maximum 10 bar", "15 bar", "8 bar"),
        ("The pressure shall be not less than 10 bar", "5 bar", "12 bar"),
        ("The pressure is not to be less than 10 bar", "5 bar", "12 bar"),
        ("The pressure shall not be lower than 10 bar", "5 bar", "12 bar"),
        ("The pressure shall not be below 10 bar", "5 bar", "12 bar"),
        ("The pressure shall be at least 10 bar", "5 bar", "12 bar"),
        ("The pressure shall be minimum 10 bar", "5 bar", "12 bar"),
    ],
)
def test_the_comparator_table_reads_every_negated_form_the_right_way(clause, bad, ok):
    refused(bad, clause)
    assert run(ok, clause)[0] is True  # the positive control


@pytest.mark.parametrize(
    "clause",
    [
        "The pressure shall be 10 bar",  # no comparator: not readable as a limit
        "The pressure shall be more than 10 bar",  # a bare strict comparator is not in the closed table
        "The pressure shall be less than 10 bar",
        "The pressure shall be not less than 10 bar and not more than 15 bar",  # two comparators
        "The pressure shall be not less than 10 or 12 bar",
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
        "The pressure shall be not less than 10 bar",
        "The pressure shall be not more than 10 bar",
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
        "The pressure shall be not less than 10 bar",
        "The pressure shall be not more than 10 bar",
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
    refused(value, "The pressure shall be not more than 10 bar")
    refused(value, "The pressure shall be not less than 10 bar")


def test_a_tolerance_in_the_clause_quote_is_never_a_pass():
    refused("8 bar", "The pressure shall be not more than 10 ± 2 bar")
    refused("8 bar", "The pressure shall be not more than 10 +/- 2 bar")


@pytest.mark.parametrize(
    "value", ["1 000 bar", "1 000 bar", "1,000 bar", "1.000 bar", "1,000,000 bar"]
)
def test_a_thousands_separator_is_never_read_as_a_smaller_number(value):
    refused(value, "The pressure shall be not less than 10 bar")
    refused(value, "The pressure shall be not more than 10 bar")


def test_a_decimal_comma_is_read_as_a_decimal_and_converted_by_code():
    clause = "The pressure shall be not less than 10 bar"
    assert run("1,5 MPa", clause)[0] is True  # 1.5 MPa is 15 bar
    refused("0,5 MPa", clause)  # 5 bar
    refused("1,5 MPa", "The pressure shall be not more than 10 bar")


def test_a_standard_designator_with_a_dash_is_not_a_figure():
    refused("12 bar", "ISO 15156-3 shall be not less than 10 bar")
    refused("12 bar ISO 15156-3", "The pressure shall be not less than 10 bar")


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
    clause = "The pressure shall be not less than 10 bar"
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
    assert term("carbon steel", "The material shall be carbon steel")[0] is True
    assert term("Carbon  Steel", "The material shall be of carbon steel")[0] is True
    assert (
        term("304 stainless steel", "The material shall be 304 stainless steel")[0]
        is True
    )


@pytest.mark.parametrize(
    ("value", "clause"),
    [
        ("low carbon steel", "The material shall be carbon steel"),
        ("non-stainless steel", "The material shall be stainless steel"),
        (
            "carbon steel (stainless steel optional)",
            "The material shall be stainless steel",
        ),
        ("carbon steel", "The material shall be stainless steel"),
        ("replaced by carbon steel", "The material shall be carbon steel"),
        ("instead of carbon steel", "The material shall be carbon steel"),
        ("unless carbon", "The material shall be carbon steel"),
        (
            "carbon steel trim material: stainless steel",
            "The material shall be stainless steel",
        ),
        ("316 stainless steel", "The material shall be 304 stainless steel"),
        ("304 stainless steel", "The material shall be 316 stainless steel"),
        ("non English", "The language shall be English"),
        ("unsafe fire safe", "The rating shall be fire safe"),
        ("with lining", "The lining shall be with or without lining"),
        ("with or without lining", "The lining shall be with or without lining"),
        ("carbon steel", "The material shall be carbon steel or stainless steel"),
        ("carbon steel", "The material shall not be carbon steel"),
        (
            "carbon steel",
            "The material shall be carbon steel unless stainless steel is stated",
        ),
    ],
)
def test_a_term_that_is_not_the_whole_affirmative_value_is_never_a_pass(value, clause):
    refused(value, clause)


@pytest.mark.parametrize(
    "value",
    ["TBA", "TBC", "TBD", "n.a.", "N/A", "-", "--", "by others", "by vendor", "excluded", "omitted", "to be provided",
     "to be confirmed", "not applicable", "see note 3", "as per datasheet", "pending", "none"],
)  # fmt: skip
def test_a_placeholder_is_never_a_value(value):
    refused(value, "The material shall be carbon steel")
    refused(value, "The pressure shall be not less than 10 bar")


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
    refused("12 bar", "The pressure shall be not less than 10 bar", rows={"k": fail})


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
        "12 bar", "The pressure shall be not less than 10 bar", extra_pages={2: other}
    )


def test_the_same_value_under_another_name_does_not_block_the_pass():
    ok, _ = run(
        "12 bar",
        "The pressure shall be not less than 10 bar",
        extra_pages={2: "Test pressure 12 bar"},
    )
    assert ok is True


# ---- the second reading is a different call the runner issued -----------------------------------------------------------
def test_the_second_reading_must_be_a_different_call_the_runner_issued():
    clause = "The pressure shall be not less than 10 bar"
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
