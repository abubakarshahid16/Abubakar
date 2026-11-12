"""The general review of procedures and contracts (#1690, #781): the single exit, the mode decision, the five parts, the three
defects found by the scorer, the project papers, the job, the routes and the money.

INVENTED papers and an INVENTED model (no network, no key, no real text). Each test names the guard it checks.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import (
    access,
    agent_claude,
    agent_general_crs,
    agent_general_job,
    agent_general_parts,
    agent_general_prompts,
    agent_general_review,
    agent_review_gate,
    agent_review_jobs,
    agent_review_kind,
    claude_approved,
    claude_spend,
    db,
    nothing_read,
    submittal_review,
)
from app import agent_general_review as core
from app import agent_review_request as request_mod
from app import agent_review_run as runner_mod
from app.config import settings
from app.main import app
from tests import agent_review_support as s

PAPER, PROJ, OTHER, BOOK = "doc_proc", "doc_proj", "doc_other", "doc_book"
PAGES = {
    1: "Test Procedure for Widget Review. Section 1 scope. The review team meets every 4 weeks to decide actions. See Table 9 for the schedule.",
    2: "Section 2 team. The team has 6 members: Ann, Bob, Cy, Di, Ed. Actions are recorded without owner or date. Closure is by e-mail.",
    3: "Section 3 the review interval is 8 weeks. Appendix Z lists the forms. End of the invented paper, signed by the chair. Reference: IEC 61511.",
}
PROJ_PAGES = {
    1: "The procedure shall name an owner and a due date for every action. Reviews are held every 4 weeks, in writing."
}
OTHER_PAGES = {
    1: "SECRET other document text that must never be sent anywhere at all, not in any request body."
}
Q_A = "The review team meets every 4 weeks to decide actions."
Q_B = "the review interval is 8 weeks."
Q_COUNT = "The team has 6 members: Ann, Bob, Cy, Di, Ed."
Q_TABLE = "See Table 9 for the schedule."
Q_ACTIONS = "Actions are recorded without owner or date."
Q_REQ = "The procedure shall name an owner and a due date for every action."
Q_FORMS = "Appendix Z lists the forms."
ITEMS = [
    {
        "item_id": "S-C1",
        "source": "skill",
        "topic": "Scope",
        "question": "Topic: Scope",
        "clause_refs": [],
    },
    {
        "item_id": "S-C2",
        "source": "skill",
        "topic": "Closure",
        "question": "Topic: Closure",
        "clause_refs": [],
    },
]
LEAD, SECOND = "fake-lead-model-1", "fake-second-model-2"


class GFake:
    """An invented Claude for the general review. `p2..p5` and `review` map the last text of the request to a reply."""

    def __init__(
        self,
        p2=None,
        p3=None,
        p4=None,
        p5=None,
        review=None,
        second_name=SECOND,
        stop=None,
    ):
        self.p2, self.p3, self.p4, self.p5, self.review = p2, p3, p4, p5, review
        self.second_name, self.stop = second_name, stop
        self.bodies: list[dict] = []
        self._lock = threading.Lock()

    def __call__(self, url, *, headers, body, timeout):
        with self._lock:
            self.bodies.append(body)
        system = json.dumps(body.get("system"))
        last = body["messages"][0]["content"][-1]["text"]
        usage = {
            "input_tokens": 3000,
            "output_tokens": 600,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        if "independent senior engineer reviewing ONE finding" in system:
            fn, model = self.review, self.second_name
            reply = (
                fn(last)
                if fn
                else {"decision": "keep", "reason": "fake", "quotes_relate": "yes"}
            )
        else:
            fn, model = None, LEAD
            for marker, handler in (
                ("COMPLETE for its kind", self.p2),
                ("against ITSELF", self.p3),
                ("PROJECT PAPERS", self.p4),
                ("experienced engineer commenting", self.p5),
            ):
                if marker in system:
                    fn = handler
            assert fn is not None or True
            reply = fn(last) if fn else {}
        out = {"model": model, "stop_reason": self.stop or "end_turn", "usage": usage,
               "content": [{"type": "text", "text": reply if isinstance(reply, str) else json.dumps(reply)}]}  # fmt: skip
        return out

    def texts(self) -> str:
        return json.dumps(self.bodies)

    def calls_of(self, marker: str) -> int:
        return sum(1 for b in self.bodies if marker in json.dumps(b.get("system")))


def good_p2(_last):
    return {
        "answers": [
            {
                "item_id": "S-C1",
                "paper_page": 1,
                "paper_quote": PAGES[1][:50],
                "status": "present",
                "note": "x",
                "concern": "",
            },
            {
                "item_id": "S-C2",
                "paper_page": 2,
                "paper_quote": "",
                "status": "absent",
                "note": "no closure",
                "concern": "",
            },
        ]
    }


def good_p3(_last):
    return {
        "findings": [
            {
                "kind": "disagreement",
                "quote_a": {"page": 1, "text": Q_A},
                "quote_b": {"page": 3, "text": Q_B},
                "what": "Review interval is 4 weeks on page 1 and 8 weeks on page 3.",
                "severity": "high",
            },
            {
                "kind": "count_mismatch",
                "quote_a": {"page": 2, "text": Q_COUNT},
                "quote_b": {"page": 2, "text": Q_ACTIONS},
                "what": "Six members stated, five names listed.",
                "severity": "low",
            },
            {
                "kind": "broken_reference",
                "quote_a": {"page": 1, "text": Q_TABLE},
                "quote_b": None,
                "what": "Table 9 is referenced but not defined.",
                "severity": "medium",
            },
            {
                "kind": "open_action",
                "quote_a": {"page": 2, "text": Q_ACTIONS},
                "quote_b": None,
                "what": "Actions have no owner or date.",
                "severity": "medium",
            },
            {
                "kind": "disagreement",
                "quote_a": {"page": 1, "text": "INVENTED words not on the page at all"},
                "quote_b": {"page": 3, "text": Q_B},
                "what": "bad quote",
                "severity": "low",
            },
        ]
    }


def good_p4(_last):
    return {
        "findings": [
            {
                "document": PROJ,
                "kind": "contradicts",
                "quote_paper": {"page": 2, "text": Q_ACTIONS},
                "quote_other": {"page": 1, "text": Q_REQ},
                "what": "Actions lack the owner and date the project paper requires.",
            },
            {
                "document": PROJ,
                "kind": "silent",
                "quote_paper": None,
                "quote_other": {"page": 1, "text": Q_REQ},
                "what": "Owner and due date are not addressed.",
            },
        ]
    }


def good_p5(_last):
    return {
        "comments": [
            {
                "quote": {"page": 3, "text": Q_FORMS},
                "comment": "State where Appendix Z is held.",
            },
            {
                "quote": {"page": 3, "text": "NOT on the page anywhere"},
                "comment": "unverified",
            },
        ]
    }


def full_fake(**kw):
    return GFake(p2=good_p2, p3=good_p3, p4=good_p4, p5=good_p5, **kw)


def _add(conn, doc_id, filename, pages):
    conn.execute(
        "INSERT INTO documents(id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
        " VALUES (?,?,?,1,'x','ready','2020-01-01')",
        (doc_id, filename, hashlib.sha256(doc_id.encode()).hexdigest()),
    )
    for n, text in pages.items():
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
            (doc_id, n, text, len(text)),
        )


def reading(kind="procedure", known=True):
    return agent_review_kind.PaperReading(
        kind, known, "read by code", "title", False, None, None
    )


@pytest.fixture
def world(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    submittal_review.ensure_schema()
    with db.connect() as conn:
        _add(conn, PAPER, "procedure.pdf", PAGES)
        _add(conn, PROJ, "project-paper.pdf", PROJ_PAGES)
        _add(conn, OTHER, "other.pdf", OTHER_PAGES)
        conn.commit()
    monkeypatch.setattr(agent_general_review, "_kind_rule_books", lambda _k: [])
    monkeypatch.setattr(
        agent_general_review,
        "checklist_items",
        lambda *_a, **_k: (list(ITEMS), {"kind": "procedure"}),
    )
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: reading())
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    yield tmp_path
    db.reset_connection()


def build(
    world,
    fake,
    *,
    project=(PROJ,),
    carrier=None,
    items=ITEMS,
    unread=(),
    books=None,
    run_name="r1",
):
    conn = db.connect()
    runner = runner_mod.Runner(
        paper=PAPER,
        items=[],
        pages=request_mod.DbPages(conn, PAPER),
        clauses=request_mod.ClauseCache({}),
        model=LEAD,
        send=fake,
        env=s.ENV,
        retry_base=0.0,
    )
    carrier = list(carrier if carrier is not None else [PAPER, *project])
    docs = core.load_documents(conn, PAPER, list(project), carrier)
    folder = world / run_name
    folder.mkdir(exist_ok=True)
    g = agent_general_parts.GeneralRun(
        paper=PAPER,
        docs=docs,
        kind="procedure",
        books=books
        or {
            "not_held": [
                {"rule_book": "IEC 61511", "why": "cited by the paper"},
                {"rule_book": "API 521", "why": "cited by the paper"},
            ]
        },
        items=list(items),
        items_info={"kind": "procedure"},
        project=list(project),
        run_dir=folder,
        runner=runner,
        unread=unread,
        lead_model=LEAD,
        second_model=SECOND,
        concurrency=1,
    )
    return g, runner


def go(g, runner):
    with claude_approved.carrying([PAPER, PROJ]), claude_spend.for_run("gr-test"):
        runner.gate = request_mod.AppStepGate(request_mod.app_cap(), 0.0)
        g.run_all()
    return g.lines


def by_part(lines, part):
    return [ln for ln in lines if ln["part"] == part]


# ---------------------------------------------------------------- the single exit refuses the rule review's words

BAD = [
    {"verdict_class": "Proven by code"},
    {"verdict_class": "AI opinion, engineer to confirm"},
    {"verdict_class": "AI opinion, rule not yet approved"},
    {"verdict_class": "Pass"},
    {"verdict_class": core.CLASS_QUERY, "verdict": "Pass"},
    {"verdict_class": core.CLASS_QUERY, "verdict": "Fail"},
    {"verdict_class": core.CLASS_QUERY, "word": "Pass"},
    {"verdict_class": core.CLASS_QUERY, "word": "Fail"},
    {
        "verdict_class": core.CLASS_NOTE,
        "subkind": "x",
        "verdict_label": "AI thinks: met",
    },
    {
        "verdict_class": core.CLASS_NOTE,
        "subkind": "x",
        "verdict_label": "AI thinks: not met",
    },
    {"verdict_class": core.CLASS_NOTE, "subkind": "x", "word": "AI thinks"},
    {"verdict_class": core.CLASS_NOTE, "subkind": "x", "decided_by": "Proven by code"},
    {"verdict_class": core.CLASS_QUERY, "ai_verdict": "Fail"},
    {"verdict_class": core.CLASS_QUERY, "source": "rule"},
    {"verdict_class": core.CLASS_QUERY, "item_id": "R-123"},
    {"verdict_class": core.CLASS_NOTE},
    {"verdict_class": core.CLASS_QUERY, "part": 9},
    {"verdict_class": core.CLASS_QUERY, "part": None},
    {"verdict_class": "Query for the engineer ", "part": 3},
    {"verdict_class": core.CLASS_QUERY, "text": "Fail: the paper does not say"},
    {"verdict_class": core.CLASS_QUERY, "text": "AI thinks: not met"},
]


@pytest.mark.parametrize("bad", BAD)
def test_the_exit_refuses_pass_fail_ai_thinks_proven_by_code_and_rule_items(bad):
    with pytest.raises(core.GeneralModeViolation):
        core.finalize_line(
            {"text": "x", "part": 3, **bad}
            if "part" not in bad
            else {"text": "x", **bad}
        )


def test_a_sentence_that_merely_contains_a_verdict_word_is_ordinary_prose():
    out = core.finalize_line(
        {
            "verdict_class": core.CLASS_NOTE,
            "subkind": "s",
            "part": 5,
            "text": "The valve may pass a failure test.",
        }
    )
    assert out["word"] == "AI note" and out["internal_only"] is True


def test_the_exit_sets_the_word_of_each_of_the_four_classes_and_marks_internal():
    assert set(core.CLASSES) == {
        "Not checked: rule book not held",
        "AI note, no rule book",
        "Query for the engineer",
        "Not reviewed",
    }
    for cls, word in core.WORD_OF.items():
        out = core.finalize_line(
            {"verdict_class": cls, "subkind": "s", "text": "t", "part": 2}
        )
        assert out["word"] == word and out["internal_only"] is True


def test_the_writer_takes_nothing_that_skipped_the_exit(tmp_path):
    forged = {
        "verdict_class": "Proven by code",
        "text": "forged",
        "part": 3,
        "line_id": "x",
        "word": "Pass",
    }
    with pytest.raises(core.GeneralModeViolation):
        agent_general_crs.write_all(
            [forged], tmp_path / "f", {"paper": "p", "run_id": "r", "date": "d"}, [], {}
        )


# ---------------------------------------------------------------- the mode decision


def _conn_with(tmp_path, monkeypatch, pages=PAGES):
    s.setup_world(tmp_path, monkeypatch)
    submittal_review.ensure_schema()
    with db.connect() as conn:
        _add(conn, PAPER, "procedure.pdf", pages)
        conn.commit()
    monkeypatch.setattr(agent_general_review, "_kind_rule_books", lambda _k: [])
    return db.connect()


def test_decide_mode_kind_first_unknown_datasheet_and_other_kinds_are_refused(
    tmp_path, monkeypatch
):
    conn = _conn_with(tmp_path, monkeypatch)
    for kind, known in (
        ("procedure", False),
        (None, True),
        ("datasheet", True),
        ("drawing", True),
        ("calculation", True),
        ("other", True),
    ):
        got = core.decide_mode(conn, PAPER, kind, known)
        assert got["ok"] is False and got["message"].startswith("REFUSED"), kind
    assert core.decide_mode(conn, PAPER, "procedure")["ok"] is True
    assert core.decide_mode(conn, PAPER, "contract")["ok"] is True


def test_decide_mode_refuses_a_paper_with_no_readable_text(tmp_path, monkeypatch):
    conn = _conn_with(tmp_path, monkeypatch, pages={1: "short"})
    got = core.decide_mode(conn, PAPER, "procedure")
    assert got["ok"] is False and "no readable page text" in got["message"]


def _held_book(conn, with_rule_of_kind: str | None):
    _add(
        conn,
        BOOK,
        "IEC 61511.pdf",
        {1: "4.1 The invented clause shall be applied by the team in every case."},
    )
    conn.execute(
        "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, created_at, updated_at)"
        " VALUES ('req-1', ?, '4.1', 1, 'The invented clause shall be applied.', 'x', 'x')",
        (BOOK,),
    )
    if with_rule_of_kind:
        s.label_rows(conn, ["1"])
        conn.execute(
            "UPDATE rule_label SET paper_kind = ? WHERE rule_ref = 'req-1'",
            (with_rule_of_kind,),
        )
    conn.commit()


def _cites(
    conn,
    text="This procedure follows IEC 61511 and API 521 in every study it makes for the plant. "
    * 3,
):
    conn.execute(
        "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = 1",
        (" " + text, PAPER),
    )
    conn.commit()


def test_a_held_cited_book_without_an_approved_rule_of_this_kind_is_named_as_not_used(
    tmp_path, monkeypatch
):
    conn = _conn_with(tmp_path, monkeypatch)
    _cites(conn)
    _held_book(conn, "datasheet")  # approved, but for another kind of paper
    got = core.decide_mode(conn, PAPER, "procedure")
    assert (
        got["ok"]
        and list(got["held_not_fit"].values()) == ["IEC 61511"]
        and got["held_fit"] == {}
    )
    assert [b["rule_book"] for b in got["not_held"]] == ["API 521"]


def test_a_held_book_with_approved_rules_of_this_kind_still_runs_and_says_so_in_one_true_line(
    world,
):
    conn = db.connect()
    _cites(conn)
    _held_book(conn, "procedure")
    got = core.decide_mode(conn, PAPER, "procedure")
    assert (
        got["ok"]
        and list(got["held_fit"].values()) == ["IEC 61511"]
        and got["held_not_fit"] == {}
    )
    g, _runner = build(world, GFake(), books=got)
    g.part1()
    fit = [ln for ln in g.lines if ln.get("held_rule_books")]
    assert [ln["text"] for ln in fit] == [
        "rule books we hold that fit this paper were not used: rule review for this kind is switched off"
    ]
    assert fit[0]["verdict_class"] == core.CLASS_NOT_CHECKED and fit[0][
        "held_rule_books"
    ] == ["IEC 61511"]


def test_held_books_that_do_not_fit_leave_a_line_on_the_crs_not_a_silent_drop(world):
    g, _r = build(
        world,
        GFake(),
        books={"not_held": [], "held_not_fit": {"d": "IEC 61511"}, "held_fit": {}},
    )
    g.part1()
    [ln] = g.lines
    assert (
        "not used in this general review" in ln["text"]
        and "IEC 61511" in ln["text"]
        and ln["part"] == 1
    )


# ---------------------------------------------------------------- a full run: classes, parts, the three outputs


def test_a_full_run_has_the_four_classes_five_parts_and_exact_part_one_wording(world):
    fake = full_fake()
    g, runner = build(world, fake)
    lines = go(g, runner)
    assert {ln["verdict_class"] for ln in lines} <= set(core.CLASSES)
    assert all(
        ln["internal_only"] is True and not str(ln["item_id"]).startswith("R-")
        for ln in lines
    )
    assert [ln["text"] for ln in by_part(lines, 1)] == [
        "not checked against IEC 61511, rule book not held",
        "not checked against API 521, rule book not held",
    ]
    p2 = by_part(lines, 2)
    assert (
        len(p2) == 1
        and p2[0]["verdict_class"] == core.CLASS_QUERY
        and p2[0]["item_id"] == "G-003"
    )
    assert "not found" in p2[0]["text"] and "not met" not in p2[0]["text"]
    p3 = by_part(lines, 3)
    assert sorted(ln["subkind"] for ln in p3) == sorted(
        [core.SUB_SELF, core.SUB_REF, core.SUB_OPEN, core.SUB_COUNT]
    )
    assert g.dropped.as_json()["3"]["quote not verified"] == 1
    assert all(
        ln["quotes_verified_by_code"]
        and ln["word"] == "AI note"
        and ln["text_source"] == "the model's words"
        for ln in p3
    )
    assert {ln["verdict_class"] for ln in by_part(lines, 4)} == {
        core.CLASS_NOTE,
        core.CLASS_QUERY,
    }
    p5 = by_part(lines, 5)
    assert [ln["quote_a"]["text"] for ln in p5] == [Q_FORMS] and p5[0][
        "verdict_class"
    ] == core.CLASS_NOTE


def test_figures_are_compared_by_code_only_under_the_strict_rule(world):
    g, runner = build(world, full_fake())
    lines = go(g, runner)
    dis = next(ln for ln in by_part(lines, 3) if ln["subkind"] == core.SUB_SELF)
    cnt = next(ln for ln in by_part(lines, 3) if ln["subkind"] == core.SUB_COUNT)
    assert (
        dis["figures"] == "figures differ: by code"
        and cnt["figures"] == "not compared by code"
    )


@pytest.mark.parametrize(
    "a,b,label",
    [
        ("every 4 weeks", "is 8 weeks", "figures differ: by code"),
        ("5 bar", "6 bar", "figures differ: by code"),
        (
            "5 bar",
            "5 bar",
            "figures equal: by code (the disagreement is not about the figure)",
        ),
        ("10 mm", "1 cm", "not compared by code"),
        ("1.500 kg", "1500 kg", "not compared by code"),
        ("5", "5 bar", "not compared by code"),
        ("5 and 6 bar", "6 bar", "not compared by code"),
    ],
)
def test_figures_need_the_same_unit_and_no_doubt(a, b, label):
    assert core.figures_label("disagreement", a, b) == label


def test_an_unverified_quote_is_never_stored_returned_or_reviewed(world):
    fake = full_fake()
    g, runner = build(world, fake)
    lines = go(g, runner)
    assert "INVENTED words" not in json.dumps(lines)
    reviews = [
        b
        for b in fake.bodies
        if "independent senior engineer" in json.dumps(b["system"])
    ]
    assert "INVENTED words" not in json.dumps(reviews)
    assert g.dropped.as_json()["5"]["quote not verified"] == 1


def test_a_second_model_drop_an_error_or_the_same_family_is_never_shown(world):
    g, runner = build(
        world,
        full_fake(review=lambda _l: {"decision": "drop", "reason": "page explains it"}),
    )
    assert [ln for ln in go(g, runner) if ln["part"] in (3, 4)] == []
    assert g.dropped.as_json()["3"]["second model dropped"] == 4

    g, runner = build(
        world, full_fake(review=lambda _l: "not json at all"), run_name="r2"
    )
    assert [ln for ln in go(g, runner) if ln["part"] in (3, 4)] == []
    assert g.dropped.as_json()["3"]["second model gave no decision"] == 4

    g, runner = build(
        world, full_fake(second_name=LEAD), run_name="r3"
    )  # a model of the lead's own family
    assert [ln for ln in go(g, runner) if ln["part"] in (3, 4)] == []
    assert (
        g.dropped.as_json()["3"]["second model unknown or not a different family"] == 4
    )


def test_a_second_model_transport_error_is_never_shown(world, monkeypatch):
    fake = full_fake()

    def boom(url, *, headers, body, timeout):
        if "independent senior engineer" in json.dumps(body["system"]):
            raise OSError("down")
        return fake(url, headers=headers, body=body, timeout=timeout)

    g, runner = build(world, boom)
    assert [ln for ln in go(g, runner) if ln["part"] in (3, 4)] == []
    assert g.dropped.as_json()["3"]["second model error"] == 4


def test_silence_is_a_query_never_not_met_and_a_silent_finding_carries_no_paper_quote(
    world,
):
    g, runner = build(world, full_fake())
    lines = go(g, runner)
    silent = [ln for ln in lines if ln.get("subkind") == core.SUB_SILENT]
    assert (
        len(silent) == 1
        and silent[0]["verdict_class"] == core.CLASS_QUERY
        and silent[0]["quote_paper"] is None
    )
    assert silent[0]["text"].startswith(
        "the paper is silent on this requirement of doc_proj"
    )
    assert not any("not met" in ln["text"].lower() for ln in lines)


def test_no_rule_item_is_ever_built_or_asked(world):
    fake = full_fake()
    g, runner = build(world, fake)
    lines = go(g, runner)
    assert all(ln.get("source") != "rule" for ln in lines)
    assert "rule_quote" not in fake.texts() and "clause_quote" not in fake.texts()
    asked = [
        json.loads(b["messages"][0]["content"][-1]["text"].split("\n\n")[0])
        for b in fake.bodies
        if "COMPLETE for its kind" in json.dumps(b["system"])
    ]
    assert [i["item_id"] for i in asked[0]["checklist"]] == ["S-C1", "S-C2"]


def test_no_completeness_checklist_says_so_in_one_line_and_asks_nothing(world):
    fake = full_fake()
    g, runner = build(world, fake, items=[])
    lines = go(g, runner)
    [ln] = by_part(lines, 2)
    assert (
        ln["text"] == "no completeness checklist for this kind of paper"
        and ln["verdict_class"] == core.CLASS_NOT_REVIEWED
    )
    assert fake.calls_of("COMPLETE for its kind") == 0


def test_with_no_project_paper_part_four_writes_one_line_and_asks_nothing(world):
    fake = full_fake()
    g, runner = build(world, fake, project=())
    lines = go(g, runner)
    [ln] = by_part(lines, 4)
    assert (
        ln["text"] == "no project paper was given to check against"
        and fake.calls_of("PROJECT PAPERS") == 0
    )


def test_part_five_is_at_most_ten_comments_per_run_over_several_windows(
    world, monkeypatch
):
    quotes = [
        (1, "Test Procedure for Widget Review."),
        (1, "Section 1 scope."),
        (1, Q_A),
        (1, Q_TABLE),
        (2, "Section 2 team."),
        (2, Q_COUNT),
        (2, Q_ACTIONS),
        (2, "Closure is by e-mail."),
        (3, Q_B),
        (3, Q_FORMS),
        (3, "End of the invented paper"),
        (3, "signed by the chair"),
    ]
    turn = iter(range(3))

    def many(_l):
        i = next(turn)  # window i answers four distinct comments: 12 in all
        return {
            "comments": [
                {"quote": {"page": p, "text": t}, "comment": f"comment {p} {j}"}
                for j, (p, t) in enumerate(quotes[i * 4 : i * 4 + 4])
            ]
        }

    fake = GFake(p5=many)
    g, runner = build(world, fake, items=[], project=())
    g.window_tokens = 5  # one page per window
    lines = go(g, runner)
    assert (
        len(by_part(lines, 5)) == agent_general_parts.MAX_COMMENTS_P5 == 10
        and fake.calls_of("experienced engineer commenting") == 3
    )
    assert g.dropped.as_json()["5"]["over the limit of comments"] == 2


# ---------------------------------------------------------------- the three defects the scorer found


def test_defect_a_the_whole_text_of_a_line_is_stored_and_written_never_cut_at_200_characters(
    world,
):
    long_what = " ".join(
        ["measurement-of-the-review-interval"] * 20
    )  # 20 words, far above 200 characters
    assert len(long_what) > 600

    def p3(_l):
        return {
            "findings": [
                {
                    "kind": "open_action",
                    "quote_a": {"page": 2, "text": Q_ACTIONS},
                    "quote_b": None,
                    "what": long_what,
                    "severity": "low",
                }
            ]
        }

    g, runner = build(world, GFake(p3=p3), items=[], project=())
    lines = go(g, runner)
    [note] = by_part(lines, 3)
    assert note["text"] == long_what
    from app import agent_review_schema

    agent_review_schema.ensure_schema()
    agent_general_job.store_lines(db.connect(), "run-a", lines)
    stored = (
        db.connect()
        .execute(
            "SELECT reason FROM agent_review_line WHERE run_id = 'run-a' AND item_id = ?",
            (note["item_id"],),
        )
        .fetchone()[0]
    )
    assert stored == long_what
    agent_general_crs.write_all(
        lines, world / "out-a", {"paper": "p", "run_id": "r", "date": "d"}, [], {}
    )
    cells = [
        c.value
        for row in load_workbook(world / "out-a" / "crs-internal.xlsx")[
            "Evidence"
        ].iter_rows()
        for c in row
    ]
    assert (
        long_what in cells
    )  # the whole text, on the Evidence sheet (never in the comment)


@pytest.mark.parametrize(
    "status,words",
    [
        ("partial", "partly covered: the closure owner is not named"),
        ("absent", "not found in the paper"),
        ("unclear", "the AI could not tell whether the paper covers it"),
    ],
)
def test_defect_b_a_checklist_query_says_what_the_answer_was(world, status, words):
    def p2(_l):
        return {
            "answers": [
                {
                    "item_id": "S-C1",
                    "paper_page": 1,
                    "paper_quote": PAGES[1][:50],
                    "status": "present",
                    "note": "",
                    "concern": "",
                },
                {
                    "item_id": "S-C2",
                    "paper_page": 2,
                    "paper_quote": Q_ACTIONS,
                    "status": status,
                    "note": "the closure owner is not named",
                    "concern": "",
                },
            ]
        }

    g, runner = build(world, GFake(p2=p2), project=())
    [q] = by_part(go(g, runner), 2)
    assert q["verdict_class"] == core.CLASS_QUERY and words in q["text"]
    if status != "partial":
        assert "partly" not in q["text"]
    if status == "absent":
        assert "found nothing" not in q["text"]


def test_defect_b_a_present_answer_with_a_concern_becomes_an_ai_note_with_its_verified_quote(
    world,
):
    def p2(_l):
        return {
            "answers": [
                {
                    "item_id": "S-C1",
                    "paper_page": 1,
                    "paper_quote": Q_A,
                    "status": "present",
                    "note": "",
                    "concern": "four weeks is shorter than the interval of page 3",
                },
                {
                    "item_id": "S-C2",
                    "paper_page": 2,
                    "paper_quote": Q_ACTIONS,
                    "status": "present",
                    "note": "",
                    "concern": "  ",
                },
            ]
        }

    g, runner = build(world, GFake(p2=p2), project=())
    lines = by_part(go(g, runner), 2)
    [note] = lines
    assert (
        note["verdict_class"] == core.CLASS_NOTE and note["subkind"] == core.SUB_CONCERN
    )
    assert (
        note["quote_a"]["text"] == Q_A
        and note["quotes_verified_by_code"] is True
        and "four weeks" in note["text"]
    )
    assert g.part_counts[2]["covered_with_verified_quote"] == 1


def test_defect_b_a_concern_beside_a_quote_that_does_not_verify_is_only_a_query(world):
    def p2(_l):
        return {
            "answers": [
                {
                    "item_id": "S-C1",
                    "paper_page": 1,
                    "paper_quote": "INVENTED quote",
                    "status": "present",
                    "note": "",
                    "concern": "something is wrong",
                },
                {
                    "item_id": "S-C2",
                    "paper_page": 2,
                    "paper_quote": Q_ACTIONS,
                    "status": "present",
                    "note": "",
                    "concern": "",
                },
            ]
        }

    g, runner = build(world, GFake(p2=p2), project=())
    [q] = by_part(go(g, runner), 2)
    assert (
        q["verdict_class"] == core.CLASS_QUERY
        and "not verified by code" in q["text"]
        and "quote_a" not in q
    )


def _missing_p3(page, flag):
    return lambda _l: {
        "findings": [
            {
                "kind": "broken_reference",
                "quote_a": {"page": page, "text": {1: Q_TABLE, 3: Q_FORMS}[page]},
                "quote_b": None,
                "what": "The formula for the interval is missing from the paper.",
                "severity": "medium",
                "claims_missing": flag,
            }
        ]
    }


def test_defect_c_the_prompts_say_which_pages_were_not_read_as_text(world):
    fake = full_fake()
    g, runner = build(world, fake, unread=[3])
    go(g, runner)
    for marker in ("against ITSELF", "experienced engineer commenting"):
        sent = [b for b in fake.bodies if marker in json.dumps(b["system"])]
        assert sent and all(
            "Pages 3 hold pictures or formulas that were not read as text."
            in b["messages"][0]["content"][-1]["text"]
            for b in sent
        )
    quiet = full_fake()
    g, runner = build(world, quiet, run_name="r2")
    go(g, runner)
    assert "hold pictures or formulas" not in quiet.texts()


@pytest.mark.parametrize("flag", [True, False])
def test_defect_c_a_missing_claim_on_an_unread_page_is_a_query_not_a_note(world, flag):
    g, runner = build(
        world, GFake(p3=_missing_p3(3, flag)), items=[], project=(), unread=[3]
    )
    [q] = by_part(go(g, runner), 3)
    assert q["verdict_class"] == core.CLASS_QUERY and q["subkind"] == core.SUB_UNREAD
    assert q["text"].startswith(
        "could not be checked: the page holds pictures that were not read"
    )
    assert q["quote_a"]["text"] == Q_FORMS


def test_defect_c_a_missing_claim_on_a_page_that_was_read_stays_an_ai_note(world):
    g, runner = build(
        world, GFake(p3=_missing_p3(1, True)), items=[], project=(), unread=[3]
    )
    [n] = by_part(go(g, runner), 3)
    assert n["verdict_class"] == core.CLASS_NOTE


def test_defect_c_a_comment_that_claims_something_missing_on_an_unread_page_is_a_query(
    world,
):
    def p5(_l):
        return {
            "comments": [
                {
                    "quote": {"page": 3, "text": Q_FORMS},
                    "comment": "The formulas are missing here.",
                },
                {
                    "quote": {"page": 3, "text": Q_B},
                    "comment": "State the unit of the interval.",
                    "claims_missing": False,
                },
            ]
        }

    g, runner = build(world, GFake(p5=p5), items=[], project=(), unread=[3])
    a, b = by_part(go(g, runner), 5)
    assert (a["verdict_class"], a["subkind"]) == (
        core.CLASS_QUERY,
        core.SUB_UNREAD,
    ) and b["verdict_class"] == core.CLASS_NOTE


def test_unread_pages_are_read_from_the_extractor_flags_and_the_amount_of_text(world):
    with db.connect() as conn:
        _add(
            conn,
            "doc_flags",
            "flags.pdf",
            {1: "x" * 300, 2: "y" * 300, 3: "z" * 300, 4: "tiny"},
        )
        conn.execute(
            "UPDATE pages SET needs_ocr = 1 WHERE document_id = 'doc_flags' AND page_no = 2"
        )
        conn.execute(
            "UPDATE pages SET equation_heavy = 1 WHERE document_id = 'doc_flags' AND page_no = 3"
        )
        conn.commit()
        assert core.unread_pages(conn, "doc_flags") == [2, 3, 4]
        assert core.unread_pages(conn, PAPER) == []
    assert (
        core.picture_fact([]) == ""
        and core.picture_fact([4, 2])
        == "Pages 2, 4 hold pictures or formulas that were not read as text."
    )


# ---------------------------------------------------------------- part 4: the project papers


def test_part_four_quotes_both_papers_and_marks_a_second_quote_that_does_not_relate(
    world,
):
    g, runner = build(
        world,
        full_fake(
            review=lambda _l: {
                "decision": "keep",
                "reason": "ok",
                "quotes_relate": "no",
            }
        ),
    )
    lines = by_part(go(g, runner), 4)
    note = next(ln for ln in lines if ln["verdict_class"] == core.CLASS_NOTE)
    assert (
        note["subkind"] == core.SUB_ENGINEERING
        and note["quote_other"] is None
        and "do not relate" in note["text"]
    )
    ok_g, ok_runner = build(world, full_fake(), run_name="r2")
    ok = next(
        ln
        for ln in by_part(go(ok_g, ok_runner), 4)
        if ln["verdict_class"] == core.CLASS_NOTE
    )
    assert (
        ok["subkind"] == "disagrees with doc_proj"
        and ok["quote_other"]["text"] == Q_REQ
    )


def test_a_project_paper_outside_the_carrier_is_refused_before_any_call(world):
    fake = full_fake()
    with pytest.raises(core.Refused):
        build(
            world, fake, carrier=[PAPER]
        )  # the project paper is not in what the run declares
    with pytest.raises(core.Refused):
        core.Documents([PAPER], PAPER, {PAPER: PAGES}).pages(OTHER)
    assert fake.bodies == []


def test_another_document_text_is_never_in_a_request(world):
    fake = full_fake()
    g, runner = build(world, fake)
    go(g, runner)
    assert "SECRET" not in fake.texts() and OTHER not in fake.texts()


def test_project_papers_must_be_readable_by_the_caller_not_the_paper_not_a_rule_book(
    world,
):
    conn = db.connect()
    _held_book(conn, None)
    _add(conn, "doc_blank", "blank.pdf", {1: "   "})
    conn.commit()
    allowed = frozenset({PAPER, PROJ, BOOK, "doc_blank"})
    ok, problems = core.check_project_papers(conn, PAPER, [PROJ], allowed)
    assert ok == [{"document_id": PROJ, "name": "project-paper.pdf"}] and problems == []
    for bad, why in (
        (OTHER, "no such document"),
        ("nope", "no such document"),
        (PAPER, "the paper itself"),
        (BOOK, "rule book"),
        ("doc_blank", "no stored page text"),
    ):
        got, problems = core.check_project_papers(conn, PAPER, [bad], allowed)
        assert got == [] and why in problems[0], (
            bad
        )  # OTHER is real but outside the caller's scope: the same words as unknown


def test_a_document_named_like_the_register_is_never_a_project_paper(world):
    conn = db.connect()
    key = (
        claude_approved.REGISTER_NAME_KEY
    )  # the register file name, spelled from the app's own key
    _add(
        conn,
        "doc_reg",
        f"{key[:11].title()} {key[11:].title()}.pdf",
        {1: "register text " * 20},
    )
    conn.commit()
    got, problems = core.check_project_papers(
        conn, PAPER, ["doc_reg"], frozenset({PAPER, "doc_reg"})
    )
    assert got == [] and "is not sent" in problems[0]


# ---------------------------------------------------------------- failures are Not reviewed, never a verdict


def test_a_cut_off_answer_is_not_reviewed_with_its_error_code_never_a_verdict(world):
    g, runner = build(world, full_fake(stop="max_tokens"))
    lines = go(g, runner)
    assert lines and {ln["verdict_class"] for ln in lines if ln["part"] != 1} == {
        core.CLASS_NOT_REVIEWED
    } - {None} | {core.CLASS_NOT_REVIEWED}
    assert any("stop_max_tokens" in ln["text"] for ln in lines)
    assert g.failures > 0 and not [
        ln for ln in lines if ln["verdict_class"] in (core.CLASS_NOTE,)
    ]


def test_an_unreadable_answer_is_not_reviewed_and_not_stored_so_a_resume_asks_again(
    world,
):
    fake = GFake(p3=lambda _l: "this is not json")
    g, runner = build(world, fake, items=[], project=())
    go(g, runner)
    assert any(
        ln["verdict_class"] == core.CLASS_NOT_REVIEWED
        and ln["part"] == 3
        and "not_json" in ln["text"]
        for ln in g.lines
    )
    assert not list((world / "r1" / "steps").glob("p3-*"))


def test_a_resumed_run_pays_nothing_twice(world):
    fake = full_fake()
    g, runner = build(world, fake)
    first = [ln["text"] for ln in go(g, runner)]
    calls = len(fake.bodies)
    assert calls > 0
    g2, runner2 = build(world, fake)  # the same run folder: the stored replies are used
    second = [ln["text"] for ln in go(g2, runner2)]
    assert len(fake.bodies) == calls and second == first


def test_a_cap_stop_asks_nothing_more_and_says_so(world, monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    fake = full_fake()
    g, runner = build(world, fake)
    lines = go(g, runner)
    assert fake.bodies == [] and g.stopped.startswith("app_step_cap")
    assert {ln["verdict_class"] for ln in lines if ln["part"] != 1} <= {
        core.CLASS_NOT_REVIEWED
    }


# ---------------------------------------------------------------- the job, end to end


@pytest.fixture
def job_world(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    fake = full_fake()
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    return fake


def start(project=(PROJ,)):
    run_id, job_id = agent_review_jobs.enqueue(
        PAPER,
        allowed_document_ids=frozenset({PAPER, PROJ, OTHER}),
        requested_by=None,
        project_document_ids=tuple(project),
    )
    assert agent_review_jobs.claim_next("w") == job_id
    return run_id, job_id


def lines_of(run_id):
    rows = (
        db.connect()
        .execute("SELECT * FROM agent_review_line WHERE run_id = ?", (run_id,))
        .fetchall()
    )
    return {r["item_id"]: dict(r) for r in rows}


def test_the_job_runs_a_general_review_stores_lines_and_names_the_project_papers(
    job_world,
):
    run_id, job_id = start()
    assert agent_review_jobs.run(job_id, "w") == "done"
    rows = lines_of(run_id)
    assert {r["verdict_class"] for r in rows.values()} <= set(core.CLASSES)
    assert not {r["word"] for r in rows.values()} & {
        "Pass",
        "Fail",
        "AI thinks: met",
        "AI thinks: not met",
    }
    assert {r["part"] for r in rows.values()} == set(core.PART_WORDS.values())
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (
        (run["paper_kind"], run["rule_set_changed_by"]) == ("procedure", None)
        and run["usd"] > 0
        and run["partial"] == 0
    )
    general = (
        db.connect()
        .execute("SELECT * FROM agent_review_general WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert json.loads(general["project_json"]) == [
        {"document_id": PROJ, "name": "project-paper.pdf"}
    ]
    assert (
        not db.connect()
        .execute("SELECT 1 FROM agent_review_rule WHERE run_id = ?", (run_id,))
        .fetchone()
    )  # no rule was built
    assert [
        r["name"]
        for r in db.connect().execute(
            "SELECT name FROM agent_review_missing_book WHERE run_id = ?", (run_id,)
        )
    ] == ["IEC 61511"]


def test_the_job_declares_only_the_paper_and_the_named_project_papers(
    job_world, monkeypatch
):
    seen = []

    def stop(*_a, **_k):
        seen.append(claude_approved.carried())
        raise agent_claude.AgentBudgetStop("stop_for_test")

    monkeypatch.setattr(agent_claude, "_call", stop)
    _run, job_id = start()
    agent_review_jobs.run(job_id, "w")
    assert seen and set(seen) == {frozenset({PAPER, PROJ})}


def test_contractor_and_comment_only_copies_are_empty_whatever_the_lines_are(job_world):
    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    folder = agent_review_jobs.run_dir(run_id)
    for name in ("crs-contractor.xlsx", "crs-scoring-comment-only.xlsx"):
        wb = load_workbook(folder / name)
        assert wb.sheetnames == ["CRS"]
        rows = [[c.value for c in row] for row in wb["CRS"].iter_rows()]
        head = next(i for i, r in enumerate(rows) if r[0] == "Item No")
        assert (
            rows[head + 1 :] == []
        )  # nine columns, no rows: a general review proves no Fail
        assert len([c for c in rows[head] if c]) == 9
    internal = load_workbook(folder / "crs-internal.xlsx")
    assert internal.sheetnames == [
        "CRS",
        "Not reviewed or not applicable",
        "Evidence",
        "Notes",
    ]
    notes = {r[0].value: r[1].value for r in internal["Notes"].iter_rows(min_row=2)}
    assert notes["Papers used"] not in ("", core.NO_PROJECT_PAPER)


def test_a_resumed_job_does_not_pay_twice_and_replaces_its_own_lines(job_world):
    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    first = lines_of(run_id)
    calls = len(job_world.bodies)
    agent_general_job.run(
        run_id,
        PAPER,
        frozenset({PAPER, PROJ}),
        reading(),
        "2026-11-11T00:00:00Z",
        folder=agent_review_jobs.run_dir(run_id),
        name="procedure.pdf",
        lane=lambda: (job_world, s.ENV),
    )
    assert len(job_world.bodies) == calls
    assert {k: v["reason"] for k, v in lines_of(run_id).items()} == {
        k: v["reason"] for k, v in first.items()
    }


def test_a_project_paper_the_approved_list_refuses_stops_the_run_before_any_call(
    job_world, monkeypatch
):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    claude_approved.list_path().write_text(
        json.dumps({"documents": []}), encoding="utf-8"
    )
    run_id, job_id = start()
    assert agent_review_jobs.run(job_id, "w") == "done"
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert job_world.bodies == [] and run["usd"] is None and run["partial"] == 1
    assert (
        run["stop_reason"].startswith("not_approved")
        and "owner question" in run["stop_reason"]
    )
    assert {
        r["verdict_class"] for r in lines_of(run_id).values() if r["part"] != "not held"
    } == {core.CLASS_NOT_REVIEWED}


def test_a_project_paper_the_requester_may_not_read_refuses_the_run_before_any_call(
    job_world, monkeypatch
):
    run_id, job_id = start(project=(OTHER,))
    monkeypatch.setattr(
        agent_review_jobs.review_jobs, "_scope_of", lambda _u: frozenset({PAPER})
    )
    assert agent_review_jobs.run(job_id, "w") == "done"
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (
        job_world.bodies == []
        and run["stop_reason"].startswith("refused: project paper refused")
        and lines_of(run_id) == {}
    )


def test_the_decide_path_refuses_what_the_gate_does_not_name_even_inside_the_job(
    job_world, monkeypatch
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading(kind="drawing")
    )
    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    assert job_world.bodies == [] and lines_of(run_id) == {}


def test_a_datasheet_still_goes_to_the_rule_review_not_the_general_one(
    job_world, monkeypatch
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading(kind="datasheet")
    )
    called = []
    monkeypatch.setattr(agent_general_job, "run", lambda *a, **k: called.append(1))
    monkeypatch.setattr(
        agent_review_jobs,
        "_plan",
        lambda *a, **k: {"block": {}, "items": [], "cache": {}, "stop": "x"},
    )
    run_id, job_id = agent_review_jobs.enqueue(
        PAPER, allowed_document_ids=frozenset({PAPER}), requested_by=None
    )
    agent_review_jobs.claim_next("w")
    agent_review_jobs.run(job_id, "w")
    assert (
        called == []
        and not db.connect()
        .execute("SELECT 1 FROM agent_review_general WHERE run_id = ?", (run_id,))
        .fetchone()
    )


# ---------------------------------------------------------------- the routes


@pytest.fixture
def client(job_world):
    return TestClient(app, base_url="http://127.0.0.1")


def post(client, **body):
    return client.post(
        "/api/reviews/agent-run", json={"submittal_document_id": PAPER, **body}
    )


def jobs_count():
    return (
        db.connect()
        .execute("SELECT COUNT(*) FROM jobs WHERE stage = 'agent_review'")
        .fetchone()[0]
    )


@pytest.mark.parametrize("kind", ["procedure", "contract"])
def test_a_procedure_or_a_contract_is_queued_for_the_general_review(
    client, monkeypatch, kind
):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading(kind=kind)
    )
    r = post(client, project_document_ids=[PROJ])
    assert r.status_code == 200 and r.json()["status"] == "queued"
    row = (
        db.connect()
        .execute("SELECT requested_json FROM agent_review_general")
        .fetchone()
    )
    assert json.loads(row[0]) == [PROJ]


@pytest.mark.parametrize("kind", ["drawing", "calculation", "other", "unknown"])
def test_every_other_kind_stays_409_kind_not_enabled_with_no_job(
    client, monkeypatch, kind
):
    monkeypatch.setattr(
        agent_review_kind,
        "decide",
        lambda *_a, **_k: reading(kind=kind, known=kind != "unknown"),
    )
    r = post(client)
    assert (
        r.status_code == 409
        and r.json()["detail"]["code"] == "kind_not_enabled"
        and jobs_count() == 0
    )


def test_project_papers_belong_to_a_general_review_only(client, monkeypatch):
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading(kind="datasheet")
    )
    r = post(client, project_document_ids=[PROJ])
    assert r.status_code == 422 and jobs_count() == 0


def test_a_project_paper_outside_the_callers_scope_is_a_404_before_any_job(
    client, monkeypatch
):
    scope = access.AccessScope(
        user_id="u1", allowed_document_ids=frozenset({PAPER, PROJ})
    )
    app.dependency_overrides[access.current_scope] = lambda: scope
    try:
        r = post(client, project_document_ids=[OTHER])
        again = post(client, project_document_ids=["no-such-document"])
    finally:
        app.dependency_overrides.pop(access.current_scope, None)
    assert (
        r.status_code == 404
        and again.status_code == 404
        and r.json()["detail"]["message"] == again.json()["detail"]["message"]
        and jobs_count() == 0
    )


def test_a_rule_book_or_the_paper_itself_as_a_project_paper_is_a_422_before_any_job(
    client,
):
    with db.connect() as conn:
        _held_book(conn, None)
    assert post(client, project_document_ids=[BOOK]).status_code == 422
    assert post(client, project_document_ids=[PAPER]).status_code == 422
    assert jobs_count() == 0


def test_switch_off_is_a_404_and_no_table_for_a_general_review_request(
    tmp_path, monkeypatch
):
    s.setup_world(tmp_path, monkeypatch, on=False)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.post(
        "/api/reviews/agent-run",
        json={"submittal_document_id": s.PAPER, "project_document_ids": ["x"]},
    )
    assert r.status_code == 404
    names = {
        row[0]
        for row in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert not [n for n in names if n.startswith("agent_review_")]
    assert agent_review_jobs.claim_next("w") is None


def _snapshot():
    conn = db.connect()
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    return {
        n: conn.execute(
            f'SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(rowid AS TEXT))), 0) FROM "{n}"'
        ).fetchone()[:]
        for n in names
    }


def test_the_get_routes_show_mode_parts_projects_and_the_trace_and_write_nothing(
    client, monkeypatch
):
    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    before = _snapshot()
    summary = client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()
    assert summary["mode"] == "general review" and summary["project_papers_used"] == [
        {"document_id": PROJ, "name": "project-paper.pdf"}
    ]
    assert summary["paper_kind"] == "procedure" and set(
        summary["counts_by_class"]
    ) <= set(core.CLASSES)
    lines = client.get(f"/api/reviews/runs/{run_id}/agent/lines").json()["lines"]
    assert {ln["part"] for ln in lines} == set(core.PART_WORDS.values()) and all(
        ln["rule_tier"] is None for ln in lines
    )
    note = next(
        ln
        for ln in lines
        if ln["verdict_class"] == core.CLASS_NOTE
        and ln["part"] == "paper against itself"
    )
    assert note["text_source"] == "the model's words" and note["word"] == "AI note"
    trace = client.get(
        f"/api/reviews/runs/{run_id}/agent/lines/{note['item_id']}/trace"
    ).json()
    assert (
        trace["part"] == "paper against itself"
        and trace["paper_quote"]
        and any(g["step"] == "quote verified by code" for g in trace["gate"])
    )
    assert (
        client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=internal").status_code
        == 200
    )
    assert client.get(f"/api/reviews/runs/{run_id}/rules-used").json()["asked"] == []
    assert _snapshot() == before


def test_a_rule_review_run_still_says_rule_review_with_no_project_papers(
    tmp_path, monkeypatch
):
    import tests.test_agent_review_job as job_tests

    s.setup_world(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    from app import agent_review_schema

    agent_review_schema.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, started_at)"
            " VALUES ('r', ?, 'datasheet', 'k', 'x')",
            (s.PAPER,),
        )
    from app.api import agent_review as route

    assert route._mode_of(db.connect(), "r") == {
        "mode": "rule review",
        "project_papers_used": [],
    }
    assert job_tests is not None


# ---------------------------------------------------------------- the gate, the call site, the tables


def test_the_gate_names_procedure_and_contract_for_general_review_behind_the_same_switch():
    assert agent_review_gate.AGENT_GENERAL_REVIEW_KINDS == ("procedure", "contract")
    assert agent_review_gate.AGENT_REVIEW_KINDS == ("datasheet",)
    for kind in ("procedure", "contract", "Procedure"):
        assert agent_review_gate.general_kind_enabled(
            kind
        ) and agent_review_gate.any_kind_enabled(kind)
    for kind in (
        "datasheet",
        "drawing",
        "calculation",
        "other",
        "test_record",
        "unknown",
        None,
        "",
    ):
        assert not agent_review_gate.general_kind_enabled(kind)
    assert agent_review_gate.any_kind_enabled(
        "datasheet"
    ) and not agent_review_gate.any_kind_enabled("drawing")


def test_the_general_modules_never_call_claude_themselves_they_go_through_the_declared_runner():
    """No entry in test_806's list is needed: no general module starts a call (the runner does, under the declaration of
    `agent_general_job`, which names the paper and the project papers through `claude_approved.carrying`)."""
    from pathlib import Path

    root = Path(agent_general_review.__file__).parent
    for n in ("review", "parts", "findings", "prompts", "job", "crs"):
        text = (root / f"agent_general_{n}.py").read_text(encoding="utf-8")
        for pattern in (
            "agent_claude._call(",
            "get_provider(",
            "ClaudeProvider(",
            "metered(",
            "transport(",
        ):
            assert pattern not in text, (n, pattern)
    assert "claude_approved.carrying(carrier)" in (
        root / "agent_general_job.py"
    ).read_text(encoding="utf-8")


def test_the_tables_refuse_a_general_line_with_a_tier_a_verdict_word_or_no_part(world):
    from app import agent_review_schema

    agent_review_schema.ensure_schema()
    conn = db.connect()
    ok = (
        "r",
        "i",
        "AI note, no rule book",
        "AI note",
        None,
        "x",
        "{}",
        "x",
        "engineering comment",
    )
    sql = (
        "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, rule_tier, reason, line_json, decided_at, part)"
        " VALUES (?,?,?,?,?,?,?,?,?)"
    )
    conn.execute(sql, ok)
    for bad in (
        (
            "r",
            "j",
            "AI note, no rule book",
            "AI note",
            "Owner",
            "x",
            "{}",
            "x",
            "engineering comment",
        ),
        ("r", "k", "AI note, no rule book", "AI note", None, "x", "{}", "x", None),
        (
            "r",
            "l",
            "AI note, no rule book",
            "Pass",
            None,
            "x",
            "{}",
            "x",
            "engineering comment",
        ),
        (
            "r",
            "m",
            "Query for the engineer",
            "AI note",
            None,
            "x",
            "{}",
            "x",
            "checklist",
        ),
        (
            "r",
            "n",
            "AI note, no rule book",
            "AI note",
            None,
            "x",
            "{}",
            "x",
            "a made up part",
        ),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, bad)


def test_the_modules_name_no_equipment_study_or_client_word_rule_13():
    from pathlib import Path

    root = Path(agent_general_review.__file__).parent
    text = " ".join(
        (root / f"agent_general_{n}.py").read_text(encoding="utf-8").lower()
        for n in ("review", "parts", "findings", "prompts", "job", "crs")
    )
    import re

    for word in (
        "hazop",
        "pump",
        "psv",
        "sif",
    ):
        assert not re.search(rf"\b{word}\b", text), word
    assert agent_general_prompts.PROMPT_VERSION == "general-review-v1"


def test_a_run_made_a_general_review_by_the_decided_kind_alone_still_says_general_review(
    job_world,
):
    """A run queued before the kind was confirmed has no request row: the job still records its mode."""
    run_id, job_id = agent_review_jobs.enqueue(
        PAPER, allowed_document_ids=frozenset({PAPER}), requested_by=None
    )
    agent_review_jobs.claim_next("w")
    agent_review_jobs.run(job_id, "w")
    from app.api import agent_review as route

    assert route._mode_of(db.connect(), run_id) == {
        "mode": "general review",
        "project_papers_used": [],
    }
    assert [
        ln["reason"]
        for ln in lines_of(run_id).values()
        if ln["part"] == "against project papers"
    ] == ["no project paper was given to check against"]


# ---------------------------------------------------------------- R17: wording on unread pages, quotes_relate, the unrelated comment


def test_a_silent_checklist_item_or_project_paper_on_a_paper_with_unread_pages_is_could_not_be_checked(
    world,
):
    g, runner = build(world, full_fake(), unread=[3])
    lines = go(g, runner)
    [q2] = by_part(lines, 2)
    assert (
        q2["text"]
        == "checklist: Closure: could not be checked: page 3 holds pictures that were not read"
    )
    assert "not found" not in q2["text"]
    silent = next(ln for ln in lines if ln.get("subkind") == core.SUB_SILENT)
    assert silent["text"].startswith(
        "could not be checked: page 3 holds pictures that were not read"
    )
    assert "is silent" not in silent["text"]


def test_a_missing_quotes_relate_answer_counts_as_not_related(world):
    g, runner = build(
        world, full_fake(review=lambda _l: {"decision": "keep", "reason": "ok"})
    )
    lines = go(g, runner)
    assert not [
        ln
        for ln in by_part(lines, 3)
        if ln["subkind"] in (core.SUB_SELF, core.SUB_COUNT)
    ]
    assert g.dropped.as_json()["3"]["second model: the two quotes do not relate"] == 2
    note = next(
        ln for ln in by_part(lines, 4) if ln["verdict_class"] == core.CLASS_NOTE
    )
    assert note["subkind"] == core.SUB_ENGINEERING and note["quote_other"] is None


def test_the_unrelated_comment_does_not_show_the_models_sentence_about_the_other_paper(
    world,
):
    reply = {
        "decision": "keep",
        "reason": "SENTENCE-ABOUT-OTHER",
        "quotes_relate": "no",
    }
    g, runner = build(world, full_fake(review=lambda _l: reply))
    note = next(
        ln for ln in by_part(go(g, runner), 4) if ln["verdict_class"] == core.CLASS_NOTE
    )
    assert "Actions lack the owner and date" not in json.dumps(note)
    assert (
        "SENTENCE-ABOUT-OTHER" not in json.dumps(note)
        and note["quote_paper"]["text"] == Q_ACTIONS
    )


# ---------------------------------------------------------------- R17 blocking: an older table shape is upgraded, data kept

OLD_LINE_SQL = """CREATE TABLE agent_review_line (
    run_id TEXT NOT NULL, item_id TEXT NOT NULL CHECK (length(item_id) > 0),
    verdict_class TEXT NOT NULL CHECK (verdict_class IN {classes}), word TEXT NOT NULL CHECK (word IN {words}),
    page INTEGER CHECK (page IS NULL OR page >= 1), clause TEXT, rule_book TEXT, reason TEXT,
    rule_tier TEXT CHECK (rule_tier IS NULL OR rule_tier IN ('Owner','Engineer','AI approved','Not AI approved')),
    line_json TEXT NOT NULL, trace_json TEXT, decided_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id),
    CHECK (word NOT IN ('Pass', 'Fail') OR verdict_class = 'Proven by code'),
    CHECK (word NOT IN ('Pass', 'Fail') OR rule_tier IS NULL OR rule_tier <> 'Not AI approved'))"""
OLD_CLASSES = (
    "Proven by code",
    "AI opinion, engineer to confirm",
    "AI opinion, rule not yet approved",
    "Query for the engineer",
    "Not applicable",
    "Not reviewed",
)
OLD_WORDS = (
    "Pass",
    "Fail",
    "AI thinks: met",
    "AI thinks: not met",
    "Query",
    "Not applicable",
    "Not reviewed",
)
OLD_ROWS = [
    (
        "old-run",
        "R-1",
        "Proven by code",
        "Pass",
        2,
        "4.1",
        "Book",
        "met",
        "AI approved",
    ),
    (
        "old-run",
        "R-2",
        "Query for the engineer",
        "Query",
        None,
        "4.2",
        "Book",
        "why",
        None,
    ),
    (
        "old-run",
        "R-3",
        "Not reviewed",
        "Not reviewed",
        None,
        "",
        "Book",
        "no answer",
        "Owner",
    ),
]


def _old_shape(conn):
    """The line table exactly as the reviewer job PR made it (no part, no text_source, the narrow CHECKs), with rows."""
    quote = lambda t: "(" + ",".join("'" + x.replace("'", "''") + "'" for x in t) + ")"  # noqa: E731
    conn.execute(
        OLD_LINE_SQL.format(classes=quote(OLD_CLASSES), words=quote(OLD_WORDS))
    )
    conn.execute(
        "CREATE INDEX agent_review_line_run ON agent_review_line (run_id, item_id)"
    )
    for r in OLD_ROWS:
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason,"
            " rule_tier, line_json, decided_at) VALUES (?,?,?,?,?,?,?,?,?,'{}','2026-11-11')",
            r,
        )
    conn.commit()


def _rows(conn, table):
    return [
        tuple(r)
        for r in conn.execute(
            f'SELECT run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier FROM "{table}" ORDER BY item_id'
        )
    ]


def test_an_older_line_table_is_upgraded_in_one_step_with_every_row_kept_and_the_old_table_kept(
    job_world,
):
    from app import agent_review_schema as sch

    conn = db.connect()
    _old_shape(conn)
    assert (
        sch.line_shape_is_old(conn)
        and not sch.has_tables(conn)
        and sch.shape_problem(conn)
    )
    sch.ensure_schema()
    assert (
        not sch.line_shape_is_old(conn)
        and sch.has_tables(conn)
        and sch.shape_problem(conn) is None
    )
    assert _rows(conn, "agent_review_line") == [tuple(r) for r in OLD_ROWS]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM agent_review_line WHERE part IS NOT NULL OR text_source IS NOT NULL"
        ).fetchone()[0]
        == 0
    )
    [old] = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'agent_review_line_before_general_%'"
        )
    ]
    assert _rows(conn, old) == [tuple(r) for r in OLD_ROWS]  # nothing was deleted
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'agent_review_line_run' AND tbl_name = 'agent_review_line'"
    ).fetchone()
    event = conn.execute(
        "SELECT resource_id, detail FROM audit_events WHERE action = 'agent_review_tables_upgraded'"
    ).fetchone()
    assert event["resource_id"] == old and "rows copied: 3" in event["detail"]
    sch.ensure_schema()  # a second call changes nothing
    assert conn.execute("SELECT COUNT(*) FROM agent_review_line").fetchone()[0] == 3


def test_after_the_upgrade_the_routes_serve_old_and_new_runs_and_a_general_run_stores_its_lines(
    client,
):
    conn = db.connect()
    _old_shape(conn)
    conn.execute(
        "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('old-run', ?, 'completed', 'x', 'x')",
        (PAPER,),
    )
    conn.commit()
    got = client.get(
        "/api/reviews/runs/old-run/agent/lines"
    )  # the first request upgrades the table (data kept)
    assert (
        got.status_code == 404
    )  # no agent_review_run row for it yet: but no 500, and the table is upgraded
    from app import agent_review_schema as sch

    assert sch.has_tables(db.connect())
    db.connect().execute(
        "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, started_at) VALUES ('old-run', ?, 'datasheet', 'k', 'x')",
        (PAPER,),
    )
    db.connect().commit()
    old = client.get("/api/reviews/runs/old-run/agent/lines").json()["lines"]
    assert [(ln["item_id"], ln["word"], ln["part"]) for ln in old] == [
        ("R-1", "Pass", None),
        ("R-2", "Query", None),
        ("R-3", "Not reviewed", None),
    ]
    assert (
        client.get("/api/reviews/runs/old-run/agent/summary").json()["mode"]
        == "rule review"
    )
    r = post(client, project_document_ids=[PROJ])
    assert r.status_code == 200
    job_id = agent_review_jobs.claim_next("w")
    assert agent_review_jobs.run(job_id, "w") == "done"
    new_id = r.json()["id"] if "id" in r.json() else r.json()["review_run_id"]
    got = client.get(f"/api/reviews/runs/{new_id}/agent/lines").json()["lines"]
    assert got and {ln["part"] for ln in got} >= {"not held", "paper against itself"}
    assert (
        client.get(f"/api/reviews/runs/{new_id}/agent/summary").json()["mode"]
        == "general review"
    )


def _failing_copy(monkeypatch):
    from app import agent_review_schema as sch

    def boom(*_a, **_k):
        raise sqlite3.IntegrityError("boom")

    monkeypatch.setattr(sch, "_copy_old_rows", boom)


def test_a_copy_that_fails_rolls_back_and_every_route_answers_503(client, monkeypatch):
    conn = db.connect()
    _old_shape(conn)
    _failing_copy(monkeypatch)
    for url in (
        "/api/reviews/runs/x/agent/lines",
        "/api/reviews/runs/x/agent/summary",
        "/api/reviews/agent-status",
    ):
        r = client.get(url)
        assert (
            r.status_code == 503
            and r.json()["detail"] == "the AI review tables could not be upgraded: boom"
        )
    assert post(client).status_code == 503
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'agent_review%'"
        )
    ]
    assert names == ["agent_review_line"] and _rows(conn, "agent_review_line") == [
        tuple(r) for r in OLD_ROWS
    ]
    assert not conn.execute(
        "SELECT 1 FROM audit_events WHERE action = 'agent_review_tables_upgraded'"
    ).fetchone()


@pytest.mark.parametrize("kind", ["procedure", "datasheet"])
def test_a_queued_run_on_a_table_that_cannot_be_upgraded_is_refused_before_any_call(
    job_world, monkeypatch, kind
):
    """The shape is checked before the first Claude call: the fake model is asked nothing, nothing is paid."""
    monkeypatch.setattr(
        agent_review_kind, "decide", lambda *_a, **_k: reading(kind=kind)
    )
    from app import agent_review_schema as sch

    with (
        monkeypatch.context() as quiet
    ):  # queued before the tables exist: the old shape appears afterwards
        quiet.setattr(sch, "ensure_schema", lambda *_a: None)
        _run_id, job_id = agent_review_jobs.enqueue(
            PAPER, allowed_document_ids=frozenset({PAPER}), requested_by=None
        )
    assert agent_review_jobs.claim_next("w") == job_id
    _old_shape(db.connect())
    _failing_copy(monkeypatch)
    agent_review_jobs.run(job_id, "w")
    assert job_world.bodies == []
    assert (
        db.connect().execute("SELECT COUNT(*) FROM agent_review_line").fetchone()[0]
        == 3
    )


def test_the_preflights_of_both_reviews_refuse_an_old_shape_before_any_call(job_world):
    from app import agent_review_schema as sch

    conn = db.connect()
    _old_shape(conn)
    problem = sch.shape_problem(conn)
    assert agent_general_job.preflight({"ok": True}, [], problem) == problem
    assert (
        agent_review_jobs.preflight(conn, PAPER, reading(kind="datasheet"), {}, {})
        == problem
    )


# ---------------------------------------------------------------- order 13: the general review writes the ONE layout


def _one_layout_lines():
    note = core.finalize_line(
        {"part": 3, "verdict_class": core.CLASS_NOTE, "subkind": core.SUB_SELF, "line_id": "n1", "document": "p.pdf",
         "text": "the interval differs between two sections",
         "quote_a": {"document": "p.pdf", "page": 1, "text": Q_A}, "quote_b": {"document": "p.pdf", "page": 3, "text": Q_B},
         "quotes_verified_by_code": True, "figures": "figures differ: by code"}
    )  # fmt: skip
    query = core.finalize_line(
        {"part": 2, "verdict_class": core.CLASS_QUERY, "subkind": core.SUB_CHECKLIST, "line_id": "q1", "document": "p.pdf",
         "topic": "owner of each action", "text": "checklist: owner of each action: not found in the paper"}
    )  # fmt: skip
    held = core.finalize_line(
        {"part": 1, "verdict_class": core.CLASS_NOT_CHECKED, "subkind": None, "line_id": "h1", "document": "p.pdf",
         "text": "not checked against IEC 61511, rule book not held", "rule_book": "IEC 61511"}
    )  # fmt: skip
    return [held, query, note]


def test_the_general_review_writes_the_one_layout_with_the_three_part_comment(tmp_path):
    agent_general_crs.write_all(
        _one_layout_lines(),
        tmp_path,
        {"paper": "p.pdf", "run_id": "r", "date": "d"},
        [],
        {},
    )
    wb = load_workbook(tmp_path / "crs-internal.xlsx")
    rows = [[c.value for c in r] for r in wb["CRS"].iter_rows()]
    head = next(i for i, r in enumerate(rows) if r[0] == "Item No")
    assert rows[head][-1] == "Status" and len([c for c in rows[head] if c]) == 10
    body = rows[head + 1 :]
    assert [r[-1] for r in body] == ["AI opinion", "Query"]  # never Pass, never Fail
    note_cell, query_cell = body[0][3], body[1][3]
    assert note_cell.startswith(
        "The paper must agree with itself"
    ) and note_cell.endswith("confirm or correct it.")
    assert f'"{Q_A}", page 1' in note_cell and f'"{Q_B}", page 3' in note_cell
    assert (
        "not proven by code" in note_cell
        and "Figures: figures differ: by code" in note_cell
    )
    assert query_cell.startswith(
        "Contractor to confirm owner of each action"
    )  # a question is worded so
    assert [r[8] for r in body] == [
        "Medium",
        "Low",
    ]  # no rule is mandatory in a mode with no rule book
    assert (
        wb["Not reviewed or not applicable"]["E2"].value
        == "Not checked: rule book not held"
    )
    assert {"Evidence", "Notes"} <= set(wb.sheetnames)


def test_the_general_review_contractor_copy_holds_nine_columns_and_no_row(tmp_path):
    agent_general_crs.write_all(
        _one_layout_lines(),
        tmp_path,
        {"paper": "p.pdf", "run_id": "r", "date": "d"},
        [],
        {},
    )
    rows = [
        [c.value for c in r]
        for r in load_workbook(tmp_path / "crs-contractor.xlsx")["CRS"].iter_rows()
    ]
    head = next(i for i, r in enumerate(rows) if r[0] == "Item No")
    assert len([c for c in rows[head] if c]) == 9 and rows[head + 1 :] == []
    assert not any("Query" in str(c) or "AI opinion" in str(c) for r in rows for c in r)


def _cells(path, sheet="CRS"):
    return [[c.value for c in r] for r in load_workbook(path)[sheet].iter_rows()]


def test_the_contractor_copies_carry_the_datasheet_header_and_no_verdict_word(tmp_path):
    agent_general_crs.write_all(
        _one_layout_lines(),
        tmp_path,
        {"paper": "p.pdf", "run_id": "r", "date": "d"},
        [],
        {},
    )
    for name in agent_general_crs.COPY_NAMES:
        rows = _cells(tmp_path / name)
        labels = [r[0] for r in rows if r[0] and str(r[0]).endswith(":")]
        assert labels == [
            "Project:", "Document number:", "Document title:", "Revision:", "Date:", "Discipline:",
            "Rule books used (rows shown):",
        ]  # fmt: skip
        text = " ".join(str(c) for r in rows for c in r if c)
        assert (
            "Pass" not in text
            and "Fail" not in text
            and "general review" not in text.lower()
        )
    notes = " ".join(
        str(c) for r in _cells(tmp_path / "crs-internal.xlsx", "Notes") for c in r
    )
    assert (
        "no Pass or Fail" in notes
    )  # the explanation is on the internal Notes sheet only


def test_the_ai_free_text_never_enters_the_comment_only_the_evidence_sheet(tmp_path):
    lines = _one_layout_lines()
    lines[1]["topic"] = None
    lines[1]["text"] = "SENTINEL words of the model about the paper"
    agent_general_crs.write_all(
        lines, tmp_path, {"paper": "p.pdf", "run_id": "r", "date": "d"}, [], {}
    )
    crs = " ".join(
        str(c) for r in _cells(tmp_path / "crs-internal.xlsx") for c in r if c
    )
    assert "SENTINEL" not in crs
    ev = " ".join(
        str(c)
        for r in _cells(tmp_path / "crs-internal.xlsx", "Evidence")
        for c in r
        if c
    )
    assert "SENTINEL" in ev


def test_a_quote_that_code_did_not_verify_is_never_printed_as_what_the_paper_states(
    tmp_path,
):
    lines = _one_layout_lines()
    lines[2]["quotes_verified_by_code"] = False
    comment = agent_general_crs.comment_of(lines[2], "AI opinion")
    assert Q_A not in comment and "The paper states" not in comment
    assert agent_general_crs.NO_QUOTE in comment  # the neutral sentence, exactly


def test_the_neutral_sentence_is_exactly_the_one_ordered(tmp_path):
    assert (
        agent_general_crs.NO_QUOTE
        == "The AI reviewer holds no verified quote from the paper for this point."
    )
    ln = core.finalize_line(
        {"part": 5, "verdict_class": core.CLASS_NOTE, "subkind": core.SUB_ENGINEERING, "line_id": "x",
         "text": "t", "quotes_verified_by_code": True}
    )  # fmt: skip
    assert (
        agent_general_crs.comment_of(ln, "AI opinion")
        .split("\n")[1]
        .startswith(
            "The AI reviewer holds no verified quote from the paper for this point."
        )
    )
