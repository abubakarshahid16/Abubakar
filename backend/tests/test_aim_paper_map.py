"""The paper map (owner's standing lesson, 25 Nov 2026 23:15: NO BLIND CHUNKING): a paper too long for one judge call is judged
with a map made by code and the full pages each item cites, never a window alone; every call records what it read. A long
INVENTED contract; a fake model that can only find what the call's full pages hold."""

from __future__ import annotations

import json
import re

import pytest

from app import agent_general_review
from app.aim_review import paper_map as M
from app.aim_review import steps as S
from app.aim_review.paper import Paper
from app.config import settings

FILLER = (
    "Invented general wording of the invented agreement between the invented parties, repeated to make a long page. "
    * 40
)
COUNT = 30


def _page(k: int) -> str:
    extra = {20: "The warranty bond shall be ten (10) percent of the invented price.",
             25: "Delivery of the invented spare parts shall be within 40 days of the order."}.get(k, "")  # fmt: skip
    return (f"ARTICLE {k} INVENTED TERMS\n{k}.1 The Contractor shall deliver the invented item {k} within {k + 10} days.\n"
            f"Tag of the invented unit: XA-{100 + k}\nItem  Qty  Unit  Rate\nA{k}  1  set  {k}\nB{k}  2  set  {k}\n"
            f"Line C{k}  3  set  {k}\n{extra}\n{FILLER}")  # fmt: skip


PAPER = Paper(
    paper_id="doc_inv_long_contract", pages={k: _page(k) for k in range(1, COUNT + 1)}
)
WINDOWS = agent_general_review.window_pages(PAPER.pages, 9000, 1)
#: where each item's thing stands (page, the exact words), or None: it stands nowhere
TRUTH = {
    "C001": (12, "The Contractor shall deliver the invented item 12 within 22 days."),
    "C002": (20, "The warranty bond shall be ten (10) percent of the invented price."),
    "C003": (
        25,
        "Delivery of the invented spare parts shall be within 40 days of the order.",
    ),
    "C004": None,
    "C005": (28, "The Contractor shall deliver the invented item 28 within 38 days."),
}


def _item(i: str, pages=(), fields=()) -> dict:
    return {"id": i, "book": "", "clause": "", "source": S.KNOWLEDGE, "topic": "t", "what_to_check": "an invented check",
            "rule_quote": "", "applies_when": "always", "paper_fields": list(fields), "paper_pages": list(pages),
            "kind": "presence"}  # fmt: skip


ITEMS = [_item("C001", [12]), _item("C002", fields=["warranty bond"]), _item("C003", [3]), _item("C004", [5]),
         _item("C005", fields=["a field the paper never names"])]  # fmt: skip


class _Model:
    """Finds an item only when its words stand on the FULL pages the call carries (never in the map alone)."""

    def __init__(self):
        self.asked = []

    def ask(self, **kw):
        self.asked.append(kw)
        full = (
            kw["cached"].split("PAPER MAP", 1)[-1].split("\n\n", 1)[-1]
            if "PAPER MAP" in kw["cached"]
            else kw["cached"]
        )
        out = []
        for i in re.findall(r'"id": "(C\d+)"', kw["prompt"]):
            t = TRUTH.get(i)
            if t and t[1] in full:
                out.append(
                    {
                        "id": i,
                        "label": "Question",
                        "page": t[0],
                        "quote": t[1],
                        "comment": "Please confirm the term.",
                    }
                )
            else:
                out.append({"id": i, "not_here": True, "page": t[0] if t else None})
        return {"judgments": out}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "aim_paper_map_enabled", True)


def _run(scope=None):
    model, scope = _Model(), scope if scope is not None else {}
    lines, stop = S.s4_judge(model, PAPER, {"books": []}, None, items=ITEMS, windows=WINDOWS, lead="claude-sonnet-5-5",
                             scope=scope)  # fmt: skip
    return model, scope, {ln["item_id"]: ln for ln in lines}, stop


def test_the_map_is_made_by_code_from_every_page_with_headings_tags_tables_and_values():
    m = M.build(PAPER)
    assert sorted(m) == list(range(1, COUNT + 1))
    e = m[12]
    assert (
        e["headings"][0].startswith("ARTICLE 12")
        and "XA-112" in e["tags"]
        and e["table_rows"] >= 3
    )
    assert any("22 days" in v for v in e["values"])
    text = M.text(m)
    assert (
        text.startswith("PAPER MAP")
        and "page 30: " in text
        and M.tokens(text) < M.tokens(PAPER.text_with_markers()) / 5
    )


def test_the_paper_is_long_and_switch_off_judges_window_by_window_and_says_so():
    assert len(WINDOWS) > 2
    model, scope, _lines, _stop = _run()
    assert all("PAPER MAP" not in a["cached"] for a in model.asked)
    assert scope["judge_seen"] and all(
        s.startswith("page window ") and s.endswith(", no map")
        for s in scope["judge_seen"]
    )


def test_every_item_is_judged_with_the_map_and_its_cited_pages_and_every_call_records_what_it_read(
    on,
):
    model, scope, lines, stop = _run()
    assert stop == ""
    assert all(
        a["cached"].startswith("PAPER MAP") for a in model.asked
    )  # the map in every call
    assert len(scope["judge_seen"]) == len(model.asked) and all(
        s.startswith("map + pages ") for s in scope["judge_seen"]
    )
    first = {}
    for a in model.asked:
        for i in re.findall(r'"id": "(C\d+)"', a["prompt"]):
            first.setdefault(i, a)
    for item in (
        ITEMS
    ):  # the first call of every item holds the full text of every page it cites
        cited = M.cited_pages(item, PAPER)
        assert all(PAPER.pages[n] in first[item["id"]]["cached"] for n in cited), item[
            "id"
        ]
    assert (lines["C001"]["page"], lines["C002"]["page"]) == (
        12,
        20,
    )  # cited page; found by its field
    assert (
        lines["C003"]["page"] == 25
    )  # not on its cited page: asked again on the page the map showed
    assert (
        lines["C005"]["page"] == 28
    )  # placed nowhere by code: every part, each with the map


def test_an_item_shown_nowhere_is_said_to_be_on_no_page_only_after_every_page_was_read_in_full(
    on,
):
    model, _scope, lines, _stop = _run()
    read = set()
    for a in model.asked:
        if '"id": "C004"' in a["prompt"]:
            read |= {n for n, t in PAPER.pages.items() if t in a["cached"]}
    assert read == set(PAPER.pages)
    assert (
        lines["C004"]["label"] == "Question"
        and lines["C004"]["code"] == S.NOT_ON_ANY_PAGE
    )


def test_a_paper_that_fits_is_judged_whole_as_before_and_the_record_says_whole_paper(
    on,
):
    small = Paper(
        paper_id="doc_inv_short", pages={1: _page(1)[:400], 2: _page(2)[:400]}
    )
    model, scope = _Model(), {}
    S.s4_judge(
        model,
        small,
        {"books": []},
        None,
        items=ITEMS[:1],
        windows=[[1, 2]],
        lead="claude-sonnet-5-5",
        scope=scope,
    )
    assert (
        scope["judge_seen"] == [M.WHOLE] and "PAPER MAP" not in model.asked[0]["cached"]
    )


def test_pages_are_written_as_ranges():
    assert (
        M.pages_text([9, 3, 4, 5, 11, 10]) == "3-5, 9-11"
        and M.seen([2]) == "map + pages 2"
    )
    assert json.dumps(M.Call([ITEMS[0]], [1, 2]).seen) == '"map + pages 1-2"'
