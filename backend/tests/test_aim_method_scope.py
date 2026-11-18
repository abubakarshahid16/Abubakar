"""K1 and K2 (the lead, 18 Nov 2026; strict judges on the procedure paper: 22 WRONG of 206). Invented procedures; no paid call.

K1 SCOPE / PHASE: S1 keeps the paper's own statement of its scope ONLY as a quote code finds on its page; the judge is told
that an item for another life-cycle phase, stage or kind of facility is "Does not apply", never a Question. The build never
sees it (the fair rule).
K2 CLAIMS ANOTHER PAGE ANSWERS: in the editor, a line that claims an absence, a limitation or "only" may be taken off the sheet
by a quote from ANY page of the paper, checked by code (found on a page, at least 40 characters, two content words shared with
the line's field or topic); never a line code compared; a datasheet keeps the strict E1 rule.
"""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import checklist as CL
from app.aim_review import editor as ED
from app.aim_review import engine as E
from app.aim_review import prompts as P
from app.aim_review import steps as S
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    PAPER_PAGES,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


PROC = {
    1: "Invented study procedure\nScope: this procedure covers the design phase hazard study of the invented unit only.\n",
    2: "Section 3 lists the study team and the review sessions of the invented unit.\n",
    4: "Relief scenarios of the invented unit are defined for normal operation, start-up and shutdown in the worksheet.\n",
}
PROC_PAPER = Paper(paper_id="doc_proc", pages=PROC)
SCOPE = "this procedure covers the design phase hazard study of the invented unit only"
ELSEWHERE = "Relief scenarios of the invented unit are defined for normal operation, start-up and shutdown"


class _Model:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def ask(self, **kw):
        self.asked.append(kw)
        return self.answers.get(kw["step"], {})


def _identify(scope):
    return {"kind": "procedure", "equipment_type": None, "subject": "a study procedure", "subject_key": "study_procedure",
            "service": "", "evidence": [], "cited": [], "scope": scope}  # fmt: skip


# ---- K1 -----------------------------------------------------------------------------------------------------------------------


def test_s1_keeps_the_scope_only_as_a_quote_code_found_on_its_page():
    got = S.s1_identify(
        _Model({"aim_identify": _identify({"page": 1, "quote": SCOPE})}),
        PROC_PAPER,
        [],
        "claude-sonnet-5-5",
    )
    assert got["scope_quote"] == SCOPE and got["scope_page"] == 1
    made_up = {
        "page": 1,
        "quote": "this procedure covers the operating phase revalidation of the unit",
    }
    got = S.s1_identify(
        _Model({"aim_identify": _identify(made_up)}),
        PROC_PAPER,
        [],
        "claude-sonnet-5-5",
    )
    assert (
        got["scope_quote"] == "" and got["scope_page"] is None
    )  # not on the paper: nothing kept
    got = S.s1_identify(
        _Model({"aim_identify": _identify(None)}), PROC_PAPER, [], "claude-sonnet-5-5"
    )
    assert got["scope_quote"] == ""


def test_the_judge_is_told_the_scope_and_the_rule_and_the_build_never_sees_it():
    assert (
        "outside the paper's stated scope" in P.S4_TASK
        and "never a\nQuestion for it" in P.S4_TASK
    )
    assert S._scope_line({"scope_quote": SCOPE, "scope_page": 1}) == (
        f'THE PAPER\'S STATED SCOPE (page 1): "{SCOPE}"\n'
    )
    assert (
        S._scope_line({"scope_quote": SCOPE, "scope_page": None}) == ""
        and S._scope_line(None) == ""
    )
    typed = CL.type_identity(
        {"kind": "procedure", "scope_quote": SCOPE, "scope_page": 1, "subject_key": "x"}
    )
    assert SCOPE not in str(
        typed
    )  # the fair rule: the checklist is written for the type, never from the paper


def test_through_run_the_judge_prompt_carries_the_verified_scope(aim_db):
    first = PAPER_PAGES[1].splitlines()[
        1
    ]  # an invented line of the helper paper, as its "scope"
    ident = _identify({"page": 1, "quote": first})
    ident.update(kind="datasheet", subject_key="test_item")
    model = E.FakeModel(
        kind="datasheet", subject_key="test_item", answers={"aim_identify": ident}
    )
    r = aim_review.run(aim_db, run_id="run_scope", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    assert r.status == "done" and r.identity["scope_quote"] == first
    judges = [c["prompt"] for c in model.asked if c["step"] == "aim_judge"]
    assert judges and all(
        f'THE PAPER\'S STATED SCOPE (page 1): "{first}"' in p for p in judges
    )
    builds = [
        c["prompt"]
        for c in model.asked
        if c["step"] in ("aim_select", "aim_checklist", "aim_attack")
    ]
    assert builds and all(first not in p for p in builds)


# ---- K2 -----------------------------------------------------------------------------------------------------------------------


def _claim(**over):
    base = {"item_id": "C001", "field": "relief scenarios", "topic": "relief scenario coverage", "label": "Question",
            "page": 2, "quote": "", "comment": "Relief scenarios are only defined for normal operation.", "code": ""}  # fmt: skip
    return {**base, **over}


def _edit(lines, quote, kind="procedure", page=None):
    model = _Model(
        {
            "aim_edit": {
                "moves": [
                    {
                        "n": 1,
                        "reason": "paper_states_otherwise",
                        "page": page,
                        "quote": quote,
                    }
                ]
            }
        }
    )
    return ED.s5_edit(model, PROC_PAPER, lines, "claude-sonnet-5-5", kind)


def test_a_claim_of_only_answered_on_another_page_is_moved_and_keeps_the_quote_and_page():
    lines = [_claim()]
    assert _edit(lines, ELSEWHERE) == 1
    assert lines[0]["code"] == f'edited: paper states otherwise (page 4: "{ELSEWHERE}")'
    assert lines[0]["label"] == "Question" and lines[0]["comment"].startswith(
        "Relief scenarios are only"
    )


@pytest.mark.parametrize(
    "comment",
    ["Relief scenarios are not covered.", "Coverage is limited to normal operation.", "No provision for start-up is made.",
     "Relief scenarios are missing for start-up."],
)  # fmt: skip
def test_the_widened_claims_are_read_from_the_lines_own_words(comment):
    assert _edit([_claim(comment=comment)], ELSEWHERE) == 1


def test_a_short_or_unverified_or_unrelated_quote_is_refused():
    assert _edit([_claim()], "defined for normal operation") == 0  # under 40 characters
    assert (
        _edit(
            [_claim()],
            "Relief scenarios of the invented unit are defined for every phase of operation",
        )
        == 0
    )  # not on a page
    unrelated = (
        "Section 3 lists the study team and the review sessions of the invented unit"
    )
    assert (
        _edit([_claim()], unrelated) == 0
    )  # on a page, long enough, but not about relief scenarios


def test_a_line_that_claims_nothing_missing_is_never_moved():
    assert (
        _edit(
            [_claim(comment="Confirm the relief scenarios with the licensor.")],
            ELSEWHERE,
        )
        == 0
    )


def test_a_code_compared_line_is_never_moved():
    fail = {
        "result": "fail",
        "why": "25 bar <= 20 bar: false",
        "paper": [25.0, "bar"],
        "rule": [20.0, "bar"],
    }
    passed = {**fail, "result": "pass"}
    assert _edit([_claim(code_compare=fail, label="Not met")], ELSEWHERE) == 0
    assert _edit([_claim(code_compare=passed, label="AI opinion")], ELSEWHERE) == 0


def test_a_datasheet_keeps_the_strict_e1_rule():
    assert (
        _edit([_claim()], ELSEWHERE, kind="datasheet") == 0
    )  # another page, no label with a value on the line's page
