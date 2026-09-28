"""OCR routing by page content, merge with the text layer, and per-page failure.

Audit F6: a page went to recognition only when its text layer had fewer than
100 characters. A scanned page carrying a digital header, footer and DCC stamp
(238 characters on the audited submittal) was never read, and nothing recorded
it. Routing is now per page, by image coverage and text density
(`ocr.route_page`), with the reason stored on the page and shown in the ledger.

Audit F7: one page the recogniser could not process stayed pending forever and
the ingest loop failed the whole document. It is now stored as a failed page,
consumed, shown as unread with its reason, and the rest is embedded.

Every PDF here is synthetic: a "scan" is a rendered page inserted as an image,
with real text-layer furniture drawn over it. No client file (CLAUDE.md
rule 3). No real recognition runs - the engine is faked at the boundary ocr.py
owns, as in test_ocr.py.

Mutations: M1250-M1264 (`python scripts/mutation_check.py --only M1250 ...`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, extract, ocr, page_ledger, states
from app.config import settings
from app.db import connect
from app.quality import normalise_text


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


# ------------------------------------------------------------ synthetic pages

BODY = ("7.6 Cathodic Protection Continuity. The electrical resistance between "
        "any two points of the bonded structure shall not exceed 0.01 ohm. ") * 14
HEADER = "COMPANY CONFIDENTIAL - Uncontrolled when printed   Doc No. 216400-C-0001 Rev 2"
FOOTER = "Page 15 of 26                Issued for Construction"
STAMP = "DCC RECEIVED 2026-09-01   Code A - Approved"
DENSE = "The contractor shall submit the coating procedure for approval before work starts. "


def _scan_png(text: str = BODY) -> bytes:
    """A page of text, rasterised: what a scanner hands back."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_textbox(pymupdf.Rect(72, 90, 540, 740), text, fontsize=10)
    return p.get_pixmap(dpi=100, colorspace=pymupdf.csGRAY).tobytes("png")


def _furniture(page) -> None:
    page.insert_text((40, 30), HEADER, fontsize=8)
    page.insert_text((40, 815), FOOTER, fontsize=8)
    page.insert_text((380, 60), STAMP, fontsize=8)


def add_dense_text(doc) -> None:
    p = doc.new_page()
    p.insert_textbox(pymupdf.Rect(60, 60, 540, 790), DENSE * 45, fontsize=9)


def add_text_with_logo(doc) -> None:
    logo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
    logo.clear_with(200)
    p = doc.new_page()
    p.insert_image(pymupdf.Rect(60, 40, 120, 100), stream=logo.tobytes("png"))
    p.insert_textbox(pymupdf.Rect(60, 110, 540, 790), DENSE * 30, fontsize=9)


def add_stamped_scan(doc) -> None:
    """The audited case: scanned body, digital header/footer/stamp on top."""
    p = doc.new_page()
    p.insert_image(p.rect, stream=_scan_png())
    _furniture(p)


def add_scan_with_invisible_ocr_layer(doc) -> None:
    """A scanner that already OCR'd: full-page image, dense invisible text."""
    p = doc.new_page()
    p.insert_image(p.rect, stream=_scan_png())
    p.insert_textbox(pymupdf.Rect(72, 90, 540, 740), BODY, fontsize=10, render_mode=3)
    _furniture(p)


def make_pdf(path, *builders) -> str:
    doc = pymupdf.open()
    for b in builders:
        b(doc)
    doc.save(str(path))
    doc.close()
    return str(path)


def upload(path) -> str:
    from app.main import app
    with open(path, "rb") as fh:
        return TestClient(app).post(
            "/api/documents", files={"file": ("doc.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]


def pages(doc_id: str) -> dict[int, dict]:
    return {r["page_no"]: dict(r) for r in connect().execute(
        "SELECT page_no, char_count, needs_ocr, ocr_route, ocr_route_version"
        " FROM pages WHERE document_id = ?", (doc_id,))}


def _route(builder):
    doc = pymupdf.open()
    builder(doc)
    page = doc.load_page(0)
    return ocr.route_page(page, normalise_text(page.get_text("text")))


# ------------------------------------------------------------------ routing

def test_a_normal_dense_text_page_is_not_routed_to_ocr():
    """Recognition costs ~1.1 s/page. A text page must never pay it.

    A logo in the corner is not a scan either.
    """
    for builder in (add_dense_text, add_text_with_logo):
        route = _route(builder)
        assert route.needs_ocr is False, route.reason
        assert route.code == "text_layer"


def test_a_scanned_page_with_a_digital_header_and_stamp_is_routed_to_ocr():
    """F6. Over the old 100-character floor, and still a scan."""
    doc = pymupdf.open()
    add_stamped_scan(doc)
    page = doc.load_page(0)
    text = normalise_text(page.get_text("text"))
    assert len(text.strip()) >= 100, "the case must beat the old count-only rule"
    route = ocr.route_page(page, text)
    assert route.needs_ocr is True, route.reason
    assert route.code == "image_dominant"
    assert "images cover 100%" in route.reason


def test_a_scan_that_already_carries_an_ocr_text_layer_is_not_recognised_again():
    """Dense (invisible) text over the image: the text layer IS the reading."""
    route = _route(add_scan_with_invisible_ocr_layer)
    assert route.needs_ocr is False, route.reason
    assert route.reason.startswith("text_layer: dense text over image")


def test_a_page_without_a_text_layer_is_still_routed():
    doc = pymupdf.open()
    doc.new_page()
    route = ocr.route_page(doc.load_page(0), "")
    assert route.needs_ocr is True
    assert route.code == "no_text_layer"


def test_the_thresholds_come_from_settings(monkeypatch):
    """Configurable, not a literal: an impossible coverage floor routes nothing."""
    monkeypatch.setattr(settings, "ocr_image_coverage_min", 1.01)
    assert _route(add_stamped_scan).needs_ocr is False
    monkeypatch.setattr(settings, "ocr_image_coverage_min", 0.5)
    monkeypatch.setattr(settings, "ocr_min_usable_chars", 5000)
    assert _route(add_dense_text).code == "no_text_layer"


def test_overlapping_images_are_not_counted_twice():
    half = (0.0, 0.0, 100.0, 50.0)
    assert ocr._union_area([half, half, half]) == pytest.approx(5000.0)
    assert ocr._union_area([(0, 0, 10, 10), (5, 5, 15, 15)]) == pytest.approx(175.0)
    # A page half covered by three stacked copies of one image is half covered.
    route = ocr.route_decision(500, 10000.0, ocr._union_area([half] * 3), 100.0)
    assert "images cover 50%" in route.reason


def test_extraction_records_the_decision_and_its_reason_on_every_page(tmp_path):
    """The UI and an audit can say why a page was, or was not, OCR'd."""
    doc_id = upload(make_pdf(tmp_path / "mix.pdf", add_dense_text, add_stamped_scan,
                             add_scan_with_invisible_ocr_layer))
    extract.extract_document(doc_id)
    got = pages(doc_id)
    assert [got[p]["needs_ocr"] for p in (1, 2, 3)] == [0, 1, 0]
    assert got[1]["ocr_route"].startswith("text_layer:")
    assert got[2]["ocr_route"].startswith("image_dominant:")
    assert got[3]["ocr_route"].startswith("text_layer: dense text over image")
    assert {got[p]["ocr_route_version"] for p in got} == {ocr.OCR_ROUTE_VERSION}
    # Counts only - the reason never carries page text.
    assert "Cathodic" not in got[2]["ocr_route"] and "CONFIDENTIAL" not in got[2]["ocr_route"]
    assert connect().execute("SELECT needs_ocr_pages FROM documents WHERE id = ?",
                             (doc_id,)).fetchone()["needs_ocr_pages"] == 1
    # And the ledger shows it.
    page_ledger.refresh(doc_id)
    ledger = {r["page_no"]: r for r in page_ledger.rows(doc_id)}
    assert ledger[2]["ocr_status"] == "pending"
    assert ledger[2]["ocr_reason"].startswith("image_dominant:")
    assert ledger[1]["ocr_status"] == "not_required"
    assert ledger[1]["ocr_reason"].startswith("text_layer:")


def test_low_conf_boxes_survives_storage_and_reaches_the_ledger(tmp_path, monkeypatch):
    """The count is not just computed - it is PERSISTED and SURFACED.

    Goes through the real `_commit_batch` (page_ocr) and `page_ledger.refresh`
    (page_ledger), not just the in-memory tuple `recognise_batch` returns.
    """
    doc_id = upload(make_pdf(tmp_path / "s.pdf", add_dense_text, add_stamped_scan))
    extract.extract_document(doc_id)
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)

    def fake_batch(stored_path, sha256, page_nos):
        # page 2 is the scanned one; give it 3 low-confidence boxes.
        return [(p, "some recognised text", 0.6, 0.05, 10, 3, 0.5, 0, "", None)
                if p == 2 else (p, "", None, None, 0, 0, 0.1, 0, "", None)
                for p in page_nos]
    monkeypatch.setattr(ocr, "recognise_batch", fake_batch)
    ocr.recognise_document(doc_id)

    stored = connect().execute(
        "SELECT low_conf_boxes FROM page_ocr WHERE document_id = ? AND page_no = 2",
        (doc_id,)).fetchone()
    assert stored["low_conf_boxes"] == 3

    page_ledger.refresh(doc_id)
    ledger = {r["page_no"]: r for r in page_ledger.rows(doc_id)}
    assert ledger[2]["ocr_low_conf_boxes"] == 3


# -------------------------------------------------------------------- merge

def test_merge_keeps_the_text_layer_and_adds_only_the_scanned_body():
    native = [(60.0, 80.0, HEADER), (125.0, 790.0, STAMP), (1690.0, 80.0, FOOTER)]
    recognised = [
        (61.0, 82.0, "COMPANY CONFIDENTIAL -Uncontrolled when printed Doc No. 216400-C-0001 Rev 2"),
        (126.0, 792.0, "DCC RECEIVED 2O26-09-01 Code A - Approved"),   # 0 misread as O
        (200.0, 150.0, "7.6 Cathodic Protection Continuity"),
        (230.0, 150.0, "The resistance shall not exceed 0.01 ohm."),
        (1691.0, 82.0, "Page 15 of 26"),
    ]
    merged, added = ocr.merge_page_text(native, recognised)
    lines = merged.splitlines()
    assert added == 2
    assert lines == [HEADER, STAMP, "7.6 Cathodic Protection Continuity",
                     "The resistance shall not exceed 0.01 ohm.", FOOTER]


class _FakeEngine:
    def __init__(self, texts, boxes, scores=None):
        self._res = SimpleNamespace(
            txts=texts, scores=scores if scores is not None else [0.9] * len(texts),
            boxes=boxes)

    def __call__(self, image):
        return self._res


def _box(x, y, w=400, h=20):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_recognition_of_a_stamped_scan_is_merged_with_its_text_layer(tmp_path, monkeypatch):
    """The worker reads the page's own text-layer lines, in image pixels."""
    path = make_pdf(tmp_path / "s.pdf", add_stamped_scan)
    scale = settings.ocr_dpi / 72
    texts = [HEADER, "7.6 Cathodic Protection Continuity",
             "The resistance shall not exceed 0.01 ohm.", FOOTER]
    boxes = [_box(40 * scale, 22 * scale), _box(150, 200), _box(150, 230),
             _box(40 * scale, 807 * scale)]
    monkeypatch.setattr(ocr, "_build_engine", lambda: _FakeEngine(texts, boxes))
    (row,) = ocr.recognise_batch(path, "sha-merge", [1])
    pno, text, *_rest, err = row
    assert err is None
    lines = text.splitlines()
    assert lines.count(HEADER) == 1 and lines.count(FOOTER) == 1
    assert STAMP in lines
    assert lines.index(HEADER) < lines.index("7.6 Cathodic Protection Continuity") < lines.index(FOOTER)


def test_recognition_that_adds_nothing_leaves_the_text_layer_in_charge(tmp_path, monkeypatch):
    """No new line: stored text is empty, so the page is not claimed recognised."""
    path = make_pdf(tmp_path / "s.pdf", add_stamped_scan)
    monkeypatch.setattr(ocr, "_build_engine",
                        lambda: _FakeEngine([HEADER, FOOTER], [_box(80, 60), _box(80, 1690)]))
    (row,) = ocr.recognise_batch(path, "sha-nothing", [1])
    assert row[1] == ""
    assert row[4] == 2          # the boxes it did find are still recorded


def test_low_confidence_boxes_are_counted_not_just_averaged_away(tmp_path, monkeypatch):
    """A page-level mean/min hides ONE bad word among many good ones.

    Four boxes: three confident (0.95+), one at 0.10 - a wrong digit in a
    tag number, say. mean_conf still looks fine (0.71); this is the count
    those two numbers cannot give: exactly how many boxes were actually bad.
    """
    path = make_pdf(tmp_path / "s.pdf", add_stamped_scan)
    texts = [HEADER, "7.6 Cathodic Protection Continuity",
             "The resistance shall not exceed 0.01 ohm.", FOOTER]
    boxes = [_box(40, 22), _box(150, 200), _box(150, 230), _box(40, 807)]
    scores = [0.97, 0.95, 0.10, 0.99]
    monkeypatch.setattr(settings, "ocr_low_conf_threshold", 0.70)
    monkeypatch.setattr(ocr, "_build_engine", lambda: _FakeEngine(texts, boxes, scores))
    (row,) = ocr.recognise_batch(path, "sha-lowconf", [1])
    pno, text, mean_c, min_c, box_count, low_conf, *_rest = row
    assert low_conf == 1, "exactly one of the four boxes is below threshold"
    assert min_c == pytest.approx(0.10)
    assert mean_c > 0.70, "the average alone would look acceptable"


def test_no_boxes_below_threshold_counts_zero_not_none(tmp_path, monkeypatch):
    """Zero is a real, checked answer here - never confused with 'not measured'."""
    path = make_pdf(tmp_path / "s.pdf", add_stamped_scan)
    texts = [HEADER, "7.6 Cathodic Protection Continuity",
             "The resistance shall not exceed 0.01 ohm.", FOOTER]
    boxes = [_box(40, 22), _box(150, 200), _box(150, 230), _box(40, 807)]
    monkeypatch.setattr(ocr, "_build_engine",
                        lambda: _FakeEngine(texts, boxes, [0.95, 0.96, 0.97, 0.98]))
    (row,) = ocr.recognise_batch(path, "sha-clean", [1])
    assert row[5] == 0


# ----------------------------------------------------- one page fails, not all

class _InlineFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class _InlinePool:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *args, **kwargs):
        return _InlineFuture(fn(*args, **kwargs))


def _one_page_fails(stored_path, sha256, page_nos):
    return [
        (p, "", None, None, 0, 0, 0.2, 0, "", "RuntimeError: onnx session died")
        if p == 1 else
        (p, "Coating system no. 1 shall achieve a nominal dry film thickness of "
            "80 micrometres measured in accordance with the referenced standard.",
         0.95, 0.91, 6, 0, 0.8, 0, "", None)
        for p in page_nos
    ]


def test_one_page_failing_recognition_fails_the_page_not_the_document(tmp_path, monkeypatch):
    """F7. Before: status `failed`, embedded 0, READY hooks never ran."""
    from app.ingest import IngestionWorker

    def blank(doc):
        doc.new_page()
    doc_id = upload(make_pdf(tmp_path / "f.pdf", blank, blank, add_dense_text))
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(ocr, "recognise_batch", _one_page_fails)
    IngestionWorker().process(doc_id)

    conn = connect()
    row = conn.execute("SELECT status, error_message, embedded_count, chunk_count"
                       " FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["status"] == states.READY, row["error_message"]
    assert row["embedded_count"] == row["chunk_count"] > 0
    failed = conn.execute("SELECT text, error FROM page_ocr WHERE document_id = ?"
                          " AND page_no = 1", (doc_id,)).fetchone()
    assert failed is not None and failed["text"] == ""
    assert "onnx session died" in failed["error"]
    assert ocr.pending_pages(doc_id) == []
    # recorded as unread, with its reason, in both places a reader looks
    assert conn.execute("SELECT rule FROM exclusions WHERE document_id = ? AND"
                        " page_start = 1", (doc_id,)).fetchone()["rule"] == "ocr_failed"
    ledger = {r["page_no"]: r for r in page_ledger.rows(doc_id)}
    assert ledger[1]["ocr_status"] == "failed"
    assert "onnx session died" in ledger[1]["ocr_reason"]
    assert ledger[2]["ocr_status"] == "done"
    # and a deliberate retry makes it pending again
    assert ocr.retry_failed(doc_id) == 1
    assert ocr.pending_pages(doc_id) == [1]


def test_pages_with_text_counts_this_round_only(tmp_path, monkeypatch):
    """A cumulative count re-chunked after every round that added nothing."""
    def blank(doc):
        doc.new_page()
    doc_id = upload(make_pdf(tmp_path / "r.pdf", blank, blank))
    extract.extract_document(doc_id)
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)

    def reads_page_one_only(stored_path, sha256, page_nos):
        return [(p, "recognised words on page one" if p == 1 else "",
                 None, None, 1 if p == 1 else 0, 0, 0.1, 0, "", None) for p in page_nos]
    monkeypatch.setattr(ocr, "recognise_batch", reads_page_one_only)
    first = ocr.recognise_document(doc_id, max_pages=1)
    second = ocr.recognise_document(doc_id, max_pages=1)
    assert first["pages_with_text"] == 1
    assert second["pages_with_text"] == 0
    assert second["pages_failed"] == 0


# ------------------------------------------------ re-deciding stored documents

def _as_decided_by_the_old_rule(doc_id: str) -> None:
    """What the live DB holds: every page >= 100 chars unflagged, no reason."""
    conn = connect()
    with conn:
        conn.execute("UPDATE pages SET needs_ocr = CASE WHEN char_count < 100 THEN 1"
                     " ELSE 0 END, ocr_route = NULL, ocr_route_version = NULL"
                     " WHERE document_id = ?", (doc_id,))
        conn.execute("UPDATE documents SET status = ?, needs_ocr_pages = 0 WHERE id = ?",
                     (states.READY, doc_id))


def test_reroute_finds_the_stamped_scan_in_a_stored_document_and_requeues_it(tmp_path):
    doc_id = upload(make_pdf(tmp_path / "old.pdf", add_dense_text, add_stamped_scan))
    extract.extract_document(doc_id)
    _as_decided_by_the_old_rule(doc_id)

    estimate = extract.reroute_document(doc_id, apply=False)
    assert estimate["stale"] == 2 and estimate["newly_needs_ocr"] == 1
    assert estimate["requeued"] is True
    # a dry run writes nothing
    assert pages(doc_id)[2]["needs_ocr"] == 0
    assert pages(doc_id)[2]["ocr_route_version"] is None

    done = extract.reroute_document(doc_id)
    assert done["newly_needs_ocr"] == 1
    got = pages(doc_id)
    assert got[2]["needs_ocr"] == 1 and got[2]["ocr_route"].startswith("image_dominant")
    assert got[1]["ocr_route_version"] == ocr.OCR_ROUTE_VERSION
    row = connect().execute("SELECT status, needs_ocr_pages FROM documents WHERE id = ?",
                            (doc_id,)).fetchone()
    assert row["status"] == states.CHUNKING       # the worker picks it up
    assert row["needs_ocr_pages"] == 1
    assert ocr.pending_pages(doc_id) == [2]


def test_reroute_of_a_text_only_document_changes_no_state(tmp_path):
    """No forced re-ingest: a document whose decision does not change stays put."""
    doc_id = upload(make_pdf(tmp_path / "txt.pdf", add_dense_text, add_text_with_logo))
    extract.extract_document(doc_id)
    _as_decided_by_the_old_rule(doc_id)
    done = extract.reroute_document(doc_id)
    assert done["newly_needs_ocr"] == 0 and done["requeued"] is False
    assert connect().execute("SELECT status FROM documents WHERE id = ?",
                             (doc_id,)).fetchone()["status"] == states.READY
    # but the reason is now recorded, so the page is no longer stale
    assert {p["ocr_route_version"] for p in pages(doc_id).values()} == {ocr.OCR_ROUTE_VERSION}


# ---------------------------------------------------------------- migration

def test_an_older_database_gains_the_routing_and_failure_columns(tmp_path, monkeypatch):
    """Built OLD-shaped, then migrated - not built from the current schema."""
    conn = connect()
    for table, column in (("pages", "ocr_route"), ("pages", "ocr_route_version"),
                          ("page_ocr", "error"), ("page_ledger", "ocr_reason")):
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    conn.commit()
    assert "error" not in db.columns_of(conn, "page_ocr")
    db.reset_connection()
    db.init_db()
    conn = connect()
    assert {"ocr_route", "ocr_route_version"} <= db.columns_of(conn, "pages")
    assert "error" in db.columns_of(conn, "page_ocr")
    assert "ocr_reason" in db.columns_of(conn, "page_ledger")
