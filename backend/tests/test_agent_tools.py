"""Tests for app.agent_tools (#1690). All text is invented; no db, no model, no network."""

from __future__ import annotations

import json
import sys
import types

import pytest

from app import agent_tools
from app.agent_tools import TOOL_SPECS, ToolBox, ToolContext

DOC = "doc-sub"
OTHER = "doc-secret"
STD = "doc-std"
PAGES = {
    (
        DOC,
        1,
    ): "Widget model W-1 is rated for a working figure of 12 units at the stated site.\nMaterial: invented alloy.\nWorking figure: 12 units",
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


DQ = "Working figure: 12 units"
CQ = "The working figure shall be at least 10 units"


def good(**over):
    f = {
        "item": "I-1",
        "color": "GREEN",
        "doc": DOC,
        "page": 1,
        "doc_quote": "rated for a working figure of 12 units",
        "standard": "ISO 9999",
        "clause": "4.2",
        "clause_quote": "shall be at least 10 units",
        "value": "12 units",
        "reason": "Figure is stated.",
        "action": "none",
        "priority": "should",
    }
    f.update(over)
    return f


class FigureResult:
    """Shaped like figure_compare.FigureResult (#1689)."""

    def __init__(self, verdict, reason="r", direction=None):
        self.verdict, self.reason, self.direction = verdict, reason, direction


def plug_compare(monkeypatch, fn):
    mod = types.ModuleType("app.figure_compare")
    mod.compare = fn
    monkeypatch.setitem(sys.modules, "app.figure_compare", mod)
    import app

    monkeypatch.setattr(app, "figure_compare", mod, raising=False)


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


def test_search_scope_outside_is_never_searched_and_is_noted():
    seen = []

    def spy(query, allowed):
        seen.append(allowed)
        return fake_search(query, allowed)

    r = box(searcher=spy).run("search", {"query": "x", "scope": [OTHER]})
    assert OTHER not in seen[0] and r["result"]["note"].startswith(
        "scope_not_recognised"
    )
    assert [p["doc"] for p in r["result"]["passages"]] == [DOC]


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
        == "not held: edition not confirmed"
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
    r = box().run("compare_number", {"doc_quote": DQ, "clause_quote": CQ})
    assert r["result"]["decided"] is False and r["result"]["verdict"] == "cannot decide"


def test_compare_mapping_and_argument_order(monkeypatch):
    seen = []
    answers = {"12 units": True, "20 units": False}

    def fake(doc_quote, clause_quote):
        seen.append((doc_quote, clause_quote))
        return FigureResult(answers.get(doc_quote.split(": ")[1]))

    plug_compare(monkeypatch, fake)
    b = box()
    out = {
        n: b.run(
            "compare_number", {"doc_quote": f"Working figure: {n}", "clause_quote": CQ}
        )["result"]
        for n in ("12 units", "20 units", "30 units")
    }
    assert (
        out["12 units"]["verdict"] == "meets"
        and out["20 units"]["verdict"] == "does_not_meet"
    )
    assert (
        out["30 units"]["verdict"] == "cannot decide"
        and out["30 units"]["decided"] is False
    )
    assert seen[0] == (DQ, CQ)  # document quote first, clause quote second


def test_compare_other_shapes_cannot_decide(monkeypatch):
    for shape in ("yes", {"decided": True, "verdict": "meets"}, None, 1):
        plug_compare(monkeypatch, lambda a, c, shape=shape: shape)
        r = box().run("compare_number", {"doc_quote": DQ, "clause_quote": CQ})
        assert r["result"]["decided"] is False


def _decide(monkeypatch, doc_quote, clause_quote):
    """Run compare_number with a figure_compare that would say MEETS to anything: only the subject check can stop it."""
    calls = []

    def always_meets(d, c):
        calls.append((d, c))
        return FigureResult(True)

    plug_compare(monkeypatch, always_meets)
    r = box().run(
        "compare_number", {"doc_quote": doc_quote, "clause_quote": clause_quote}
    )
    return r["result"], calls


@pytest.mark.parametrize(
    ("doc_quote", "clause_quote"),
    [
        (
            "Corrosion allowance: 3 mm",
            "Wall thickness shall be at least 2 mm",
        ),  # the owner's example
        ("Test pressure: 10 bar", "Design pressure shall not exceed 15 bar"),
        ("Operating pressure: 10 bar", "Design pressure shall not exceed 15 bar"),
        (
            "12 bar",
            "Design pressure shall not exceed 15 bar",
        ),  # a bare value has no subject
        (
            "Design pressure: 12 bar",
            "Pressure shall not exceed 15 bar",
        ),  # extra qualifier, doc side
        (
            "Pressure: 12 bar",
            "Design pressure shall not exceed 15 bar",
        ),  # extra qualifier, clause side
        ("Design pressure: 12 bar", "15 bar maximum"),  # empty clause subject
    ],
)
def test_subject_mismatch_cannot_decide_even_if_compare_says_meets(
    monkeypatch, doc_quote, clause_quote
):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert result["decided"] is False and result["verdict"] == "cannot decide"
    assert result["reason"] == "subject_mismatch" and "doc_subject" in result["detail"]
    assert calls == []  # figure_compare is never reached


def test_subject_mismatch_without_figure_compare_still_cannot_decide(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.figure_compare", None)
    r = box().run(
        "compare_number",
        {
            "doc_quote": "Corrosion allowance: 3 mm",
            "clause_quote": "Wall thickness shall be at least 2 mm",
        },
    )
    assert r["result"]["reason"] == "subject_mismatch"


@pytest.mark.parametrize(
    ("doc_quote", "clause_quote"),
    [
        ("Design pressure: 10 bar", "Design pressure shall be at least 8 bar"),
        (
            "Design pressures: 12 bar",
            "The pressure, design, shall not exceed 15 bar",
        ),  # plural, order, case
        ("DESIGN PRESSURE = 12 bar", "design pressure must not exceed 15 bar"),
    ],
)
def test_same_subject_goes_to_figure_compare(monkeypatch, doc_quote, clause_quote):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert result["verdict"] == "meets" and calls == [(doc_quote, clause_quote)]


@pytest.mark.parametrize(
    ("doc_quote", "clause_quote"),
    [
        (
            "12 bar",
            "15 bar maximum",
        ),  # both subjects empty: equal sets, but no subject at all
        ("Design pressure: 12 bar", "15 bar maximum"),
        ("12 bar", "Design pressure shall not exceed 15 bar"),
        ("Maximum 12 bar", "At least 8 bar"),
    ],
)
def test_empty_subject_never_matches(monkeypatch, doc_quote, clause_quote):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert result["reason"] == "subject_mismatch" and calls == []


@pytest.mark.parametrize(
    ("doc_quote", "clause_quote"),
    [
        (
            "Class 150 design pressure: 10 bar",
            "Class 300 design pressure shall be at least 8 bar",
        ),
        (
            "Class 150 wall thickness: 10 mm",
            "Class 300 wall thickness shall be at least 8 mm",
        ),
        ("Type 2 design pressure: 10 bar", "Design pressure shall be at least 8 bar"),
        ("No. 3 design pressure: 10 bar", "Design pressure shall be at least 8 bar"),
        ("Design pressure: 10 bar", "Design pressure shall be between 8 and 12 bar"),
        (
            "Design pressure: ten bar and 12 bar",
            "Design pressure shall be at least 8 bar",
        ),
        (
            "Design pressure: 1\u00bd bar",
            "Design pressure shall be at least 1 bar and 2 bar",
        ),
        ("Class 150: 10 bar", "Design pressure shall be at least 8 bar"),
    ],
)
def test_ambiguous_numbers_cannot_decide(monkeypatch, doc_quote, clause_quote):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert (
        result["decided"] is False
        and result["reason"] == "subject_ambiguous"
        and calls == []
    )


def test_label_number_alone_is_ambiguous(monkeypatch):
    result, calls = _decide(
        monkeypatch,
        "Design pressure Class 150 : bar",
        "Design pressure shall be at least 8 bar",
    )
    assert result["reason"] == "subject_ambiguous" and calls == []


@pytest.mark.parametrize(
    ("doc_quote", "clause_quote"),
    [
        ("Bearing temperature: 70 C", "Bear temperature shall not exceed 90 C"),
        ("Cooling water flow: 5 kg/h", "Cool water flow shall be at least 3 kg/h"),
        ("Heating duty: 5 kW", "Heat duty shall be at least 3 kW"),
        ("Rated load: 5 kN", "Rate load shall be at least 3 kN"),
    ],
)
def test_ing_and_ed_are_not_stripped(monkeypatch, doc_quote, clause_quote):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert result["reason"] == "subject_mismatch" and calls == []


def test_plurals_still_match():
    assert agent_tools.subject_words(
        "Design pressures: 12 bar"
    ) == agent_tools.subject_words("Design pressure 8 bar")
    assert agent_tools.subject_words("Supplies: 1 x") == agent_tools.subject_words(
        "Supply 2 x"
    )


@pytest.mark.parametrize(
    ("doc_quote", "clause_quote"),
    [
        (
            "Grade A wall thickness: 5 mm",
            "Grade C wall thickness shall be at least 2 mm",
        ),
        ("Type A pressure: 5 bar", "Type F pressure shall not exceed 9 bar"),
        ("Zone H temperature: 50 C", "Zone V temperature shall not exceed 90 C"),
        ("Unit K temperature: 50 C", "Unit W temperature shall not exceed 90 C"),
        ("Pump A head: 50 m", "Pump head shall be at least 40 m"),
        (
            "Grade B wall thickness: 5 mm",
            "Grade B wall thickness shall be at least 2 mm",
        ),  # same letter: still not decided
    ],
)
def test_lone_letter_label_is_ambiguous(monkeypatch, doc_quote, clause_quote):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert (
        result["decided"] is False
        and result["reason"] == "subject_ambiguous"
        and calls == []
    )


def test_unit_words_are_not_stripped_from_a_label():
    # "bar" in a label is a word of the subject; it is no longer silently dropped
    assert agent_tools.subject_words(
        "Design pressure bar: 5"
    ) != agent_tools.subject_words("Design pressure 5")


ORDINARY_PAIRS = [
    ("Design pressure: 10 bar", "Design pressure shall not exceed 15 bar"),
    ("Design pressures: 10 bar", "The design pressure shall not exceed 15 bar"),
    ("Wall thickness: 5 mm", "Wall thickness shall be at least 2 mm"),
    ("Corrosion allowance: 3 mm", "Corrosion allowance shall be at least 1.5 mm"),
    ("Design temperature: 80 C", "Design temperature shall not exceed 120 C"),
    ("Operating pressure: 8 bar", "The operating pressure must not exceed 10 bar"),
    ("Test pressure: 20 bar", "Test pressure shall be at least 18 bar"),
    ("Flow rate: 5 kg/h", "A flow rate of at least 3 kg/h is required"),
    ("Rated power: 5 kW", "Rated power shall be at least 3 kW"),
    (
        "Maximum allowable working pressure: 12 bar",
        "Maximum allowable working pressure shall be at least 10 bar",
    ),
    ("Shell thickness: 9 mm", "Shell thickness shall be at least 6 mm"),
    ("Hydrotest pressure: 20 bar", "Hydrotest pressure is at least 15 bar"),
]


@pytest.mark.parametrize(("doc_quote", "clause_quote"), ORDINARY_PAIRS)
def test_ordinary_pairs_still_decide(monkeypatch, doc_quote, clause_quote):
    result, calls = _decide(monkeypatch, doc_quote, clause_quote)
    assert result["verdict"] == "meets" and calls == [(doc_quote, clause_quote)]


def test_subject_mismatch_blocks_a_pass_finding(monkeypatch):
    b = box()
    fig = {
        "doc_quote": "Corrosion allowance: 3 mm",
        "clause_quote": "Wall thickness shall be at least 2 mm",
    }
    plug_compare(monkeypatch, lambda d, c: FigureResult(True))
    b.run("compare_number", fig)
    r = b.run(
        "record_finding",
        {"finding": good(figures=[fig], doc_quote=DQ, clause_quote=CQ)},
    )
    # refused whichever gate sees it first (figures not inside the quote, or never decided by code)
    assert r["result"]["accepted"] is False and b.ctx.findings.all() == []


def test_record_green_accepted_and_stored():
    b = box()
    r = b.run("record_finding", {"finding": good()})
    assert (
        r["ok"]
        and r["result"]["verdict"] == "accepted"
        and r["result"]["accepted"] is True
    )
    assert len(b.ctx.findings.all()) == 1 and {"doc": DOC, "page": 1} in r["cites"]


def test_green_without_document_quote_refused():
    b = box()
    r = b.run("record_finding", {"finding": good(doc_quote="")})
    assert (
        not r["ok"]
        and r["result"]["verdict"] == "refused"
        and r["result"]["accepted"] is False
    )
    assert b.ctx.findings.all() == []


def test_refused_findings_not_stored():
    b = box()
    for bad in (
        good(doc_quote="a quote that is nowhere on the page"),
        good(clause_quote="text that is not in the clause at all"),
        good(doc=OTHER),
        good(reason="not mentioned in the document"),
        good(clause="9.9"),
        good(page=2),
        good(color="BLUE"),
    ):
        assert b.run("record_finding", {"finding": bad})["result"]["accepted"] is False
    assert b.ctx.findings.all() == []


def test_numbers_decided_only_by_code(monkeypatch):
    b = box()
    fig = {"doc_quote": DQ, "clause_quote": CQ}
    f = good(figures=[fig], doc_quote=DQ, clause_quote=CQ)
    assert (
        b.run("record_finding", {"finding": f})["result"]["reason"]
        == "number_not_decided_by_code"
    )
    plug_compare(monkeypatch, lambda d, c: FigureResult(False))
    b.run("compare_number", fig)
    assert (
        b.run("record_finding", {"finding": f})["result"]["reason"]
        == "verdict_disagrees_with_code_comparison"
    )
    assert b.ctx.findings.all() == []
    plug_compare(monkeypatch, lambda d, c: FigureResult(True))
    b.run("compare_number", fig)
    assert b.run("record_finding", {"finding": f})["result"]["accepted"] is True


def test_confidence_high_refused_absent_allowed():
    b = box()
    r = b.run("record_finding", {"finding": good(confidence="high")})
    assert (
        r["result"]["reason"] == "confidence_never_high" and b.ctx.findings.all() == []
    )
    assert (
        b.run("record_finding", {"finding": good(confidence="HIGH")})["result"][
            "accepted"
        ]
        is False
    )
    assert (
        b.run("record_finding", {"finding": good()})["result"]["accepted"] is True
    )  # no confidence needed


def test_record_finding_scope_refused_before_anything_else():
    b = box()
    r = b.run(
        "record_finding",
        {"finding": good(doc=OTHER, page=1, doc_quote="Hidden words about")},
    )
    assert (
        r["result"]["reason"] == "document_not_in_scope" and b.ctx.findings.all() == []
    )
    r = b.run(
        "record_finding", {"finding": {"item": "I-1", "color": "YELLOW", "doc": OTHER}}
    )
    assert r["result"]["reason"] == "document_not_in_scope"


def test_color_verdict_alias_and_conflict_and_required():
    b = box()
    alias = good()
    alias["verdict"] = alias.pop("color")
    assert b.run("record_finding", {"finding": alias})["result"]["accepted"] is True
    # a FRESH item id, so the only possible refusal is the conflict itself
    clash = b.run("record_finding", {"finding": good(item="I-2", verdict="RED")})
    assert clash["result"]["reason"] == "color_not_green_yellow_red_or_conflicting"
    same = b.run("record_finding", {"finding": good(item="I-3", verdict="GREEN")})
    assert (
        same["result"]["accepted"] is True
    )  # the same word in both keys is not a conflict
    for n, missing in enumerate(("item", "color")):
        f = good(item=f"M-{n}")
        f.pop(missing)
        assert b.run("record_finding", {"finding": f})["result"]["accepted"] is False
    assert len(b.ctx.findings.all()) == 2


def test_stored_finding_uses_canonical_keys():
    b = box()
    b.run("record_finding", {"finding": good()})
    assert (
        b.ctx.findings.all()[0]["color"] == "GREEN"
        and "verdict" not in b.ctx.findings.all()[0]
    )


def test_tool_specs_on_class():
    assert ToolBox.TOOL_SPECS is TOOL_SPECS and box().TOOL_SPECS is TOOL_SPECS


def test_clause_text_never_read_from_unscoped_standard():
    b = box(allowed=(DOC,))
    assert b.run("get_clause", {"standard": "ISO 9999", "clause": "4.2"})["ok"] is False
    assert b.run("record_finding", {"finding": good()})["result"]["accepted"] is False


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
    long = b.run("ask_engineer", {"item": "I-3", "reason": " ".join(["w"] * 31)})
    assert (
        long["ok"] and len(b.ctx.queries[-1]["reason"].split()) == 30
    )  # cut, not refused
    assert not b.run("ask_engineer", {"item": "", "reason": "x"})["ok"]
    assert len(b.ctx.queries) == 2


def test_tool_exception_is_refusal_not_crash():
    def boom(d, p):
        raise RuntimeError("secret text")

    r = box(page_reader=boom).run("open_page", {"doc": DOC, "page": 1})
    assert not r["ok"] and "secret" not in str(r)


# ------------------------------------------------ integration: real ToolBox, tiny invented SQLite, the loop's FakeProvider


@pytest.fixture
def tiny_db(monkeypatch):
    import sqlite3

    from app import db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE documents (id TEXT, filename TEXT);"
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
    )
    conn.execute("INSERT INTO documents VALUES ('sub', 'invented sheet.pdf')")
    conn.execute("INSERT INTO documents VALUES ('std', 'ISO 9999 2020.pdf')")
    conn.execute("INSERT INTO documents VALUES ('secret', 'other.pdf')")
    conn.execute("INSERT INTO pages VALUES ('sub', 1, ?)", (PAGES[(DOC, 1)],))
    conn.execute(
        "INSERT INTO pages VALUES ('secret', 1, 'Hidden words about the invented gadget')"
    )
    for n, t in STD_PAGES:
        conn.execute("INSERT INTO pages VALUES ('std', ?, ?)", (n, t))
    monkeypatch.setattr(db, "connect", lambda: conn)
    return conn


def _db_evidence(allowed):
    from app import db
    from app.agent_edition import edition_evidence

    return lambda s, e: edition_evidence(db.connect(), frozenset(allowed), s, e)


def _loop_box(allowed):
    ctx = ToolContext(frozenset(allowed), "sub", {"ISO 9999": "2020"})
    from app import db
    from app.agent_edition import edition_evidence

    return ToolBox(
        ctx,
        searcher=fake_search,
        edition_evidence=lambda s, e: edition_evidence(
            db.connect(), frozenset(allowed), s, e
        ),
    )  # page and clause readers are the real defaults; the edition evidence is asked of the (fake) database


def test_integration_loop_records_through_real_toolbox(tiny_db, monkeypatch):
    from app import agent_loop

    plug_compare(monkeypatch, lambda d, c: FigureResult(True))
    fig = {"doc_quote": DQ, "clause_quote": CQ}
    final = good(doc="sub", figures=[fig], doc_quote=DQ, clause_quote=CQ)
    provider = agent_loop.FakeProvider(
        [
            {"tool": "open_page", "args": {"doc": "sub", "page": 1}, "reason": "read"},
            {
                "tool": "get_clause",
                "args": {"standard": "ISO 9999", "clause": "4.2"},
                "reason": "clause",
            },
            {"tool": "compare_number", "args": fig, "reason": "compare"},
            {"final": final},
        ]
    )
    box = _loop_box(("sub", "std"))
    out = agent_loop.run_item(
        {"id": "I-1", "doc": "sub"}, {}, box, provider, usd_cap=1.0
    )
    assert out["why"] == "recorded" and out["finding"]["color"] == "GREEN"
    assert [f["item"] for f in box.ctx.findings.all()] == ["I-1"]


def test_integration_out_of_scope_document_never_recorded(tiny_db):
    from app import agent_loop

    bad = good(doc="secret", doc_quote="Hidden words about")
    provider = agent_loop.FakeProvider(
        [
            {
                "tool": "open_page",
                "args": {"doc": "secret", "page": 1},
                "reason": "peek",
            },
            {"final": bad},
            {"final": bad},
        ]
    )
    box = _loop_box(("sub", "std"))
    out = agent_loop.run_item(
        {"id": "I-1", "doc": "sub"}, {}, box, provider, usd_cap=1.0, max_steps=4
    )
    assert box.ctx.findings.all() == []
    assert out["finding"]["color"] == "YELLOW"
    tool_replies = [
        m for call in provider.calls for m in call if m.get("role") == "tool"
    ]
    assert tool_replies and all("Hidden" not in str(m) for m in tool_replies)


def test_second_record_for_same_item_refused_first_stays():
    b = box()
    assert b.run("record_finding", {"finding": good()})["result"]["accepted"] is True
    again = b.run(
        "record_finding", {"finding": good(color="YELLOW", reason="changed my mind")}
    )
    assert again["ok"] is False and again["result"]["reason"] == "already recorded"
    assert (
        len(b.ctx.findings.all()) == 1 and b.ctx.findings.get("I-1")["color"] == "GREEN"
    )


def test_refused_first_record_does_not_block_a_later_good_one():
    b = box()
    assert (
        b.run(
            "record_finding", {"finding": good(doc_quote="nothing like the page text")}
        )["ok"]
        is False
    )
    assert b.run("record_finding", {"finding": good()})["ok"] is True


def test_findings_is_a_store_not_a_list():
    assert not isinstance(box().ctx.findings, list)
    for name in ("add", "get", "has", "all"):
        assert callable(getattr(box().ctx.findings, name))


def test_real_sink_survives_kill_and_refuses_second_record(tiny_db, tmp_path):
    from app import agent_trace

    def toolbox():
        sink = agent_trace.FindingSink(tmp_path / "run")
        return ToolBox(
            ToolContext(
                frozenset(("sub", "std")), "sub", {"ISO 9999": "2020"}, findings=sink
            ),
            searcher=fake_search,
            edition_evidence=_db_evidence(("sub", "std")),
        )

    first = toolbox()
    assert (
        first.run("record_finding", {"finding": good(doc="sub")})["result"]["accepted"]
        is True
    )
    del first  # the "kill": every object is gone, only the file on disk remains
    second = toolbox()
    assert (
        second.ctx.findings.has("I-1")
        and second.ctx.findings.get("I-1")["color"] == "GREEN"
    )
    again = second.run("record_finding", {"finding": good(doc="sub", color="YELLOW")})
    assert again["ok"] is False and again["result"]["reason"] == "already recorded"
    assert len(second.ctx.findings.all()) == 1


# ------------------------------------------------ the model-facing contract (first real run failed on these)


def _valid(value, schema, path="$"):
    """A small JSON-Schema check (type, enum, minimum, required, properties, items); jsonschema is not installed."""
    kind = schema.get("type")
    types = {"string": str, "object": dict, "array": list}
    if kind == "integer":
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{path} not an integer"
        )
    elif kind in types:
        assert isinstance(value, types[kind]), f"{path} not a {kind}"
    if "enum" in schema:
        assert value in schema["enum"], f"{path} not in enum"
    if "minimum" in schema:
        assert value >= schema["minimum"], f"{path} below minimum"
    if kind == "object":
        for name in schema.get("required", []):
            assert name in value, f"{path}.{name} required"
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                _valid(value[name], sub, f"{path}.{name}")
    if kind == "array":
        for n, entry in enumerate(value):
            _valid(entry, schema.get("items", {}), f"{path}[{n}]")


PLAUSIBLE = [
    ("open_page", {"doc": DOC, "page": 1, "reason": "read the page"}),
    ("open_page", {"page": 1, "reason": "own document by default"}),
    ("search", {"query": "working figure", "reason": "find it"}),
    ("search", {"query": "working figure", "scope": [DOC], "reason": "find it"}),
    ("get_clause", {"standard": "ISO 9999", "clause": "4.2", "reason": "read it"}),
    ("compare_number", {"doc_quote": DQ, "clause_quote": CQ, "reason": "compare"}),
    ("ask_engineer", {"why": "figure is unclear on the page", "reason": "ask"}),
    ("ask_engineer", {"item": "I-9", "why": "figure is unclear", "reason": "ask"}),
    (
        "record_finding",
        {
            "finding": {
                "color": "GREEN",
                "item": "I-1",
                "doc": DOC,
                "page": 1,
                "doc_quote": "rated for a working figure of 12 units",
                "clause_quote": "shall be at least 10 units",
                "standard": "ISO 9999",
                "clause": "4.2",
                "action": "none",
                "priority": "should",
                "reason": "Figure is stated.",
            },
            "reason": "record",
        },
    ),
    (
        "record_finding",
        {
            "finding": {
                "color": "YELLOW",
                "action": "confirm",
                "priority": "must",
                "reason": "unclear",
            },
            "reason": "record",
        },
    ),
]


def _through_adapter(name, args, box_):
    """The exact path of a real call: the adapter's own tool JSON, its reply parser, then the toolbox."""
    from app import agent_claude

    tools = {t["name"]: t for t in agent_claude.anthropic_tools(TOOL_SPECS)}
    _valid(args, tools[name]["input_schema"])
    reply = agent_claude.parse_reply(
        {"content": [{"type": "tool_use", "name": name, "input": args}]}, set(tools)
    )
    return box_.run(reply["tool"], reply["args"])


@pytest.mark.parametrize(("name", "args"), PLAUSIBLE)
def test_every_plausible_model_call_is_accepted(name, args):
    b = box()
    b.set_item("I-1")
    out = _through_adapter(name, args, b)
    assert out["ok"] is True, out["result"]


def test_every_tool_has_a_real_input_schema():
    for spec in TOOL_SPECS:
        schema = spec["input_schema"]
        assert schema["type"] == "object" and schema["properties"] and "params" in spec
    page = agent_tools.INPUT_SCHEMAS["open_page"]["properties"]["page"]
    assert page["type"] == "integer" and page["minimum"] == 1
    assert agent_tools.INPUT_SCHEMAS["search"]["properties"]["scope"]["type"] == "array"
    colour = agent_tools.INPUT_SCHEMAS["record_finding"]["properties"]["finding"][
        "properties"
    ]["color"]
    assert colour["enum"] == ["GREEN", "YELLOW", "RED"]


def test_ask_engineer_reason_is_not_the_adapters_reason_field():
    # the adapter pops "reason" from every call as the model's why-this-tool; ask_engineer must not use that name
    props = agent_tools.INPUT_SCHEMAS["ask_engineer"]["properties"]
    assert "reason" not in props and "why" in props


@pytest.mark.parametrize("page", [1, 1.0, "1", " 1 ", "1.0"])
def test_page_is_coerced(page):
    r = box().run("open_page", {"doc": DOC, "page": page})
    assert r["ok"] and r["result"]["page"] == 1


@pytest.mark.parametrize(
    ("page", "code"),
    [(0, "page_must_be_1_or_more"), (-3, "page_must_be_1_or_more"), ("abc", "page_missing_or_not_a_number"),
     (None, "page_missing_or_not_a_number"), (True, "page_missing_or_not_a_number"), (1.5, "page_missing_or_not_a_number")],
)  # fmt: skip
def test_bad_page_refused_with_code_and_hint(page, code):
    r = box().run("open_page", {"doc": DOC, "page": page})
    assert r["ok"] is False and r["result"]["refused"] == code
    assert r["result"]["expect"] == {"doc": "string?", "page": "integer"}


@pytest.mark.parametrize(
    "scope", [None, "", [], "   ", DOC, f"{DOC},zzz", f'["{DOC}"]', [DOC, "zzz"], 7]
)
def test_scope_is_tolerated_in_any_shape(scope):
    r = box().run("search", {"query": "figure", "scope": scope})
    assert r["ok"] is True and [p["doc"] for p in r["result"]["passages"]] == [DOC]


def test_doc_defaults_to_the_runs_document_and_unknown_args_are_dropped():
    r = box().run("open_page", {"page": "1", "document": DOC, "junk": 1})
    assert r["ok"] and r["result"]["doc"] == DOC
    r = box().run("open_page", {"page_number": 1})
    assert r["ok"]


def test_refusals_carry_expected_names_and_never_text():
    r = box().run("get_clause", {"standard": 5})
    assert r["ok"] is False and r["result"]["expect"] == {
        "standard": "string",
        "clause": "string",
    }
    r = box().run("open_page", {"doc": OTHER, "page": 1})
    assert r["result"]["refused"] == "document_not_in_scope" and "Hidden" not in str(r)
    r = box().run("nope", {})
    assert set(r["result"]["expect"]) == set(agent_tools.INPUT_SCHEMAS)


def test_ask_engineer_uses_the_loops_current_item():
    b = box()
    assert b.run("ask_engineer", {"why": "unclear"})["ok"] is False  # no item known yet
    b.set_item("I-7")
    r = b.run("ask_engineer", {"item": "I-999", "why": "unclear"})
    assert r["ok"] and b.ctx.queries[-1]["item"] == "I-7"
    assert b.run("ask_engineer", {"reason": "old name still works"})["ok"]


def test_the_loop_names_its_item_to_the_toolbox():
    from app import agent_loop

    b = box()
    provider = agent_loop.FakeProvider(
        [{"tool": "ask_engineer", "args": {"why": "figure unclear"}, "reason": "ask"}]
    )
    out = agent_loop.run_item({"id": "I-5", "doc": DOC}, {}, b, provider, usd_cap=1.0)
    assert out["why"] == "asked the engineer" and b.ctx.queries[0]["item"] == "I-5"


def test_record_finding_tolerates_shapes_the_model_could_not_know():
    b = box()
    b.set_item("I-1")
    flat = good(
        page="1",
        priority="Should",
        figures=[],
        clause_quote="shall be at least 10 units",
    )
    flat.pop("item")
    flat.pop("doc")
    assert (
        b.run("record_finding", {**flat})["ok"] is True
    )  # flat, no wrapper, no item, no doc
    b2 = box()
    assert (
        b2.run("record_finding", {"finding": json.dumps(good())})["ok"] is True
    )  # JSON text


def test_yellow_with_empty_strings_is_accepted():
    f = {
        "color": "YELLOW",
        "item": "I-4",
        "doc_quote": "",
        "clause_quote": "",
        "page": "",
        "priority": "",
        "action": "ask",
        "reason": "x",
    }
    assert box().run("record_finding", {"finding": f})["ok"] is True
