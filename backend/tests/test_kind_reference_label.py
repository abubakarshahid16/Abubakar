"""Kit proof 1 Nov: a blank pump datasheet template was called a drawing from
its field label "SERVICE / P&ID NUMBER". A kind word followed by number / no. /
ref names ANOTHER document; it is not this document's title. Invented pages."""

from __future__ import annotations

import pytest

from app import document_kind


def _kind(*lines):
    text = "\n".join(lines) + "\n" + "\n".join(f"Filler {i}" for i in range(10))
    return document_kind.decide_document_kind([{"page_no": 1, "text": text}]).kind


@pytest.mark.parametrize(
    "label",
    [
        "| SERVICE / P&ID NUMBER | | |",
        "Drawing No",
        "SPECIFICATION NO.",
        "Procedure Ref",
        "Datasheet number",
    ],
)
def test_a_label_pointing_at_another_document_is_not_the_title(label):
    assert _kind(label) == "unknown"


def test_the_real_title_still_wins_after_a_reference_label():
    assert _kind("| P&ID NUMBER | |", "CENTRIFUGAL PUMP DATA SHEET") == "datasheet"


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("PIPING AND INSTRUMENT DIAGRAM", "drawing"),
        ("HYDROTEST PROCEDURE", "procedure"),
        ("NUMBERING PROCEDURE", "procedure"),
        ("SPECIFICATION NUMBERING", "specification"),
        ("Datasheet No-Load Test", "datasheet"),
        ("Procedure Numbered Steps", "procedure"),
        ("Drawing Notes", "drawing"),
    ],
)
def test_ordinary_titles_are_unchanged(title, kind):
    assert _kind(title) == kind
