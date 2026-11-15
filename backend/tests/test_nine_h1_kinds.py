"""H1: the nine roles for a kind of paper with no field list (the two small items of the HAZOP list): role 1 does not ask datasheet fields of it,
and the fixed texts have a closed wording per kind. Invented kinds and data; no model, no network."""

from __future__ import annotations

import itertools
import re
import types

import pytest

from app import kind_review_table as krt
from app import (
    nine_call,
    nine_context,
    nine_job,
    nine_librarian,
    nine_record,
    nine_reviewer,
    nine_support,
    nine_writer,
)
from app.nine_contract import RoleRecord, empty_record


def _ctx(kind, plan=None):
    return nine_job.RoleContext("run1", "doc1", kind, plan or {}, {}, lambda *a: None)


# ---------------------------------------------------------------- (1) the reader


def test_a_kind_has_a_field_list_by_its_row_not_by_its_name(monkeypatch):
    assert krt.has_field_list("datasheet") and not krt.has_field_list("procedure")
    rows = {
        k: dict(r) for k, r in krt._kinds().items()
    }  # an invented kind with a row that says "no main equipment"
    rows["invented_kind"] = {**rows["datasheet"], "no_main_equipment": True}
    rows["procedure"] = {**rows["procedure"], "no_main_equipment": False}
    monkeypatch.setattr(krt, "_kinds", lambda: rows)
    assert not krt.has_field_list("invented_kind") and krt.has_field_list("procedure")
    assert krt.wording("invented_kind") == krt.WORDING_STATEMENTS
    assert krt.wording("procedure") == krt.WORDING_FIELDS


def test_role_1_for_a_kind_with_no_field_list_is_not_run_costs_nothing_and_asks_no_model(
    monkeypatch,
):
    def boom(*a, **k):
        raise AssertionError(
            "the reader must not be called for a kind with no field list"
        )

    monkeypatch.setattr(nine_job.nine_reader, "read_paper", boom)
    monkeypatch.setattr(nine_call, "ask", boom)
    for name in ("procedure", "contract", "transmittal"):
        got = nine_job.reader_role(_ctx(types.SimpleNamespace(kind=name)))
        assert got.state == "not_run" and got.why == nine_job.NO_FIELD_LIST
        assert got.calls == 0 and got.usd is None and got.models == ()


def test_role_1_for_a_datasheet_still_reaches_the_reader(monkeypatch):
    seen = {}

    def fake(**kw):
        seen["fields_for"] = kw["equipment_type"]
        raise RuntimeError("stop here")

    monkeypatch.setattr(nine_job.nine_reader, "read_paper", fake)
    monkeypatch.setattr(nine_job, "_engine", lambda ctx: "local")
    monkeypatch.setattr(nine_job, "_paper_pages", lambda ctx: {1: "x"})
    from app import datasheets

    monkeypatch.setattr(datasheets, "list_facts", lambda *a, **k: [])
    with pytest.raises(RuntimeError):
        nine_job.reader_role(
            _ctx(types.SimpleNamespace(kind="datasheet", equipment_type="x"))
        )
    assert seen["fields_for"] == "x"


def test_the_reason_is_a_closed_code_the_record_keeps_whole_and_the_sheet_line_names():
    assert nine_job.NO_FIELD_LIST in nine_record.WHY_CODES
    assert nine_job.NO_CHECKLIST in nine_record.WHY_CODES
    assert nine_record._short_why(nine_job.NO_FIELD_LIST) == nine_job.NO_FIELD_LIST
    rec = empty_record("run1", "doc1", "claude")
    roles = tuple(
        RoleRecord(
            r.role_no, r.role, "not_run", nine_job.NO_FIELD_LIST, None, (), 0, None
        )
        if r.role_no == 1
        else r
        for r in rec.roles
    )
    line = (
        type(rec)(**{**rec.__dict__, "roles": roles}).roles_line()
        if hasattr(rec, "__dict__")
        else ""
    )
    assert "1 Reader: this kind of paper has no field list" in line


def test_role_4_with_no_fact_sheet_sends_the_papers_pages_and_no_facts_block():
    """What role 4 does when role 1 was not run: `ctx.store` has no fact sheet, so the prefix is the paper's pages (named) and the project
    context only: no `fact_sheet`, no blank-fields block (`nine_support._prefix`), and the chapter budget is computed without a digest."""
    ctx = _ctx(types.SimpleNamespace(kind="procedure"))
    pages = {1: "page one words", 2: "page two words"}
    prefix, groups, no_context = nine_support._prefix(ctx, pages, [["g"]])
    assert [b.document_kind for b in prefix] == ["paper", "paper"]
    assert not [b for b in prefix if b.document_kind == "review_record"]
    assert groups == [["g"]] and no_context is True and prefix[-1].cache is True
    assert nine_support.chapter_budget(ctx, pages) >= nine_support.MIN_CHAPTER_CHARS
    assert (
        "digest_counts" not in ctx.store
    )  # no fact counts to record: the record shows no fact rows, not zero


# ---------------------------------------------------------------- (2) the wording per kind


def _text(template_id: str) -> str:
    return nine_call.render((template_id, {}))[1]


def test_the_datasheet_wording_is_byte_the_same_as_before():
    assert nine_reviewer.TEMPLATES_OF["fields"] == (
        "nine_reviewer_system",
        "nine_reviewer_question",
    )
    assert _text("nine_reviewer_system") == nine_reviewer.SYSTEM
    assert _text("nine_reviewer_question") == nine_reviewer.ANSWER_SHAPE
    assert nine_librarian.QUESTION_OF["fields"] == "nine_librarian_titles"
    assert nine_context.QUESTION_OF["fields"] == "nine_context_read"
    assert nine_writer.TEMPLATES_OF["fields"] == (
        nine_writer.WRITER_SYSTEM,
        nine_writer.WRITER_QUESTION,
    )
    assert "datasheet review of the equipment" in _text("nine_librarian_titles")
    assert "equipment under review" in _text("nine_context_read")
    assert (
        "the field, its status"
        in nine_call.render(("nine_writer_question", {"count": 2}))[1]
    )


def test_the_statements_wording_names_no_field_value_or_equipment_and_keeps_the_finding_shape():
    system, question = (_text(i) for i in nine_reviewer.TEMPLATES_OF["statements"])
    for word in (
        "supplier",
        "digest",
        "fact_sheet",
        "legend",
        "EMPTY",
        "values read",
        "equipment",
    ):
        assert word not in system, word
    assert (
        "statements, commitments, method steps" in system
        and "acceptance criteria" in system
    )
    assert "documents it refers to" in system
    keys = lambda text: set(re.findall(r'"([a-z_]+)":', text))  # noqa: E731
    assert keys(question) == keys(
        nine_reviewer.ANSWER_SHAPE
    )  # the finding shape (and so `check_raw`, the approval path) is untouched
    assert '"fact_ids": []' in question and "the field name" not in question
    assert "datasheet" not in _text(nine_librarian.QUESTION_OF["statements"])
    assert "equipment" not in _text(nine_context.QUESTION_OF["statements"])
    _w_sys, w_q = nine_writer.TEMPLATES_OF["statements"]
    assert "the field, its status" not in nine_call.render((w_q, {"count": 2}))[1]
    assert "the subject, its status" in nine_call.render((w_q, {"count": 2}))[1]


def test_the_reviewer_asks_with_the_wording_it_is_given():
    seen = []

    def fake_ask(run_id, role, blocks, question, **kw):
        seen.append((question[0], kw["system"][0]))
        return nine_call.Answer(
            False,
            "c",
            role,
            "failed",
            "model_failed",
            None,
            None,
            None,
            None,
            "claude",
            (),
            (),
            (),
        )

    group = [nine_reviewer.ChapterText("b1", "1", 1, 1, (1,), 100)]
    prefix = [nine_call.Block("paper", "d1", (1,))]
    for wording, want in (
        ("fields", ("nine_reviewer_question", "nine_reviewer_system")),
        (
            "statements",
            ("nine_reviewer_question_statements", "nine_reviewer_system_statements"),
        ),
    ):
        seen.clear()
        nine_reviewer.review(
            "run1", prefix, [group], ask=fake_ask, engine="claude", wording=wording
        )
        assert seen and seen[0] == want


def test_the_job_chooses_the_wording_from_the_kind_row():
    assert nine_job._wording(_ctx(types.SimpleNamespace(kind="datasheet"))) == "fields"
    assert (
        nine_job._wording(_ctx(types.SimpleNamespace(kind="procedure"))) == "statements"
    )
    assert (
        nine_job._wording(_ctx(object())) == "fields"
    )  # an unknown kind keeps today's words


# ---------------------------------------------------------------- (3) role 5 says it has no approved checklist


def test_role_5_says_there_is_no_approved_checklist_when_the_plan_holds_none():
    ctx = _ctx(
        types.SimpleNamespace(kind="procedure"),
        {"items": [{"item_id": "R-1", "source": "rule"}]},
    )
    ctx.store["coverage"] = types.SimpleNamespace(to_ask=[], required=(), skipped={})
    got = nine_job.checklist_role(ctx)
    assert got.state == "ran_partly" and got.why == nine_job.NO_CHECKLIST
    assert got.produced["required"] == 1
    with_skill = _ctx(
        types.SimpleNamespace(kind="datasheet"),
        {
            "items": [
                {"item_id": "R-1", "source": "rule"},
                {"item_id": "S-1", "source": "skill"},
            ]
        },
    )
    with_skill.store["coverage"] = types.SimpleNamespace(
        to_ask=[], required=(), skipped={}
    )
    assert nine_job.checklist_role(with_skill).state == "ran"
    no_skill_datasheet = _ctx(
        types.SimpleNamespace(kind="datasheet"),
        {"items": [{"item_id": "R-1", "source": "rule"}]},
    )
    no_skill_datasheet.store["coverage"] = types.SimpleNamespace(
        to_ask=[], required=(), skipped={}
    )
    assert (
        nine_job.checklist_role(no_skill_datasheet).state == "ran"
    )  # a datasheet's record is not changed by this step


# ---------------------------------------------------------------- a paper too large for one request is read in page windows


def _pages(n, size):
    return dict.fromkeys(range(1, n + 1), "x" * size)


def test_a_paper_that_fits_is_one_window_and_the_prefix_is_built_as_before():
    pages = _pages(5, 1000)
    assert nine_support.paper_windows(pages) == [[1, 2, 3, 4, 5]]
    ctx = _ctx(types.SimpleNamespace(kind="datasheet"))
    got = nine_support._prefix(ctx, pages, [["g1"], ["g2"]])
    assert got == nine_support._prefix_core(
        ctx, pages, [["g1"], ["g2"]], [1, 2, 3, 4, 5]
    )
    assert [b.pages for b in got[0]] == [(n,) for n in range(1, 6)] and got[1] == [
        ["g1"],
        ["g2"],
    ]


def test_a_large_paper_is_cut_into_windows_that_cover_every_page_with_one_page_back():
    pages = _pages(
        25, 3_500
    )  # 87,500 characters: over the ceiling with any chapter group
    wins = nine_support.paper_windows(pages)
    assert len(wins) > 1
    assert sorted({n for w in wins for n in w}) == list(range(1, 26))
    assert all(
        sum(len(pages[n]) for n in w) <= nine_support.PAPER_WINDOW_CHARS for w in wins
    )
    assert all(
        b[0] == a[-1] for a, b in itertools.pairwise(wins)
    )  # each window starts one page back
    assert nine_support.paper_windows({1: "y" * 90_000, 2: "z"}) == [
        [1],
        [2],
    ]  # a page over the limit goes alone


def test_the_reviewers_requests_for_a_large_paper_each_carry_one_window_and_stay_under_the_ceiling():
    pages = _pages(25, 3_500)
    ctx = _ctx(types.SimpleNamespace(kind="procedure"))
    budget = nine_support.chapter_budget(ctx, pages)
    widest = max(
        sum(len(pages[n]) for n in w) for w in nine_support.paper_windows(pages)
    )
    assert (
        budget + widest + nine_support.REQUEST_OVERHEAD_CHARS
        <= nine_call.MAX_REQUEST_CHARS
    )
    groups = [["g1"], ["g2"]]
    prefix, expanded, _none = nine_support._prefix(ctx, pages, groups)
    wins = nine_support.paper_windows(pages)
    assert len(expanded) == len(wins) * len(groups) and callable(prefix)
    seen = set()
    for i, g in enumerate(expanded):
        blocks = prefix(i, g)
        n_chars = sum(
            len(pages[b.pages[0]]) for b in blocks if b.document_kind == "paper"
        )
        assert n_chars <= nine_support.PAPER_WINDOW_CHARS
        seen |= {b.pages[0] for b in blocks if b.document_kind == "paper"}
    assert seen == set(range(1, 26))  # every page is read in some request
    assert (
        ctx.store.get("request_plan") is None
    )  # only `request_groups` writes the plan; here the prefix alone was built
