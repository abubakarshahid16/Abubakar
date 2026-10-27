"""#505: a citation to a scanned page shows how well the page was read.

The tier is the recogniser's own confidence grouped by stated cut-offs, with its
denominator; a page with a text layer has no tier; a scanned page with no usable
record says so by name. Invented pages and rows only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import scan_quality
from app.db import connect
from app.main import app
from tests.test_508_finding_evidence_image import _reviewed
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _user,
    temp_storage,
    world,
)


@pytest.fixture
def w(request):
    return request.getfixturevalue("world")


@pytest.mark.parametrize(
    ("mean", "low", "boxes", "tier"),
    [
        (0.97, 0, 100, scan_quality.CLEAR),
        (0.90, 5, 100, scan_quality.CLEAR),
        (0.90, 6, 100, scan_quality.MIXED),
        (0.80, 0, 100, scan_quality.MIXED),
        (0.84, 1, 100, scan_quality.MIXED),
        (0.69, 0, 100, scan_quality.POOR),
        (0.95, 21, 100, scan_quality.POOR),
        (0.90, 20, 100, scan_quality.MIXED),
        (None, 0, 0, scan_quality.NOT_CHECKED),
        (0.95, 0, 0, scan_quality.NOT_CHECKED),
        (None, 0, 12, scan_quality.NOT_CHECKED),
    ],
)
def test_the_tier_follows_the_stated_cut_offs(mean, low, boxes, tier):
    assert scan_quality.tier_of(mean, low, boxes) == tier


def _ocr(doc, page, *, mean=0.92, low=1, boxes=40, error=None):
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO page_ocr
               (document_id, page_no, text, char_count, engine, model, dpi, mean_conf,
                low_conf_boxes, box_count, seconds, recognised_at, batch_no, error)
               VALUES (?,?,'x',1,'e','m',150,?,?,?,0.1,'2026-10-27T00:00:00Z',0,?)""",
            (doc, page, mean, low, boxes, error),
        )


def test_a_recognised_page_carries_its_tier_and_denominator(w):
    _ocr(w["sub"], 1, mean=0.9, low=2, boxes=40)
    scan = scan_quality.for_page(w["sub"], 1)
    assert scan["tier"] == scan_quality.CLEAR
    assert (scan["low_conf_boxes"], scan["box_count"], scan["mean_conf"]) == (
        2,
        40,
        0.9,
    )


def test_a_poorly_read_page_says_to_check_by_eye(w):
    _ocr(w["sub"], 1, mean=0.55, low=20, boxes=40)
    scan = scan_quality.for_page(w["sub"], 1)
    assert scan["tier"] == scan_quality.POOR and "by eye" in scan["words"]


def test_a_failed_page_is_named_not_graded(w):
    _ocr(w["sub"], 1, mean=None, low=0, boxes=0, error="boom")
    scan = scan_quality.for_page(w["sub"], 1)
    assert scan["tier"] == scan_quality.COULD_NOT_READ
    assert scan["mean_conf"] is None and scan["box_count"] is None


def test_a_page_with_no_confidence_is_not_checked_never_clear(w):
    _ocr(w["sub"], 1, mean=None, low=0, boxes=0)
    assert scan_quality.for_page(w["sub"], 1)["tier"] == scan_quality.NOT_CHECKED


def _page(doc, page, needs_ocr):
    with connect() as conn:
        conn.execute(
            "DELETE FROM page_ocr WHERE document_id = ? AND page_no = ?", (doc, page)
        )
        conn.execute(
            "INSERT OR REPLACE INTO pages (document_id, page_no, text, char_count, needs_ocr, batch_no)"
            " VALUES (?,?,'',0,?,0)",
            (doc, page, needs_ocr),
        )


def test_a_scanned_page_not_read_yet_is_named(w):
    _page(w["sub"], 7, 1)
    assert scan_quality.for_page(w["sub"], 7)["tier"] == scan_quality.NOT_YET_READ


def test_a_text_layer_page_has_no_scan_record(w):
    _page(w["sub"], 7, 0)
    assert scan_quality.for_page(w["sub"], 7) is None
    assert scan_quality.for_page(None, 7) is None
    assert scan_quality.for_page(w["sub"], None) is None


def test_the_evidence_route_carries_the_scan_of_each_side(w, tmp_path):
    finding = _reviewed(w, tmp_path)
    _ocr(w["sub"], finding["contractor_page"], mean=0.6, low=15, boxes=40)
    r = TestClient(app).get(
        f"/api/reviews/findings/{finding['id']}/evidence", headers=w["admin"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submittal"]["scan"]["tier"] == scan_quality.POOR
    assert body["submittal"]["scan"]["box_count"] == 40
    assert body["standard"]["scan"] is None
