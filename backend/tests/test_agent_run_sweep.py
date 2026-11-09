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
    prov = al.FakeProvider([fin(1), fin(2), boom, fin(9, "GREEN"), boom])
    out = go(copy_db, run_dir, prov, [item(1, repeat=True), item(2), item(3)])
    live, res = read(out, "LIVE.md"), read(out, "RESULTS.md")
    # the failed third run is not done (a resume asks it again): LIVE counts the runs that are done
    assert "3/3 items (2 sweep runs done)" in live
    assert "DONE**: 3 of 3 items" in live and "Items finished: 3" in res
    assert (
        "items ended by provider error: 2" in res
    )  # skill items: I1 (its third run) and I3
    assert "sweep runs asked: 3 (ended by provider error 1" in res
    assert "2 sweep findings from 1 sweep items, 3 sweep runs asked" in res


def test_j_why_a_sweep_stopped_is_reported_and_a_failed_run_is_asked_again(
    copy_db, run_dir
):
    boom = lambda _m: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    out = go(copy_db, run_dir, al.FakeProvider([fin(1), boom]), [item(1, repeat=True)])
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
        copy_db, run_dir, al.FakeProvider([fin(1), boom]), [item(1, repeat=True)]
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
