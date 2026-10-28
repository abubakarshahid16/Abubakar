"""Order 274.6: the board's per-run export is one saved record, with the file behind every number."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app import db, review, submittal_review
from app.config import settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "board_export_run.py"
NOW = "2026-10-28T00:00:00Z"


@pytest.fixture(scope="module")
def board():
    spec = importlib.util.spec_from_file_location("board_export_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_db(tmp_path, monkeypatch, *, run_settings: bool):
    path = tmp_path / "copy.sqlite"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", path)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    review.ensure_schema()
    with db.connect() as conn:
        if (
            run_settings
        ):  # the column order 273.4 (#1411) adds; an older database has none
            conn.execute("ALTER TABLE review_runs ADD COLUMN run_settings TEXT")
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('sub','sheet.pdf','sha',1,'/x','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,model_name,config_version,"
            "outcome_json,started_at,completed_at,created_at,updated_at)"
            " VALUES ('run1','sub','completed','m1','cfg1',?,?,?,?,?)",
            (
                json.dumps(
                    {
                        "recommended_code": "B",
                        "reason": "r",
                        "requirement_split": {
                            "checked": 3,
                            "applies_not_checked": 7,
                            "note": "x",
                        },
                    }
                ),
                NOW,
                NOW,
                NOW,
                NOW,
            ),
        )
        if run_settings:
            conn.execute(
                "UPDATE review_runs SET run_settings = ? WHERE id = 'run1'",
                (json.dumps({"settings": {"geometry_reader_enabled": True}}),),
            )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES ('run2','sub','running',?,?)",
            (NOW, NOW),
        )
        for i, status in enumerate(("COMPLIANT", "COMPLIANT", "MISSING_INFORMATION")):
            conn.execute(
                "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,"
                "required_action,created_at,updated_at,review_run_id,compliance_status,contractor_page)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"f{i}",
                    "sub",
                    "c",
                    "s",
                    f"req {i}",
                    "fnd",
                    "act",
                    NOW,
                    NOW,
                    "run1",
                    status,
                    i + 1,
                ),
            )
    db.reset_connection()
    return path


@pytest.fixture
def copy_db(tmp_path, monkeypatch):
    return _make_db(tmp_path, monkeypatch, run_settings=True)


def _read(folder: Path, name: str) -> dict:
    text = (folder / name).read_text(encoding="utf-8")
    start = text.index("= ", text.index('.runs["run1"].')) + 2
    return json.loads(text[start : text.rindex(";")])


def test_a_finished_run_is_saved_as_four_files(board, copy_db, tmp_path):
    out = tmp_path / "mirror" / "run1"
    counts = board.export(copy_db, "run1", out)
    assert sorted(counts) == sorted(board.FILES)
    assert counts["findings.js"] == 3
    run = _read(out, "run.js")
    assert (run["status"], run["model_name"], run["config_version"]) == (
        "completed",
        "m1",
        "cfg1",
    )
    assert run["run_settings"]["settings"]["geometry_reader_enabled"] is True
    findings = _read(out, "findings.js")
    assert [f["id"] for f in findings] == ["f0", "f1", "f2"] and findings[2][
        "contractor_page"
    ] == 3
    xray = _read(out, "xray.js")
    assert {"pairing", "comparison", "coverage"} <= {s["id"] for s in xray}
    assert {s["id"] for s in _read(out, "decisions.js")} <= set(board.DECISION_SECTIONS)


def test_every_number_names_the_file_and_place_it_came_from(board, copy_db, tmp_path):
    out = tmp_path / "m"
    board.export(copy_db, "run1", out)
    numbers = _read(out, "run.js")["numbers"]
    assert numbers and all(n["source_file"] and n["source_path"] for n in numbers)
    by_label = {n["label"]: n for n in numbers}
    assert by_label["findings"]["value"] == 3
    assert by_label["findings: COMPLIANT"]["value"] == 2
    assert by_label["checked"]["value"] == 3 and by_label["checked"]["source_path"] == (
        "outcome.requirement_split.checked"
    )
    assert "note" not in by_label  # a text entry of the split is not a number


def test_a_finished_run_is_never_overwritten(board, copy_db, tmp_path):
    out = tmp_path / "m"
    board.export(copy_db, "run1", out)
    before = (out / "run.js").read_text()
    with pytest.raises(FileExistsError):
        board.export(copy_db, "run1", out)
    assert (out / "run.js").read_text() == before


def test_an_unfinished_run_and_an_unknown_run_are_refused_and_write_nothing(
    board, copy_db, tmp_path
):
    out = tmp_path / "m"
    with pytest.raises(ValueError, match="when it has finished"):
        board.export(copy_db, "run2", out)
    with pytest.raises(LookupError):
        board.export(copy_db, "nope", out)
    assert not out.exists()


def test_the_files_may_not_go_inside_the_repository(board, copy_db):
    with pytest.raises(ValueError, match="outside the repository"):
        board.export(copy_db, "run1", board.REPO / "docs" / "board")


def test_a_live_shaped_path_is_refused(board, tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    assert (
        board.main(["--db", str(live), "--run", "run1", "--out", str(tmp_path / "o")])
        == 2
    )


def test_an_older_database_without_the_settings_column_shows_none_never_invented(
    board, tmp_path, monkeypatch
):
    path = _make_db(tmp_path, monkeypatch, run_settings=False)
    out = tmp_path / "old"
    board.export(path, "run1", out)
    run = _read(out, "run.js")
    assert run["run_settings"] is None and run["model_name"] == "m1"
