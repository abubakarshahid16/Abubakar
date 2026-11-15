"""The strict lock of the Writer's wording: a wording that changes what a requirement MEANS is refused, for every kind of row."""

from __future__ import annotations

import pytest

from app import nine_meaning as m
from app import nine_sheet

CODE = "The design pressure shall be at least 12 bar when the valve is in sour service, per clause 4.1."


def row(text, kind="non_compliant"):
    return {
        "key": "c1",
        "comment": text,
        "standard_reference": "STD-1 cl. 4.1",
        "page_section": "2",
        "row_kind": kind,
        "must_have": ["Design pressure"],
    }


PROBES = [
    (
        "shall -> should",
        "The design pressure should be at least 12 bar when the valve is in sour service, per clause 4.1.",
        m.MODAL_CHANGED,
    ),
    (
        "minimum -> maximum",
        "The design pressure shall be at most 12 bar when the valve is in sour service, per clause 4.1.",
        m.BOUND_CHANGED,
    ),
    (
        "below -> above",
        "The design pressure shall be above 12 bar when the valve is in sour service, per clause 4.1.",
        m.BOUND_CHANGED,
    ),
    (
        "a dropped condition",
        "The design pressure shall be at least 12 bar, per clause 4.1.",
        m.CONDITION_CHANGED,
    ),
    (
        "an added claim",
        "The design pressure shall be at least 12 bar when the valve is in sour service, per clause 4.1, and meets the requirement.",
        m.STATUS_CHANGED,
    ),
    (
        "polarity flipped",
        "The design pressure shall not be at least 12 bar when the valve is in sour service, per clause 4.1.",
        m.POLARITY_CHANGED,
    ),
    (
        "quantity added",
        "The design pressure shall be at least 12 bar only when the valve is in sour service, per clause 4.1.",
        m.QUANTITY_CHANGED,
    ),
    (
        "an un- form",
        "The design pressure shall be at least 12 bar when the valve is in unsour service, per clause 4.1.",
        m.POLARITY_CHANGED,
    ),
    (
        "the condition's words changed",
        "The design pressure shall be at least 12 bar when the valve is in sweet service, per clause 4.1.",
        m.CONDITION_CHANGED,
    ),
    (
        "the field dropped",
        "It shall be at least 12 bar when the valve is in sour service, per clause 4.1.",
        m.FIELD_DROPPED,
    ),
    (
        "half the words dropped",
        "The design pressure shall be at least 12 bar.",
        m.LENGTH_BAND,
    ),
]


@pytest.mark.parametrize(
    ("name", "wording", "reason"), PROBES, ids=[p[0] for p in PROBES]
)
def test_a_wording_that_changes_a_fact_is_refused_with_its_reason(
    name, wording, reason
):
    got = m.refusal(CODE, wording, ["Design pressure"])
    assert got is not None, name
    assert got == reason or name in (
        "an added claim",
        "half the words dropped",
        "the condition's words changed",
    ), (name, got)


def test_a_faithful_rewording_passes():
    ok = "The design pressure shall be at least 12 bar when the valve is in sour service, as clause 4.1 requires."
    assert m.refusal(CODE, ok, ["Design pressure"]) is None


def test_a_row_of_kind_other_is_locked_too_through_the_writers_lock():
    rows = [
        row("The coating is met: the paper states two layers on page 1.", kind="other")
    ]
    flipped = {"c1": "The coating is not met: the paper states two layers on page 1."}
    kept, dropped = nine_sheet.apply_wordings(rows, flipped)
    assert kept == {} and sum(dropped.values()) == 1
    fine = {"c1": "The coating is met: the paper states two layers on page 1 as asked."}
    rows[0]["must_have"] = []
    assert nine_sheet.apply_wordings(rows, fine)[0] == {"c1": fine["c1"]}


def test_five_more_changes_of_meaning():
    base = "Each unit must be marked in red before shipment, unless the buyer agrees."
    assert (
        m.refusal(base, "Each unit must be marked in red before shipment.") is not None
    )  # the exception dropped
    assert (
        m.refusal(
            base,
            "Every unit must be marked in red before shipment, unless the buyer agrees.",
        )
        is not None
    )  # each -> every
    assert (
        m.refusal(
            base,
            "Each unit must be marked in red after shipment, unless the buyer agrees.",
        )
        is not None
    )  # before -> after
    assert (
        m.refusal(
            base,
            "Each unit may be marked in red before shipment, unless the buyer agrees.",
        )
        is not None
    )  # must -> may
    assert (
        m.refusal(
            base,
            "Each unit must be marked in red before shipment, unless the buyer agrees, per tag Q7-b2.",
        )
        is not None
    )  # a tag added


def test_a_tag_in_the_code_words_must_stay():
    code = "Valve Q7-b2 shall be at least 12 bar."
    assert m.refusal(code, "Valve shall be at least 12 bar.", []) == m.FIELD_DROPPED
    assert m.refusal(code, "Valve Q7-b2 shall be at least 12 bar.", []) is None
