"""The local route's method fixes never change a CLAUDE review (lead-4, 26 Nov 2026): a fake-model review on the Claude route
sends exactly the prompts and reaches exactly the lines of main 475adb91. The record in tests/data/aim_review_main_475adb91.json
was made by main's own code: one review per kind on the method tests' invented paper, the whole-paper check on, every call's
step with the sha256 of its prompt and paper text, and every line. No network, no model."""

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


@pytest.mark.parametrize("kind", sorted(MAIN))
def test_a_claude_route_review_sends_and_decides_exactly_as_main(
    tmp_path, monkeypatch, kind
):
    monkeypatch.setattr(settings, "aim_answered_check_enabled", True)
    monkeypatch.setattr(settings, "aim_discipline_reviewers_enabled", False)
    conn = next(open_aim_db(tmp_path, monkeypatch))
    model = E.FakeModel(kind=kind, subject_key=f"test_{kind}")
    r = aim_review.run(conn, run_id=f"run_{kind}", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    calls = [{"step": a["step"], "prompt": _sha(a["prompt"]), "paper": _sha(a["cached_text"]), "carries": sorted(a["carries"])}
             for a in model.asked]  # fmt: skip
    lines = json.loads(
        json.dumps([{k: ln.get(k) for k in LINE_KEYS} for ln in r.lines], default=str)
    )
    assert (
        calls == MAIN[kind]["calls"]
        and lines == MAIN[kind]["lines"]
        and r.status == MAIN[kind]["status"]
    )
