"""The bench stops on any big jump against its baseline, in both directions. Owner's
order, after a change moved one document's sent-away count from 19 to 1246 and its CRS
lines from 3 to 2 with the gate green: that document's baseline had been 1328."""

from __future__ import annotations

import pytest
from tools import crs_bench

CASE = {"name": "Doc", "run": "r"}


def _m(**over):
    base = {
        "run": "r",
        "document": "d",
        "model": None,
        "quotes_verified": 100,
        "wrong": 0,
        "untrue": 2,
        "irrelevant": 0,
        "pass_on_deferred": 1,
        "sent_away": 100,
        "checklist_decided": 100,
        "checklist_total": 200,
        "rules_decided": 100,
        "rules_in_scope": 200,
        "quotes_unverified": 100,
        "quotes_total": 200,
        "pages_read": 100,
        "pages_total": 200,
        "findings": 300,
        "fails": 3,
        "passes": 4,
        "crs_lines": 5,
        "kind_ok": True,
        "kind": "datasheet",
    }
    return {**base, **over}


def _gate(then: dict, now: dict) -> list[str]:
    before = [{"case": CASE, "stored": _m(**then)}]
    return crs_bench.gate([{"case": CASE, "stored": _m(**now)}], before)


def _jumps(then: dict, now: dict) -> list[str]:
    return [r for r in _gate(then, now) if "big jump" in r]


def test_the_case_the_owner_saw_stops_the_gate():
    reasons = _gate({"sent_away": 19, "crs_lines": 3}, {"sent_away": 1246, "crs_lines": 2})
    assert any("big jump: sent_away 19 -> 1246 (+6457.9%)" in r for r in reasons)
    assert any("big jump: crs_lines 3 -> 2 (-33.3%)" in r for r in reasons)


def test_a_jump_up_on_a_better_when_higher_measure_stops_until_re_saved():
    reasons = _jumps({"rules_decided": 100}, {"rules_decided": 150})
    assert len(reasons) == 1
    assert "big jump: rules_decided 100 -> 150 (+50.0%)" in reasons[0]
    assert "better when higher" in reasons[0] and "re-saves" in reasons[0]


def test_a_jump_down_on_a_better_when_lower_measure_is_an_improvement_and_still_stops():
    assert "sent_away" in crs_bench.BETTER_WHEN_LOWER
    reasons = _jumps({"sent_away": 1328}, {"sent_away": 19})
    assert len(reasons) == 1
    assert "big jump: sent_away 1328 -> 19 (-98.6%)" in reasons[0]
    assert "better when lower" in reasons[0] and "re-saves" in reasons[0]


def test_a_re_saved_baseline_is_the_way_past_a_jump():
    now = _m(sent_away=19)
    assert crs_bench.gate(
        [{"case": CASE, "stored": now}], [{"case": CASE, "stored": dict(now)}]
    ) == []


@pytest.mark.parametrize("key", ["sent_away", "irrelevant", "findings", "pages_read"])
def test_a_small_change_is_not_a_big_jump(key):
    assert _jumps({key: 100}, {key: 110}) == []
    assert _jumps({key: 100}, {key: 90}) == []


@pytest.mark.parametrize(
    "old, new, stops",
    [
        (40, 50, False),  # exactly 25%: "more than" is not met
        (39, 49, True),  # 25.6% and 10 rows
        (30, 39, False),  # 30% but 9 rows
        (30, 40, True),  # 33.3% and 10 rows
        (0, 9, False),  # from nothing, 9 rows
        (0, 10, True),  # from nothing, 10 rows
        (50, 40, False),  # 20% down
        (40, 30, False),  # exactly 25% down
        (39, 29, True),  # 25.6% down and 10 rows
    ],
)
def test_the_thresholds_at_their_edge(old, new, stops):
    # findings: gated on no direction, so only the big-jump rule can stop it
    assert bool(_gate({"findings": old}, {"findings": new})) is stops


def test_the_thresholds_live_in_one_named_place_and_decide_the_gate(monkeypatch):
    assert crs_bench.BIG_JUMP_PERCENT == 25 and crs_bench.BIG_JUMP_MIN_ROWS == 10
    monkeypatch.setattr(crs_bench, "BIG_JUMP_MIN_ROWS", 20)
    assert _jumps({"findings": 100}, {"findings": 130}) != []
    assert _jumps({"findings": 100}, {"findings": 119}) == []
    monkeypatch.setattr(crs_bench, "BIG_JUMP_PERCENT", 50)
    assert _jumps({"findings": 100}, {"findings": 130}) == []


def test_from_zero_says_so_and_prints_no_percent():
    reasons = _jumps({"findings": 0}, {"findings": 40})
    assert reasons == ["Doc: big jump: findings 0 -> 40 (from 0, no percent)"]


@pytest.mark.parametrize(
    "key", ["untrue", "fails", "passes", "pass_on_deferred", "crs_lines"]
)
@pytest.mark.parametrize("step", [1, -1])
def test_any_change_stops_where_small_numbers_matter(key, step):
    old = _m()[key]
    assert key in crs_bench.ANY_CHANGE_STOPS
    assert any(f"big jump: {key} {old} -> {old + step}" in r for r in _gate({}, {key: old + step}))


def test_wrong_moving_up_by_one_stops():
    reasons = _gate({"wrong": 1}, {"wrong": 2})
    assert any("big jump: wrong 1 -> 2" in r for r in reasons)


def test_wrong_moving_down_prints_but_does_not_stop_the_comparison():
    before = [{"case": CASE, "stored": _m(wrong=3)}]
    after = [{"case": CASE, "stored": _m(wrong=0)}]
    assert crs_bench.gate(after, before) == []
    text = crs_bench.render_markdown(after, {}, title="t", baseline=before)
    assert "Gate: GREEN" in text
    assert "wrong 3 -> 0" in text and "not a failure" in text


def test_a_measure_that_was_null_prints_as_null_and_never_as_zero():
    before = [{"case": CASE, "stored": _m(passes=None)}]
    after = [{"case": CASE, "stored": _m(passes=7)}]
    assert crs_bench.gate(after, before) == []
    text = crs_bench.render_markdown(after, {}, title="t", baseline=before)
    assert "passes was null, now 7" in text
    assert "passes 0 ->" not in text


def test_a_baseline_older_than_a_measure_is_null_not_zero():
    old = _m()
    del old["passes"]
    before = [{"case": CASE, "stored": old}]
    after = [{"case": CASE, "stored": _m(passes=7)}]
    assert crs_bench.gate(after, before) == []
    assert "passes was null, now 7" in crs_bench.render_markdown(
        after, {}, title="t", baseline=before
    )


def test_a_measure_that_goes_null_stops_and_never_reads_as_zero():
    reasons = _gate({"crs_lines": 5}, {"crs_lines": None})
    assert any("big jump: crs_lines 5 -> blank" in r for r in reasons)
    assert not any("crs_lines 5 -> 0" in r for r in reasons)


def test_one_change_stops_once_not_twice():
    reasons = _gate({"sent_away": 100}, {"sent_away": 200})
    assert len([r for r in reasons if "sent_away" in r]) == 1


def test_each_document_and_each_measure_is_judged_on_its_own():
    other = {"name": "Other", "run": "s"}
    before = [{"case": CASE, "stored": _m()}, {"case": other, "stored": _m()}]
    now = [
        {"case": CASE, "stored": _m(findings=400)},
        {"case": other, "stored": _m(pages_total=300)},
    ]
    assert crs_bench.gate(now, before) == [
        "Doc: big jump: findings 300 -> 400 (+33.3%)",
        "Other: big jump: pages_total 200 -> 300 (+50.0%)",
    ]


def test_the_replay_column_is_the_one_compared_when_both_have_it():
    before = [{"case": CASE, "stored": _m(), "replay": _m()}]
    now = [{"case": CASE, "stored": _m(), "replay": _m(findings=400)}]
    assert any("findings" in r for r in crs_bench.gate(now, before))
    moved_stored = [{"case": CASE, "stored": _m(findings=400), "replay": _m()}]
    assert crs_bench.gate(moved_stored, before) == []


def test_different_settings_stay_one_reason_and_compare_nothing():
    before = [{"case": CASE, "config": "a", "stored": _m()}]
    now = [{"case": CASE, "config": "b", "stored": _m(findings=999)}]
    reasons = crs_bench.gate(now, before)
    assert len(reasons) == 1 and "settings differ" in reasons[0]


def test_the_table_prints_the_thresholds_the_directions_and_who_re_saves():
    results = [{"case": CASE, "stored": _m()}]
    text = crs_bench.render_markdown(results, {}, title="t")
    assert "more than 25% and at least 10 rows" in text
    for key in crs_bench.ANY_CHANGE_STOPS + crs_bench.BETTER_WHEN_LOWER:
        assert key in text
    assert "Better when lower:" in text
    assert "needs a table on the PR" in text
    assert "the lead's" in text and "the owner's" in text


def test_every_measure_the_gate_reads_is_in_the_big_jump_check():
    gated = (
        crs_bench.HIGHER_IS_WORSE
        + crs_bench.LOWER_IS_WORSE
        + ("wrong", "quotes_total", "findings")
    )
    assert set(gated) <= set(crs_bench.JUMP_MEASURES)
    # every count in the table's rows, each x/y's denominator too
    assert {
        "fails",
        "crs_lines",
        "passes",
        "checklist_total",
        "rules_in_scope",
        "pages_total",
    } <= set(crs_bench.JUMP_MEASURES)
