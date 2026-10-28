"""Order 274.6: the before / after matches findings by the requirement they answer, never by position."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def diff():
    return _load("board_run_diff")


@pytest.fixture(scope="module")
def export():
    return _load("board_export_run")


def _f(fid, req_id, status, text, *, reason=None, clause="5.1", std="std1"):
    return {
        "id": fid,
        "requirement_id": req_id,
        "compliance_status": status,
        "reason_code": reason,
        "standard_document_id": std,
        "standard_clause": clause,
        "requirement": text,
        "requirement_source_text": text,
        "contractor_page": 1,
    }


def _save(export, folder: Path, run_id: str, findings: list[dict]) -> Path:
    folder.mkdir(parents=True)
    (folder / "run.js").write_text(
        export._script(run_id, "run", {"id": run_id}), encoding="utf-8"
    )
    (folder / "findings.js").write_text(
        export._script(run_id, "findings", findings), encoding="utf-8"
    )
    return folder


def _runs(export, tmp_path, before, after):
    return (
        _save(export, tmp_path / "b", "runB", before),
        _save(export, tmp_path / "a", "runA", after),
    )


def test_findings_are_matched_by_requirement_not_by_position(diff, export, tmp_path):
    before = [
        _f("b1", "r1", "MISSING_INFORMATION", "The set pressure shall be stated."),
        _f("b2", "r2", "COMPLIANT", "The tag shall be stated."),
    ]
    after = [
        _f("a1", "r2", "COMPLIANT", "The tag shall be stated."),
        _f("a2", "r1", "COMPLIANT", "The set pressure shall be stated."),
    ]
    b, a = _runs(export, tmp_path, before, after)
    result = diff.build(b, a)
    [change] = result["changes"]
    assert change["transition"] == "MISSING_INFORMATION -> COMPLIANT"
    assert (change["before"]["finding_id"], change["after"]["finding_id"]) == (
        "b1",
        "a2",
    )
    assert {n["label"]: n["value"] for n in result["numbers"]}["unchanged"] == 1


def test_a_requirement_whose_id_changed_is_matched_by_its_words(diff, export, tmp_path):
    before = [
        _f("b1", "old-1", "MISSING_INFORMATION", "The   set pressure SHALL be stated.")
    ]
    after = [_f("a1", "new-9", "COMPLIANT", "The set pressure shall be stated.")]
    result = diff.build(*_runs(export, tmp_path, before, after))
    assert [c["transition"] for c in result["changes"]] == [
        "MISSING_INFORMATION -> COMPLIANT"
    ]
    assert result["only_before"] == [] and result["only_after"] == []


def test_a_different_clause_or_text_is_not_matched(diff, export, tmp_path):
    before = [
        _f(
            "b1",
            "old-1",
            "COMPLIANT",
            "The set pressure shall be stated.",
            clause="5.1",
        )
    ]
    after = [
        _f(
            "a1",
            "new-1",
            "COMPLIANT",
            "The set pressure shall be stated.",
            clause="5.2",
        ),
        _f("a2", "new-2", "COMPLIANT", "Another sentence."),
    ]
    result = diff.build(*_runs(export, tmp_path, before, after))
    assert [f["finding_id"] for f in result["only_before"]] == ["b1"]
    assert sorted(f["finding_id"] for f in result["only_after"]) == ["a1", "a2"]
    assert result["changes"] == []


def test_two_findings_for_one_requirement_pair_in_id_order_once_each(
    diff, export, tmp_path
):
    before = [
        _f("b1", "r1", "COMPLIANT", "x"),
        _f("b2", "r1", "MISSING_INFORMATION", "x"),
    ]
    after = [_f("a1", "r1", "COMPLIANT", "x"), _f("a2", "r1", "COMPLIANT", "x")]
    result = diff.build(*_runs(export, tmp_path, before, after))
    [change] = result["changes"]
    assert (change["before"]["finding_id"], change["after"]["finding_id"]) == (
        "b2",
        "a2",
    )
    assert result["only_before"] == [] and result["only_after"] == []


def test_the_fix_behind_a_change_comes_only_from_the_planners_file(
    diff, export, tmp_path
):
    before = [
        _f("b1", "r1", "MISSING_INFORMATION", "one"),
        _f("b2", "r2", "NON_COMPLIANT", "two"),
        _f("b3", "r3", "MISSING_INFORMATION", "three"),
    ]
    after = [
        _f("a1", "r1", "COMPLIANT", "one"),
        _f("a2", "r2", "COMPLIANT", "two"),
        _f("a3", "r3", "COMPLIANT", "three"),
    ]
    fixes = {
        "by_requirement": {"a2": {"pr": "#1400", "line": "banner"}},
        "by_transition": {
            "MISSING_INFORMATION -> COMPLIANT": {"pr": "#1399", "line": "placeholder"}
        },
    }
    result = diff.build(*_runs(export, tmp_path, before, after), fixes)
    fix = {c["after"]["finding_id"]: c["fix"] for c in result["changes"]}
    assert fix["a2"]["pr"] == "#1400" and fix["a1"]["pr"] == "#1399" == fix["a3"]["pr"]
    none = diff.build(tmp_path / "b", tmp_path / "a")
    assert all(c["fix"] is None for c in none["changes"])


def test_every_number_names_the_file_and_place_it_came_from(diff, export, tmp_path):
    before = [_f("b1", "r1", "MISSING_INFORMATION", "one")]
    after = [_f("a1", "r1", "COMPLIANT", "one")]
    numbers = diff.build(*_runs(export, tmp_path, before, after))["numbers"]
    assert numbers and all(
        n["source_file"] == "diff.js" and n["source_path"] for n in numbers
    )
    assert any(
        n["label"] == "MISSING_INFORMATION -> COMPLIANT" and n["value"] == 1
        for n in numbers
    )


def test_a_diff_is_saved_once_and_never_inside_the_repository(diff, export, tmp_path):
    b, a = _runs(
        export,
        tmp_path,
        [_f("b1", "r1", "COMPLIANT", "one")],
        [_f("a1", "r1", "COMPLIANT", "one")],
    )
    out = tmp_path / "out"
    assert diff.export(b, a, out) == {"changed": 0, "only_before": 0, "only_after": 0}
    saved = (out / "diff.js").read_text()
    assert '"runB..runA"' in saved
    with pytest.raises(FileExistsError):
        diff.export(b, a, out)
    with pytest.raises(ValueError, match="outside the repository"):
        diff.export(b, a, diff.REPO / "docs" / "diffs")
    assert (out / "diff.js").read_text() == saved


def test_a_folder_without_a_saved_run_is_refused(diff, tmp_path):
    (tmp_path / "empty").mkdir()
    assert (
        diff.main(
            [
                "--before",
                str(tmp_path / "empty"),
                "--after",
                str(tmp_path / "empty"),
                "--out",
                str(tmp_path / "o"),
            ]
        )
        == 1
    )
