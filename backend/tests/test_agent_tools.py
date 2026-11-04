"""Tests for app.agent_tools (#1690). All text is invented; no db, no model, no network."""

from __future__ import annotations

import sys
import types

from app.agent_tools import TOOL_SPECS, ToolBox, ToolContext

DOC = "doc-sub"
OTHER = "doc-secret"
STD = "doc-std"
PAGES = {
    (
        DOC,
        1,
    ): "Widget model W-1 is rated for a working figure of 12 units at the stated site.\nMaterial: invented alloy.",
    (DOC, 2): "   ",
    (OTHER, 1): "Hidden words about the invented gadget live here.",
}
STD_PAGES = [
    (
        1,
        "1 General\nIntro words.\n4.2 Working figure\nThe working figure shall be at least 10 units.\nException: none for sealed widgets.\n4.3 Marking\nMark it.",
    ),
]


def page_reader(doc, page):
    return PAGES.get((doc, page))


def fake_search(query, allowed):
    hits = [
        {"document_id": DOC, "page_start": 1, "text": "invented passage a"},
        {"document_id": OTHER, "page_start": 1, "text": "leak"},
    ]
    return {
        "hits": [
            h for h in hits if h["document_id"] in allowed or h["document_id"] == OTHER
        ]
    }


def box(allowed=(DOC, STD), editions=None, **kw):
    ctx = ToolContext(
        frozenset(allowed),
        DOC,
        editions if editions is not None else {"ISO 9999": "2020"},
    )
    defaults = {
        "page_reader": page_reader,
        "searcher": fake_search,
        "standard_pages": lambda d: STD_PAGES,
        "standard_resolver": lambda s, e: STD if e == "2020" else None,
    }
    defaults.update(kw)
    return ToolBox(ctx, **defaults)


def good(**over):
    f = {
        "item": "I-1",
        "verdict": "GREEN",
        "doc": DOC,
        "page": 1,
        "doc_quote": "rated for a working figure of 12 units",
        "standard": "ISO 9999",
        "clause": "4.2",
        "clause_quote": "shall be at least 10 units",
        "value": "12 units",
        "comment": "Figure is stated.",
        "confidence": "medium",
        "priority": "should",
    }
    f.update(over)
    return f


def test_specs_match_tools():
    assert [s["name"] for s in TOOL_SPECS] == list(box()._tools)
    assert all({"name", "description", "params"} <= set(s) for s in TOOL_SPECS)


def test_unknown_tool_and_bad_args():
    assert box().run("nope", {})["ok"] is False
    assert box().run("open_page", "x")["ok"] is False


def test_open_page_reads_and_cites():
    r = box().run("open_page", {"doc": DOC, "page": 1})
    assert (
        r["ok"]
        and "working figure" in r["result"]["text"]
        and r["cites"] == [{"doc": DOC, "page": 1}]
    )


def test_open_page_out_of_scope_refused():
    r = box().run("open_page", {"doc": OTHER, "page": 1})
    assert not r["ok"] and "Hidden" not in str(r) and r["cites"] == []


def test_open_page_unread_and_empty():
    unread = box().run("open_page", {"doc": DOC, "page": 9})
    empty = box().run("open_page", {"doc": DOC, "page": 2})
    assert unread["result"]["state"] == "page_not_read" and not unread["ok"]
    assert (
        empty["result"]["state"] == "page_has_no_readable_text"
        and empty["result"]["text"] is None
    )


def test_search_intersects_scope_and_drops_outside():
    r = box().run("search", {"query": "figure", "scope": [DOC, OTHER]})
    assert [p["doc"] for p in r["result"]["passages"]] == [DOC]
    assert r["cites"] == [{"doc": DOC, "page": 1}]


def test_search_scope_fully_outside_returns_nothing_without_calling():
    def boom(*a):
        raise AssertionError("must not search")

    r = box(searcher=boom).run("search", {"query": "x", "scope": [OTHER]})
    assert r["result"]["passages"] == []


def test_get_clause_full_text_with_exception():
    r = box().run("get_clause", {"standard": "ISO 9999", "clause": "4.2"})
    assert (
        r["ok"]
        and "at least 10 units" in r["result"]["text"]
        and "Exception" in r["result"]["text"]
    )
    assert "Mark it" not in r["result"]["text"]
    assert r["cites"] == [{"doc": "ISO 9999", "clause": "4.2"}]


def test_get_clause_not_held_cases():
    assert (
        box(editions={})
        .run("get_clause", {"standard": "ISO 9999", "clause": "4.2"})["result"]["state"]
        .startswith("not held")
    )
    assert (
        box(editions={"ISO 9999": "1999"}).run(
            "get_clause", {"standard": "ISO 9999", "clause": "4.2"}
        )["result"]["state"]
        == "not held"
    )
    # the standard's document is not in scope: refused, rule 5
    assert (
        box(allowed=(DOC,)).run(
            "get_clause", {"standard": "ISO 9999", "clause": "4.2"}
        )["ok"]
        is False
    )
    assert (
        box().run("get_clause", {"standard": "ISO 9999", "clause": "7.7"})["ok"]
        is False
    )


def test_compare_unavailable_cannot_decide(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.figure_compare", None)  # import fails
    r = box().run(
        "compare_number", {"clause_figure": "10 units", "doc_figure": "12 units"}
    )
    assert r["result"]["decided"] is False and r["result"]["verdict"] is None


def test_compare_with_module_and_garbage(monkeypatch):
    mod = types.ModuleType("app.figure_compare")
    mod.compare = lambda a, b: {"decided": True, "verdict": "meets", "reason": "ok"}
    monkeypatch.setitem(sys.modules, "app.figure_compare", mod)
    import app

    monkeypatch.setattr(app, "figure_compare", mod, raising=False)
    assert (
        box().run("compare_number", {"clause_figure": "a", "doc_figure": "b"})[
            "result"
        ]["verdict"]
        == "meets"
    )
    mod.compare = lambda a, b: "yes"
    assert (
        box().run("compare_number", {"clause_figure": "a", "doc_figure": "b"})[
            "result"
        ]["decided"]
        is False
    )


def test_record_green_accepted_and_stored():
    b = box()
    r = b.run("record_finding", {"finding": good()})
    assert (
        r["ok"]
        and r["result"]["verdict"] == "accepted"
        and r["result"]["accepted"] is True
    )
    assert len(b.ctx.findings) == 1 and {"doc": DOC, "page": 1} in r["cites"]


def test_green_without_document_quote_refused():
    b = box()
    r = b.run("record_finding", {"finding": good(doc_quote="")})
    assert (
        not r["ok"]
        and r["result"]["verdict"] == "refused"
        and r["result"]["accepted"] is False
    )
    assert b.ctx.findings == []


def test_refused_findings_not_stored():
    b = box()
    for bad in (
        good(doc_quote="a quote that is nowhere on the page"),
        good(clause_quote="text that is not in the clause at all"),
        good(confidence="high"),
        good(doc=OTHER),
        good(comment="not mentioned in the document"),
        good(clause="9.9"),
        good(page=2),
        good(verdict="BLUE"),
    ):
        assert b.run("record_finding", {"finding": bad})["result"]["accepted"] is False
    assert b.ctx.findings == []


def test_numbers_decided_only_by_code(monkeypatch):
    b = box()
    f = good(clause_figure="10 units", doc_figure="12 units")
    assert (
        b.run("record_finding", {"finding": f})["result"]["reason"]
        == "number_not_decided_by_code"
    )
    mod = types.ModuleType("app.figure_compare")
    mod.compare = lambda a, c: {"decided": True, "verdict": "does_not_meet"}
    monkeypatch.setitem(sys.modules, "app.figure_compare", mod)
    import app

    monkeypatch.setattr(app, "figure_compare", mod, raising=False)
    b.run("compare_number", {"clause_figure": "10 units", "doc_figure": "12 units"})
    assert (
        b.run("record_finding", {"finding": f})["result"]["reason"]
        == "verdict_disagrees_with_code_comparison"
    )
    assert b.ctx.findings == []


def test_ask_engineer_stores_yellow_row():
    b = box()
    r = b.run("ask_engineer", {"item": "I-2", "reason": "figure unclear on page"})
    assert r["ok"] and b.ctx.queries == [
        {
            "item": "I-2",
            "verdict": "YELLOW",
            "reason": "figure unclear on page",
            "kind": "engineer_query",
        }
    ]
    assert not b.run("ask_engineer", {"item": "I-3", "reason": " ".join(["w"] * 31)})[
        "ok"
    ]
    assert not b.run("ask_engineer", {"item": "", "reason": "x"})["ok"]
    assert len(b.ctx.queries) == 1


def test_tool_exception_is_refusal_not_crash():
    def boom(d, p):
        raise RuntimeError("secret text")

    r = box(page_reader=boom).run("open_page", {"doc": DOC, "page": 1})
    assert not r["ok"] and "secret" not in str(r)
