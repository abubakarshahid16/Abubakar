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


def test_a_seal_row_with_one_listed_phrase_states_the_seal_type():
    page = "Seals\nSEAL: DOUBLE MECHANICAL SEAL\nSEAL = Double mechanical seal.\n"
    assert (
        verify(
            "seal_type", "DOUBLE MECHANICAL SEAL", "SEAL: DOUBLE MECHANICAL SEAL", page
        )
        is None
    )
    assert (
        verify(
            "seal_type",
            "DOUBLE MECHANICAL SEAL",
            "SEAL = Double mechanical seal.",
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
    page = "IMPELLER WEAR RING :  Bronze\n"
    got = verify(
        "impeller_material",
        "Bronze",
        "IMPELLER WEAR RING : Bronze",
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
    "ASTM A216 WCB",
    "316 SS",
    "Bronze",
    "Ni-Resist",
    "Super Duplex S.S. ASTM A890 Gr. 4A",
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
def test_a_listed_seal_type_fills_only_as_an_exact_row_never_in_a_sentence(value):
    row = f"SEAL: {value}"
    assert verify("seal_type", value, row, row + "\n") is None
    sentence = f"SEALING SHALL BE A {value}"
    assert verify("seal_type", value, sentence, sentence + "\n") is not None
    assert not part_name_roles.accepts("seal_type", value, sentence, RULES)


# --- 2nd review: the full wrong-fill lists, and the exact-match property ----------------------------------------------

WRONG_VALUES = [
    "2024", "12345", "P101A", "1A", "A1", "3A", "CLASS 150", "API 610", "ISO 2024", "DIN 2024", "316 / WCB", "316, 304",
    "316-304", "A216 WCB, CF8M", "WCB/CF8M", "CAST IRON ASTM", "STEEL", "IRON", "ASTM A216", "A216", "ASTM",
]  # fmt: skip


@pytest.mark.parametrize("value", WRONG_VALUES)
def test_a_code_a_family_word_a_separator_or_a_second_entry_never_fills_gate_or_stored(
    value,
):
    quote = f"IMPELLER: {value}"
    assert not part_name_roles.accepts("impeller_material", value, quote, RULES)
    assert names([fact("impeller", value)]) == ["impeller"]


@pytest.mark.parametrize(
    "quote",
    [
        "SINGLE SEAL OR DOUBLE SEAL",
        "SEAL NEVER DOUBLE SEAL",
        "SEAL N/A SINGLE SEAL",
        "SEAL REMOVED, SINGLE SEAL",
        "SEAL TO BE UPGRADED FROM SINGLE SEAL",
        "PREVIOUS SEAL WAS SINGLE SEAL",
        "SEAL EXCLUDED ; SINGLE SEAL",
        "SEAL: DOUBLE SEAL?",
        "NO SEAL: SINGLE SEAL",
        "SEAL: SINGLE SEAL, DOUBLE SEAL",
    ],
)
def test_a_seal_quote_that_is_not_exactly_label_then_one_phrase_never_fills(quote):
    for value in ("SINGLE SEAL", "DOUBLE SEAL"):
        assert not part_name_roles.accepts("seal_type", value, quote, RULES)


def test_the_positive_controls_still_fill_exactly():
    for value in GOOD:
        assert part_name_roles.material_value(value, RULES), value
    assert part_name_roles.accepts(
        "seal_type", "SINGLE SEAL", "SEAL: SINGLE SEAL.", RULES
    )


def test_property_two_entries_or_an_entry_and_an_extra_word_are_never_one_entry():
    import random

    rng = random.Random(805)
    entries = [*GOOD, *RULES["material_names"]]
    own = {
        " ".join(n.lower().replace("-", " ").split()) for n in RULES["material_names"]
    }
    extras = [
        "or",
        "and",
        "not",
        "at",
        "vendor",
        "works",
        "see",
        "note",
        "per",
        "same",
        "as",
        "with",
        "plus",
        "optional",
        "tbc",
        "n/a",
    ]
    seps = [" ", ", ", " / ", " - ", "; ", " & ", " + ", " or "]
    for _ in range(600):
        a, b = rng.choice(entries), rng.choice(entries)
        joined = a + rng.choice(seps) + b
        flat = " ".join(joined.lower().replace("-", " ").split())
        if (
            flat not in own
        ):  # two plain names that together are a listed name (duplex + ss) are that one entry
            assert not part_name_roles.material_value(joined, RULES), joined
        extra = rng.choice(extras)
        for text in (f"{a} {extra}", f"{extra} {a}", f"{a}, {extra}"):
            assert not part_name_roles.material_value(text, RULES), text


def test_two_printed_grades_are_two_values_for_the_engineer_never_a_fill():
    value = "Super Duplex S.S. ASTM A890 Gr. 4A/3A"
    out = part_name_roles.with_roles([fact("impeller", value)], RULES, WANTED)
    assert [f["field_name"] for f in out] == ["impeller material"] * 2
    assert {f["field_value"] for f in out} == {
        "Super Duplex S.S. ASTM A890 Gr. 4A",
        "Super Duplex S.S. ASTM A890 Gr. 3A",
    }
    res = {
        r["rule_id"]: r
        for r in dc.evaluate(
            [fact("impeller", value)], equipment_type=PUMP, page_texts={1: "x"}
        )
    }
    assert res["PMP-13"]["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in res["PMP-13"]["detail"]


@pytest.mark.parametrize(
    "value",
    ["A216 WCB / A105N", "316 / WCB", "Bronze / Brass", "4A/3A/2A", "NOT 4A/3A"],
)
def test_a_slash_that_is_not_a_range_between_two_grade_codes_is_nothing(value):
    assert part_name_roles.grade_alternatives(value, RULES) == []
    assert names([fact("impeller", value)]) == ["impeller"]
