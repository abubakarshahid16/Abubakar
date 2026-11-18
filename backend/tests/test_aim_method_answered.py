"""S4b, the whole-paper check (18 Nov 2026, after live): a line on no held rule that the paper answers on some page is kept in
"All points" and not sent; code checks every answer (the quote is on that page). Invented paper; no paid call, no socket."""

from __future__ import annotations

from app import aim_review
from app.aim_review import answered as A
from app.aim_review.engine import StepFailed, to_line
from app.aim_review.paper import Paper

PAGES = {
    1: "Scope of the invented study: the plant units listed in section two\n",
    2: "Team: the chair and the scribe shall each hold the invented competence record\n",
    3: "Spurious action of a safeguard shall be reviewed for every invented node\n",
}
PAPER = Paper(paper_id="doc_ans", pages=PAGES)
TEAM = "the chair and the scribe shall each hold the invented competence record"
MODEL = "claude-sonnet-5-5"


def _line(
    n_item,
    label="Question",
    source="engineering knowledge (book not held)",
    page=1,
    code="",
    **over,
):
    return {"item_id": n_item, "field": "f", "label": label, "page": page, "quote": "", "comment": "c", "code": code,
            "source": source, "code_compare": None, "deferred": False, **over}  # fmt: skip


class _Checker:
    def __init__(self, answered=None, fail=None):
        self.answered, self.fail, self.asked = answered or [], fail, []

    def ask(self, **kw):
        self.asked.append(kw)
        if self.fail:
            raise StepFailed(f"aim_answered: {self.fail}")
        return {
            "verdicts": [
                {**a, "answered": a.get("answered", True)} for a in self.answered
            ]
        }


def test_only_sent_lines_the_ai_alone_decided_are_offered_on_any_source():
    lines = [
        _line("C01"),  # offered
        _line("C02", label="AI opinion"),  # offered
        _line(
            "C03", source="held standard"
        ),  # a held rule: offered too (v3: its claims are checked like any other)
        _line(
            "C04", code_compare={"result": "unclear", "read_from": "verified quotes"}
        ),  # compared by code: never
        _line("C05", deferred=True),  # a value left open: never
        _line("C06", code="provisional_unchecked"),  # a provisional figure: never
        _line("C07", label="Met"),  # a verdict: never (not a Question or opinion)
        _line("C08", code="not_judged"),  # not sent: never
    ]
    assert sorted(A.offered([*lines, _line("C09", label="Not met")])) == [1, 2, 3, 9]


def test_an_answer_is_accepted_only_with_a_quote_code_finds_on_that_page():
    shown = {1: _line("C01"), 2: _line("C02")}
    ok = {"n": 1, "page": 2, "quote": TEAM}
    assert A.answer_reason(ok, shown, PAPER).startswith(
        'answered: the paper covers it on page 2: "the chair'
    )
    assert 'covers what it says ("no team named") on page 2' in A.answer_reason(
        dict(ok, claim="no team named"), shown, PAPER
    )
    assert A.answer_reason(dict(ok, page=3), shown, PAPER) is None  # not on THAT page
    assert A.answer_reason(dict(ok, page=9), shown, PAPER) is None  # no such page
    assert (
        A.answer_reason(dict(ok, n=5), shown, PAPER) is None
    )  # not offered in this call
    assert A.answer_reason(dict(ok, n=True), shown, PAPER) is None
    assert (
        A.answer_reason(
            dict(ok, quote="the chair and the scribe ... record"), shown, PAPER
        )
        is None
    )  # a "..." part
    assert (
        A.answer_reason(dict(ok, quote="chair"), shown, PAPER) is None
    )  # too short to show anything
    assert (
        A.answer_reason(
            dict(ok, quote="the chair and the scribe shall hold a pilot licence"),
            shown,
            PAPER,
        )
        is None
    )


def test_an_answered_line_stays_a_point_and_is_never_sent():
    lines = [
        _line("C01", page=1),
        _line("C02", page=3),
        _line("C03", code_compare={"result": "fail", "read_from": "verified quotes"}),
    ]
    model = _Checker(
        [{"n": 1, "page": 2, "quote": TEAM}, {"n": 3, "page": 2, "quote": TEAM}]
    )
    assert (
        A.s4b_answered(model, PAPER, lines, MODEL) == 1
    )  # line 3 is code's own comparison: never offered, so refused
    assert not aim_review.sendable(to_line(1, lines[0]))
    assert "answered: the paper covers it on page 2" in lines[0]["code"]
    assert aim_review.sendable(to_line(2, lines[1])) and aim_review.sendable(
        to_line(3, lines[2])
    )
    assert model.asked[0]["step"] == "aim_answered" and model.asked[0]["carries"] == {
        "doc_ans"
    }
    assert (
        '"n": 3' not in model.asked[0]["prompt"]
    )  # a code-compared line is not shown to the check


def test_a_failed_check_takes_nothing_off_and_no_offered_line_means_no_call():
    lines = [_line("C01")]
    assert (
        A.s4b_answered(_Checker(fail="transport ReadTimeout"), PAPER, lines, MODEL) == 0
    )
    assert lines[0]["code"] == "" and aim_review.sendable(to_line(1, lines[0]))
    quiet = _Checker()
    assert (
        A.s4b_answered(quiet, PAPER, [_line("C01", deferred=True)], MODEL) == 0
        and quiet.asked == []
    )


def test_more_lines_than_one_call_holds_go_to_a_second_call(monkeypatch):
    monkeypatch.setattr(A, "ANSWER_CHUNK", 2)
    model = _Checker()
    A.s4b_answered(model, PAPER, [_line(f"C{i:02d}") for i in range(1, 6)], MODEL)
    assert len(model.asked) == 3


def test_answered_is_a_not_sent_note():
    assert aim_review.ANSWERED in aim_review.NOT_SENT_NOTES


def test_the_lines_own_evidence_on_its_own_page_is_never_an_answer():
    """A value conflict quotes its value; an "answer" that repeats that quote on the line's own page is the comment's evidence,
    not an answer: refused, so the conflict stays sent. The same words on ANOTHER page, or other words on the same page, may
    answer it."""
    conflict = _line("C01", page=2, quote="the chair and the scribe shall each hold")
    shown = {1: conflict}
    assert (
        A.answer_reason({"n": 1, "page": 2, "quote": TEAM}, shown, PAPER) is None
    )  # holds the line's own quote
    assert (
        A.answer_reason(
            {"n": 1, "page": 2, "quote": "the chair and the scribe shall each hold"},
            shown,
            PAPER,
        )
        is None
    )
    other_page = dict(conflict, page=3)
    assert (
        A.answer_reason({"n": 1, "page": 2, "quote": TEAM}, {1: other_page}, PAPER)
        is not None
    )
    no_quote = dict(conflict, quote="")
    assert (
        A.answer_reason({"n": 1, "page": 2, "quote": TEAM}, {1: no_quote}, PAPER)
        is not None
    )


def test_only_a_verdict_answered_true_is_checked_and_applied():
    lines = [_line("C01"), _line("C02")]
    model = _Checker(
        [
            {"n": 1, "answered": False, "page": 2, "quote": TEAM},
            {"n": 2, "answered": "yes", "page": 2, "quote": TEAM},
        ]
    )
    assert (
        A.s4b_answered(model, PAPER, lines, MODEL) == 0
    )  # false, and a non-boolean "yes": nothing taken off
    model = _Checker([{"n": 1, "answered": True, "page": 2, "quote": TEAM}])
    assert (
        A.s4b_answered(model, PAPER, lines, MODEL) == 1
        and "answered:" in lines[0]["code"]
    )


def test_the_check_asks_one_verdict_for_every_comment():
    from app.aim_review import prompts as P

    assert (
        "check EVERY such claim and request" in P.ANSWERED_TASK
        and "for ANY ONE of its claims" in P.ANSWERED_TASK
        and '"claim"' in P.ANSWERED_TASK
        and '"verdicts"' in P.ANSWERED_TASK
    )


def test_a_line_a_reference_paper_checked_is_never_offered():
    """The Schedule a reference line rests on is not in this step's request: it can neither answer nor take off such a line."""
    differs = _line("R01", label="AI opinion", source="held contract paper (same package)",
                    code="reference_checked: Invented Schedule X")  # fmt: skip
    assert list(A.offered([differs, _line("C02")])) == [2]


def test_the_books_a_line_names_are_declared_as_carried():
    model = _Checker([])
    line = _line(
        "C01",
        book_document_id="doc_book_x",
        named_books=[{"id": "doc_sched_y", "name": "Invented Schedule Y"}],
    )
    A.s4b_answered(model, PAPER, [line], MODEL)
    assert model.asked[0]["carries"] == {"doc_ans", "doc_book_x", "doc_sched_y"}
