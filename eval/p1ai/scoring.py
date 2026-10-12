"""P1-AI scoring: what the MODEL wrote, checked by code that does not trust it (#674).

The three things scored, per question:

  1. FIGURES. Every figure the shown answer states (a number, its sign, and the
     unit written beside it) must be in a passage that sentence cites. This
     checker is written HERE, apart from `app/answer.py`'s own filter
     (`ground_numbers`, #653), on purpose: if the exam called the filter it is
     meant to test, weakening the filter would weaken the exam by the same
     amount and nothing would turn red. It is stricter than the filter in one
     way (no unit conversion: the invented questions are written so none is
     needed) and cruder in another (words, not sentences' meaning).
  2. CLAUSE. The cited clause is the expected clause (or a subclause).
  3. COULD NOT READ, NOT A GUESS. A question the corpus cannot answer must be
     refused. An answerable one the model cannot support may also be refused
     (that costs a point, it is not a guess); a WRONG answer is a guess.

Pure functions. No model, no database, no network.
"""
from __future__ import annotations

import re

#: A number with its sign, standing alone (not inside A-001, 4.1.2 handled below).
_NUMBER = re.compile(r"(?<![\w.,^/])([-+]?)(\d+(?:[.,]\d+)*)(?![\w])")
_CITATION = re.compile(r"\[S\d+\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[(])|\n+")
#: Words that are units. Anything else after a number is just the next word:
#: "4.1 says" is a clause number, not 4.1 "says". A token with a slash, a
#: caret, a degree sign, a percent sign or a bracket is also a unit (mm/s, 10^9).
_UNIT_WORDS = frozenset({
    "mm", "cm", "m", "km", "um", "micrometre", "micrometres", "micrometer", "micrometers", "kg", "g", "mg",
    "s", "sec", "h", "hr", "hrs", "hour", "hours", "min", "minute", "minutes", "day", "days", "week", "weeks",
    "month", "months", "year", "years", "bar", "barg", "bara", "kpa", "kpag", "mpa", "pa", "psi", "psig", "psia",
    "degc", "degf", "°c", "°f", "k", "hz", "khz", "v", "kv", "a", "ma", "kw", "w", "mw", "ohm", "ohms", "db",
    "rpm", "l", "ml", "kn", "n", "nm", "times", "percent", "points", "threads", "degrees", "degree", "deg"})
_UNIT_SYNONYMS = {"%": "percent", "degrees": "deg", "degree": "deg", "°c": "degc", "hr": "hours", "hrs": "hours",
                  "hour": "hours", "minute": "minutes", "min": "minutes", "year": "years", "month": "months",
                  "week": "weeks", "day": "days", "micrometer": "micrometre", "micrometers": "micrometres"}
_UNIT_TOKEN = re.compile(r"^[A-Za-z%°][A-Za-z0-9%°/^.()\-]*")


def _num(text: str) -> float | None:
    t = text.replace(",", ".") if re.fullmatch(r"\d+,\d+", text) else text.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _unit(text: str) -> str | None:
    m = _UNIT_TOKEN.match(text.strip())
    if not m:
        return None
    word = m.group(0).rstrip(".,;:").lower()
    if not word:
        return None
    if word in _UNIT_WORDS or any(c in word for c in "/^°%(") or word.startswith("db("):
        return _UNIT_SYNONYMS.get(word, word)
    return None


def figures(text: str) -> list[dict]:
    """Every figure in `text`: {value, sign, unit, line_units}. `unit` is the word
    written right after the number (None when it is a stop word or absent);
    `line_units` are the units written earlier on the same line, for a table
    row whose unit sits in its label ("Allowable accumulation, psi (kPa)  10.0")."""
    out = []
    for line in re.split(r"\n", _CITATION.sub("", text)):
        for m in _NUMBER.finditer(line):
            value = _num(m.group(2))
            if value is None:
                continue
            after = line[m.end():].lstrip(" \t")
            if after.startswith("%"):
                unit = "percent"
            else:
                unit = _unit(after)
            before = line[:m.start()]
            near = re.findall(r"[A-Za-z%°][A-Za-z0-9%°/^.()\-]*", before)[-4:] \
                + re.findall(r"[A-Za-z%°][A-Za-z0-9%°/^.()\-]*", after)[:3]
            line_units = {u for u in (_unit(w.strip("()[],;:.")) for w in near) if u}
            out.append({"value": value, "sign": "-" if m.group(1) == "-" else "+",
                        "unit": unit, "line_units": line_units,
                        "text": (m.group(0) + (" " + (unit or "") if unit else "")).strip()})
    return out


def _grounded(claim: dict, page: list[dict]) -> bool:
    for found in page:
        if abs(found["value"] - claim["value"]) > 1e-9:
            continue
        if claim["sign"] != found["sign"]:
            continue
        if claim["unit"] is None:
            return True
        units = ({found["unit"]} if found["unit"] else set()) | found["line_units"]
        if claim["unit"] in units:
            return True
    return False


def ungrounded_figures(answer: str, passages: list[dict], cited_only: list[dict]) -> list[str]:
    """Figures the answer states that the passage its sentence cites does not.
    `passages` are the passages [S#] points into; `cited_only` are the passages
    the whole answer cited (used for a sentence that carries no marker). The
    sentence itself is never returned: only the figure, as written."""
    bad: list[str] = []
    for sentence in _SENTENCE.split(answer or ""):
        claims = figures(sentence)
        if not claims:
            continue
        marks = sorted({int(n) for n in re.findall(r"\[S(\d+)\]", sentence) if 1 <= int(n) <= len(passages)})
        pool = [passages[n - 1] for n in marks] if marks else cited_only
        page = [f for p in pool for f in figures(p.get("text") or "")]
        for claim in claims:
            if not _grounded(claim, page):
                bad.append(claim["text"])
    return bad


# ----------------------------------------------------------------------- facts

def _fold(text: str) -> str:
    t = _CITATION.sub("", text or "").lower().replace("%", " percent")
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    return " ".join(t.split())


def facts_present(answer: str, needles: list[str]) -> bool:
    folded = _fold(answer)
    return all(_fold(n) in folded for n in needles)


def forbidden_present(answer: str, forbidden: list[str]) -> list[str]:
    folded = _fold(answer)
    return [f for f in forbidden if _fold(f) in folded]


# ------------------------------------------------------------------------ rows

def score_row(q: dict, row: dict, result: dict) -> dict:
    """Add the P1-AI fields to `row` (made by `run_eval.score_one`). `result` is
    the chat answer. Nothing here changes what the system showed."""
    from run_eval import _clause_matches, evidence_of

    answered = result["answer_type"] in ("extract", "generated")
    text = result.get("answer") or ""
    passages = result.get("passages") or []
    cited = evidence_of(result)
    row["model_unavailable"] = result["answer_type"] == "model_unavailable"
    row["could_not_read"] = result["answer_type"] == "insufficient_evidence"
    row["figures_ungrounded"] = ungrounded_figures(text, passages, cited) if answered else []
    row["figures_ok"] = not row["figures_ungrounded"]
    # What the model tried and the system's own filter removed: the model's
    # quality, reported, not part of the pass rule.
    row["model_figures_removed"] = len(result.get("numbers_unsupported") or [])
    row["forbidden_found"] = forbidden_present(text, q.get("forbidden_in_answer") or []) if answered else []
    if row.get("length_limited"):
        # A refusal caused by the token budget says nothing about the corpus
        # (run_eval.score_one): it is neither a pass nor a correct refusal.
        row.update(facts_ok=None, clause_ok=None, guessed=False, passed=False)
        return row
    if not q["answerable"]:
        row["facts_ok"] = None
        row["clause_ok"] = None
        row["guessed"] = answered
        row["passed"] = bool(not answered and not row["model_unavailable"])
        return row
    row["facts_ok"] = bool(answered and facts_present(text, q["expected_answer_contains"])
                           and not row["forbidden_found"])
    row["clause_ok"] = (bool(_clause_matches(q["expected_clause"], row.get("cited_clause")))
                        if q.get("expected_clause") else None)
    row["guessed"] = bool(answered and not row["facts_ok"])
    row["passed"] = bool(answered and row["figures_ok"] and row["facts_ok"]
                         and row.get("retrieval_correct") is True and row["clause_ok"] is not False)
    return row


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    clause = [r["clause_ok"] for r in rows if r.get("clause_ok") is not None]
    times = sorted(r["seconds"] for r in rows)

    def pct_time(p: float) -> float:
        return times[min(len(times) - 1, int(p * len(times)))] if times else 0.0

    return {
        "questions": n,
        "passed": sum(1 for r in rows if r["passed"]),
        "figures_ungrounded_answers": [r["id"] for r in rows if not r["figures_ok"]],
        "guessed": [r["id"] for r in rows if r.get("guessed")],
        "unanswerable_answered": [r["id"] for r in unanswerable if r["answered"]],
        "could_not_read_answerable": [r["id"] for r in answerable if r["could_not_read"]],
        "clause_right": [sum(clause), len(clause)],
        "model_figures_removed": sum(r["model_figures_removed"] for r in rows),
        "model_unavailable": [r["id"] for r in rows if r["model_unavailable"]],
        "seconds_total": round(sum(times), 1),
        "seconds_median": round(times[len(times) // 2], 1) if times else 0.0,
        "seconds_p95": round(pct_time(0.95), 1),
        "seconds_worst": round(times[-1], 1) if times else 0.0,
    }


def compare_with_baseline(rows: list[dict], baseline: dict | None) -> list[str]:
    """Why this run must BLOCK. The first two rules need no baseline at all:
    a shown figure the cited page does not hold, and a question the corpus
    cannot answer that was answered. Then, with a stored baseline for THIS
    model: every question that passed must still pass (or, with a `gate`
    written by the owner, the minimum and the protected ones)."""
    reasons = []
    for r in rows:
        if not r["figures_ok"]:
            reasons.append(f"{r['id']} shows a figure its cited passage does not hold: "
                           f"{', '.join(r['figures_ungrounded'])}")
        if not r["answerable"] and r["answered"]:
            reasons.append(f"{r['id']} is unanswerable and was answered (a guess)")
    if not baseline or not baseline.get("passing"):
        return reasons
    passed_now = {r["id"] for r in rows if r["passed"]}
    gate = baseline.get("gate")
    must = baseline["passing"] if gate is None else gate["protected"]
    if gate is not None and len(passed_now) < gate["min_passing"]:
        reasons.append(f"{len(passed_now)} questions pass; the gate needs at least {gate['min_passing']}")
    for qid in must:
        if qid not in passed_now:
            reasons.append(f"{qid} passed in the baseline and does not now")
    return reasons
