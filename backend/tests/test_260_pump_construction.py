"""Order 260.5 (service_unknown): a sentence that names a pump CONSTRUCTION ("for between-bearing
pumps") is decided by the sheet's pump-type line, not held. It does not apply only when a stated
pump-type field names ANOTHER construction; a type line that names none of them stays unknown and
the requirement stays a check/hold. Invented sentences and sheets only (rule 13)."""

from __future__ import annotations

import pytest

from app import service_scope


def req(rid, text):
    return {
        "id": rid,
        "requirement_type": "statement",
        "source_text": text,
        "requirement_text": text,
    }


def fact(label, value):
    return {
        "field_label": label,
        "field_name": label,
        "field_value": value,
        "raw_value": value,
    }


BB = req("bb", "Bearing housings shall be oil lubricated for between-bearing pumps.")
OH = req("oh", "The shaft shall be rigid for overhung pumps.")
BOTH = req(
    "both",
    "Seal chambers shall be vented, for overhung pumps and for between bearing pumps.",
)
PLAIN = req("plain", "Vents shall be provided at every high point.")


def run(requirements, facts):
    out = service_scope.gate(requirements, facts=facts)
    return (
        [r["id"] for r in out["kept"]],
        {i["requirement"]["id"] for i in out["items"]},
        {h["requirement"]["id"] for h in out["held"]},
    )


@pytest.mark.parametrize("type_line", ["API 610 OH2", "overhung, API type OH2"])
def test_a_sheet_that_says_overhung_makes_the_between_bearing_sentence_not_apply(
    type_line,
):
    kept, not_applied, held = run([BB, OH, PLAIN], [fact("Pump type", type_line)])
    assert not_applied == {"bb"}
    assert (
        "oh" in kept and "plain" in kept and "bb" not in held
    )  # the sheet's own is checked


def test_a_sheet_that_says_between_bearings_makes_the_overhung_sentence_not_apply():
    kept, not_applied, _held = run([BB, OH], [fact("API pump type", "BB2")])
    assert not_applied == {"oh"}
    assert kept == ["bb"]


def test_a_type_line_that_names_no_construction_decides_nothing():
    """ "Centrifugal, single stage" is a stated pump-type field naming neither: unknown, so the
    sentence is never dropped (it was not named, so it also stays out of the new vocabulary)."""
    kept, not_applied, held = run(
        [BB, OH], [fact("Pump type", "Centrifugal, single stage")]
    )
    assert not_applied == set()
    assert kept == [] and held == {"bb", "oh"}


def test_no_pump_type_field_decides_nothing():
    kept, not_applied, held = run([BB, OH], [fact("Service", "Crude oil")])
    assert not_applied == set()
    assert kept == [] and held == {"bb", "oh"}


def test_a_sentence_that_also_names_the_sheets_own_construction_is_kept():
    """ "for overhung pumps and for between bearing pumps" applies to the overhung pump on the sheet."""
    kept, not_applied, _held = run([BOTH], [fact("Pump type", "OH1")])
    assert not_applied == set()
    assert kept == ["both"]


def test_a_blank_pump_type_field_decides_nothing():
    kept, not_applied, held = run(
        [BB],
        [{**fact("Pump type", ""), "is_blank": True}, fact("Service", "Crude oil")],
    )
    assert not_applied == set()
    assert kept == [] and held == {"bb"}


def test_the_not_applied_item_cites_the_sheets_own_field_and_value():
    out = service_scope.gate(
        [BB], facts=[{**fact("Pump type", "API 610 OH2"), "page": 3}]
    )
    [item] = out["items"]
    assert "Pump type: API 610 OH2" in item["detail"]
    assert "page 3" in item["detail"]


@pytest.mark.parametrize(
    "text",
    [
        "The seal shall be as described in the following service notes.",
        "The design shall be per ASME application rules.",
        "A similar service duty shall be documented.",
        "For onshore service the coating shall be applied.",
        "The proposed service life shall be stated.",
    ],
)
def test_a_reference_word_or_standards_body_is_not_a_named_service(text):
    from app import clause_support

    assert clause_support.named_conditions(req("x", text)) == []


def test_a_real_service_is_still_named():
    from app import clause_support

    assert clause_support.named_conditions(
        req("x", "The pump shall be suitable for amine service.")
    ) == ["amine"]


# ----- review of #1391: a list, a negation or an exception is never dropped ------------------
LIST_OH = req("lst", "Shaft shall be rigid for overhung and between-bearing pumps.")
NEGATED = req(
    "neg", "Not applicable to overhung pumps; bearing housing shall be vented."
)
EXCEPT = req("exc", "Vent shall be fitted, except between-bearing pumps.")
VERT = req("vert", "Shaft shall be rigid for overhung pumps and vertical pumps.")


@pytest.mark.parametrize(
    ("sentence", "pump_type"),
    [
        (LIST_OH, "API 610 OH2"),
        (LIST_OH, "BB2"),
        (NEGATED, "BB2"),
        (EXCEPT, "OH2"),
        (VERT, "VS1"),
        (VERT, "BB1"),
    ],
)
def test_a_list_a_negation_or_an_exception_is_held_never_dropped(sentence, pump_type):
    kept, not_applied, held = run([sentence], [fact("Pump type", pump_type)])
    assert not_applied == set()
    assert sentence["id"] in set(kept) | held


@pytest.mark.parametrize(
    ("sentence", "pump_type"),
    [(NEGATED, "BB2"), (EXCEPT, "OH2"), (VERT, "BB1")],
)
def test_such_a_sentence_is_held_for_the_engineer_not_compared(sentence, pump_type):
    kept, _not_applied, held = run([sentence], [fact("Pump type", pump_type)])
    assert kept == [] and held == {sentence["id"]}


@pytest.mark.parametrize(
    "value", ["Not overhung", "non-overhung", "not OH2", "No overhung"]
)
def test_a_negated_sheet_value_states_no_construction(value):
    _kept, not_applied, held = run([BB], [fact("Pump type", value)])
    assert not_applied == set()
    assert held == {"bb"}


def test_a_plain_sentence_is_still_dropped_when_the_sheet_names_another_construction():
    kept, not_applied, _held = run([BB], [fact("Pump type", "API 610 OH2")])
    assert not_applied == {"bb"} and kept == []


def test_the_added_generic_words_do_not_hide_a_real_service():
    from app import clause_support

    for text, expected in [
        ("The pump shall be suitable for sour service.", ["sour"]),
        ("The pump shall be suitable for hydrocarbon service.", ["hydrocarbon"]),
        ("Fluid pumps shall be tested.", []),
    ]:
        assert clause_support.named_conditions(req("x", text)) == expected


def test_a_sentence_with_a_conjunction_next_to_the_marker_is_held_not_dropped():
    """Conservative on purpose: "and"/"or" within a few words of the marker may start a list."""
    sentence = req(
        "conj", "Shafts shall be rigid for overhung pumps and shall not deflect."
    )
    kept, not_applied, held = run([sentence], [fact("Pump type", "BB2")])
    assert not_applied == set() and held == {"conj"} and kept == []


@pytest.mark.parametrize(
    "value",
    ["other than overhung", "excluding overhung", "except overhung", "unless overhung"],
)
def test_a_sheet_value_that_excludes_a_construction_states_none(value):
    _kept, not_applied, held = run([BB], [fact("Pump type", value)])
    assert not_applied == set() and held == {"bb"}


@pytest.mark.parametrize("pump_type", ["API 610 OH2", "BB2"])
def test_a_list_gives_one_answer_whichever_construction_is_named_first(pump_type):
    forward = req("fwd", "Shaft shall be rigid for overhung and between-bearing pumps.")
    backward = req(
        "bwd", "Shaft shall be rigid for between-bearing and overhung pumps."
    )
    kept_f, na_f, held_f = run([forward], [fact("Pump type", pump_type)])
    kept_b, na_b, held_b = run([backward], [fact("Pump type", pump_type)])
    assert na_f == set() and na_b == set()
    assert (kept_f == []) == (kept_b == []) and (held_f == set()) == (held_b == set())


def test_only_the_sentences_own_words_can_drop_it_never_the_heading():
    """A clause under a "Vertically suspended pumps" heading whose own sentence names no
    construction ("An alternative pump type is acceptable") is held, not dropped."""
    sentence = {
        **req("alt", "An alternative pump type may be proposed for approval."),
        "standard_document_id": "STD",
        "clause": "9.1",
    }
    out = service_scope.gate(
        [sentence],
        facts=[fact("Pump type", "API 610 OH2")],
        headings_by_standard={"STD": {"9.1": "Vertically suspended pumps"}},
    )
    assert out["items"] == [] and out["kept"] == []
    assert [h["requirement"]["id"] for h in out["held"]] == ["alt"]
