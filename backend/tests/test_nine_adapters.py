# ruff: noqa: RUF059
"""B5: the adapters that wire roles 1 to 4 into the job. No model, no network: the role modules are replaced by fakes where a call would
be made, and every model call is shown to go through `nine_call.ask`."""

from __future__ import annotations

import pytest

from app import db, nine_call, nine_context, nine_facts, nine_job, nine_reader
from app.config import settings
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)


def ctx_for(doc, ai, items=()):
    return nine_job.RoleContext(
        ai,
        doc,
        type("K", (), {"equipment_type": "relief valve", "kind": "datasheet"})(),
        {"items": list(items)},
        {},
        lambda *a: None,
    )


def no_calls(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a model call was made")

    monkeypatch.setattr(nine_call, "ask", boom)


def test_the_reader_adapter_hands_pages_stored_facts_and_the_engine_to_the_reader_and_stores_the_sheet(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    seen = {}

    def fake(**kw):
        seen.update(kw)
        sheet = nine_facts.sheet_of(
            kw["run_id"], kw["paper_id"], 4, [], [], kw["engine"], ["m1"]
        )
        return nine_reader.ReadResult(
            sheet, {"facts": 0}, "ran_partly", "one page not read"
        )

    monkeypatch.setattr(nine_reader, "read_paper", fake)
    ctx = ctx_for(doc, ai)
    got = nine_job.reader_role(ctx)
    assert (
        seen["engine"] == "claude"
        and seen["paper_id"] == doc
        and seen["equipment_type"] == "relief valve"
        and callable(seen["picture_of"])
    )
    assert (
        got.state == "ran_partly"
        and got.why == "one page not read"
        and ctx.store["fact_sheet"].paper_id == doc
    )
    assert nine_facts.load(db.connect(), ai) is not None


def test_the_reader_has_no_picture_function_on_the_local_model(monkeypatch):
    doc, rc, ai, client = world_with_both()
    seen = {}
    monkeypatch.setattr(nine_job, "_engine", lambda ctx: "local")
    monkeypatch.setattr(
        nine_reader,
        "read_paper",
        lambda **kw: (
            seen.update(kw)
            or nine_reader.ReadResult(
                nine_facts.sheet_of(
                    kw["run_id"], kw["paper_id"], 0, [], [], "local", []
                ),
                {},
                "ran",
            )
        ),
    )
    nine_job.reader_role(ctx_for(doc, ai))
    assert seen["engine"] == "local" and seen["picture_of"] is None


def test_the_context_role_with_nothing_held_makes_no_call_and_says_the_five_things_are_not_available(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    no_calls(monkeypatch)
    ctx = ctx_for(doc, ai)
    got = nine_job.context_role(ctx)
    note = ctx.store["context_note"]
    assert got.state == "ran" and [n.what for n in note.not_available] == list(
        nine_context.WHATS
    )
    assert got.produced["context_passed"] == "no"
    assert got.produced["context_not_passed_because"] == "per_document_blocks_not_built"


def test_the_librarian_with_no_chosen_rules_reads_nothing_and_says_so(monkeypatch):
    doc, rc, ai, client = world_with_both()
    no_calls(monkeypatch)
    ctx = ctx_for(doc, ai)
    got = nine_job.librarian_role(ctx)
    assert (
        got.state == "ran"
        and got.produced["books"] == 0
        and got.produced["chapters_chosen"] == 0
    )


def test_the_reviewer_with_no_reading_list_does_not_run_and_the_checklist_then_asks_everything(
    monkeypatch,
):
    doc, rc, ai, client = world_with_both()
    ctx = ctx_for(doc, ai, [{"item_id": "R-1"}, {"item_id": "S-2"}])
    got = nine_job.reviewer_role(ctx)
    assert (
        got.state == "not_run"
        and "no chapter was chosen" in got.why
        and ctx.flags["reviewer_failed"]
    )
    asked = []
    ctx.ask = lambda *a: asked.append([i["item_id"] for i in a[3]["items"]])
    nine_job.checklist_role(ctx)
    assert asked == [["R-1", "S-2"]]


def test_a_nine_role_run_whose_roles_read_nothing_asks_exactly_what_todays_review_asks(
    monkeypatch,
):
    """Roles 2 to 4 with nothing to read, role 1 unable to read: the lines come from the same ask over the same items as today's review."""
    doc, rc, ai, client = world_with_both()
    items = [{"item_id": "R-1"}, {"item_id": "R-2"}, {"item_id": "S-3"}]
    today, nine = [], []
    from app import agent_review_dispatch

    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", False)
    agent_review_dispatch.run(
        ai,
        doc,
        "k",
        {"items": list(items)},
        {},
        lambda *a: today.append([i["item_id"] for i in a[3]["items"]]),
    )
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    monkeypatch.setattr(
        nine_reader,
        "read_paper",
        lambda **kw: nine_reader.ReadResult(
            nine_facts.sheet_of(
                kw["run_id"], kw["paper_id"], 0, [], [], kw["engine"], []
            ),
            {},
            "not_run",
            "no page could be read",
        ),
    )
    no_calls(monkeypatch)
    ctx = type("K", (), {"equipment_type": None, "kind": "datasheet"})()
    agent_review_dispatch.run(
        ai,
        doc,
        ctx,
        {"items": list(items)},
        {},
        lambda *a: nine.append([i["item_id"] for i in a[3]["items"]]),
    )
    assert nine == today == [["R-1", "R-2", "S-3"]]
    rows = {
        r["role_no"]: r
        for r in db.connect().execute(
            "SELECT * FROM agent_review_role WHERE run_id = ?", (ai,)
        )
    }
    assert (
        len(rows) == 9
        and rows[4]["state"] == "not_run"
        and rows[1]["state"] == "not_run"
    )


def test_the_dry_run_prints_sizes_and_usd_per_role_sends_nothing_and_applies_the_stop_line(
    tmp_path, monkeypatch, capsys
):
    import importlib.util
    import shutil
    from pathlib import Path

    doc, rc, ai, client = world_with_both()
    db.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy(settings.db_path, tmp_path / "rag_intelligence.sqlite")
    spec = importlib.util.spec_from_file_location(
        "nine_dry_run",
        Path(__file__).resolve().parents[2] / "scripts" / "nine_dry_run.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(
        nine_job._jobs(),
        "lane",
        lambda: (_ for _ in ()).throw(AssertionError("a dry run sends nothing")),
    )
    assert script.main(["--copy", str(tmp_path), "--paper", doc, "--run", ai]) == 0
    out = capsys.readouterr().out
    assert "1 Reader" in out and "TOTAL" in out and "within the stop line" in out
    monkeypatch.setattr(script, "STOP_EXPECTED", -1.0)
    assert (
        script.main(["--copy", str(tmp_path), "--paper", doc, "--run", ai]) == 1
    )  # over the line: the exit says STOP
