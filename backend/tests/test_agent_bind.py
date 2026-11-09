"""GREEN and RED exist only for numbers decided by code (#1690, rule 4). Invented text only; typed AND by reference."""

from __future__ import annotations

import sys
import types

import pytest

from app import agent_bind, agent_loop
from app.agent_quote_refs import make_toolbox, numbered_lines
from app.agent_tools import ToolContext

DOC, STD = "doc-sub", "doc-std"
OWN = "Hydrostatic pressure: 12 bar"
SENTENCE = "The hydrostatic pressure shall be at least 10 bar"
FIG = {"doc_quote": OWN, "clause_quote": SENTENCE}
HEADING = "Maximum hydrostatic pressure of 15 bar for all vessels"
HEAD_FIG = {"doc_quote": OWN, "clause_quote": "hydrostatic pressure of 15 bar"}
# the reviewer's TEXTUAL classes: each holds the topic words and was accepted by the old overlap rule
TEXTUAL = [
    "The hydrostatic pressure test was witnessed and accepted by the inspector on site",  # an ordinary sentence
    "The hydrostatic pressure test procedure requirements are stated in this section.",  # a full-sentence heading
    "Hydrostatic pressure values in this sheet comply with the rules in section 3 of the plan",  # boilerplate with a digit
    "Note 2: the hydrostatic pressure was not changed by the revision described above here",  # a footnote sentence
    "Hydrostatic pressure test procedure requirements overview for all vessels",  # an 8-word title line
    "Invented datasheet revision 3",  # a title
    "General notes: design data per standard",  # generic words only
]
LINES = [
    OWN, "Shell thickness: 9 mm", "Pressure: 12 bar for hydrostatic vessel tests", "Pressure: 12 bar for hydrostatic tests",
    "Auxiliary device tag B", *TEXTUAL,
]  # fmt: skip
PAGE = "\n".join(dict.fromkeys(LINES))
STD_TEXT = (
    f"4.1 Hydrostatic pressure\n{SENTENCE}.\n4.2 Shell thickness\nThe shell thickness shall be at least 6 mm.\n"
    f"4.3 Marking\nMark each part clearly and permanently.\n4.5 {HEADING}\nVessels shall be marked.\n"
    "4.6 Pressure requirement\nPressure shall be at least 10 bar.\n4.7 Vessel pressure\nPressure shall be at least 10 bar for vessels."
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


def plug(monkeypatch, verdict=True):
    mod = types.ModuleType("app.figure_compare")
    mod.compare = lambda d, c: types.SimpleNamespace(
        verdict=verdict, reason="r", direction=None
    )
    monkeypatch.setitem(sys.modules, "app.figure_compare", mod)
    monkeypatch.setattr(__import__("app"), "figure_compare", mod, raising=False)


def line_id(text, page=PAGE):
    return next(k for k, v in numbered_lines(page) if v == text)


def build(
    mode,
    doc_line,
    *,
    clause="4.1",
    cq=SENTENCE,
    colour="GREEN",
    value=None,
    figures=None,
    page=PAGE,
):
    """A finding, typed or by reference (then code builds the quote text from the line id and block C1)."""
    f = {"item": "I-1", "color": colour, "doc": DOC, "page": 1, "standard": "ISO 9999", "clause": clause,
         "action": "none", "priority": "should", "reason": "Stated in the document."}  # fmt: skip
    if mode == "typed":
        f.update(doc_quote=doc_line, clause_quote=cq)
    else:
        f.update(
            doc_quote_ref={"page": 1, "lines": line_id(doc_line, page)},
            clause_quote_ref={"standard": "ISO 9999", "clause": clause, "blocks": "C1"},
        )
        f.pop("page"), f.pop("standard"), f.pop("clause")
    for key, val in (("value", value), ("figures", figures)):
        if val is not None:
            f[key] = val
    return f


def decide(box, pair):
    return box.run("compare_number", pair)["result"]


def submit(box, f):
    return box.run("record_finding", {"finding": f})["result"]


def refused(box, f):
    r = submit(box, f)
    return r["accepted"] is False and r["reason"] == agent_bind.CODE


def numeric(mode, monkeypatch, *, topic=TOPIC, pair=FIG, line=OWN, **over):
    """A box where `pair` was DECIDED by code, and the finding that uses it: only the rule under test can refuse it."""
    plug(monkeypatch)
    box = make(on=mode == "ref", topic=topic)
    assert decide(box, pair)["decided"] is True
    return box, build(
        mode, line, figures=[pair], value=over.pop("value", "12 bar"), **over
    )


MODES = ("typed", "ref")


# ------------------------------------------------------------------ the only way to GREEN or RED: a number decided by code


@pytest.mark.parametrize("mode", MODES)
def test_a_decided_figure_in_bound_quotes_is_accepted(mode, monkeypatch):
    box, f = numeric(mode, monkeypatch)
    assert submit(box, f)["accepted"] is True


@pytest.mark.parametrize("mode", MODES)
def test_a_red_with_a_decided_figure_is_accepted(mode, monkeypatch):
    plug(monkeypatch, verdict=False)
    box = make(on=mode == "ref")
    decide(box, FIG)
    assert (
        submit(box, build(mode, OWN, colour="RED", figures=[FIG]))["accepted"] is True
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("text", TEXTUAL)
def test_every_textual_finding_is_refused_green_and_red(mode, text):
    for colour in ("GREEN", "RED"):
        box = make(on=mode == "ref")
        assert refused(box, build(mode, text, colour=colour)), text
        assert box.ctx.findings.all() == []


@pytest.mark.parametrize("mode", MODES)
def test_a_pair_never_decided_by_code_is_refused(mode):
    box = make(on=mode == "ref")  # compare_number was never asked
    assert (
        box.run("record_finding", {"finding": build(mode, OWN, figures=[FIG])})[
            "result"
        ]["accepted"]
        is False
    )


@pytest.mark.parametrize("mode", MODES)
def test_yellow_is_never_bound(mode):
    for topic in (TOPIC, "", None):
        box = make(on=mode == "ref", topic=topic)
        assert submit(box, build(mode, TEXTUAL[5], colour="YELLOW"))["accepted"] is True


def test_the_hint_has_fixed_words_only_and_names_the_yellow_way():
    r = submit(make(), build("typed", TEXTUAL[0]))
    assert r["reason"] == agent_bind.CODE and r["expect"] == agent_bind.EXPECT
    assert "YELLOW" in str(agent_bind.EXPECT) and "hydrostatic" not in str(
        r
    ).lower().replace("expect", "")


# ------------------------------------------------------------------ the numeric rules, each isolated by a decided pair


@pytest.mark.parametrize("mode", MODES)
def test_a_decided_pair_does_not_excuse_a_quote_about_another_item(mode, monkeypatch):
    other = {
        "doc_quote": "Shell thickness: 9 mm",
        "clause_quote": "The shell thickness shall be at least 6 mm",
    }
    box, f = numeric(
        mode,
        monkeypatch,
        pair=other,
        line="Shell thickness: 9 mm",
        clause="4.2",
        cq="The shell thickness shall be at least 6 mm.",
        value="9 mm",
    )
    assert refused(
        box, f
    )  # decided, with units, and inside the quotes: only the topic rule refuses it


@pytest.mark.parametrize("mode", MODES)
def test_the_document_side_of_a_pair_must_stand_inside_the_document_quote(
    mode, monkeypatch
):
    pair = {
        "doc_quote": "Hydrostatic pressure: 15 bar",
        "clause_quote": SENTENCE,
    }  # decided, but not the quoted line
    box, f = numeric(mode, monkeypatch, pair=pair, value=None)
    assert refused(box, f)


@pytest.mark.parametrize("mode", MODES)
def test_the_clause_side_of_a_pair_must_stand_inside_the_clause_quote(
    mode, monkeypatch
):
    pair = {
        "doc_quote": OWN,
        "clause_quote": "The hydrostatic pressure shall be at least 11 bar",
    }
    box, f = numeric(mode, monkeypatch, pair=pair, value=None)
    assert refused(box, f)


def test_a_pair_needs_number_and_unit_on_both_sides(monkeypatch):
    pair = {
        "doc_quote": "Hydrostatic pressure: 12",
        "clause_quote": "The hydrostatic pressure shall be at least 10",
    }
    box, f = numeric("typed", monkeypatch, pair=pair, value=None, cq=SENTENCE + ".")
    assert refused(box, f)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "value", ["12", "May 2019", "12/05/2019", "P-101", "316L", "99 bar"]
)
def test_a_claimed_value_must_be_a_figure_with_a_unit_inside_the_document_quote(
    mode, monkeypatch, value
):
    box, f = numeric(mode, monkeypatch, value=value)
    r = submit(box, f)
    assert r["accepted"] is False and r["reason"] in (
        agent_bind.CODE,
        "value_not_on_page",
    )


def test_a_unitless_value_is_refused_by_the_binding_itself(monkeypatch):
    box, f = numeric("typed", monkeypatch, value="12")
    assert refused(box, f)


@pytest.mark.parametrize("mode", MODES)
def test_topic_overlap_needs_two_document_words(mode, monkeypatch):
    pair = {
        "doc_quote": "Pressure: 12 bar for hydrostatic tests",
        "clause_quote": "Pressure shall be at least 10 bar for vessels",
    }
    box, f = numeric(
        mode,
        monkeypatch,
        topic="Hydrostatic vessel",
        pair=pair,
        line="Pressure: 12 bar for hydrostatic tests",
        clause="4.7",
        cq="Pressure shall be at least 10 bar for vessels.",
        value="12 bar",
    )
    assert refused(
        box, f
    )  # one shared word in the document quote (hydrostatic), one in the clause (vessels)


@pytest.mark.parametrize("mode", MODES)
def test_topic_overlap_needs_one_clause_word(mode, monkeypatch):
    pair = {
        "doc_quote": "Pressure: 12 bar for hydrostatic vessel tests",
        "clause_quote": "Pressure shall be at least 10 bar",
    }
    box, f = numeric(
        mode,
        monkeypatch,
        topic="Hydrostatic vessel",
        pair=pair,
        line="Pressure: 12 bar for hydrostatic vessel tests",
        clause="4.6",
        cq="Pressure shall be at least 10 bar.",
        value="12 bar",
    )
    assert refused(box, f)  # two shared words in the document quote, none in the clause
    good_clause = {
        "doc_quote": "Pressure: 12 bar for hydrostatic vessel tests",
        "clause_quote": "Pressure shall be at least 10 bar for vessels",
    }
    box, f = numeric(
        mode,
        monkeypatch,
        topic="Hydrostatic vessel",
        pair=good_clause,
        line="Pressure: 12 bar for hydrostatic vessel tests",
        clause="4.7",
        cq="Pressure shall be at least 10 bar for vessels.",
        value="12 bar",
    )
    assert submit(box, f)["accepted"] is True


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "topic", ["Pressure", "Design pressure", "General notes", "", "the of and"]
)
def test_a_topic_of_fewer_than_two_content_words_never_carries_green_or_red(
    mode, monkeypatch, topic
):
    box, f = numeric(mode, monkeypatch, topic=topic)
    assert refused(box, f)


@pytest.mark.parametrize("mode", MODES)
def test_topic_none_still_needs_a_decided_pair_but_skips_the_overlap(mode, monkeypatch):
    plug(monkeypatch)
    box = make(on=mode == "ref", topic=None)
    assert refused(box, build(mode, TEXTUAL[0]))  # textual: refused whatever the topic
    other = {
        "doc_quote": "Shell thickness: 9 mm",
        "clause_quote": "The shell thickness shall be at least 6 mm",
    }
    decide(box, other)
    f = build(
        mode,
        "Shell thickness: 9 mm",
        clause="4.2",
        cq="The shell thickness shall be at least 6 mm.",
        figures=[other],
        value="9 mm",
    )
    assert (
        submit(box, f)["accepted"] is True
    )  # no topic to overlap with, a decided pair is enough


# clause quote: long enough, and not the clause's own heading (typed only: a block always runs past the heading)
@pytest.mark.parametrize(
    "cq",
    [
        HEADING,
        f"4.5 {HEADING}",
        "Maximum hydrostatic pressure of 15 bar for",
    ],
)
def test_a_clause_quote_that_is_the_heading_or_a_prefix_of_it_is_refused(
    cq, monkeypatch
):
    box, f = numeric(
        "typed", monkeypatch, pair=HEAD_FIG, clause="4.5", cq=cq, value="12 bar"
    )
    assert refused(box, f)


def test_a_clause_quote_that_goes_past_the_heading_is_accepted(monkeypatch):
    box, f = numeric(
        "typed",
        monkeypatch,
        pair=HEAD_FIG,
        clause="4.5",
        cq=f"{HEADING} Vessels shall be marked.",
        value="12 bar",
    )
    assert submit(box, f)["accepted"] is True


def test_a_short_clause_quote_is_refused(monkeypatch):
    pair = {
        "doc_quote": "pressure: 12 bar",
        "clause_quote": "pressure shall be at least 10 bar",
    }
    box, f = numeric(
        "typed",
        monkeypatch,
        pair=pair,
        cq="pressure shall be at least 10 bar",
        value="12 bar",
    )
    assert len(f["clause_quote"]) < agent_bind.MIN_CLAUSE_QUOTE_CHARS and refused(
        box, f
    )


# ------------------------------------------------------------------ helpers, the loop, and no silent unbound path


@pytest.mark.parametrize(
    ("text", "figure"),
    [("12 bar", True), ("12bar", True), ("12 mm", True), ("12", False), ("12 May 2019", False), ("May 2019", False), ("12/05/2019", False),
     ("2019-05-12", False), ("P-101", False), ("M12", False), ("316L", False), ("Class 150", False), ("10 MPa", True), ("20 C", True), ("a 5 mm gap", True),
     ("Pump P-101 A", False), ("dated 12/05/2019 a copy", False), ("revised 2019-05-12 a copy", False), ("issued 12 May 2019 a copy", False), ("Rev M12 A", False)],
)  # fmt: skip
def test_has_figure(text, figure):
    assert agent_bind.has_figure(text) is figure


def test_content_words_are_general():
    assert agent_bind.content_words("The Design pressures of the shells") == {
        "pressure",
        "shell",
    }
    assert agent_bind.content_words("General notes: design data") == frozenset()


class _Box:
    def __init__(self, takes_topic=True):
        self.TOOL_SPECS = [
            {"name": "ask_engineer", "description": "d", "params": {}},
            {"name": "record_finding", "description": "d", "params": {}},
        ]
        self.seen, self.recorded = [], []
        if not takes_topic:
            self.set_item = self._old_set_item

    def set_item(self, item_id, topic=None):
        self.seen.append((item_id, topic))

    def _old_set_item(self, item_id):
        self.seen.append((item_id, "no topic argument"))

    def run(self, name, args):
        if name == "record_finding":
            self.recorded.append(args["finding"])
        return {"ok": True, "result": {"accepted": True}, "cites": []}


def test_the_loop_passes_the_items_topic_and_an_empty_one_when_missing():
    for item, expected in (
        (
            {"id": "I-3", "doc": DOC, "topic": "Hydrostatic pressure"},
            "Hydrostatic pressure",
        ),
        ({"id": "I-4", "doc": DOC}, ""),
    ):
        box = _Box()
        provider = agent_loop.FakeProvider(
            [{"tool": "ask_engineer", "args": {}, "reason": "ask"}]
        )
        agent_loop.run_item(item, {}, box, provider, usd_cap=1.0)
        assert box.seen == [(item["id"], expected)]


def test_a_toolbox_that_takes_no_topic_can_never_hold_a_green_or_red():
    green = {
        "color": "GREEN",
        "doc_quote": "x" * 30,
        "page": 1,
        "action": "none",
        "reason": "r",
    }
    box = _Box(takes_topic=False)
    provider = agent_loop.FakeProvider([{"final": green}])
    out = agent_loop.run_item(
        {"id": "I-5", "doc": DOC, "topic": "Hydrostatic pressure"},
        {},
        box,
        provider,
        usd_cap=1.0,
    )
    assert (
        out["finding"]["color"] == "YELLOW"
        and box.recorded
        and box.recorded[0]["color"] == "YELLOW"
    )


def test_the_same_toolbox_with_a_topic_argument_keeps_green():
    green = {
        "color": "GREEN",
        "doc_quote": "x" * 30,
        "page": 1,
        "action": "none",
        "reason": "r",
    }
    box = _Box()
    provider = agent_loop.FakeProvider([{"final": green}])
    out = agent_loop.run_item(
        {"id": "I-5", "doc": DOC, "topic": "Hydrostatic pressure"},
        {},
        box,
        provider,
        usd_cap=1.0,
    )
    assert out["finding"]["color"] == "GREEN"


def test_one_look_per_page_names_each_item_and_its_topic_and_never_leaves_an_unbound_green():
    green = {
        "item": "I-1",
        "color": "GREEN",
        "doc_quote": "x" * 30,
        "page": 1,
        "action": "none",
        "reason": "r",
    }

    class Provider:
        def complete(self, msgs, specs):
            return {"final": {"findings": [green]}, "usd": 0.0}

    class PageBox(_Box):
        def run(self, name, args):
            if name == "open_page":
                return {"ok": True, "result": "text", "cites": []}
            return super().run(name, args)

    items = [{"id": "I-1", "doc": DOC, "topic": "Hydrostatic pressure", "page": 1}]
    box = PageBox()
    agent_loop.answer_open_page(items, 1, box, Provider(), doc=DOC, usd_cap=1.0)
    assert (
        "I-1",
        "Hydrostatic pressure",
    ) in box.seen  # the item and topic were named before the finding was recorded
    old = PageBox(takes_topic=False)
    answers = agent_loop.answer_open_page(
        items, 1, old, Provider(), doc=DOC, usd_cap=1.0
    )
    assert answers["I-1"]["color"] == "YELLOW"


# ------------------------------------------------------------------ KNOWN LIMIT (honest): no instance binding


@pytest.mark.parametrize("mode", MODES)
def test_known_limit_the_same_label_and_figure_about_another_device_is_not_caught(
    mode, monkeypatch
):
    """A decided figure whose label and figure match the item passes even if the line belongs to another device; only the
    local second opinion and the engineer can tell. Documented in the module docstring."""
    box, f = numeric(mode, monkeypatch)
    assert submit(box, f)["accepted"] is True


# ------------------------------------------------------------------ measured on a generator of invented text

NAMES = [("hydrostatic", "pressure", "bar"), ("shell", "thickness", "mm"), ("coating", "adhesion", "MPa"), ("bearing", "temperature", "C"),
         ("lubricant", "flow", "kg"), ("impeller", "diameter", "mm"), ("flange", "rating", "bar"), ("gasket", "power", "kW")]  # fmt: skip
TITLES = [
    "Invented datasheet revision 3",
    "General notes: design data per standard",
    "Project sheet revision 2",
    "Table of contents",
]


def world():
    num = {
        i: f"{a.capitalize()} {b}: {10 + i} {u}" for i, (a, b, u) in enumerate(NAMES)
    }
    txt = {
        i: f"The {a} {b} was checked and accepted by the inspector on site today"
        for i, (a, b, _u) in enumerate(NAMES)
    }
    sent = {
        i: f"The {a} {b} shall be at least {5 + i} {u}"
        for i, (a, b, u) in enumerate(NAMES)
    }
    page = "\n".join([*TITLES, *num.values(), *txt.values()])
    std = "\n".join(
        f"4.{i + 1} {a.capitalize()} {b}\n{sent[i]}."
        for i, (a, b, _u) in enumerate(NAMES)
    )
    return num, txt, sent, page, std


def test_generator_accepts_no_irrelevant_finding_typed_and_by_reference(monkeypatch):
    plug(monkeypatch)
    num, txt, sent, page, std = world()
    t = {
        "irrelevant_tried": 0,
        "irrelevant_accepted": 0,
        "relevant_tried": 0,
        "relevant_accepted": 0,
    }
    for i, (a, b, _u) in enumerate(NAMES):
        topic = f"{a.capitalize()} {b}"
        for mode in MODES:
            candidates = [(x, "text") for x in (*TITLES, *txt.values())] + [
                (num[j], "num") for j in range(len(NAMES))
            ]
            for line, kind in candidates:
                for clause_i in (i, (i + 1) % len(NAMES)):
                    box = make(on=mode == "ref", topic=topic, page=page, std=std)
                    cq = sent[clause_i]
                    block = f"4.{clause_i + 1} {NAMES[clause_i][0].capitalize()} {NAMES[clause_i][1]} {cq}."
                    kwargs = {
                        "clause": f"4.{clause_i + 1}",
                        "cq": block if mode == "typed" else cq,
                        "page": page,
                    }
                    if kind == "num":
                        pair = {"doc_quote": line, "clause_quote": cq}
                        decide(box, pair)
                        kwargs.update(value=line.split(": ")[1], figures=[pair])
                    ok = submit(box, build(mode, line, **kwargs))["accepted"]
                    real = line == num[i] and clause_i == i
                    t["relevant_tried" if real else "irrelevant_tried"] += 1
                    t["relevant_accepted" if real else "irrelevant_accepted"] += int(ok)
    print(f"GENERATOR {t}")
    assert t["irrelevant_accepted"] == 0
    assert t["relevant_accepted"] == t["relevant_tried"] > 0
