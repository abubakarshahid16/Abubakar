"""Order 274.6: the page viewer draws a value only where its reader recorded a box, and lists the rest."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pymupdf
import pytest

from app import db, review, submittal_review
from app.config import settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "board_page_boxes.py"
NOW = "2026-10-28T00:00:00Z"
#: A box well inside a 595 x 842 point page.
BOX = [100.0, 200.0, 220.0, 224.0]


@pytest.fixture(scope="module")
def boxes():
    spec = importlib.util.spec_from_file_location("board_page_boxes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdf(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(path))
    return path


def _fact(conn, fid, page, label, value, prov, method="geometry_reader"):
    conn.execute(
        "INSERT INTO submittal_facts (id,submittal_document_id,field_name,field_label,raw_value,"
        "field_value,page,extraction_method,bbox,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fid, "sub", label.lower(), label, value, value, page, method, prov, NOW, NOW),
    )


@pytest.fixture
def copy_db(tmp_path, monkeypatch):
    path = tmp_path / "copy.sqlite"
    pdf = _pdf(tmp_path / "sheet.pdf")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", path)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('sub','sheet.pdf','sha',1,?,'ready',2,?)",
            (str(pdf), NOW),
        )
        for rid, status in (("run1", "completed"), ("run2", "running")):
            conn.execute(
                "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                " VALUES (?,?,?,?,?)",
                (rid, "sub", status, NOW, NOW),
            )
        _fact(
            conn,
            "f1",
            1,
            "Set pressure",
            "10",
            json.dumps({"reader": "geometry_reader", "value_bbox": BOX}),
        )
        _fact(
            conn,
            "f2",
            1,
            "Flow",
            "24",
            json.dumps(
                {
                    "reader": "vision_reader",
                    "value_bbox": [300, 300, 380, 320],
                    "label_bbox": [200, 300, 290, 320],
                }
            ),
            "vision_reader",
        )
        _fact(
            conn, "f3", 1, "Tag", "PSV-1", None, "rule_reader"
        )  # no box: listed, not drawn
        _fact(
            conn,
            "f4",
            2,
            "Temp",
            "95",
            json.dumps(
                {"reader": "geometry_reader", "value_bbox": [9000, 9000, 9100, 9020]}
            ),
        )
        _fact(
            conn, "f5", 7, "Ghost", "1", json.dumps({"value_bbox": BOX})
        )  # page not in the file
        conn.execute(
            "UPDATE submittal_facts SET superseded_at = ? WHERE id = 'f4'", (NOW,)
        )
        _fact(
            conn,
            "f6",
            2,
            "Weight",
            "3",
            json.dumps(
                {"reader": "geometry_reader", "value_bbox": [9000, 9000, 9100, 9020]}
            ),
        )
    db.reset_connection()
    return path


def _data(folder: Path) -> dict:
    text = (folder / "boxes.js").read_text(encoding="utf-8")
    start = text.index("= ", text.index(".boxes")) + 2
    return json.loads(text[start : text.rindex(";")])


def _pixel(png: Path, x_pt: float, y_pt: float, scale: float):
    pix = pymupdf.Pixmap(str(png))
    return pix.pixel(int(x_pt * scale), int(y_pt * scale))


def test_a_value_is_drawn_where_its_reader_put_the_box_and_nowhere_else(
    boxes, copy_db, tmp_path
):
    out = tmp_path / "m"
    counts = boxes.export(copy_db, "run1", out)
    assert counts == {"values": 5, "drawn": 2, "not_drawn": 3, "pages_with_picture": 1}
    data = _data(out)
    by_id = {f["fact_id"]: f for p in data["pages"].values() for f in p}
    assert by_id["f1"]["drawn"] and by_id["f2"]["drawn"]
    assert by_id["f3"]["reason"] == "no box recorded"
    assert by_id["f5"]["reason"] == "page not in the file"
    assert by_id["f6"]["reason"] == "box off the page"
    assert "f4" not in by_id  # a superseded value is not on the board
    assert (out / "page-1.png").exists() and not (out / "page-2.png").exists()
    scale = data["pdf_scale"]
    top_edge = _pixel(
        out / "page-1.png", 160, 200.0, scale
    )  # on f1's top edge: its blue
    inside = _pixel(
        out / "page-1.png", 160, 212.0, scale
    )  # inside the box: the page's white
    assert top_edge[2] > top_edge[0] and inside == (255, 255, 255)


def test_the_colour_says_who_read_it(boxes, copy_db, tmp_path):
    out = tmp_path / "m"
    boxes.export(copy_db, "run1", out)
    scale = _data(out)["pdf_scale"]
    green = _pixel(
        out / "page-1.png", 340, 300.0, scale
    )  # f2's top edge, picture reader
    assert green[1] > green[0] and green[1] > green[2]


def test_an_unfinished_run_a_missing_pdf_and_an_existing_file_are_refused(
    boxes, copy_db, tmp_path
):
    out = tmp_path / "m"
    with pytest.raises(ValueError, match="when it has finished"):
        boxes.export(copy_db, "run2", out)
    with pytest.raises(FileNotFoundError):
        boxes.export(copy_db, "run1", out, pdf=tmp_path / "nope.pdf")
    assert not out.exists()
    boxes.export(copy_db, "run1", out)
    with pytest.raises(FileExistsError):
        boxes.export(copy_db, "run1", out)


def test_the_pictures_may_not_go_inside_the_repository(boxes, copy_db):
    with pytest.raises(ValueError, match="outside the repository"):
        boxes.export(copy_db, "run1", boxes.REPO / "docs" / "pictures")


def test_a_live_shaped_path_is_refused(boxes, tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    assert (
        boxes.main(["--db", str(live), "--run", "run1", "--out", str(tmp_path / "o")])
        == 2
    )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json",
        "[1, 2, 3, 4]",
        json.dumps({"value_bbox": [5, 5, 1, 1]}),
        json.dumps({"value_bbox": "x"}),
    ],
)
def test_a_box_that_is_not_four_ordered_numbers_is_no_box(boxes, raw):
    assert boxes._box(boxes._provenance(raw).get("value_bbox")) is None
