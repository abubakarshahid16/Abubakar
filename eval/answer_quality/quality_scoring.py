"""Answer-quality scoring (order 189, part B): faithfulness, response relevancy,
noise sensitivity and citation quality (ALCE style), by CODE only.

No judge model, no NLI model, no network. Where Ragas and ALCE ask a model "is
this claim supported", this module asks a stricter, cruder question of the text:
the figure and its unit are on the cited page (`eval/p1ai/scoring.py`, written
apart from the application's own filter) and most of the sentence's content
words are in the cited passage. So the numbers are NOT comparable with
published scores; they are comparable between prompt variants run on the same
questions, which is what they are for.

Pure functions over dicts shaped like `chat.ask`'s answer: `answer` (text with
[S1] markers) and `passages` (list of {"text": ...}).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p1ai"))
import scoring as p1ai  # (eval/p1ai/scoring.py)

_MARK = re.compile(r"\[S(\d+)[^\]]*\]")
_WORD = re.compile(r"[a-z0-9][a-z0-9.\-/%]*")
#: Words that carry no claim. A short closed list of function words, not a
#: vocabulary of any one document type.
_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "at",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "shall",
        "should",
        "must",
        "may",
        "can",
        "will",
        "would",
        "not",
        "no",
        "than",
        "then",
        "there",
        "their",
        "from",
        "into",
        "over",
        "under",
        "per",
        "each",
        "all",
        "any",
        "if",
        "when",
        "where",
        "which",
        "who",
        "what",
        "how",
        "also",
        "only",
        "both",
        "such",
        "other",
        "more",
        "most",
        "less",
        "least",
        "one",
        "two",
    ]
)
#: A sentence is a claim only if it says something: not a lead-in, not a heading.
_MIN_CONTENT = 3
#: Share of a claim's content words that must be in the cited text.
SUPPORT = 0.7
#: Share needed for a single cited passage to count as relevant to the sentence.
RELEVANT = 0.4
REFUSAL = "insufficient evidence"


def _content(text: str) -> list[str]:
    folded = _MARK.sub(" ", text or "").lower()
    return [
        w.rstrip(".-/")
        for w in _WORD.findall(folded)
        if w.rstrip(".-/") not in _STOP and len(w.rstrip(".-/")) > 1
    ]


def claims(answer: str) -> list[str]:
    """The sentences of the answer that state something (refusal text and
    sentences with fewer than three content words are not claims)."""
    if not answer or REFUSAL in answer.lower():
        return []
    out = []
    for raw in p1ai._SENTENCE.split(answer):
        sentence = raw.strip(" -*#\t")
        if len(_content(sentence)) >= _MIN_CONTENT:
            out.append(sentence)
    return out


def _marks(sentence: str, n_passages: int) -> list[int]:
    return sorted(
        {int(n) for n in _MARK.findall(sentence) if 1 <= int(n) <= n_passages}
    )


def _overlap(sentence: str, text: str) -> float:
    words = _content(sentence)
    if not words:
        return 0.0
    held = set(_content(text))
    return sum(1 for w in words if w in held) / len(words)


def supported(sentence: str, passages: list[dict]) -> bool:
    """A claim is supported when every figure it states is on the cited page
    (with its sign and unit) and at least SUPPORT of its content words are in
    the cited passages. A sentence that cites nothing is judged against
    `passages` as a whole."""
    marks = _marks(sentence, len(passages))
    pool = [passages[n - 1] for n in marks] if marks else list(passages)
    text = " ".join(p.get("text") or "" for p in pool)
    if p1ai.ungrounded_figures(sentence, passages, pool):
        return False
    return _overlap(sentence, text) >= SUPPORT


def faithfulness(answer: str, passages: list[dict]) -> float | None:
    """Share of the answer's claims that are supported. None when the answer
    makes no claim (a refusal is neither faithful nor unfaithful)."""
    cl = claims(answer)
    if not cl:
        return None
    return sum(1 for c in cl if supported(c, passages)) / len(cl)


def citation_recall(answer: str, passages: list[dict]) -> float | None:
    """Share of claims that carry at least one valid citation."""
    cl = claims(answer)
    if not cl:
        return None
    return sum(1 for c in cl if _marks(c, len(passages))) / len(cl)


def citation_precision(answer: str, passages: list[dict]) -> float | None:
    """Share of citation markers whose passage is relevant to its sentence.
    None when nothing is cited."""
    total = good = 0
    for c in claims(answer):
        for n in _marks(c, len(passages)):
            total += 1
            good += _overlap(c, passages[n - 1].get("text") or "") >= RELEVANT
    return good / total if total else None


def response_relevancy(answer: str, needles: list[str]) -> float | None:
    """Share of the question's expected facts the answer states. Facts are the
    labels' `expected_answer_contains`. A forbidden fact is a separate count
    (`forbidden`), never folded into this share."""
    if not needles:
        return None
    return sum(1 for n in needles if p1ai.facts_present(answer, [n])) / len(needles)


def forbidden(answer: str, banned: list[str]) -> list[str]:
    return p1ai.forbidden_present(answer, banned)


def noise_sensitivity(
    noisy_answer: str, gold_passages: list[dict], noisy_passages: list[dict]
) -> float | None:
    """Ragas' idea in code: with irrelevant passages added to the context, what
    share of the answer's claims is NOT supported by the passages that really
    answer the question? Lower is better. `noisy_passages` is the list the
    markers in `noisy_answer` point into; `gold_passages` is the clean list."""
    cl = claims(noisy_answer)
    if not cl:
        return None
    bad = 0
    for c in cl:
        cited = [noisy_passages[n - 1] for n in _marks(c, len(noisy_passages))]
        gold_texts = {(p.get("text") or "") for p in gold_passages}
        from_gold = [p for p in cited if (p.get("text") or "") in gold_texts]
        # a claim resting only on a passage that is not a gold one is noise
        if (cited and not from_gold) or not supported(c, gold_passages):
            bad += 1
    return bad / len(cl)


# ------------------------------------------------------------------ aggregate

#: measure -> True when higher is better.
MEASURES = {
    "faithfulness": True,
    "response_relevancy": True,
    "citation_recall": True,
    "citation_precision": True,
    "noise_sensitivity": False,
}


def score_row(q: dict, result: dict, noisy: dict | None = None) -> dict:
    """One question's measures. `q` is a p1ai-style label; `result` the answer;
    `noisy` the same question asked with extra irrelevant passages (optional)."""
    answer = result.get("answer") or ""
    passages = result.get("passages") or []
    row = {
        "id": q["id"],
        "answered": result.get("answer_type") in ("extract", "generated")
        and bool(answer),
        "faithfulness": faithfulness(answer, passages),
        "citation_recall": citation_recall(answer, passages),
        "citation_precision": citation_precision(answer, passages),
        "response_relevancy": response_relevancy(
            answer, q.get("expected_answer_contains") or []
        ),
        "forbidden": forbidden(answer, q.get("forbidden_in_answer") or []),
        "noise_sensitivity": None,
    }
    if noisy is not None:
        row["noise_sensitivity"] = noise_sensitivity(
            noisy.get("answer") or "", passages, noisy.get("passages") or []
        )
    return row


def aggregate(rows: list[dict]) -> dict:
    """Mean of each measure over the questions where it exists, with the count
    it is a mean of (a share with no denominator is not reported)."""
    out: dict = {"questions": len(rows)}
    for name in MEASURES:
        vals = [r[name] for r in rows if r.get(name) is not None]
        out[name] = {
            "mean": round(sum(vals) / len(vals), 4) if vals else None,
            "n": len(vals),
        }
    out["forbidden_answers"] = sorted(r["id"] for r in rows if r.get("forbidden"))
    return out


def keep_variant(
    base: dict,
    variant: dict,
    *,
    false_meets_base: int = 0,
    false_meets_variant: int = 0,
) -> list[str]:
    """Why a prompt variant must NOT be kept. Empty list = same or better on
    EVERY measure and no new false Meets or forbidden answer. A measure with no
    value on either side cannot justify keeping the variant, so it blocks."""
    reasons = []
    for name, higher in MEASURES.items():
        b, v = base[name]["mean"], variant[name]["mean"]
        if b is None or v is None:
            reasons.append(
                f"{name}: no value on one side (base {b}, variant {v}); cannot show it is not worse"
            )
        elif (v < b) if higher else (v > b):
            reasons.append(f"{name}: worse ({b} -> {v})")
    new_forbidden = set(variant["forbidden_answers"]) - set(base["forbidden_answers"])
    if new_forbidden:
        reasons.append(f"new forbidden answers: {', '.join(sorted(new_forbidden))}")
    if false_meets_variant > false_meets_base or false_meets_variant > 0:
        reasons.append(
            f"false Meets: {false_meets_base} -> {false_meets_variant} (must stay 0)"
        )
    return reasons
