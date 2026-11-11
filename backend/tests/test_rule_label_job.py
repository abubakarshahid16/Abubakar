"""The rule-label job (owner decision 1): two different models, code decides, a COPY only. Fake sender, no network."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import claude_spend
from app import rule_label_job as job
from app import rule_label_schema as schema
from app import rule_labels as rl
from app.agent_claude import reset_shared_meter_for_tests
from app.config import settings
from tests import rule_label_support as s


@pytest.fixture(autouse=True)
def _world(tmp_path, monkeypatch):
    reset_shared_meter_for_tests()
    s.switch(monkeypatch)
    s.patch_pages(monkeypatch)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    yield
    reset_shared_meter_for_tests()


@pytest.fixture
def copy(tmp_path):
    path = s.make_db(tmp_path / "copy.sqlite", with_book=True)
    return path


def run(path, pass_, model, fake, *, rules=None, usd=5.0, **kw):
    conn = job.open_copy(path)
    rules = rules if rules is not None else job.select_rules(conn, books=[s.STANDARD])
    ledger = job.CapLedger(usd)
    counts = job.run_pass(
        conn,
        rules,
        pass_=pass_,
        model=model,
        lane=job.Lane(ledger, send=fake, env=s.ENV, retry_base=0),
        out=lambda _m: None,
        **kw,
    )
    return conn, counts, ledger


def states(conn):
    return {
        r["rule_ref"]: r["state"]
        for r in conn.execute("SELECT rule_ref, state FROM rule_label")
    }


def both_passes(path, fake_a=None, fake_b=None, **kw):
    run(path, "a", s.MODEL_A, fake_a or s.FakeModel())
    return run(path, "b", s.MODEL_B, fake_b or s.FakeModel(), **kw)


# ---------------------------------------------------------------- the two passes


def test_two_different_models_that_agree_approve_both_rules(copy):
    conn, counts, ledger = both_passes(copy)
    assert states(conn) == {"r1": "ai_approved", "r2": "ai_approved"}
    row = conn.execute("SELECT * FROM rule_label WHERE rule_ref = 'r1'").fetchone()
    assert (row["a_model"], row["b_model"], row["a_prompt"], row["b_prompt"]) == (
        s.MODEL_A,
        s.MODEL_B,
        rl.PROMPT_VERSION,
        rl.PROMPT_VERSION,
    )
    assert (
        row["quote_sha256"] == rl.quote_hash(s.QUOTE_NUM)
        and row["quote_page"] == 1
        and row["quote_recovery"] is None
    )
    assert (
        row["paper_kind"] == "datasheet"
        and row["field"] == s.FIELD()
        and json.loads(row["reading_json"])["values"] == [10.0]
    )
    assert ledger.run_usd > 0 and counts["state:ai_approved"] == 2


def test_the_prompt_carries_rule_book_text_only(copy):
    fake = s.FakeModel()
    run(copy, "a", s.MODEL_A, fake)
    body = json.dumps(fake.bodies[0])
    assert s.QUOTE_NUM in body and "4.1" in body
    sent = json.loads(fake.bodies[0]["messages"][0]["content"][0]["text"])
    assert set(sent) == {"rules"} and all(
        set(r) == {"n", "clause", "quote"} for r in sent["rules"]
    )


def test_a_disagreement_between_the_two_models_goes_to_a_human(copy):
    def other(rule):
        a = s.FakeModel.good(rule)
        if "10 bar" in rule["quote"]:
            a.update(
                values=[12], comparator="ge"
            )  # a number the quote does not hold, and another comparator
        return a

    conn, _c, _l = both_passes(copy, fake_b=s.FakeModel(other))
    assert states(conn)["r1"] == "needs_human" and states(conn)["r2"] == "ai_approved"
    assert (
        "invalid_reading"
        in conn.execute(
            "SELECT disagreement FROM rule_label WHERE rule_ref='r1'"
        ).fetchone()[0]
    )


def test_two_models_that_read_the_kind_differently_go_to_a_human(copy):
    def other(rule):
        a = s.FakeModel.good(rule)
        if "10 bar" in rule["quote"]:
            a.update(paper_kind="procedure", field=None)
        return a

    conn, _c, _l = both_passes(copy, fake_b=s.FakeModel(other))
    assert states(conn)["r1"] == "needs_human"
    assert conn.execute(
        "SELECT disagreement, paper_kind FROM rule_label WHERE rule_ref='r1'"
    ).fetchone()[:] == ("kind", None)


def test_a_quote_not_on_the_page_is_never_sent_and_is_quote_not_found(
    copy, monkeypatch
):
    s.patch_pages(monkeypatch, pages={1: "A page without either invented rule in it."})
    fake = s.FakeModel()
    conn, counts, _l = run(copy, "a", s.MODEL_A, fake)
    assert fake.calls == 0 and counts["quote_not_found"] == 2
    assert states(conn) == {"r1": "quote_not_found", "r2": "quote_not_found"}


def test_two_empty_readings_cannot_approve_a_numeric_rule(copy):
    def bare(rule):
        a = s.FakeModel.good(rule)
        if "10 bar" in rule["quote"]:
            a.update(comparator="statement", values=[], unit=None)
        return a

    conn, _c, _l = both_passes(copy, fake_a=s.FakeModel(bare), fake_b=s.FakeModel(bare))
    assert states(conn) == {"r1": "needs_human", "r2": "ai_approved"}
    assert (
        "numbers_unread"
        in conn.execute(
            "SELECT disagreement FROM rule_label WHERE rule_ref='r1'"
        ).fetchone()[0]
    )


def test_a_garbled_ocr_page_never_approves(copy, monkeypatch):
    s.patch_pages(
        monkeypatch, origin={1: {"page_source": "recognised", "page_min_conf": 0.1}}
    )
    conn, _c, _l = both_passes(copy)
    assert set(states(conn).values()) == {"needs_human"}
    assert (
        "ocr_low_confidence"
        in conn.execute(
            "SELECT disagreement FROM rule_label WHERE rule_ref='r1'"
        ).fetchone()[0]
    )


def test_the_same_model_twice_is_refused_before_anything_is_sent(copy):
    run(copy, "a", s.MODEL_A, s.FakeModel())
    fake = s.FakeModel()
    with pytest.raises(job.LabelError):
        run(copy, "b", "claude-sonnet-5-5-20261101", fake)
    assert fake.calls == 0


def test_an_answer_from_pass_as_model_is_never_stored_as_pass_b(copy):
    run(copy, "a", s.MODEL_A, s.FakeModel())
    conn, counts, _l = run(
        copy, "b", s.MODEL_B, s.FakeModel(model_id=s.MODEL_A)
    )  # the API answered with pass a's model
    assert (
        set(states(conn).values()) == {"labelled_a"}
        and counts["unlabelled_same_model_answered"] == 2
    )


def test_an_answer_attached_to_the_wrong_rule_is_dropped(copy):
    def swapped(rule):
        a = s.FakeModel.good(rule)
        a["start"] = "some other words"  # the echo does not match THIS rule's quote
        return a

    conn, counts, _l = run(copy, "a", s.MODEL_A, s.FakeModel(swapped))
    assert states(conn) == {} and counts["unlabelled_unreadable_or_wrong_rule"] == 2


def test_rows_from_a_pass_under_another_prompt_version_are_not_asked_again_in_pass_b(
    copy,
):
    run(copy, "a", s.MODEL_A, s.FakeModel())
    conn = sqlite3.connect(str(copy))
    conn.execute("UPDATE rule_label SET a_prompt = 'rule-label-v2'")
    conn.commit()
    fake = s.FakeModel()
    _c, counts, _l = run(copy, "b", s.MODEL_B, fake)
    assert fake.calls == 0 and counts["not_asked_pass_a_not_current"] == 2
    assert set(states(job.open_copy(copy)).values()) == {"labelled_a"}


def test_pass_b_does_not_ask_a_rule_whose_quote_changed_since_pass_a(copy):
    run(copy, "a", s.MODEL_A, s.FakeModel())
    conn = sqlite3.connect(str(copy))
    conn.execute(
        "UPDATE standard_requirements SET source_text = source_text || ' Changed.' WHERE id = 'r1'"
    )
    conn.commit()
    fake = s.FakeModel()
    _c, counts, _l = run(copy, "b", s.MODEL_B, fake)
    assert (
        counts["not_asked_quote_changed"] == 1
        and states(job.open_copy(copy))["r1"] == "labelled_a"
    )


def test_a_standard_of_a_family_the_owner_did_not_open_is_never_sent(tmp_path):
    path = s.make_db(tmp_path / "other.sqlite", standard=s.OTHER_STANDARD)
    fake = s.FakeModel()
    conn = job.open_copy(path)
    rules = job.select_rules(conn, books=[s.OTHER_STANDARD])
    _c, counts, _l = run(path, "a", s.MODEL_A, fake, rules=rules)
    assert fake.calls == 0 and counts["not_sent_family_not_allowed"] == 2


# ---------------------------------------------------------------- money


def test_the_order_ledger_stops_the_run_before_a_call_is_sent(copy):
    fake = s.FakeModel()
    conn, counts, _l = run(copy, "a", s.MODEL_A, fake, usd=0.00001)
    assert (
        fake.calls == 0 and counts["stopped"] == "order_stop_usd" and states(conn) == {}
    )


def test_every_call_is_booked_on_the_injected_ledger(copy):
    class Spy(job.CapLedger):
        def __init__(self):
            super().__init__(5.0)
            self.reserved, self.settled = [], []

        def reserve(self, worst):
            self.reserved.append(worst)
            return super().reserve(worst)

        def settle(self, worst, **kw):
            self.settled.append(kw["usd"])
            super().settle(worst, **kw)

    conn = job.open_copy(copy)
    spy = Spy()
    fake = s.FakeModel()
    job.run_pass(
        conn,
        job.select_rules(conn, books=[s.STANDARD]),
        pass_="a",
        model=s.MODEL_A,
        lane=job.Lane(spy, send=fake, env=s.ENV),
        out=lambda _m: None,
    )
    assert fake.calls == len(spy.reserved) == len(spy.settled) == 1
    assert spy.settled[0] == pytest.approx(claude_spend.cost_usd(s.MODEL_A, s.USAGE))


def test_the_command_refuses_a_paid_pass_without_a_ledger(copy, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_rule_labels",
        Path(__file__).resolve().parents[2] / "scripts" / "run_rule_labels.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (
        mod.main(["run", "--pass", "a", "--db", str(copy), "--book", s.STANDARD]) == 1
    )
    assert "ledger" in capsys.readouterr().out


# ---------------------------------------------------------------- safety: a copy only, nothing existing written


def test_a_live_shaped_path_is_refused(tmp_path):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    sqlite3.connect(str(live)).close()
    with pytest.raises(job.LabelError):
        job.open_copy(live)
    with pytest.raises(job.LabelError):
        job.refuse_live(live.with_name("rag_intelligence.sqlite-wal"))
    # a connection that points at it is refused again by the run itself, whatever opened it
    conn = sqlite3.connect(str(live))
    with pytest.raises(job.LabelError):
        job.require_copy(conn)
    with pytest.raises(job.LabelError):
        job.run_pass(
            conn, [], pass_="a", model=s.MODEL_A, lane=job.Lane(job.CapLedger(1))
        )
    assert "rule_label" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master")
    }


def test_the_job_writes_only_its_own_tables(copy):
    before = sqlite3.connect(str(copy))
    names = {
        r[0]
        for r in before.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    held = {n: s.table_hash(before, n) for n in names}
    both_passes(copy)
    after = sqlite3.connect(str(copy))
    now = {
        r[0]
        for r in after.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert now - names == {
        "rule_label",
        "rule_label_event",
        "sqlite_sequence",
    } or now - names == {"rule_label", "rule_label_event"}
    assert {
        n: s.table_hash(after, n) for n in names
    } == held  # rulebook_approval and the rest: count and hash unchanged


def test_the_switch_off_refuses_the_job_and_makes_no_table(copy, monkeypatch):
    s.switch(monkeypatch, False)
    conn = job.open_copy(copy)
    rules = job.select_rules(conn, books=[s.STANDARD])
    with pytest.raises(schema.SwitchedOff):
        job.run_pass(
            conn,
            rules,
            pass_="a",
            model=s.MODEL_A,
            lane=job.Lane(job.CapLedger(1), send=s.FakeModel(), env=s.ENV),
        )
    assert "rule_label" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master")
    }


# ---------------------------------------------------------------- the export


def test_the_export_holds_hashes_and_ids_and_no_quote_text(copy, tmp_path):
    conn, _c, _l = both_passes(copy)
    out = tmp_path / "labels.json"
    assert job.write_export(conn, out) == 2
    text = out.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["format"] == "rule-labels-v1" and {
        r["state"] for r in data["rows"]
    } == {"ai_approved"}
    assert (
        s.QUOTE_NUM not in text
        and s.QUOTE_TXT not in text
        and "written statement" not in text
    )
    row = next(r for r in data["rows"] if r["rule_ref"] == "r1")
    assert (
        row["quote_sha256"] == rl.quote_hash(s.QUOTE_NUM)
        and row["a_model"] == s.MODEL_A
        and row["reading"]["values"] == [10.0]
    )
    assert "a_answer_json" not in row


def test_the_bridge_to_the_rule_book_is_stored_by_quote_and_page(copy):
    conn, _c, _l = both_passes(copy)
    assert (
        conn.execute(
            "SELECT rule_version_id FROM rule_label WHERE rule_ref = 'r1'"
        ).fetchone()[0]
        == "v1"
    )
    assert (
        conn.execute(
            "SELECT rule_version_id FROM rule_label WHERE rule_ref = 'r2'"
        ).fetchone()[0]
        is None
    )
