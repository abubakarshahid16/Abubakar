"""The absence word "AI verdict: not stated" of the class "AI verdict, two readers agree" (lead order, 12 Nov 2026).

Invented paper, rule and models; no network. The code's absence search is the REAL `agent_review_absence.prove` (the product's
field registry), the paper's pages and ledger rows are written into the test database."""

# ruff: noqa: F811
from __future__ import annotations

import itertools
import json

import openpyxl
import pytest

from app import agent_review_absence as A
from app import agent_review_jobs, db
from app import agent_review_two_reader as two
from app import agent_review_two_reader_absence as step
from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_crs import META, OK, SK, rows_of
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_two_reader import CLASS, TwoLane, step_of, stored

ROLE = "design_pressure"
FILL = " Invented filler line about the casing material, carbon steel to an invented grade, for the test."
PAGES = {
    1: "DATA SHEET. Coating layers two. Marking blue. Serial invented." + FILL,
    2: "Impeller trim: bronze. Casing: carbon steel." + FILL,
    3: "Notes. Delivery as agreed. Painting standard invented." + FILL,
}
NOT_STATED = "AI verdict: not stated"


class AbsLane(TwoLane):
    """The first reader says R-coat is absent; the absence reader (the system text of `ABSENCE_SYSTEM`) answers from `absence`."""

    def __init__(self, absence=None, **kw):
        super().__init__(**kw)
        self.answers["R-coat"] = {
            **s.ANSWERS["R-coat"], "verdict": "Fail", "reason_code": "absent", "paper_quote": "", "pages_searched": [1, 2, 3],
            "reasoning": "SENTINEL-LEAD-REASONING-81", "comment": "SENTINEL-LEAD-COMMENT-82",
        }  # fmt: skip
        self.absence_answers = {
            "R-coat": {
                "found": False,
                "clause_quote": s.RULES["R-coat"][0],
                "open": False,
            }
        }
        if absence:
            self.absence_answers["R-coat"] = {
                **self.absence_answers["R-coat"],
                **absence,
            }
        self.absence_bodies = []

    def __call__(self, url, *, headers, body, timeout):
        if step.ABSENCE_SYSTEM in json.dumps(body.get("system")).replace(
            "\\n", "\n"
        ) or "reading a supplier paper" in json.dumps(body.get("system")):
            self.absence_bodies.append(body)
            self.kinds.append("absence")
            last = body["messages"][0]["content"][-1]["text"]
            ids = [q["item_id"] for q in json.loads(last.split("\n\n")[0])["items"]]
            got = [
                {"item_id": i, **self.absence_answers[i]}
                for i in ids
                if i in self.absence_answers
            ]
            return self._reply(
                self.reply_model,
                {"input_tokens": 4000, "output_tokens": 200},
                json.dumps({"answers": got}),
            )
        return super().__call__(url, headers=headers, body=body, timeout=timeout)


@pytest.fixture
def both(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    monkeypatch.setattr(settings, "agent_review_two_reader_absence_enabled", True)
    monkeypatch.setattr(A, "carried_roles", lambda *_a, **_k: frozenset({ROLE}))


def paper(pages=PAGES, ledger=None):
    """The paper's pages and ledger rows as the product stores them."""
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
        for n, text in pages.items():
            conn.execute(
                "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
                (s.PAPER, n, text, len(text)),
            )
            if ledger is None or n in ledger:
                conn.execute(
                    "INSERT INTO page_ledger(document_id, page_no, native_status, ocr_status, updated_at) VALUES (?,?, 'text', 'not_required', '2026-11-12')",
                    (s.PAPER, n),
                )


def setup(w, **kw):
    for it in w["doc"]["items"]:
        if it["item_id"] == "R-coat":
            it.update(
                page_hint=[1, 2, 3],
                field_roles=[ROLE],
                rule_row_found=True,
                rule_condition=None,
                rule_exceptions=None,
            )
    w["fake"] = AbsLane(**kw)
    return w["fake"]


def absence_step(run_id):
    row = (
        db.connect()
        .execute("SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["counts_json"]).get("two_reader_absence_step")


def test_both_readers_say_not_stated_and_code_search_is_empty_gives_the_new_word(
    w, both
):
    paper()
    fake = setup(w)
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == (CLASS, NOT_STATED)
    assert row["reason"] == two.ABSENCE_WHY and row["word"] not in ("Pass", "Fail")
    line = stored(run_id, "R-coat")
    assert (
        line["verdict"] == "Query"
        and line["two_reader_absence"]["code_search"]["proven"] is True
    )
    assert absence_step(run_id) == {
        "candidates": 1,
        "asked": 1,
        "calls": 1,
        "agreed": 1,
        "disagreed": 0,
        "unconfirmed": 0,
        "off": None,
    }
    assert len(fake.absence_bodies) == 1


def test_the_absence_request_holds_every_page_whole_and_nothing_the_first_reader_said(
    w, both
):
    paper()
    fake = setup(w)
    run_review()
    body = fake.absence_bodies[0]
    text = json.dumps(body, ensure_ascii=False)
    for n, page in PAGES.items():
        assert any(
            b["text"] == f'<paper document="{s.PAPER}" page="{n}">\n{page}\n</paper>'
            for b in body["messages"][0]["content"]
        )
    assert (
        "SENTINEL-LEAD" not in text
        and "does not state" not in text
        and "absent" not in text.lower().replace("absence", "")
    )
    items = json.loads(body["messages"][0]["content"][-1]["text"].split("\n\n")[0])[
        "items"
    ]
    assert [q["item_id"] for q in items] == ["R-coat"]
    assert set(items[0]) <= {
        "item_id",
        "question",
        "field_roles",
        "standard",
        "clause",
        "rule_kind",
        "comparator",
        "value",
        "unit",
        "page_hint",
        "requirement_ref",
        "clause_ref",
    }


def test_a_value_the_second_reader_finds_and_code_verifies_is_a_disagreement_with_its_quote_on_evidence(
    w, both
):
    paper()
    setup(w, absence={"found": True, "page": 2, "paper_quote": "Impeller trim: bronze"})
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == ("Query for the engineer", "Query")
    assert row["reason"] == "two AI readers disagree on this line"
    assert absence_step(run_id)["disagreed"] == 1
    ev = rows_of(agent_review_jobs.run_dir(run_id) / "crs-internal.xlsx", "Evidence")
    mine = [r for r in ev if r["Independent reader: verdict"] == "found a value"]
    assert (
        len(mine) == 1
        and mine[0]["Independent reader: paper quote"] == "Impeller trim: bronze"
        and mine[0]["Independent reader: paper page"] == 2
    )


@pytest.mark.parametrize(
    "absence",
    [
        {
            "found": True,
            "page": 2,
            "paper_quote": "A value that is on no page at all",
        },  # a quote code cannot verify
        {"found": False, "open": True},  # the paper leaves it open: not a verdict
        {
            "found": False,
            "clause_quote": "A rule sentence that is not in the rule book.",
        },
        {"found": None},
    ],
)
def test_an_answer_code_cannot_stand_behind_leaves_the_line_as_it_was(w, both, absence):
    paper()
    setup(w, absence=absence)
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: not met"
    assert (
        absence_step(run_id)["agreed"] == 0 and absence_step(run_id)["unconfirmed"] == 1
    )


def test_one_unread_page_means_no_candidate_and_no_call(w, both):
    paper(ledger={1, 2})  # page 3 has no ledger row: not read
    fake = setup(w)
    run_id = run_review()
    assert (
        fake.absence_bodies == []
        and lines_of(run_id)["R-coat"]["word"] == "AI thinks: not met"
    )
    assert absence_step(run_id)["candidates"] == 0


def test_a_near_empty_page_is_not_read(w, both):
    paper({**PAGES, 3: "x"})
    fake = setup(w)
    run_review()
    assert fake.absence_bodies == []


def test_code_finding_the_field_words_with_a_value_means_no_candidate(w, both):
    paper({**PAGES, 2: PAGES[2] + "\nDesign pressure 10 barg"})
    fake = setup(w)
    run_id = run_review()
    assert (
        fake.absence_bodies == []
        and lines_of(run_id)["R-coat"]["word"] == "AI thinks: not met"
    )


def test_a_deferral_marker_beside_the_label_is_not_absence(w, both):
    paper({**PAGES, 2: PAGES[2] + "\nDesign pressure: By Contractor"})
    fake = setup(w)
    run_id = run_review()
    assert (
        fake.absence_bodies == []
        and lines_of(run_id)["R-coat"]["verdict_class"] != CLASS
    )


def test_the_absence_switch_off_changes_nothing_and_makes_no_call(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    monkeypatch.setattr(A, "carried_roles", lambda *_a, **_k: frozenset({ROLE}))
    paper()
    fake = setup(w)
    run_id = run_review()
    assert fake.absence_bodies == [] and absence_step(run_id) is None
    assert (
        "two_reader_absence" not in stored(run_id, "R-coat")
        and lines_of(run_id)["R-coat"]["word"] == "AI thinks: not met"
    )


def test_the_absence_switch_needs_the_first_switch(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_absence_enabled", True)
    monkeypatch.setattr(A, "carried_roles", lambda *_a, **_k: frozenset({ROLE}))
    paper()
    fake = setup(w)
    run_review()
    assert fake.absence_bodies == []


def test_the_default_of_the_absence_switch_is_off():
    from app.settings_ext import SettingsExt

    assert (
        SettingsExt.model_fields["agent_review_two_reader_absence_enabled"].default
        is False
    )


def test_a_paper_over_the_size_limit_has_no_candidate_and_nothing_is_sent(
    w, both, monkeypatch
):
    monkeypatch.setattr(two, "ABSENCE_MAX_PAGE_CHARS", 100)
    paper()
    fake = setup(w)
    run_id = run_review()
    assert (
        fake.absence_bodies == []
        and absence_step(run_id)["off"] == two.OFF_PAPER_TOO_LONG
    )
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: not met"


def test_a_cap_refusal_inside_the_absence_step_switches_it_off_and_the_run_completes(
    w, both, monkeypatch
):
    from app import agent_review_request as request_mod
    from app import agent_review_run as run_mod

    paper()
    fake = setup(w)
    orig = run_mod.Runner.call

    def call(self, model, parts, max_tokens, once=False):
        if parts["system"][0]["text"] == step.ABSENCE_SYSTEM:
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
        and absence_step(run_id)["off"] == two.OFF_CAP
        and fake.absence_bodies == []
    )
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: not met"


def test_the_same_family_as_the_first_reader_gives_no_word(w, both):
    paper()
    fake = setup(w, second_reply_model="claude-sonnet-5-5-20260101")
    fake.LEAD = "claude-sonnet-5-5"
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: not met"


def test_a_line_proven_by_code_is_never_asked(w, both):
    paper()
    fake = setup(w)
    fake.agree = True
    fake.answers["R-coat"] = s.ANSWERS["R-coat"]  # a proven Pass
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["word"] == "Pass" and fake.absence_bodies == []


def test_the_contractor_copy_never_holds_the_word_or_its_sentence(w, both):
    paper()
    setup(w)
    run_id = run_review()
    ws = openpyxl.load_workbook(
        agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx"
    )["CRS"]
    text = "\n".join(
        str(c) for row in ws.iter_rows(values_only=True) for c in row if c is not None
    )
    for banned in ("AI verdict", "not stated", "Two AI readers", two.ABSENCE_WHY):
        assert banned not in text


# ---------------------------------------------------------------- the pure rule and the CRS


def _line(**over):
    base = dict(
        item_id="R-9", source="rule", standard="STD-1", clause="4.1", verdict="Query", decided_by="engineer",
        ai_verdict="Fail", reason_code="absent", pages_searched=[1, 2], model="lead-m", paper_page=1, paper_quote=None,
        clause_quote="Nameplates shall be steel and fixed", field_roles=["design_pressure"], field="Design pressure",
        quotes_checked={"paper": False, "clause": True, "clause_strong": True}, reasoning="The sheet gives none.",
        two_reader_absence={
            "verdict": "not stated", "model": "second-m", "paper_quote": None, "paper_page": None,
            "clause_quote": "Nameplates shall be steel and fixed",
            "quotes_checked": {"paper": False, "clause": True, "clause_strong": True, "both": False},
            "code_search": {"proven": True, "pages_checked": 3}, "pages_total": 3,
        },
    )  # fmt: skip
    base.update(over)
    return W.final_cap(base, OK, skill_ids=SK, paper_kind="datasheet")


def test_a_not_stated_line_in_the_crs_has_the_status_priority_and_only_established_words(
    tmp_path,
):
    ln = _line()
    assert (ln["verdict_class"], ln["verdict_label"]) == (CLASS, NOT_STATED)
    assert WB.status_of(ln) == (words.STATUS_AI_VERDICT, words.ORDER_AI_VERDICT_NOT_MET)
    view = WB.layout_view([ln], META, "internal")
    row = view["rows"][0]
    assert (
        row[9] == "AI verdict" and row[8] == "High"
    )  # Priority as for "not met", mandatory
    assert two.ABSENCE_WHY in row[3] and "Contractor to state Design pressure" in row[3]
    assert (
        not words.has_banned(row[3])
        and "the paper does not state" not in row[3].lower()
    )
    assert view["evidence"]["rows"][0][14] == "not stated"  # the independent reader's verdict on the Evidence sheet
    assert (
        W.counts([ln])["ai_verdict_not_stated"] == 1
        and WB.layout_view([ln], META, "contractor")["rows"] == []
    )


def test_the_absence_word_is_in_the_one_table_and_never_a_pass_or_fail():
    from app import agent_review_pair as pair

    ln = _line()
    cls, word = pair.contract_class_and_word(ln)
    assert (cls, word) == (CLASS, NOT_STATED) and word not in ("Pass", "Fail")
    assert W.writer_refusal(ln) is None


def _oracle(
    cand_ok,
    rec_verdict,
    clause_ok,
    strong,
    proven,
    pages_ok,
    differ,
    source_ok,
    hold,
    reason_ok,
    tier_ok,
):
    return (
        cand_ok and rec_verdict == "not stated" and clause_ok and strong and proven and pages_ok and differ
        and source_ok and not hold and reason_ok and tier_ok
    )  # fmt: skip


def test_the_absence_word_is_reachable_only_by_the_rule_brute_force():
    flags = [False, True]
    reached = 0
    for (
        rec_verdict,
        clause_ok,
        strong,
        proven,
        pages_ok,
        differ,
        source_ok,
        hold,
        reason_ok,
        tier_ok,
    ) in itertools.product(
        ["not stated", "found a value", "cannot tell"],
        flags,
        flags,
        flags,
        flags,
        flags,
        flags,
        flags,
        flags,
        flags,
    ):
        ln = _line(
            source="rule" if source_ok else "skill",
            reason_code="absent" if reason_ok else "met",
            conditional_hold=hold,
            two_reader_absence={
                "verdict": rec_verdict, "model": "second-m" if differ else "lead-m-20260101",
                "clause_quote": "x", "paper_quote": "Some value 10", "paper_page": 1,
                "quotes_checked": {"paper": True, "clause": clause_ok, "clause_strong": strong},
                "code_search": {"proven": proven, "pages_checked": 3 if pages_ok else 2}, "pages_total": 3,
            },
        )  # fmt: skip
        if not tier_ok:
            ln = W.final_cap(
                {**ln},
                {
                    "source": "rule",
                    "rule_tier": "not_approved",
                    "rule_unapproved_why": "x",
                },
                skill_ids=SK,
                paper_kind="datasheet",
            )
        got = W.apply(ln)
        want = _oracle(
            True,
            rec_verdict,
            clause_ok,
            strong,
            proven,
            pages_ok,
            differ,
            source_ok,
            hold,
            reason_ok,
            tier_ok,
        )
        assert (got["verdict_label"] == NOT_STATED) is want, (
            rec_verdict,
            clause_ok,
            strong,
            proven,
            pages_ok,
            differ,
            source_ok,
            hold,
            reason_ok,
            tier_ok,
        )
        reached += want
    assert reached == 1  # exactly one corner of the table reaches the word
