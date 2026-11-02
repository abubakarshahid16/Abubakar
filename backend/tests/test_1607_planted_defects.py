"""#1607 (plan change 6 D, first slice): planted-defect sheets and their scorer.

An invented base datasheet, copies with ONE known defect each, a machine-readable
answer per copy, and a scorer that runs the real review path on a database copy
and reports per defect kind. The headline is a planted defect read as a Pass.
Invented values only; no model and no Claude here.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pymupdf
import pytest
from tools import planted_defects as pd

from app import db, submittal_review
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
SEVEN = {
    "over_limit",
    "wrong_unit",
    "blank_required",
    "contradictory",
    "wrong_sign",
    "wrong_field",
    "missing_page",
}


@pytest.fixture(scope="module")
def base() -> dict:
    return pd.load_base(pd.BASES / "relief_valve.json")


def _printed(path: Path) -> list[str]:
    with pymupdf.open(path) as pdf:
        return [line for page in pdf for line in page.get_text().splitlines()]


def _rows_of(sheet: dict) -> list[tuple]:
    return [
        (page["heading"], r["role"], r["value"], r.get("unit"))
        for page in sheet["pages"]
        for r in page["rows"]
    ]


# ------------------------------------------------------------------ the generator


def test_the_relief_valve_base_plants_all_seven_kinds_with_an_answer(base, tmp_path):
    manifest = pd.write_set(base, tmp_path)
    planted = [s for s in manifest["sheets"] if not s["control"]]
    assert {s["defect"] for s in planted} == SEVEN
    assert len(planted) == len(base["plants"])
    for sheet in planted:
        answer = json.loads((tmp_path / sheet["answer"]).read_text())
        assert answer["format"] == "planted-answer/1"
        assert answer["defect"] in SEVEN
        assert answer["fields"], "an answer names the field"
        assert answer["wanted"] in ("does_not_meet", "query")
        assert (tmp_path / answer["sheet"]).is_file()


def test_each_copy_differs_from_the_clean_sheet_only_where_the_answer_says(base):
    clean = pd.control_sheet(base, base["controls"][0])
    for plant in base["plants"]:
        sheet, answer = pd.plant(base, plant)
        before, after = set(_rows_of(clean)), set(_rows_of(sheet))
        changed = {row[1] for row in before ^ after}
        if answer["defect"] == "missing_page":
            assert len(sheet["pages"]) == len(clean["pages"]) - 1
            assert changed == set(answer["fields"])
        else:
            assert changed == set(answer["fields"]), plant


def test_the_defects_do_what_their_names_say(base):
    set_row = lambda sheet: next(  # noqa: E731
        r for p in sheet["pages"] for r in p["rows"] if r["role"] == "set_pressure"
    )
    sign, _ = pd.plant(
        base, {"defect": "wrong_sign", "field": "set_pressure", "wanted": "query"}
    )
    assert set_row(sign)["value"] == "-10"
    blank, _ = pd.plant(
        base, {"defect": "blank_required", "field": "set_pressure", "wanted": "query"}
    )
    assert set_row(blank)["value"] == ""
    swap, answer = pd.plant(
        base,
        {
            "defect": "wrong_field",
            "field": "set_pressure",
            "with": "mawp",
            "wanted": "does_not_meet",
        },
    )
    assert set_row(swap)["value"] == "12" and set(answer["fields"]) == {
        "set_pressure",
        "mawp",
    }
    twice, _ = pd.plant(
        base,
        {
            "defect": "contradictory",
            "field": "set_pressure",
            "value": "11.5",
            "wanted": "query",
        },
    )
    both = [
        (p, r["value"])
        for p, page in enumerate(twice["pages"], start=1)
        for r in page["rows"]
        if r["role"] == "set_pressure"
    ]
    assert {v for _, v in both} == {"10", "11.5"} and len({p for p, _ in both}) == 2


def test_the_files_are_blind_and_the_same_bytes_every_run(base, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    first, second = pd.write_set(base, a), pd.write_set(base, b)
    assert first == second
    for sheet in first["sheets"]:
        assert (a / sheet["sheet"]).read_bytes() == (b / sheet["sheet"]).read_bytes()
        name = sheet["sheet"].lower()
        assert not any(word in name for word in (*SEVEN, "clean", "control", "planted"))
    text = " ".join(_printed(a / first["sheets"][-1]["sheet"])).lower()
    assert not any(word in text for word in ("planted", "defect", "clean"))


def test_the_printed_sheet_carries_the_planted_value(base, tmp_path):
    sheet, answer = pd.plant(base, base["plants"][0])
    path = tmp_path / "x.pdf"
    pd.render_pdf(sheet, path, doc_no="SYN-PSV-0000")
    assert answer["planted"] in _printed(path)


def test_the_generator_names_no_equipment_type_a_second_base_works():
    """Rule 13: the same code plants in any base; nothing here knows relief valves."""
    pump = {
        "format": "planted-base/1",
        "source": "invented",
        "name": "pump",
        "equipment_type": "Centrifugal Pump",
        "title": "CENTRIFUGAL PUMP DATA SHEET",
        "doc_prefix": "SYN-PMP",
        "pages": [
            {
                "heading": "A",
                "rows": [
                    {
                        "role": "rated_flow",
                        "field": "Rated flow",
                        "value": "40",
                        "unit": "m3/h",
                    }
                ],
            },
            {
                "heading": "B",
                "rows": [
                    {
                        "role": "rated_head",
                        "field": "Rated head",
                        "value": "55",
                        "unit": "m",
                    }
                ],
            },
        ],
        "controls": [{"name": "clean", "set": {}}],
        "plants": [{"defect": "wrong_sign", "field": "rated_head", "wanted": "query"}],
    }
    sheet, answer = pd.plant(pd.check_base(pump), pump["plants"][0])
    assert (
        answer["fields"] == ["rated_head"]
        and sheet["pages"][1]["rows"][0]["value"] == "-55"
    )


def test_a_base_not_marked_invented_or_public_is_refused():
    with pytest.raises(ValueError, match="invented or public"):
        pd.check_base(
            {"format": "planted-base/1", "source": "client", "pages": [], "plants": []}
        )


def test_an_unknown_defect_or_field_is_refused_never_a_silent_clean_copy(base):
    with pytest.raises(ValueError):
        pd.plant(base, {"defect": "typo", "field": "set_pressure", "wanted": "query"})
    with pytest.raises(ValueError):
        pd.plant(
            base, {"defect": "wrong_sign", "field": "no_such_field", "wanted": "query"}
        )
    with pytest.raises(ValueError):
        pd.plant(
            base, {"defect": "wrong_sign", "field": "set_pressure", "wanted": "maybe"}
        )


# ------------------------------------------------------------------ the scoring


def row(status, role, key="k1", tier="checklist"):
    return {"key": key, "status": status, "roles": {role}, "tier": tier}


ANSWER = {"fields": ["set_pressure"], "wanted": "does_not_meet", "defect": "over_limit"}


def test_a_new_fail_on_the_field_is_caught_as_a_fail():
    got = pd.judge(ANSWER, [row("NON_COMPLIANT", "set_pressure")], [])
    assert got["got"] == "fail" and got["as_wanted"] is True


def test_a_new_query_on_the_field_is_caught_but_not_as_wanted():
    for status in ("MISSING_INFORMATION", "NEEDS_ENGINEER_REVIEW"):
        got = pd.judge(ANSWER, [row(status, "set_pressure")], [])
        assert got["got"] == "query" and got["as_wanted"] is False


def test_a_pass_on_the_field_with_nothing_else_is_the_headline():
    got = pd.judge(
        ANSWER, [row("COMPLIANT", "set_pressure")], [row("COMPLIANT", "set_pressure")]
    )
    assert got["got"] == "wrongly_passed"


def test_a_query_the_clean_sheet_also_has_catches_nothing():
    """Not vacuous: a Query already on the clean sheet is no catch of the plant."""
    same = row("NEEDS_ENGINEER_REVIEW", "set_pressure")
    got = pd.judge(ANSWER, [same], [same])
    assert got["got"] == "missed"
    got = pd.judge(ANSWER, [same, row("COMPLIANT", "set_pressure", "k2")], [same])
    assert got["got"] == "wrongly_passed"


def test_no_row_on_the_field_is_missed():
    assert (
        pd.judge(ANSWER, [row("NOT_APPLICABLE", "set_pressure")], [])["got"] == "missed"
    )
    assert pd.judge(ANSWER, [], [])["got"] == "missed"


def test_a_new_row_on_another_field_catches_nothing_and_is_a_false_alarm():
    got = pd.judge(ANSWER, [row("NON_COMPLIANT", "mawp")], [])
    assert got["got"] == "missed" and got["false_new"] == 1
    got = pd.judge(
        ANSWER,
        [
            row("NON_COMPLIANT", "set_pressure"),
            row("NEEDS_ENGINEER_REVIEW", "mawp", "k2"),
        ],
        [],
    )
    assert got["got"] == "fail" and got["false_new"] == 1


def test_a_passing_row_on_a_caught_defect_is_stated_apart():
    rows = [
        row("NON_COMPLIANT", "set_pressure"),
        row("COMPLIANT", "set_pressure", "k2"),
    ]
    got = pd.judge(ANSWER, rows, [])
    assert got["got"] == "fail" and got["also_passed"] == 1


def test_the_table_counts_per_kind_and_puts_the_passes_first():
    sheets = [
        {
            "defect": "over_limit",
            "got": "fail",
            "as_wanted": True,
            "false_new": 0,
            "also_passed": 0,
        },
        {
            "defect": "over_limit",
            "got": "wrongly_passed",
            "as_wanted": False,
            "false_new": 1,
            "also_passed": 0,
        },
        {
            "defect": "wrong_sign",
            "got": "query",
            "as_wanted": True,
            "false_new": 0,
            "also_passed": 0,
        },
        {
            "defect": "wrong_sign",
            "got": "missed",
            "as_wanted": False,
            "false_new": 0,
            "also_passed": 0,
        },
        {
            "defect": "wrong_sign",
            "got": "not_run",
            "as_wanted": False,
            "false_new": 0,
            "also_passed": 0,
        },
    ]
    kinds = pd.per_kind(sheets)
    assert kinds["over_limit"] == {
        "planted": 2,
        "fail": 1,
        "query": 0,
        "missed": 0,
        "wrongly_passed": 1,
        "not_run": 0,
        "as_wanted": 1,
        "on_crs": 0,
        "false_new": 1,
    }
    assert kinds["wrong_sign"]["planted"] == 3 and kinds["wrong_sign"]["not_run"] == 1
    text = pd.render(
        {
            "reader": "rules",
            "base": "relief_valve",
            "sheets": sheets,
            "controls": [
                {
                    "sheet": "s",
                    "fail": 2,
                    "query": 1,
                    "fail_library": 0,
                    "query_library": 7,
                }
            ],
            "library_rows": 0,
        }
    )
    first = text.index("read as a Pass")
    assert first < text.index("| over_limit |")
    assert "1 of 5 planted defects" in text and "not run" in text
    assert "false alarms" in text and "reader: rules" in text


def test_a_sheet_that_did_not_run_is_never_counted_as_read():
    """A failed review is 'not run', never 'missed' and never a clean result."""
    kinds = pd.per_kind(
        [
            {
                "defect": "over_limit",
                "got": "not_run",
                "as_wanted": False,
                "false_new": 0,
                "also_passed": 0,
            }
        ]
    )
    assert kinds["over_limit"]["missed"] == 0 and kinds["over_limit"]["fail"] == 0


def test_nothing_run_never_reads_as_zero_passes():
    """Rule 4: 0 of 2 read as a Pass, when neither sheet ran, is not a green number."""
    nothing = {"got": "not_run", "as_wanted": False, "false_new": 0, "also_passed": 0}
    text = pd.render(
        {
            "reader": "rules",
            "base": "b",
            "sheets": [
                {"defect": "over_limit", **nothing},
                {"defect": "wrong_sign", **nothing},
            ],
            "controls": [
                {
                    "sheet": "s",
                    "fail": 0,
                    "query": 0,
                    "fail_library": 0,
                    "query_library": 0,
                    "not_run": "not read",
                }
            ],
        }
    )
    assert "2 not run, so this count is not a result" in text
    assert "over 0 clean sheets" in text and "1 clean sheets did not run" in text


def test_a_plant_is_not_judged_when_its_clean_control_did_not_run(
    base, copy_db, tmp_path, monkeypatch
):
    small = _small(base, (("over_limit", "set_pressure"),))
    real = pd._review
    calls = []

    def fails_first(path):
        calls.append(path)
        return (None, "not read: failed") if len(calls) == 1 else real(path)

    monkeypatch.setattr(pd, "_review", fails_first)
    result = pd.score(copy_db, [small], reader="rules", work=tmp_path / "w")
    assert result["sheets"][0]["got"] == "not_run"
    assert "clean control" in result["sheets"][0]["why"]


def test_a_spawned_worker_is_pointed_at_the_copy_and_the_environment_comes_back(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DB_PATH", "before")
    monkeypatch.setattr(settings, "db_path", tmp_path / "x.sqlite")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    audit_before = settings.review_audit_dir
    with pd._settings_for_copy(tmp_path):
        import os

        assert os.environ["DB_PATH"] == str(tmp_path / "x.sqlite")
        assert os.environ["UPLOAD_DIR"] == str(tmp_path / "uploads")
        assert settings.review_audit_dir == str(tmp_path / "audit")
    assert (
        os.environ["DB_PATH"] == "before" and settings.review_audit_dir == audit_before
    )


# ------------------------------------------------------------------ the real path


@pytest.fixture
def copy_db(tmp_path, monkeypatch):
    """A small database standing in for a copy: no library, the checklist only."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "source.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    db.reset_connection()
    return tmp_path / "source.sqlite"


def _small(base: dict, defects: tuple[str, ...]) -> dict:
    out = copy.deepcopy(base)
    out["plants"] = [
        p for p in base["plants"] if (p["defect"], p.get("field")) in defects
    ]
    out["controls"] = base["controls"][:1]
    return out


def test_the_scorer_runs_the_real_review_path_on_its_own_copy(base, copy_db, tmp_path):
    small = _small(base, (("over_limit", "set_pressure"),))
    before = copy_db.read_bytes()
    result = pd.score(copy_db, [small], reader="rules", work=tmp_path / "w")
    assert copy_db.read_bytes() == before, "the database passed in is not written"
    assert result["reader"] == "rules"
    assert not list((tmp_path / "w").glob("*.sqlite"))
    sheet = result["sheets"][0]
    assert sheet["got"] == "fail", sheet
    assert sheet["defect"] == "over_limit"
    control = result["controls"][0]
    assert control["fail"] == 0, control


def test_the_stand_in_reader_reads_the_same_sheet_through_the_ai_path(
    base, copy_db, tmp_path
):
    small = _small(base, (("over_limit", "set_pressure"),))
    result = pd.score(copy_db, [small], reader="fake", work=tmp_path / "w")
    assert result["sheets"][0]["got"] == "fail", result["sheets"][0]
    assert result["ai_facts"] > 0, "the fake reader's readings reached the facts"


def test_the_scorer_can_report_a_pass_through_the_real_path(base, copy_db, tmp_path):
    """The headline is not vacuous. A changed value still within its limit reads as a Pass, so
    the scorer reports it, whatever later fixes do to the real plants."""
    small = _small(base, ())
    small["plants"] = [
        {
            "defect": "over_limit",
            "field": "overpressure",
            "value": "20",
            "wanted": "does_not_meet",
        }
    ]
    result = pd.score(copy_db, [small], reader="rules", work=tmp_path / "w")
    assert result["sheets"][0]["got"] == "wrongly_passed", result["sheets"][0]
    assert "1 of 1 planted defects" in pd.render(result)


def test_a_clean_sheet_read_by_the_stand_in_has_no_false_alarm(base, copy_db, tmp_path):
    small = _small(base, ())
    result = pd.score(copy_db, [small], reader="fake", work=tmp_path / "w")
    control = result["controls"][0]
    assert {k: control[k] for k in ("sheet", "fail", "query")} == {
        "sheet": "relief_valve-01.pdf",
        "fail": 0,
        "query": 0,
    }
    assert control["fail_library"] == 0 and control["query_library"] == 0


def test_the_scorer_refuses_the_live_database(tmp_path, monkeypatch):
    from app import live_guard

    monkeypatch.setattr(live_guard, "is_live_shaped", lambda _p: True)
    with pytest.raises(PermissionError):
        pd.score(tmp_path / "x.sqlite", [], reader="rules", work=tmp_path)


def test_no_reader_mode_can_reach_claude():
    from app import reader_transport

    for reader in pd.READERS:
        with pd.no_claude(reader), pytest.raises(pd.ClaudeRefused):
            reader_transport.stream("anything")


def test_an_unknown_reader_is_refused(tmp_path):
    with pytest.raises(ValueError, match="reader"):
        pd.score(tmp_path / "x.sqlite", [], reader="claude", work=tmp_path)


# ------------------------------------------------------------------ the bench switch


def _bench():
    spec = importlib.util.spec_from_file_location(
        "crs_bench_script_1607", REPO / "scripts" / "crs_bench.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bench_run(tmp_path, monkeypatch):
    from tools import crs_bench

    source = tmp_path / "copy.sqlite"
    sqlite3.connect(source).close()
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"cases": []}))
    monkeypatch.setattr(crs_bench, "run_bench", lambda *_a, **_k: [])
    monkeypatch.setattr(crs_bench, "render_markdown", lambda *_a, **_k: "BENCH TABLE")
    monkeypatch.setattr(crs_bench, "gate", lambda *_a, **_k: [])
    script = _bench()
    monkeypatch.setattr(script, "_settings_file", lambda _g: None)
    return script, ["--db", str(source), "--truth", str(truth), "--stored-only"]


def test_the_switch_defaults_off_and_the_bench_then_runs_no_scorer(
    bench_run, monkeypatch, capsys
):
    script, argv = bench_run
    assert settings.planted_defects_bench_enabled is False
    monkeypatch.setattr(
        pd, "bench_section", lambda *_a, **_k: pytest.fail("the scorer ran")
    )
    assert script.main(argv) == 0
    assert "Planted defects" not in capsys.readouterr().out


def test_the_switch_on_prints_the_table_and_never_moves_the_gate(
    bench_run, monkeypatch, capsys
):
    script, argv = bench_run
    monkeypatch.setattr(settings, "planted_defects_bench_enabled", True)
    monkeypatch.setattr(
        pd, "bench_section", lambda *_a, **_k: "## Planted defects\n9 read as a Pass"
    )
    assert script.main(argv) == 0, (
        "a planted defect read as a Pass is printed, not gated yet"
    )
    out = capsys.readouterr().out
    assert "BENCH TABLE" in out and "## Planted defects" in out


def test_a_scorer_crash_says_not_run_and_the_bench_table_stays(
    bench_run, monkeypatch, capsys
):
    script, argv = bench_run
    monkeypatch.setattr(settings, "planted_defects_bench_enabled", True)

    def boom(*_a, **_k):
        raise RuntimeError("no")

    monkeypatch.setattr(pd, "bench_section", boom)
    assert script.main(argv) == 0
    out = capsys.readouterr().out
    assert "BENCH TABLE" in out and "Planted defects: not run (RuntimeError)" in out


def test_the_script_writes_a_set(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location(
        "planted_script_1607", REPO / "scripts" / "planted_defects.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.main(["generate", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "relief_valve" / "manifest.json").is_file()
    assert (tmp_path / "centrifugal_pump" / "manifest.json").is_file()


# ------------------------------------------------------------------ the pump base


@pytest.fixture(scope="module")
def pump() -> dict:
    return pd.load_base(pd.BASES / "centrifugal_pump.json")


def test_the_pump_base_is_invented_and_plants_all_seven_kinds(pump, tmp_path):
    assert pump["source"] == "invented"
    assert pump["equipment_type"] == "Centrifugal Pump"
    manifest = pd.write_set(pump, tmp_path)
    planted = [s for s in manifest["sheets"] if not s["control"]]
    assert {s["defect"] for s in planted} == SEVEN
    assert manifest["equipment_type"] == "Centrifugal Pump"


@pytest.mark.parametrize("name", ["relief_valve", "centrifugal_pump"])
def test_every_printed_label_is_read_as_the_field_the_base_says(name):
    """Otherwise a plant lands on a row the review cannot see, and scores as a miss
    of the reader when the base is what is wrong."""
    from app import datasheet_checks as dc

    rules = dc.load_rules()
    base = pd.load_base(pd.BASES / f"{name}.json")
    known = {r["role"]: r["field"] for p in base["pages"] for r in p["rows"]}
    wrong = {
        role: label
        for role, label in known.items()
        if dc.role_of(label, rules, frozenset(known)) != role
    }
    assert not wrong


def test_the_pump_base_prints_every_field_its_checklist_asks_for(pump):
    from app import datasheet_checks as dc

    items = dc.load_rules()["checklists"][pump["equipment_type"]]["items"]
    printed = {r["role"] for p in pump["pages"] for r in p["rows"]}
    assert {i["rule"]["field"] for i in items} <= printed


def test_the_scorer_module_names_no_equipment_type():
    """Rule 13: a new kind of equipment is a new base file, never new code here."""
    import re

    from app import datasheet_checks as dc

    source = (REPO / "backend" / "tools" / "planted_defects.py").read_text().lower()
    types = [t for t in dc.load_rules()["checklists"] if not t.startswith("_")]
    assert not [t for t in types if t.lower() in source]
    assert not re.search(r"\b(pump|valve|vessel|exchanger)\b", source)


def test_a_pump_sheet_goes_through_the_real_review_and_is_typed_as_a_pump(
    pump, copy_db, tmp_path
):
    small = _small(pump, (("over_limit", "operating_pressure"),))
    result = pd.score(copy_db, [small], reader="rules", work=tmp_path / "w")
    sheet, control = result["sheets"][0], result["controls"][0]
    assert sheet["got"] == "fail", sheet
    assert sheet["equipment_type"] == "Centrifugal Pump"
    assert sheet["typed_as"] == "Centrifugal Pump"
    assert control["typed_as"] == "Centrifugal Pump"
    assert control["fail"] == 0 and control["query"] == 0, control
    assert control["checklist"]["rows"] >= 17, "the pump checklist ran"


# ------------------------------------------------------------------ risk and coverage


def _sheet(got, kind="Centrifugal Pump", **extra):
    return {
        "defect": "over_limit",
        "equipment_type": kind,
        "typed_as": kind,
        "got": got,
        "as_wanted": False,
        "false_new": 0,
        "also_passed": 0,
        **extra,
    }


def _clean(kind="Centrifugal Pump", *, rows=17, decided=17, fail=0, **extra):
    return {
        "sheet": "s",
        "equipment_type": kind,
        "typed_as": kind,
        "fail": fail,
        "query": rows - decided,
        "fail_library": 0,
        "query_library": 0,
        "checklist": {"rows": rows, "decided": decided, "fail": fail},
        **extra,
    }


def test_a_fail_is_decided_and_right_a_pass_is_decided_and_wrong():
    got = pd.per_type(
        [_sheet("fail"), _sheet("fail"), _sheet("wrongly_passed")], [_clean()]
    )["Centrifugal Pump"]
    assert got["planted"]["decided"] == 3 and got["planted"]["applicable"] == 3
    assert got["planted"]["risk"]["wrong"] == 1
    assert got["planted"]["risk"]["decided"] == 3


def test_a_query_or_no_row_is_not_decided_and_never_wrong():
    got = pd.per_type([_sheet("query"), _sheet("missed"), _sheet("fail")], [])[
        "Centrifugal Pump"
    ]
    assert got["planted"]["applicable"] == 3 and got["planted"]["decided"] == 1
    assert got["planted"]["risk"]["wrong"] == 0


def test_a_sheet_that_did_not_run_is_out_of_both_numbers_and_is_said():
    got = pd.per_type([_sheet("not_run"), _sheet("fail")], [])["Centrifugal Pump"]
    assert got["planted"]["applicable"] == 1 and got["not_run"] == 1


def test_a_fail_on_a_clean_sheet_is_the_wrong_side_of_the_risk():
    """Not vacuous: a review that fails everything has no wrong plant, so the clean
    side has to count, or it would read as 0 risk."""
    got = pd.per_type([_sheet("fail")], [_clean(rows=17, decided=10, fail=4)])[
        "Centrifugal Pump"
    ]
    assert got["clean"]["applicable"] == 17 and got["clean"]["decided"] == 10
    assert got["clean"]["risk"]["wrong"] == 4
    assert got["planted"]["risk"]["wrong"] == 0, "the two sides are never added"


def test_a_clean_sheet_that_did_not_run_is_not_counted_as_clean():
    got = pd.per_type([], [_clean(rows=0, decided=0, not_run="not read")])[
        "Centrifugal Pump"
    ]
    assert got["clean"] is None and got["not_run"] == 1


def _result(sheets, controls):
    return {"reader": "rules", "base": "b", "sheets": sheets, "controls": controls}


def _line(text, kind):
    return next(r for r in text.splitlines() if r.startswith(f"| {kind} |"))


def test_one_type_cannot_hide_another():
    text = pd.render(
        _result(
            [
                _sheet("fail", "Pressure Safety Valve"),
                _sheet("fail", "Pressure Safety Valve"),
                _sheet("wrongly_passed"),
                _sheet("query"),
            ],
            [_clean("Pressure Safety Valve", rows=47, decided=40), _clean()],
        )
    )
    assert "Risk and coverage per equipment type" in text
    psv, pmp = _line(text, "Pressure Safety Valve"), _line(text, "Centrifugal Pump")
    assert "2 of 2" in psv and "0 of 2" in psv and "40 of 47" in psv
    assert "1 of 2" in pmp and "17 of 17" in pmp
    assert text.index("Risk and coverage per equipment type") < text.index(
        "| over_limit |"
    )


def test_the_kind_table_is_per_type_too():
    text = pd.render(
        _result([_sheet("fail", "Pressure Safety Valve"), _sheet("wrongly_passed")], [])
    )
    assert text.count("| over_limit |") == 2
    assert "Pressure Safety Valve: per defect kind" in text
    assert "Centrifugal Pump: per defect kind" in text


def test_nothing_decided_is_not_measured_never_zero_risk():
    """Rule 4: a type of Queries only has made no decision that could be wrong."""
    line = _line(
        pd.render(_result([_sheet("query")], [_clean(rows=0, decided=0)])),
        "Centrifugal Pump",
    )
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[1] == "0 of 1" and cells[2] == "not measured"
    assert cells[3] == "" and cells[4] == "not measured", "null renders as nothing"


def test_a_type_with_nothing_run_gives_no_coverage_and_no_risk():
    line = _line(pd.render(_result([_sheet("not_run")], [])), "Centrifugal Pump")
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[1] == "" and cells[2] == "not measured" and cells[5] == "1"


def test_a_sheet_the_review_typed_as_something_else_is_said():
    """The type on the row is the base's. If the review read another, that type's
    checklist never ran: it stays in the number, as what the review did, and is said."""
    other = _sheet("missed", typed_as="Pressure Vessel")
    none = _clean(typed_as=None)
    line = _line(
        pd.render(_result([other, _sheet("fail")], [none])), "Centrifugal Pump"
    )
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[7] == "2"


def test_the_table_says_no_percentage():
    text = pd.render(_result([_sheet("fail")], [_clean()]))
    assert "%" not in text


def test_the_bench_prints_the_pair_per_type_through_the_real_scorer(
    base, pump, copy_db, tmp_path, monkeypatch, capsys
):
    from tools import crs_bench

    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"cases": []}))
    monkeypatch.setattr(crs_bench, "run_bench", lambda *_a, **_k: [])
    monkeypatch.setattr(crs_bench, "render_markdown", lambda *_a, **_k: "BENCH TABLE")
    monkeypatch.setattr(crs_bench, "gate", lambda *_a, **_k: ["red before the table"])
    monkeypatch.setattr(settings, "planted_defects_bench_enabled", True)
    monkeypatch.setattr(
        pd,
        "all_bases",
        lambda: [
            _small(base, (("over_limit", "set_pressure"),)),
            _small(pump, (("over_limit", "operating_pressure"),)),
        ],
    )
    script = _bench()
    monkeypatch.setattr(script, "_settings_file", lambda _g: None)
    code = script.main(["--db", str(copy_db), "--truth", str(truth), "--stored-only"])
    out = capsys.readouterr().out
    assert code == 1, (
        "the bench's own gate decides the exit code, not the planted table"
    )
    assert "Risk and coverage per equipment type" in out
    assert _line(out, "Pressure Safety Valve") and _line(out, "Centrifugal Pump")
    assert "not run (" not in out
