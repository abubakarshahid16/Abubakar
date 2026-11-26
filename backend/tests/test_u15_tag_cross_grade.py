"""A material grade glued to its number ("316L") is never a value with a unit (builder H, 26 Nov 2026: "stainless steel 316L" was read as
316 litres, which would give two papers with different grades a wrong number Question). Invented lines only."""

from __future__ import annotations

from app import tag_cross as T


def _read(line: str) -> list[tuple[str, str, str]]:
    return [(r.field, r.value, r.unit) for r in T.text_readings("d1", "P-001", {1: line + "\n"})]


def test_a_grade_glued_to_its_number_is_no_reading():
    assert _read("Piping material stainless steel 316L") == []
    assert _read("Body material 304L") == []
    assert _read("Trim material 410S") == []


def test_a_one_letter_unit_apart_or_small_and_a_decimal_still_read():
    assert _read("Tank volume 10 L") == [("tank volume", "10", "L")]
    assert _read("Pipe length 6m") == [("pipe length", "6", "m")]
    assert _read("Supply voltage 1.5V") == [("supply voltage", "1.5", "V")]
    assert _read("Design pressure 10 barg") == [("design pressure", "10", "barg")]


def test_the_printed_pair_reader_uses_the_same_rule():
    assert T._grade(T._VALUE.match("316L")) is True
    assert T._grade(T._VALUE.match("10 L")) is False
    assert T._grade(T._VALUE.match("1.5V")) is False
    assert T._grade(T._VALUE.match("25mm")) is False
    assert open(T.__file__).read().count("_grade(m)") == 2  # both readers ask it
