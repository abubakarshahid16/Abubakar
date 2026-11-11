"""Quote-level OCR confidence (lifted from the lab labeller's tests): alignment of a quote in a page's boxes, and the rule
that uses it. INVENTED boxes and pages."""

from __future__ import annotations

import sqlite3

import pytest

from app import rule_label_ocr as O
from app.config import settings

BOXES = [
    ("The vessel wall thickness shall be", 0.95),
    ("checked before the test pressure is", 0.91),
    ("applied to the item, and the", 0.42),
    ("record kept for ten years.", 0.88),
]


def test_alignment_is_the_minimum_over_the_boxes_the_quote_touches():
    assert O.align_quote("vessel wall thickness shall be", BOXES) == 0.95
    assert O.align_quote("shall be checked before the test pressure", BOXES) == 0.91
    assert O.align_quote("pressure is applied to the item,", BOXES) == 0.42
    assert (
        O.align_quote("test pressure is applied to the item, and the record", BOXES)
        == 0.42
    )
    assert (
        O.align_quote("The VESSEL wall", BOXES) is None
    )  # even the case must match inside the span


def test_alignment_joins_a_hyphen_break_across_boxes_and_needs_every_character_to_match():
    boxes = [
        ("The pressure shall be (ten", 0.9),
        ("bar), and the vessel is mea-", 0.8),
        ("sured at the flange.", 0.6),
    ]
    assert O.align_quote("(ten bar), and the vessel", boxes) == 0.8
    assert (
        O.align_quote("ten bar), and the vessel", boxes) is None
    )  # no edge stripping: "(ten" is not "ten"
    assert (
        O.align_quote("vessel is measured at the flange.", boxes) == 0.6
    )  # "mea-" + "sured" is one word
    assert (
        O.align_quote("vessel is measured at the flange", boxes) is None
    )  # the box ends with a full stop
    assert O.align_quote("is measured at", boxes) == 0.6


def test_alignment_is_unknown_when_it_cannot_be_done():
    assert O.align_quote("words that are not on the page", BOXES) is None
    assert O.align_quote("vessel wall", []) is None
    assert O.align_quote("", BOXES) is None and O.align_quote(None, BOXES) is None
    assert O.align_quote("vessel wall", [("The vessel wall", None)]) is None
    assert (
        O.align_quote("elsewhere", [("The vessel wall", None), ("elsewhere", 0.9)])
        == 0.9
    )
    assert O.align_quote("x " * 50, BOXES) is None


def test_a_quote_standing_twice_gets_the_lowest_of_its_places():
    boxes = [
        ("shall be marked clearly", 0.9),
        ("and later shall be marked clearly", 0.5),
    ]
    assert O.align_quote("shall be marked clearly", boxes) == 0.5


@pytest.mark.parametrize(
    "quote,page",
    [
        ("at least >= 5 mm", "at least < 5 mm"),
        ("at least >= 5 mm", "at least <= 5 mm"),
        ("at least >= 5 mm", "at least > 5 mm"),
        ("temp -5 C max", "temp 5 C max"),
        ("temp -5 C max", "temp +5 C max"),
        ("temp 5 C max", "temp -5 C max"),
        ("not less than 5 % of it", "not less than 5 of it"),
        ("at 5 °C or less", "at 5 C or less"),
        ("rate (5) mm wide", "rate 5 mm wide"),
        ("of 5 MPa or more", "of 5 MPA or more"),
        ("of 5 mPa or more", "of 5 MPa or more"),
        ("it is not allowed here", "it is allowed here"),
        ("a gap of 0.5 mm here", "a gap of .5 mm here"),
        ("a gap of 0.5 mm here", "a gap of 1,5 mm here"),
        ("a gap of 5 mm here", "a gap of 6 mm here"),
    ],
)
def test_a_difference_inside_the_quote_span_means_no_alignment(quote, page):
    assert O.align_quote(quote, [(page, 0.99)]) is None
    assert O.align_quote(quote, [(quote, 0.99)]) == 0.99


@pytest.mark.parametrize(
    "quote,page",
    [
        ("5 mm", ".5 mm"),
        ("5 mm", ",5 mm"),
        (".5 mm", "5 mm"),
        ("is 5", 'is 5"'),
        ("is 5", "is 5'"),
        ("is 5", "is 5."),
        ("is 5.", "is 5"),
        ("is 5", "is 5,"),
        ("the gauge shall read >= 5 bar", 'He said: "the gauge shall read >= 5 bar.'),
        ("(the gauge shall read >= 5 bar)", "the gauge shall read >= 5 bar,"),
        ("shall be at least 5 %", "shall be at least 5"),
        ("-5 C or less", "5 C or less"),
        ("is >=", "is >"),
        ("The vessel", "the vessel"),
    ],
)
def test_there_is_no_edge_stripping_every_character_of_the_quote_must_match(
    quote, page
):
    assert O.align_quote(quote, [(page, 0.99)]) is None
    assert O.align_quote(quote, [(quote, 0.99)]) == 0.99


def test_edge_symbols_stay_exact_when_the_quote_continues_on_both_sides():
    assert O.align_quote("is 5 mm", [("it is 5 mm more", 0.9)]) == 0.9
    assert O.align_quote("is 5 mm", [("it is 5 mm.", 0.9)]) is None
    assert O.align_quote("is 5 mm", [("it is .5 mm", 0.9)]) is None


@pytest.mark.parametrize(
    "quote,page",
    [
        ("5 - 10", "5 10"),
        ("5- 10", "510"),
        ("temp - 5", "temp 5"),
        ("pressure -  5 bar", "pressure 5 bar"),
        ("5 - 10 mm", "5 10 mm"),
        ("a 5- 10 b", "a 510 b"),
        ("range 5 \u2013 10", "range 5 10"),
    ],
)
def test_a_dash_or_minus_or_a_digit_hyphen_is_never_removed_from_the_quote(quote, page):
    assert O.align_quote(quote, [(page, 0.9)]) is None
    assert O.align_quote(quote, [(quote, 0.9)]) == 0.9


def test_only_a_letter_hyphen_whitespace_letter_break_is_joined_and_on_both_sides_alike():
    assert (
        O.align_quote(
            "the vessel is mea- sured here", [("the vessel is measured here", 0.9)]
        )
        == 0.9
    )
    assert (
        O.align_quote(
            "the vessel is measured here", [("the vessel is mea- sured here", 0.9)]
        )
        == 0.9
    )
    assert (
        O.align_quote(
            "the vessel is mea- sured here",
            [("the vessel is mea-", 0.9), ("sured here", 0.7)],
        )
        == 0.7
    )
    assert (
        O.align_quote(
            "the vessel is measured here",
            [("the vessel is mea-", 0.9), ("sured here", 0.7)],
        )
        == 0.7
    )
    assert O.align_quote("grade 5- mm here", [("grade 5- mm here", 0.9)]) == 0.9
    assert O.align_quote("grade 5- mm here", [("grade 5mm here", 0.9)]) is None
    assert O.align_quote("a - b c", [("a b c", 0.9)]) is None
    assert O.align_quote("a -b c", [("a b c", 0.9)]) is None


# ---------------------------------------------------------------- the rule that uses it

QUOTE = "The vessel wall thickness shall be checked before the test"
RECOGNISED = {"page_source": "recognised", "page_min_conf": 0.2}
NATIVE = {"page_source": "native", "page_min_conf": None}


def db(boxes=None, page_row=True):
    conn = sqlite3.connect(":memory:")
    if boxes is not None:
        conn.execute(
            "CREATE TABLE ocr_box (document_id TEXT, page_no INTEGER, seq INTEGER, text TEXT, score REAL)"
        )
        conn.execute(
            "CREATE TABLE ocr_box_page (document_id TEXT, page_no INTEGER, engine TEXT, extracted_at TEXT, matches_page INTEGER)"
        )
        if page_row:
            conn.execute("INSERT INTO ocr_box_page VALUES ('d1', 1, 'e', 't', 0)")
        for i, (t, s) in enumerate(boxes):
            conn.execute("INSERT INTO ocr_box VALUES ('d1', 1, ?, ?, ?)", (i, t, s))
    return conn


def test_a_weak_box_elsewhere_on_the_page_does_not_demote_a_clean_quote_but_a_touched_one_does():
    conn = db(BOXES)
    assert (
        O.quote_is_low(
            conn, "d1", 1, "vessel wall thickness shall be checked", RECOGNISED
        )
        is False
    )
    assert (
        O.quote_is_low(
            conn, "d1", 1, "test pressure is applied to the item", RECOGNISED
        )
        is True
    )


def test_unknown_is_low_no_row_not_aligned_or_no_score():
    assert (
        O.quote_is_low(
            db(BOXES, page_row=False), "d1", 1, "vessel wall thickness", RECOGNISED
        )
        is True
    )
    assert (
        O.quote_is_low(db(BOXES), "d1", 1, "words that are not there", RECOGNISED)
        is True
    )
    assert (
        O.quote_is_low(
            db([("The vessel wall", None)]), "d1", 1, "vessel wall", RECOGNISED
        )
        is True
    )


def test_the_threshold_is_the_apps_own(monkeypatch):
    conn = db([("The vessel wall thickness", 0.75)])
    monkeypatch.setattr(settings, "ocr_low_conf_threshold", 0.70)
    assert O.quote_is_low(conn, "d1", 1, "vessel wall thickness", RECOGNISED) is False
    monkeypatch.setattr(settings, "ocr_low_conf_threshold", 0.80)
    assert O.quote_is_low(conn, "d1", 1, "vessel wall thickness", RECOGNISED) is True


def test_a_text_layer_page_is_never_low_and_an_unknown_source_needs_box_evidence():
    assert O.quote_is_low(db(), "d1", 1, QUOTE, NATIVE) is False
    assert O.quote_is_low(db(), "d1", 1, QUOTE, None) is True  # no origin row, no boxes
    assert (
        O.quote_is_low(
            db([("The vessel wall thickness", 0.95)]),
            "d1",
            1,
            "vessel wall thickness",
            None,
        )
        is False
    )


def test_without_a_box_table_the_strict_page_rule_stays():
    assert O.quote_is_low(db(), "d1", 1, QUOTE, RECOGNISED) is True
    assert (
        O.quote_is_low(
            db(), "d1", 1, QUOTE, {"page_source": "recognised", "page_min_conf": 0.99}
        )
        is False
    )
    assert (
        O.quote_is_low(
            db(), "d1", 1, QUOTE, {"page_source": "recognised", "page_min_conf": None}
        )
        is True
    )
