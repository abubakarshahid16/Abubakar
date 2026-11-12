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
from app import agent_review_verdict as V
from tests import agent_review_support as s


def reading(kind="datasheet", known=True):
    return agent_review_kind.PaperReading(
        kind, known, "read by code", "title", False, None, None
    )


@pytest.fixture
def world(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    fake = s.FakeModel()
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading())
    monkeypatch.setattr(
        agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id
    )
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
    run_id, job_id = agent_review_jobs.enqueue(
        paper, allowed_document_ids=frozenset({paper}), requested_by=None
    )
    claimed = agent_review_jobs.claim_next("w-test")
    assert claimed == job_id
    return run_id, job_id


def run_job(job_id):
    return agent_review_jobs.run(job_id, "w-test")


def lines_of(run_id):
    rows = (
        db.connect()
        .execute("SELECT * FROM agent_review_line WHERE run_id = ?", (run_id,))
        .fetchall()
    )
    return {r["item_id"]: dict(r) for r in rows}


def test_a_full_fake_model_review_writes_lines_both_copies_and_the_record(world):
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    lines = lines_of(run_id)
    assert {k: (v["verdict_class"], v["word"]) for k, v in lines.items()} == {
        "R-coat": (
            "AI verdict, two readers agree",
            "AI verdict: met",
        ),  # a Pass the code did not compare
        "R-frame": ("Proven by code", "Pass"),
        "R-mark": ("Proven by code", "Fail"),
        "R-colour": ("Not reviewed", "Not reviewed"),
    }
    assert lines["R-colour"]["reason"].startswith("no answer from the AI")
    assert lines["R-mark"]["rule_tier"] == "AI approved"
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (
        run["paper_kind"],
        run["partial"],
        run["stop_reason"],
        run["rule_set_changed_by"],
    ) == ("datasheet", 0, None, None)
    assert run["usd"] > 0 and "fake-second-model-2" in run["models_json"]
    folder = agent_review_jobs.run_dir(run_id)
    internal, contractor = (
        load_workbook(folder / "crs-internal.xlsx"),
        load_workbook(folder / "crs-contractor.xlsx"),
    )
    assert internal.sheetnames and contractor.sheetnames
    trace = [json.loads(x) for x in (folder / "trace.jsonl").read_text().splitlines()]
    assert {t["type"] for t in trace} >= {"prompt", "batch", "item"}
    status = (
        db.connect()
        .execute("SELECT status FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()["status"]
    )
    assert status == "completed"


def test_the_internal_copy_header_holds_the_documents_facts_and_the_notes_sheet_the_run_facts(
    world,
):
    """Order 13: the header block reads what the app holds for the paper (`document_classification`); the run id and the cost are
    on the Notes sheet only."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_classification (document_id, suggested_by, project, document_number, title,"
            " revision, effective_date, discipline) VALUES (?, 'test', 'Project Q', 'DOC-77', 'Title Z', 'B', '2026-01-05',"
            " 'instrument')",
            (s.PAPER,),
        )
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    wb = load_workbook(agent_review_jobs.run_dir(run_id) / "crs-internal.xlsx")
    top = {
        r[0]: r[2] for r in wb["CRS"].iter_rows(max_row=12, values_only=True) if r[0]
    }
    assert (top["Project:"], top["Document number:"], top["Document title:"]) == (
        "Project Q",
        "DOC-77",
        "Title Z",
    )
    assert (top["Revision:"], top["Date:"], top["Discipline:"]) == (
        "B",
        "2026-01-05",
        "instrument",
    )
    notes = {r[0]: r[1] for r in wb["Notes"].iter_rows(min_row=2, values_only=True)}
    usd = (
        db.connect()
        .execute("SELECT usd FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()["usd"]
    )
    assert notes["Run id"] == run_id and notes["Cost (USD)"] == usd
    assert run_id not in "\n".join(
        str(c)
        for row in wb["CRS"].iter_rows(values_only=True)
        for c in row
        if c is not None
    )
    assert {
        r[4] for r in wb["CRS"].iter_rows(min_row=13, values_only=True) if r[0]
    } == {"AI reviewer, instrument"}


def test_the_contractor_copy_holds_the_proven_fail_only(world):
    run_id, job_id = start()
    run_job(job_id)
    ws = load_workbook(agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx").active
    text = "\n".join(
        " | ".join(str(c) for c in row if c is not None)
        for row in ws.iter_rows(values_only=True)
    )
    assert "red" in text or "marking" in text.lower() or "Marking" in text
    for pass_word in ("Coating layers two", "Frame width 45 mm"):
        assert pass_word not in text  # a Pass never reaches the contractor


def test_a_pass_or_fail_needs_the_second_model_to_agree(world, monkeypatch):
    fake = s.FakeModel(agree=False)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    lines = lines_of(run_id)
    assert (  # N9: a "met" the second model disagreed on is a Query
        lines["R-coat"]["word"] == "Query"
        and lines["R-coat"]["verdict_class"] == "Query for the engineer"
    )
    assert lines["R-mark"]["word"] == "AI thinks: not met"
    assert (
        lines["R-frame"]["word"] == "Pass"
    )  # a number line is decided by code, not by the second opinion
    assert not [
        r
        for r in lines.values()
        if r["word"] in ("Pass", "Fail") and r["verdict_class"] != "Proven by code"
    ]


def test_a_rule_whose_tier_is_not_approved_now_never_becomes_pass_or_fail_and_buys_no_call(
    world,
):
    with db.connect() as conn:
        # the label table is the CURRENT tier: take the approval away from two rules (a person declined, the table says so)
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute(
            "DELETE FROM rule_label WHERE rule_ref IN ('req-R-coat', 'req-R-mark')"
        )
        conn.commit()
    fake = world
    run_id, job_id = start()
    run_job(job_id)
    lines = lines_of(run_id)
    for iid in ("R-coat", "R-mark"):
        assert lines[iid]["word"] not in ("Pass", "Fail")
        assert lines[iid]["rule_tier"] == "Not AI approved"
        assert lines[iid]["verdict_class"] == "AI opinion, rule not yet approved"
    assert (
        fake.kinds.count("second") == 0 and fake.kinds.count("context") == 0
    )  # nothing bought for them
    ws = load_workbook(agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx").active
    assert "Marking blue" not in str(list(ws.iter_rows(values_only=True)))


def test_a_cut_off_answer_is_asked_again_per_half_and_what_stays_unanswered_is_not_reviewed(
    world, monkeypatch
):
    fake = s.FakeModel(cut_first=True)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    first, halves = fake.lead_asked[0], fake.lead_asked[1:3]
    assert len(first) == 4 and [len(h) for h in halves] == [2, 2]
    assert sorted(first) == sorted(halves[0] + halves[1])
    lines = lines_of(run_id)
    assert lines["R-colour"]["word"] == "Not reviewed"  # never a Query about the paper
    assert lines["R-coat"]["word"] == "AI verdict: met"


def test_an_unknown_paper_kind_asks_nothing_and_the_run_says_so(world, monkeypatch):
    monkeypatch.setattr(
        agent_review_kind,
        "decide",
        lambda *_a, **_k: reading(kind="unknown", known=False),
    )
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    assert world.lead_asked == [] and lines_of(run_id) == {}
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert run["paper_kind"] == "unknown" and run["stop_reason"].startswith(
        "paper_kind_unknown"
    )


@pytest.mark.parametrize("kind", ["drawing", "calculation", "other"])
def test_a_kind_the_reviewer_is_not_enabled_for_asks_nothing_even_inside_the_job(
    world, monkeypatch, kind
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading(kind=kind)
    )
    run_id, job_id = start()
    run_job(job_id)
    assert world.lead_asked == [] and lines_of(run_id) == {}
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert run["stop_reason"].startswith("kind_not_enabled")


def test_a_cap_stop_writes_a_partial_run_with_the_reason(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    run_id, job_id = start()
    assert run_job(job_id) == "done"
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert run["partial"] == 1 and run["stop_reason"].startswith("app_step_cap")
    assert world.lead_asked == []  # nothing was sent: the cap refused before the call
    assert {v["word"] for v in lines_of(run_id).values()} == {"Not reviewed"}


def test_a_restart_asks_only_the_items_without_a_line(world, monkeypatch):
    run_id, job_id = start()
    run_job(job_id)
    first_calls = len(world.lead_asked)
    # the process died after the first pass: the job is claimed again and resumes from the stored lines
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET state = 'running', claimed_by = 'w-test' WHERE id = ?",
            (job_id,),
        )
        conn.execute(
            "UPDATE review_runs SET status = 'running' WHERE id = ?", (run_id,)
        )
    before = lines_of(run_id)
    run_job(job_id)
    asked_again = [i for batch in world.lead_asked[first_calls:] for i in batch]
    assert set(asked_again) == {
        "R-colour"
    }  # only the item that had no answer; the three decided lines are kept
    after = lines_of(run_id)
    for iid in ("R-coat", "R-frame", "R-mark"):
        assert after[iid]["line_json"] == before[iid]["line_json"]


def test_a_stored_pass_of_a_rule_no_longer_approved_is_capped_on_resume(world):
    run_id, job_id = start()
    run_job(job_id)
    with db.connect() as conn:
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute("DELETE FROM rule_label WHERE rule_ref = 'req-R-coat'")
        conn.execute(
            "UPDATE jobs SET state = 'running', claimed_by = 'w-test' WHERE id = ?",
            (job_id,),
        )
        conn.execute(
            "UPDATE review_runs SET status = 'running' WHERE id = ?", (run_id,)
        )
    run_job(job_id)
    line = lines_of(run_id)["R-coat"]
    assert (
        line["word"] not in ("Pass", "Fail") and line["rule_tier"] == "Not AI approved"
    )


def test_no_paper_or_rule_book_text_reaches_a_log(world, caplog):
    caplog.set_level(logging.DEBUG)
    _run_id, job_id = start()
    run_job(job_id)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (
        "Coating layers two",
        "Frame width 45 mm",
        "Marking blue",
        "marking shall be in red",
        "INV-STD-100",
        "frame width",
    ):
        assert secret not in logged, secret
    assert "agent review" in logged  # the run did log, with counts and codes only


def test_the_switch_off_claims_no_job_creates_no_table_and_refuses_to_enqueue(
    tmp_path, monkeypatch
):
    s.setup_world(tmp_path, monkeypatch, on=False)
    assert agent_review_schema.has_tables(db.connect()) is False
    agent_review_schema.ensure_schema()
    assert agent_review_schema.has_tables(db.connect()) is False
    with pytest.raises(agent_review_gate.FeatureOff):
        agent_review_jobs.enqueue(
            s.PAPER, allowed_document_ids=frozenset({s.PAPER}), requested_by=None
        )
    assert (
        agent_review_jobs.claim_next("w") is None
        and agent_review_jobs.recover_stale() == 0
    )
    # a queued agent job already in the table stays queued, unclaimed
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at, priority) VALUES"
            " ('j1', ?, 'agent_review', 'queued', 'x', 'x', 0)",
            (s.PAPER,),
        )
    assert agent_review_jobs.claim_next("w") is None
    assert (
        db.connect()
        .execute("SELECT state FROM jobs WHERE id = 'j1'")
        .fetchone()["state"]
        == "queued"
    )


def test_the_worker_claims_a_classic_job_first_and_leaves_the_classic_path_alone(
    world, monkeypatch
):
    calls = []
    from app import review_jobs

    monkeypatch.setattr(review_jobs, "recover_stale", lambda: 0)
    monkeypatch.setattr(
        review_jobs, "claim_next", lambda _w: calls.append("classic") or "job-classic"
    )
    monkeypatch.setattr(
        review_jobs, "run", lambda *_a, **_k: calls.append("classic-run") or "done"
    )
    monkeypatch.setattr(
        agent_review_jobs, "claim_next", lambda _w: calls.append("agent") or None
    )

    class W(worker_review.ReviewDrain):
        last_beat = last_progress = 0.0
        alive = True
        _thread = None
        last_error = None

    assert W()._drain_review_jobs() is True
    assert calls == [
        "classic",
        "classic-run",
    ]  # the agent stage is not even asked while a classic job is waiting


def test_the_approved_list_still_applies_an_unapproved_document_stops_the_run_with_a_code(
    world, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(claude_approved, "approved_hashes", lambda: frozenset())
    run_id, job_id = start()
    run_job(job_id)
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert run["partial"] == 1 and "not_approved" in run["stop_reason"]
    assert world.lead_asked == []  # nothing was sent


def _stored_json(run_id, item_id):
    return json.loads(
        db.connect()
        .execute(
            "SELECT line_json FROM agent_review_line WHERE run_id = ? AND item_id = ?",
            (run_id, item_id),
        )
        .fetchone()["line_json"]
    )


def test_a_not_mentioned_pass_is_stored_as_a_query_with_the_not_stated_reason(
    world, monkeypatch
):
    """N9, the whole chain: the lead says Pass but its own words say the paper does not mention the field -> the real gate
    sets its code -> `_line`/`_holds` store it -> the single exit -> the table. The stored line is a Query, never met."""
    absent = {
        **s.ANSWERS["R-coat"],
        "reasoning": "the coating layers are not mentioned on the sheet",
    }
    fake = s.FakeModel(answers={**s.ANSWERS, "R-coat": absent})
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    line = _stored_json(run_id, "R-coat")
    row = lines_of(run_id)["R-coat"]
    assert line["not_mentioned_hold"] is True and line["verdict"] == "Query"
    assert (row["word"], row["verdict_class"]) == ("Query", "Query for the engineer")
    assert row["reason"].startswith(V.NOT_STATED_WHY)
    assert "not confirmed: " in row["reason"]  # the first reader's words follow, marked


def test_a_disagreeing_second_reader_is_stored_as_a_query_with_the_disagreement_reason(
    world, monkeypatch
):
    """N9, the whole chain for a code set by the runner: the stubbed second reader disagrees."""
    monkeypatch.setattr(
        agent_review_jobs, "lane", lambda: (s.FakeModel(agree=False), s.ENV)
    )
    run_id, job_id = start()
    run_job(job_id)
    line, row = _stored_json(run_id, "R-coat"), lines_of(run_id)["R-coat"]
    assert line["second_opinion"]["agree"] is False and line["ai_verdict"] == "Pass"
    assert row["word"] == "Query"
    assert row["reason"].startswith("two AI readers disagree on this line")


WEAK = {
    **s.ANSWERS["R-coat"],
    "clause_quote": "applied in two layers",
}  # verified word for word in the clause, but too short to prove a Pass


def _run_with(monkeypatch, answers, agree):
    fake = s.FakeModel(answers={**s.ANSWERS, **answers}, agree=agree)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    return fake, run_id


def test_a_met_line_gets_one_extra_second_reader_call(world, monkeypatch):
    strong, _ = _run_with(monkeypatch, {}, True)
    weak, run_id = _run_with(monkeypatch, {"R-coat": WEAK}, True)
    line = _stored_json(run_id, "R-coat")
    assert (
        line["quotes_checked"]["both"] and not line["quotes_checked"]["clause_strong"]
    )
    assert line["second_opinion"] and line["second_opinion"]["agree"] is True
    # the weak line used to buy no second call; now it buys exactly the one the strong line always bought
    assert weak.kinds.count("second") == strong.kinds.count("second")


def test_a_weak_met_the_second_reader_disagrees_on_is_stored_as_a_query(
    world, monkeypatch
):
    _, run_id = _run_with(monkeypatch, {"R-coat": WEAK}, False)
    row = lines_of(run_id)["R-coat"]
    assert row["word"] == "Query" and row["reason"].startswith(V.DISAGREE_WHY)


def test_a_weak_met_stays_met_when_the_second_reader_agrees_or_gives_no_answer(
    world, monkeypatch
):
    for agree in (True, None):
        _, run_id = _run_with(monkeypatch, {"R-coat": WEAK}, agree)
        row = lines_of(run_id)["R-coat"]
        assert row["word"] == "AI thinks: met", agree
