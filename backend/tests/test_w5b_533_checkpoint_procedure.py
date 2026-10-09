"""#533 (W5b-09): the checkpoint reviews one invented procedure end to end.

`scripts/checkpoint_procedure.py` uploads the invented HAZOP procedure in
`eval/checkpoint/procedure.json`, extracts, chunks and reviews it against its
playbook in a temporary data directory, and records per element the expected
state, the review's state and pass/fail, with the sample's boundary.

Mutations: M5901-M5907 (scripts/mutations/w5b_533_checkpoint_procedure.py).
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from app import db
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("checkpoint_procedure",
                                               REPO / "scripts" / "checkpoint_procedure.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


@pytest.fixture(autouse=True)
def restore_settings(tmp_path, monkeypatch):
    """run_checkpoint points the settings at its work dir; put them back."""
    for name in ("data_dir", "upload_dir", "db_path", "auth_mode"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(settings, "data_dir", tmp_path / "unused")
    monkeypatch.setattr(settings, "db_path", tmp_path / "unused" / "x.sqlite")
    yield
    db.reset_connection()


def _review(states: dict, read: bool = True) -> dict:
    return {"document": {"read_in_full": read, "not_read_reason": None if read else "status: chunking"},
            "elements": [{"id": k, "state": v} for k, v in states.items()]}


# ------------------------------------------------------------------ end to end


def test_the_checkpoint_reviews_the_procedure_and_records_every_element(tmp_path):
    """THE MUTATION TARGET: the procedure's review results are recorded."""
    result = cp.run_checkpoint(tmp_path / "work")
    key = cp.load_key()
    assert result["status"] == "pass", result["elements"]
    assert result["total"] == len(key["expected"]) == 11
    assert result["passed"] == 11
    got = {r["id"]: r["got"] for r in result["elements"]}
    # The planted gaps are found, not papered over.
    assert got["H07"] == "missing" and got["H11"] == "missing"
    assert got["H02"] == "unclear"
    assert result["counts"]["total"] == 11
    assert "invented sample, not the client's documents" in result["boundary"]
    assert "DRAFT" in result["boundary"]
    assert "1 invented procedure" in result["boundary"]


def test_the_checkpoint_never_writes_outside_its_work_dir(tmp_path):
    work = tmp_path / "work"
    cp.run_checkpoint(work)
    assert Path(settings.db_path).parent == work
    assert (work / "checkpoint.sqlite").exists()


def test_the_main_command_records_the_result_and_exits_zero_on_a_pass(tmp_path, capsys):
    out = tmp_path / "result.json"
    assert cp.main(["--out", str(out)]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["status"] == "pass" and saved["passed"] == 11
    printed = capsys.readouterr().out
    assert "11 of 11" in printed
    # Counts and ids only: the invented text is never printed.
    assert "study leader chairs" not in printed


# ------------------------------------------------------------------ scoring


def test_a_review_that_calls_everything_present_fails_the_checkpoint():
    key = cp.load_key()
    result = cp.score(_review({k: "present" for k in key["expected"]}), key["expected"])
    assert result["status"] == "fail"
    assert result["passed"] == 8
    assert {r["id"] for r in result["elements"] if not r["pass"]} == {"H02", "H07", "H11"}


def test_an_element_the_review_did_not_report_is_not_a_pass():
    result = cp.score(_review({"H01": "present"}), {"H01": "present", "H02": "missing"})
    row = next(r for r in result["elements"] if r["id"] == "H02")
    assert row["got"] is None and row["pass"] is False
    assert result["status"] == "fail"


def test_a_document_not_read_in_full_is_incomplete_never_a_pass():
    result = cp.score(_review({"H01": "present"}, read=False), {"H01": "present"})
    assert result["status"] == "incomplete"
    assert result["passed"] == 0
    assert result["not_read_reason"] == "status: chunking"


# ------------------------------------------------------------------ named failures


def test_a_missing_key_is_a_named_error_and_exit_code_2(tmp_path, monkeypatch, capsys):
    with pytest.raises(cp.CheckpointError, match="missing"):
        cp.load_key(tmp_path / "nope.json")
    monkeypatch.setattr(cp, "KEY_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(cp.load_key, "__defaults__", (tmp_path / "nope.json",))
    assert cp.main([]) == 2
    assert "checkpoint not run" in capsys.readouterr().err


@pytest.mark.parametrize("change, message", [
    (lambda k: k.update(format="other/1"), "format"),
    (lambda k: k.update(expected={}), "expected"),
    (lambda k: k.update(sections=[]), "sections"),
])
def test_a_malformed_key_is_refused_by_name(tmp_path, change, message):
    key = copy.deepcopy(json.loads(cp.KEY_PATH.read_text(encoding="utf-8")))
    change(key)
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key), encoding="utf-8")
    with pytest.raises(cp.CheckpointError, match=message):
        cp.load_key(path)


def test_an_unknown_playbook_is_a_named_error(tmp_path):
    key = cp.load_key()
    key["playbook"] = "no_such_playbook"
    with pytest.raises(cp.CheckpointError, match="no_such_playbook"):
        cp.run_checkpoint(tmp_path / "work", key)
