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
        return {"answered": self.answered}


def test_only_sent_lines_on_no_held_rule_that_ask_or_opine_are_offered():
    lines = [
        _line("C01"),  # offered
        _line("C02", label="AI opinion"),  # offered
        _line("C03", source="held standard"),  # a held rule: never
        _line(
            "C04", code_compare={"result": "unclear", "read_from": "verified quotes"}
        ),  # compared by code: never
        _line("C05", deferred=True),  # a value left open: never
        _line("C06", code="provisional_unchecked"),  # a provisional figure: never
        _line("C07", label="Met"),  # a verdict: never (not a Question or opinion)
        _line("C08", code="not_judged"),  # not sent: never
    ]
    assert sorted(A.offered(lines)) == [1, 2]


def test_an_answer_is_accepted_only_with_a_quote_code_finds_on_that_page():
    shown = {1: _line("C01"), 2: _line("C02")}
    ok = {"n": 1, "page": 2, "quote": TEAM}
    assert A.answer_reason(ok, shown, PAPER).startswith(
        'answered: the paper answers it on page 2: "the chair'
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
        _line("C03", source="held standard"),
    ]
    model = _Checker(
        [{"n": 1, "page": 2, "quote": TEAM}, {"n": 3, "page": 2, "quote": TEAM}]
    )
    assert (
        A.s4b_answered(model, PAPER, lines, MODEL) == 1
    )  # line 3 rests on a held rule: never offered, so refused
    assert not aim_review.sendable(to_line(1, lines[0]))
    assert "answered: the paper answers it on page 2" in lines[0]["code"]
    assert aim_review.sendable(to_line(2, lines[1])) and aim_review.sendable(
        to_line(3, lines[2])
    )
    assert model.asked[0]["step"] == "aim_answered" and model.asked[0]["carries"] == {
        "doc_ans"
    }
    assert (
        '"n": 3' not in model.asked[0]["prompt"]
    )  # a held-rule line is not shown to the check


def test_a_failed_check_takes_nothing_off_and_no_offered_line_means_no_call():
    lines = [_line("C01")]
    assert (
        A.s4b_answered(_Checker(fail="transport ReadTimeout"), PAPER, lines, MODEL) == 0
    )
    assert lines[0]["code"] == "" and aim_review.sendable(to_line(1, lines[0]))
    quiet = _Checker()
    assert (
        A.s4b_answered(quiet, PAPER, [_line("C01", source="held standard")], MODEL) == 0
        and quiet.asked == []
    )


def test_more_lines_than_one_call_holds_go_to_a_second_call(monkeypatch):
    monkeypatch.setattr(A, "ANSWER_CHUNK", 2)
    model = _Checker()
    A.s4b_answered(model, PAPER, [_line(f"C{i:02d}") for i in range(1, 6)], MODEL)
    assert len(model.asked) == 3


def test_answered_is_a_not_sent_note():
    assert aim_review.ANSWERED in aim_review.NOT_SENT_NOTES
