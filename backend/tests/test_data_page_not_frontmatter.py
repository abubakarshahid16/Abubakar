"""Kit proof 1 Nov: a public filled pump datasheet read 1 of 5 pages. Pages 2-5
each end with a vendor copyright footer, so the chunker set them aside as book
front matter and the fact reader never saw them. A page of measured values is
a data page whatever its footer says. Invented pages only."""

from __future__ import annotations

import pytest

from app import chunker
from app.config import settings

FOOTER = "Copyright © 2014 Acme Pumps. All rights reserved."
DATA_PAGE = (
    "CENTRIFUGAL PUMP DATA SHEET\n"
    + "\n".join(
        f"{label} : {value}"
        for label, value in [
            ("Rated flow", "210.0 l/s"),
            ("Rated head", "48.5 m"),
            ("NPSH required", "4.2 m"),
            ("Speed", "1480 rpm"),
            ("Efficiency", "82 %"),
            ("Power", "132 kW"),
            ("Suction pressure", "1.2 bar"),
            ("Discharge pressure", "6.0 bar"),
            ("Temperature", "35 °C"),
            ("Viscosity", "1.0 cP"),
            ("Impeller diameter", "410 mm"),
            ("Shut-off head", "61 m"),
        ]
    )
    + "\n"
    + FOOTER
)
BOOK_COPYRIGHT_PAGE = (
    "Pump Handbook\nFourth Edition\n" + FOOTER + "\nISBN 978-0-00-000000-0\n"
    "No part of this publication may be reproduced without permission.\n"
    "Printed in the United States of America\n10 9 8 7 6 5 4 3 2 1"
)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "data_page_not_frontmatter_enabled", True)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "data_page_not_frontmatter_enabled", False)


def test_on_a_page_of_measured_values_with_a_copyright_footer_is_not_front_matter(on):
    assert chunker.classify_page(DATA_PAGE, 2, 5) != "frontmatter"


def test_off_the_page_is_front_matter_as_before(off):
    assert chunker.classify_page(DATA_PAGE, 2, 5) == "frontmatter"


def test_on_a_book_copyright_page_is_still_front_matter(on):
    assert chunker.classify_page(BOOK_COPYRIGHT_PAGE, 2, 300) == "frontmatter"


def test_on_labels_and_values_on_separate_lines_still_make_a_data_page(on):
    # PDF text often gives the label on one line and its value on the next.
    rows = []
    for i in range(22):
        rows += [f"Field {i}", f"{10 + i}.5 bar", "", "-"]
    page = "PUMP DATA SHEET\n" + "\n".join(r for r in rows if r) + "\n" + FOOTER
    assert chunker.classify_page(page, 2, 5) != "frontmatter"


EDITION_LIST = (
    "Pump Handbook\n"
    + FOOTER
    + "\n"
    + "\n".join(
        f"{1980 + i} edition, {i % 9 + 1}rd printing, 12 Jan {1980 + i}"
        for i in range(35)
    )
)
CONTRIBUTORS = (
    "List of Contributors\n"
    + FOOTER
    + "\n"
    + "\n".join(
        f"Dr A. Author {i}, Tel 555 01{i:02d} ext {i}, Rev {i}" for i in range(30)
    )
)


@pytest.mark.parametrize("page", [EDITION_LIST, CONTRIBUTORS])
def test_on_an_edition_list_or_contributor_page_stays_front_matter(on, page):
    assert chunker.classify_page(page, 2, 300) == "frontmatter"
