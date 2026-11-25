"""Order 210, FIX 2: a failed or unsure read of a standard's title block never
holds the whole standard.

The invented pump standard has no Part or Appendix: its first line after the
title is a "candidate start" (found by shape), so the whole standard was one
unit. The model read its scope sentence ("covers centrifugal pumps"), was
unsure the sheet is of that construction and quoted nothing, and every clause
of the standard was held (21 of 35 such replies on the invented set). Now a
hold on the title block is a check with a note; a real Part whose scope read
failed stays held (A-1239). Invented text only; fake model; no database.
"""

from __future__ import annotations

import pytest

from app import ai_applicability, division_text, scope_type_words, subject_scope
from app.config import settings
from tests.test_141_division_scope import (
    GENERAL,
    SPECIAL,
    STEEL,
    FakeModel,
    temp_storage,  # noqa: F401 - used through usefixtures
)
from tests.test_141_division_scope import (
    PAGES as PART_PAGES,
)

SCOPE = "This invented standard covers centrifugal pumps."
TITLE_BLOCK = [
    (
        1,
        "STD-PUMP-0101 Centrifugal pumps (invented)\n"
        "Revision 0 Engineering Standard (invented for testing)\n"
        "1 Scope\n" + SCOPE + "\n"
        "4.2 Design pressure\nThe design pressure shall be at least 12 barg.\n"
        "5.1 Seals\nThe mechanical seal plan shall be stated on the datasheet.\n",
    )
]
pytestmark = pytest.mark.usefixtures("temp_storage")
LIMITS = {"limited": "yes", "construction": "centrifugal pumps", "quote": SCOPE}
UNSURE_TYPE = {"equipment_is": "not stated", "quote": "", "is_that": "unsure"}
PRESSURE = {
    "id": "dp",
    "standard_document_id": "std",
    "page": 1,
    "requirement_text": "The design pressure shall be at least 12 barg.",
    "source_text": "The design pressure shall be at least 12 barg.",
}
SEAL = {
    "id": "seal",
    "standard_document_id": "std",
    "page": 1,
    "requirement_text": "The mechanical seal plan shall be stated on the datasheet.",
    "source_text": "The mechanical seal plan shall be stated on the datasheet.",
}


def _model(scope=LIMITS, construction=UNSURE_TYPE, **kw):
    return FakeModel(scope, construction, **kw)


def _gate(
    model,
    pages=TITLE_BLOCK,
    reqs=(PRESSURE, SEAL),
    facts=(),
    equipment="Centrifugal Pump",
):
    return ai_applicability.division_gate(
        [dict(r) for r in reqs],
        classification={"equipment_type": equipment},
        facts=list(facts),
        standard_labels={"std": "STD-PUMP-0101"},
        provider=model,
        pages_of=lambda sid: pages,
    )


def _ids(rows):
    return [r["requirement"]["id"] if "requirement" in r else r["id"] for r in rows]


def test_the_title_block_is_one_unit_of_its_own_and_is_front_matter():
    text = subject_scope.StandardText(TITLE_BLOCK)
    [top] = division_text._tops(text, division_text.divisions(text))
    assert top["kind"] == "candidate"
    units, _where, _unplaced = division_text.place(
        [dict(PRESSURE), dict(SEAL)], lambda sid: TITLE_BLOCK
    )
    [unit] = units.values()
    assert division_text.is_front_matter(unit)


def test_the_pump_case_an_unsure_type_read_no_longer_holds_the_whole_standard():
    out = _gate(_model())
    assert _ids(out["kept"]) == ["dp", "seal"] and out["held"] == []
    assert out["summary"]["requirements_kept_scope_not_confirmed"] == 2
    assert out["notes"] == {
        "dp": scope_type_words.SCOPE_NOT_CONFIRMED,
        "seal": scope_type_words.SCOPE_NOT_CONFIRMED,
    }


def test_a_scope_read_that_failed_on_the_title_block_is_kept_with_a_note():
    out = _gate(_model(fail="the model is down"))
    assert _ids(out["kept"]) == ["dp", "seal"] and out["held"] == []
    assert set(out["notes"]) == {"dp", "seal"}


def test_an_unsure_scope_on_the_title_block_is_kept_with_a_note():
    out = _gate(
        _model(scope={"limited": "unsure", "construction": None, "quote": None})
    )
    assert _ids(out["kept"]) == ["dp", "seal"] and set(out["notes"]) == {"dp", "seal"}


def test_a_real_part_whose_scope_read_failed_is_still_held():
    """A-1239: a NAMED part (Part ZZ) that nobody could read is never compared."""
    out = _gate(
        _model(fail="the model is down"),
        pages=PART_PAGES,
        reqs=(GENERAL, SPECIAL),
        equipment="Pressure vessel",
    )
    assert "zz" in _ids(out["held"]) and out["notes"] == {}


def test_a_real_part_the_model_is_unsure_of_is_still_held():
    unsure = _model(scope={"limited": "unsure", "construction": None, "quote": None})
    out = _gate(
        unsure,
        pages=PART_PAGES,
        reqs=(SPECIAL,),
        equipment="Pressure vessel",
        facts=STEEL,
    )
    assert _ids(out["held"]) == ["zz"] and out["notes"] == {}


def test_a_model_no_resting_on_a_stated_line_stays_held_on_the_title_block():
    """s3's probe: the standard covers centrifugal pumps, the sheet's own type
    line says Reciprocating Pump, the model says NO quoting it. Code cannot turn
    that into another material of a family, so it is not 'does not apply'; it is
    still the sheet speaking against the standard, so it is HELD, not compared."""
    no = {
        "equipment_is": "Reciprocating Pump",
        "quote": "equipment type: Reciprocating Pump",
        "is_that": "no",
    }
    out = _gate(_model(construction=no), equipment="Reciprocating Pump")
    assert _ids(out["held"]) == ["dp", "seal"] and out["kept"] == []
    assert out["notes"] == {}


def test_a_model_no_that_quotes_no_stated_line_is_an_unread_read_and_is_softened():
    """A rejected reply (its quote is no stated line) is an UNREAD construction:
    on the title block that is a kept clause with the note, like a model that is down."""
    no_quote = {"equipment_is": "x", "quote": "something else", "is_that": "no"}
    out = _gate(_model(construction=no_quote), equipment="Reciprocating Pump")
    assert _ids(out["kept"]) == ["dp", "seal"] and out["held"] == []


def test_a_title_block_with_a_stated_other_material_stays_held():
    """Code found a stated material of another family: that evidence is not
    softened (a candidate start can only hold, never exclude, as before)."""
    pages = [
        (
            1,
            TITLE_BLOCK[0][1].replace(
                "centrifugal pumps", "vessels constructed of titanium"
            ),
        )
    ]
    scope = {
        "limited": "yes",
        "construction": "constructed of titanium",
        "quote": "This invented standard covers vessels constructed of titanium.",
    }
    steel_no = {
        "equipment_is": "Carbon steel plate XQ-70",
        "quote": "Shell material: Carbon steel plate XQ-70",
        "is_that": "no",
    }
    out = _gate(
        _model(scope=scope, construction=steel_no),
        pages=pages,
        facts=STEEL,
        equipment="Pressure vessel",
    )
    assert (
        _ids(out["held"]) == ["dp", "seal"] and out["kept"] == [] and out["notes"] == {}
    )


# ----------------------------------------------- the draft rule: words in the type


@pytest.mark.parametrize(
    "construction, classification, expected",
    [
        ("centrifugal pumps", {"equipment_type": "Centrifugal Pump"}, True),
        ("centrifugal pumps", {"title": "CENTRIFUGAL PUMP DATASHEET"}, True),
        ("magnetic-drive pumps", {"equipment_type": "Centrifugal Pump"}, False),
        ("gas compressors", {"equipment_type": "Compressor"}, False),
        ("pumps for the oil service", {"equipment_type": "Oil Service Pump"}, True),
        ("", {"equipment_type": "Pump"}, False),
        ("centrifugal pumps", None, False),
    ],
)
def test_every_word_of_the_construction_must_be_in_the_type_or_title(
    construction, classification, expected
):
    assert (
        scope_type_words.construction_in_type(construction, classification) is expected
    )


def test_the_rule_is_off_by_default_and_the_model_is_asked():
    assert settings.scope_type_words_rule_enabled is False
    model = _model()
    _gate(
        model,
        facts=[
            {
                "field_name": "casing material",
                "field_label": "Casing material",
                "field_value": "Carbon steel",
            }
        ],
    )
    assert "construction" in model.calls


def test_switched_on_the_rule_applies_without_asking_the_model(monkeypatch):
    monkeypatch.setattr(settings, "scope_type_words_rule_enabled", True)
    model = _model()
    out = _gate(model)
    assert (
        _ids(out["kept"]) == ["dp", "seal"] and out["held"] == [] and out["notes"] == {}
    )
    assert "construction" not in model.calls
