"""A drawing page with only a running header is routed to recognition (switch).

IOGP S-619, 1 Nov proof: 25 of 85 pages were one picture over 47 % of the page
under a ~120 character header; needs_ocr stayed 0 and the review never read
them. Invented pages only: a picture is a rendered text page inserted as an
image; no recognition runs.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import figure_page, ocr
from app.config import settings
from app.quality import normalise_text

HEADER = "Specification for Unfired Fusion Welded Pressure Vessels Page 47 of 82 IOGP S-619 April 2022 J.2 Vortex breaker"
BODY = (
    "7.6 Weld inspection. Every butt weld shall be examined by radiography "
    "and the report shall be filed before the vessel is released. "
) * 12


def _picture() -> bytes:
    src = pymupdf.open()
    p = src.new_page()
    p.insert_textbox(pymupdf.Rect(40, 40, 500, 700), "drawing " * 60, fontsize=12)
    return p.get_pixmap(dpi=40).tobytes("png")


def _figure_page(doc, frac_w=0.67, frac_h=0.71, text=HEADER):
    p = doc.new_page()  # 595 x 842
    w, h = p.rect.width * frac_w, p.rect.height * frac_h
    x0 = (p.rect.width - w) / 2
    p.insert_image(pymupdf.Rect(x0, 110, x0 + w, 110 + h), stream=_picture())
    p.insert_textbox(pymupdf.Rect(60, 20, 540, 90), text, fontsize=9)
    return p


def _route(page):
    return ocr.route_page(page, normalise_text(page.get_text("text")))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "figure_page_ocr_enabled", True)


def test_drawing_with_header_only_is_routed_when_switch_on(on):
    doc = pymupdf.open()
    page = _figure_page(doc)
    text = normalise_text(page.get_text("text"))
    assert 100 <= len(text.strip()) <= 300, "the case must beat the old 100-char floor"
    route = _route(page)
    assert route.needs_ocr is True, route.reason
    assert route.code == "figure_page"


def test_switch_off_leaves_the_drawing_page_as_text_layer():
    doc = pymupdf.open()
    route = _route(_figure_page(doc))
    assert route.needs_ocr is False
    assert route.code == "text_layer"


def test_body_text_page_with_a_figure_is_not_routed(on):
    doc = pymupdf.open()
    p = _figure_page(doc, text=BODY[:280] + HEADER)
    p.insert_textbox(pymupdf.Rect(60, 20, 540, 105), BODY, fontsize=7)
    text = normalise_text(p.get_text("text"))
    assert len(text.strip()) > 300
    assert _route(p).needs_ocr is False


def test_small_logo_is_not_a_figure(on):
    doc = pymupdf.open()
    p = _figure_page(doc, frac_w=0.15, frac_h=0.1)
    assert _route(p).needs_ocr is False


def test_figure_with_a_lot_of_text_beside_it_is_not_routed(on):
    """Few characters is not enough: the text blocks must be a sliver of the picture."""
    s = figure_page.route(250, 500000.0, 150000.0, 60000.0)
    assert s.needs_ocr is False


def test_pure_rule_boundaries(on):
    assert figure_page.route(250, 500000.0, 150000.0, 1000.0).code == "figure_page"
    assert figure_page.route(301, 500000.0, 150000.0, 1000.0).needs_ocr is False
    assert figure_page.route(250, 500000.0, 100000.0, 1000.0).needs_ocr is False  # 20 %
