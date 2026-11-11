"""The OCR box import (order 12, N7): a quote on a scanned page is judged by the boxes it stands in. INVENTED pages, boxes and ids."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import db, live_guard, ocr_box_convert
from app import ocr_box_import as box
from app import rule_label_import as imp
from app import rule_label_ocr as O
from app.config import settings
from app.db import connect
from app.rule_label_schema import SwitchedOff
from tests import r2_security_support as support
from tests import rule_label_support as s
from tests.test_rule_label_import import _label_file, _rows

temp_storage = support.temp_storage
world = support.world
h = support.h

SHA = hashlib.sha256(b"revision one").hexdigest()
OTHER_SHA = hashlib.sha256(b"revision two").hexdigest()
PAGE_TEXT = f"{s.QUOTE_NUM}\n{s.QUOTE_TXT}\nA closing line of the invented page."
RECOGNISED = {1: {"page_source": "recognised", "page_min_conf": 0.1}}


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    s.switch(monkeypatch)
    s.patch_pages(monkeypatch, origin=RECOGNISED)


def _server(tmp_path, *, role="COMPANY_STANDARD", sha=SHA):
    path = s.make_db(tmp_path / "server.sqlite", with_book=True)
    conn = sqlite3.connect(str(path))
    conn.execute("ALTER TABLE documents ADD COLUMN sha256 TEXT")
    conn.execute("UPDATE documents SET sha256 = ? WHERE id = 'd1'", (sha,))
    conn.execute(
        "CREATE TABLE document_classification (document_id TEXT, document_role TEXT)"
    )
    conn.execute("INSERT INTO document_classification VALUES ('d1', ?)", (role,))
    conn.commit()
    return conn


def _page(score=0.95, *, page=1, sha=SHA, text=PAGE_TEXT, scores=None, **over):
    lines = text.split("\n")
    scores = scores or [score] * len(lines)
    p = {
        "document_id": "d1",
        "document_sha256": sha,
        "page": page,
        "engine": "invented-ocr-1.0",
        "model": "invented-model",
        "dpi": 150,
        "made_at": "2026-11-11T19:52:03",
        "boxes": [{"text": t, "score": sc} for t, sc in zip(lines, scores)],
    }
    return {**p, **over}


def _stored(conn):
    return conn.execute("SELECT COUNT(*) FROM ocr_box_page").fetchone()[0]


def test_a_page_is_stored_with_its_provenance_and_a_second_import_changes_nothing(
    tmp_path,
):
    conn = _server(tmp_path)
    got = box.import_pages(conn, [_page()], "f" * 64)
    assert got["stored"] == 1 and got["refused_total"] == 0
    row = conn.execute(
        "SELECT engine, extracted_at, model, dpi, document_sha256, file_sha256, text_agreement, imported_at, matches_page"
        " FROM ocr_box_page"
    ).fetchone()
    assert row[:7] == (
        "invented-ocr-1.0",
        "2026-11-11T19:52:03",
        "invented-model",
        150,
        SHA,
        "f" * 64,
        1.0,
    )
    assert row[7] and row[8] == 1
    assert conn.execute("SELECT COUNT(*) FROM ocr_box").fetchone()[0] == 3
    again = box.import_pages(conn, [_page()], "f" * 64)
    assert again["stored"] == 0 and again["unchanged"] == 1
    assert conn.execute("SELECT COUNT(*) FROM ocr_box").fetchone()[0] == 3


def test_boxes_made_from_another_revision_of_the_book_are_refused(tmp_path):
    conn = _server(tmp_path)
    got = box.import_pages(conn, [_page(sha=OTHER_SHA)], "f" * 64)
    assert got["refused"]["revision_mismatch"] == 1 and _stored(conn) == 0


def test_boxes_that_do_not_match_the_stored_page_text_are_refused_but_a_small_reread_difference_is_not(
    tmp_path,
):
    conn = _server(tmp_path)
    other = "Completely different invented words standing on some other page of some other thing entirely."
    assert (
        box.import_pages(conn, [_page(text=other)], "f" * 64)["refused"][
            "text_mismatch"
        ]
        == 1
    )
    one_word = PAGE_TEXT.replace(
        "closing", "clasing"
    )  # 1 of 29 words differs: 0.966 >= 0.95
    assert box.import_pages(conn, [_page(text=one_word)], "f" * 64)["stored"] == 1
    two_words = PAGE_TEXT.replace("closing", "clasing").replace(
        "invented", "inverted", 1
    )
    # 2 differing words of 29 is 0.931: refused (a fresh database, since page 1 is held)
    fresh = _server(_sub(tmp_path, "b"))
    assert (
        box.import_pages(fresh, [_page(text=two_words)], "f" * 64)["refused"][
            "text_mismatch"
        ]
        == 1
    )


def _sub(tmp_path, name):
    p = tmp_path / name
    p.mkdir()
    return p


@pytest.mark.parametrize("bad", [1.5, -0.1, None, float("nan"), True, "0.9"])
def test_a_score_outside_zero_to_one_or_not_a_number_refuses_the_page(tmp_path, bad):
    conn = _server(tmp_path)
    page = _page()
    page["boxes"][0]["score"] = bad
    got = box.import_pages(conn, [page], "f" * 64)
    assert got["refused"]["bad_score"] == 1 and _stored(conn) == 0


def test_only_a_rule_book_with_that_page_as_recognised_text_is_accepted(tmp_path):
    paper = _server(tmp_path, role="SUBMITTAL")
    assert (
        box.import_pages(paper, [_page()], "f" * 64)["refused"]["not_a_rule_book"] == 1
    )
    conn = _server(_sub(tmp_path, "c"))
    assert (
        box.import_pages(conn, [_page(document_id="nope")], "f" * 64)["refused"][
            "unknown_document"
        ]
        == 1
    )
    assert (
        box.import_pages(conn, [_page(page=9)], "f" * 64)["refused"]["no_such_page"]
        == 1
    )


def test_a_text_layer_page_takes_no_boxes(tmp_path, monkeypatch):
    s.patch_pages(
        monkeypatch, origin={1: {"page_source": "native", "page_min_conf": None}}
    )
    conn = _server(tmp_path)
    assert (
        box.import_pages(conn, [_page()], "f" * 64)["refused"]["not_recognised_page"]
        == 1
    )


def test_a_page_held_with_other_boxes_is_a_conflict_and_the_tables_are_append_only(
    tmp_path,
):
    conn = _server(tmp_path)
    box.import_pages(conn, [_page()], "f" * 64)
    got = box.import_pages(conn, [_page(score=0.5)], "f" * 64)
    assert got["refused"]["conflict"] == 1
    assert conn.execute("SELECT MIN(score) FROM ocr_box").fetchone()[0] == 0.95
    for sql in (
        "UPDATE ocr_box SET score = 0.1",
        "DELETE FROM ocr_box",
        "UPDATE ocr_box_page SET engine = 'x'",
        "DELETE FROM ocr_box_page",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)


def test_malformed_pages_are_counted_not_fatal(tmp_path):
    conn = _server(tmp_path)
    got = box.import_pages(
        conn,
        ["x", {}, _page(boxes=[]), _page(page="1"), _page(boxes_sha256="0" * 64)],
        "f" * 64,
    )
    assert got["refused"]["malformed"] == 5 and got["stored"] == 0


def test_the_switch_off_imports_nothing_and_makes_no_table(tmp_path, monkeypatch):
    conn = _server(tmp_path)
    s.switch(monkeypatch, False)
    with pytest.raises(SwitchedOff):
        box.import_pages(conn, [_page()], "f" * 64)
    assert "ocr_box" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master")
    }


# ------------------------------------------------------------------ the label import uses them, 0.70 unchanged


def test_a_label_refused_for_a_low_page_is_approved_after_the_boxes_and_a_quote_on_a_low_box_stays_refused(
    tmp_path, monkeypatch
):
    s.patch_pages(
        monkeypatch
    )  # the labeller read a text-layer page: its labels are approved
    rows = _rows(_label_file(tmp_path, monkeypatch))
    s.patch_pages(
        monkeypatch, origin=RECOGNISED
    )  # the server holds it as a scan with a weak page minimum
    conn = _server(_sub(tmp_path, "srv"))
    conn.row_factory = sqlite3.Row
    before = imp.import_labels(
        conn, rows
    )  # the page minimum is 0.1: both refused, as today
    assert before["refused"] == 2 and before["stored"] == 0
    # line 1 of the page is the first rule's quote, line 2 the second's. Line 2 sits on a 0.4 box.
    box.import_pages(conn, [_page(scores=[0.95, 0.4, 0.95])], "f" * 64)
    after = imp.import_labels(conn, rows)
    assert after["stored"] == 1 and after["refused"] == 1
    states = conn.execute("SELECT rule_ref, state FROM rule_label").fetchall()
    assert [tuple(r) for r in states] == [("r1", "ai_approved")]
    assert settings.ocr_low_conf_threshold == 0.70


def test_a_page_with_no_stored_boxes_keeps_the_strict_page_rule_even_when_other_pages_have_boxes(
    tmp_path,
):
    conn = _server(tmp_path)
    box.import_pages(conn, [_page()], "f" * 64)
    low = {"page_source": "recognised", "page_min_conf": 0.2}
    fine = {"page_source": "recognised", "page_min_conf": 0.99}
    assert (
        O.quote_is_low(conn, "d1", 2, s.QUOTE_NUM, fine) is False
    )  # page 2 has no boxes: the page minimum decides
    assert O.quote_is_low(conn, "d1", 2, s.QUOTE_NUM, low) is True
    assert (
        O.quote_is_low(conn, "d1", 1, s.QUOTE_NUM, low) is False
    )  # page 1 has boxes: the quote's own boxes decide


# ------------------------------------------------------------------ the lab converter


def test_the_converter_writes_rule_book_pages_only_with_the_lab_recogniser_and_the_import_takes_the_file(
    tmp_path,
):
    lab = sqlite3.connect(str(tmp_path / "lab.sqlite"))
    lab.executescript(
        """
        CREATE TABLE documents (id TEXT, sha256 TEXT);
        CREATE TABLE document_classification (document_id TEXT, document_role TEXT);
        CREATE TABLE ocr_box_page (document_id TEXT, page_no INTEGER, engine TEXT, extracted_at TEXT, matches_page INTEGER);
        CREATE TABLE ocr_box (document_id TEXT, page_no INTEGER, seq INTEGER, text TEXT, score REAL);
        CREATE TABLE page_ocr (document_id TEXT, page_no INTEGER, engine TEXT, model TEXT, dpi INTEGER);
        """
    )
    lab.execute("INSERT INTO documents VALUES ('d1', ?), ('paper', ?)", (SHA, SHA))
    lab.execute(
        "INSERT INTO document_classification VALUES ('d1','COMPANY_STANDARD'), ('paper','SUBMITTAL')"
    )
    for did in ("d1", "paper"):
        lab.execute(
            "INSERT INTO ocr_box_page VALUES (?, 1, 'app', '2026-11-11T19:52:03', 1)",
            (did,),
        )
        lab.execute(
            "INSERT INTO page_ocr VALUES (?, 1, 'invented-ocr-1.0', 'invented-model', 150)",
            (did,),
        )
        for i, (t, sc) in enumerate(zip(PAGE_TEXT.split("\n"), (0.9, 0.8, 0.7))):
            lab.execute("INSERT INTO ocr_box VALUES (?, 1, ?, ?, ?)", (did, i, t, sc))
    pages, counts = ocr_box_convert.convert(lab)
    assert counts == {"lab_pages": 2, "not_a_rule_book": 1, "written": 1}
    assert [p["document_id"] for p in pages] == ["d1"] and pages[0][
        "engine"
    ] == "invented-ocr-1.0"
    data = tmp_path / "boxes.json"
    ocr_box_convert.write(pages, data)
    got_pages, sha = box.read_file(data)
    assert sha == hashlib.sha256(data.read_bytes()).hexdigest()
    conn = _server(_sub(tmp_path, "s"))
    out = box.import_pages(conn, got_pages, sha)
    assert out["stored"] == 1 and out["refused_total"] == 0


# ------------------------------------------------------------------ the route and the command line


def test_the_route_is_admin_only_404_when_off_and_the_server_writes(
    world, tmp_path, monkeypatch
):
    conn = connect()
    with conn:
        conn.execute("UPDATE documents SET sha256 = ? WHERE id = 'doc_std'", (SHA,))
        conn.execute(
            "INSERT OR REPLACE INTO document_classification (document_id, suggested_by, document_role)"
            " VALUES ('doc_std', 'test', 'COMPANY_STANDARD')"
        )
    from app import compiled_rule_report

    monkeypatch.setattr(compiled_rule_report, "pages_of", lambda c, d: {1: PAGE_TEXT})
    monkeypatch.setattr(compiled_rule_report, "page_origin", lambda c, d: RECOGNISED)
    page = _page(document_id="doc_std")
    (tmp_path / "ocr-boxes.json").write_text(
        json.dumps({"format": box.EXPORT_FORMAT, "pages": [page]})
    )
    url, body = "/api/admin/ocr-boxes/import", {"path": "ocr-boxes.json"}
    s.switch(monkeypatch, False)
    off = world.post(url, json=body, headers=h("u_admin"))
    assert off.status_code == 404 and "feature_off" in off.text
    s.switch(monkeypatch, True)
    assert world.post(url, json=body, headers=h("u_sub")).status_code == 404
    assert (
        world.post(url, json={"path": "../x.json"}, headers=h("u_admin")).status_code
        == 422
    )
    ok = world.post(url, json=body, headers=h("u_admin"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["stored"] == 1 and ok.json()["refused_total"] == 0
    assert world.post(url, json=body, headers=h("u_admin")).json()["unchanged"] == 1


_spec = importlib.util.spec_from_file_location(
    "import_ocr_boxes",
    Path(__file__).resolve().parents[2] / "scripts" / "import_ocr_boxes.py",
)
cli = importlib.util.module_from_spec(_spec)
sys.modules["import_ocr_boxes"] = cli
_spec.loader.exec_module(cli)


def test_the_command_line_refuses_with_the_switch_off_a_running_server_or_a_file_outside_the_data_dir(
    tmp_path, monkeypatch
):
    path = Path(_server(tmp_path).execute("PRAGMA database_list").fetchone()[2])
    data = tmp_path / "data"
    data.mkdir()
    (data / "b.json").write_text(
        json.dumps({"format": box.EXPORT_FORMAT, "pages": [_page()]})
    )
    monkeypatch.delenv(live_guard.SERVER_ENV, raising=False)
    monkeypatch.setattr(live_guard, "known_live_files", lambda: ())
    kw = {"db_path": str(path), "data_dir": str(data), "check_server": False}
    s.switch(monkeypatch, False)
    with pytest.raises(cli.Refused):
        cli.load("b.json", **kw)
    s.switch(monkeypatch, True)
    monkeypatch.setattr(cli.base, "server_answers", lambda *a, **k: True)
    with pytest.raises(cli.Refused, match="stop the server"):
        cli.load("b.json", db_path=str(path), data_dir=str(data))
    with pytest.raises(cli.Refused):
        cli.load("../b.json", **kw)
    monkeypatch.setattr(cli.base, "server_answers", lambda *a, **k: False)
    db.reset_connection()
    got = cli.load("b.json", **kw)
    assert got["boxes"]["stored"] == 1
    db.reset_connection()
    assert cli.load("b.json", **kw)["boxes"]["unchanged"] == 1
    assert (
        cli.main(
            [
                "--boxes",
                "b.json",
                "--db",
                str(path),
                "--data-dir",
                str(data),
                "--expect-stored",
                "7",
                "--port",
                "1",
            ]
        )
        == 3
    )
    db.reset_connection()
