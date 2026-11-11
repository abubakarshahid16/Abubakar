"""The label import (owner decision 1): the server re-checks every row by code before it stores it. Invented data."""

from __future__ import annotations

import copy as copylib
import json
import sqlite3

import pytest

from app import rule_label_import as imp
from app import rule_label_job as job
from app import rule_labels as rl
from app.config import settings
from app.db import connect
from tests import r2_security_support as support
from tests import rule_label_support as s

temp_storage = support.temp_storage
world = support.world
h = support.h


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    s.switch(monkeypatch)
    s.patch_pages(monkeypatch)


def _label_file(tmp_path, monkeypatch, name="labels.json"):
    """A real label file: the job labels a copy with two fake models and exports it."""
    from app import agent_claude

    agent_claude.reset_shared_meter_for_tests()
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    path = s.make_db(tmp_path / "labeller.sqlite")
    conn = job.open_copy(path)
    rules = job.select_rules(conn, books=[s.STANDARD])
    for pass_, model in (("a", s.MODEL_A), ("b", s.MODEL_B)):
        job.run_pass(
            conn,
            rules,
            pass_=pass_,
            model=model,
            lane=job.Lane(job.CapLedger(5), send=s.FakeModel(), env=s.ENV),
            out=lambda _m: None,
        )
    out = tmp_path / name
    job.write_export(conn, out)
    return out


@pytest.fixture
def server(tmp_path):
    """A plain database standing in for the server's: the same rules, with an engineer approval already in the book."""
    path = s.make_db(tmp_path / "server.sqlite", with_book=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(path):
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def test_a_label_file_is_stored_row_by_row_and_nothing_is_approved_unchecked(
    tmp_path, monkeypatch, server
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    approvals = s.table_hash(server, "rulebook_approval")
    counts = imp.import_labels(server, rows)
    assert counts == {
        "read": 2,
        "stored": 2,
        "skipped_changed_quote": 0,
        "unknown_rule": 0,
        "refused": 0,
    }
    assert {
        r["rule_ref"]: r["state"]
        for r in server.execute("SELECT rule_ref, state FROM rule_label")
    } == {"r1": "ai_approved", "r2": "ai_approved"}
    assert rl.usable_tier(server, requirement_id="r2").tier == "AI approved"
    assert (
        server.execute(
            "SELECT rule_version_id FROM rule_label WHERE rule_ref = 'r1'"
        ).fetchone()[0]
        == "v1"
    )  # derived here
    assert (
        s.table_hash(server, "rulebook_approval") == approvals
    )  # the engineer approval: count and hash unchanged


def test_a_label_whose_quote_changed_is_skipped_never_approved(
    tmp_path, monkeypatch, server
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    server.execute(
        "UPDATE standard_requirements SET source_text = source_text || ' Changed.' WHERE id = 'r1'"
    )
    server.commit()
    counts = imp.import_labels(server, rows)
    assert counts["skipped_changed_quote"] == 1 and counts["stored"] == 1
    assert (
        server.execute(
            "SELECT COUNT(*) FROM rule_label WHERE rule_ref = 'r1'"
        ).fetchone()[0]
        == 0
    )


def test_a_quote_that_no_longer_stands_on_its_page_is_not_approved(
    tmp_path, monkeypatch, server
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    s.patch_pages(
        monkeypatch, pages={1: "The page was replaced and holds neither invented rule."}
    )
    counts = imp.import_labels(server, rows)
    assert counts["skipped_changed_quote"] == 2 and counts["stored"] == 0
    assert server.execute("SELECT COUNT(*) FROM rule_label").fetchone()[0] == 0


def test_a_row_for_a_rule_this_database_does_not_hold_is_counted_not_stored(
    tmp_path, monkeypatch, server
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    rows[0]["rule_ref"] = "no-such-rule"
    counts = imp.import_labels(server, rows)
    assert counts["unknown_rule"] == 1 and counts["stored"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"b_model": s.MODEL_A},
        {"b_prompt": "rule-label-v2"},
        {"a_answer_sha256": None},
        {"paper_kind": None},
        {"reading": None},
        {"quote_page": 2},
        {"state": "bogus"},
        {"quote_recovery": "page"},
        {"quote_sha256": "short"},
    ],
)
def test_an_approval_that_fails_a_guard_is_refused_and_never_stored(
    tmp_path, monkeypatch, server, change
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    rows[0].update(change)
    counts = imp.import_labels(server, rows)
    assert counts["refused"] == 1 and counts["stored"] == 1
    assert (
        server.execute(
            "SELECT COUNT(*) FROM rule_label WHERE rule_ref = ?", (rows[0]["rule_ref"],)
        ).fetchone()[0]
        == 0
    )


def test_a_reading_the_quote_does_not_support_is_refused(tmp_path, monkeypatch, server):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    rows[0]["reading"]["values"] = [99.0]
    assert imp.import_labels(server, rows)["refused"] == 1


def test_a_quote_on_a_low_confidence_ocr_page_is_refused(tmp_path, monkeypatch, server):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    s.patch_pages(
        monkeypatch, origin={1: {"page_source": "recognised", "page_min_conf": 0.1}}
    )
    counts = imp.import_labels(server, rows)
    assert counts["refused"] == 2 and counts["stored"] == 0


def test_the_import_is_idempotent_and_writes_no_second_event(
    tmp_path, monkeypatch, server
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    first = imp.import_labels(server, rows)
    events = server.execute("SELECT COUNT(*) FROM rule_label_event").fetchone()[0]
    snapshot = s.table_hash(server, "rule_label")
    assert imp.import_labels(server, copylib.deepcopy(rows)) == first
    assert (
        server.execute("SELECT COUNT(*) FROM rule_label_event").fetchone()[0]
        == events
        == 2
    )
    assert s.table_hash(server, "rule_label") == snapshot


def test_a_changed_label_updates_the_row_and_appends_an_event(
    tmp_path, monkeypatch, server
):
    rows = _rows(_label_file(tmp_path, monkeypatch))
    imp.import_labels(server, rows)
    rows[0].update(
        state="needs_human",
        disagreement="kind",
        paper_kind=None,
        field=None,
        reading=None,
        quote_page=None,
        labelled_at="2026-11-12T00:00:00Z",
    )
    assert imp.import_labels(server, rows)["stored"] == 2
    assert (
        server.execute(
            "SELECT state FROM rule_label WHERE rule_ref = ?", (rows[0]["rule_ref"],)
        ).fetchone()[0]
        == "needs_human"
    )
    assert (
        server.execute(
            "SELECT COUNT(*) FROM rule_label_event WHERE event_type = 'relabel'"
        ).fetchone()[0]
        == 1
    )


def test_malformed_rows_are_refused_not_fatal(server):
    counts = imp.import_labels(server, ["not a row", {"source": "x"}, 7])
    assert counts == {
        "read": 3,
        "stored": 0,
        "skipped_changed_quote": 0,
        "unknown_rule": 0,
        "refused": 3,
    }


def test_the_switch_off_imports_nothing_and_makes_no_table(server, monkeypatch):
    s.switch(monkeypatch, False)
    from app.rule_label_schema import SwitchedOff

    with pytest.raises(SwitchedOff):
        imp.import_labels(server, [])
    assert "rule_label" not in {
        r[0] for r in server.execute("SELECT name FROM sqlite_master")
    }


# ---------------------------------------------------------------- the path and the route


def test_only_a_json_file_inside_the_data_directory_can_be_read(tmp_path):
    inside = tmp_path / "sub" / "labels.json"
    inside.parent.mkdir()
    inside.write_text("{}")
    assert imp.resolve_data_path("sub/labels.json") == inside.resolve()
    outside = tmp_path.parent / "outside-labels.json"
    outside.write_text("{}")
    for bad, why in (
        ("../outside-labels.json", "outside_the_data_directory"),
        (str(outside), "outside_the_data_directory"),
        ("sub/missing.json", "no_such_file"),
        ("sub", "not_a_json_file"),
        ("", "no_path"),
    ):
        with pytest.raises(imp.ImportPathError, match=why):
            imp.resolve_data_path(bad)
    link = tmp_path / "link.json"
    link.symlink_to(outside)
    with pytest.raises(imp.ImportPathError, match="outside_the_data_directory"):
        imp.resolve_data_path("link.json")


def _seed_server_rules():
    """The app's own database: a standard document with the two invented rules."""
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE documents SET filename = ? WHERE id = 'doc_std'", (s.STANDARD,)
        )
        for rid, clause, quote in (
            ("r1", "4.1", s.QUOTE_NUM),
            ("r2", "4.2", s.QUOTE_TXT),
        ):
            conn.execute(
                "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
                " created_at, updated_at) VALUES (?, 'doc_std', ?, 1, 'x', ?, 't', 't')",
                (rid, clause, quote),
            )


def test_the_route_is_admin_only_404_when_off_and_the_server_writes(
    world, tmp_path, monkeypatch
):
    # pages are read from the app's own tables: patched to the invented page for the document the rules sit on
    from app import compiled_rule_report

    page = f"{s.QUOTE_NUM}\n{s.QUOTE_TXT}\nA closing line of the invented page."
    monkeypatch.setattr(compiled_rule_report, "pages_of", lambda conn, sdid: {1: page})
    monkeypatch.setattr(compiled_rule_report, "page_origin", lambda conn, sdid: {})
    file = _label_file(tmp_path, monkeypatch)
    rows = _rows(file)
    file.write_text(json.dumps({"format": "rule-labels-v1", "rows": rows}))
    _seed_server_rules()
    body = {"path": "labels.json"}
    url = "/api/admin/rule-labels/import"

    s.switch(monkeypatch, False)
    off = world.post(url, json=body, headers=h("u_admin"))
    assert off.status_code == 404 and "feature_off" in off.text
    assert "rule_label" not in {
        r[0] for r in connect().execute("SELECT name FROM sqlite_master")
    }

    s.switch(monkeypatch, True)
    assert (
        world.post(url, json=body, headers=h("u_sub")).status_code == 404
    )  # not an admin: the same 404 as the others
    assert world.post(url, json=body).status_code == 404
    assert (
        world.post(url, json={"path": "../x.json"}, headers=h("u_admin")).status_code
        == 422
    )
    assert (
        world.post(url, json={"path": "missing.json"}, headers=h("u_admin")).status_code
        == 422
    )
    ok = world.post(url, json=body, headers=h("u_admin"))
    assert ok.status_code == 200, ok.text
    assert ok.json() == {
        "read": 2,
        "stored": 2,
        "skipped_changed_quote": 0,
        "unknown_rule": 0,
        "refused": 0,
    }
    assert (
        connect()
        .execute("SELECT COUNT(*) FROM rule_label WHERE state = 'ai_approved'")
        .fetchone()[0]
        == 2
    )
    again = world.post(url, json=body, headers=h("u_admin"))
    assert again.json() == ok.json()  # idempotent
