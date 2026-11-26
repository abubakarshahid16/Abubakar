"""Roles 5 and 6 of the nine roles on the general review (lead-4, 26 Nov 2026; behind the nine-role gate `updates.nine_roles`, off).
Role 5: after the judge, the checklist asks ONCE more, under its own step, only the items the judge left "not judged"; the
checklist-before-the-judge order is unchanged. Role 6: the second reviewer's work (the attack and the second read) counted in the
record. A whole run with the fake model; invented paper and books; no paid call, no socket."""

from __future__ import annotations

import pytest

from app import aim_review
from app.aim_review import (
    NOT_JUDGED,
    READERS_DIFFER,
    TWO_READERS_AGREE,
    answer_schema,
    local_model,
    missed,
    prompts,
    roles,
    updates,
)
from app.aim_review import engine as E
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

RUN = "run_nine_t56"
SKIPPED = "C001"  # the item the fake judge leaves without an answer


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _judge_skips(model, skipped=SKIPPED):
    """The fake judge answers every item but `skipped` (as a judge answer that names no finding for it)."""

    def answer(step, cached, prompt):
        got = model.fake_answer(step, cached, prompt)
        return {"judgments": [j for j in got["judgments"] if j["id"] != skipped]}

    model.answers["aim_judge"] = answer
    return model


def _run(conn, model):
    result = aim_review.run(conn, run_id=RUN, paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=MemoryStore(),
                            max_usd=5.0, model=model)  # fmt: skip
    updates.nine_end(RUN, {"calls": result.calls, "lines": result.lines})
    return result


def _of(result, item):
    return [x for x in result.lines if x.get("item_id") == item]


def _code(x) -> str:
    return str(x.get("code_note") or x.get("code") or "")


def _role(conn, n):
    import json

    row = conn.execute(
        f"SELECT state, produced_json FROM {roles.ROLES} WHERE run_id = ? AND role_no = ?",
        (RUN, n),
    ).fetchone()
    return row["state"], json.loads(row["produced_json"] or "{}")


def test_off_an_item_the_judge_left_unanswered_stays_not_judged_and_nothing_is_asked_again(
    aim_db,
):
    model = _judge_skips(E.FakeModel(kind="datasheet", subject_key="test_item"))
    result = _run(aim_db, model)
    assert _of(result, SKIPPED) and all(
        NOT_JUDGED in _code(x) for x in _of(result, SKIPPED)
    )  # today's run, unchanged
    assert missed.STEP not in {a["step"] for a in model.asked}


def test_on_the_checklist_asks_again_only_what_the_judge_missed_and_its_answer_takes_the_place(
    aim_db, monkeypatch
):
    monkeypatch.setattr(
        updates, "nine_roles", lambda: True
    )  # the nine-role gate on, whatever switch it reads
    model = _judge_skips(E.FakeModel(kind="datasheet", subject_key="test_item"))
    result = _run(aim_db, model)
    again = [a for a in model.asked if a["step"] == missed.STEP]
    assert (
        len(again) == 1 and f'"id": "{SKIPPED}"' in again[0]["prompt"]
    )  # one call, for the missed item only
    others = {i for i in {x.get("item_id") for x in result.lines} if i and i != SKIPPED}
    assert others and not any(
        f'"id": "{i}"' in again[0]["prompt"] for i in others
    )  # a judged item is never asked again
    assert _of(result, SKIPPED) and not any(
        NOT_JUDGED in _code(x) for x in _of(result, SKIPPED)
    )
    assert all(
        missed.ASKED_AGAIN in _code(x) for x in _of(result, SKIPPED)
    )  # the team file says it was asked again
    state, produced = _role(aim_db, 5)
    assert state == "ran"
    assert produced["calls_answered"] == _calls(
        model, 5
    )  # the checklist's own calls and the one asked again
    assert produced["lines_answered_after_the_judge"] == len(_of(result, SKIPPED))


def _calls(model, role):
    return sum(1 for a in model.asked if roles.ROLE_OF_STEP.get(a["step"], 4) == role)


def test_on_an_item_still_unanswered_keeps_its_not_judged_line_as_it_was(
    aim_db, monkeypatch
):
    monkeypatch.setattr(
        updates, "nine_roles", lambda: True
    )  # the nine-role gate on, whatever switch it reads
    model = _judge_skips(E.FakeModel(kind="datasheet", subject_key="test_item"))
    model.answers[missed.STEP] = lambda step, cached, prompt: {
        "judgments": []
    }  # the second ask answers nothing either
    result = _run(aim_db, model)
    lines = _of(result, SKIPPED)
    assert (
        len(lines) == 1 and _code(lines[0]) == NOT_JUDGED
    )  # its "not judged" line exactly as it was
    assert _role(aim_db, 5)[1]["lines_answered_after_the_judge"] == 0


def test_nothing_is_asked_again_when_the_run_is_stopping():
    lines = [{"item_id": "C1", "code": NOT_JUDGED}]
    assert missed.ask_again(
        object(), None, {}, None, [{"id": "C1"}], lines, "stop: run_cap"
    ) == (lines, "stop: run_cap")


def test_an_item_with_any_judged_line_is_not_missed():
    items = [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]
    lines = [
        {"item_id": "C1", "code": NOT_JUDGED},
        {"item_id": "C2", "code": NOT_JUDGED},
        {"item_id": "C2", "code": ""},  # one place judged: the item was judged
        {"item_id": "C3", "code": ""},
    ]
    assert [it["id"] for it in missed.missed(items, lines)] == ["C1"]


def test_role_6_counts_the_lines_the_second_reader_checked():
    lines = [
        {"code_note": TWO_READERS_AGREE},
        {"code_note": f"x; {READERS_DIFFER}: first Not met, second Met"},
        {"code_note": ""},
    ]
    assert roles._review_counts(6, lines) == {
        "lines_two_readers_agree": 1,
        "lines_readers_differ": 1,
    }


def test_the_new_step_is_known_everywhere_a_step_is_named():
    step = missed.STEP
    assert roles.ROLE_OF_STEP[step] == 5
    assert (
        answer_schema.SCHEMAS[step] == answer_schema.SCHEMAS["aim_judge"]
    )  # the judge's own answer shape
    assert prompts.ANSWER_KEYS[step] == prompts.ANSWER_KEYS["aim_judge"]
    assert step in local_model.STEP_GROUPS["judge"]  # the judge's local model setting
