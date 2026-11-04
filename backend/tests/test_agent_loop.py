"""#1690 agent_loop with a fake provider and a fake toolbox. No model, no network."""
from app import agent_loop as al
from app import agent_trace as at

SPECS = [{"name": n, "description": "", "params": {}} for n in al.TOOL_NAMES]
GOOD = {"color": "GREEN", "doc_quote": "invented quote", "page": 2, "clause_quote": "invented clause"}


class Box:
    TOOL_SPECS = SPECS

    def __init__(self, accept=True):
        self.accept, self.ran = accept, []

    def run(self, name, args):
        self.ran.append(name)
        if name == "record_finding":
            v = "accepted" if self.accept else "refused"
            return {"ok": self.accept, "result": {"verdict": v, "reason": "bad quote"}, "cites": []}
        return {"ok": True, "result": {"text": "x"}, "cites": [{"doc": "d", "page": 1}]}


ITEM = {"id": "i1", "doc": "d"}


def run(script, box=None, **kw):
    box = box or Box()
    kw.setdefault("usd_cap", 1.0)
    return al.run_item(ITEM, {}, box, al.FakeProvider(script, usd=kw.pop("cost", 0.0)), **kw), box


def test_tool_then_final_recorded():
    out, box = run([{"tool": "open_page", "args": {"doc": "d", "page": 1}, "reason": "look"}, {"final": GOOD}])
    assert out["finding"]["color"] == "GREEN" and out["steps"] == 2 and box.ran == ["open_page", "record_finding"]


def test_step_limit_is_yellow_and_asks_engineer():
    out, box = run([{"tool": "search", "args": {}, "reason": "r"}] * 5, max_steps=3)
    assert out["finding"]["color"] == "YELLOW" and out["finding"]["reason"] == "step limit" and out["steps"] == 3
    assert box.ran[-1] == "ask_engineer"


def test_usd_cap_stops():
    out, _ = run([{"tool": "search", "args": {}}] * 5, cost=0.6, usd_cap=1.0)
    assert out["why"] == "usd cap" and out["steps"] == 2 and out["finding"]["color"] == "YELLOW"


def test_refused_finding_is_not_recorded_then_retry():
    box = Box(accept=False)
    out, _ = run([{"final": GOOD}, {"final": GOOD}], box=box, max_steps=2)
    assert out["why"] == "step limit" and out["finding"]["color"] == "YELLOW"
    assert box.ran.count("record_finding") == 2


def test_unknown_tool_does_not_crash():
    out, _ = run([{"tool": "delete_all", "args": {}}, {"final": GOOD}])
    assert out["finding"]["color"] == "GREEN" and out["steps"] == 2


def test_provider_error_is_yellow():
    class Boom:
        def complete(self, *a):
            raise ValueError("x")
    out = al.run_item(ITEM, {}, Box(), Boom(), usd_cap=1)
    assert out["finding"]["color"] == "YELLOW"


def test_check_final_invariants():
    assert al.check_final({**GOOD, "doc_quote": ""})["color"] == "YELLOW"
    assert al.check_final({**GOOD, "page": None})["downgraded_from"] == "GREEN"
    assert al.check_final({**GOOD, "comment": "Value is not mentioned"})["color"] == "YELLOW"
    assert "confidence" not in al.check_final({**GOOD, "confidence": "High"})
    assert al.check_final({**GOOD, "confidence": "low"})["confidence"] == "low"
    assert al.check_final({**GOOD, "color": "blue"})["color"] == "YELLOW"
    assert al.check_final("junk")["color"] == "YELLOW"
    assert al.check_final({**GOOD, "color": "red"})["color"] == "RED"
    assert al.check_final(GOOD)["color"] == "GREEN"


def test_green_without_quote_is_never_recorded_as_green():
    out, _ = run([{"final": {"color": "GREEN", "page": 1}}])
    assert out["finding"]["color"] == "YELLOW"


def test_resume_replays_without_provider_cost(tmp_path):
    w = at.TraceWriter(tmp_path)
    box = Box()
    p1 = al.FakeProvider([{"tool": "search", "args": {"query": "q"}, "reason": "r"}], usd=0.3)
    out = al.run_item(ITEM, {}, box, p1, max_steps=1, usd_cap=5, trace=w)
    assert out["why"] == "step limit"
    # simulate a kill after step 1: checkpoint exists again, item not done
    w.save_checkpoint("i1", [{"tool": "search", "args": {"query": "q"}, "result": None, "reason": "r", "usd": 0.3}])
    p2 = al.FakeProvider([{"final": GOOD}], usd=0.1)
    out = al.run_item(ITEM, {}, Box(), p2, usd_cap=5, trace=w)
    assert out["steps"] == 2 and abs(out["usd"] - 0.4) < 1e-9 and len(p2.calls) == 1
    assert any(m.get("name") == "search" for m in p2.calls[0])


def test_run_items_skips_completed(tmp_path):
    w = at.TraceWriter(tmp_path, total=2)
    items = [{"id": "a", "doc": "d"}, {"id": "b", "doc": "d"}]
    al.run_items(items[:1], Box(), al.FakeProvider([{"final": GOOD}]), w, usd_cap_item=1, usd_cap_run=5)
    w2 = at.TraceWriter(tmp_path, total=2)
    p = al.FakeProvider([{"final": GOOD}])
    res = al.run_items(items, Box(), p, w2, usd_cap_item=1, usd_cap_run=5)
    assert list(res["results"]) == ["b"] and len(p.calls) == 1 and (tmp_path / "LIVE.md").exists()


def test_run_cap_stops_run(tmp_path):
    w = at.TraceWriter(tmp_path)
    items = [{"id": "a", "doc": "d"}, {"id": "b", "doc": "d"}]
    res = al.run_items(items, Box(), al.FakeProvider([{"final": GOOD}], usd=2.0), w, usd_cap_item=5, usd_cap_run=2)
    assert list(res["results"]) == ["a"] and res["stopped"] and not w.is_done("b")


def test_document_map_keeps_headings_only():
    m = al.build_document_map({2: "1 SCOPE\nthis body sentence is long and ends here.\nMore body, text", 1: "TITLE"})
    assert m == [{"page": 1, "headings": ["TITLE"]}, {"page": 2, "headings": ["1 SCOPE"]}]


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
    assert out["a"]["color"] == "GREEN" and out["b"]["color"] == "YELLOW" and "c" not in out
