"""#1478 kit proof 1 Nov: a public 5-page pump sheet printed one rights footer
on pages 2-5. Its two drawing pages (a performance curve under a short header
block, three measured values) were set aside as book front matter because of
that footer alone, so the fact reader never saw them. A rights line repeated on
three or more pages is the running footer and is not front-matter evidence.
Invented pages only."""

from __future__ import annotations

import pytest

from app import chunker, data_page
from app.config import settings

FOOTER = "Copyright © 2014 Acme Pumps. All rights reserved."

#: A curve page: a header block of labels and values, curve axis numbers, footer.
CURVE_PAGE = "\n".join(
    [
        ":  ACME PUMP",
        ":  Station 7 duty pump",
        ":  2024-118",
        ":  95.0 l/s",
        ":  62.00 m",
        ":  1.000",
        ":  1480 rpm",
        "CURVES ARE APPROXIMATE, GUARANTEED AT ONE SET OF CONDITIONS",
        "Customer",
        "Item number",
        "Capacity",
        "Head",
        "Specific gravity",
        "Pump speed",
        "0",
        "20",
        "40",
        "60",
        "80",
        "100",
        FOOTER,
        "Curve tool v2",
        "1 of 1",
    ]
)
SHEET_PAGE = "\n".join(
    [
        "Hydraulic Datasheet",
        "Rated flow : 95.0 l/s",
        "Rated head : 62.0 m",
        "Speed : 1480 rpm",
        "Efficiency : 78 %",
        FOOTER,
    ]
)
#: A book's credits page: its own markers besides the repeated footer.
CREDITS_PAGE = "\n".join(
    [
        "Pump Handbook",
        "Fourth Edition",
        FOOTER,
        "ISBN 978-0-00-000000-0",
        "No part of this publication may be reproduced without permission.",
        "Printed in the United States of America",
    ]
)
COVER = "ACME PUMPS\nPump package datasheet\nStation 7\nDocument 2024-118 Rev 0"


def _document(*pages: str) -> list[tuple[int, str]]:
    return list(enumerate(pages, start=1))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "running_footer_not_frontmatter_enabled", True)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "running_footer_not_frontmatter_enabled", False)


SHEET = _document(COVER, SHEET_PAGE, CURVE_PAGE, SHEET_PAGE, CURVE_PAGE)


def test_on_curve_pages_under_a_repeated_footer_are_not_front_matter(on):
    kinds = chunker.classify_document_pages(SHEET, len(SHEET))
    assert kinds[3] != "frontmatter" and kinds[5] != "frontmatter"


def test_off_the_footer_sets_the_curve_pages_aside_as_before(off):
    kinds = chunker.classify_document_pages(SHEET, len(SHEET))
    assert kinds[3] == "frontmatter" and kinds[5] == "frontmatter"


def test_on_the_footer_line_is_found_only_when_it_repeats_on_three_pages(on):
    assert data_page.running_rights_lines(SHEET) == {chunker.normalise_line(FOOTER)}
    two = _document(COVER, CURVE_PAGE, CURVE_PAGE)
    assert data_page.running_rights_lines(two) == frozenset()
    kinds = chunker.classify_document_pages(two, len(two))
    assert kinds[2] == "frontmatter"  # a footer on two pages still counts


def test_on_a_credits_page_keeps_its_own_markers(on):
    book = _document(COVER, CREDITS_PAGE, SHEET_PAGE, SHEET_PAGE, CURVE_PAGE)
    kinds = chunker.classify_document_pages(book, len(book))
    assert kinds[2] == "frontmatter"
    assert kinds[5] != "frontmatter"


def test_off_no_footer_lines_are_found(off):
    assert data_page.running_rights_lines(SHEET) == frozenset()


#: A 7-line cover whose only front-matter marker is the running footer.
TITLE_COVER = "\n".join(
    [
        "ACME PUMPS",
        "Pump package datasheet",
        "Station 7 duty pumps",
        "Document 2024-118",
        "Revision 0",
        "Issued for review",
        FOOTER,
    ]
)
COVERED = _document(TITLE_COVER, SHEET_PAGE, CURVE_PAGE, SHEET_PAGE, CURVE_PAGE)


@pytest.mark.parametrize("switch", [False, True])
def test_a_cover_with_the_footer_keeps_its_title_page_label(monkeypatch, switch):
    monkeypatch.setattr(settings, "running_footer_not_frontmatter_enabled", switch)
    kinds = chunker.classify_document_pages(COVERED, len(COVERED))
    assert kinds[1] == chunker.TITLE_KIND


def test_switching_on_changes_the_chunk_signature_off_leaves_it(monkeypatch):
    monkeypatch.setattr(settings, "running_footer_not_frontmatter_enabled", False)
    off = chunker._chunk_signature("sha", SHEET)
    assert data_page.footer_signature() == ""
    monkeypatch.setattr(settings, "running_footer_not_frontmatter_enabled", True)
    assert chunker._chunk_signature("sha", SHEET) != off
