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
    claude_approved,
    db,
    nothing_read,
)
from app.config import settings
from tests import agent_review_support as s

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "trial_on_copy", REPO / "scripts" / "trial_on_copy.py"
)
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
    return agent_review_kind.PaperReading(
        "datasheet", True, "read by code", "title", False, None, None
    )


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
    for env in (
        "REASONING_PROVIDER",
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "AGENT_SKILLS_DIR",
    ):
        monkeypatch.setenv(env, "x")
        monkeypatch.delenv(env)
    monkeypatch.setattr(
        trial, "BACKEND", tmp_path / "no-backend"
    )  # no backend/.env beside the code
    monkeypatch.setattr(
        trial, "live_roots", lambda: [Path("/nonexistent-live-checkout")]
    )
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading())
    monkeypatch.setattr(
        agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id
    )
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    doc, cache = s.item_doc()

    def build(_conn, _paper, _kind, *, cache=None, **_kw):
        cache.update(_CACHE["cache"])
        return _CACHE["doc"]

    _CACHE["doc"], _CACHE["cache"] = doc, cache
    monkeypatch.setattr(items_mod, "build_items", build)
    with db.connect() as conn:
        s.label_rows(conn, [i["item_id"] for i in doc["items"]])
    from app import classification

    classification.set_role(
        s.STD, "COMPANY_STANDARD"
    )  # the rule book is a standard, as the approval hook requires
    db.reset_connection()
    return tmp_path


_CACHE: dict = {}


def cfg_for(tmp_path, **over):
    base = {
        "data_dir": tmp_path,
        "document": s.PAPER,
        "lane": "open",
        "db": tmp_path / "agent.sqlite",
        "labels_dir": tmp_path / "no-labels",
        "timeout": 120.0,
        "max_usd": 2.0,
    }
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


def test_a_good_run_with_a_not_applicable_answer_and_a_cut_off_answer_passes_every_check(
    world, monkeypatch
):
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", pair_fixed)
    checks = trial.run_trial(
        cfg_for(world), lane=stub(cut_first=True), log=lambda _m: None
    )
    got = by_name(checks)
    assert failed(checks) == [], trial.table(checks)
    assert "asked 4" in got["rules asked > 0, or the plan says why none"].detail
    assert (
        "proven Pass 1, proven Fail 1" in got["Pass/Fail only with code proof"].detail
    )
    assert "4 line(s)" in got["route trace 200 for every line"].detail
    assert (
        "standing approval" in " ".join(got)
        and got[
            "standing approval: paper and asked rule books approved, register blocked"
        ].ok
    )
    assert got["spend under the cap and real answers"].ok


def _illegal_rows(path):
    """The stored rows the contract refuses, read straight from the database (not through any route)."""
    from pydantic import ValidationError

    from app.api import agent_review_schemas as contract

    bad = []
    for r in trial.ro(path).execute(
        "SELECT item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, part, text_source FROM agent_review_line"
    ):
        try:
            contract.AgentLine.model_validate(dict(r))
        except ValidationError:
            bad.append(r["item_id"])
    return bad


def test_an_illegal_pair_planted_as_a_stored_row_is_reported_whatever_the_route_does(
    world,
):
    """The live database holds one from the 12 Nov run: class "Not applicable" with the word "Query"."""
    from app import agent_review_schema

    agent_review_schema.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier,"
            " line_json, decided_at) VALUES ('r','S-EQ-17','Not applicable','Query',1,'4.1','B','',NULL,'{}','2026-11-12')"
        )
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier,"
            " line_json, decided_at) VALUES ('r','S-EQ-18','Not reviewed','Not reviewed',1,'4.1','B','',NULL,'{}','2026-11-12')"
        )
    check = trial.legal_rows_check(trial.ro(world / "agent.sqlite"), "r")
    assert not check.ok and '"Not applicable"+"Query"' in check.detail
    assert "1 of 2 lines illegal" in check.detail


def test_the_table_check_reports_a_pair_only_when_the_table_itself_is_wrong(
    monkeypatch,
):
    monkeypatch.setattr(
        agent_review_jobs,
        "contract_class_and_word",
        lambda _line: ("Not applicable", "Query"),
    )
    assert not trial.static_pair_check().ok  # a wrong table
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", pair_fixed)
    assert trial.static_pair_check().ok  # a right table, whatever the stored rows hold


def test_the_lines_route_check_follows_what_the_rows_really_are(world, monkeypatch):
    """With a wrong table a run may store the bad pair (the route then answers 500) or refuse to store it, or map it at read
    (the route answers 200): the trial must say exactly what is true, by behaviour, in either world."""
    monkeypatch.setattr(
        agent_review_jobs,
        "contract_class_and_word",
        lambda line: (
            ("Not applicable", "Query")
            if line.get("reason_code") == "not_applicable"
            else real_pair(line)
        ),
    )
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    bad = failed(checks)
    stored_bad = _illegal_rows(world / "agent.sqlite")
    assert (
        "class/word table legal for every core line" in bad
    )  # the grid reaches the same patched function
    assert ("stored lines legal by the contract" in bad) == bool(stored_bad)
    if "route lines 200" in bad:  # the old 500: only a stored illegal row can cause it
        assert stored_bad
    assert "route summary 200" not in bad  # the rest of the routes still answer


def test_the_static_table_check_names_the_illegal_pair(monkeypatch):
    monkeypatch.setattr(
        agent_review_jobs,
        "contract_class_and_word",
        lambda line: ("Not applicable", "Query"),
    )
    check = trial.static_pair_check()
    assert not check.ok and '"Not applicable"+"Query"' in check.detail
    monkeypatch.setattr(agent_review_jobs, "contract_class_and_word", pair_fixed)
    assert trial.static_pair_check().ok


def test_an_empty_plan_now_carries_its_own_stated_reason_so_the_trial_passes_it(
    world, monkeypatch
):
    quiet = {
        **_CACHE["doc"]["rule_labels"],
        "summary_lines": [],
        "missing_rule_books": [],
        "counts": {},
    }
    _CACHE["doc"] = {
        **_CACHE["doc"],
        "items": [],
        "counts": {"skill": 0, "rule": 0},
        "rule_labels": quiet,
    }
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    # C2: an empty plan is never silent any more: the run itself says why (the trial's old "no word" failure cannot happen)
    got = by_name(checks)["rules asked > 0, or the plan says why none"]
    assert got.ok and "the plan stopped: no_rule_asked" in got.detail


def test_left_out_rules_with_a_reason_explain_an_empty_ask(world, monkeypatch):
    out = {
        "rule_version_id": "v-x",
        "rule_book": "INV-STD-100",
        "clause": "9.9",
        "reason": "needs_another_paper",
        "needs_paper_kind": "procedure",
        "standard_document_id": s.STD,
    }
    doc, _cache = s.item_doc(ids=(), left_out=[out])
    doc["rule_labels"]["summary_lines"] = []
    _CACHE["doc"] = doc
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    got = by_name(checks)
    assert (
        got["rules asked > 0, or the plan says why none"].ok
        and "left out 1" in got["rules asked > 0, or the plan says why none"].detail
    )
    assert (
        "asked 0, left out 1"
        in got["Rules used lists asked + left out, one reason each"].detail
    )


def test_a_paper_the_standing_approval_leaves_out_is_caught(world, monkeypatch):
    from app import claude_auto_approve

    monkeypatch.setattr(
        claude_auto_approve, "on_agent_standards", lambda *_a, **_k: None
    )  # the gap this PR closes, put back
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    bad = by_name(checks)[
        "standing approval: paper and asked rule books approved, register blocked"
    ]
    assert not bad.ok and "not approved" in bad.detail


# ----------------------------------------------------------------------------------------- the single checks


def line(**over):
    base = {
        "quotes_checked": {"paper": True, "clause": True},
        "decided_by": "decided by code",
        "compare": {"decided": "Pass"},
        "tier": "AI approved",
    }
    base.update(over)
    return base


def test_proof_rule_for_pass_and_fail():
    assert trial.proof_problem(line(), "Proven by code") is None
    assert trial.proof_problem(line(), "AI opinion, engineer to confirm")
    assert (
        trial.proof_problem(
            line(quotes_checked={"paper": True, "clause": False}), "Proven by code"
        )
        == "rule quote not verified by code"
    )
    assert (
        trial.proof_problem(
            line(quotes_checked={"paper": False, "clause": True}), "Proven by code"
        )
        == "paper quote not verified by code"
    )
    assert trial.proof_problem(
        line(decided_by="AI verdict", compare=None), "Proven by code"
    )
    assert (
        trial.proof_problem(
            line(decided_by="AI verdict", compare=None, second_opinion="agreed"),
            "Proven by code",
        )
        is None
    )
    assert (
        trial.proof_problem(line(tier="Not AI approved"), "Proven by code")
        == "the rule is not approved"
    )
    assert (
        trial.proof_problem(line(tier=None, checklist=True), "Proven by code") is None
    )


def test_the_proof_check_reads_the_stored_lines(world):
    with db.connect() as conn:
        from app import agent_review_schema

        agent_review_schema.ensure_schema()
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, line_json, decided_at)"
            " VALUES ('r','A','Proven by code','Fail',1,'4.1','B','',NULL,?,'2026-11-12')",
            (json.dumps(line(quotes_checked={"paper": True, "clause": False})),),
        )
    ro = trial.ro(world / "agent.sqlite")
    check = trial.proof_check(ro, "r")
    assert not check.ok and "rule quote not verified by code" in check.detail


def sheet(refs, extra=None, status=False):
    """A contractor copy as the app writes it since order 13: nine company columns, no item id, no Status."""
    wb = Workbook()
    ws = wb.active
    ws.append(["COMMENT RESOLUTION SHEET"])
    ws.append([])
    ws.append(
        [
            "Item No",
            "Document Name",
            "Standard Reference",
            *(["Status"] if status else []),
        ]
    )
    for n, ref in enumerate(refs, start=1):
        ws.append([n, extra or "paper", ref, *(["Fail"] if status else [])])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_contractor_copy_may_hold_only_proven_fail_rows(world):
    with db.connect() as conn:
        from app import agent_review_schema

        agent_review_schema.ensure_schema()
        for item, cls, word, clause in (
            ("F1", "Proven by code", "Fail", "4.1"),
            ("F2", "Proven by code", "Fail", "5.2"),
            ("P1", "Proven by code", "Pass", "6.3"),
        ):
            conn.execute(
                "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier, line_json, decided_at)"
                " VALUES ('r',?,?,?,1,?,'B','',NULL,'{}','2026-11-12')",
                (item, cls, word, clause),
            )
    ro = trial.ro(world / "agent.sqlite")
    one, two = "B clause 4.1", "B clause 5.2"
    assert trial.contractor_check(ro, "r", sheet([one, two])).ok
    assert trial.contractor_check(
        ro, "r", sheet([two, one])
    ).ok  # order does not matter
    assert not trial.contractor_check(ro, "r", None).ok
    for refs in (
        ["", ""],  # two blank-reference rows
        [one, one],  # the same proven reference twice
        [one, "OTHER clause 9"],  # one proven and one unknown
        [one],  # a proven Fail missing
        [one, two, two],  # an extra row
        [one, two, ""],
    ):
        got = trial.contractor_check(ro, "r", sheet(refs))
        assert not got.ok, refs
    assert "missing" in trial.contractor_check(ro, "r", sheet([one])).detail
    worded = trial.contractor_check(
        ro, "r", sheet([one, two], extra="The AI reviewer's view, not proven")
    )
    assert not worded.ok and "AI wording" in worded.detail
    assert not trial.contractor_check(
        ro, "r", sheet([one, two], status=True)
    ).ok  # a Status column is refused


def test_the_normal_review_check_says_a_skipped_step_is_a_failure():
    skipped = json.dumps(
        {
            "ai_steps_skipped": [
                {
                    "step": "clause_review",
                    "calls_not_made": 3,
                    "note": "skipped: local engine not loaded in a Claude-lane run",
                }
            ]
        }
    )
    bad = trial.normal_review_check(skipped, "completed")
    assert not bad.ok and "clause_review" in bad.detail
    assert trial.normal_review_check("{}", "completed").ok
    assert not trial.normal_review_check("{}", "failed").ok
    assert not trial.normal_review_check(
        json.dumps({"x": "A step was skipped in a Claude-lane run"}), "completed"
    ).ok


# ----------------------------------------------------------------------------------------- the refusals


def test_a_path_under_the_live_checkout_a_live_shaped_database_and_a_dotenv_are_refused(
    tmp_path, monkeypatch
):
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


def test_the_open_lane_needs_the_callers_key_and_a_secret_looking_setting_is_refused(
    world, monkeypatch
):
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
    code = trial.main(
        [
            "--lane",
            "closed",
            "--data-dir",
            str(live / "backend" / "data"),
            "--in-place",
            "--document",
            "d",
        ]
    )
    assert code == 2 and "REFUSED" in capsys.readouterr().out
    assert (
        trial.main(["--lane", "closed", "--data-dir", str(tmp_path), "--document", "d"])
        == 2
    )  # neither --copy-to nor --in-place


# ----------------------------------------------------------------------------------------- caps, approval proof, ledger


def test_max_usd_can_only_lower_the_owners_caps(world, monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    assert trial.effective_cap(100, settings) == 5.0
    assert trial.effective_cap(1.5, settings) == 1.5
    cfg = cfg_for(world, max_usd=100)
    trial.apply_settings(cfg)
    assert (
        settings.claude_budget_usd_per_step,
        settings.claude_budget_usd_total,
        cfg.max_usd,
    ) == (5.0, 5.0, 5.0)
    cfg = cfg_for(world, max_usd=0.5)
    trial.apply_settings(cfg)
    assert (settings.claude_budget_usd_per_step, settings.claude_budget_usd_total) == (
        0.5,
        0.5,
    )


def _owner_list(sha_by_id, source="owner"):
    claude_approved.list_path().write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "sha256": sha,
                        "document_id": i,
                        "status": "approved",
                        "source": source,
                        "approved_by": "owner",
                    }
                    for i, sha in sha_by_id.items()
                ]
            }
        ),
        encoding="utf-8",
    )


def test_an_approval_that_came_from_a_copied_list_does_not_prove_the_hook(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["0" * 64]}), encoding="utf-8"
    )
    from app import agent_review_schema

    agent_review_schema.ensure_schema()
    db.reset_connection()
    conn = trial.ro(world / "agent.sqlite")
    shas = {
        r["id"]: r["sha256"] for r in conn.execute("SELECT id, sha256 FROM documents")
    }
    _owner_list(shas)
    bad = trial.approval_check(conn, "no-run", s.PAPER, world)
    assert not bad.ok and "not add in this run" in bad.detail.replace(
        "did not add", "not add"
    )
    _owner_list(shas, source="auto: invented")
    assert trial.approval_check(conn, "no-run", s.PAPER, world).ok


def test_the_copys_list_is_set_aside_so_a_run_proves_the_hook_itself(world):
    conn = trial.ro(world / "agent.sqlite")
    _owner_list(
        {r["id"]: r["sha256"] for r in conn.execute("SELECT id, sha256 FROM documents")}
    )
    conn.close()
    checks = trial.run_trial(cfg_for(world), lane=stub(), log=lambda _m: None)
    assert (world / "claude_approved_documents.json.from-copy").is_file()
    assert by_name(checks)[
        "standing approval: paper and asked rule books approved, register blocked"
    ].ok


def test_the_closed_lane_spend_check_compares_the_ledger_before_and_after(tmp_path):
    cfg = trial.TrialConfig(data_dir=tmp_path, document="d", lane="closed")
    (tmp_path / "claude_spend.jsonl").write_text('{"a":1}\n{"a":2}\n{"a":3}\n')
    assert trial.spend_check(
        cfg, {"usd": None}, tmp_path, lines_before=3
    ).ok  # a copied ledger already had its lines
    assert not trial.spend_check(
        cfg, {"usd": None}, tmp_path, lines_before=2
    ).ok  # a line written by this run
    assert not trial.spend_check(cfg, {"usd": 0.1}, tmp_path, lines_before=3).ok
