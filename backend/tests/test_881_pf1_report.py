"""PF1 (#881): the per-type report. Invented data only; counts in, counts out.

The set is built by the real builder from a tiny invented spec, the findings
are written by hand from the key's own items, so each number is known.
"""

from __future__ import annotations

import json

import pytest
from tools import pf1_report as rep
from tools import pf1_set

from tests.test_881_pf1_set import _doc, _spec, _with_clause_5_1
from tests.test_w8_676_review_score import live_like_db  # noqa: F401 - a fixture


def _set(tmp_path, *docs):
    docs = docs or (_with_clause_5_1(_doc()),)
    index = pf1_set.build(_spec(*docs), tmp_path / "set")
    keys = {
        e["id"]: json.loads((tmp_path / "set" / e["key"]).read_text(encoding="utf-8"))
        for e in index["documents"]
    }
    return index, keys


def _finding(item, status):
    return {
        "standard": item["standard"],
        "clause": item["clause"],
        "field": item.get("field") or "",
        "submittal_page": item.get("submittal_page"),
        "compliance_status": status,
        "requirement_text": item.get("field") or "",
        "citation_valid": True,
    }


def _findings(key, **by_id):
    items = {it["id"]: it for it in key["items"]}
    return {
        "format": "review-findings/1",
        "model": "invented-model",
        "findings": [_finding(items[i], s) for i, s in by_id.items()],
    }


def _run(mode="main", status="completed", minutes=5.0, read=2, total=2):
    return {
        "format": "pf1-run/1",
        "mode": mode,
        "status": status,
        "minutes": minutes,
        "pages_read": read,
        "pages_total": total,
    }


def _report(tmp_path, findings, runs, *docs):
    index, keys = _set(tmp_path, *docs)
    return rep.build_report(index, keys, findings, runs)


def test_one_sheet_scored_by_the_numbers_of_its_key(tmp_path):
    index, keys = _set(tmp_path)
    key = keys["pf1-t-pump"]
    findings = {
        "pf1-t-pump": _findings(
            key,
            D1="NON_COMPLIANT",
            D2="MISSING_INFORMATION",
            M1="COMPLIANT",
            T1="COMPLIANT",
            N1="NOT_APPLICABLE",
        )
    }
    out = rep.build_report(index, keys, findings, {"pf1-t-pump": _run()})
    (sheet,) = out["sheets"]
    assert sheet["defects"] == 2 and sheet["defects_caught"] == 2
    assert sheet["defects_caught_plain_fail"] == 1
    assert sheet["false_meets"] == 0
    assert sheet["correct_items"] == 2 and sheet["correct_confirmed_meets"] == 2
    assert sheet["correct_wrongly_flagged"] == 0 and sheet["correct_undecided"] == 0
    assert sheet["keyed_items"] == 5 and sheet["keyed_decided"] == 4  # D2 asks a human
    assert sheet["finished"] is True and sheet["minutes"] == 5.0
    assert out["blocked"] == []


def test_a_false_meets_on_a_planted_defect_blocks_the_report(tmp_path):
    index, keys = _set(tmp_path)
    findings = {
        "pf1-t-pump": _findings(keys["pf1-t-pump"], D1="COMPLIANT", D2="NON_COMPLIANT")
    }
    out = rep.build_report(index, keys, findings, {"pf1-t-pump": _run()})
    assert out["sheets"][0]["false_meets"] == 1
    assert out["sheets"][0]["false_meets_ids"] == ["D1"]
    assert out["blocked"] and "1 false Meets" in out["blocked"][0]
    assert "BLOCKED" in rep.render(out)


def test_a_correct_item_wrongly_flagged_or_left_undecided_is_counted_apart(tmp_path):
    index, keys = _set(tmp_path)
    findings = {
        "pf1-t-pump": _findings(
            keys["pf1-t-pump"], D1="NON_COMPLIANT", M1="NEEDS_ENGINEER_REVIEW"
        )
    }
    (sheet,) = rep.build_report(index, keys, findings, {"pf1-t-pump": _run()})["sheets"]
    assert sheet["correct_wrongly_flagged"] == 1  # M1
    assert sheet["correct_undecided"] == 1  # T1: no finding at all
    assert sheet["correct_confirmed_meets"] == 0


def test_a_sheet_with_no_run_is_listed_and_never_scored_as_zeros(tmp_path):
    out = _report(tmp_path, {}, {})
    (sheet,) = out["sheets"]
    assert sheet["run"] is False and "defects" not in sheet
    assert (
        out["totals"]["all"]["sheets_run"] == 0 and out["totals"]["all"]["defects"] == 0
    )
    assert "no run" in rep.render(out)


def test_an_unfinished_run_is_marked_beside_its_numbers(tmp_path):
    index, keys = _set(tmp_path)
    findings = {"pf1-t-pump": _findings(keys["pf1-t-pump"], D1="NON_COMPLIANT")}
    for run in (_run(status="failed"), _run(read=1)):
        out = rep.build_report(index, keys, findings, {"pf1-t-pump": run})
        assert out["sheets"][0]["finished"] is False
        assert "INCOMPLETE" in rep.render(out)
        assert out["totals"]["all"]["incomplete_runs"] == 1


def test_held_out_sheets_are_in_the_totals_and_nowhere_else(tmp_path):
    held = _with_clause_5_1(_doc("pf1-h-pump", held_out=True))
    open_ = _with_clause_5_1(_doc("pf1-o-pump"))
    index, keys = _set(tmp_path, open_, held)
    findings = {
        "pf1-o-pump": _findings(keys["pf1-o-pump"], D1="NON_COMPLIANT"),
        "pf1-h-pump": _findings(
            keys["pf1-h-pump"], D1="NON_COMPLIANT", D2="NON_COMPLIANT"
        ),
    }
    runs = {"pf1-o-pump": _run(), "pf1-h-pump": _run()}
    out = rep.build_report(index, keys, findings, runs)
    assert [s["id"] for s in out["sheets"]] == ["pf1-o-pump"]
    text = rep.render(out) + json.dumps(out)
    assert "pf1-h-pump" not in text
    assert out["totals"]["held_out"]["defects_caught"] == 2
    assert out["totals"]["tuning"]["defects_caught"] == 1
    assert out["totals"]["all"]["defects_caught"] == 3


def test_a_false_meets_on_a_held_out_sheet_blocks_without_naming_the_item(tmp_path):
    held = _with_clause_5_1(_doc("pf1-h-pump", held_out=True))
    index, keys = _set(tmp_path, held)
    findings = {"pf1-h-pump": _findings(keys["pf1-h-pump"], D1="COMPLIANT")}
    out = rep.build_report(index, keys, findings, {"pf1-h-pump": _run()})
    assert out["blocked"] and out["totals"]["held_out"]["false_meets"] == 1
    assert "D1" not in rep.render(out)


def test_two_modes_in_one_report_are_refused(tmp_path):
    a, b = _with_clause_5_1(_doc("pf1-a")), _with_clause_5_1(_doc("pf1-b"))
    index, keys = _set(tmp_path, a, b)
    findings = {i: _findings(keys[i], D1="NON_COMPLIANT") for i in keys}
    runs = {"pf1-a": _run("main"), "pf1-b": _run("checklists_off")}
    with pytest.raises(rep.ReportError, match="mix modes"):
        rep.build_report(index, keys, findings, runs)


def test_the_mode_is_named_and_the_diagnostic_is_not_called_the_main_score(tmp_path):
    index, keys = _set(tmp_path)
    findings = {"pf1-t-pump": _findings(keys["pf1-t-pump"], D1="NON_COMPLIANT")}
    main = rep.render(
        rep.build_report(index, keys, findings, {"pf1-t-pump": _run("main")})
    )
    diag = rep.render(
        rep.build_report(index, keys, findings, {"pf1-t-pump": _run("checklists_off")})
    )
    assert "MAIN score" in main and "MAIN score" not in diag
    assert "DIAGNOSTIC (checklists off)" in diag


def test_the_report_holds_counts_never_the_text_of_a_finding(tmp_path):
    index, keys = _set(tmp_path)
    findings = {"pf1-t-pump": _findings(keys["pf1-t-pump"], D1="NON_COMPLIANT")}
    findings["pf1-t-pump"]["findings"][0]["requirement_text"] = (
        "SECRET REQUIREMENT WORDS"
    )
    out = rep.build_report(index, keys, findings, {"pf1-t-pump": _run()})
    assert "SECRET" not in json.dumps(out) and "SECRET" not in rep.render(out)


def test_a_missing_key_stops_the_report(tmp_path):
    index, _keys = _set(tmp_path)
    with pytest.raises(rep.ReportError, match="no answer key"):
        rep.build_report(index, {}, {}, {})


def test_a_run_record_must_state_its_mode():
    bad = {"format": "pf1-run/1", "status": "completed"}
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "x.run.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(rep.ReportError, match="mode"):
            rep.load_run_record(p)


def test_load_set_reads_the_folders_and_treats_a_missing_findings_file_as_no_run(
    tmp_path,
):
    _index, keys = _set(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    i, k, f, r = rep.load_set(tmp_path / "set", runs_dir)
    assert f == {} and r == {} and set(k) == {"pf1-t-pump"}
    (runs_dir / "pf1-t-pump.findings.json").write_text(
        json.dumps(_findings(keys["pf1-t-pump"], D1="NON_COMPLIANT")), encoding="utf-8"
    )
    (runs_dir / "pf1-t-pump.run.json").write_text(json.dumps(_run()), encoding="utf-8")
    i, k, f, r = rep.load_set(tmp_path / "set", runs_dir)
    out = rep.build_report(i, k, f, r)
    assert out["sheets"][0]["defects_caught"] == 1


def _script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "pf1_report.py"
    spec = importlib.util.spec_from_file_location("pf1_report_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_run(tmp_path, keys, status):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    (runs_dir / "pf1-t-pump.findings.json").write_text(
        json.dumps(_findings(keys["pf1-t-pump"], D1=status, D2="NON_COMPLIANT")),
        encoding="utf-8",
    )
    (runs_dir / "pf1-t-pump.run.json").write_text(json.dumps(_run()), encoding="utf-8")
    return runs_dir


def test_the_command_prints_the_table_and_check_fails_only_on_a_false_meets(
    tmp_path, capsys
):
    _index, keys = _set(tmp_path)
    script = _script()
    runs_dir = _write_run(tmp_path, keys, "NON_COMPLIANT")
    args = ["--set", str(tmp_path / "set"), "--runs", str(runs_dir), "--check"]
    assert script.main(args) == 0
    out = capsys.readouterr().out
    assert "PF1 report" in out and "Hard rule holds" in out
    runs_dir = _write_run(tmp_path, keys, "COMPLIANT")
    assert script.main([*args, "--json", str(tmp_path / "r.json")]) == 1
    assert "BLOCKED" in capsys.readouterr().out
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["blocked"]
    assert (
        script.main(args[:-1]) == 0
    )  # without --check a false Meets is reported, not an exit code


def test_the_command_refuses_a_folder_that_is_not_a_set(tmp_path, capsys):
    assert _script().main(["--set", str(tmp_path), "--runs", str(tmp_path)]) == 1
    assert "REFUSED" in capsys.readouterr().out


def test_the_four_stage_e_numbers_and_the_ai_use_are_reported(tmp_path):
    index, keys = _set(tmp_path)
    findings = {
        "pf1-t-pump": _findings(
            keys["pf1-t-pump"],
            D1="NON_COMPLIANT",
            D2="NON_COMPLIANT",
            M1="COMPLIANT",
            T1="COMPLIANT",
        )
    }
    run = {**_run(), "ai": {"reader": "ollama", "claude": False}}
    out = rep.build_report(index, keys, findings, {"pf1-t-pump": run})
    total = out["totals"]["all"]
    assert total["recall"] == 1.0 and total["precision"] == 1.0
    assert total["citation_validity"] == 1.0 and total["false_meets"] == 0
    text = rep.render(out)
    assert "recall 100%, precision 100%, false Meets 0, citations valid 100%" in text
    assert '"claude": false' in text and "AI use: " in text


def test_ai_use_not_recorded_is_said_not_assumed_empty(tmp_path):
    index, keys = _set(tmp_path)
    findings = {"pf1-t-pump": _findings(keys["pf1-t-pump"], D1="NON_COMPLIANT")}
    out = rep.build_report(index, keys, findings, {"pf1-t-pump": _run()})
    assert "AI use: not recorded" in rep.render(out)


def test_against_the_stage_e_bar_each_number_meets_is_below_or_cannot_tell(tmp_path):
    index, keys = _set(tmp_path)
    low = {
        "pf1-t-pump": _findings(keys["pf1-t-pump"], D1="NON_COMPLIANT")
    }  # 1 of 2 defects
    out = rep.build_report(
        index, keys, low, {"pf1-t-pump": _run()}, bar=rep.STAGE_E_BAR
    )
    status = out["bar"]["status"]
    assert status["recall"] == "BELOW" and status["false_meets"] == "meets"
    assert "Against the Stage E pass mark" in rep.render(out)
    none = rep.build_report(index, keys, {}, {}, bar=rep.STAGE_E_BAR)
    assert set(none["bar"]["status"].values()) == {
        "cannot tell",
        "meets",
    }  # nothing run: no number, no pass
    assert none["bar"]["status"]["recall"] == "cannot tell"
    assert rep.STAGE_E_BAR == {
        "recall": 0.85,
        "precision": 0.80,
        "false_meets": 0,
        "citations_valid": 1.0,
    }


def test_the_command_shows_the_stage_e_bar_on_request(tmp_path, capsys):
    _index, keys = _set(tmp_path)
    runs_dir = _write_run(tmp_path, keys, "NON_COMPLIANT")
    args = ["--set", str(tmp_path / "set"), "--runs", str(runs_dir)]
    assert "Against the Stage E" not in (
        _script().main(args) or capsys.readouterr().out
    )
    _script().main([*args, "--bar", "stage-e"])
    assert "Against the Stage E pass mark" in capsys.readouterr().out


# ------------------------------------------------------ pf1_collect: runner -> report


def test_outcome_facts_counts_pages_not_left_unread_and_names_the_ai_use():
    outcome = {
        "page_coverage": {
            "pages_total": 11,
            "pages_not_read_into_fields": [3],
            "pages_ai_not_read": [3, 5],
        },
        "requirement_split": {"reader": {"engine": "ollama", "model": "qwen3.5:4b"}},
        "ai_matcher": {"engine": "ollama", "model": "ollama:qwen3.5:4b"},
    }
    facts = rep.outcome_facts(outcome)
    assert (
        facts["pages_total"] == 11 and facts["pages_read"] == 9
    )  # pages 3 and 5 unread
    assert facts["ai"]["reader"] == "ollama" and facts["ai"]["claude"] is False
    assert rep.outcome_facts({})["pages_read"] is None and rep.outcome_facts(None)[
        "ai"
    ] == {"claude": False}
    assert (
        rep.outcome_facts({"requirement_split": {"reader": {"engine": "claude"}}})[
            "ai"
        ]["claude"]
        is True
    )


def test_a_run_record_is_completed_with_the_declared_mode_and_keeps_the_runners_fields():
    record = {
        "format": "pf1-run/1",
        "id": "x",
        "review_run_id": "r1",
        "status": "completed",
        "minutes": 4.0,
    }
    done = rep.complete_record(record, {"page_coverage": {"pages_total": 2}}, "main")
    assert (
        done["mode"] == "main"
        and done["pages_total"] == 2
        and done["review_run_id"] == "r1"
    )
    with pytest.raises(rep.ReportError, match="mode"):
        rep.complete_record(record, {}, "guess")


def test_collect_writes_the_findings_and_completes_the_record_from_a_read_only_copy(
    tmp_path,
    live_like_db,  # noqa: F811
    capsys,
):
    import importlib.util
    import sqlite3
    from pathlib import Path

    with sqlite3.connect(live_like_db) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS review_runs (id TEXT PRIMARY KEY, outcome_json TEXT)"
        )
        conn.execute(
            "INSERT INTO review_runs (id, outcome_json) VALUES ('run1', ?)",
            (
                json.dumps(
                    {
                        "page_coverage": {
                            "pages_total": 2,
                            "pages_not_read_into_fields": [],
                        },
                        "requirement_split": {
                            "reader": {"engine": "ollama", "model": "m"}
                        },
                    }
                ),
            ),
        )
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "pf1-a.run.json").write_text(
        json.dumps(
            {
                "format": "pf1-run/1",
                "id": "pf1-a",
                "review_run_id": "run1",
                "status": "completed",
                "minutes": 3.5,
            }
        ),
        encoding="utf-8",
    )
    (runs_dir / "pf1-b.run.json").write_text(
        json.dumps(
            {
                "format": "pf1-run/1",
                "id": "pf1-b",
                "review_run_id": None,
                "status": "error",
                "minutes": 0.1,
            }
        ),
        encoding="utf-8",
    )
    path = Path(__file__).resolve().parents[2] / "scripts" / "pf1_collect.py"
    spec = importlib.util.spec_from_file_location("pf1_collect_script", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    before = live_like_db.read_bytes()
    assert (
        script.main(
            [
                "--db",
                str(live_like_db),
                "--runs",
                str(runs_dir),
                "--mode",
                "main",
                "--model",
                "m9",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"collected": 1, "skipped_no_run": 1}
    assert live_like_db.read_bytes() == before  # the copy is only read
    found = json.loads((runs_dir / "pf1-a.findings.json").read_text(encoding="utf-8"))
    assert (
        found["format"] == "review-findings/1"
        and len(found["findings"]) == 2
        and found["model"] == "m9"
    )
    record = json.loads((runs_dir / "pf1-a.run.json").read_text(encoding="utf-8"))
    assert (
        record["mode"] == "main"
        and record["pages_read"] == 2
        and record["ai"]["reader"] == "ollama"
    )
    assert record["minutes"] == 3.5  # the runner's own field kept
    assert not (runs_dir / "pf1-b.findings.json").exists()
    assert "mode" not in json.loads(
        (runs_dir / "pf1-b.run.json").read_text(encoding="utf-8")
    )
    with pytest.raises(SystemExit):  # a mode nobody declared is refused
        script.main(
            ["--db", str(live_like_db), "--runs", str(runs_dir), "--mode", "guess"]
        )
