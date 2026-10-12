"""parse_condition: the circumstance a requirement holds under.

Two defects (2026-10-02), both invented-name sentences here:
  * a comma INSIDE the circumstance ("carbon steel, low-alloy steel and alloy
    steel systems") cut it at the first comma, so the requirement kept a
    fragment of its condition;
  * "where ..." / "if ..." sentences with no "shall" returned None, so a
    conditional requirement was stored as unconditional.
Honest behaviour is kept: nothing parseable means None, never an invented
condition, and a leading "unless" is kept verbatim so the downstream reader
(`conditions.read_condition`) sees an unread word and abstains.
"""
from __future__ import annotations

import pytest

from app import conditions, requirements_3b

parse = requirements_3b.parse_condition


def test_commas_inside_the_circumstance_are_kept():
    got = parse("For carbon steel, low-alloy steel and alloy steel systems, "
                "a minimum C.A. of at least 1.6 mm shall be used.")
    assert got == "carbon steel, low-alloy steel and alloy steel systems"


def test_the_subject_after_the_last_comma_is_not_in_the_condition():
    got = parse("For new equipment, the noise level shall not exceed 90 dB(A).")
    assert got == "new equipment"
    assert "noise" not in (parse("For A-grade, B-grade and C-grade pipe, "
                                 "the wall shall be 6 mm.") or "")


def test_where_without_shall_is_conditional():
    got = parse("Where the thickness exceeds 25 mm, PWHT is required.")
    assert got == "the thickness exceeds 25 mm"


def test_if_form_is_conditional():
    assert parse("If the service is sour, PWHT applies.") == "the service is sour"
    assert parse("If the service is sour, welds shall be PWHT treated.") == "the service is sour"


def test_when_form_with_a_comma_in_the_circumstance():
    got = parse("When the service is sour, and the design temperature exceeds "
                "100 C, the weld hardness shall not exceed 22 HRC.")
    assert got == "the service is sour, and the design temperature exceeds 100 C"


def test_a_modal_phrase_inside_the_circumstance_does_not_end_it():
    got = parse("Where PWHT is required, welds shall be inspected after treatment.")
    assert got == "PWHT is required"


def test_unless_is_kept_verbatim_and_never_read_as_positive():
    got = parse("Unless the service is non-sour, welds shall be PWHT treated.")
    assert got == "unless the service is non-sour"
    # The downstream reader must not decide it: "unless" is a word it did not read.
    reading = conditions.read_condition(got)
    assert reading is not None and reading.problem is not None


def test_a_condition_longer_than_the_old_cap_is_not_truncated():
    cond = ("the design temperature exceeds 100 C and the service is sour and the "
            "line size is above NPS 4 and the rating is above Class 600")
    got = parse(f"Where {cond}, welds shall be PWHT treated.")
    assert got == cond


@pytest.mark.parametrize("sentence", [
    "The coating shall be applied for corrosion protection.",
    "Welds shall be PWHT treated where the thickness exceeds 25 mm.",
    "Where the service is sour, welds, flanges, bolts apply here, again, no end.",
    "PWHT is required.",
    "",
])
def test_nothing_parseable_is_none_never_invented(sentence):
    assert parse(sentence) is None


def test_an_over_long_circumstance_is_refused_not_cut():
    cond = " and ".join(f"the line number {n} is in sour service" for n in range(1, 12))
    assert len(cond) > 240
    assert parse(f"Where {cond}, welds shall be PWHT treated.") is None
