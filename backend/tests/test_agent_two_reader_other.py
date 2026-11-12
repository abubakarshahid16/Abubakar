"""The class "Not checked on this paper" (word "Needs a drawing or a calculation"; lead order, 12 Nov 2026). Invented data; no network."""

# ruff: noqa: F811
from __future__ import annotations

import itertools
import json

import openpyxl
import pytest

from app import agent_claude, agent_review_jobs, db
from app import agent_review_pair as pair
from app import agent_review_request as request_mod
from app import agent_review_run as run_mod
from app import agent_review_two_reader as two
from app import agent_review_wording as W
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_crs import OK, SK, rows_of
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_two_reader import TwoLane, stored

CLASS, WORD = "Not checked on this paper", "Needs a drawing or a calculation"
NEEDS = {
    "verdict": "Query",
    "reason_code": "needs_drawing_or_calc",
    "paper_quote": "",
    "reasoning": "SENTINEL-LEAD-73",
    "comment": "SENTINEL-LEAD-74",
}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    monkeypatch.setattr(settings, "agent_review_two_reader_other_paper_enabled", True)


def lane(w, second=None, **kw):
    fake = w["fake"] = TwoLane(**kw)
    fake.answers["R-coat"] = {**s.ANSWERS["R-coat"], **NEEDS}
    fake.second["R-coat"] = {
        **s.ANSWERS["R-coat"],
        **{**NEEDS, "reasoning": "needs a drawing", "comment": "n"},
        **(second or {}),
    }
    return fake


def asked_ids(fake):
    out = []
    for body in fake.reader2:
        out += [
            q["item_id"]
            for q in json.loads(
                body["messages"][0]["content"][-1]["text"].split("\n\n")[0]
            )["items"]
        ]
    return out


def other_step(run_id):
    row = (
        db.connect()
        .execute("SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["counts_json"]).get("two_reader_other_step")


def test_both_readers_need_a_drawing_and_both_clause_quotes_verified_gives_the_new_class_on_the_parked_sheet(
    w, on
):
    lane(w)
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == (CLASS, WORD) and row[
        "reason"
    ] == two.OTHER_WHY
    assert row["word"] not in ("Pass", "Fail", "Query", "Not applicable")
    path = agent_review_jobs.run_dir(run_id) / "crs-internal.xlsx"
    parked = rows_of(path, "Not reviewed or not applicable")
    mine = [r for r in parked if r["What it is"] == CLASS]
    assert len(mine) == 1 and mine[0]["Reason"] == two.OTHER_WHY + "."
    assert all(
        r["Status"] != "Query" for r in rows_of(path) if "R-coat" in str(r)
    )  # it is not on the item rows as a Query
    notes = {
        r[0]: r[1]
        for r in openpyxl.load_workbook(path)["Notes"].iter_rows(
            min_row=2, values_only=True
        )
    }
    assert notes["Count: Not checked on this paper"] == 1
    assert other_step(run_id) == {
        "candidates": 1,
        "asked": 1,
        "calls": 1,
        "agreed": 1,
        "disagreed": 0,
        "unconfirmed": 0,
        "off": None,
    }
    counts = {r["verdict_class"]: 0 for r in lines_of(run_id).values()}
    assert CLASS in counts


def test_the_cause_is_read_from_the_closed_reason_code_never_from_free_text(w, on):
    fake = lane(w)
    fake.answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "verdict": "Query",
        "reason_code": "other",
        "paper_quote": "",
        "comment": "this needs a drawing or a calculation",
    }
    run_id = run_review()
    assert lines_of(run_id)["R-coat"][
        "verdict_class"
    ] == "Query for the engineer" and "two_reader_other" not in stored(run_id, "R-coat")


def test_a_verdict_by_the_second_reader_with_verified_quotes_is_a_disagreement_and_goes_to_evidence(
    w, on
):
    lane(
        w,
        second={
            "verdict": "Pass",
            "reason_code": "met",
            "paper_quote": "Coating layers two",
            "paper_page": 1,
        },
    )
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["reason"]) == (
        "Query for the engineer",
        "two AI readers disagree on this line",
    )
    assert other_step(run_id)["disagreed"] == 1
    ev = rows_of(agent_review_jobs.run_dir(run_id) / "crs-internal.xlsx", "Evidence")
    assert "met" in [r["Independent reader: verdict"] for r in ev]


@pytest.mark.parametrize(
    "second",
    [
        {"verdict": "Query", "reason_code": "other"},  # cannot tell for another reason
        {"verdict": "Query", "reason_code": "sheet_silent"},
        {
            "clause_quote": "A rule sentence that is not in the rule book."
        },  # its clause quote is not verified
        {
            "verdict": "Pass",
            "reason_code": "met",
            "paper_quote": "Coating layers three",
        },  # a verdict whose quote is not verified
    ],
)
def test_anything_else_from_the_second_reader_leaves_the_line_a_query(w, on, second):
    lane(w, second=second)
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["verdict_class"] == "Query for the engineer"
    assert other_step(run_id)["agreed"] == 0


def test_switch_off_stores_nothing_and_makes_no_extra_call(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    fake = lane(w)
    run_id = run_review()
    assert (
        "R-coat" not in asked_ids(fake)
        and other_step(run_id) is None
        and "two_reader_other" not in stored(run_id, "R-coat")
    )
    assert lines_of(run_id)["R-coat"]["verdict_class"] == "Query for the engineer"


def test_the_switch_needs_the_first_switch(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_other_paper_enabled", True)
    fake = lane(w)
    run_review()
    assert "R-coat" not in asked_ids(fake)


def test_the_default_of_the_switch_is_off():
    from app.settings_ext import SettingsExt

    assert (
        SettingsExt.model_fields["agent_review_two_reader_other_paper_enabled"].default
        is False
    )


def test_an_unapproved_rule_is_never_asked_and_never_moves(w, on):
    with db.connect() as conn:
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute("DELETE FROM rule_label WHERE rule_ref = 'req-R-coat'")
        conn.commit()
    fake = lane(w)
    run_id = run_review()
    assert (
        "R-coat" not in asked_ids(fake)
        and lines_of(run_id)["R-coat"]["verdict_class"] != CLASS
    )


def test_the_second_readers_request_holds_nothing_the_first_reader_said(w, on):
    fake = lane(w)
    run_review()
    assert "SENTINEL-LEAD" not in json.dumps(fake.reader2[0])
    assert fake.reader2[0]["system"][0]["text"] == request_mod.SYSTEM


def test_the_same_family_as_the_first_reader_gives_no_class(w, on):
    fake = lane(w, second_reply_model="claude-sonnet-5-5-20260101")
    fake.LEAD = "claude-sonnet-5-5"
    assert lines_of(run_review())["R-coat"]["verdict_class"] == "Query for the engineer"


def test_a_cap_refusal_switches_the_step_off_and_the_run_completes(w, on, monkeypatch):
    fake = lane(w)
    orig = run_mod.Runner.call

    def call(self, model, parts, max_tokens, once=False):
        ids = json.dumps(parts["messages"][0]["content"][-1])
        if (
            model == agent_claude.SECOND_MODEL
            and "R-coat" in ids
            and "R-mark" not in ids
        ):  # the other-paper batch only; the value step asks R-mark
            raise request_mod.StepCapStop("invented cap")
        return orig(self, model, parts, max_tokens, once)

    monkeypatch.setattr(run_mod.Runner, "call", call)
    run_id = run_review()
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (
        run["stop_reason"] is None
        and other_step(run_id)["off"] == two.OFF_CAP
        and "R-coat" not in asked_ids(fake)
    )
    assert lines_of(run_id)["R-coat"]["verdict_class"] == "Query for the engineer"


def test_the_contractor_copy_never_holds_the_class(w, on):
    lane(w)
    run_id = run_review()
    ws = openpyxl.load_workbook(
        agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx"
    )["CRS"]
    text = "\n".join(
        str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None
    )
    for banned in (CLASS, WORD, "Two AI readers", "drawing or a calculation"):
        assert banned not in text


def _line(**over):
    base = {
        "item_id": "R-9", "source": "rule", "standard": "STD-1", "clause": "4.1", "verdict": "Query", "decided_by": "engineer", "ai_verdict": "Query",
        "reason_code": "needs_drawing_or_calc", "model": "lead-m", "paper_page": None, "clause_quote": "Nameplates shall be steel",
        "quotes_checked": {"paper": False, "clause": True}, "reasoning": "Needs a drawing.",
        "two_reader_other": {"verdict": two.V_NEEDS, "model": "second-m", "quotes_checked": {"paper": False, "clause": True}},
    }  # fmt: skip
    base.update(over)
    return W.final_cap(
        base, over.pop("_item", OK), skill_ids=SK, paper_kind="datasheet"
    )


def test_the_class_is_reachable_only_by_the_rule_brute_force():
    flags = [False, True]
    reached = 0
    for (
        rec_verdict,
        clause1,
        clause2,
        differ,
        code_ok,
        hold,
        tier_ok,
    ) in itertools.product(
        [two.V_NEEDS, two.V_MET, two.V_NOT_MET, two.V_CANNOT_TELL],
        flags,
        flags,
        flags,
        flags,
        flags,
        flags,
    ):
        item = (
            OK
            if tier_ok
            else {
                "source": "rule",
                "rule_tier": "not_approved",
                "rule_unapproved_why": "x",
            }
        )
        base = {
            "item_id": "R-9", "source": "rule", "standard": "STD-1", "clause": "4.1", "verdict": "Query", "decided_by": "engineer", "ai_verdict": "Query",
            "reason_code": "needs_drawing_or_calc" if code_ok else "other", "model": "lead-m", "clause_quote": "x",
            "quotes_checked": {"paper": True, "clause": clause1}, "conditional_hold": hold, "reasoning": "r",
            "two_reader_other": {"verdict": rec_verdict, "model": "second-m" if differ else "lead-m-20260101", "quotes_checked": {"paper": True, "clause": clause2}},
        }  # fmt: skip
        capped = W.final_cap(base, item, skill_ids=SK, paper_kind="datasheet")
        got = W.apply(capped)
        want = (
            rec_verdict == two.V_NEEDS
            and clause1
            and clause2
            and differ
            and code_ok
            and not hold
            and tier_ok
        )
        assert (got["verdict_class"] == CLASS) is bool(want), (
            rec_verdict,
            clause1,
            clause2,
            differ,
            code_ok,
            hold,
            tier_ok,
        )
        if got["verdict_class"] == CLASS:
            reached += 1
            assert (
                got["verdict_label"] == WORD
                and pair.contract_class_and_word(capped)[1] == WORD
            )
            assert got["verdict"] == "Query" and W.writer_refusal(capped) is None
    assert reached == 1


def test_a_checklist_item_is_a_candidate_too():
    ln = W.final_cap(
        {**_line(), "source": "skill", "item_id": "S-1"},
        {"source": "skill", "item_id": "S-1"},
        skill_ids=SK,
        paper_kind="datasheet",
    )
    assert ln["verdict_class"] == CLASS and ln.get("tier") is None
