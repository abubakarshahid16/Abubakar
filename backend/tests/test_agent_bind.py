"""GREEN and RED findings are bound to their item (#1690, rule 4). Invented text only."""

from __future__ import annotations

import pytest

from app import agent_bind, agent_loop
from app.agent_quote_refs import make_toolbox
from app.agent_tools import ToolContext

DOC, STD = "doc-sub", "doc-std"
TITLE = "Invented datasheet revision 3"
PAGE = (
    f"{TITLE}\nGeneral notes: design data per standard\nHydrostatic pressure: 12 bar\nShell thickness: 9 mm\n"
    "Coating adhesion: 4 MPa\nShell pressure: 5 bar\nHydrostatic pressure margin: 20 bar\nTest head: 12 bar"
)
STD_TEXT = (
    "4.1 Hydrostatic pressure\nThe hydrostatic pressure shall be at least 10 bar.\n"
    "4.2 Shell thickness\nThe shell thickness shall be at least 6 mm.\n"
    "4.3 Marking\nMark each part clearly."
)
TOPIC = "Hydrostatic pressure"


def make(on=False, topic=TOPIC, page=PAGE, std=STD_TEXT):
    ctx = ToolContext(frozenset((DOC, STD)), DOC, {"ISO 9999": "2020"})
    box = make_toolbox(
        ctx,
        quote_by_reference=on,
        page_reader=lambda d, p: page if (d, p) == (DOC, 1) else None,
        searcher=lambda q, a: {"hits": []},
        standard_pages=lambda d: [(1, std)],
        standard_resolver=lambda s, e: STD,
    )
    box.set_item("I-1", topic=topic)
    box.run("open_page", {"doc": DOC, "page": 1})
    return box


def green(
    doc_quote="Hydrostatic pressure: 12 bar",
    clause="4.1",
    cq="The hydrostatic pressure shall be at least 10 bar",
    **over,
):
    f = {
        "item": "I-1", "color": "GREEN", "doc": DOC, "page": 1, "doc_quote": doc_quote, "standard": "ISO 9999", "clause": clause,
        "clause_quote": cq, "value": "12 bar", "action": "none", "priority": "should", "reason": "Value stated.",
    }  # fmt: skip
    f.update(over)
    return f


def run(box, f):
    return box.run("record_finding", {"finding": f})["result"]


def refused(box, f):
    r = run(box, f)
    return r["accepted"] is False and r["reason"] == agent_bind.CODE


def test_positive_control_is_accepted_typed():
    assert run(make(), green())["accepted"] is True


# the reviewer's classes: each was ACCEPTED before this change
@pytest.mark.parametrize(
    "over",
    [
        {
            "doc_quote": TITLE,
            "value": None,
            "cq": "Mark each part clearly",
            "clause": "4.3",
        },  # title line + unrelated block
        {"doc_quote": "Shell thickness: 9 mm"},  # figure on the page, not in the quote
        {
            "doc_quote": "Hydrostatic pressure margin: 20 bar"
        },  # a different quantity in the quote
        {
            "doc_quote": "General notes: design data per standard",
            "value": None,
        },  # generic-only overlap
        {
            "doc_quote": "Shell pressure: 5 bar",
            "value": "5 bar",
        },  # one shared word is not enough
        {
            "cq": "The shell thickness shall be at least 6 mm",
            "clause": "4.2",
        },  # unrelated clause block
    ],
)
def test_unbound_findings_are_refused_typed(over):
    box = make()
    f = green(**over)
    f = {k: v for k, v in f.items() if v is not None}
    assert refused(box, f) and box.ctx.findings.all() == []


def test_a_red_is_bound_too():
    assert refused(make(), green(color="RED", doc_quote=TITLE, value=None))
    assert run(make(), green(color="RED"))["accepted"] is True


@pytest.mark.parametrize(
    "lines",
    ["L1", "L2", "L4", "L5", "L6"],
)
def test_unbound_findings_are_refused_by_reference(lines):
    box = make(on=True)  # L3 is the line about the item
    f = green(doc_quote=None, value=None)
    f = {k: v for k, v in f.items() if v is not None and k != "doc_quote"}
    f["doc_quote_ref"] = {"page": 1, "lines": lines}
    f["clause_quote_ref"] = {"standard": "ISO 9999", "clause": "4.1", "blocks": "C1"}
    assert refused(box, f)


def test_the_bound_finding_by_reference_is_accepted():
    box = make(on=True)
    f = {
        k: v
        for k, v in green().items()
        if k not in ("doc_quote", "clause_quote", "standard", "clause")
    }
    f["doc_quote_ref"] = {"page": 1, "lines": "L3"}
    f["clause_quote_ref"] = {"standard": "ISO 9999", "clause": "4.1", "blocks": "C1"}
    assert run(box, f)["accepted"] is True


def test_the_clause_block_must_be_about_the_topic_by_reference():
    box = make(on=True)
    f = {
        k: v
        for k, v in green().items()
        if k not in ("doc_quote", "clause_quote", "standard", "clause")
    }
    f["doc_quote_ref"] = {"page": 1, "lines": "L3"}
    f["clause_quote_ref"] = {"standard": "ISO 9999", "clause": "4.3", "blocks": "C1"}
    assert refused(box, f)


def test_a_figures_pair_must_stand_inside_the_quotes(monkeypatch):
    box = make()
    fig = {
        "doc_quote": "Shell thickness: 9 mm",
        "clause_quote": "The shell thickness shall be at least 6 mm",
    }
    assert refused(box, green(figures=[fig]))
    assert refused(box, green(figures=["not a pair"]))


def test_yellow_is_never_bound_and_no_topic_binds_nothing():
    assert (
        run(
            make(),
            {
                "item": "I-1",
                "color": "YELLOW",
                "doc": DOC,
                "action": "ask",
                "priority": "must",
                "reason": "unclear",
                "doc_quote": TITLE,
                "page": 1,
            },
        )["accepted"]
        is True
    )
    box = make(topic=None)
    assert (
        run(box, green(doc_quote="Shell thickness: 9 mm", value="9 mm"))["accepted"]
        is True
    )  # no topic known: not topic-bound


def test_a_one_word_topic_needs_that_one_word():
    box = make(topic="Thickness")
    assert (
        run(
            box,
            green(
                doc_quote="Shell thickness: 9 mm",
                value="9 mm",
                cq="The shell thickness shall be at least 6 mm",
                clause="4.2",
            ),
        )["accepted"]
        is True
    )
    assert refused(make(topic="Thickness"), green())


def test_synonyms_are_refused_as_documented():
    # a true GREEN phrased with other words than the topic is refused: the safe side
    assert refused(
        make(topic="Hydrostatic pressure"),
        green(
            doc_quote="Test head: 12 bar",
            cq="The hydrostatic pressure shall be at least 10 bar",
        ),
    )


def test_refusal_hint_has_fixed_words_only():
    r = run(make(), green(doc_quote=TITLE, value=None))
    assert r["reason"] == agent_bind.CODE and r["expect"] == agent_bind.EXPECT
    assert "Invented" not in str(r) and "Hydrostatic" not in str(r)


def test_the_loop_passes_the_items_topic():
    class Box:
        def __init__(self):
            self.TOOL_SPECS = [
                {"name": "ask_engineer", "description": "d", "params": {}}
            ]
            self.seen = []

        def set_item(self, item_id, topic=None):
            self.seen.append((item_id, topic))

        def run(self, name, args):
            return {"ok": True, "result": {}, "cites": []}

    box = Box()
    provider = agent_loop.FakeProvider(
        [{"tool": "ask_engineer", "args": {}, "reason": "ask"}]
    )
    agent_loop.run_item(
        {"id": "I-3", "doc": DOC, "topic": "Hydrostatic pressure"},
        {},
        box,
        provider,
        usd_cap=1.0,
    )
    assert box.seen == [("I-3", "Hydrostatic pressure")]


def test_a_toolbox_without_a_topic_argument_still_works():
    class Old:
        def __init__(self):
            self.TOOL_SPECS = [
                {"name": "ask_engineer", "description": "d", "params": {}}
            ]
            self.seen = []

        def set_item(self, item_id):
            self.seen.append(item_id)

        def run(self, name, args):
            return {"ok": True, "result": {}, "cites": []}

    box = Old()
    provider = agent_loop.FakeProvider(
        [{"tool": "ask_engineer", "args": {}, "reason": "ask"}]
    )
    agent_loop.run_item(
        {"id": "I-4", "doc": DOC, "topic": "x"}, {}, box, provider, usd_cap=1.0
    )
    assert box.seen == ["I-4"]


def test_content_words_are_general():
    assert agent_bind.content_words("The Design pressures of the shells") == {
        "pressure",
        "shell",
    }
    assert agent_bind.content_words("General notes: design data") == frozenset()


# ------------------------------------------------ measured on a generator of invented text

NAMES = [("hydrostatic", "pressure", "bar"), ("shell", "thickness", "mm"), ("coating", "adhesion", "MPa"), ("bearing", "temperature", "C"),
         ("lubricant", "viscosity", "cSt"), ("impeller", "diameter", "mm"), ("flange", "rating", "bar"), ("gasket", "hardness", "HRC")]  # fmt: skip
TITLES = [
    TITLE,
    "General notes: design data per standard",
    "Project sheet revision 2",
    "Table of contents",
]


def world():
    lines = {
        i: f"{a.capitalize()} {b}: {10 + i} {u}" for i, (a, b, u) in enumerate(NAMES)
    }
    clauses = {
        i: f"The {a} {b} shall be at least {5 + i} {u}"
        for i, (a, b, u) in enumerate(NAMES)
    }
    page = "\n".join([*TITLES, *lines.values()])
    std = "\n".join(
        f"4.{i + 1} {a.capitalize()} {b}\n{clauses[i]}."
        for i, (a, b, _u) in enumerate(NAMES)
    )
    return lines, clauses, page, std


def test_generator_accepts_no_irrelevant_finding_and_reports_the_relevant():
    lines, clauses, page, std = world()
    irrelevant_accepted = relevant_accepted = irrelevant_tried = relevant_tried = 0
    for i, (a, b, _u) in enumerate(NAMES):
        topic = f"{a.capitalize()} {b}"
        candidates = [(t, None, False) for t in TITLES] + [
            (lines[j], lines[j].split(": ")[1], j == i) for j in range(len(NAMES))
        ]
        for text, value, relevant in candidates:
            for use_value in (True, False):
                for clause_i in (i, (i + 1) % len(NAMES)):
                    own_clause = clause_i == i
                    if not relevant and not own_clause and use_value:
                        pass
                    box = make(topic=topic, page=page, std=std)
                    f = green(
                        doc_quote=text,
                        clause=f"4.{clause_i + 1}",
                        cq=clauses[clause_i],
                        value=(lines[i].split(": ")[1] if use_value else None),
                    )
                    f = {k: v for k, v in f.items() if v is not None}
                    ok = run(box, f)["accepted"]
                    real = relevant and own_clause
                    if real:
                        relevant_tried += 1
                        relevant_accepted += ok
                    else:
                        irrelevant_tried += 1
                        irrelevant_accepted += ok
    print(
        f"accepted-irrelevant {irrelevant_accepted}/{irrelevant_tried}, accepted-relevant {relevant_accepted}/{relevant_tried}"
    )
    assert irrelevant_accepted == 0
    assert relevant_accepted == relevant_tried


def test_the_clause_side_of_a_figures_pair_must_stand_inside_the_clause_quote():
    fig = {
        "doc_quote": "Hydrostatic pressure: 12 bar",
        "clause_quote": "The shell thickness shall be at least 6 mm",
    }
    assert refused(make(), green(figures=[fig]))
