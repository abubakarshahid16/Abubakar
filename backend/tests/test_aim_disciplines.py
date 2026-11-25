"""Discipline reviewers of the judge (owner, 25 Nov 2026: start with two, mechanical and contract): routed by kind and equipment
family in code, the same judge with its own section and worked examples, behind a switch that is OFF. Invented papers only."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import aim_review
from app.aim_review import disciplines as D
from app.aim_review import library as L
from app.aim_review import prompts as P
from app.aim_review import steps as S
from app.aim_review.paper import Paper
from app.config import settings

PAGES = {
    1: "Invented sheet. Corrosion allowance: 1.5 mm",
    2: "Invented sheet, page 2. Design temperature: 80 C",
}
PAPER = Paper(paper_id="doc_inv_sheet", pages=PAGES)
ITEMS = [{"id": "C001", "book": "", "clause": "", "source": S.KNOWLEDGE, "topic": "t", "what_to_check": "x", "rule_quote": "",
          "applies_when": "always", "paper_fields": [], "paper_pages": [], "kind": "limit"}]  # fmt: skip
MECHANICAL_TYPE = next(t["id"] for t in L.taxonomy() if t["family"] == "rotating")
OTHER_TYPE = next(t["id"] for t in L.taxonomy() if t["family"] == "electrical")


class _Model:
    def __init__(self):
        self.asked = []

    def ask(self, **kw):
        self.asked.append(kw)
        return {
            "judgments": [
                {
                    "id": "C001",
                    "label": "Question",
                    "page": 1,
                    "quote": PAGES[1],
                    "comment": "Please confirm.",
                }
            ]
        }


class _Text:
    def pages(self, _doc):
        return {}

    def page(self, _doc, _n):
        return None


def _judge(identity: dict) -> dict:
    model = _Model()
    S.s4_judge(
        model,
        PAPER,
        {"books": []},
        _Text(),
        items=ITEMS,
        windows=[[1, 2]],
        lead="claude-sonnet-5-5",
        scope=identity,
    )
    (request,) = model.asked
    return request


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "aim_discipline_reviewers_enabled", True)


def test_switch_off_the_judge_asks_exactly_the_general_task_and_records_no_reviewer():
    identity = {"kind": "datasheet", "equipment_type": MECHANICAL_TYPE}
    asked = _judge(identity)
    assert D.reviewer_for(identity) is None and "reviewer" not in identity
    assert (
        asked["prompt"].startswith(P.S4_TASK.split("%(items)s")[0][:60])
        and "YOU JUDGE AS" not in asked["prompt"]
    )


def test_routing_by_kind_and_equipment_family_in_code(on):
    assert (
        D.reviewer_for({"kind": "datasheet", "equipment_type": MECHANICAL_TYPE})
        == "mechanical"
    )
    assert D.reviewer_for({"kind": "contract", "equipment_type": None}) == "contract"
    assert (
        D.reviewer_for({"kind": "datasheet", "equipment_type": OTHER_TYPE}) is None
    )  # not a mechanical family
    assert (
        D.reviewer_for({"kind": "datasheet", "equipment_type": None}) is None
    )  # no family: the general judge
    assert (
        D.reviewer_for({"kind": "procedure", "equipment_type": MECHANICAL_TYPE}) is None
    )


def test_a_reviewer_adds_its_section_and_examples_and_keeps_the_whole_paper_and_the_task(
    on,
):
    general = _judge({"kind": "datasheet", "equipment_type": OTHER_TYPE})
    identity = {"kind": "datasheet", "equipment_type": MECHANICAL_TYPE}
    mech = _judge(identity)
    assert identity["reviewer"] == "mechanical"  # the run records who judged
    assert mech["cached"] == general["cached"] and all(
        t in mech["cached"] for t in PAGES.values()
    )  # the whole paper, as before
    assert (
        "YOU JUDGE AS A SENIOR MECHANICAL ENGINEER" in mech["prompt"]
        and "EXAMPLE 3." in mech["prompt"]
    )
    assert mech["prompt"].endswith(
        general["prompt"]
    )  # the task, the labels, the answer shape and the items unchanged
    assert (
        mech["step"] == general["step"] == "aim_judge"
        and mech["carries"] == general["carries"]
    )
    contract = _judge({"kind": "contract"})
    assert "SENIOR CONTRACTS ENGINEER" in contract["prompt"] and contract[
        "prompt"
    ].endswith(general["prompt"])


def test_every_worked_example_is_a_judgment_the_judges_own_rules_allow():
    """An example teaches the answer shape: a wrong example teaches a wrong judgment."""
    shape = set(re.findall(r'"([a-z_]+)":', P.S4_TASK)) | {"other", "items", "id"}
    for name, r in D.table()["reviewers"].items():
        assert set(r["kinds"]) <= set(L.KINDS) and set(r["families"]) <= {
            t["family"] for t in L.taxonomy()
        }, name
        assert len(r["examples"]) >= 2 and len(r["checks"]) >= 4, name
        for e in r["examples"]:
            a, item = e["answer"], e["item"]
            assert (
                set(a) <= shape
                and a["label"] in aim_review.LABELS
                and a["id"] == item["id"]
            ), (name, a["id"])
            assert item["standard"].startswith("Invented"), "invented rule books only"
            assert (
                a["quote"] == e["paper"]["quote"] and 5 <= len(a["quote"].split()) <= 30
            )
            assert len(a["comment"].split()) <= 35
            if a["label"] in ("Met", "Not met"):
                assert a.get("numbers") and not a.get(
                    "deferred"
                )  # a stated value and a limit: code compares
            if a.get("deferred"):
                assert a["label"] == "Question" and a.get("ask") in (
                    "confirm",
                    "concern",
                )  # a value left open: a Question
            if a["label"] == "Does not apply":
                assert item["applies_when"] != "always" and not a["comment"]


def test_the_package_module_names_no_equipment_and_no_rule_book():
    """The routing data lives in the reference file; the package code stays general (CLAUDE.md, package ban)."""
    text = Path(D.__file__).read_text(encoding="utf-8").lower()
    assert MECHANICAL_TYPE.replace("_", " ") not in text and "rotating" not in text
