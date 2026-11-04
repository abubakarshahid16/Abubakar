"""#1690 agent_loop with a fake provider and a fake toolbox. No model, no network."""

import json
from typing import ClassVar

from app import agent_loop as al
from app import agent_trace as at

SPECS = [{"name": n, "description": "", "params": {}} for n in al.TOOL_NAMES]
GOOD = {
    "color": "GREEN",
    "doc_quote": "invented quote",
    "page": 2,
    "clause_quote": "invented clause",
}


class Box:
    TOOL_SPECS = SPECS

    def __init__(self, accept=True):
        self.accept, self.ran = accept, []

    def run(self, name, args):
        self.ran.append(name)
        if name == "record_finding":
            v = "accepted" if self.accept else "refused"
            return {
                "ok": self.accept,
                "result": {"verdict": v, "reason": "bad quote"},
                "cites": [],
            }
        return {"ok": True, "result": {"text": "x"}, "cites": [{"doc": "d", "page": 1}]}


ITEM = {"id": "i1", "doc": "d"}


def run(script, box=None, **kw):
    box = box or Box()
    kw.setdefault("usd_cap", 1.0)
    return al.run_item(
        ITEM, {}, box, al.FakeProvider(script, usd=kw.pop("cost", 0.0)), **kw
    ), box


def test_tool_then_final_recorded():
    out, box = run(
        [
            {"tool": "open_page", "args": {"doc": "d", "page": 1}, "reason": "look"},
            {"final": GOOD},
        ]
    )
    assert (
        out["finding"]["color"] == "GREEN"
        and out["steps"] == 2
        and box.ran == ["open_page", "record_finding"]
    )


def test_step_limit_is_yellow_and_asks_engineer():
    out, box = run([{"tool": "search", "args": {}, "reason": "r"}] * 5, max_steps=3)
    assert (
        out["finding"]["color"] == "YELLOW"
        and out["finding"]["reason"] == "step limit"
        and out["steps"] == 3
    )
    assert box.ran[-1] == "ask_engineer"


def test_usd_cap_stops():
    out, _ = run([{"tool": "search", "args": {}}] * 5, cost=0.6, usd_cap=1.0)
    assert (
        out["why"] == "usd cap"
        and out["steps"] == 2
        and out["finding"]["color"] == "YELLOW"
    )


def test_refused_finding_is_not_recorded_then_retry():
    box = Box(accept=False)
    out, _ = run([{"final": GOOD}, {"final": GOOD}], box=box, max_steps=2)
    assert out["why"] == "step limit" and out["finding"]["color"] == "YELLOW"
    assert box.ran.count("record_finding") == 2


def test_unknown_tool_ends_yellow_with_problem_line(tmp_path):
    w = at.TraceWriter(tmp_path)
    box = Box()
    p = al.FakeProvider([{"tool": "delete_all", "args": {}}, {"final": GOOD}])
    out = al.run_item(ITEM, {}, box, p, usd_cap=1, trace=w)
    assert out["finding"]["color"] == "YELLOW" and out["why"] == "unknown tool"
    assert box.ran == [] and len(p.calls) == 1
    assert "PROBLEM" in (tmp_path / "live.log").read_text()
    assert w.problems


def test_provider_error_is_yellow():
    class Boom:
        def complete(self, *a):
            raise ValueError("x")

    out = al.run_item(ITEM, {}, Box(), Boom(), usd_cap=1)
    assert out["finding"]["color"] == "YELLOW"


def test_check_final_invariants():
    assert al.check_final({**GOOD, "doc_quote": ""})["color"] == "YELLOW"
    assert "downgraded from GREEN" in al.check_final({**GOOD, "page": None})["reason"]
    assert (
        al.check_final({**GOOD, "reason": "Value is not mentioned"})["color"]
        == "YELLOW"
    )
    assert al.check_final({**GOOD, "color": "blue"})["color"] == "YELLOW"
    assert al.check_final("junk")["color"] == "YELLOW"
    assert al.check_final({**GOOD, "color": "red"})["color"] == "RED"
    assert al.check_final(GOOD)["color"] == "GREEN"


def test_confidence_is_never_sent_whatever_its_value():
    for value in ("high", "High", "low", "medium", 0.9):
        assert "confidence" not in al.check_final({**GOOD, "confidence": value})
    out, _ = run([{"final": {**GOOD, "confidence": "low", "extra": 1}}])
    assert "confidence" not in out["finding"] and "extra" not in out["finding"]
    assert set(out["finding"]) <= set(al.CANON_KEYS)


def test_green_without_quote_is_never_recorded_as_green():
    out, _ = run([{"final": {"color": "GREEN", "page": 1}}])
    assert out["finding"]["color"] == "YELLOW"


def test_resume_replays_without_provider_cost(tmp_path):
    w = at.TraceWriter(tmp_path)
    box = Box()
    p1 = al.FakeProvider(
        [{"tool": "search", "args": {"query": "q"}, "reason": "r"}], usd=0.3
    )
    out = al.run_item(ITEM, {}, box, p1, max_steps=1, usd_cap=5, trace=w)
    assert out["why"] == "step limit"
    # simulate a kill after step 1: checkpoint exists again, item not done
    w.save_checkpoint(
        "i1",
        [
            {
                "tool": "search",
                "args": {"query": "q"},
                "result": None,
                "reason": "r",
                "usd": 0.3,
            }
        ],
    )
    p2 = al.FakeProvider([{"final": GOOD}], usd=0.1)
    out = al.run_item(ITEM, {}, Box(), p2, usd_cap=5, trace=w)
    assert out["steps"] == 2 and abs(out["usd"] - 0.4) < 1e-9 and len(p2.calls) == 1
    assert any(m.get("name") == "search" for m in p2.calls[0])


def test_run_items_skips_completed(tmp_path):
    w = at.TraceWriter(tmp_path, total=2)
    items = [{"id": "a", "doc": "d"}, {"id": "b", "doc": "d"}]
    al.run_items(
        items[:1],
        Box(),
        al.FakeProvider([{"final": GOOD}]),
        w,
        usd_cap_item=1,
        usd_cap_run=5,
    )
    w2 = at.TraceWriter(tmp_path, total=2)
    p = al.FakeProvider([{"final": GOOD}])
    res = al.run_items(items, Box(), p, w2, usd_cap_item=1, usd_cap_run=5)
    assert (
        list(res["results"]) == ["b"]
        and len(p.calls) == 1
        and (tmp_path / "LIVE.md").exists()
    )


def test_run_cap_stops_run(tmp_path):
    w = at.TraceWriter(tmp_path)
    items = [{"id": "a", "doc": "d"}, {"id": "b", "doc": "d"}]
    res = al.run_items(
        items,
        Box(),
        al.FakeProvider([{"final": GOOD}], usd=2.0),
        w,
        usd_cap_item=5,
        usd_cap_run=2,
    )
    assert list(res["results"]) == ["a"] and res["stopped"] and not w.is_done("b")


def test_document_map_keeps_headings_only():
    m = al.build_document_map(
        {
            2: "1 SCOPE\nthis body sentence is long and ends here.\nMore body, text",
            1: "TITLE",
        }
    )
    assert m == [
        {"page": 1, "headings": ["TITLE"]},
        {"page": 2, "headings": ["1 SCOPE"]},
    ]


def test_answer_open_page_one_look():
    class B(Box):
        def run(self, name, args):
            self.ran.append(name)
            if name == "record_finding":
                return {"ok": True, "result": {"verdict": "accepted"}, "cites": []}
            return {"ok": True, "result": {"text": "p"}, "cites": []}

    items = [{"id": "a", "page": 3}, {"id": "b", "pages": [3]}, {"id": "c", "page": 9}]
    p = al.FakeProvider([{"final": {"findings": [{"item": "a", **GOOD}]}}])
    box = B()
    out = al.answer_open_page(items, 3, box, p, doc="d", usd_cap=1)
    assert box.ran.count("open_page") == 1 and len(p.calls) == 1
    assert (
        out["a"]["color"] == "GREEN"
        and out["b"]["color"] == "YELLOW"
        and "c" not in out
    )


# ---- stand-in ToolBox with the real TOOL_SPECS class attribute shape ------------------------------------------
class StandIn:
    """Same shape as the tools helper's box: TOOL_SPECS class attribute, run(name, args) -> dict."""

    TOOL_SPECS: ClassVar[list] = [
        {"name": n, "description": "d", "params": {"x": "str"}} for n in al.TOOL_NAMES
    ]

    def __init__(self, verdict="accepted"):
        self.verdict, self.ran = verdict, []

    def run(self, name, args):
        self.ran.append(name)
        if name == "record_finding":
            ok = self.verdict == "accepted"
            inner = {"verdict": self.verdict, "accepted": ok, "reason": "checked"}
            return {"ok": ok, "result": inner, "cites": []}
        if name == "ask_engineer":
            return {"ok": True, "result": {"queued": True}, "cites": []}
        return {
            "ok": True,
            "result": {
                "text": "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi"
            },
            "cites": [{"doc": "d", "page": 2}],
        }


FULL = {
    "item": "i1",
    "doc": "d",
    "color": "RED",
    "page": 2,
    "doc_quote": "invented words",
    "clause_quote": "invented clause",
    "standard": "S-1",
    "clause": "4.1",
    "action": "fix it",
    "priority": "must",
    "figures": {"a": 1},
    "reason": "differs",
}


def test_integration_standin_toolbox_whole_item(tmp_path):
    w = at.TraceWriter(tmp_path)
    box = StandIn()
    script = [
        {
            "tool": "open_page",
            "args": {"doc": "d", "page": 2},
            "reason": "read the page",
        },
        {
            "tool": "get_clause",
            "args": {"standard": "S-1", "clause": "4.1"},
            "reason": "clause",
        },
        {"final": {**FULL, "confidence": "high"}},
    ]
    out = al.run_item(ITEM, {}, box, al.FakeProvider(script), usd_cap=1, trace=w)
    assert out["finding"]["color"] == "RED" and "confidence" not in out["finding"]
    assert box.ran == ["open_page", "get_clause", "record_finding"]
    text = (tmp_path / "i1.trace.jsonl").read_text()
    assert (
        "invented" not in text and "invented" not in (tmp_path / "live.log").read_text()
    )
    assert w.is_done("i1") is False and not (tmp_path / "i1.ckpt.json").exists()


def test_toolspecs_fall_back_to_agent_tools_module(monkeypatch):
    import types

    mod = types.ModuleType("agent_tools")
    mod.TOOL_SPECS = StandIn.TOOL_SPECS
    monkeypatch.setattr("app.agent_tools", mod, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "app.agent_tools", mod)

    class Bare:
        def run(self, name, args):
            return {"ok": True, "result": {}, "cites": []}

    assert [s["name"] for s in al._specs(Bare())] == list(al.TOOL_NAMES)


def _killed_midway(tmp_path, final_call):
    """Run until the saved call `final_call`, then 'kill' by dropping the writer; return the box used."""
    w = at.TraceWriter(tmp_path)
    box = StandIn()
    al.run_item(
        ITEM, {}, box, al.FakeProvider([final_call]), max_steps=1, usd_cap=5, trace=w
    )
    return box


def test_resume_after_accepted_record_finding_makes_no_model_call(tmp_path):
    # first run: model call 1 = open_page, call 2 = accepted final; process killed before mark_done
    w = at.TraceWriter(tmp_path)
    box = StandIn()
    al.run_item(
        ITEM,
        {},
        box,
        al.FakeProvider(
            [{"tool": "open_page", "args": {"doc": "d", "page": 2}}, {"final": FULL}],
            usd=0.2,
        ),
        usd_cap=5,
        trace=w,
    )
    # put the checkpoint back as the killed process left it (finish_item removes it)
    calls = [
        {
            "tool": "open_page",
            "args": {"doc": "d", "page": 2},
            "rerun": True,
            "reason": "",
            "usd": 0.2,
        },
        {
            "tool": "record_finding",
            "args": {},
            "rerun": False,
            "reason": "final",
            "usd": 0.2,
            "saved": al._saved(
                "record_finding", {"finding": FULL}, box.run("record_finding", {})
            ),
        },
    ]
    w.save_checkpoint("i1", calls)
    box2, p2 = StandIn(), al.FakeProvider([{"final": FULL}])
    out = al.run_item(ITEM, {}, box2, p2, usd_cap=5, trace=at.TraceWriter(tmp_path))
    assert (
        p2.calls == [] and "record_finding" not in box2.ran
    )  # no model call, not recorded twice
    assert (
        out["why"] == "recorded"
        and out["finding"]["color"] == "RED"
        and out["finding"]["page"] == 2
    )
    assert out["steps"] == 2 and abs(out["usd"] - 0.4) < 1e-9
    assert (
        out["finding"]["doc_quote"] == "invented words"
    )  # the stored finding, from the sink
    (tmp_path / "findings.jsonl").unlink()
    w3 = at.TraceWriter(tmp_path)
    w3.save_checkpoint("i1", calls)
    again = al.run_item(ITEM, {}, StandIn(), al.FakeProvider([]), usd_cap=5, trace=w3)
    assert "invented" not in str(again["finding"]) and again["finding"]["page"] == 2


def test_resume_after_ask_engineer_makes_no_model_call(tmp_path):
    w = at.TraceWriter(tmp_path)
    w.save_checkpoint(
        "i1",
        [
            {
                "tool": "ask_engineer",
                "args": {},
                "rerun": False,
                "reason": "unsure",
                "usd": 0.1,
                "saved": {
                    "ok": True,
                    "accepted": False,
                    "verdict": "",
                    "reason": "unsure",
                },
            }
        ],
    )
    box, p = StandIn(), al.FakeProvider([{"final": FULL}])
    out = al.run_item(ITEM, {}, box, p, usd_cap=5, trace=w)
    assert p.calls == [] and box.ran == [] and out["finding"]["color"] == "YELLOW"


def test_resume_after_refused_finding_continues_with_the_model(tmp_path):
    w = at.TraceWriter(tmp_path)
    w.save_checkpoint(
        "i1",
        [
            {
                "tool": "record_finding",
                "args": {},
                "rerun": False,
                "reason": "final",
                "usd": 0.1,
                "saved": {
                    "ok": False,
                    "accepted": False,
                    "verdict": "refused",
                    "reason": "bad quote",
                },
            }
        ],
    )
    p = al.FakeProvider([{"final": FULL}])
    out = al.run_item(ITEM, {}, StandIn(), p, usd_cap=5, trace=w)
    assert len(p.calls) == 1 and out["why"] == "recorded"
    assert any("bad quote" in str(m.get("content")) for m in p.calls[0])


def test_checkpoint_keeps_no_quote_text(tmp_path):
    w = at.TraceWriter(tmp_path)
    box = StandIn("refused")
    al.run_item(
        ITEM,
        {},
        box,
        al.FakeProvider(
            [
                {"tool": "search", "args": {"query": "invented query text"}},
                {"final": FULL},
            ]
        ),
        max_steps=2,
        usd_cap=5,
        trace=w,
    )
    # the item finished (step limit) so the checkpoint is gone; rebuild one mid-item
    w2 = at.TraceWriter(tmp_path)
    run = al._ItemRun(ITEM, {}, StandIn("refused"), al.FakeProvider([]), 5, 5, w2)
    res = run.toolbox.run("record_finding", {})
    run.save("record_finding", {"finding": FULL}, res, "final", 0.1)
    run.save("search", {"query": "invented query text"}, res, "look", 0.0)
    raw = (tmp_path / "i1.ckpt.json").read_text()
    assert "invented" not in raw and "quote_hash" in raw
    assert json.loads(raw)["calls"][1]["rerun"] is False


def test_checkpoint_deleted_when_item_completes(tmp_path):
    w = at.TraceWriter(tmp_path)
    al.run_item(
        ITEM,
        {},
        StandIn(),
        al.FakeProvider([{"tool": "search", "args": {"page": 1}}, {"final": FULL}]),
        usd_cap=5,
        trace=w,
    )
    assert not (tmp_path / "i1.ckpt.json").exists()


def test_verdict_that_differs_from_color_is_yellow():
    out = al.check_final({**GOOD, "verdict": "RED"})
    assert out["color"] == "YELLOW" and out["reason"] == "color and verdict differ"
    assert "verdict" not in out
    assert al.check_final({**GOOD, "verdict": "green"})["color"] == "GREEN"


def test_quote_mark_in_raw_reason_is_withheld_in_log_and_checkpoint(tmp_path):
    w = at.TraceWriter(tmp_path)
    for mark in ('"', "'", "\u201c", "\u2019", "\u00ab"):
        assert w.clean_reason("i", f"has {mark}a quote") == "reason withheld"
    box = StandIn()
    p = al.FakeProvider(
        [{"tool": "search", "args": {"page": 1}, "reason": 'it says "alpha"'}] * 2
    )
    al.run_item(ITEM, {}, box, p, max_steps=1, usd_cap=5, trace=w)
    assert "alpha" not in (tmp_path / "live.log").read_text()
    assert "alpha" not in (tmp_path / "i1.trace.jsonl").read_text()


def test_checkpoint_reason_copied_from_a_page_is_withheld(tmp_path):
    w = at.TraceWriter(tmp_path)
    copied = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi"
    run = al._ItemRun(ITEM, {}, StandIn(), al.FakeProvider([]), 5, 5, w)
    res = run.toolbox.run("open_page", {})
    w.step(doc="d", item_id="i1", step=1, tool="open_page", args={}, result=res)
    run.save("open_page", {"page": 2}, res, copied, 0.0)
    raw = (tmp_path / "i1.ckpt.json").read_text()
    assert "alpha" not in raw and "reason withheld" in raw


def test_sink_persists_and_survives_a_kill(tmp_path):
    w = at.TraceWriter(tmp_path)
    p = al.FakeProvider([{"final": FULL}])
    al.run_item(ITEM, {}, StandIn(), p, usd_cap=5, trace=w)
    sink = at.FindingSink(tmp_path)  # a fresh process reloads from disk
    assert sink.has("i1") and sink.get("i1")["doc_quote"] == "invented words"
    assert [f["item"] for f in sink.all()] == ["i1"] and sink.get("zz") is None
    for name in ("live.log", "LIVE.md", "i1.trace.jsonl"):
        f = tmp_path / name
        assert not f.exists() or "invented" not in f.read_text()


def test_sink_skips_a_torn_last_line(tmp_path):
    s = at.FindingSink(tmp_path)
    s.add("a", {"color": "RED"})
    with (tmp_path / "findings.jsonl").open("a") as fh:
        fh.write('{"item": "b", "fin')
    assert at.FindingSink(tmp_path).has("a") and not at.FindingSink(tmp_path).has("b")


def test_run_items_gives_the_toolbox_the_sink(tmp_path):
    class Ctx:
        findings = None

    box = StandIn()
    box.ctx = Ctx()
    w = at.TraceWriter(tmp_path, total=1)
    al.run_items(
        [ITEM],
        box,
        al.FakeProvider([{"final": FULL}]),
        w,
        usd_cap_item=1,
        usd_cap_run=5,
    )
    assert box.ctx.findings is w.sink and w.sink.has("i1")
