"""Reference papers of a contract review (order 14, owner's after-live order, item 2). Invented documents and words only.

A contract paper that cites a Schedule which ONE held contract paper is reads that paper as a reference paper (not a rule book) and
checks the open questions that name it against it; the paper is listed before the start and sent only through the existing gates."""

from __future__ import annotations

import json

import pytest

from app import aim_review, aim_review_store, aim_review_view
from app.aim_review import engine as E
from app.aim_review import references as R
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import MemoryStore, _doc, open_aim_db

AGREEMENT, SCHED_C, SCHED_B1, SCHED_B2, SCHED_Z = (
    "doc_rf_agreement", "doc_rf_sched_c", "doc_rf_sched_b1", "doc_rf_sched_b2", "doc_rf_sched_z",
)  # fmt: skip
AGREEMENT_PAGES = {
    1: "FORM OF AGREEMENT\nThe milestones and the delay damages are set out in Schedule C.\n"
    "Payment follows Schedule B and Schedule D.\nThe drawings list is Appendix 1 and Attachment II.\n",
}
SCHED_C_PAGES = {
    1: "SCHEDULE C\nMILESTONES AND DELAY DAMAGES\n"
    "The contractor shall complete milestone one within ninety days of the effective date of the contract.\n",
    2: "Delay damages are payable at one half of one percent of the contract price for each week of delay.\n",
}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


@pytest.fixture
def world(conn):
    with conn:
        _doc(conn, AGREEMENT, "agreement.pdf", "CONTRACT_DOCUMENT", AGREEMENT_PAGES)
        _doc(conn, SCHED_C, "sched-c.pdf", "CONTRACT_DOCUMENT", SCHED_C_PAGES)
        _doc(
            conn,
            SCHED_B1,
            "sched-b-1.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE B\nPAYMENT\nPayment is made monthly in arrears."},
        )
        _doc(
            conn,
            SCHED_B2,
            "sched-b-2.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE B\nPAYMENT (COPY)\nPayment is made monthly in arrears."},
        )
        _doc(
            conn,
            SCHED_Z,
            "sched-z.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE Z\nOTHER\nSomething the agreement never cites."},
        )
        conn.execute(  # the parts of ONE package carry one RECORDED project (the link is never a likeness of names)
            "UPDATE document_classification SET project = 'Invented Project One' WHERE document_role = 'CONTRACT_DOCUMENT'"
        )
    return conn


def _line(n: int, comment: str, **kw) -> dict:
    base = {"item_id": f"C{n:03d}", "finding_no": 1, "label": "Question", "field": "Milestones", "page": 1,
            "quote": "The milestones and the delay damages are set out in Schedule C.", "comment": comment,
            "ask": "confirm", "deferred": False, "code": "", "standard": "STD", "clause": "1"}  # fmt: skip
    return {**base, **kw}


class Part:
    """A stand-in model: records every call and answers with what the test gave it."""

    def __init__(self, answers) -> None:
        self.answers, self.calls = answers, []

    def ask(self, **kw):
        self.calls.append(kw)
        return self.answers(kw) if callable(self.answers) else self.answers


def _paper(conn) -> Paper:
    from app.aim_review.paper import load_paper

    return load_paper(conn, AGREEMENT)


def _answer(n, result, quote="", page=1, comment="the schedule says so"):
    return {
        "checks": [
            {"n": n, "result": result, "page": page, "quote": quote, "comment": comment}
        ]
    }


QUOTE = (
    "complete milestone one within ninety days of the effective date of the contract"
)


# ---- which parts are cited and which are held (the code's own part reading, never a name guess) -------------------------------


def test_the_paper_cites_schedules_only_never_a_sub_part(world):
    assert [R.name_of(k) for k in R.paper_cites(AGREEMENT_PAGES)] == [
        "Schedule C",
        "Schedule B",
        "Schedule D",
    ]


def test_exactly_one_held_paper_is_a_reference_the_rest_are_said_not_guessed(world):
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES)
    assert [(r.doc_id, r.name) for r in res.refs] == [(SCHED_C, "Schedule C")]
    assert res.ambiguous == [
        "Schedule B"
    ]  # two held papers are Schedule B: neither is chosen
    assert res.not_held == ["Schedule D"]
    assert SCHED_Z not in {r.doc_id for r in res.refs}  # held but never cited


def test_a_schedule_of_another_package_is_compared_only_when_a_recorded_link_ties_it(
    world,
):
    """Two invented packages are held. Project one's agreement cites Schedule C and Schedule B; a Schedule C of project TWO is held, and a
    Schedule D with NO recorded project. A recorded link is the SAME recorded project, or the engineer's choice at the start (the shown
    list). With neither, a held Schedule is said ("not linked"), never compared and never called "not held"."""
    with world:
        world.execute(
            "UPDATE document_classification SET project = 'Invented Project Two' WHERE document_id = ?",
            (SCHED_C,),
        )  # package B's Schedule C
        _doc(
            world,
            "doc_rf_p1_d",
            "d.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE D\nOTHER\nHeld with no recorded project."},
        )
        world.execute(
            "UPDATE document_classification SET project = NULL WHERE document_id = 'doc_rf_p1_d'"
        )
        _doc(
            world,
            "doc_rf_p1_c",
            "c1.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE C\nMILESTONES\nProject one's own Schedule C."},
        )
        world.execute(
            "UPDATE document_classification SET project = 'Invented Project One' WHERE document_id = 'doc_rf_p1_c'"
        )
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES)
    assert [(r.doc_id, r.name) for r in res.refs] == [
        ("doc_rf_p1_c", "Schedule C")
    ]  # same recorded project only
    assert res.unlinked == ["Schedule D"] and res.not_held == []  # held, no link: said
    # package B's only Schedule C, not on A's shown list and no shared project -> not compared
    with world:
        world.execute(
            "UPDATE document_classification SET project = 'Invented Project Two' WHERE document_id = 'doc_rf_p1_c'"
        )
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES)
    assert res.refs == [] and "Schedule C" in res.unlinked
    record, carried = R.check(
        world,
        Part({}),
        _paper(world),
        [_line(1, "Please confirm (Schedule C).")],
        frozenset(),
        "lead",
    )
    assert {e["status"] for e in record if e["part"] == "Schedule C"} == {
        R.NOT_LINKED
    } and carried == set()
    # ... but the engineer's choice at the start (it is ON the shown list) ties it: compared, held once for that letter
    shown = frozenset({"doc_rf_p1_c"})
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES, shown)
    assert [(r.doc_id, r.name) for r in res.refs] == [
        ("doc_rf_p1_c", "Schedule C")
    ] and "Schedule C" not in res.unlinked
    record, carried = R.check(
        world,
        Part({}),
        _paper(world),
        [_line(1, "Please confirm (Schedule C).")],
        shown,
        "lead",
    )
    assert carried == {"doc_rf_p1_c"} and not any(
        e["status"] == R.NOT_LINKED and e["part"] == "Schedule C" for e in record
    )
    # a paper with no recorded project links nothing by project: only the shown list ties
    with world:
        world.execute(
            "UPDATE document_classification SET project = '  ' WHERE document_id = ?",
            (AGREEMENT,),
        )
        world.execute(
            "UPDATE document_classification SET project = 'Invented Project One' WHERE document_id = 'doc_rf_p1_c'"
        )
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES)
    assert res.refs == [] and sorted(res.unlinked) == [
        "Schedule B",
        "Schedule C",
        "Schedule D",
    ]
    # the plan (nothing shown yet) lists project-linked Schedules only
    assert (
        R.plan_entries(world, AGREEMENT, frozenset({"doc_rf_p1_c", SCHED_C}))[0] == []
    )


def test_a_paper_is_never_its_own_reference(world):
    assert SCHED_C not in {
        r.doc_id for r in R.resolve(world, SCHED_C, SCHED_C_PAGES).refs
    }


# ---- the check -----------------------------------------------------------------------------------------------------------


def test_a_question_the_schedule_answers_is_settled_with_its_verified_quote(world):
    lines = [_line(1, "Please confirm where the milestones are set out (Schedule C).")]
    model = Part(_answer(1, "agrees", QUOTE))
    record, carried = R.check(
        world, model, _paper(world), lines, frozenset({SCHED_C}), "m"
    )
    ln = lines[0]
    assert (
        ln["label"] == "Met" and ln["ask"] == ""
    )  # an AI opinion, kept in "All points", not sent
    assert ln["comment"].startswith("Schedule C, page 1: ")
    assert (
        R.NOTE_CHECKED in ln["code"]
        and {"id": SCHED_C, "name": "Schedule C"} in ln["named_books"]
    )
    assert carried == {SCHED_C} and model.calls[0]["carries"] == {AGREEMENT, SCHED_C}
    assert (
        record[0]["status"] == "read"
        and record[0]["settled"] == 1
        or any(r["part"] == "Schedule C" and r["settled"] == 1 for r in record)
    )


def test_a_part_that_differs_is_a_sent_ai_opinion(world):
    lines = [_line(1, "Please confirm the milestones (Schedule C).")]
    R.check(
        world,
        Part(_answer(1, "differs", QUOTE)),
        _paper(world),
        lines,
        frozenset({SCHED_C}),
        "m",
    )
    assert lines[0]["label"] == "AI opinion" and aim_review.sendable(
        {"label": lines[0]["label"], "code_note": lines[0]["code"]}
    )


def test_a_part_that_does_not_state_it_leaves_the_question_and_says_it_was_read(world):
    lines = [_line(1, "Please confirm the delay damages (Schedule C).")]
    R.check(
        world,
        Part(_answer(1, "not_stated")),
        _paper(world),
        lines,
        frozenset({SCHED_C}),
        "m",
    )
    assert lines[0]["label"] == "Question"
    assert lines[0]["comment"].startswith(
        "Schedule C was read and does not state this. Please confirm"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "The schedule says the contractor shall paint every wall blue on Tuesdays",
        "too short",
    ],
)
def test_a_quote_code_cannot_find_on_the_part_changes_nothing(world, quote):
    lines = [_line(1, "Please confirm the milestones (Schedule C).")]
    before = dict(lines[0])
    R.check(
        world,
        Part(_answer(1, "agrees", quote)),
        _paper(world),
        lines,
        frozenset({SCHED_C}),
        "m",
    )
    assert lines[0] == before


def test_a_vendor_deferred_value_and_an_unnamed_part_are_never_touched(world):
    lines = [
        _line(1, "The value is left to Contractor (Schedule C).", deferred=True),
        _line(
            2,
            "Please confirm the payment terms (Schedule B).",
            quote="Payment follows Schedule B and Schedule D.",
        ),  # Schedule B is held twice: not chosen
        _line(
            3,
            "A different question with no part named.",
            quote="The drawings list is Appendix 1 and Attachment II.",
        ),
        _line(4, "Settled (Schedule C).", label="Met", ask=""),
    ]
    before = [dict(x) for x in lines]
    model = Part(lambda kw: {"checks": []})
    R.check(
        world,
        model,
        _paper(world),
        lines,
        frozenset({SCHED_C, SCHED_B1, SCHED_B2}),
        "m",
    )
    # v2: the Form's own sentence that points to Schedule C is compared with it (one call); no QUESTION is asked of any part
    assert lines == before
    assert [c["prompt"].startswith("TASK S7") for c in model.calls] == [True]


def test_a_schedule_not_on_the_shown_list_is_not_sent_and_its_questions_stay(world):
    lines = [_line(1, "Please confirm the milestones (Schedule C).")]
    before = dict(lines[0])
    model = Part(_answer(1, "agrees", QUOTE))
    record, carried = R.check(world, model, _paper(world), lines, frozenset(), "m")
    assert lines[0] == before and model.calls == [] and carried == set()
    assert any(r["part"] == "Schedule C" and r["status"] == R.NOT_SENT for r in record)
    assert {r["status"] for r in record} >= {R.AMBIGUOUS, R.NOT_HELD}


def test_a_refused_send_is_said_and_the_questions_stay(world):
    def refuse(kw):
        raise E.StepFailed("aim_reference: gate_closed")

    lines = [_line(1, "Please confirm the milestones (Schedule C).")]
    before = dict(lines[0])
    record, _ = R.check(
        world, Part(refuse), _paper(world), lines, frozenset({SCHED_C}), "m"
    )
    assert lines[0] == before
    assert [r["status"] for r in record if r["part"] == "Schedule C"] == [R.NOT_SENT]


def test_a_paper_that_is_not_a_contract_reads_no_reference_paper(world, monkeypatch):
    from app import claude_auto_approve

    monkeypatch.setattr(claude_auto_approve, "is_contract_paper", lambda _doc: False)
    lines = [_line(1, "Please confirm the milestones (Schedule C).")]
    model = Part(_answer(1, "agrees", QUOTE))
    assert R.check(world, model, _paper(world), lines, frozenset({SCHED_C}), "m") == (
        [],
        set(),
    )
    assert model.calls == []


# ---- the run: a reference paper is never a rule book; the contract gate still decides ------------------------------------------


def test_the_real_gate_still_refuses_a_contract_without_consent_and_the_run_says_so(
    world,
):
    model = E.FakeModel(kind="contract", subject_key="form_of_agreement")
    r = aim_review.run(
        world,
        run_id="run_rf_1",
        paper_id=AGREEMENT,
        allowed_books=frozenset({SCHED_C}),
        store=MemoryStore(),
        max_usd=5.0,
        model=model,
    )
    assert SCHED_C not in r.books  # never a rule book
    sent = [c for c in model.asked if SCHED_C in c["carries"]]
    assert all(c["step"] == "aim_reference" for c in sent)


# ---- the page: what was done is served, and a part the viewer may not read is never named --------------------------------------


def test_the_page_serves_the_references_and_hides_a_part_the_viewer_may_not_read(world):
    aim_review_store.ensure_schema(world)
    refs = [
        {
            "id": SCHED_C,
            "part": "Schedule C",
            "status": "read",
            "reason": "",
            "questions": 3,
            "settled": 2,
        }
    ]
    row = {"run_id": "g1", "paper_document_id": AGREEMENT, "references": refs}

    class Scope:
        def __init__(self, may):
            self.may = may

        def may_read(self, d):
            return self.may

    shown = aim_review_view._references(world, row, Scope(True))
    assert (
        shown[0]["part"] == "Schedule C"
        and shown[0]["title"] == "sched-c.pdf"
        and shown[0]["settled"] == 2
    )
    hidden = aim_review_view._references(world, row, Scope(False))
    assert "Schedule C" not in json.dumps(hidden) and "sched-c" not in json.dumps(
        hidden
    )
    assert hidden[0]["part"] == aim_review_view.HIDDEN_BOOK_WORDS


def test_a_checked_line_shows_a_viewer_who_may_not_read_the_part_no_words_of_it(world):
    line = {"comment": "Schedule C, page 2: the schedule's own words", "standard": "STD", "clause": "1", "code_note": f"{R.NOTE_CHECKED}: Schedule C",
            "named_books": [{"id": SCHED_C, "name": "Schedule C"}], "book_document_id": "", "label": "Met", "shown_label": "AI opinion: met"}  # fmt: skip
    out = aim_review_view.line_view(line, 1, hidden=True)
    assert out["comment"] == R.HIDDEN_COMMENT and "own words" not in json.dumps(out)


# ---- the Form against the Schedule it cites (v2) -------------------------------------------------------------------------------


def _ref(name="Schedule C", doc=SCHED_C):
    return R.Ref(doc, ("schedule", name[-1]), name)


def test_the_citing_sentences_are_the_papers_own_lines_that_point_to_the_schedule(
    world,
):
    cites = R.citing_sentences(AGREEMENT_PAGES, _ref())
    assert [(c.page, c.text) for c in cites] == [
        (
            1,
            "The milestones and the delay damages are set out in Schedule C. Payment follows Schedule B and Schedule D.",
        )
    ]


def test_a_heading_a_repeat_and_a_sub_part_are_not_citing_sentences():
    pages = {
        1: "SCHEDULE C\nThe fee is stated in Schedule C of this agreement.\nThe fee is stated in Schedule C of this agreement.\nSee Attachment II of Schedule C.\n",
        2: "The fee is stated in Schedule C of this agreement.\n",
    }
    cites = R.citing_sentences(pages, _ref())
    assert (
        len(cites) == 1 and cites[0].page == 1
    )  # the heading, the second copy and the sub-part form are left out


def test_the_citing_sentences_are_capped(monkeypatch):
    monkeypatch.setattr(R, "MAX_CITES", 3)
    pages = {
        1: "\n".join(
            f"Clause {i} follows Schedule C in all respects, item {i}."
            for i in range(10)
        )
    }
    assert len(R.citing_sentences(pages, _ref())) == 3


def test_windows_never_split_a_page_and_are_capped(monkeypatch):
    monkeypatch.setattr(R, "WINDOW_CHARS", 100)
    monkeypatch.setattr(R, "MAX_WINDOWS", 2)
    got = R.windows_of({n: "x" * 60 for n in range(1, 7)})
    assert [sorted(w) for w in got] == [[1], [2]] and all(
        len(t) == 60 for w in got for t in w.values()
    )


FORM_QUOTE = "The milestones and the delay damages are set out in Schedule C."
PART_QUOTE = "Delay damages are payable at one half of one percent of the contract price for each week of delay."


def _compare_answer(result, form=FORM_QUOTE, part=PART_QUOTE, fpage=1, ppage=2, n=1):
    return {
        "compare": [
            {
                "n": n,
                "result": result,
                "form_quote": form,
                "form_page": fpage,
                "part_quote": part,
                "part_page": ppage,
                "comment": "the two differ on the rate",
            }
        ]
    }


def test_a_difference_with_both_quotes_found_becomes_one_sent_ai_opinion_naming_both_pages(
    world,
):
    lines: list[dict] = []
    model = Part(_compare_answer("differs"))
    record, carried = R.check(
        world, model, _paper(world), lines, frozenset({SCHED_C}), "m"
    )
    assert len(lines) == 1
    ln = lines[0]
    assert ln["label"] == "AI opinion" and aim_review.sendable(
        {"label": ln["label"], "code_note": ln["code"]}
    )
    assert "Form page 1" in ln["comment"] and "Schedule C page 2" in ln["comment"]
    assert FORM_QUOTE in ln["comment"] and PART_QUOTE in ln["comment"]
    assert (
        ln["quote"] == FORM_QUOTE
        and ln["page"] == 1
        and {"id": SCHED_C, "name": "Schedule C"} in ln["named_books"]
    )
    row = [r for r in record if r["part"] == "Schedule C"][0]
    assert row["differs"] == 1 and row["compared"] == 1 and carried == {SCHED_C}
    assert model.calls[0]["carries"] == {AGREEMENT, SCHED_C} and model.calls[0][
        "prompt"
    ].startswith("TASK S7")


def test_an_agreement_adds_no_line_only_a_count(world):
    lines: list[dict] = []
    record, _ = R.check(
        world,
        Part(_compare_answer("agrees")),
        _paper(world),
        lines,
        frozenset({SCHED_C}),
        "m",
    )
    assert lines == []
    assert [
        (r["agrees"], r["differs"]) for r in record if r["part"] == "Schedule C"
    ] == [(1, 0)]


@pytest.mark.parametrize(
    "answer",
    [
        _compare_answer(
            "differs",
            part="The schedule says something its page does not hold at all, in any words",
        ),
        _compare_answer(
            "differs",
            form="The paper says something its page never states anywhere in the document",
        ),
        _compare_answer(
            "differs", fpage=5, ppage=9
        ),  # wrong pages are found by a search of the other pages too: still verified
        _compare_answer("differs", part="short one"),
        _compare_answer("not_here"),
        {
            "compare": [
                {
                    "n": 99,
                    "result": "differs",
                    "form_quote": FORM_QUOTE,
                    "form_page": 1,
                    "part_quote": PART_QUOTE,
                    "part_page": 2,
                    "comment": "x",
                }
            ]
        },
    ],
)
def test_an_answer_whose_quote_code_cannot_find_changes_nothing(world, answer):
    lines: list[dict] = []
    R.check(world, Part(answer), _paper(world), lines, frozenset({SCHED_C}), "m")
    unverified_pages = answer["compare"][0].get("form_page") == 5
    assert (len(lines) == 1) if unverified_pages else lines == []


def test_a_difference_in_any_window_wins_over_an_agreement_in_another(
    world, monkeypatch
):
    monkeypatch.setattr(
        R, "WINDOW_CHARS", 60
    )  # each page of Schedule C is its own window
    seen = []

    def answer(kw):
        seen.append(kw["prompt"])
        return _compare_answer("agrees" if len(seen) == 1 else "differs")

    lines: list[dict] = []
    R.check(world, Part(answer), _paper(world), lines, frozenset({SCHED_C}), "m")
    assert len(seen) == 2 and len(lines) == 1 and lines[0]["label"] == "AI opinion"


def test_a_schedule_with_no_open_question_is_still_compared_when_the_form_points_to_it(
    world,
):
    record, _ = R.check(
        world, Part({"compare": []}), _paper(world), [], frozenset({SCHED_C}), "m"
    )
    assert [r["compared"] for r in record if r["part"] == "Schedule C"] == [1]


def test_a_refused_comparison_is_said_and_adds_nothing(world):
    def refuse(kw):
        raise E.StepFailed("aim_reference: gate_closed")

    lines: list[dict] = []
    record, _ = R.check(
        world, Part(refuse), _paper(world), lines, frozenset({SCHED_C}), "m"
    )
    assert lines == [] and [
        r["status"] for r in record if r["part"] == "Schedule C"
    ] == [R.NOT_SENT]


def test_a_schedule_not_on_the_list_is_not_compared_and_no_call_is_made(world):
    model = Part(_compare_answer("differs"))
    lines: list[dict] = []
    R.check(world, model, _paper(world), lines, frozenset(), "m")
    assert lines == [] and model.calls == []


def test_a_call_that_stops_after_settled_questions_says_how_many_not_failed():
    """Lines already settled stay settled: the status is "read in part" with the count, never "failed"."""
    from app.aim_review import references as RR

    ref = RR.Ref(doc_id="doc_ref_inv", key=None, name="Invented Schedule X")
    part = RR._failed(ref, "transport ReadTimeout", questions=5, settled=3)
    assert part["status"] == RR.READ_IN_PART and part["settled"] == 3
    assert part["reason"].startswith("3 of 5 questions settled before a call stopped")
    assert (
        RR._failed(ref, "transport ReadTimeout", questions=5, settled=0)["status"]
        == RR.FAILED
    )
    assert (
        RR._failed(ref, "gate_closed", questions=5, settled=0)["status"] == RR.NOT_SENT
    )


# ---- several held papers are one cited Schedule (planner note 20:48): main over attachment, then the highest revision ---------


def _set(conn, doc_id, **cols):
    with conn:
        for k, v in cols.items():
            conn.execute(
                f"UPDATE document_classification SET {k} = ? WHERE document_id = ?",
                (v, doc_id),
            )


def test_the_main_schedule_is_chosen_over_its_attachment_by_recorded_title(world):
    _set(world, SCHED_B2, title="Invented Schedule B Attachment 1 Rates")
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES)
    assert (SCHED_B1, "Schedule B") in [
        (r.doc_id, r.name) for r in res.refs
    ] and "Schedule B" not in res.ambiguous


def test_a_paper_whose_first_page_heads_an_attachment_is_not_the_main_schedule(conn):
    with conn:
        _doc(conn, AGREEMENT, "agreement.pdf", "CONTRACT_DOCUMENT", AGREEMENT_PAGES)
        _doc(
            conn,
            SCHED_B1,
            "b-main.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE B\nPAYMENT\nPayment is made monthly."},
        )
        _doc(conn, SCHED_B2, "b-two.pdf", "CONTRACT_DOCUMENT",
             {1: "SCHEDULE B\nPAYMENT\nINVENTED HEADER\nNOTES\nATTACHMENT 2\nRates table."})  # fmt: skip
        conn.execute(
            "UPDATE document_classification SET project = 'Invented Project One'"
        )
    assert R.pick(conn, [SCHED_B1, SCHED_B2]) == [SCHED_B1]


@pytest.mark.parametrize(
    ("revs", "chosen"),
    [
        (("1", "Rev. 2"), [SCHED_B2]),
        (("B", "A"), [SCHED_B1]),
        (
            ("Z", "AA"),
            [SCHED_B2],
        ),  # letters order like a spreadsheet column: by length, then letters
        (("ab", "AA"), [SCHED_B1]),
        (
            ("1", "B"),
            [SCHED_B1, SCHED_B2],
        ),  # a number and a letter: no order, still tied
        (("3", None), [SCHED_B1, SCHED_B2]),  # one revision not recorded: no order
        (("2", "2"), [SCHED_B1, SCHED_B2]),
    ],
)
def test_the_highest_recorded_revision_is_chosen_else_still_tied(world, revs, chosen):
    _set(world, SCHED_B1, revision=revs[0])
    _set(world, SCHED_B2, revision=revs[1])
    assert R.pick(world, [SCHED_B1, SCHED_B2]) == chosen


def test_a_tie_is_never_merged_and_is_offered_on_the_plan_for_the_engineer_to_choose(
    world,
):
    res = R.resolve(world, AGREEMENT, AGREEMENT_PAGES)
    assert res.ambiguous == ["Schedule B"] and not [
        r for r in res.refs if r.name == "Schedule B"
    ]
    tied = [(r.doc_id, r.name) for r in res.offers if r.key == ("schedule", "B")]
    assert tied == [
        (SCHED_B1, f"Schedule B ({R.TIED})"),
        (SCHED_B2, f"Schedule B ({R.TIED})"),
    ]
    chosen = R.resolve(
        world, AGREEMENT, AGREEMENT_PAGES, shown=frozenset({SCHED_B2})
    )  # the engineer ticked one
    assert [(r.doc_id, r.name) for r in chosen.refs if r.key == ("schedule", "B")] == [
        (SCHED_B2, "Schedule B")
    ]
