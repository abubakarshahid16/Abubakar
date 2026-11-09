"""GREEN and RED findings are bound to their item (#1690, rule 4). Invented text only; typed AND by reference."""

from __future__ import annotations

import sys
import types

import pytest

from app import agent_bind, agent_loop
from app.agent_quote_refs import make_toolbox, numbered_lines
from app.agent_tools import ToolContext

DOC, STD = "doc-sub", "doc-std"
TITLE = "Invented datasheet revision 3"
GENERAL = "General notes: design data per standard"
OWN = "Hydrostatic pressure: 12 bar"
SENTENCE = "The hydrostatic pressure shall be at least 10 bar"
CLAUSE_TITLE = "Hydrostatic pressure testing requirements for vessels"
TEXT_OWN = (
    "The hydrostatic pressure test was witnessed and accepted by the inspector on site"
)
LINES = [
    TITLE, GENERAL, OWN, "Shell thickness: 9 mm", "Coating adhesion: 4 MPa", "Shell pressure: 5 bar",
    "Hydrostatic pressure margin: 20 bar", "Test head: 12 bar", "Hydrostatic pressure test procedure requirements overview",
    "Hydrostatic pressure record dated 12/05/2019 on file", "Hydrostatic pressure part P-101: 12 bar",
    "General note: all pressure values are given in bar unless stated otherwise", TEXT_OWN,
    "The hydrostatic test was witnessed and accepted by the inspector on site today",
    "Auxiliary device tag B: the hydrostatic pressure of the unrelated auxiliary device is 12 bar",
    "Hydrostatic pressure: 12 bar", "Hydrostatic pressure: 12 bar. Hydrostatic test pressure: 30 bar",
]  # fmt: skip
PAGE = "\n".join(dict.fromkeys(LINES))
STD_TEXT = (
    f"4.1 Hydrostatic pressure\n{SENTENCE}.\n4.2 Shell thickness\nThe shell thickness shall be at least 6 mm.\n"
    f"4.3 Marking\nMark each part clearly and permanently.\n4.4 {CLAUSE_TITLE}\nTesting shall follow the written procedure."
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
    box.run("get_clause", {"standard": "ISO 9999", "clause": "4.1"})
    return box


def plug(monkeypatch, verdict=True):
    mod = types.ModuleType("app.figure_compare")
    mod.compare = lambda d, c: types.SimpleNamespace(
        verdict=verdict, reason="r", direction=None
    )
    monkeypatch.setitem(sys.modules, "app.figure_compare", mod)
    import app

    monkeypatch.setattr(app, "figure_compare", mod, raising=False)


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
    block="C1",
    page=PAGE,
):
    """A finding for the item, typed or by reference. By reference the quote text is built by code from line / block ids."""
    f = {"item": "I-1", "color": colour, "doc": DOC, "page": 1, "standard": "ISO 9999", "clause": clause,
         "action": "none", "priority": "should", "reason": "Stated in the document."}  # fmt: skip
    if mode == "typed":
        f.update(doc_quote=doc_line, clause_quote=cq)
    else:
        f.update(
            doc_quote_ref={"page": 1, "lines": line_id(doc_line, page)},
            clause_quote_ref={
                "standard": "ISO 9999",
                "clause": clause,
                "blocks": block,
            },
        )
        f.pop("page"), f.pop("standard"), f.pop("clause")
    for key, val in (("value", value), ("figures", figures)):
        if val is not None:
            f[key] = val
    return f


def decide(box, fig):
    return box.run("compare_number", fig)["result"]


def submit(box, f):
    return box.run("record_finding", {"finding": f})["result"]


def refused(box, f):
    r = submit(box, f)
    return r["accepted"] is False and r["reason"] == agent_bind.CODE


FIG = {"doc_quote": OWN, "clause_quote": SENTENCE}
MODES = ("typed", "ref")


# ------------------------------------------------------------------ positive controls


@pytest.mark.parametrize("mode", MODES)
def test_a_decided_figure_in_bound_quotes_is_accepted(mode, monkeypatch):
    plug(monkeypatch)
    box = make(on=mode == "ref")
    assert decide(box, FIG)["decided"] is True
    assert (
        submit(box, build(mode, OWN, value="12 bar", figures=[FIG]))["accepted"] is True
    )


@pytest.mark.parametrize("mode", MODES)
def test_a_red_with_a_decided_figure_is_accepted(mode, monkeypatch):
    plug(monkeypatch, verdict=False)
    box = make(on=mode == "ref")
    decide(box, FIG)
    assert (
        submit(box, build(mode, OWN, colour="RED", figures=[FIG]))["accepted"] is True
    )


@pytest.mark.parametrize("mode", MODES)
def test_a_textual_finding_holding_every_topic_word_is_accepted(mode):
    assert submit(make(on=mode == "ref"), build(mode, TEXT_OWN))["accepted"] is True


# ------------------------------------------------------------------ the reviewer's classes, typed AND by reference


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("heading line with the topic words, no figure", {"doc_line": "Hydrostatic pressure test procedure requirements overview"}),
        ("title line and an unrelated block", {"doc_line": TITLE, "clause": "4.3", "cq": "Mark each part clearly and permanently."}),
        ("generic-only overlap", {"doc_line": GENERAL}),
        ("topic word missing from a long textual line", {"doc_line": "The hydrostatic test was witnessed and accepted by the inspector on site today"}),
        ("unitless value", {"doc_line": OWN, "value": "12"}),
        ("value is a date", {"doc_line": "Hydrostatic pressure record dated 12/05/2019 on file", "value": "12/05/2019"}),
        ("value is part of a part number", {"doc_line": "Hydrostatic pressure part P-101: 12 bar", "value": "P-101"}),
        ("figure on the page, not in the quote", {"doc_line": "Shell thickness: 9 mm", "value": "12 bar"}),
        ("a different quantity in the quote", {"doc_line": "Hydrostatic pressure margin: 20 bar", "value": "12 bar"}),
        ("one shared word only", {"doc_line": "Shell pressure: 5 bar", "value": "5 bar"}),
        ("unrelated clause block", {"doc_line": TEXT_OWN, "clause": "4.2", "cq": "The shell thickness shall be at least 6 mm."}),
        ("numeric item never decided by code", {"doc_line": OWN, "value": "12 bar", "figures": [FIG]}),
    ],
)  # fmt: skip
def test_unbound_findings_are_refused(mode, name, kwargs):
    box = make(on=mode == "ref")
    kwargs = dict(kwargs)
    f = build(mode, kwargs.pop("doc_line"), **kwargs)
    assert refused(box, f), name
    assert box.ctx.findings.all() == []


@pytest.mark.parametrize("mode", MODES)
def test_a_decided_pair_does_not_excuse_a_quote_about_another_item(mode, monkeypatch):
    plug(monkeypatch)
    box = make(on=mode == "ref")
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
        value="9 mm",
        figures=[other],
    )
    assert refused(box, f)


@pytest.mark.parametrize("mode", MODES)
def test_the_document_side_of_a_pair_must_stand_inside_the_document_quote(
    mode, monkeypatch
):
    plug(monkeypatch)
    box = make(on=mode == "ref")
    pair = {"doc_quote": "Shell thickness: 9 mm", "clause_quote": SENTENCE}
    decide(box, pair)
    assert refused(box, build(mode, OWN, figures=[pair]))


@pytest.mark.parametrize("mode", MODES)
def test_the_clause_side_of_a_pair_must_stand_inside_the_clause_quote(
    mode, monkeypatch
):
    plug(monkeypatch)
    box = make(on=mode == "ref")
    pair = {
        "doc_quote": OWN,
        "clause_quote": "The shell thickness shall be at least 6 mm",
    }
    decide(box, pair)
    assert refused(box, build(mode, OWN, figures=[pair]))


def test_a_pair_needs_number_and_unit_on_both_sides(monkeypatch):
    plug(monkeypatch)
    box = make()
    pair = {"doc_quote": "Hydrostatic pressure margin", "clause_quote": SENTENCE}
    decide(box, pair)
    f = build("typed", "Hydrostatic pressure margin: 20 bar", figures=[pair])
    assert refused(box, f)


# clause quote rules (typed: a block by reference is always more than the heading)
@pytest.mark.parametrize(
    "cq",
    [
        "Hydrostatic pressure",
        CLAUSE_TITLE,
        f"4.4 {CLAUSE_TITLE}",
        "Hydrostatic pressure testing",
        "shall be at least 10 bar",
    ],
)
def test_a_clause_quote_that_is_short_or_the_clauses_own_heading_is_refused(cq):
    assert refused(
        make(),
        build(
            "typed",
            TEXT_OWN,
            clause="4.4" if "testing" in cq.lower() or "requirements" in cq else "4.1",
            cq=cq,
        ),
    )


def test_a_clause_quote_longer_than_the_heading_is_accepted():
    box = make()
    f = build(
        "typed",
        TEXT_OWN,
        clause="4.4",
        cq=f"{CLAUSE_TITLE} Testing shall follow the written procedure.",
    )
    assert submit(box, f)["accepted"] is True


@pytest.mark.parametrize("mode", MODES)
def test_a_one_word_topic_can_never_carry_green_or_red(mode, monkeypatch):
    plug(monkeypatch)
    for topic in ("Design pressure", "Pressure", "", "the of and"):
        box = make(on=mode == "ref", topic=topic)
        decide(box, FIG)
        assert refused(box, build(mode, OWN, figures=[FIG])), topic
        assert refused(
            box,
            build(
                mode,
                "General note: all pressure values are given in bar unless stated otherwise",
                clause="4.1",
            ),
        )


@pytest.mark.parametrize("mode", MODES)
def test_yellow_is_never_bound(mode):
    box = make(on=mode == "ref", topic="")
    assert submit(box, build(mode, TITLE, colour="YELLOW"))["accepted"] is True


def test_no_topic_known_binds_nothing_by_topic_but_figures_stay_inside_their_quotes():
    box = make(topic=None)
    assert (
        submit(
            box,
            build(
                "typed",
                "Shell thickness: 9 mm",
                clause="4.2",
                cq="shall be at least 6 mm",
                value="9 mm",
            ),
        )["accepted"]
        is True
    )
    assert refused(
        make(topic=None), build("typed", "Shell thickness: 9 mm", value="12 bar")
    )


def test_refusal_hint_has_fixed_words_only_and_names_the_yellow_way():
    r = submit(make(), build("typed", TITLE))
    assert r["reason"] == agent_bind.CODE and r["expect"] == agent_bind.EXPECT
    assert (
        "yellow" in str(agent_bind.EXPECT).lower()
        and "Invented" not in str(r)
        and "Hydrostatic" not in str(r)
    )


# ------------------------------------------------------------------ helpers and the loop


@pytest.mark.parametrize(
    ("text", "figure"),
    [("12 bar", True), ("12bar", True), ("12 mm", True), ("12", False), ("12 May 2019", False), ("May 2019", False), ("12/05/2019", False),
     ("2019-05-12", False), ("P-101", False), ("M12", False), ("316L", False), ("Class 150", False), ("10 MPa", True), ("20 C", True), ("a 5 mm gap", True)],
)  # fmt: skip
def test_has_figure(text, figure):
    assert agent_bind.has_figure(text) is figure


@pytest.mark.parametrize(
    ("line", "heading"),
    [("Hydrostatic Pressure Test Procedure Requirements", True), ("Design data", True), ("Pressure: 12 bar", False), ("The pressure is checked.", False),
     ("One two three four five six seven", False)],
)  # fmt: skip
def test_heading_like(line, heading):
    assert agent_bind.heading_like(line) is heading


def test_content_words_and_topic_order_are_general():
    assert agent_bind.content_words("The Design pressures of the shells") == {
        "pressure",
        "shell",
    }
    assert agent_bind.content_words("General notes: design data") == frozenset()
    assert agent_bind.topic_order(
        "Hydrostatic test pressure of the main shell wall section"
    ) == ["hydrostatic", "test", "pressure", "main"]


def test_the_loop_passes_the_items_topic_and_an_empty_one_when_missing():
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

    for item, expected in (
        (
            {"id": "I-3", "doc": DOC, "topic": "Hydrostatic pressure"},
            "Hydrostatic pressure",
        ),
        ({"id": "I-4", "doc": DOC}, ""),
    ):
        box = Box()
        provider = agent_loop.FakeProvider(
            [{"tool": "ask_engineer", "args": {}, "reason": "ask"}]
        )
        agent_loop.run_item(item, {}, box, provider, usd_cap=1.0)
        assert box.seen == [(item["id"], expected)]


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


# ------------------------------------------------------------------ KNOWN LIMITS (honest): heuristic, no instance binding


@pytest.mark.parametrize("mode", MODES)
def test_known_limit_a_paragraph_about_another_device_with_the_same_words_is_not_caught(
    mode, monkeypatch
):
    """The binding does not bind the quote to the right INSTANCE: only the local second opinion and the engineer can."""
    plug(monkeypatch)
    other = "Auxiliary device tag B: the hydrostatic pressure of the unrelated auxiliary device is 12 bar"
    pair = {
        "doc_quote": "hydrostatic pressure of the unrelated auxiliary device is 12 bar",
        "clause_quote": SENTENCE,
    }
    box = make(on=mode == "ref")
    assert (
        decide(box, pair)["decided"] is False
    )  # the subject check on labels keeps this one from being decided
    assert refused(box, build(mode, other, figures=[pair]))
    # but a textual claim on the same line carries the topic words, so it passes the heuristic
    assert submit(make(on=mode == "ref"), build(mode, other))["accepted"] is True


# ------------------------------------------------------------------ measured on a generator of invented text

NAMES = [("hydrostatic", "pressure", "bar"), ("shell", "thickness", "mm"), ("coating", "adhesion", "MPa"), ("bearing", "temperature", "C"),
         ("lubricant", "flow", "kg"), ("impeller", "diameter", "mm"), ("flange", "rating", "bar"), ("gasket", "power", "kW")]  # fmt: skip
TITLES = [
    TITLE,
    GENERAL,
    "Project sheet revision 2",
    "Table of contents",
    "Hydrostatic pressure test procedure requirements overview",
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
    tally = {
        "irrelevant_tried": 0,
        "irrelevant_accepted": 0,
        "relevant_tried": 0,
        "relevant_accepted": 0,
    }
    for i, (a, b, _u) in enumerate(NAMES):
        topic = f"{a.capitalize()} {b}"
        for mode in MODES:
            candidates = [(t, "text", False) for t in (*TITLES, *txt.values())] + [
                (num[j], "num", j == i) for j in range(len(NAMES))
            ]
            for line, kind, own_line in candidates:
                own_line = own_line or line == txt[i]
                for clause_i in (i, (i + 1) % len(NAMES)):
                    box = make_box(mode, topic, page, std)
                    cq = sent[clause_i]
                    block_text = f"4.{clause_i + 1} {NAMES[clause_i][0].capitalize()} {NAMES[clause_i][1]} {cq}."
                    kwargs = {
                        "clause": f"4.{clause_i + 1}",
                        "cq": block_text if mode == "typed" else cq,
                    }
                    if kind == "num":
                        pair = {"doc_quote": line, "clause_quote": cq}
                        decide(box, pair)
                        kwargs.update(value=line.split(": ")[1], figures=[pair])
                    f = build(mode, line, page=page, **kwargs)
                    ok = submit(box, f)["accepted"]
                    real = own_line and clause_i == i
                    tally["relevant_tried" if real else "irrelevant_tried"] += 1
                    tally["relevant_accepted" if real else "irrelevant_accepted"] += (
                        int(ok)
                    )
    print(f"GENERATOR {tally}")
    assert tally["irrelevant_accepted"] == 0
    assert tally["relevant_accepted"] == tally["relevant_tried"] > 0


def make_box(mode, topic, page, std):
    box = make(on=mode == "ref", topic=topic, page=page, std=std)
    for clause in range(1, len(NAMES) + 1):
        box.run("get_clause", {"standard": "ISO 9999", "clause": f"4.{clause}"})
    return box


def test_known_limit_a_unit_the_repos_unit_table_lacks_is_not_a_figure():
    """A true figure in a unit the repo does not know (here a hardness scale) is refused: the safe side, say YELLOW."""
    assert agent_bind.has_figure("Gasket hardness: 17 HRC") is False
    assert agent_bind.has_figure("Gasket power: 17 kW") is True


# ------------------------------------------------------------------ survivors of the first revert run, each now killed


def test_a_longer_topic_needs_every_word_not_just_two(monkeypatch):
    box = make(topic="Hydrostatic test pressure")  # three content words
    two_of_three = (
        "The hydrostatic pressure was accepted by the inspector on site today"
    )
    all_three = "The hydrostatic test pressure was accepted by the inspector on site"
    page = "\n".join([two_of_three, all_three])
    for text, ok in ((two_of_three, False), (all_three, True)):
        box = make(topic="Hydrostatic test pressure", page=page)
        f = build("typed", text, page=page)
        assert (submit(box, f)["accepted"] is True) is ok, text


def test_a_short_textual_quote_is_refused():
    text = "Hydrostatic pressure was accepted."  # topic words, a sentence, but under 40 characters
    page = text + "\n" + OWN
    assert len(text) < agent_bind.MIN_TEXT_QUOTE_CHARS
    assert refused(make(page=page), build("typed", text, page=page))


def test_a_decided_pair_with_a_unitless_value_is_refused(monkeypatch):
    plug(monkeypatch)
    box = make()
    decide(box, FIG)
    assert refused(box, build("typed", OWN, value="12", figures=[FIG]))


def test_a_decided_pair_whose_doc_side_is_not_in_the_quote_is_refused(monkeypatch):
    plug(monkeypatch)
    box = make()
    pair = {"doc_quote": "Hydrostatic pressure: 15 bar", "clause_quote": SENTENCE}
    assert decide(box, pair)["decided"] is True
    assert refused(box, build("typed", OWN, figures=[pair]))


def test_a_decided_pair_whose_clause_side_is_not_in_the_clause_quote_is_refused(
    monkeypatch,
):
    plug(monkeypatch)
    box = make()
    pair = {
        "doc_quote": OWN,
        "clause_quote": "The hydrostatic pressure shall be at least 11 bar",
    }
    assert decide(box, pair)["decided"] is True
    assert refused(box, build("typed", OWN, figures=[pair]))


def test_a_decided_pair_without_units_is_refused(monkeypatch):
    plug(monkeypatch)
    box = make()
    pair = {
        "doc_quote": "Hydrostatic pressure: 12",
        "clause_quote": "The hydrostatic pressure shall be at least 10",
    }
    assert decide(box, pair)["decided"] is True
    assert refused(box, build("typed", OWN, figures=[pair], cq=SENTENCE + "."))


@pytest.mark.parametrize(
    "text",
    [
        "Pump P-101 A",
        "dated 12/05/2019 a copy",
        "revised 2019-05-12 a copy",
        "issued 12 May 2019 a copy",
        "Rev M12 A",
    ],
)
def test_digits_of_dates_and_part_numbers_are_not_figures_even_before_a_unit_like_letter(
    text,
):
    assert agent_bind.has_figure(text) is False


def test_a_short_clause_quote_with_the_topic_words_is_refused():
    assert refused(
        make(), build("typed", TEXT_OWN, cq="hydrostatic pressure shall be at least")
    )
