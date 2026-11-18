"""S4c, the second reader (18 Nov 2026 after live): a finding the AI alone decided is sent only when a blind second reader also
finds a fault on a quote code finds; otherwise it is sent as a Question with both readers' words. Invented paper; no paid call."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import second_read as R
from app.aim_review.engine import StepFailed, to_line
from app.aim_review.paper import Paper

PAGES = {
    1: "Design pressure of the invented item: 25 bar gauge at the inlet\n",
    2: "Seat material: invented alloy grade two\n",
}
DOC = Paper(paper_id="doc_two", pages=PAGES)
GOOD = "Design pressure of the invented item: 25 bar gauge"
MODEL = "claude-sonnet-5-5"


def _line(label="Not met", **over):
    return {"item_id": "C01", "field": "f", "label": label, "page": 1, "quote": GOOD, "comment": "First reader's words.",
            "code": "", "source": "held standard", "code_compare": None, "deferred": False, **over}  # fmt: skip


class _Reader:
    def __init__(self, reads=None, fail=None):
        self.reads, self.fail, self.asked = reads or [], fail, []

    def ask(self, **kw):
        self.asked.append(kw)
        if self.fail:
            raise StepFailed(f"aim_second_read: {self.fail}")
        return {"reads": self.reads}


def _read(lines, reads, **kw):
    return R.s4c_second_read(_Reader(reads, **kw), DOC, lines, {"items": []}, MODEL)


@pytest.mark.parametrize("second", ["Not met", "AI opinion"])
def test_two_readers_who_both_find_a_fault_send_the_line_as_it_is(second):
    lines = [_line()]
    assert (
        _read(
            lines, [{"n": 1, "label": second, "page": 1, "quote": GOOD, "reason": "r"}]
        )
        == 0
    )
    assert (
        lines[0]["label"] == "Not met"
        and lines[0]["code"] == aim_review.TWO_READERS_AGREE
    )
    assert lines[0]["comment"] == "First reader's words."


@pytest.mark.parametrize(
    "read",
    [
        {
            "n": 1,
            "label": "Met",
            "page": 1,
            "quote": GOOD,
            "reason": "The value is within the limit.",
        },
        {
            "n": 1,
            "label": "Not met",
            "page": 1,
            "quote": "words not on the paper at all",
            "reason": "x",
        },  # quote not found
        {
            "n": 1,
            "label": "Not met",
            "page": 1,
            "quote": "Design pressure ... gauge",
            "reason": "x",
        },  # "..." part
        {
            "n": 9,
            "label": "Not met",
            "page": 1,
            "quote": GOOD,
        },  # no answer for this line
    ],
)
def test_a_disagreement_is_a_sent_question_with_the_first_readers_plain_words_and_both_readers_in_the_note(
    read,
):
    lines = [_line()]
    assert _read(lines, [read]) == 1
    d = lines[0]
    assert d["label"] == "Question" and aim_review.sendable(to_line(1, d))
    # the comment is the first reader's own plain words: no reader names, no labels, no process wording
    assert d["comment"] == "First reader's words."
    assert "reader" not in d["comment"].replace("First reader's words.", "").lower()
    assert d["code"].startswith(f"{aim_review.READERS_DIFFER}: first Not met, second ")
    assert d["quote"] == GOOD  # the first reader's evidence stays


@pytest.mark.parametrize(
    "line",
    [
        _line(
            code_compare={"result": "fail", "read_from": "verified quotes"}
        ),  # a code-compared Fail: code's own verdict
        _line(
            code_compare={"result": "fail", "read_from": "verified paper quotes"}
        ),  # any comparison by code
        _line(label="Question"),
        _line(label="Met"),
        _line(code="provisional_unchecked"),
        _line(deferred=True),
        _line(code="not_judged"),  # not sent
    ],
)
def test_nothing_code_compared_and_no_question_or_met_is_offered(line):
    reader = _Reader([{"n": 1, "label": "Met", "page": 1, "quote": GOOD}])
    assert (
        R.s4c_second_read(reader, DOC, [line], {"items": []}, MODEL) == 0
        and reader.asked == []
    )
    assert "readers" not in (line.get("code") or "")


def test_a_failed_second_reader_changes_nothing():
    lines = [_line()]
    assert _read(lines, [], fail="transport ReadTimeout") == 0
    assert lines[0]["label"] == "Not met" and lines[0]["code"] == ""


def test_the_second_reader_is_blind_to_the_first_readers_label_and_words():
    reader = _Reader([])
    R.s4c_second_read(reader, DOC, [_line(comment="FIRST-READER-SECRET")], {"items": [{"id": "C01", "topic": "t",
                      "what_to_check": "w", "rule_quote": "The design pressure shall not exceed 20 bar gauge."}]}, MODEL)  # fmt: skip
    prompt = reader.asked[0]["prompt"]
    assert (
        "FIRST-READER-SECRET" not in prompt
        and '"label"' not in prompt.split("THE ITEMS:")[1]
    )
    assert (
        "shall not exceed 20 bar gauge" in prompt
        and reader.asked[0]["step"] == "aim_second_read"
    )


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    from tests.test_aim_method_helpers import open_aim_db

    yield from open_aim_db(tmp_path, monkeypatch)


def test_a_run_asks_the_second_reader_after_the_judge_and_before_the_editor(aim_db):
    from app.aim_review import engine as E
    from tests.test_aim_method_helpers import BOOK_A, BOOK_B, PAPER, MemoryStore

    model = E.FakeModel(
        kind="datasheet",
        subject_key="test_item",
        answers={"aim_second_read": {"reads": []}},
    )
    r = aim_review.run(aim_db, run_id="run_two_readers", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    steps = [c["step"] for c in model.asked]
    assert r.status == "done" and steps.index("aim_second_read") < steps.index(
        "aim_edit"
    )
    differ = [
        ln for ln in r.lines if aim_review.READERS_DIFFER in (ln["code_note"] or "")
    ]
    assert differ and all(
        ln["label"] == "Question" for ln in differ
    )  # no answer: every offered finding is to be checked


def test_a_line_a_reference_paper_checked_never_goes_to_the_second_reader():
    reader = _Reader([{"n": 1, "label": "Met", "page": 1, "quote": GOOD}])
    differs = _line(label="AI opinion", code="reference_checked: Invented Schedule X")
    assert (
        R.s4c_second_read(reader, DOC, [differs], {"items": []}, MODEL) == 0
        and reader.asked == []
    )
    assert differs["label"] == "AI opinion" and "readers" not in differs["code"]


def test_a_long_first_readers_comment_is_kept_whole_nothing_is_cut():
    """The comment is the first reader's own words, unchanged: nothing is cut (so no cut needs a mark); the readers' words are in the note."""
    lines = [_line(comment="x" * 2000)]
    _read(lines, [{"n": 1, "label": "Met", "page": 1, "quote": GOOD, "reason": "r"}])
    assert lines[0]["comment"] == "x" * 2000 and "readers differ" in lines[0]["code"]
