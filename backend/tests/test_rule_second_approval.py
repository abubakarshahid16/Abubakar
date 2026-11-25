"""The second-model approval pass over needs_human rules, its blind sample judge and the measured gate (planner, 25 Nov 2026,
item A). Invented rules, fake senders, a database COPY; no network, no paid call."""

from __future__ import annotations

import sqlite3

import pytest

from app import rule_second_approval as RS
from app.agent_claude import reset_shared_meter_for_tests
from app.aim_review import library
from app.config import settings
from tests import rule_label_support as s
from tests.test_rule_label_job import run, states

THIRD, JUDGE = "claude-haiku-5-5", "claude-fable-5-2"


@pytest.fixture(autouse=True)
def _world(tmp_path, monkeypatch):
    reset_shared_meter_for_tests()
    s.switch(monkeypatch)
    s.patch_pages(monkeypatch)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setattr(settings, "db_path", settings.db_path)  # the runner points it at its copy: restored after each test
    yield
    reset_shared_meter_for_tests()


def _comparator_differs(rule):
    a = s.FakeModel.good(rule)
    if "10 bar" in rule["quote"]:
        a.update(
            comparator="ge"
        )  # the same number, another comparator: a reading difference
    return a


@pytest.fixture
def copy(tmp_path):
    """r1: the two label passes read the comparator differently (needs_human); r2: they agreed (ai_approved)."""
    path = s.make_db(tmp_path / "copy.sqlite")
    with sqlite3.connect(str(path)) as c:  # the column the review's rule pool reads
        c.execute("ALTER TABLE standard_requirements ADD COLUMN requirement_text TEXT")
    run(path, "a", s.MODEL_A, s.FakeModel())
    conn, _c, _l = run(path, "b", s.MODEL_B, s.FakeModel(_comparator_differs))
    assert states(conn) == {"r1": "needs_human", "r2": "ai_approved"}
    return path


def _second(path, fake, model=THIRD):
    from app import rule_label_job as job

    conn = job.open_copy(path)
    rules = job.select_rules(conn, books=[s.STANDARD])
    ledger = job.CapLedger(5.0)
    counts = RS.run_second(conn, rules, model=model, lane=job.Lane(ledger, send=fake, env=s.ENV, retry_base=0),
                           out=lambda _m: None)  # fmt: skip
    return conn, counts, rules


def test_a_third_model_that_agrees_with_one_pass_approves_and_stores_approver_model_and_date(
    copy,
):
    fake = s.FakeModel()
    conn, counts, _r = _second(copy, fake)
    assert (
        counts["sent"] == 1
        and counts["not_needs_human"] == 1
        and counts["state:second_approved"] == 1
    )
    row = conn.execute(
        "SELECT * FROM rule_second_approval WHERE rule_ref = 'r1'"
    ).fetchone()
    assert (
        row["state"] == RS.APPROVED
        and row["approver"] == RS.APPROVER
        and row["model"] == THIRD
    )
    assert (
        row["agrees_with"] == "a"
        and row["approved_at"]
        and row["quote_page"] == 1
        and len(row["quote_sha256"]) == 64
    )
    sent = fake.bodies[0]["messages"][0]["content"][0]["text"]
    assert (
        "ge" not in sent and s.MODEL_A not in sent and "needs_human" not in sent
    )  # rule-book text only, blind


def test_a_third_model_that_agrees_with_neither_pass_is_refused_with_the_reasons(copy):
    def third(rule):
        a = s.FakeModel.good(rule)
        a.update(comparator="lt")
        return a

    conn, _counts, _r = _second(copy, s.FakeModel(third))
    row = conn.execute(
        "SELECT state, refused_because, agrees_with FROM rule_second_approval WHERE rule_ref = 'r1'"
    ).fetchone()
    assert row[0] == RS.REFUSED and "a:" in row[1] and "b:" in row[1] and row[2] is None


def test_a_model_of_a_label_pass_family_is_refused_before_anything_is_sent(copy):
    fake = s.FakeModel()
    with pytest.raises(ValueError):
        _second(copy, fake, model="claude-sonnet-5-5-20261101")
    assert fake.calls == 0


def test_a_guard_disagreement_stays_with_a_person(copy):
    from app import rule_label_job as job

    conn = job.open_copy(copy)
    conn.execute(
        "UPDATE rule_label SET disagreement = 'ocr_low_confidence' WHERE rule_ref = 'r1'"
    )
    conn.commit()
    conn.close()
    fake = s.FakeModel()
    _conn, counts, _r = _second(copy, fake)
    assert fake.calls == 0 and counts["a_guard_not_a_reading"] == 1


def test_rows_are_never_deleted_or_changed(copy):
    conn, _c, _r = _second(copy, s.FakeModel())
    for sql in (
        "DELETE FROM rule_second_approval",
        "UPDATE rule_second_approval SET model = 'x'",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)


def _judge(verdict):
    return s.RawModel(
        lambda rules: [
            {"n": r["n"], "verdict": verdict, "reason": "invented"} for r in rules
        ]
    )


def test_the_blind_sample_judge_measures_wrong_of_judged_and_the_gate_needs_both_numbers(
    copy, monkeypatch
):
    conn, _c, rules = _second(copy, s.FakeModel())
    from app import rule_label_job as job

    sample = RS.draw_sample(conn, n=5, seed=7)
    fake = _judge("right")
    got = RS.judge_sample(conn, sample, judge_model=JUDGE, lane=job.Lane(job.CapLedger(5.0), send=fake, env=s.ENV, retry_base=0),
                          rules={r.ref: r for r in rules})  # fmt: skip
    seen = fake.bodies[0]["messages"][0]["content"][0]["text"]
    assert (
        got == {"right": 1} and THIRD not in seen and "agrees_with" not in seen
    )  # blind: not who approved it or why
    assert RS.gate(conn)["sentence"] == "Second-model approvals: not measured."
    m = RS.measure(conn, sample)
    assert (m["judged"], m["wrong"]) == (1, 0)
    g = RS.gate(conn)
    assert (
        not g["open"] and "0 wrong of 1 judged (0.0%)" in g["sentence"]
    )  # too few judged
    monkeypatch.setattr(RS, "GATE_MIN_JUDGED", 1)
    assert RS.gate(conn)["open"]
    with pytest.raises(
        ValueError
    ):  # the judge's family is none of the approving models'
        RS.judge_sample(conn, sample, judge_model=THIRD, lane=None, rules={})


def test_reviews_use_a_second_model_approval_only_behind_the_open_gate(
    copy, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "aim_u8_enabled", True)  # its update's switch (`aim_review.updates`)
    conn, _c, rules = _second(copy, s.FakeModel())
    pool = lambda: {r["id"] for r in library.rule_pool(conn, "datasheet", None)}  # noqa: E731
    assert (
        pool() == set()
    )  # r2 is a contract rule; r1 is second-approved but the gate has no measure
    from app import rule_label_job as job

    sample = RS.draw_sample(conn, n=5, seed=3)
    RS.judge_sample(conn, sample, judge_model=JUDGE, lane=job.Lane(job.CapLedger(5.0), send=_judge("right"), env=s.ENV,
                    retry_base=0), rules={r.ref: r for r in rules})  # fmt: skip
    RS.measure(conn, sample)
    assert pool() == set()  # 1 judged is below the minimum
    monkeypatch.setattr(RS, "GATE_MIN_JUDGED", 1)
    got = {r["id"]: r for r in library.rule_pool(conn, "datasheet", None)}
    assert set(got) == {"r1"} and '"comparator": "le"' in got["r1"]["reading_json"]
    sample2 = RS.draw_sample(conn, n=5, seed=4)
    RS.judge_sample(conn, sample2, judge_model=JUDGE, lane=job.Lane(job.CapLedger(5.0), send=_judge("wrong"), env=s.ENV,
                    retry_base=0), rules={r.ref: r for r in rules})  # fmt: skip
    RS.measure(conn, sample2)
    assert pool() == set()  # the latest measure: 1 wrong of 1 -> closed again


def _script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "run_rule_second.py"
    spec = importlib.util.spec_from_file_location("A_run_rule_second", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_run_refuses_more_than_the_first_batch_or_all_rules_before_a_measure(copy, monkeypatch, capsys):
    """Owner, 25 Nov 2026 (#1584 comment 7169525003): start with 2,000 rules and report the error rate before the rest."""
    from app import rule_label_job as job

    script = _script()
    sent = []
    monkeypatch.setattr(job, "Lane", lambda *a, **k: sent.append(1))  # any lane built would be a paid start
    for limit in (0, RS.FIRST_BATCH + 1):
        assert script.main(["run", "--db", str(copy), "--max-usd", "1", "--limit", str(limit)]) == 2
        assert "first batch is 2,000 rules; judge a sample and report the error rate first" in capsys.readouterr().out
    assert sent == []
    conn = job.open_copy(copy)
    RS.create(conn)  # a measure below the minimum does not open the rest either
    conn.execute("INSERT INTO rule_second_measure (sample_id, measured_at, covers_until, judged, wrong, judge_model)"
                 " VALUES ('s1', '2026-11-25', '2026-11-25', ?, 0, ?)", (RS.GATE_MIN_JUDGED - 1, JUDGE))  # fmt: skip
    conn.commit()
    assert RS.batch_refusal(conn, 0) and RS.batch_refusal(conn, RS.FIRST_BATCH + 1)
    assert RS.batch_refusal(conn, RS.FIRST_BATCH) is None and RS.batch_refusal(conn, 1) is None


def test_the_rest_may_run_once_a_measure_judged_enough_approvals(copy):
    from app import rule_label_job as job

    conn, _c, rules = _second(copy, s.FakeModel())
    sample = RS.draw_sample(conn, n=5, seed=7)
    RS.judge_sample(conn, sample, judge_model=JUDGE, lane=job.Lane(job.CapLedger(5.0), send=_judge("right"), env=s.ENV,
                    retry_base=0), rules={r.ref: r for r in rules})  # fmt: skip
    RS.measure(conn, sample)
    assert RS.batch_refusal(conn, 0)  # 1 judged: still the first batch only
    conn.execute("INSERT INTO rule_second_measure (sample_id, measured_at, covers_until, judged, wrong, judge_model)"
                 " VALUES (?, '2026-11-25', '2026-11-25', ?, 3, ?)", (sample, RS.GATE_MIN_JUDGED, JUDGE))  # fmt: skip
    conn.commit()
    assert RS.batch_refusal(conn, 0) is None and RS.batch_refusal(conn, RS.FIRST_BATCH + 1) is None


def test_the_runner_points_the_apps_gate_at_the_copy_it_sends_from(copy, monkeypatch):
    """Review u8 B2: the runner never set `settings.db_path`, so the gate's block check read another database (by default
    the live one) than the copy whose rule text is sent. It now points every helper at the copy, as the label runner does."""
    from app import claude_approved
    from app import rule_label_job as job

    script, fake, seen = _script(), s.FakeModel(), []
    real_lane, real_block = job.Lane, claude_approved._block_stop
    monkeypatch.setattr(job, "Lane", lambda ledger: real_lane(ledger, send=fake, env=s.ENV, retry_base=0))

    def block_seen(ids):
        seen.append(str(settings.db_path))
        return real_block(ids)

    monkeypatch.setattr(claude_approved, "_block_stop", block_seen)
    assert script.main(["run", "--db", str(copy), "--max-usd", "1", "--limit", "5", "--model", THIRD]) == 0
    assert settings.db_path == copy.resolve() and seen and set(seen) == {str(copy.resolve())}
    assert fake.calls == 1 and job.open_copy(copy).execute(
        "SELECT state FROM rule_second_approval WHERE rule_ref = 'r1'").fetchone()[0] == RS.APPROVED  # fmt: skip
