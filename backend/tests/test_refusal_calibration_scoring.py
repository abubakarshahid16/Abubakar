"""eval/refusal_calibration.py's "which clause applies" scoring.

Plan step 4 added `condition_choice`: when a question named no condition and
several clauses competed, EVERY one is returned (`mode == "options"`), none
picked for the reader. The old scoring only ever looked at the FIRST
passage, so an "options" answer whose correct clause sat second or third was
counted as wrong even though the reader was shown the right answer among the
options. `mode == "matched"` (a named condition already picked a winner) is
scored exactly like any other extract - unchanged.

Both tests build a synthetic `item` and monkeypatch `_retrieve`,
`_lexical_signal` and `_run_answer` so no corpus, index or model is needed -
same pattern `test_eval_scoring.py` uses for `run_eval.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

import refusal_calibration as rc  # noqa: E402


class _NullLog:
    def write(self, row: dict) -> None:
        pass


ITEM = {"chunk_id": "chunk_right", "number": "50", "unit": "mm",
       "topic": "weld cap height", "comparator": "max",
       "sentence": "weld cap height shall not exceed 50 mm"}


def _patch_common(monkeypatch, run_answer_result: dict) -> None:
    monkeypatch.setattr(rc, "_retrieve", lambda question, allowed: {
        "hits": [], "top": None, "top_score": -1.0, "top5_scores": [], "separation": None,
    })
    monkeypatch.setattr(rc, "_lexical_signal", lambda question, top, allowed: {
        "ok": True, "covered": 1, "total": 1,
    })
    monkeypatch.setattr(rc, "_run_answer", lambda question, allowed: run_answer_result)


def test_the_correct_clause_among_options_is_its_own_row_not_exact(monkeypatch):
    """`mode == "options"`, the RIGHT clause is the second of two shown -
    never the lead passage `answered_chunk_id` points at. The old scoring
    (first passage only) would have called this really wrong."""
    _patch_common(monkeypatch, {
        "answer_type": "extract",
        "answered_chunk_id": "chunk_other",
        "answered_text": "a rival clause for a different condition, 30 mm",
        "condition_mode": "options",
        "answer_passages": [
            {"chunk_id": "chunk_other", "text": "a rival clause for a different condition, 30 mm"},
            {"chunk_id": "chunk_right", "text": "weld cap height shall not exceed 50 mm"},
        ],
    })
    row = rc.score_present(None, ITEM, "doc", "q", frozenset(), _NullLog(), item_id=0)

    assert row["condition_mode"] == "options"
    assert row["correct_with_options"] is True
    # NEVER merged into exact or same-value - those keep meaning "the ONE
    # passage returned was right", which an options answer does not claim.
    assert row["answered_exact"] is False
    assert row["answered_same_value"] is None
    assert row["answered_right"] is True
    assert row["answered_really_wrong"] is False


def test_a_matched_condition_scores_like_any_ordinary_extract(monkeypatch):
    """`mode == "matched"`: the named condition already picked the winner,
    which IS the lead passage. Scored exactly as before - `correct_with_options`
    stays False even though the passage is exactly right, because this is an
    ordinary exact match, not an "every option shown" answer."""
    _patch_common(monkeypatch, {
        "answer_type": "extract",
        "answered_chunk_id": "chunk_right",
        "answered_text": "weld cap height shall not exceed 50 mm",
        "condition_mode": "matched",
        "answer_passages": [
            {"chunk_id": "chunk_right", "text": "weld cap height shall not exceed 50 mm"},
        ],
    })
    row = rc.score_present(None, ITEM, "doc", "q", frozenset(), _NullLog(), item_id=0)

    assert row["condition_mode"] == "matched"
    assert row["correct_with_options"] is False
    assert row["answered_exact"] is True
    assert row["answered_right"] is True
    assert row["answered_really_wrong"] is False
