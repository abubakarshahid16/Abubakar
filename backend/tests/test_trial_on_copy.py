"""scripts/trial_on_copy.py: the trial on a copy, with a STUBBED lane that returns invented answers (order 12, N3 part A).

The stub answers like the real lane would: proven Pass and Fail, a not-applicable answer, and a first answer that is cut off.
Invented paper, invented rule book, no network, no real text. The checks are proved to CATCH a defect (a wrong pair, an empty
plan, a Fail the code did not prove) as well as to pass a good run, so the tests hold whatever state the reviewer's own fixes
are in: they patch the one function under suspicion.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

from app import agent_review_items as items_mod
from app import (
    agent_review_jobs,
    agent_review_kind,
    db,
    nothing_read,
)
from app.config import settings
from tests import agent_review_support as s

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("trial_on_copy", REPO / "scripts" / "trial_on_copy.py")
trial = importlib.util.module_from_spec(_spec)
sys.modules["trial_on_copy"] = trial
_spec.loader.exec_module(trial)

SETTINGS_TOUCHED = (
    "data_dir upload_dir db_path claude_spend_log claude_cache_dir agent_review_enabled host auth_mode startup_warmup "
    "claude_auto_approve_reviews_enabled claude_approved_list_enforced reasoning_provider standards_reader_enabled "
    "standards_reader_allow_public_egress anthropic_api_key ollama_url claude_budget_usd_per_step claude_budget_usd_total"
).split()
NOT_APPLICABLE_ANSWER = {
    "paper_page": 1,
    "paper_quote": "",
    "clause_quote": s.RULES["R-colour"][0],
    "reasoning": "the clause is about housing paint, which this paper kind does not state",
    "comment": "none",
    "verdict": "Query",
    "reason_code": "not_applicable",
    "field_label": "Colour",
}


def reading():
    return agent_review_kind.PaperReading("datasheet", True, "read by code", "title", False, None, None)


def pair_fixed(line):
    """The contract's table as the fixed core gives it: the not-applicable line is class and word "Not applicable"."""
    cls, word = real_pair(line)
    return (cls, "Not applicable") if cls == "Not applicable" else (cls, word)


real_pair = agent_review_jobs.contract_class_and_word


@pytest.fixture
def world(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    for name in SETTINGS_TOUCHED:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    for env in ("REASONING_PROVIDER", "STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY", "AGENT_SKILLS_DIR"):
        monkeypatch.setenv(env, "x")
        monkeypatch.delenv(env)
    monkeypatch.setattr(trial, "BACKEND", tmp_path / "no-backend")  # no backend/.env beside the code
    monkeypatch.setattr(trial, "live_roots", lambda: [Path("/nonexistent-live-checkout")])
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading())
    monkeypatch.setattr(agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id)
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    doc, cache = s.item_doc()

    def build(_conn, _paper, _kind, *, cache=None, **_kw):
        cache.update(_CACHE["cache"])
        return _CACHE["doc"]

    _CACHE["doc"], _CACHE["cache"] = doc, cache
    monkeypatch.setattr(items_mod, "build_items", build)
    with db.connect() as conn:
        s.label_rows(conn, [i["item_id"] for i in doc["items"]])
    db.reset_connection()
    return tmp_path


_CACHE: dict = {}


def cfg_for(tmp_path, **over):
    base = {"data_dir": tmp_path, "document": s.PAPER, "lane": "open", "db": tmp_path / "agent.sqlite", "labels_dir": tmp_path / "no-labels", "timeout": 120.0, "max_usd": 2.0}
    base.update(over)
    return trial.TrialConfig(**base)


def stub(answers=None, **kw):
    answers = dict(s.ANSWERS if answers is None else answers)
    answers["R-colour"] = NOT_APPLICABLE_ANSWER
    fake = s.FakeModel(answers=answers, **kw)
    return lambda: (fake, s.ENV)


def by_name(checks):
    return {c.name: c for c in checks}


def failed(checks):
    return sorted(c.name for c in checks if not c.ok)


def test_a_good_run_with_a_not_applicable_answer_and_a_cut_off_answer_passes_every_check(world, monkeypatch):
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", pair_fixed)
    checks = trial.run_trial(cfg_for(world), lane=stub(cut_first=True), log=lambda _m: None)
    got = by_name(checks)
    assert failed(checks) == [], trial.table(checks)
    assert "asked 4" in got["rules asked > 0, or the plan says why none"].detail
    assert "proven Pass 2, proven Fail 1" in got["Pass/Fail only with code proof"].detail
    assert "4 line(s)" in got["route trace 200 for every line"].detail
    assert "standing approval" in " ".join(got) and got["standing approval: paper and asked rule books approved, register blocked"].ok
    assert got["spend under the cap and real answers"].ok


def test_a_wrong_class_word_pair_is_caught_by_the_table_the_lines_route_and_the_stored_rows(world, monkeypatch):
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", lambda line: ("Not applicable", "Query") if line.get("reason_code") == "not_applicable" else real_pair(line))
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    bad = failed(checks)
    assert "class/word table legal for every core line" in bad  # the grid reaches the same patched function
    assert "stored lines legal by the contract" in bad
    assert "route lines 200" in bad  # the very 500 of the live run
    assert "route summary 200" not in bad  # the rest of the routes still answer


def test_the_static_table_check_names_the_illegal_pair(monkeypatch):
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", lambda line: ("Not applicable", "Query"))
    check = trial.static_pair_check()
    assert not check.ok and '"Not applicable"+"Query"' in check.detail
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", pair_fixed)
    assert trial.static_pair_check().ok


def test_an_empty_plan_with_no_word_about_it_fails_and_a_stated_reason_passes(world, monkeypatch):
    quiet = {**_CACHE["doc"]["rule_labels"], "summary_lines": [], "missing_rule_books": [], "counts": {}}
    _CACHE["doc"] = {**_CACHE["doc"], "items": [], "counts": {"skill": 0, "rule": 0}, "rule_labels": quiet}
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    assert "rules asked > 0, or the plan says why none" in failed(checks)
    assert "empty plan" in by_name(checks)["rules asked > 0, or the plan says why none"].detail


def test_left_out_rules_with_a_reason_explain_an_empty_ask(world, monkeypatch):
    out = {"rule_version_id": "v-x", "rule_book": "INV-STD-100", "clause": "9.9", "reason": "needs_another_paper", "needs_paper_kind": "procedure", "standard_document_id": s.STD}
    doc, _cache = s.item_doc(ids=(), left_out=[out])
    doc["rule_labels"]["summary_lines"] = []
    _CACHE["doc"] = doc
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    got = by_name(checks)
    assert got["rules asked > 0, or the plan says why none"].ok and "left out 1" in got["rules asked > 0, or the plan says why none"].detail
    assert "asked 0, left out 1" in got["Rules used lists asked + left out, one reason each"].detail


def test_a_paper_the_standing_approval_leaves_out_is_caught(world, monkeypatch):
    from app import claude_auto_approve

    monkeypatch.setattr(claude_auto_approve, "on_agent_standards", lambda *_a, **_k: None)  # the gap this PR closes, put back
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    bad = by_name(checks)["standing approval: paper and asked rule books approved, register blocked"]
    assert not bad.ok and "not approved" in bad.detail


# ----------------------------------------------------------------------------------------- the single checks


def line(**over):
    base = {"quotes_checked": {"paper": True, "clause": True}, "decided_by": "decided by code", "compare": {"decided": "Pass"}, "tier": "AI approved"}
    base.update(over)
    return base


def test_proof_rule_for_pass_and_fail():
    assert trial.proof_problem(line(), "Proven by code") is None
    assert trial.proof_problem(line(), "AI opinion, engineer to confirm")
    assert trial.proof_problem(line(quotes_checked={"paper": True, "clause": False}), "Proven by code") == "rule quote not verified by code"
    assert trial.proof_problem(line(quotes_checked={"paper": False, "clause": True}), "Proven by code") == "paper quote not verified by code"
    assert trial.proof_problem(line(decided_by="AI verdict", compare=None), "Proven by code")
    assert trial.proof_problem(line(decided_by="AI verdict", compare=None, second_opinion="agreed"), "Proven by code") is None
    assert trial.proof_problem(line(tier="Not AI approved"), "Proven by code") == "the rule is not approved"
    assert trial.proof_problem(line(tier=None, checklist=True), "Proven by code") is None


def test_the_proof_check_reads_the_stored_lines(world):
    with db.connect() as conn:
        from app import agent_review_schema

        agent_review_schema.ensure_schema()
        conn.execute("INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, line_json, decided_at)"
                     " VALUES ('r','A','Proven by code','Fail',1,'4.1','B','',NULL,?,'2026-11-12')", (json.dumps(line(quotes_checked={"paper": True, "clause": False})),))
    ro = trial.ro(world / "agent.sqlite")
    check = trial.proof_check(ro, "r")
    assert not check.ok and "rule quote not verified by code" in check.detail


def sheet(ids):
    wb = Workbook()
    ws = wb.active
    ws.append(["COMMENT RESOLUTION SHEET"])
    ws.append([])
    ws.append(["Item No", "Document Name"])
    for i in ids:
        ws.append([i, "paper"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_contractor_copy_may_hold_only_proven_fail_rows(world):
    with db.connect() as conn:
        from app import agent_review_schema

        agent_review_schema.ensure_schema()
        for item, cls, word in (("F1", "Proven by code", "Fail"), ("P1", "Proven by code", "Pass")):
            conn.execute("INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, line_json, decided_at)"
                         " VALUES ('r',?,?,?,1,'4.1','B','',NULL,'{}','2026-11-12')", (item, cls, word))
    ro = trial.ro(world / "agent.sqlite")
    assert trial.contractor_check(ro, "r", sheet(["F1"])).ok
    bad = trial.contractor_check(ro, "r", sheet(["F1", "P1"]))
    assert not bad.ok and "1 row(s) that are not a proven Fail" in bad.detail
    assert not trial.contractor_check(ro, "r", None).ok


def test_the_normal_review_check_says_a_skipped_step_is_a_failure():
    skipped = json.dumps({"ai_steps_skipped": [{"step": "clause_review", "calls_not_made": 3, "note": "skipped: local engine not loaded in a Claude-lane run"}]})
    bad = trial.normal_review_check(skipped, "completed")
    assert not bad.ok and "clause_review" in bad.detail
    assert trial.normal_review_check("{}", "completed").ok
    assert not trial.normal_review_check("{}", "failed").ok
    assert not trial.normal_review_check(json.dumps({"x": "A step was skipped in a Claude-lane run"}), "completed").ok


# ----------------------------------------------------------------------------------------- the refusals


def test_a_path_under_the_live_checkout_a_live_shaped_database_and_a_dotenv_are_refused(tmp_path, monkeypatch):
    live = tmp_path / "Abubakar"
    (live / "backend" / "data").mkdir(parents=True)
    monkeypatch.setattr(trial, "live_roots", lambda: [live.resolve()])
    monkeypatch.setattr(trial, "BACKEND", tmp_path / "none")
    with pytest.raises(trial.Refused, match="under the live checkout"):
        trial.refuse_live({"data folder": live / "backend" / "data"})
    other = tmp_path / "elsewhere" / "backend" / "data"
    other.mkdir(parents=True)
    with pytest.raises(trial.Refused, match="live-shaped"):
        trial.refuse_live({"database": other / "rag_intelligence.sqlite"})
    trial.refuse_live({"data folder": tmp_path / "copy"})  # a plain copy is fine
    envdir = tmp_path / "be"
    envdir.mkdir()
    (envdir / ".env").write_text("X=1")
    monkeypatch.setattr(trial, "BACKEND", envdir)
    with pytest.raises(trial.Refused, match=r"backend/\.env"):
        trial.refuse_live({"data folder": tmp_path / "copy"})


def test_the_open_lane_needs_the_callers_key_and_a_secret_looking_setting_is_refused(world, monkeypatch):
    with pytest.raises(trial.Refused, match="no key in the caller's environment"):
        trial.run_trial(cfg_for(world))
    with pytest.raises(trial.Refused, match="secret-looking"):
        trial.run_trial(cfg_for(world, sets={"ANTHROPIC_API_KEY": "x"}))
    with pytest.raises(trial.Refused, match="allow-local-models"):
        trial.run_trial(cfg_for(world, normal_review=True))


def test_main_refuses_a_live_path_with_exit_2(tmp_path, monkeypatch, capsys):
    live = tmp_path / "Abubakar"
    (live / "backend" / "data").mkdir(parents=True)
    monkeypatch.setattr(trial, "live_roots", lambda: [live.resolve()])
    code = trial.main(["--lane", "closed", "--data-dir", str(live / "backend" / "data"), "--in-place", "--document", "d"])
    assert code == 2 and "REFUSED" in capsys.readouterr().out
    assert trial.main(["--lane", "closed", "--data-dir", str(tmp_path), "--document", "d"]) == 2  # neither --copy-to nor --in-place
