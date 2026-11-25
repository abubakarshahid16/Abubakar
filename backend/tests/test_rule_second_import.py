"""The second-model approval file, copy -> the server's database (built like the label import): append-only, idempotent,
every approval checked against the live book, counts by family, a dry run, refused while a review runs. Invented rules,
fake senders; no network."""

from __future__ import annotations

import sqlite3

import pytest

from app import rule_label_job as job
from app import rule_second_approval as RS
from app import rule_second_import as RI
from tests import rule_label_support as s
from tests.rule_label_support import table_hash
from tests.test_rule_label_job import run
from tests.test_rule_second_approval import (
    JUDGE,
    _comparator_differs,
    _judge,
    _second,
    _world,  # noqa: F401 - the autouse fixture
)


def _labelled(path):
    s.make_db(path)
    with sqlite3.connect(str(path)) as c:
        c.execute("ALTER TABLE standard_requirements ADD COLUMN requirement_text TEXT")
    run(path, "a", s.MODEL_A, s.FakeModel())
    run(path, "b", s.MODEL_B, s.FakeModel(_comparator_differs))
    return path


@pytest.fixture
def exported(tmp_path, monkeypatch):
    """The copy's file after the pass, one judged sample and its measure."""
    conn, _c, rules = _second(_labelled(tmp_path / "copy.sqlite"), s.FakeModel())
    sample = RS.draw_sample(conn, n=5, seed=11)
    lane = job.Lane(job.CapLedger(5.0), send=_judge("right"), env=s.ENV, retry_base=0)
    RS.judge_sample(
        conn, sample, judge_model=JUDGE, lane=lane, rules={r.ref: r for r in rules}
    )
    RS.measure(conn, sample)
    return RS.export(conn)


@pytest.fixture
def live(tmp_path):
    return job.open_copy(_labelled(tmp_path / "live.sqlite"))


def test_a_dry_run_checks_and_counts_and_writes_nothing(exported, live):
    before = table_hash(live, "rule_label")
    got = RI.import_second(live, exported, dry_run=True)
    assert (
        got["would_add:second_approved"] == 1
        and got["rule_second_measure:would_add"] == 1
        and got["dry_run"]
    )
    assert got["by_family"] == {"SAES": {"would_add:second_approved": 1}}
    assert not RS.has_tables(live) and table_hash(live, "rule_label") == before


def test_the_import_adds_once_and_a_rerun_adds_nothing_and_rule_label_is_never_written(
    exported, live, monkeypatch
):
    before = table_hash(live, "rule_label")
    first = RI.import_second(live, exported)
    assert (
        first["added:second_approved"] == 1
        and first["rule_second_sample:added"] == 1
        and first["rule_second_measure:added"] == 1
    )
    again = RI.import_second(live, exported)
    assert (
        again["already_held"] == 1
        and again["rule_second_measure:already_held"] == 1
        and "added:second_approved" not in again
    )
    assert table_hash(live, "rule_label") == before
    monkeypatch.setattr(RS, "GATE_MIN_JUDGED", 1)
    assert RS.gate(live)[
        "open"
    ]  # the measure the copy made reaches the server with its approvals


def test_a_held_row_is_never_changed(exported, live):
    RI.import_second(live, exported)
    changed = {
        **exported,
        "approvals": [
            {**exported["approvals"][0], "model": "claude-haiku-5-5-20261201"}
        ],
    }
    got = RI.import_second(live, changed)
    assert got["conflict"] == 1
    assert (
        live.execute("SELECT model FROM rule_second_approval").fetchone()[0]
        == "claude-haiku-5-5"
    )


def test_an_approval_lands_only_on_the_live_books_own_quote_and_a_needs_human_label(
    exported, live, monkeypatch
):
    live.execute(
        "UPDATE standard_requirements SET source_text = 'The set pressure shall not exceed 12 bar.' WHERE id = 'r1'"
    )
    assert RI.import_second(live, exported, dry_run=True)["changed_quote"] == 1
    live.rollback()
    s.patch_pages(
        monkeypatch,
        pages={1: "A page of the invented book that no longer holds the rule."},
    )
    assert RI.import_second(live, exported, dry_run=True)["quote_not_on_page"] == 1
    tampered = {
        **exported,
        "approvals": [{**exported["approvals"][0], "answer_sha256": "0" * 64}],
    }
    assert RI.import_second(live, tampered, dry_run=True)["refused"] == 1


def test_the_import_waits_while_a_review_runs(exported, live):
    live.execute("CREATE TABLE jobs (id TEXT, review_run_id TEXT, state TEXT)")
    live.execute("INSERT INTO jobs VALUES ('j1', 'run1', 'running')")
    with pytest.raises(RI.ReviewRunning):
        RI.import_second(live, exported, dry_run=True)
    assert not RS.has_tables(live)


def test_a_file_of_another_format_is_refused(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text('{"format": "rule-labels-v1", "rows": []}')
    with pytest.raises(RI.NotASecondFile):
        RI.read_file(bad)
