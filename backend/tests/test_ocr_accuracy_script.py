"""The OCR accuracy measure's pure parts: order-free recall, numbers kept
whole, a misread number counted, and nothing reported as 0 or 1 by default."""
from __future__ import annotations

import collections
import importlib.util
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ocr_accuracy", REPO / "scripts" / "ocr_accuracy.py")
m = importlib.util.module_from_spec(_spec)
sys.modules["ocr_accuracy"] = m
_spec.loader.exec_module(m)


def test_recall_is_order_free_and_counts_repeats():
    truth = m.words("pump casing pump")
    assert m.recall(truth, m.words("casing pump")) == 2 / 3
    assert m.recall(truth, m.words("pump pump casing")) == 1.0


def test_a_decimal_is_one_number_and_a_comma_is_a_different_one():
    assert m.numbers("12.5 barg, 3/4 in, 150") == collections.Counter({"12.5": 1, "3/4": 1, "150": 1})
    s = m.score_page("design 12.5 barg", "design 12,5 barg")
    assert s["number_recall"] == 0.0 and s["misread_numbers"] == 1


def test_nothing_to_recall_is_none_not_zero_or_one():
    assert m.recall(collections.Counter(), m.words("anything")) is None
    assert m.score_page("no digits here", "no digits here")["number_recall"] is None


def test_the_summary_carries_its_denominators():
    pages = [m.score_page("a 1 2", "a 1 2"), m.score_page("b 3 4", "b 3 9")]
    s = m.summarise(pages)
    assert (s["pages"], s["true_numbers"], s["misread_numbers"]) == (2, 4, 1)
    assert s["misread_per_100_true"] == 25.0
    assert s["number_recall_median"] == 0.75


def test_the_sample_takes_only_native_text_pages_and_caps_each_document(tmp_path):
    db = sqlite3.connect(tmp_path / "x.sqlite")
    db.execute("create table documents(id,stored_path,status)")
    db.execute("create table pages(document_id,page_no,text,char_count,needs_ocr)")
    db.execute("insert into documents values('d1','a.pdf','ready')")
    db.execute("insert into documents values('d2','b.pdf','ready')")
    for p in range(1, 6):
        db.execute("insert into pages values('d1',?,?,300,0)", (p, "x" * 300))
    db.execute("insert into pages values('d2',1,'y',300,1)")      # needs OCR: no truth
    db.execute("insert into pages values('d2',2,'y',50,0)")       # too short
    picked = m.sample_pages(db, n=10, per_doc=2, seed=1)
    assert len(picked) == 2 and {p[0] for p in picked} == {"d1"}


def test_a_moved_pdf_is_found_through_the_path_map():
    assert m._map_path(r"D:\project\Rag_chatbot\backend\data\u\a.pdf",
                       [(r"D:\project\Rag_chatbot", "/mnt/R")]) == "/mnt/R/backend/data/u/a.pdf"


def test_the_scan_estimate_changes_the_image():
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
    out = m.degrade(buf.getvalue(), seed=3)
    assert out != buf.getvalue() and Image.open(io.BytesIO(out)).format == "JPEG"
