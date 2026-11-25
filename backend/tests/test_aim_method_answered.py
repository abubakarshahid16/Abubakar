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


def test_the_lines_own_quote_disproves_its_own_comment_that_the_value_is_blank():
    """The LINE'S comment says the value is blank (the second reader's words): its own quote holding the value disproves it. The
    model's claim never opens this door, and a Not met or a code-compared line is never taken off on its own quote (review of
    d4dceeeb: a 150# vs 300# Not met was taken off on a model claim holding "only")."""
    ok = {"n": 1, "page": 2, "quote": TEAM}
    blank = _line("C01", page=2, quote="the chair and the scribe shall each hold",
                  comment="Second reader (Question): the team row has no value.")  # fmt: skip
    assert A.answer_reason(ok, {1: blank}, PAPER) is not None
    plain = _line(
        "C01",
        page=2,
        quote="the chair and the scribe shall each hold",
        comment="The team differs from page 3.",
    )
    assert (
        A.answer_reason(
            {**ok, "claim": "the sheet only says no value"}, {1: plain}, PAPER
        )
        is None
    )
    for line in (
        _line("C01", label="Not met", page=2, quote="the chair and the scribe shall each hold", comment="Rating is blank: only 150#."),
        _line("C01", page=2, quote="the chair and the scribe shall each hold", comment="Rating is blank.",
              code_compare={"result": "fail", "read_from": "verified quotes"}),
    ):  # fmt: skip
        assert (
            A.answer_reason({**ok, "claim": "only 150# is stated"}, {1: line}, PAPER)
            is None
        )


def test_every_verdict_is_recorded_with_what_code_did_with_it():
    """The local run record keeps each verdict as answered (line, answer, claim, page, quote) and whether code took the line off,
    so a miss can be read later; a call that applied nothing is recorded too."""
    lines = [_line("C01"), _line("C02")]
    record: list = []
    model = _Checker([{"n": 1, "page": 2, "quote": TEAM, "claim": "no team named"},
                      {"n": 2, "answered": True, "page": 3, "quote": "words not on that page at all"}])  # fmt: skip
    assert A.s4b_answered(model, PAPER, lines, MODEL, record) == 1
    assert record == [
        {
            "n": 1,
            "answered": True,
            "claim": "no team named",
            "claims": None,
            "page": 2,
            "quote": TEAM,
            "taken_off": True,
            "outcome": "taken off",
        },
        {
            "n": 2,
            "answered": True,
            "claim": "",
            "claims": None,
            "page": 3,
            "quote": "words not on that page at all",
            "taken_off": False,
            "outcome": "kept",
        },
    ]
    failed: list = []
    A.s4b_answered(
        _Checker(fail="transport ReadTimeout"), PAPER, [_line("C01")], MODEL, failed
    )
    assert failed == [{"lines": [1], "not_applied": True}]


def test_the_verdicts_are_stored_with_the_run_and_read_back(tmp_path, monkeypatch):
    from app import aim_review_store as ST
    from tests.test_aim_method_helpers import open_aim_db

    conn = next(open_aim_db(tmp_path, monkeypatch))
    ST.start_run(conn, "run_rec", "doc_ans", "2026-11-18T21:00:00Z")
    verdicts = [
        {
            "n": 1,
            "answered": False,
            "claim": "",
            "page": None,
            "quote": "",
            "taken_off": False,
        }
    ]
    ST.finish_run(
        conn,
        "run_rec",
        {"status": "done", "lines": [], "answered": verdicts},
        "2026-11-18T21:01:00Z",
    )
    assert ST.run(conn, "run_rec")["answered"] == verdicts


A1 = "The team record is not named."
A2 = "Spurious action is not reviewed for each node."
OPEN = "The test is set to NO for a pressure part."
TAIL = "including the team record"
FULL = f"{OPEN} {A1} {A2} State the test, {TAIL}."
SPURIOUS = "Spurious action of a safeguard shall be reviewed for every invented node"


def _protected(comment=FULL, **over):
    return _line("C01", ask="concern", comment=comment, **over)


def _claims(*open_words, answered=((A1, 2, TEAM), (A2, 3, SPURIOUS))):
    return [
        {"words": w, "answered": True, "page": p, "quote": q} for w, p, q in answered
    ] + [{"words": w, "answered": False} for w in open_words]


def _answer(**over):
    return {"n": 1, "page": 2, "quote": TEAM, "claim": "team record named", **over}


def test_a_protected_line_is_taken_off_only_when_every_claim_of_it_is_answered():
    """Update 6, the same-judge gate: one side claim was cut and the rest, which the paper also answers, was sent. A concern or
    a line both readers agree on is offered; it is taken off when EVERY claim is answered, each by a quote code finds."""
    agreed = _line("C02", label="AI opinion", code=aim_review.TWO_READERS_AGREE)
    assert sorted(A.offered([_protected(), agreed])) == [1, 2]
    every = [_line("C01", ask="concern", comment=f"{A1} {A2}")]
    assert (
        A.s4b_answered(_Checker([_answer(claims=_claims())]), PAPER, every, MODEL) == 1
    )
    assert not aim_review.sendable(to_line(1, every[0]))
    plain = [
        _line("C01", comment=FULL)
    ]  # not protected: any answered claim takes it off, as before
    assert A.s4b_answered(_Checker([_answer()]), PAPER, plain, MODEL) == 1


def test_every_answered_claim_is_cut_the_open_ones_are_sent_and_the_full_text_stays_in_the_team_note():
    for line in (
        _protected(),
        _line(
            "C01", label="AI opinion", code=aim_review.TWO_READERS_AGREE, comment=FULL
        ),
    ):
        record: list = []
        assert (
            A.s4b_answered(
                _Checker(
                    [
                        _answer(
                            claims=_claims(
                                OPEN,
                                "State the test",
                                answered=(
                                    (A1, 2, TEAM),
                                    (A2, 3, SPURIOUS),
                                    (TAIL, 2, TEAM),
                                ),
                            )
                        )
                    ]
                ),
                PAPER,
                [line],
                MODEL,
                record,
            )
            == 0
        )
        assert line["comment"] == f"{OPEN} State the test." and aim_review.sendable(
            to_line(1, line)
        )  # no dangling comma
        assert (
            line["code"].count(A.SIDE_CLAIM) == 1
            and f'read before the cut: "{FULL}"' in line["code"]
        )
        assert (
            'on page 2: "the chair' in line["code"]
            and 'on page 3: "Spurious' in line["code"]
        )
        assert (
            A.cuts_of(line["code"]) == [{"page": 2, "pages": [2, 3, 2], "before": FULL}]
            and record[0]["outcome"] == "cut"
        )


def test_a_protected_line_is_never_taken_off_on_an_answer_code_cannot_check():
    """No claims list (an older answer): sent whole with the note. An answered claim whose quote is not on its page, or whose
    words are not in the comment, stays open: never taken off on it, never cut."""
    line = _protected()
    assert A.s4b_answered(_Checker([_answer()]), PAPER, [line], MODEL) == 0
    assert (
        line["comment"] == FULL
        and "the answer lists no claims, so nothing was cut" in line["code"]
    )
    for claims in (
        _claims(answered=((A1, 3, TEAM), (A2, 3, SPURIOUS))),
        _claims(answered=(("words it never had", 2, TEAM), (A2, 3, SPURIOUS))),
    ):
        line = _protected(comment=f"{A1} {A2}")
        assert (
            A.s4b_answered(_Checker([_answer(claims=claims)]), PAPER, [line], MODEL)
            == 0
        )
        assert line["comment"] == A1 and aim_review.sendable(
            to_line(1, line)
        )  # only the checked claim is cut
    short = _protected()
    assert A.s4b_answered(_Checker([_answer(claims=[{"words": "State", "answered": True, "page": 2, "quote": TEAM}])]),
                          PAPER, [short], MODEL) == 0  # fmt: skip
    assert short["comment"] == FULL


def test_the_check_asks_for_every_claim_with_the_comments_own_words():
    from app.aim_review import prompts

    assert (
        '"claims": EVERY claim and request' in prompts.ANSWERED_TASK
        and '"words"' in prompts.ANSWERED_TASK
    )
    assert '"main"' not in prompts.ANSWERED_TASK
    assert (
        "vendor to advise" in prompts.S4_TASK
        and "revision and approval block" in prompts.S4_TASK
    )
