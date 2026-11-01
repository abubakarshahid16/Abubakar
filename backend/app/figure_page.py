"""A drawing page whose only text is the running header is a scan in all but name.

IOGP S-619 (public vessel specification, 1 Nov proof): 25 of its 85 pages are a
standard drawing, one raster picture over 47 % of the page, under a 100-150
character running header. The router (`ocr.route_decision`) sends a page to
recognition only when images cover half the page, so these pages kept needs_ocr
= 0, their chunks were a header and nothing else, and the chunker dropped them
(`page_yielded_no_chunk`, `content_quality_gate`): the review never read them.

Behind FIGURE_PAGE_OCR_ENABLED a page is recognised too when ONE large picture
covers a quarter of it and the text layer is furniture only (few characters,
text blocks a sliver of the picture). A body-text page with a figure has far
more text and is not touched.
"""

from __future__ import annotations

from .config import settings

#: A picture this share of the page is a figure, not a logo.
FIGURE_COVERAGE_MIN = 0.25
#: Text layer at most this long is page furniture (header, footer, stamp).
FIGURE_MAX_CHARS = 300
#: Text blocks under this share of the picture's area: the picture is the page.
FIGURE_MAX_TEXT_TO_IMAGE = 0.10


def measure_floor() -> float:
    """Image coverage from which `ocr.route_page` must measure the text blocks."""
    if settings.figure_page_ocr_enabled:
        return min(FIGURE_COVERAGE_MIN, settings.ocr_image_coverage_min)
    return settings.ocr_image_coverage_min


def is_figure_page(
    chars: int, coverage: float, image_area: float, text_area: float | None
) -> bool:
    """True when (switch on) a figure fills the page and the text is furniture."""
    if not settings.figure_page_ocr_enabled or image_area <= 0:
        return False
    if coverage < FIGURE_COVERAGE_MIN or chars > FIGURE_MAX_CHARS:
        return False
    return (text_area or 0.0) / image_area < FIGURE_MAX_TEXT_TO_IMAGE


def route(chars: int, page_area: float, image_area: float, text_area: float | None):
    """`ocr.route_decision`, except a figure page with furniture text goes to recognition."""
    from .ocr import Route, route_decision  # ocr imports this module

    coverage = min(1.0, image_area / page_area) if page_area > 0 else 0.0
    below_scan = (
        coverage < settings.ocr_image_coverage_min
    )  # above it, the scan rule decides
    if (
        below_scan
        and chars >= settings.ocr_min_usable_chars
        and is_figure_page(chars, coverage, image_area, text_area)
    ):
        return Route(
            True,
            "figure_page",
            f"figure_page: a picture covers {coverage:.0%} of the page, "
            f"text layer {chars} characters (header or footer only)",
        )
    return route_decision(chars, page_area, image_area, text_area)
