"""Test B (part of #805): a part printed alone fills its field, under strict rules. Invented sheets of the same SHAPE
(a bare-part-name materials block, a sentence seal), never a real sheet's text."""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app import form_reader, form_reader_fields, part_name_roles
from app.config import settings

RULES = dc.load_rules()
PUMP = "Centrifugal Pump"
BLOCK = (
    "12\nIMPELLER:        Duplex S.S. ASTM A995 Gr. 4A\n"
    "13\nSHAFT :          Carbon steel AISI 4140\n"
    "14\nCASE:            Cast iron ASTM A48\n"
)


@pytest.fixture(autouse=True)
def switch_on(monkeypatch):
    monkeypatch.setattr(settings, "form_part_name_roles_enabled", True)


def field(key):
    return next(
        f for f in form_reader_fields.field_list_for(PUMP, RULES) if f.key == key
    )


def item(value, quote):
    return {"value": value, "quote": quote, "unit": "", "status": "found"}


def verify(key, value, quote, page=BLOCK):
    return form_reader.verify(field(key), item(value, quote), page, RULES)


# --- the form reader's label gate ---------------------------------------------------------------------------------


def test_a_bare_part_row_with_a_material_value_passes_the_gate_only_with_the_switch_on(
    monkeypatch,
):
    quote = "IMPELLER:        Duplex S.S. ASTM A995 Gr. 4A"
    assert verify("impeller_material", "Duplex S.S. ASTM A995 Gr. 4A", quote) is None
    monkeypatch.setattr(settings, "form_part_name_roles_enabled", False)
    got = verify("impeller_material", "Duplex S.S. ASTM A995 Gr. 4A", quote)
    assert got is form_reader.Reason.LABEL_NOT_IN_QUOTE


def test_a_row_number_before_the_part_is_fine():
    page = "12\nSHAFT :   Carbon steel AISI 4140\n"
    assert (
        verify(
            "shaft_material",
            "Carbon steel AISI 4140",
            "12 SHAFT : Carbon steel AISI 4140",
            page,
        )
        is None
    )


def test_a_sentence_states_the_seal_type():
    page = "Seals\nSEALING SHALL BE A DOUBLE MECHANICAL SEAL\n"
    assert (
        verify(
            "seal_type",
            "DOUBLE MECHANICAL SEAL",
            "SEALING SHALL BE A DOUBLE MECHANICAL SEAL",
            page,
        )
        is None
    )


def test_two_parts_in_one_quote_never_fill():
    both = "IMPELLER: Duplex S.S. SHAFT : Carbon steel"
    assert (
        verify(
            "impeller_material",
            "Duplex S.S.",
            both,
            "IMPELLER: Duplex S.S. SHAFT : Carbon steel",
        )
        is form_reader.Reason.LABEL_NOT_IN_QUOTE
    )


def test_a_part_word_inside_a_longer_phrase_never_fills():
    page = "IMPELLER WEAR RING :  Stellite coated bronze\n"
    got = verify(
        "impeller_material",
        "Stellite coated bronze",
        "IMPELLER WEAR RING : Stellite coated bronze",
        page,
    )
    assert got is form_reader.Reason.LABEL_NOT_IN_QUOTE
    page = "CASE MOUNTING:   GROUTED\n"
    assert (
        verify("casing_material", "GROUTED", "CASE MOUNTING: GROUTED", page)
        is form_reader.Reason.LABEL_NOT_IN_QUOTE
    )


def test_a_value_that_is_not_a_material_never_fills():
    page = "IMPELLER:   3 stage\n"
    assert (
        verify("impeller_material", "3 stage", "IMPELLER: 3 stage", page)
        is form_reader.Reason.LABEL_NOT_IN_QUOTE
    )


def test_a_blank_placeholder_cell_is_refused_before_the_label_is_asked():
    page = "IMPELLER:   ___*___\n"
    got = verify("impeller_material", "___*___", "IMPELLER: ___*___", page)
    assert got is form_reader.Reason.VALUE_IS_BLANK_MARKER


# --- stored facts ---------------------------------------------------------------------------------------------------


def fact(name, value, blank=0, **kw):
    return {
        "field_name": name,
        "field_value": value,
        "is_blank": blank,
        "equipment_tag": None,
        **kw,
    }


WANTED = frozenset({"impeller_material", "shaft_material", "casing_material"})


def names(facts):
    return [f["field_name"] for f in part_name_roles.with_roles(facts, RULES, WANTED)]


def test_a_bare_part_fact_with_a_material_value_is_renamed_to_its_role():
    out = names(
        [
            fact("impeller", "Duplex S.S. ASTM A995"),
            fact("shaft", "Carbon steel"),
            fact("case", "Cast iron"),
        ]
    )
    assert out == ["impeller material", "shaft material", "casing material"]


def test_two_different_values_for_one_part_fill_nothing():
    out = names([fact("impeller", "Duplex S.S."), fact("impeller", "Bronze")])
    assert out == ["impeller", "impeller"]


def test_the_same_value_read_twice_is_one_value():
    out = names([fact("impeller", "Duplex S.S."), fact("impeller", "Duplex S.S.")])
    assert out == ["impeller material", "impeller material"]


def test_a_blank_a_non_material_or_an_already_named_fact_is_left_alone():
    assert names([fact("impeller", "___", blank=1)]) == ["impeller"]
    assert names([fact("impeller", "3 stage")]) == ["impeller"]
    both = [fact("impeller", "Duplex S.S."), fact("impeller material", "Duplex S.S.")]
    assert names(both) == ["impeller", "impeller material"]


def test_the_switch_off_changes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "form_part_name_roles_enabled", False)
    facts = [fact("impeller", "Duplex S.S.")]
    assert part_name_roles.with_roles(facts, RULES, WANTED) is facts


def test_the_check_finds_the_material_it_called_not_found(monkeypatch):
    facts = [
        fact("impeller", "Duplex S.S. ASTM A995"),
        fact("shaft", "Carbon steel"),
        fact("case", "Cast iron"),
    ]
    pages = {1: "x"}
    on = {
        r["rule_id"]: r["status"]
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=pages)
    }
    assert [on[i] for i in ("PMP-12", "PMP-13", "PMP-14")] == ["COMPLIANT"] * 3
    monkeypatch.setattr(settings, "form_part_name_roles_enabled", False)
    off = {
        r["rule_id"]: r["status"]
        for r in dc.evaluate(facts, equipment_type=PUMP, page_texts=pages)
    }
    assert [off[i] for i in ("PMP-12", "PMP-13", "PMP-14")] == [
        "MISSING_INFORMATION"
    ] * 3


def test_two_parts_in_one_quote_never_fill_a_sentence_either():
    quote = "SEALING FOR THE SHAFT SHALL BE A DOUBLE MECHANICAL SEAL"
    got = verify("seal_type", "DOUBLE MECHANICAL SEAL", quote, quote + "\n")
    assert got is form_reader.Reason.LABEL_NOT_IN_QUOTE


# --- the reviewer's wrong-fill cases (the dangerous direction: a wrong fill turns MISSING into COMPLIANT) -------------

PROSE = [
    "CAST AT VENDOR WORKS",
    "NOT CAST IRON",
    "NI",
    "SAME AS CAST IRON",
    "A216 WCB OR CF8M",
    "SEE NOTE 3",
    "6.12.1.1",
    "CAST",
    "BY VENDOR",
    "OPTIONAL BRONZE",
]
GOOD = [
    "Cast iron ASTM A48",
    "ASTM A216 WCB / A105N",
    "316 SS",
    "Bronze",
    "Ni-Resist",
    "Super Duplex S.S. ASTM A890 Gr. 4A/3A",
    "Carbon steel AISI 4140",
]


@pytest.mark.parametrize("value", PROSE)
def test_a_value_that_is_not_only_material_tokens_never_fills_through_the_gate(value):
    quote = f"IMPELLER:   {value}"
    assert verify("impeller_material", value, quote, quote + "\n") is not None
    assert not part_name_roles.accepts("impeller_material", value, quote, RULES)


@pytest.mark.parametrize("value", GOOD)
def test_a_value_made_only_of_material_tokens_fills_through_the_gate(value):
    quote = f"IMPELLER:   {value}"
    assert verify("impeller_material", value, quote, quote + "\n") is None


@pytest.mark.parametrize("value", PROSE)
def test_a_value_that_is_not_only_material_tokens_never_fills_a_stored_fact(value):
    assert names([fact("impeller", value)]) == ["impeller"]


@pytest.mark.parametrize("value", GOOD)
def test_a_value_made_only_of_material_tokens_fills_a_stored_fact(value):
    assert names([fact("impeller", value)]) == ["impeller material"]


@pytest.mark.parametrize(
    "value, quote",
    [
        ("NO SEAL", "PUMP SHALL HAVE NO SEAL"),
        ("SEAL", "SEAL"),
        ("SEAL FLUSH PLAN 11", "SEAL FLUSH PLAN 11"),
        ("NOT INCLUDED", "SEAL IS NOT INCLUDED"),
        ("DOUBLE MECHANICAL SEAL", "NO DOUBLE MECHANICAL SEAL"),
        ("DOUBLE MECHANICAL SEAL", "DOUBLE MECHANICAL SEAL IS OPTIONAL BY OTHERS"),
        (
            "MECHANICAL SEAL TO BE ADVISED",
            "SEALING SHALL BE MECHANICAL SEAL TO BE ADVISED",
        ),
    ],
)
def test_a_seal_that_is_negated_or_not_a_listed_type_never_fills(value, quote):
    assert verify("seal_type", value, quote, quote + "\n") is not None
    assert not part_name_roles.accepts("seal_type", value, quote, RULES)


@pytest.mark.parametrize(
    "value", ["TANDEM MECHANICAL SEAL", "Single mechanical seal", "GLAND PACKING"]
)
def test_a_listed_seal_type_stated_in_a_sentence_fills(value):
    quote = f"SEALING SHALL BE A {value}"
    if "packing" in value.lower():
        quote = "SEALING SHALL BE A GLAND PACKING"
    got = verify("seal_type", value, quote, quote + "\n")
    # packing is not a "seal" word: only a listed phrase that holds the part word can fill
    assert (got is None) == ("seal" in value.lower())
