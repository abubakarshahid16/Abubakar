"""#1690 sweep items: one skill item with repeat=true yields several findings. Invented data, fake provider."""

import json
import sqlite3
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app import agent_loop as al
from app import agent_run as ar
from app import agent_run_sweep as sw
from app import agent_skills as sk

NONE_LEFT = {"tool": "ask_engineer", "args": {"reason": "none left"}, "model": "m"}


def item(n, **extra):
    return {"id": f"I{n}", "order": n, "topic": f"zorblat rating {n}", "expected": "x",
            "acceptable_range": "x", "escalate_when": "x", "clause_refs": [], **extra}  # fmt: skip


def skill(*items):
    return {"kind": "invented_kind", "version": "1", "items": list(items)}


def fin(n, colour="YELLOW", quote=None):
    return {"final": {"color": colour, "doc_quote": quote or f"invented field {n}  is   deferred", "page": 1,
                      "clause_quote": "c", "standard": "ISO 9999", "clause": "4.1", "action": "Confirm",
                      "priority": "must", "reason": "deferred"}, "model": "m", "usd": 0.01}  # fmt: skip


class Box:
    TOOL_SPECS: ClassVar[list] = [
        {"name": n, "description": "", "params": {}} for n in al.TOOL_NAMES
    ]

    def __init__(self):
        self.ctx = SimpleNamespace(findings=None)

    def set_item(self, item_id, topic=""):
        self.item = (item_id, topic)

    def run(self, name, args):
        if name == "record_finding":
            return {"ok": True, "result": {"verdict": "accepted"}, "cites": []}
        return {"ok": True, "result": {}, "cites": []}


def factory(scope, readers):
    box = Box()
    box.scope, box.readers = scope, readers
    return box


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HEAVY_JOB_LOCK", "off")
    return tmp_path / "run"


@pytest.fixture
def copy_db(tmp_path):
    path = tmp_path / "copy.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "INSERT INTO documents VALUES ('D1','invented-sheet.pdf');"
        "INSERT INTO pages VALUES ('D1',1,'zorblat rating page one');"
    )
    db.commit()
    db.close()
    return path


def go(copy_db, run_dir, provider, sk_items, **kw):
    return ar.run_review(copy_db, "D1", "invented_kind", provider, run_dir=run_dir,
                         toolbox_factory=factory, skill=skill(*sk_items), **kw)  # fmt: skip


def ids(out):
    return [f["item"] for f in out["findings"]]


def paid(usd=0.1):
    """A paid tool step: a provider error after it has spend, so the failure breaker does not count it."""
    tool = next(n for n in al.TOOL_NAMES if n not in ("record_finding", "ask_engineer"))
    return {"tool": tool, "args": {}, "usd": usd}


def results_text(out):
    return (ar.Path(out["run_dir"]) / ar.FILES["results"]).read_text(encoding="utf-8")


def test_a_three_findings_then_none_left_stops(copy_db, run_dir):
    prov = al.FakeProvider([fin(1), fin(2), fin(3), NONE_LEFT])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert ids(out) == ["I1#1", "I1#2", "I1#3"]
    assert out["items_done"] == 1 and out["items_total"] == 1
    assert out["quote_verified"] == 3
    text = results_text(out)
    assert "Items finished: 1" in text
    assert "3 sweep findings from 1 sweep items" in text
    # run n is told what runs 1..n-1 recorded, cut to 80 chars, whitespace folded; run 1 gets an empty list
    firsts = [c[0]["content"] for c in prov.calls]
    assert firsts[0]["item"]["already_recorded"] == []
    assert firsts[3]["item"]["already_recorded"] == [
        "invented field 1 is deferred", "invented field 2 is deferred", "invented field 3 is deferred"]  # fmt: skip
    assert al.SWEEP_SENTENCE in firsts[1]["instruction"]


def test_b_a_duplicate_quote_stops_the_repeat(copy_db, run_dir):
    prov = al.FakeProvider([fin(1), fin(1), fin(3)])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert ids(out) == ["I1#1"]
    assert len(prov.calls) == 2  # the third script entry was never asked for


def test_c_repeat_max_caps_it(copy_db, run_dir):
    prov = al.FakeProvider([fin(n) for n in range(1, 9)])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True, repeat_max=2)])
    assert ids(out) == ["I1#1", "I1#2"]
    assert len(prov.calls) == 2


def test_d_green_and_red_are_stored_as_yellow(copy_db, run_dir):
    prov = al.FakeProvider([fin(1, "GREEN"), fin(2, "RED"), NONE_LEFT])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert [f["color"] for f in out["findings"]] == ["YELLOW", "YELLOW"]
    assert "GREEN 0 and RED 0" in results_text(out)
    assert "YELLOW 2" in results_text(out)


def test_e_a_normal_item_is_unchanged(copy_db, run_dir):
    prov = al.FakeProvider([fin(1, "GREEN")])
    out = go(copy_db, run_dir, prov, [item(1)])
    assert ids(out) == ["I1"] and out["findings"][0]["color"] == "GREEN"
    assert "already_recorded" not in prov.calls[0][0]["content"]["item"]
    assert al.SWEEP_SENTENCE not in prov.calls[0][0]["content"]["instruction"]
    assert "Sweep:" not in results_text(out)


def test_first_run_with_nothing_found_keeps_one_yellow_row(copy_db, run_dir):
    out = go(copy_db, run_dir, al.FakeProvider([NONE_LEFT]), [item(1, repeat=True)])
    assert ids(out) == ["I1#1"] and out["findings"][0]["color"] == "YELLOW"
    assert out["items_done"] == 1 and out["quote_verified"] == 0


def test_mixed_items_count_items_and_findings_separately(copy_db, run_dir):
    prov = al.FakeProvider([fin(1), fin(2), NONE_LEFT, fin(9, "GREEN")])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True), item(2)])
    assert ids(out) == ["I1#1", "I1#2", "I2"]
    assert out["items_done"] == 2
    text = results_text(out)
    assert "Items finished: 2" in text and "2 sweep findings from 1 sweep items" in text


def test_g_resume_does_not_duplicate_saved_findings(copy_db, run_dir):
    class Killed(BaseException):
        pass

    def die(_m):
        raise Killed

    prov = al.FakeProvider([fin(1), fin(2), die])
    with pytest.raises(Killed):
        go(copy_db, run_dir, prov, [item(1, repeat=True)])
    again = al.FakeProvider([fin(3), NONE_LEFT])
    out = go(copy_db, run_dir, again, [item(1, repeat=True)])
    assert ids(out) == ["I1#1", "I1#2", "I1#3"]
    assert len(again.calls) == 2  # runs 1 and 2 were not asked again
    lines = (ar.Path(out["run_dir"]) / "findings.jsonl").read_text().splitlines()
    assert sorted(json.loads(x)["item"] for x in lines) == ["I1#1", "I1#2", "I1#3"]
    # a third start asks nothing new for the finished sweep except the none-left run it already has saved
    last = al.FakeProvider([])
    assert ids(go(copy_db, run_dir, last, [item(1, repeat=True)])) == [
        "I1#1",
        "I1#2",
        "I1#3",
    ]
    assert last.calls == []


def test_keys_for_orders_numerically():
    finals = {f"I1#{n}": {} for n in (10, 2, 1)} | {"I1x": {}, "I12#3": {}}
    assert sw.keys_for(item(1, repeat=True), finals) == ["I1#1", "I1#2", "I1#10"]
    assert sw.base_id("I1#4") == "I1"


# ---- the loader (f) ----------------------------------------------------------------------------------------------


def checked(**extra):
    return sk.validate_skill(skill(item(1, **extra)))


def test_f_loader_accepts_repeat_and_repeat_max():
    assert checked(repeat=True)["items"][0]["repeat"] is True
    assert checked(repeat=False)
    assert checked(repeat=True, repeat_max=1) and checked(repeat=True, repeat_max=30)


@pytest.mark.parametrize(
    "extra",
    [{"repeat": "yes"}, {"repeat": 1}, {"repeat": True, "repeat_max": 0}, {"repeat": True, "repeat_max": 31},
     {"repeat": True, "repeat_max": True}, {"repeat": True, "repeat_max": "5"}, {"repeat_max": 5},
     {"repeat": False, "repeat_max": 5}, {"repeat": True, "other": 1}],
)  # fmt: skip
def test_f_loader_rejects(extra):
    with pytest.raises(sk.SkillError):
        checked(**extra)


def read(out, name):
    return (ar.Path(out["run_dir"]) / name).read_text(encoding="utf-8")


def test_h_no_green_or_red_anywhere_for_a_sweep_run(copy_db, run_dir):
    prov = al.FakeProvider([fin(1, "GREEN"), fin(2, "RED"), NONE_LEFT])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    live = read(out, "LIVE.md")
    assert "GREEN 0, YELLOW 2, RED 0" in live
    assert (
        "GREEN 0, YELLOW 2, RED 0" in out["status_box"]
        or "YELLOW 2" in out["status_box"]
    )
    assert "GREEN 1" not in out["status_box"] and "RED 1" not in out["status_box"]
    for name in ("findings.jsonl", "state.json", "finals.json"):
        text = read(out, name)
        assert '"GREEN"' not in text and '"RED"' not in text, name
    assert [f["color"] for f in out["findings"]] == ["YELLOW", "YELLOW"]


def test_i_item_counts_tell_one_story_for_a_mixed_run(copy_db, run_dir):
    boom = lambda _m: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    prov = al.FakeProvider(
        [fin(1), fin(2), paid(), boom, boom, fin(9, "GREEN"), paid(), boom, boom]
    )
    out = go(copy_db, run_dir, prov, [item(1, repeat=True), item(2), item(3)])
    live, res = read(out, "LIVE.md"), read(out, "RESULTS.md")
    # the failed third run is not done (a resume asks it again): LIVE counts the runs that are done
    assert "3/3 items (2 sweep runs done)" in live
    assert "DONE**: 3 of 3 items" in live and "Items finished: 3" in res
    assert (
        "items ended by provider error: 2" in res
    )  # skill items: I1 (its third run) and I3
    assert "sweep runs asked: 4 (ended by provider error 1" in res
    assert "2 sweep findings from 1 sweep items, 4 sweep runs asked" in res


def test_j_why_a_sweep_stopped_is_reported_and_a_failed_run_is_asked_again(
    copy_db, run_dir
):
    boom = lambda _m: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    out = go(
        copy_db,
        run_dir,
        al.FakeProvider([fin(1), paid(), boom, boom]),
        [item(1, repeat=True)],
    )
    assert ids(out) == ["I1#1"]
    assert "sweep stopped early: provider error (I1)" in results_text(out)
    again = al.FakeProvider([fin(2), NONE_LEFT])
    out = go(copy_db, run_dir, again, [item(1, repeat=True)])
    assert ids(out) == ["I1#1", "I1#2"] and len(again.calls) == 2
    assert "sweep stopped early" not in results_text(
        out
    )  # it ended on 'none left' this time


def test_j_none_left_is_quiet_and_other_stops_are_named(copy_db, run_dir):
    out = go(
        copy_db, run_dir, al.FakeProvider([fin(1), NONE_LEFT]), [item(1, repeat=True)]
    )
    assert "sweep stopped early" not in results_text(out)
    out = go(
        copy_db,
        run_dir / "b",
        al.FakeProvider([fin(1), fin(1)]),
        [item(1, repeat=True)],
    )
    assert "sweep stopped early: duplicate quote (I1)" in results_text(out)
    out = go(
        copy_db,
        run_dir / "c",
        al.FakeProvider([fin(1), fin(2), fin(3)]),
        [item(1, repeat=True, repeat_max=2)],
    )
    assert "sweep stopped early: repeat_max (I1)" in results_text(out)
    cap = {
        "tool": next(
            n for n in al.TOOL_NAMES if n not in ("record_finding", "ask_engineer")
        ),
        "args": {},
        "usd": 9.0,
    }
    out = go(
        copy_db,
        run_dir / "d",
        al.FakeProvider([fin(1), cap]),
        [item(1, repeat=True)],
        usd_cap_item=1.0,
    )
    assert "sweep stopped early: item cap (I1)" in results_text(out)


def test_k_case_and_punctuation_variants_are_duplicates(copy_db, run_dir):
    prov = al.FakeProvider(
        [
            fin(1, quote="Invented Field: deferred."),
            fin(1, quote="invented  field - DEFERRED"),
            fin(3),
        ]
    )
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert ids(out) == ["I1#1"] and len(prov.calls) == 2


def stop_of(out):
    return json.loads(read(out, "finals.json")).get("I1#stop")


def test_l_resume_of_a_finished_none_left_sweep_keeps_its_reason(copy_db, run_dir):
    go(copy_db, run_dir, al.FakeProvider([fin(1), NONE_LEFT]), [item(1, repeat=True)])
    again = al.FakeProvider([])
    out = go(copy_db, run_dir, again, [item(1, repeat=True)])
    assert again.calls == [] and ids(out) == ["I1#1"]
    assert stop_of(out) == "none left"
    assert "sweep stopped early" not in results_text(out)


def test_m_resume_of_an_item_cap_stop_keeps_its_reason(copy_db, run_dir):
    tool = next(n for n in al.TOOL_NAMES if n not in ("record_finding", "ask_engineer"))
    cap = {"tool": tool, "args": {}, "usd": 9.0}
    kw = {"usd_cap_item": 1.0}
    first = go(
        copy_db, run_dir, al.FakeProvider([fin(1), cap]), [item(1, repeat=True)], **kw
    )
    assert stop_of(first) == "item cap"
    out = go(copy_db, run_dir, al.FakeProvider([]), [item(1, repeat=True)], **kw)
    assert stop_of(out) == "item cap"
    assert "sweep stopped early: item cap (I1)" in results_text(out)


def test_n_provider_error_stop_is_reported_saved_and_retried(copy_db, run_dir):
    boom = lambda _m: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    first = go(
        copy_db,
        run_dir,
        al.FakeProvider([fin(1), paid(), boom, boom]),
        [item(1, repeat=True)],
    )
    assert stop_of(first) == "provider error"
    retry = al.FakeProvider([NONE_LEFT])
    out = go(copy_db, run_dir, retry, [item(1, repeat=True)])
    assert len(retry.calls) == 1 and stop_of(out) == "none left"


def test_o_a_dropped_duplicate_is_not_counted_in_live(copy_db, run_dir):
    out = go(
        copy_db, run_dir, al.FakeProvider([fin(1), fin(1)]), [item(1, repeat=True)]
    )
    assert ids(out) == ["I1#1"]
    assert "YELLOW 1," in read(out, "LIVE.md")  # not 2: the copy is not a finding


def test_p_lookalike_accent_and_fullwidth_variants_are_duplicates(copy_db, run_dir):
    variants = [
        "invented field deferred",
        "Inv\u00e9nted field deferred",
        "\uff49\uff4e\uff56\uff45\uff4e\uff54\uff45\uff44 \uff46\uff49\uff45\uff4c\uff44 \uff44\uff45\uff46\uff45\uff52\uff52\uff45\uff44",
    ]
    for i, second in enumerate(variants[1:]):
        prov = al.FakeProvider(
            [fin(1, quote=variants[0]), fin(1, quote=second), fin(3)]
        )
        out = go(copy_db, run_dir / str(i), prov, [item(1, repeat=True)])
        assert ids(out) == ["I1#1"] and len(prov.calls) == 2


# ---- local early stops: one retry after a provider error, one rerun on a higher step cap (repeat items only) ----------
def boom(_m):
    raise RuntimeError("down")


def steps(n):
    return [paid(0.001) for _ in range(n)]


def test_q_provider_error_then_success_records_the_finding_and_counts_the_retry(
    copy_db, run_dir
):
    prov = al.FakeProvider([boom, fin(1), NONE_LEFT])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert ids(out) == ["I1#1"] and stop_of(out) == "none left"
    res = results_text(out)
    assert "sweep runs asked: 3 (" in res  # I1#1 twice, I1#2 once: every attempt counts
    assert "retried after provider error 1, rerun on the higher step cap 0" in res
    assert "sweep stopped early" not in res


def test_r_one_flaky_run_asked_twice_is_not_two_items_for_the_breaker(copy_db, run_dir):
    out = go(copy_db, run_dir, al.FakeProvider([boom, boom]), [item(1, repeat=True)])
    assert not out["stopped"] and stop_of(out) == "provider error"


def test_r2_two_different_items_with_zero_spend_errors_still_trip_the_breaker(
    copy_db, run_dir
):
    prov = al.FakeProvider([boom, boom, boom])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True), item(2), item(3)])
    assert out["stopped"].startswith("provider errors on 2 items in a row")
    assert len(prov.calls) == 3 and out["items_done"] == 0


def test_x_total_cap_is_checked_before_a_retry(copy_db, run_dir):
    spent = {"v": 0.0}

    def boom_and_spend(_m):
        spent["v"] = 99.0
        raise RuntimeError("down")

    prov = al.FakeProvider([boom_and_spend, fin(1), NONE_LEFT])
    import contextlib

    consent = SimpleNamespace(per_request_consent=lambda _ids: contextlib.nullcontext())
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)], claude=True, consent=consent,
             documents=["D1"], ledger=lambda _s: spent["v"], total_cap_usd=10.0)  # fmt: skip
    assert out["stopped"] == "total cap for the agent test" and len(prov.calls) == 1
    fp = (
        run_dir / ar.FILES["finals"]
    )  # nothing is kept as final: a resume asks it again
    assert not fp.exists() or "I1#1" not in json.loads(fp.read_text(encoding="utf-8"))


def test_y_item_cap_bounds_the_first_run_plus_the_rerun(copy_db, run_dir):
    cap, per = 1.8, 0.1
    prov = al.FakeProvider([paid(per) for _ in range(60)])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)], usd_cap_item=cap)
    assert stop_of(out) == "item cap"
    assert len(prov.calls) * per <= cap + per + 1e-9  # not 2x the cap


def test_z_a_retry_adds_to_the_calls_of_the_first_attempt(copy_db, run_dir):
    out = go(copy_db, run_dir, al.FakeProvider([paid(), boom, paid(), boom]), [item(1, repeat=True)])  # fmt: skip
    res = results_text(out)
    assert "tool calls failed: 0 of 2" in res and "sweep runs asked: 2 (" in res
    assert "items ended by provider error: 1" in res


def test_s_two_paid_provider_errors_end_the_sweep_as_provider_error(copy_db, run_dir):
    prov = al.FakeProvider([fin(1), paid(), boom, boom])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert ids(out) == ["I1#1"] and stop_of(out) == "provider error"
    assert len(prov.calls) == 4  # one retry, not more
    res = results_text(out)
    assert "sweep stopped early: provider error (I1)" in res
    assert "retried after provider error 1" in res


def test_t_step_limit_then_success_on_the_higher_cap_records_the_finding(
    copy_db, run_dir
):
    assert sw.REPEAT_RETRY_STEPS > al.MAX_STEPS
    prov = al.FakeProvider([*steps(al.MAX_STEPS), fin(1), NONE_LEFT])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert ids(out) == ["I1#1"] and stop_of(out) == "none left"
    assert "rerun on the higher step cap 1" in results_text(out)


def test_u_step_limit_twice_is_reported_as_step_limit(copy_db, run_dir):
    # the first run stops at the normal cap; the one rerun (a fresh run, the checkpoint is gone) stops at the higher one
    total = al.MAX_STEPS + sw.REPEAT_RETRY_STEPS
    prov = al.FakeProvider(steps(total + 5))
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)])
    assert stop_of(out) == "step limit" and len(prov.calls) == total
    assert "sweep stopped early: step limit (I1)" in results_text(out)


def test_v_a_plain_item_is_not_retried_and_keeps_the_normal_cap(copy_db, run_dir):
    prov = al.FakeProvider(steps(al.MAX_STEPS * 2))
    out = go(copy_db, run_dir, prov, [item(1)])
    assert len(prov.calls) == al.MAX_STEPS and out["items_done"] == 1
    assert "rerun on the higher step cap" not in results_text(out)
    prov = al.FakeProvider([paid(), boom, fin(1)])
    out = go(copy_db, run_dir / "b", prov, [item(1)])
    assert len(prov.calls) == 2  # the error ended the item; nothing asked again


def test_w_resume_after_a_retried_sweep_does_not_duplicate_or_overwrite(
    copy_db, run_dir
):
    go(
        copy_db,
        run_dir,
        al.FakeProvider([boom, fin(1), NONE_LEFT]),
        [item(1, repeat=True)],
    )
    again = al.FakeProvider([])
    out = go(copy_db, run_dir, again, [item(1, repeat=True)])
    assert again.calls == [] and ids(out) == ["I1#1"] and stop_of(out) == "none left"


def test_aa_provider_error_retry_uses_the_item_cap_minus_the_first_attempt(
    copy_db, run_dir
):
    cap, per = 1.5, 0.1
    script = [*(paid(per) for _ in range(10)), boom, *(paid(per) for _ in range(40))]
    prov = al.FakeProvider(script)
    out = go(copy_db, run_dir, prov, [item(1, repeat=True)], usd_cap_item=cap)
    paid_calls = len(prov.calls) - 1  # the one provider error spent nothing
    assert (
        paid_calls * per <= cap + per + 1e-9
    )  # a fresh cap would allow 15 paid steps more
    assert stop_of(out) == "item cap"


def test_ab_a_rerun_adds_to_the_failed_calls_of_the_first_attempt(copy_db, run_dir):
    class FailBox(Box):
        def run(self, name, args):
            if name == paid()["tool"]:
                return {"ok": False, "result": {}, "cites": []}
            return super().run(name, args)

    out = ar.run_review(copy_db, "D1", "invented_kind",
                        al.FakeProvider([paid(), boom, paid(), boom]), run_dir=run_dir,
                        toolbox_factory=lambda s, r: FailBox(), skill=skill(item(1, repeat=True)))  # fmt: skip
    assert "tool calls failed: 2 of 2" in results_text(out)
