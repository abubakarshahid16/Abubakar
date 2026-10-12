"""B6 / ADR-0022 additions to `scripts/eval_retrieval.py`: precision@k,
latency p50/p95, and the negative-query summary. Pure functions over scored
cases - no model, no database - so each rule is pinned exactly."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "eval_retrieval_under_test", REPO / "scripts" / "eval_retrieval.py")
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)


def _case(first, correct, latency=0.1, top=None):
    return {"first_correct_rank": first, "correct_ranks": correct,
            "latency_s": latency, "top_rerank_score": top}


def test_precision_counts_every_correct_hit_in_the_first_k():
    scored = [_case(1, [1, 2]), _case(3, [3]), _case(None, [])]
    m = ev.metrics(scored)
    # (2/5 + 1/5 + 0) / 3 cases
    assert abs(m["precision@5"] - (0.4 + 0.2) / 3) < 1e-9
    # a correct hit at rank 7 counts at 10, not at 5
    assert ev.metrics([_case(7, [7])])["precision@5"] == 0.0
    assert ev.metrics([_case(7, [7])])["precision@10"] == 0.1


def test_recall_and_mrr_are_unchanged_by_the_additions():
    m = ev.metrics([_case(1, [1]), _case(4, [4]), _case(None, [])])
    assert m["recall@5"] == 2 / 3 and abs(m["mrr"] - (1 + 0.25) / 3) < 1e-9


def test_nothing_scored_is_none_not_zero():
    m = ev.metrics([])
    assert m["precision@5"] is None and m["latency_p50_ms"] is None


def test_latency_percentiles_are_from_the_measured_times():
    times = [0.1] * 18 + [2.0, 3.0]
    s = ev.latency_summary(times)
    assert s["latency_p50_ms"] == 100.0
    assert s["latency_p95_ms"] == 2000.0


def test_negatives_separate_only_when_every_negative_scores_below_every_answer():
    scored = [_case(1, [1], top=4.0), _case(1, [1], top=2.5)]
    good = [{"flagged": True, "top_rerank_score": -8.0},
            {"flagged": False, "top_rerank_score": 1.0}]
    n = ev.negative_metrics(good, scored)
    assert n["negatives_flagged"] == 1 and n["negative_best_score"] == 1.0
    assert n["answered_worst_top_score"] == 2.5 and n["separated"] is True
    bad = good + [{"flagged": False, "top_rerank_score": 3.0}]
    assert ev.negative_metrics(bad, scored)["separated"] is False


def test_a_case_answered_below_rank_one_is_not_an_answered_top_score():
    """Its top hit is some OTHER passage, so its score says nothing about how
    well answered questions score."""
    scored = [_case(3, [3], top=0.5), _case(1, [1], top=2.0)]
    # 0.5 is some other passage's score; counting it would lower the bar the
    # negatives are measured against.
    assert ev.negative_metrics([], scored)["answered_worst_top_score"] == 2.0
    assert ev.negative_metrics([], scored)["separated"] is None
