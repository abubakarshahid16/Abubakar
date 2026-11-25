"""The way back per live update (owner via the planner, 26 Nov 2026 03:25): with AIM_U6B_ENABLED, AIM_U7B_ENABLED and
AIM_U8_ENABLED all off a review sends exactly the prompts and reaches exactly the lines of main 475adb91.

The record in tests/data/aim_review_main_475adb91.json was made by main 475adb91's own code: one fake-model review per kind on
the method tests' invented paper, the whole-paper check on, every call's step with the sha256 of its prompt and of its paper
text, and every line. No network, no model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app import aim_review
from app.aim_review import engine as E
from app.config import settings
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

MAIN = json.loads(
    (Path(__file__).parent / "data" / "aim_review_main_475adb91.json").read_text(
        encoding="utf-8"
    )
)
SWITCHES = ("aim_u6b_enabled", "aim_u7b_enabled", "aim_u8_enabled")
#: The formula checks: their own switch since update 9, ON by default; "all off = main" pins it off.
FORMULAS = "aim_formula_checks_enabled"
LINE_KEYS = (
    "item_id",
    "label",
    "shown_label",
    "comment",
    "code_note",
    "field",
    "page",
    "quote",
    "ask",
    "deferred",
    "source",
)


def _sha(s) -> str:
    return hashlib.sha256(str(s or "").encode()).hexdigest()[:16]


def _record(tmp_path, monkeypatch, kind: str) -> dict:
    monkeypatch.setattr(
        settings, "aim_answered_check_enabled", True
    )  # live has the whole-paper check on: 6b is exercised
    conn = next(open_aim_db(tmp_path, monkeypatch))
    model = E.FakeModel(kind=kind, subject_key=f"test_{kind}")
    r = aim_review.run(conn, run_id=f"run_{kind}", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    return {
        "status": r.status,
        "stop": r.stop_reason,
        "calls": [
            {
                "step": a["step"],
                "prompt": _sha(a["prompt"]),
                "paper": _sha(a["cached_text"]),
                "carries": sorted(a["carries"]),
            }
            for a in model.asked
        ],
        "lines": [{k: ln.get(k) for k in LINE_KEYS} for ln in r.lines],
    }


@pytest.mark.parametrize("kind", sorted(MAIN))
def test_with_every_update_switched_off_a_review_sends_and_decides_exactly_as_main(
    tmp_path, monkeypatch, kind
):
    for name in SWITCHES:
        monkeypatch.setattr(settings, name, False)
    got = _record(tmp_path, monkeypatch, kind)
    assert [c["step"] for c in got["calls"]] == [c["step"] for c in MAIN[kind]["calls"]]
    assert (
        got["calls"] == MAIN[kind]["calls"]
    )  # every prompt and paper text, by its sha256
    assert (
        json.loads(json.dumps(got["lines"], default=str)) == MAIN[kind]["lines"]
        and got["status"] == MAIN[kind]["status"]
    )


def test_the_check_can_fail_with_the_updates_switched_on_the_prompts_differ(
    tmp_path, monkeypatch
):
    """A record compared with itself proves nothing (REVIEW.md): switched on, the same review must differ from main."""
    for name in SWITCHES:
        monkeypatch.setattr(settings, name, True)
    got = _record(tmp_path, monkeypatch, "datasheet")
    assert got["calls"] != MAIN["datasheet"]["calls"]


def test_every_switch_is_off_by_default_and_the_formula_checks_are_on():
    from app.config import Settings

    assert all(Settings.model_fields[name].default is False for name in SWITCHES)
    assert Settings.model_fields[FORMULAS].default is True


def _firm(page: int) -> dict:
    """A firm formula line with invented figures (as `formulas.lines` gives one)."""
    return {"item_id": "F-invented", "label": "Not met", "field": "Invented setting against the limit", "page": page,
            "quote": "Invented setting 150 psig", "comment": "Not met, proven by code: invented.", "standard": "X-STD",
            "clause": "X-1", "book_document_id": "doc_x", "source": "held standard", "topic": "Invented setting",
            "code": "formula check invented: code compared",
            "numbers": {"paper_value": "150", "paper_unit": "psig", "rule_value": "10", "rule_unit": "barg"},
            "code_compare": {"result": "fail", "read_from": "verified quotes", "why": "invented"}, "deferred": False,
            "ask": ""}  # fmt: skip


def test_with_the_default_switch_formula_lines_appear_and_upgrade_and_off_none_is_added(
    tmp_path, monkeypatch
):
    """Update 9 (lead-4): the formula checks out of AIM_U8_ENABLED, on by default. Through the engine a formula line is added
    with the default and never with the switch off; and a firm line upgrades the comment already made on its finding (G's
    join), adding no second line. Invented figures; the formula lookup is stood in, the join is the real one."""
    from types import SimpleNamespace

    from app.aim_review import formulas as F

    monkeypatch.setattr(F, "lines", lambda conn, paper, books: [_firm(1)])
    for name in SWITCHES:
        monkeypatch.setattr(settings, name, False)
    with_default = _record(tmp_path / "on", monkeypatch, "datasheet")
    assert any(ln["item_id"] == "F-invented" for ln in with_default["lines"])
    monkeypatch.setattr(settings, FORMULAS, False)
    switched_off = _record(tmp_path / "off", monkeypatch, "datasheet")
    assert not any(ln["item_id"] == "F-invented" for ln in switched_off["lines"])
    ai = {"item_id": "C001", "label": "AI opinion", "field": "Invented setting", "page": 1, "quote": "Invented setting 150 psig",
          "comment": "The AI's words.", "source": "held standard", "code_note": "", "deferred": False, "ask": "concern",
          "numbers": {"paper_value": "150", "paper_unit": "psig", "rule_value": "10", "rule_unit": "barg"}}  # fmt: skip
    state = SimpleNamespace(decided=[dict(ai)], books=set(), reference_ids=set())
    F.add_lines(None, None, state)
    assert (
        len(state.decided) == 1 and state.decided[0]["label"] == "Not met"
    )  # upgraded in place, no second comment
