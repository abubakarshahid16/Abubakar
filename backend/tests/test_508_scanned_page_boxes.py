"""#508: visual evidence by page and region on a SCANNED page.

A page with no text layer has nothing `highlight.locate` can find, so the
side-by-side view used to show it unboxed with only the general "could not be
placed" line. Now the page's lines are recognised by the project's own OCR
and the line holding the cited text is boxed - only when exactly one line
holds it. Otherwise the page is shown unboxed WITH THE REASON in words.

The recogniser is stubbed (`ocr.page_lines`) except where the test is about
the recogniser's own coordinates or failure. Invented PDFs only.
"""
from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import evidence_boxes, ocr
from app.db import connect
from app.main import app
from tests.test_508_finding_evidence_image import STD_TEXT, SUB_TEXT, _reviewed
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures


def _scanned(path) -> str:
    """An image-only copy of a PDF: the same page as a picture, no text layer."""
    with pymupdf.open(path) as src:
        pix = src.load_page(0).get_pixmap(matrix=pymupdf.Matrix(2, 2))
        rect = src.load_page(0).rect
    with pymupdf.open() as doc:
        doc.new_page(width=rect.width, height=rect.height).insert_image(rect, pixmap=pix)
        doc.save(str(path))
    return str(path)


def _scan_both(world, finding):
    with connect() as conn:
        for doc_id in (world["std"], world["sub"]):
            path = conn.execute("SELECT stored_path FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
            _scanned(path)


BOX = (72.0, 90.0, 300.0, 104.0)


@pytest.fixture
def lines(monkeypatch):
    """The recognised lines `ocr.page_lines` returns, and the pages asked for."""
    state = {"lines": [], "asked": []}

    def fake(path, sha, page_no):
        state["asked"].append(page_no)
        if isinstance(state["lines"], Exception):
            raise state["lines"]
        return state["lines"]

    monkeypatch.setattr(ocr, "page_lines", fake)
    return state


def _evidence(finding_id, headers):
    return TestClient(app).get(f"/api/reviews/findings/{finding_id}/evidence", headers=headers).json()


def _image(finding_id, headers, side):
    return TestClient(app).get(f"/api/reviews/findings/{finding_id}/evidence-image",
                               headers=headers, params={"side": side})


def test_the_recognised_line_holding_the_cited_text_is_boxed(world, tmp_path, lines):
    finding = _reviewed(world, tmp_path)
    _scan_both(world, finding)
    lines["lines"] = [("Datasheet heading", (72.0, 40.0, 200.0, 52.0)), (STD_TEXT, BOX)]
    body = _evidence(finding["id"], world["admin"])
    assert body["standard"]["box"] == evidence_boxes.OCR_LINE
    assert body["standard"]["reason"] is None and body["standard"]["page"] == finding["standard_page"]
    r = _image(finding["id"], world["admin"], "standard")
    assert r.status_code == 200 and r.headers["x-answer-located"] == "1"
    assert r.headers["x-evidence-box"] == evidence_boxes.OCR_LINE


def test_the_submittal_side_is_boxed_on_its_scanned_page_too(world, tmp_path, lines):
    finding = _reviewed(world, tmp_path)
    _scan_both(world, finding)
    lines["lines"] = [(SUB_TEXT.upper(), BOX)]           # case and spacing do not matter
    # the stored value "95" alone is under the safe length: no box from it
    side = _evidence(finding["id"], world["admin"])["submittal"]
    assert side["box"] is None and "not found in exactly one" in side["reason"]
    # the line the fact was read from is in exactly one recognised line: boxed
    with connect() as conn:
        conn.execute("UPDATE submittal_facts SET source_text = ? WHERE id = ?",
                     ("Noise level 95 dB(A)", finding["fact_id"]))
    assert _evidence(finding["id"], world["admin"])["submittal"]["box"] == evidence_boxes.OCR_LINE


def test_text_in_two_recognised_lines_is_not_boxed_and_says_why(world, tmp_path, lines):
    finding = _reviewed(world, tmp_path)
    _scan_both(world, finding)
    lines["lines"] = [(STD_TEXT, BOX), (STD_TEXT, (72.0, 300.0, 300.0, 314.0))]
    side = _evidence(finding["id"], world["admin"])["standard"]
    assert side["box"] is None
    assert "scanned image with no text layer" in side["reason"]
    assert "exactly one of the lines" in side["reason"]
    assert _image(finding["id"], world["admin"], "standard").headers["x-answer-located"] == "0"


def test_text_not_recognised_is_not_boxed_and_says_why(world, tmp_path, lines):
    finding = _reviewed(world, tmp_path)
    _scan_both(world, finding)
    lines["lines"] = [("Bearing temperature 82 degrees", BOX)]
    side = _evidence(finding["id"], world["admin"])["standard"]
    assert side["box"] is None and "not found in exactly one" in side["reason"]


def test_recognition_that_cannot_run_is_named_never_a_silent_blank(world, tmp_path, lines):
    finding = _reviewed(world, tmp_path)
    _scan_both(world, finding)
    lines["lines"] = ocr.PageLinesUnavailable("recognition could not run: FileNotFoundError")
    side = _evidence(finding["id"], world["admin"])["standard"]
    assert side["box"] is None and side["page"] == finding["standard_page"]
    assert "could not be read here (recognition could not run: FileNotFoundError)" in side["reason"]


def test_a_page_with_a_text_layer_never_asks_the_recogniser(world, tmp_path, lines):
    finding = _reviewed(world, tmp_path)               # text-layer PDFs
    with connect() as conn:
        conn.execute("UPDATE review_findings SET requirement_source_text = ? WHERE id = ?",
                     ("Bearing temperature shall not exceed 82 degrees.", finding["id"]))
    side = _evidence(finding["id"], world["admin"])["standard"]
    assert side["box"] is None and side["reason"] is None   # the general line, as before
    assert lines["asked"] == []


def test_the_recogniser_boxes_land_in_pdf_space(tmp_path, monkeypatch):
    """Recognised boxes are in rendered pixels; the box drawn is in PDF user
    space (the same space `highlight.locate` returns), on a rotated page too."""
    class Engine:
        def __call__(self, image):
            scale = ocr.settings.ocr_dpi / 72.0
            pts = [[100 * scale, 50 * scale], [200 * scale, 50 * scale],
                   [200 * scale, 60 * scale], [100 * scale, 60 * scale]]
            return type("R", (), {"txts": ("Noise level 95 dB(A)",), "boxes": [pts]})()

    monkeypatch.setattr(ocr, "_build_engine", lambda: Engine())
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=400, height=600)
        doc.save(str(path))
    (text, box), = ocr.recognise_page_lines(str(path), "sha-flat", 1)
    assert text == "Noise level 95 dB(A)"
    assert box == pytest.approx((100.0, 50.0, 200.0, 60.0))

    with pymupdf.open(str(path)) as doc:
        doc.load_page(0).set_rotation(90)
        doc.save(str(tmp_path / "rot.pdf"))
    (_, rot), = ocr.recognise_page_lines(str(tmp_path / "rot.pdf"), "sha-rot", 1)
    with pymupdf.open(str(tmp_path / "rot.pdf")) as doc:
        expected = pymupdf.Rect(100, 50, 200, 60) * doc.load_page(0).derotation_matrix
    assert rot == pytest.approx((expected.x0, expected.y0, expected.x1, expected.y1))


def test_a_recogniser_that_cannot_start_is_unavailable_and_not_remembered(tmp_path, monkeypatch):
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(str(path))
    monkeypatch.setattr(ocr, "recognise_page_lines", _raises)
    ocr._PAGE_LINES.clear()
    with pytest.raises(ocr.PageLinesUnavailable, match="could not run: FileNotFoundError"):
        ocr.page_lines(str(path), "sha-x", 1)
    assert ocr._PAGE_LINES == {}
    monkeypatch.setattr(ocr, "recognise_page_lines", _one_line)
    assert ocr.page_lines(str(path), "sha-x", 1) == [("a line", (1.0, 2.0, 3.0, 4.0))]
    monkeypatch.setattr(ocr, "recognise_page_lines", _raises)
    assert ocr.page_lines(str(path), "sha-x", 1) == [("a line", (1.0, 2.0, 3.0, 4.0))]  # remembered


def _raises(path, sha, page_no):
    raise FileNotFoundError("no model")


def _one_line(path, sha, page_no):
    return [("a line", (1.0, 2.0, 3.0, 4.0))]

