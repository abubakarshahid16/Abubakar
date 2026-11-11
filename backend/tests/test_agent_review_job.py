"""The AI reviewer's job, end to end, with an INVENTED paper, rule book and model (no network, no real text).

The kind reader, the classic selection and the item builder are replaced by fixed answers (each has its own tests); what is
under test here is the job: the one switch, the tables, the runner's gate and exit, resume, caps, the CRS copies and the
no-text-in-logs rule.
"""

from __future__ import annotations

import json
import logging

import pytest
from openpyxl import load_workbook

from app import (
    agent_review_gate,
    agent_review_jobs,
    agent_review_kind,
    agent_review_schema,
    claude_approved,
    db,
    nothing_read,
    worker_review,
)
from app import agent_review_items as items_mod
from tests import agent_review_support as s


def reading(kind="datasheet", known=True):
    return agent_review_kind.PaperReading(kind, known, "read by code", "title", False, None, None)


@pytest.fixture
def world(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    fake = s.FakeModel()
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading())
    monkeypatch.setattr(agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id)
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    doc, cache = s.item_doc()

    def build(_conn, _paper, _kind, *, cache=None, **_kw):
        cache.update(_CACHE)
        return _DOC

    global _DOC, _CACHE
    _DOC, _CACHE = doc, cache
    monkeypatch.setattr(items_mod, "build_items", build)
    with db.connect() as conn:
        s.label_rows(conn, [i["item_id"] for i in doc["items"]])
    return fake


_DOC: dict = {}
_CACHE: dict = {}


def start(paper=s.PAPER):
    run_id, job_id = agent_review_jobs.enqueue(paper, allowed_document_ids=frozenset({paper}), requested_by=None)
    claimed = agent_review_jobs.claim_next("w-test")
    assert claimed == job_id
    return run_id, job_id


def run_job(job_id):
    return agent_review_jobs.run(job_id, "w-test")


def lines_of(run_id):
    rows = db.connect().execute("SELECT * FROM agent_review_line WHERE run_id = ?", (run_id,)).fetchall()
    return {r["item_id"]: dict(r) for r in rows}


def test_a_full_fake_model_review_writes_lines_both_copies_and_the_record(world):
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    lines = lines_of(run_id)
    assert {k: (v["verdict_class"], v["word"]) for k, v in lines.items()} == {
        "R-coat": ("Proven by code", "Pass"),
        "R-frame": ("Proven by code", "Pass"),
        "R-mark": ("Proven by code", "Fail"),
        "R-colour": ("Not reviewed", "Not reviewed"),
    }
    assert lines["R-colour"]["reason"] == "not reviewed: no answer from the AI"
    assert lines["R-mark"]["rule_tier"] == "AI approved"
    run = dict(db.connect().execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)).fetchone())
    assert (run["paper_kind"], run["partial"], run["stop_reason"], run["rule_set_changed_by"]) == ("datasheet", 0, None, None)
    assert run["usd"] > 0 and "fake-second-model-2" in run["models_json"]
    folder = agent_review_jobs.run_dir(run_id)
    internal, contractor = load_workbook(folder / "crs-internal.xlsx"), load_workbook(folder / "crs-contractor.xlsx")
    assert internal.sheetnames and contractor.sheetnames
    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().splitlines()]
    assert {t["type"] for t in trace} >= {"prompt", "batch", "item"}
    status = db.connect().execute("SELECT status FROM review_runs WHERE id = ?", (run_id,)).fetchone()["status"]
    assert status == "completed"


def test_the_contractor_copy_holds_the_proven_fail_only(world):
    run_id, job_id = start()
    run_job(job_id)
    ws = load_workbook(agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx").active
    text = "\n".join(" | ".join(str(c) for c in row if c is not None) for row in ws.iter_rows(values_only=True))
    assert "red" in text or "marking" in text.lower() or "Marking" in text
    for pass_word in ("Coating layers two", "Frame width 45 mm"):
        assert pass_word not in text  # a Pass never reaches the contractor


def test_a_pass_or_fail_needs_the_second_model_to_agree(world, monkeypatch):
    fake = s.FakeModel(agree=False)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    lines = lines_of(run_id)
    assert lines["R-coat"]["word"] == "AI thinks: met" and lines["R-coat"]["verdict_class"] == "AI opinion, engineer to confirm"
    assert lines["R-mark"]["word"] == "AI thinks: not met"
    assert lines["R-frame"]["word"] == "Pass"  # a number line is decided by code, not by the second opinion
    assert not [r for r in lines.values() if r["word"] in ("Pass", "Fail") and r["verdict_class"] != "Proven by code"]


def test_a_rule_whose_tier_is_not_approved_now_never_becomes_pass_or_fail_and_buys_no_call(world):
    with db.connect() as conn:
        conn.execute("DELETE FROM rule_label WHERE rule_ref IN ('req-R-coat', 'req-R-mark')") if False else None
        # the label table is the CURRENT tier: take the approval away from two rules (a person declined, the table says so)
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute("DELETE FROM rule_label WHERE rule_ref IN ('req-R-coat', 'req-R-mark')")
        conn.commit()
    fake = world
    run_id, job_id = start()
    run_job(job_id)
    lines = lines_of(run_id)
    for iid in ("R-coat", "R-mark"):
        assert lines[iid]["word"] not in ("Pass", "Fail")
        assert lines[iid]["rule_tier"] == "Not AI approved"
        assert lines[iid]["verdict_class"] == "AI opinion, rule not yet approved"
    assert fake.kinds.count("second") == 0 and fake.kinds.count("context") == 0  # nothing bought for them
    ws = load_workbook(agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx").active
    assert "Marking blue" not in str([r for r in ws.iter_rows(values_only=True)])


def test_a_cut_off_answer_is_asked_again_per_half_and_what_stays_unanswered_is_not_reviewed(world, monkeypatch):
    fake = s.FakeModel(cut_first=True)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    first, halves = fake.lead_asked[0], fake.lead_asked[1:3]
    assert len(first) == 4 and [len(h) for h in halves] == [2, 2]
    assert sorted(first) == sorted(halves[0] + halves[1])
    lines = lines_of(run_id)
    assert lines["R-colour"]["word"] == "Not reviewed"  # never a Query about the paper
    assert lines["R-coat"]["word"] == "Pass"


def test_an_unknown_paper_kind_asks_nothing_and_the_run_says_so(world, monkeypatch):
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading(kind="unknown", known=False))
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    assert world.lead_asked == [] and lines_of(run_id) == {}
    run = dict(db.connect().execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)).fetchone())
    assert run["paper_kind"] == "unknown" and run["stop_reason"].startswith("paper_kind_unknown")


@pytest.mark.parametrize("kind", ["procedure", "contract", "drawing", "calculation", "other"])
def test_a_kind_the_reviewer_is_not_enabled_for_asks_nothing_even_inside_the_job(world, monkeypatch, kind):
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading(kind=kind))
    run_id, job_id = start()
    run_job(job_id)
    assert world.lead_asked == [] and lines_of(run_id) == {}
    run = dict(db.connect().execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)).fetchone())
    assert run["stop_reason"].startswith("kind_not_enabled")


def test_a_cap_stop_writes_a_partial_run_with_the_reason(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    run = dict(db.connect().execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)).fetchone())
    assert run["partial"] == 1 and run["stop_reason"].startswith("app_step_cap")
    assert world.lead_asked == []  # nothing was sent: the cap refused before the call
    assert {v["word"] for v in lines_of(run_id).values()} == {"Not reviewed"}


def test_a_restart_asks_only_the_items_without_a_line(world, monkeypatch):
    run_id, job_id = start()
    run_job(job_id)
    first_calls = len(world.lead_asked)
    # the process died after the first pass: the job is claimed again and resumes from the stored lines
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET state = 'running', claimed_by = 'w-test' WHERE id = ?", (job_id,))
        conn.execute("UPDATE review_runs SET status = 'running' WHERE id = ?", (run_id,))
    before = lines_of(run_id)
    run_job(job_id)
    asked_again = [i for batch in world.lead_asked[first_calls:] for i in batch]
    assert set(asked_again) == {"R-colour"}  # only the item that had no answer; the three decided lines are kept
    after = lines_of(run_id)
    for iid in ("R-coat", "R-frame", "R-mark"):
        assert after[iid]["line_json"] == before[iid]["line_json"]


def test_a_stored_pass_of_a_rule_no_longer_approved_is_capped_on_resume(world):
    run_id, job_id = start()
    run_job(job_id)
    with db.connect() as conn:
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute("DELETE FROM rule_label WHERE rule_ref = 'req-R-coat'")
        conn.execute("UPDATE jobs SET state = 'running', claimed_by = 'w-test' WHERE id = ?", (job_id,))
        conn.execute("UPDATE review_runs SET status = 'running' WHERE id = ?", (run_id,))
    run_job(job_id)
    line = lines_of(run_id)["R-coat"]
    assert line["word"] not in ("Pass", "Fail") and line["rule_tier"] == "Not AI approved"


def test_no_paper_or_rule_book_text_reaches_a_log(world, caplog):
    caplog.set_level(logging.DEBUG)
    run_id, job_id = start()
    run_job(job_id)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("Coating layers two", "Frame width 45 mm", "Marking blue", "marking shall be in red", "INV-STD-100", "frame width"):
        assert secret not in logged, secret
    assert run_id not in "" and "agent review" in logged  # the run did log, with counts and codes only


def test_the_switch_off_claims_no_job_creates_no_table_and_refuses_to_enqueue(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch, on=False)
    assert agent_review_schema.has_tables(db.connect()) is False
    agent_review_schema.ensure_schema()
    assert agent_review_schema.has_tables(db.connect()) is False
    with pytest.raises(agent_review_gate.FeatureOff):
        agent_review_jobs.enqueue(s.PAPER, allowed_document_ids=frozenset({s.PAPER}), requested_by=None)
    assert agent_review_jobs.claim_next("w") is None and agent_review_jobs.recover_stale() == 0
    # a queued agent job already in the table stays queued, unclaimed
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at, priority) VALUES"
            " ('j1', ?, 'agent_review', 'queued', 'x', 'x', 0)", (s.PAPER,))
    assert agent_review_jobs.claim_next("w") is None
    assert db.connect().execute("SELECT state FROM jobs WHERE id = 'j1'").fetchone()["state"] == "queued"


def test_the_worker_claims_a_classic_job_first_and_leaves_the_classic_path_alone(world, monkeypatch):
    calls = []
    from app import review_jobs

    monkeypatch.setattr(review_jobs, "recover_stale", lambda: 0)
    monkeypatch.setattr(review_jobs, "claim_next", lambda _w: calls.append("classic") or "job-classic")
    monkeypatch.setattr(review_jobs, "run", lambda *_a, **_k: calls.append("classic-run") or "done")
    monkeypatch.setattr(agent_review_jobs, "claim_next", lambda _w: calls.append("agent") or None)

    class W(worker_review.ReviewDrain):
        last_beat = last_progress = 0.0
        alive = True
        _thread = None
        last_error = None

    assert W()._drain_review_jobs() is True
    assert calls == ["classic", "classic-run"]  # the agent stage is not even asked while a classic job is waiting


def test_the_approved_list_still_applies_an_unapproved_document_stops_the_run_with_a_code(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(claude_approved, "approved_hashes", lambda: frozenset())
    run_id, job_id = start()
    run_job(job_id)
    run = dict(db.connect().execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)).fetchone())
    assert run["partial"] == 1 and "not_approved" in run["stop_reason"]
    assert world.lead_asked == []  # nothing was sent
