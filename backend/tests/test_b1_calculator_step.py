# ruff: noqa: F811
"""The calculator step of the AI review job (owner, 12 Nov 2026, STATE section 37; PR 3). An invented paper, rule book and model; no network.

Off (the default) the job is what it was; on, the old rule check's code comparisons are lines of the run, stored before the first reader call.
"""

from __future__ import annotations

import json

import pytest

import tests.test_agent_review_job as J
from app import agent_review_calculator_run as run_mod
from app import agent_review_jobs, datasheets, db
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_job import (  # noqa: F401 - fixture
    lines_of,
    reading,
    run_job,
    start,
    world,
)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_calculator_enabled", True)


def frame_item(roles=("coating thickness",), **over):
    it = next(i for i in J._DOC["items"] if i["item_id"] == "R-frame")
    it["field_roles"] = list(roles)
    it.update(over)
    return it


def fact(
    label="Coating thickness",
    raw="0.35",
    unit="mm",
    tag=None,
    source=None,
    blank=False,
    page=1,
):
    return datasheets.create_fact(
        submittal_document_id=s.PAPER, chunk_id=f"{s.PAPER}:c0", field_label=label, raw_value=None if blank else raw, page=page,
        unit=unit, equipment_tag=tag, source_text=source or f"{label}: {raw} {unit}", blank=(True, "-") if blank else None,
    )  # fmt: skip


def code_lines(run_id):
    return {k: v for k, v in lines_of(run_id).items() if k.startswith("C-")}


def outcome(run_id):
    row = (
        db.connect()
        .execute("SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["counts_json"])


# ---------------------------------------------------------------------------------------- off: the job is what it was


def test_off_the_step_does_nothing_before_any_read(world, monkeypatch):
    assert settings.ai_review_calculator_enabled is False
    monkeypatch.setattr(
        run_mod,
        "_run",
        lambda *a, **k: pytest.fail("the calculator ran with its setting off"),
    )
    frame_item()
    fact()
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    assert code_lines(run_id) == {} and "calculator" not in outcome(run_id)
    assert set(lines_of(run_id)) == {
        "R-coat",
        "R-frame",
        "R-mark",
        "R-colour",
    }  # exactly the model's lines


# ---------------------------------------------------------------------------------------- on


def test_on_a_stored_fact_against_a_numeric_rule_is_a_proven_line_of_the_run_and_the_crs(
    world, on
):
    frame_item()
    f = fact()
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    got = lines_of(run_id)[f"C-R-frame-{f['id']}"]
    assert (got["verdict_class"], got["word"]) == ("Proven by code", "Pass") and got[
        "rule_tier"
    ] == "AI approved"
    assert set(lines_of(run_id)) >= {
        "R-coat",
        "R-frame",
        "R-mark",
        "R-colour",
    }  # the model's lines are untouched
    note = outcome(run_id)["calculator"]
    assert (
        note["ran"] is True
        and note["pairs"] == 1
        and note["by_class"]["Proven by code"] >= 1
    )
    from openpyxl import load_workbook

    cells = [
        c
        for ws in load_workbook(
            agent_review_jobs.run_dir(run_id) / "crs-internal.xlsx"
        ).worksheets
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c
    ]
    assert any("Coating thickness" in str(c) for c in cells)


def test_a_breach_is_a_proven_fail_on_the_contractor_copy(world, on):
    frame_item(value=0.5)  # the limit is now at least 0.5 mm: 0.35 breaks it
    fact()
    run_id, job_id = start()
    run_job(job_id)
    (line,) = [v for k, v in code_lines(run_id).items() if v["word"] == "Fail"]
    assert line["verdict_class"] == "Proven by code"


def test_the_lines_are_stored_before_the_first_reader_call(world, on, monkeypatch):
    frame_item()
    fact()
    seen = []
    real = world.__class__.__call__

    def spy(self, *a, **k):
        seen.append(bool(code_lines(self_run[0])))
        return real(self, *a, **k)

    self_run = []
    monkeypatch.setattr(world.__class__, "__call__", spy)
    run_id, job_id = start()
    self_run.append(run_id)
    run_job(job_id)
    assert (
        seen and seen[0] is True
    )  # at the first lead call the code line was already in the table


def test_the_same_on_a_closed_lane_no_reader_at_all(world, on, monkeypatch):
    """The calculator is code: with no reader able to answer, its lines are there."""
    frame_item()
    f = fact()

    class Refusing:
        def __call__(self, *a, **k):
            raise RuntimeError("no reader")

    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (Refusing(), s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    assert (
        f"C-R-frame-{f['id']}" in lines_of(run_id)
        and lines_of(run_id)[f"C-R-frame-{f['id']}"]["word"] == "Pass"
    )


# ---------------------------------------------------------------------------------------- pairing and refusals


def test_a_fact_of_another_quantity_a_blank_one_and_a_unit_mismatch_make_no_pass(
    world, on
):
    frame_item()
    other = fact(
        label="Coating weight", raw="0.9", unit="mm"
    )  # not the quantity the rule asks
    blank = fact(label="Coating thickness", blank=True)  # a blank value
    bar = fact(
        label="Coating thickness", raw="0.35", unit="bar", tag="T2"
    )  # a unit the limit cannot be compared with: the classic pairing refuses it
    run_id, job_id = start()
    run_job(job_id)
    got = code_lines(run_id)
    for f in (other, blank, bar):
        assert (
            f"C-R-frame-{f['id']}" not in got
        )  # no pair, no line: the reader handles what the code cannot pair
    assert all(v["word"] != "Pass" for k, v in got.items() if k.startswith("C-R-"))


def test_one_line_per_tag_when_the_same_field_is_stated_for_several_items(world, on):
    frame_item()
    a, b = (
        fact(tag="N1"),
        fact(tag="N2", raw="0.1"),
    )  # the second tag's value is not on the page: a Query, never a verdict
    run_id, job_id = start()
    run_job(job_id)
    got = code_lines(run_id)
    assert got[f"C-R-frame-{a['id']}"]["word"] == "Pass"
    assert (
        got[f"C-R-frame-{b['id']}"]["word"] == "Query"
        and "not found on its page" in got[f"C-R-frame-{b['id']}"]["reason"]
    )


def test_a_quote_that_is_not_on_the_page_is_a_query_not_a_pass(world, on):
    frame_item()
    f = fact(source="Coating thickness is not stated on this page at all")
    run_id, job_id = start()
    run_job(job_id)
    line = lines_of(run_id)[f"C-R-frame-{f['id']}"]
    assert line["word"] == "Query" and "not found on its page" in line["reason"]


def test_a_numeric_code_line_of_an_unapproved_rule_is_capped(world, on):
    frame_item(
        rule_tier="not_approved",
        rule_label={
            "paper_kind": "datasheet",
            "field": "coating_thickness",
            "tier": "Not AI approved",
            "state": "ai_approved",
        },
    )
    f = fact()
    run_id, job_id = start()
    run_job(job_id)
    assert lines_of(run_id)[f"C-R-frame-{f['id']}"]["verdict_class"] != "Proven by code"


# ---------------------------------------------------------------------------------------- notes: never an empty "all fine"


def test_no_stored_facts_is_said_not_hidden(world, on):
    run_id, job_id = start()
    run_job(job_id)
    note = outcome(run_id)["calculator"]
    assert (
        note["ran"] is False
        and "no datasheet value is stored" in note["reason"]
        and code_lines(run_id) == {}
    )


def test_a_paper_that_is_not_a_datasheet_says_so(world, on, monkeypatch):
    monkeypatch.setattr(
        agent_review_jobs.agent_review_kind,
        "decide",
        lambda *a, **k: reading("procedure"),
    )
    fact()
    note = run_mod.step(
        db.connect(),
        "r",
        s.PAPER,
        reading("procedure"),
        {"items": []},
        store=lambda *a: None,
        tier_lookup=None,
    )
    assert note == []


def test_an_error_in_the_calculator_never_fails_the_review_and_is_said(
    world, on, monkeypatch
):
    monkeypatch.setattr(
        run_mod, "_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    note = outcome(run_id)["calculator"]
    assert (
        note["ran"] is False
        and "an error (RuntimeError)" in note["reason"]
        and code_lines(run_id) == {}
    )


def test_a_resumed_run_writes_the_same_lines_again_not_more(world, on):
    frame_item()
    fact()
    run_id, job_id = start()
    run_job(job_id)
    before = set(code_lines(run_id))
    again = run_mod.step(
        db.connect(),
        run_id,
        s.PAPER,
        reading(),
        {"items": [frame_item()], "cache": J._CACHE},
        store=lambda line, trace: agent_review_jobs.store_line(run_id, line, trace),
        tier_lookup=agent_review_jobs._tier_lookup(reading()),
    )
    assert before == set(code_lines(run_id)) and len(again) >= 1


def test_trial_report_names_the_calculator():
    import importlib.util
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "trial_on_copy.py"
    spec = importlib.util.spec_from_file_location("trial_on_copy_calc", path)
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["trial_on_copy_calc"] = mod
    spec.loader.exec_module(mod)
    ran = {
        "counts_json": json.dumps(
            {
                "calculator": {
                    "ran": True,
                    "lines": 3,
                    "pairs": 3,
                    "facts": 9,
                    "by_class": {"Proven by code": 3},
                }
            }
        )
    }
    out = mod.calculator_check(ran)
    assert out and out[0].ok and "3 code lines" in out[0].detail
    silent = {"counts_json": json.dumps({"calculator": {"ran": False}})}
    assert not mod.calculator_check(silent)[
        0
    ].ok  # not run and no reason: not an all-fine
    assert mod.calculator_check({"counts_json": "{}"}) == []
