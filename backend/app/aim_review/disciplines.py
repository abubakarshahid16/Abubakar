"""Discipline reviewers of the judge (S4): the SAME judge, with a section of what a senior engineer of one discipline checks and
worked examples (owner, 25 Nov 2026, planner note 23:35 b, item 4: start with two). Behind
`settings.aim_discipline_reviewers_enabled` (OFF): off, the judge's prompt on Claude is exactly the general one; on the local
model the reviewer's section and worked examples are always given (its judge needs the examples most).

THE TABLE is data (`reference/discipline_reviewers.json`): each reviewer names the paper kinds and the equipment families it
reviews; the routing is code (`reviewer_for`), never an AI manager. A paper no reviewer takes is judged by the general judge.

WHAT DOES NOT CHANGE: the items, their whole clause text, the paper (the whole paper whenever it fits, exactly as the general
judge sees it; no new cutting), the labels, the answer shape and every check code makes on the answer. The reviewer's section
is added to the task's head only. The run records which reviewer judged (`identity.reviewer`). No model, no socket here."""

from __future__ import annotations

import functools
import json
from pathlib import Path

from app.config import settings

from . import library as L

TABLE = Path(__file__).resolve().parents[1] / "reference" / "discipline_reviewers.json"


@functools.cache
def table() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def _family(equipment_type) -> str | None:
    tid = L.type_id_of(equipment_type) if equipment_type else None
    return next((t["family"] for t in L.taxonomy() if t["id"] == tid), None)


def reviewer_for(identity: dict | None) -> str | None:
    """The reviewer that judges this paper (its kind, and its equipment family when the reviewer names families), or None: the
    general judge. Switch off: None."""
    from .budget import is_local

    # on the local model the section and its worked examples are always given (26 Nov 2026: the 14B judged 58 of 61 points
    # "Question" and gave numbers on 5); on Claude only behind the switch, until it is scored
    if not (settings.aim_discipline_reviewers_enabled or is_local()) or not isinstance(
        identity, dict
    ):
        return None
    kind, family = identity.get("kind"), _family(identity.get("equipment_type"))
    for name, r in table()["reviewers"].items():
        if kind in r["kinds"] and (not r["families"] or family in r["families"]):
            return name
    return None


def block(name: str | None) -> str:
    """The reviewer's section for the head of the judge's task ("" for the general judge)."""
    if not name:
        return ""
    r = table()["reviewers"][name]
    checks = "\n".join(f"- {c}" for c in r["checks"])
    examples = "\n".join(
        f"EXAMPLE {i}. Item: {json.dumps(e['item'], sort_keys=True)}\n  The paper, page {e['paper']['page']}: "
        f'"{e["paper"]["quote"]}"\n  A correct judgment: {json.dumps(e["answer"], sort_keys=True)}'
        for i, e in enumerate(r["examples"], 1)
    )
    return (
        f"YOU JUDGE AS A {r['title'].upper()}. Besides the task below, a {r['title']} checks:\n{checks}\n"
        "WORKED EXAMPLES (invented papers and invented rule books, only to show the judgment; never quote them):\n"
        f"{examples}\nThe task, the labels and the answer shape below are unchanged.\n\n"
    )


def judge_head(identity: dict | None) -> str:
    """The reviewer's section for this paper, and the reviewer recorded on the run's identity ("" and nothing recorded when
    the general judge judges)."""
    name = reviewer_for(identity)
    if name and isinstance(identity, dict):
        identity["reviewer"] = name
    return block(name)
