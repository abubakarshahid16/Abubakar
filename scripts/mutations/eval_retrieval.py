"""Mutations of `scripts/eval_retrieval.py` - the B6 / ADR-0022 additions."""

from __future__ import annotations

from ._base import REPO, Mutation

_P = REPO / "scripts" / "eval_retrieval.py"
_T = "tests/test_eval_retrieval_b6.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M760", phase=67, description="B6 eval: precision@k counts only the first correct hit",
        path=_P,
        anchor='            sum(1 for r in c.get("correct_ranks") or [] if r <= k) / k\n',
        replacement='            (1 if (c["first_correct_rank"] or 99) <= k else 0) / k\n',
        target=_T, keyword="precision_counts_every_correct_hit",
    ),
    Mutation(
        id="M761", phase=67, description="B6 eval: nothing scored reports precision 0 instead of None",
        path=_P,
        anchor="            for c in scored) / n) if n else None\n",
        replacement="            for c in scored) / n) if n else 0.0\n",
        target=_T, keyword="nothing_scored_is_none", tags=("honesty",),
    ),
    Mutation(
        id="M762", phase=67, description="B6 eval: p95 latency is read as the median",
        path=_P,
        anchor="    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]\n    return {",
        replacement="    p95 = statistics.median(ordered)\n    return {",
        target=_T, keyword="latency_percentiles",
    ),
    Mutation(
        id="M763", phase=67, description="B6 eval: negatives count as separated when any one is below",
        path=_P,
        anchor='        "separated": (max(neg) < min(pos)) if neg and pos else None,\n',
        replacement='        "separated": (min(neg) < min(pos)) if neg and pos else None,\n',
        target=_T, keyword="separate_only_when_every_negative", tags=("honesty",),
    ),
    Mutation(
        id="M764", phase=67, description="B6 eval: a case answered below rank 1 lends its top score",
        path=_P,
        anchor='           if c.get("first_correct_rank") == 1 and c.get("top_rerank_score") is not None]\n',
        replacement='           if c.get("top_rerank_score") is not None]\n',
        target=_T, keyword="answered_below_rank_one", tags=("honesty",),
    ),
)
