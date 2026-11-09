"""Quote by reference (#1690): ids in, exact text out, same verification. Invented text only; no db, model or network."""

from __future__ import annotations

import pytest

from app import agent_claude, agent_loop, agent_quote_refs, agent_tools, agent_trace
from app.agent_quote_refs import (
    RefToolBox,
    make_toolbox,
    numbered_blocks,
    numbered_lines,
    parse_ids,
)
from app.agent_tools import ToolBox, ToolContext

DOC, OTHER, STD = "doc-sub", "doc-secret", "doc-std"
LINE1 = "Widget model W-1 is rated for a working figure of 12 units at the stated site."
PAGE1 = f"{LINE1}\nMaterial: invented alloy.\n\nTest pressure: 20 bar\nDesign pressure: 12 bar\n"
PAGES = {(DOC, 1): PAGE1, (DOC, 2): "Second page line.", (OTHER, 1): "Hidden words."}
STD_PAGES = [
    (1, "1 General\nIntro words.\n4.2 Working figure\nThe working figure shall be at least 10 units.\nException: none for sealed widgets.\n4.3 Marking\nMark it."),
]  # fmt: skip
C1 = "4.2 Working figure The working figure shall be at least 10 units."


def make(on=True, allowed=(DOC, STD)):
    ctx = ToolContext(frozenset(allowed), DOC, {"ISO 9999": "2020"})
    return make_toolbox(
        ctx,
        quote_by_reference=on,
        page_reader=lambda d, p: PAGES.get((d, p)),
        searcher=lambda q, a: {"hits": []},
        standard_pages=lambda d: STD_PAGES,
        standard_resolver=lambda s, e: STD if e == "2020" else None,
    )


def opened(box=None):
    box = box or make()
    box.set_item("I-1")
    box.run("open_page", {"doc": DOC, "page": 1})
    box.run("get_clause", {"standard": "ISO 9999", "clause": "4.2"})
    return box


def finding(**over):
    f = {
        "item": "I-1", "color": "GREEN", "doc": DOC, "action": "none", "priority": "should", "reason": "Figure stated.",
        "value": "12 units", "doc_quote_ref": {"page": 1, "lines": "L1"},
        "clause_quote_ref": {"standard": "ISO 9999", "clause": "4.2", "blocks": "C1"},
    }  # fmt: skip
    f.update(over)
    return f


def record(box, **over):
    return box.run("record_finding", {"finding": finding(**over)})


# ------------------------------------------------------------------ numbering


def test_numbered_lines_exact_stable_one_based():
    assert numbered_lines(PAGE1) == [
        ("L1", LINE1),
        ("L2", "Material: invented alloy."),
        ("L3", "Test pressure: 20 bar"),
        ("L4", "Design pressure: 12 bar"),
    ]
    assert numbered_lines(PAGE1) == numbered_lines(PAGE1)  # stable
    assert numbered_lines("") == [] and numbered_lines("\n  \n") == []


def test_open_page_returns_numbered_lines_when_on():
    r = make().run("open_page", {"doc": DOC, "page": 1})
    assert r["ok"] and r["result"]["text"].splitlines()[:2] == [
        f"L1: {LINE1}",
        "L2: Material: invented alloy.",
    ]
    assert r["result"]["lines"] == 4 and r["cites"] == [{"doc": DOC, "page": 1}]


def test_clause_blocks_exact_and_numbered():
    assert numbered_blocks("4.2 Working figure\nThe working figure shall be at least 10 units.\nException: none for sealed widgets.") == [
        ("C1", C1), ("C2", "Exception: none for sealed widgets.")]  # fmt: skip
    r = make().run("get_clause", {"standard": "ISO 9999", "clause": "4.2"})
    assert (
        r["result"]["text"] == f"C1: {C1}\nC2: Exception: none for sealed widgets."
        and r["result"]["blocks"] == 2
    )
    assert (
        r["result"]["standard"] == "ISO 9999" and r["result"]["edition"] == "2020"
    )  # existing fields kept


def test_option_off_is_the_plain_toolbox_and_identical():
    off, plain = (
        make(on=False),
        ToolBox(
            ToolContext(frozenset((DOC, STD)), DOC, {"ISO 9999": "2020"}),
            page_reader=lambda d, p: PAGES.get((d, p)),
            searcher=lambda q, a: {"hits": []},
            standard_pages=lambda d: STD_PAGES,
            standard_resolver=lambda s, e: STD,
        ),
    )
    assert type(off) is ToolBox and not isinstance(off, RefToolBox)
    for name, args in (
        ("open_page", {"doc": DOC, "page": 1}),
        ("get_clause", {"standard": "ISO 9999", "clause": "4.2"}),
    ):
        assert off.run(name, args) == plain.run(name, args)
    assert "L1:" not in off.run("open_page", {"doc": DOC, "page": 1})["result"]["text"]
    assert (
        getattr(off, "prompt_note", "") == ""
        and agent_tools.TOOL_SPECS == off.TOOL_SPECS
    )


# ------------------------------------------------------------------ ref -> exact text -> same verification


def test_ref_builds_the_exact_stored_text_and_is_accepted():
    box = opened()
    out = record(box)
    assert out["ok"] and out["result"]["accepted"] is True
    stored = box.ctx.findings.get("I-1")
    assert (
        stored["doc_quote"] == LINE1
        and stored["clause_quote"] == C1
        and stored["page"] == 1
    )
    assert "doc_quote_ref" not in stored


def test_multi_line_ref_is_joined_with_one_space_and_verifies():
    box = opened()
    out = record(
        box, value="20 bar", doc_quote_ref={"page": 1, "lines": "L2-L3"}, color="YELLOW"
    )
    assert out["ok"], out["result"]
    assert (
        box.ctx.findings.get("I-1")["doc_quote"]
        == "Material: invented alloy. Test pressure: 20 bar"
    )
    assert (
        box.built_finding({"item": "I-1"})["doc_quote"]
        == "Material: invented alloy. Test pressure: 20 bar"
    )


def test_a_ref_to_lines_that_do_not_support_green_is_still_refused():
    box = opened()
    assert record(box, value="99 bar")["result"]["reason"] == "value_not_on_page"
    assert (
        record(box, reason="the figure is not mentioned")["result"]["reason"]
        == "not_mentioned_is_never_green"
    )
    fig = {
        "doc_quote": "Design pressure: 12 bar",
        "clause_quote": "Design pressure shall be at least 8 bar",
    }
    # compare_number still decides; here the figures are not inside the quotes either, so the binding refuses first
    assert record(box, figures=[fig])["result"]["accepted"] is False
    assert box.ctx.findings.all() == []


def test_one_finding_per_item_still_holds():
    box = opened()
    assert record(box)["ok"] and record(box)["result"]["reason"] == "already recorded"


@pytest.mark.parametrize(
    ("ref", "code"),
    [
        ({"page": 1, "lines": "L9"}, "line_not_found"),
        ({"page": 2, "lines": "L1"}, "page_not_opened"),
        ({"page": 1, "lines": "L1-L13"}, "range_too_long"),
        ({"page": 1, "lines": ["L1", "L3"]}, "ids_not_contiguous"),
        ({"page": 1, "lines": "zzz"}, "ids_unreadable"),
        ({"page": 0, "lines": "L1"}, "page_must_be_1_or_more"),
        ("L1", "doc_quote_ref_not_an_object"),
    ],
)
def test_bad_doc_refs_refused_with_code_and_shape_only(ref, code):
    box = opened()
    out = record(box, doc_quote_ref=ref)
    assert out["ok"] is False and out["result"]["reason"] == code
    assert out["result"]["ref_expect"]["doc_quote_ref"]["page"] == "integer"
    assert "Widget" not in str(out) and box.ctx.findings.all() == []


def test_bad_clause_refs_refused():
    box = opened()
    bad = {"standard": "ISO 9999", "clause": "4.2", "blocks": "C7"}
    assert record(box, clause_quote_ref=bad)["result"]["reason"] == "block_not_found"
    assert (
        record(box, clause_quote_ref={**bad, "clause": "9.9", "blocks": "C1"})[
            "result"
        ]["reason"]
        == "clause_not_found"
    )


def test_ref_wins_over_typed_text_never_mixed():
    box = opened()
    out = record(
        box,
        doc_quote="a paraphrase that is nowhere on the page",
        clause_quote="another paraphrase of the clause",
    )
    assert out["ok"], out["result"]
    stored = box.ctx.findings.get("I-1")
    assert stored["doc_quote"] == LINE1 and stored["clause_quote"] == C1


def test_a_typed_quote_without_a_ref_still_works_and_is_verified():
    box = opened()
    typed = {k: v for k, v in finding().items() if not k.endswith("_ref")}
    typed.update(
        page=1, standard="ISO 9999", clause="4.2",
        doc_quote="rated for a working figure of 12 units", clause_quote="shall be at least 10 units",
    )  # fmt: skip
    assert box.run("record_finding", {"finding": typed})["ok"]
    box2 = opened()
    assert not box2.run(
        "record_finding",
        {"finding": {**typed, "doc_quote": "typed text that is not there"}},
    )["ok"]


def test_scope_is_not_widened_by_a_ref():
    box = make(allowed=(DOC,))
    box.set_item("I-1")
    box.run("open_page", {"doc": DOC, "page": 1})
    assert (
        record(box, doc=OTHER, doc_quote_ref={"page": 1, "lines": "L1"})["ok"] is False
    )
    assert (
        record(box)["ok"] is False
    )  # the standard is not in scope, so the clause ref cannot be built


@pytest.mark.parametrize(
    ("raw", "ids"),
    [("L3", [3]), (3, [3]), ("3-5", [3, 4, 5]), ("L3-L5", [3, 4, 5]), ("L3,L4", [3, 4]), (["L3", "L4"], [3, 4]), ([3, 4], [3, 4]), ("l3 - l4", [3, 4]), ("C2-C3", [2, 3])],
)  # fmt: skip
def test_ids_are_read_tolerantly(raw, ids):
    assert parse_ids(raw) == (ids, None)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, "ids_unreadable"),
        (True, "ids_unreadable"),
        ("", "ids_unreadable"),
        ("L5-L2", "range_too_long"),
        ("L1-L99999", "range_too_long"),
        ("L1,L5", "ids_not_contiguous"),
    ],
)
def test_bad_ids(raw, code):
    assert parse_ids(raw) == (None, code)


def test_quote_cap_cuts_at_a_line_boundary_and_refuses_one_long_line():
    long_page = "\n".join(f"Line number {n} " + "x" * 90 for n in range(1, 11))
    pairs = numbered_lines(long_page)
    text, bad = agent_quote_refs.build_quote(pairs, list(range(1, 11)), "L")
    assert (
        bad is None
        and len(text) <= 600
        and text.startswith("Line number 1 ")
        and text.endswith("x" * 90)
    )
    assert agent_quote_refs.build_quote([("L1", "y" * 601)], [1], "L") == (
        None,
        "quote_line_too_long",
    )


# ------------------------------------------------------------------ schema contract and the loop


def _valid(value, schema, path="$"):
    if "anyOf" in schema:
        fits = []
        for option in schema["anyOf"]:
            try:
                _valid(value, option, path)
                fits.append(True)
            except AssertionError:
                fits.append(False)
        assert any(fits), f"{path} matches no anyOf option"
        return
    kind = schema.get("type")
    kinds = {"string": str, "object": dict, "array": list, "integer": int}
    if isinstance(kind, list):
        assert any(isinstance(value, kinds[k]) for k in kind), f"{path} wrong type"
    elif kind:
        assert isinstance(value, kinds[kind]) and not isinstance(value, bool), (
            f"{path} not a {kind}"
        )
    if "enum" in schema:
        assert value in schema["enum"]
    if "minimum" in schema:
        assert value >= schema["minimum"]
    if kind == "object":
        for name in schema.get("required", []):
            assert name in value, f"{path}.{name} required"
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                _valid(value[name], sub, f"{path}.{name}")
    if kind == "array":
        for n, entry in enumerate(value):
            _valid(entry, schema.get("items", {}), f"{path}[{n}]")


PLAUSIBLE_REFS = [
    {"page": 1, "lines": "L1"},
    {"page": 1, "lines": "L2-L3"},
    {"page": 1, "lines": ["L2", "L3"]},
    {"page": 1, "lines": [2, 3]},
]


@pytest.mark.parametrize("ref", PLAUSIBLE_REFS)
def test_local_model_calls_validate_against_the_adapters_schema_and_are_accepted(ref):
    box = opened()
    tools = {t["name"]: t for t in agent_claude.anthropic_tools(box.TOOL_SPECS)}
    args = {
        "finding": {"color": "YELLOW", "action": "confirm", "priority": "must", "reason": "check", "doc_quote_ref": ref,
                    "clause_quote_ref": {"standard": "ISO 9999", "clause": "4.2", "blocks": ["C1"]}},
        "reason": "record",
    }  # fmt: skip
    _valid(args, tools["record_finding"]["input_schema"])
    parsed = agent_claude.parse_reply(
        {"content": [{"type": "tool_use", "name": "record_finding", "input": args}]},
        set(tools),
    )
    assert box.run(parsed["tool"], parsed["args"])["ok"], box.ctx.findings.all()


def test_ref_fields_are_in_the_schema_only_when_on():
    on = {s["name"]: s for s in make().TOOL_SPECS}["record_finding"]["input_schema"]
    props = on["properties"]["finding"]["properties"]
    assert {"doc_quote_ref", "clause_quote_ref"} <= set(props) and "doc_quote" in props
    assert "doc_quote_ref" not in str(
        agent_tools.TOOL_SPECS
    )  # the shared specs are untouched
    assert (
        "doc_quote" not in on["properties"]["finding"]["required"]
    )  # typed quotes are optional


def _scripted(box, final):
    provider = agent_loop.FakeProvider(
        [
            {"tool": "open_page", "args": {"doc": DOC, "page": 1}, "reason": "read"},
            {
                "tool": "get_clause",
                "args": {"standard": "ISO 9999", "clause": "4.2"},
                "reason": "clause",
            },
            {"final": final},
        ]
    )
    return provider, agent_loop.run_item(
        {"id": "I-1", "doc": DOC}, {}, box, provider, usd_cap=1.0
    )


def test_loop_green_by_reference_is_not_downgraded_and_stores_the_exact_text():
    box = make()
    final = {k: v for k, v in finding().items() if k not in ("item", "doc")}
    provider, out = _scripted(box, final)
    assert out["why"] == "recorded" and out["finding"]["color"] == "GREEN"
    assert out["finding"]["doc_quote"] == LINE1 and out["finding"]["clause_quote"] == C1
    assert "doc_quote_ref" not in out["finding"]
    assert agent_quote_refs.PROMPT_NOTE in str(
        provider.calls[0][0]["content"]["instruction"]
    )


def test_loop_prompt_note_only_when_on():
    box = make(on=False)
    box.set_item("I-1")
    provider = agent_loop.FakeProvider(
        [{"final": {"color": "YELLOW", "action": "ask", "reason": "x"}}]
    )
    agent_loop.run_item({"id": "I-1", "doc": DOC}, {}, box, provider, usd_cap=1.0)
    assert "Quote by reference" not in str(provider.calls[0][0]["content"])


def test_the_trace_args_hold_ids_only_never_text():
    args = {"finding": finding(), "reason": "r"}
    safe = agent_trace.safe_args(args)
    assert "other_keys" in safe and LINE1 not in str(safe) and "L1" not in str(safe)
    out = record(opened(), doc_quote_ref={"page": 1, "lines": "L9"})
    assert LINE1 not in str(agent_trace.safe_result(out))
