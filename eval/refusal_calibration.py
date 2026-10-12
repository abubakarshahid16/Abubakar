"""Refusal-calibration: measure the rerank floor against the owner's real corpus.

WHY (docs/limitations.md, "Why this is not tuned away"; app/answer.py
MIN_RERANK_SCORE = -3.0). Whether the system answers or refuses is decided by
ONE cross-encoder score against ONE fixed floor, calibrated on 12 examples
from a reference corpus that is not the owner's. This script measures,
self-supervised - no human answer key, no LLM-generated questions, every
question built from a fixed deterministic template - how that floor actually
behaves on the real corpus.

WHAT IT BUILDS, needing no human-written key:

  ANSWER-PRESENT. `--present` (default 200) retrievable chunks with a usable
  requirement sentence, found by scanning up to `--scan-cap` chunks sampled
  seeded and stratified across COMPANY_STANDARD documents (one draw per
  document in round-robin, so no single large standard dominates the set),
  stopping as soon as the target is reached. Each chunk is scanned for one
  sentence matching a fixed requirement shape ("X shall not exceed N", "X
  shall be at least N", "minimum X of N", ...); that sentence's own subject
  phrase is the TOPIC. The correct answer is that chunk, on its own page.

  ANSWER-ABSENT. A candidate list of business/commercial terms an engineering
  standard would not state (warranty period, payment terms, ...), each
  VERIFIED absent by `keyword.term_occurrences` before use - the same check
  `eval/run_eval.py`'s `check_ground_truth` already relies on. Plus, for
  every answer-present topic, one REAL-SUBJECT-WRONG-VALUE sibling: the same
  real topic, asking about a number that provably does not appear in that
  chunk's own text.

  FOUR WORDINGS, always the same four, template-only (no model call builds a
  question):
    (a) DOC     - the topic in the document's own words, unchanged.
    (b) KEYWORD - the topic alone, as a bare noun phrase.
    (c) CASUAL  - "how much ... is allowed" framing.
    (d) LAY     - one word of the topic swapped for its lay synonym from
        app/glossary.py, when one of the topic's words has an entry -
        SKIPPED otherwise, never invented.

READ-ONLY, LOCAL, NO CLAUDE SPEND. Works on a `live_guard.diagnostic_copy()`,
never the live file - the same pattern `scripts/blind_score.py` uses.
`tier="extract"` never calls a model (it only quotes); the reranker is a
local ONNX model. NOTHING HERE CHANGES `MIN_RERANK_SCORE` OR ANY GATE - it
only measures them, at the current floor and at a swept range of others.

WHAT "WRONG" MEANS HERE - standards repeat clauses across revisions and
sister standards, so a different chunk answering a present-question is not
automatically a mistake. A present question's answer is scored in two tiers:
  - EXACT: the answered chunk is the one the question was built from.
  - SAME-VALUE: a different chunk, but it states the same number and unit
    (checked by re-running the requirement-shape scan on that chunk's own
    text, falling back to a plain "number near unit" search).
  Only a different chunk stating a DIFFERENT value counts as really wrong.

  A wrong-value question (real topic, fabricated number) is scored by what
  the returned passage actually contains, not just whether it answered:
  - CONFIDENT WRONG: the passage contains the fabricated number, not the
    true one - the failure mode this test exists to catch.
  - CORRECTED WITH EVIDENCE: the passage contains the true number - correct
    behaviour for a quote-returning system that does not use the number in
    the question, it just returns the passage the topic maps to.
  - OTHER: answered, but neither number appears in the returned text.
  - REFUSED: not answered at extract tier.

FOUR APPROXIMATIONS, stated so the numbers are read correctly:
  - The lexical-gate verdict recorded per question is `lexical.assess` run
    against the TOP-RANKED hit's text alone, not the multi-candidate gate
    `answer._assess_candidates` actually runs across the whole shortlist.
  - The floor-sweep table is computed ARITHMETICALLY from each question's
    recorded (lexical_ok, top_score) pair, not by re-running search once per
    floor - the floor only gates a threshold comparison, so this is exact
    for that comparison, chunk/value classification does not change with
    the floor because retrieval order does not change with the floor.
  - The same-value check is a text scan (requirement-shape reuse, else a
    "number near unit" regex), not a semantic equivalence check - it can
    miss a value stated in an unusual way, or (rarely) match a coincidental
    same number in an unrelated clause.
  - `scores.separation` is computed over whatever the reranker returned as
    the top-20 candidate pool for that question, per its own definition.

WHAT IT PRINTS. Counts, score distributions and floor-sweep tables only -
never a question, a chunk's text, a filename or a clause number (CLAUDE.md
rule 1). Every count states its own denominator (rule 4). A full per-row
JSONL log (scores, ids, booleans - no text) is written to `--log-path`
(default gold/refusal_calibration_log.jsonl, git-ignored) so candidates B
(best score across wordings) and C (relative separation) can be computed
from the log without re-running the expensive scoring pass.

Usage, from the repo root with the venv active:

    python -u eval/refusal_calibration.py
    python -u eval/refusal_calibration.py --present 60 --seed 20260929
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

WORDINGS = ("doc", "keyword", "casual", "lay")

# ------------------------------------------------------------- requirement shapes
#
# Each pattern names its own comparator ("max", "min", "eq") so wording (a)
# can echo the clause's own word ("maximum"/"minimum") rather than a guess.
# Deliberately narrow and stated as such: a requirement phrased some other
# way is simply not found, and the yield (reported) is lower than the sample
# size rather than a template inventing a sentence that was never there.
#: Longer/more specific alternatives FIRST - regex alternation takes the
#: first match, not the longest, so "m" before "microns?" would truncate it.
_UNIT = r"(?:mm|cm|microns?|percent|hours?|days?|minutes?|db\(a\)|dba|deg\s?c|°c|mpa|kpa|bar|psi|kg|m|%)?"
_REQUIREMENT_SHAPES: tuple[tuple[str, re.Pattern], ...] = (
    ("max", re.compile(
        r"(?P<topic>[A-Za-z][A-Za-z0-9 ,/\-]{2,60}?)\s+shall\s+not\s+exceed\s+"
        rf"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})", re.IGNORECASE)),
    ("min", re.compile(
        r"(?P<topic>[A-Za-z][A-Za-z0-9 ,/\-]{2,60}?)\s+shall\s+be\s+at\s+least\s+"
        rf"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})", re.IGNORECASE)),
    ("max", re.compile(
        rf"maximum\s+(?P<topic>[A-Za-z][A-Za-z0-9 ,/\-]{{2,60}}?)\s+of\s+"
        rf"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})", re.IGNORECASE)),
    ("min", re.compile(
        rf"minimum\s+(?P<topic>[A-Za-z][A-Za-z0-9 ,/\-]{{2,60}}?)\s+of\s+"
        rf"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})", re.IGNORECASE)),
    ("eq", re.compile(
        r"(?P<topic>[A-Za-z][A-Za-z0-9 ,/\-]{2,60}?)\s+shall\s+be\s+"
        rf"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})(?!\s*(?:least|more))", re.IGNORECASE)),
)

_LEADING_JUNK = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:the|a|an)\s+", re.IGNORECASE)

#: Business/commercial terms an engineering standard would not state.
#: Candidates only - each is VERIFIED absent (keyword.term_occurrences == 0)
#: before it is used as a question topic.
ABSENT_CANDIDATES = (
    "warranty period", "payment terms", "liquidated damages", "bid bond",
    "performance bond", "insurance premium", "retention money",
    "force majeure clause", "arbitration venue", "currency exchange rate",
    "advance payment guarantee", "invoice payment schedule",
    "contract termination fee", "escrow account", "penalty interest rate",
)


def _clean_topic(topic: str) -> str | None:
    topic = _LEADING_JUNK.sub("", topic).strip(" ,;:-")
    words = topic.split()
    if not (2 <= len(words) <= 6):
        return None
    if not any(w.isalpha() and len(w) > 2 for w in words):
        return None
    return " ".join(words)


def find_requirement(text: str) -> dict | None:
    """The first sentence in `text` matching a known requirement shape, or
    None. Splits on '.', ';' and newlines - a cheap sentence boundary, good
    enough for a template scan, not a real parser."""
    for piece in re.split(r"(?<!\d)\.(?!\d)|[\n;]", text):
        piece = piece.strip()
        if len(piece) < 15 or len(piece) > 220:
            continue
        for comparator, pattern in _REQUIREMENT_SHAPES:
            m = pattern.search(piece)
            if not m:
                continue
            topic = _clean_topic(m.group("topic"))
            if not topic:
                continue
            return {
                "topic": topic, "comparator": comparator,
                "number": m.group("number"), "unit": (m.group("unit") or "").strip(),
                "sentence": piece,
            }
    return None


def _states_value(text: str, number: str | None, unit: str | None) -> bool:
    """True if `text` states the same (number, unit) - reusing the
    requirement-shape scan first (a real match, comparator-aware), falling
    back to a plain "number near unit" search. A text-level heuristic, not a
    semantic check - see the module docstring's APPROXIMATIONS."""
    if not number:
        return False
    req = find_requirement(text)
    if req and req["number"] == number and (req["unit"] or "").lower() == (unit or "").lower():
        return True
    unit_part = re.escape(unit) if unit else ""
    pattern = re.escape(number) + r"\s*" + unit_part
    return bool(re.search(pattern, text, re.IGNORECASE))


def _chunk_text(conn, chunk_id: str | None) -> str | None:
    if not chunk_id:
        return None
    row = conn.execute("SELECT text FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    return row["text"] if row else None


# ------------------------------------------------------------------ wordings

def _reverse_glossary() -> dict[str, str]:
    """{a technical phrasing: its lay word}, inverted from app/glossary.py's
    own list - never a new mapping invented here."""
    from app import glossary
    out: dict[str, str] = {}
    for lay, (phrasings, _why) in glossary.GLOSSARY.items():
        for phrase in phrasings:
            out.setdefault(phrase.lower(), lay)
    return out


def _swap_lay(topic: str, reverse_glossary: dict[str, str]) -> str | None:
    for phrase, lay in reverse_glossary.items():
        if phrase in topic.lower():
            return re.sub(re.escape(phrase), lay, topic, flags=re.IGNORECASE)
    return None


def build_questions(topic: str, comparator: str, number: str, unit: str,
                    reverse_glossary: dict[str, str]) -> dict[str, str]:
    """{wording: question}. "lay" is absent from the dict when no word of
    `topic` has a glossary entry - never invented, per the module docstring."""
    word = {"max": "maximum", "min": "minimum", "eq": "specified"}[comparator]
    out = {
        "doc": f"What is the {word} {topic}?",
        "keyword": f"{topic} {word} limit",
        "casual": f"how much {topic} is allowed",
    }
    lay_topic = _swap_lay(topic, reverse_glossary)
    if lay_topic:
        out["lay"] = f"how much {lay_topic} is allowed"
    return out


def pick_wrong_number(number: str, sentence: str) -> str | None:
    """A number NOT in `sentence`, never a guess dressed as a measurement -
    None when no such number could be found in three tries."""
    try:
        base = float(number)
    except ValueError:
        return None
    for offset in (base + 7, base * 2 + 1, base + 100):
        wrong = f"{offset:g}"
        if wrong not in sentence:
            return wrong
    return None


def build_wrong_value_questions(topic: str, comparator: str, number: str, unit: str,
                                sentence: str,
                                reverse_glossary: dict[str, str]) -> dict[str, str] | None:
    """The same real topic, asking about a number NOT in `sentence`. None
    when `pick_wrong_number` found none."""
    wrong = pick_wrong_number(number, sentence)
    if wrong is None:
        return None
    word = {"max": "allowed to be at most", "min": "required to be at least",
           "eq": "specified as"}[comparator]
    out = {
        "doc": f"Is {topic} {word} {wrong}{unit}?",
        "keyword": f"{topic} {wrong}{unit}",
        "casual": f"is {topic} of {wrong}{unit} allowed",
    }
    lay_topic = _swap_lay(topic, reverse_glossary)
    if lay_topic:
        out["lay"] = f"is {lay_topic} of {wrong}{unit} allowed"
    return out


# -------------------------------------------------------------------- sampling

def sample_chunks(conn, n: int, seed: int) -> list[dict]:
    """Up to `n` retrievable chunks, stratified round-robin across
    COMPANY_STANDARD documents (one draw per document per round), seeded."""
    from app.standards import COMPANY_STANDARD
    rows = conn.execute(
        "SELECT c.id, c.document_id, c.filename, c.page_start, c.page_end,"
        " c.section, c.text FROM chunks c"
        " JOIN document_classification cl ON cl.document_id = c.document_id"
        " WHERE cl.document_role = ? AND c.retrievable = 1"
        " ORDER BY c.document_id, c.ordinal", (COMPANY_STANDARD,)).fetchall()
    by_doc: dict[str, list] = {}
    for r in rows:
        by_doc.setdefault(r["document_id"], []).append(r)
    rng = random.Random(seed)
    for bucket in by_doc.values():
        rng.shuffle(bucket)
    doc_ids = list(by_doc.keys())
    rng.shuffle(doc_ids)
    picked: list[dict] = []
    round_ = 0
    while len(picked) < n and any(by_doc.values()):
        for doc_id in doc_ids:
            if len(picked) >= n:
                break
            bucket = by_doc.get(doc_id) or []
            if round_ < len(bucket):
                picked.append(dict(bucket[round_]))
        round_ += 1
        if round_ > max((len(b) for b in by_doc.values()), default=0):
            break
    return picked


def find_present_items(conn, target: int, scan_cap: int, seed: int) -> tuple[list[dict], int]:
    """Scan stratified chunks (up to `scan_cap`) until `target` items with a
    matching requirement sentence are found, or the cap is hit. Returns
    (items, chunks_scanned) - scanning is a cheap regex pass, so this is far
    cheaper than pre-committing to one raw sample size and hoping."""
    chunk_rows = sample_chunks(conn, scan_cap, seed)
    items: list[dict] = []
    scanned = 0
    for row in chunk_rows:
        scanned += 1
        req = find_requirement(row["text"])
        if req:
            items.append({"chunk_id": row["id"], **req})
            if len(items) >= target:
                break
    return items, scanned


# --------------------------------------------------------------------- scoring

def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p10": None, "median": None, "p90": None, "max": None}
    s = sorted(values)
    def pct(p: float) -> float:
        idx = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
        return round(s[idx], 3)
    return {"min": round(s[0], 3), "p10": pct(0.10), "median": round(statistics.median(s), 3),
           "p90": pct(0.90), "max": round(s[-1], 3)}


def _retrieve(question: str, allowed_document_ids: frozenset) -> dict:
    from app import scores as score_mod
    from app import search
    hits = search.search(question, limit=20, allowed_document_ids=allowed_document_ids).get("hits") or []
    field = [h["rerank_score"] for h in hits if h.get("rerank_score") is not None]
    top = hits[0] if hits else None
    sep = None
    if len(field) >= 2:
        sep = round(float(score_mod.separation(field[0], field[1], field)), 4)
    return {"hits": hits, "top": top, "top_score": (top["rerank_score"] if top else None),
           "top5_scores": field[:5], "separation": sep}


def _lexical_signal(question: str, top_hit: dict | None, allowed_document_ids: frozenset) -> dict:
    from app import lexical
    if not top_hit:
        return {"ok": False, "covered": 0, "total": 0}
    try:
        res = lexical.assess(question, top_hit["text"], allowed_document_ids=allowed_document_ids)
        return {"ok": bool(res.get("ok")), "covered": len(res.get("covered") or []),
               "total": len(res.get("terms") or [])}
    except Exception:  # noqa: BLE001 - a scoring probe must never crash the run
        return {"ok": False, "covered": 0, "total": 0}


def _run_answer(question: str, allowed_document_ids: frozenset) -> dict:
    from app import answer as answer_mod
    result = answer_mod.answer(question, tier="extract", allowed_document_ids=allowed_document_ids)
    answer_type = result.get("answer_type")
    passages = result.get("answer_passages") or []
    answered = answer_type == "extract" and bool(passages)
    choice = result.get("condition_choice") or {}
    return {
        "answer_type": answer_type,
        "answered_chunk_id": passages[0].get("chunk_id") if answered else None,
        "answered_text": passages[0].get("text") if answered else None,
        # `mode` is "options" (every competing clause shown, none picked) or
        # "matched" (the clause that holds under the named condition answers
        # instead of a higher-ranked one) - None when no clause competed.
        "condition_mode": choice.get("mode") if answered else None,
        # ALL passages, not just the first - an "options" answer's correct
        # clause can be any of them, not only the lead.
        "answer_passages": [
            {"chunk_id": p.get("chunk_id"), "text": p.get("text")} for p in passages
        ] if answered else [],
    }


class JsonlLog:
    """Per-row score/id log - no question text, no passage text (CLAUDE.md
    rule 1 holds even though this stays local: keep the habit uniform)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("w", encoding="utf-8")

    def write(self, row: dict) -> None:
        self._fh.write(json.dumps(row, sort_keys=True) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def score_present(conn, item: dict, wording: str, question: str,
                  allowed_document_ids: frozenset, log: JsonlLog, item_id: int) -> dict:
    core = _retrieve(question, allowed_document_ids)
    lex = _lexical_signal(question, core["top"], allowed_document_ids)
    ans = _run_answer(question, allowed_document_ids)

    expected_score = next(
        (h["rerank_score"] for h in core["hits"] if h["chunk_id"] == item["chunk_id"]), None)
    top_is_expected = bool(core["top"] and core["top"]["chunk_id"] == item["chunk_id"])
    top_is_same_value = None
    if core["top"] and not top_is_expected:
        top_is_same_value = _states_value(core["top"]["text"], item["number"], item["unit"])
    top_is_right = bool(top_is_expected or top_is_same_value)

    # PLAN STEP 4: a "which clause applies" answer with mode == "options"
    # shows every competing clause, none picked for the reader - so "the
    # expected chunk was the lead passage" is the wrong question to ask it.
    # It is scored on whether ANY shown passage is the expected clause or
    # states the expected value, as its own outcome (correct-with-options),
    # never folded into "exact" or "same-value" - those two keep meaning
    # "the ONE passage returned was right", which an options answer does not
    # claim to be. `mode == "matched"` (a named condition picked a winner) is
    # scored exactly like an ordinary extract: unchanged below.
    options_mode = ans["condition_mode"] == "options"
    correct_with_options = False
    if options_mode:
        for p in ans["answer_passages"]:
            if p["chunk_id"] == item["chunk_id"]:
                correct_with_options = True
                break
            text = p["text"] or _chunk_text(conn, p["chunk_id"])
            if _states_value(text or "", item["number"], item["unit"]):
                correct_with_options = True
                break
        answered_exact = False
        answered_same_value = None
    else:
        answered_exact = bool(ans["answered_chunk_id"] == item["chunk_id"])
        answered_same_value = None
        if ans["answer_type"] == "extract" and ans["answered_chunk_id"] and not answered_exact:
            text = ans["answered_text"] or _chunk_text(conn, ans["answered_chunk_id"])
            answered_same_value = _states_value(text or "", item["number"], item["unit"])
    answered_right = bool(
        ans["answer_type"] == "extract"
        and (answered_exact or answered_same_value or correct_with_options))

    row = {
        "category": "present", "wording": wording, "item_id": item_id,
        "top_score": core["top_score"], "top5_scores": core["top5_scores"],
        "separation": core["separation"], "expected_score": expected_score,
        "top_is_expected": top_is_expected, "top_is_same_value": top_is_same_value,
        "top_is_right": top_is_right,
        "condition_mode": ans["condition_mode"], "correct_with_options": correct_with_options,
        "lexical_ok": lex["ok"], "lexical_covered": lex["covered"], "lexical_total": lex["total"],
        "answer_type": ans["answer_type"],
        "answered_exact": answered_exact, "answered_same_value": answered_same_value,
        "answered_right": answered_right,
        "answered_really_wrong": bool(ans["answer_type"] == "extract" and not answered_right),
    }
    log.write(row)
    return row


def score_wrong_value(item: dict, wrong_number: str, wording: str, question: str,
                      allowed_document_ids: frozenset, log: JsonlLog, item_id: int) -> dict:
    core = _retrieve(question, allowed_document_ids)
    lex = _lexical_signal(question, core["top"], allowed_document_ids)
    ans = _run_answer(question, allowed_document_ids)

    outcome = "refused"
    if ans["answer_type"] == "extract" and ans["answered_text"] is not None:
        text = ans["answered_text"]
        has_true = _states_value(text, item["number"], item["unit"])
        has_wrong = _states_value(text, wrong_number, item["unit"])
        if has_true:
            outcome = "corrected_with_evidence"
        elif has_wrong:
            outcome = "confident_wrong"
        else:
            outcome = "other_extract"

    row = {
        "category": "wrong_value", "wording": wording, "item_id": item_id,
        "top_score": core["top_score"], "top5_scores": core["top5_scores"],
        "separation": core["separation"],
        "lexical_ok": lex["ok"], "lexical_covered": lex["covered"], "lexical_total": lex["total"],
        "answer_type": ans["answer_type"], "outcome": outcome,
    }
    log.write(row)
    return row


def score_absent(term_id: int, wording: str, question: str,
                 allowed_document_ids: frozenset, log: JsonlLog) -> dict:
    core = _retrieve(question, allowed_document_ids)
    lex = _lexical_signal(question, core["top"], allowed_document_ids)
    ans = _run_answer(question, allowed_document_ids)

    row = {
        "category": "absent", "wording": wording, "item_id": f"absent-{term_id}",
        "top_score": core["top_score"], "top5_scores": core["top5_scores"],
        "separation": core["separation"],
        "lexical_ok": lex["ok"], "lexical_covered": lex["covered"], "lexical_total": lex["total"],
        "answer_type": ans["answer_type"],
    }
    log.write(row)
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--present", type=int, default=200,
                    help="target number of answer-present items")
    ap.add_argument("--scan-cap", type=int, default=20000,
                    help="max raw chunks to scan looking for --present matches")
    ap.add_argument("--seed", type=int, default=20260929)
    ap.add_argument("--log-path", type=str,
                    default=str(REPO / "gold" / "refusal_calibration_log.jsonl"))
    args = ap.parse_args(argv)

    from app import db, live_guard
    from app.config import settings

    live = Path(settings.db_path)
    if not live.is_file():
        print(f"STOP - no database at {live}.")
        return 1
    copy = live_guard.diagnostic_copy(live)
    print(f"Working on a disposable copy: {copy} (live file untouched)")
    settings.db_path = copy
    db.reset_connection()
    db.init_db()

    from app import keyword, search

    conn = db.connect()
    scope = search.every_document_id()
    reverse_glossary = _reverse_glossary()
    log = JsonlLog(Path(args.log_path))
    print(f"Per-row log: {args.log_path}")

    present_items, scanned = find_present_items(conn, args.present, args.scan_cap, args.seed)
    print(f"Chunks scanned: {scanned} (cap {args.scan_cap}) "
         f"-> present items found: {len(present_items)} (target {args.present})")

    absent_terms = []
    for term in ABSENT_CANDIDATES:
        n = keyword.term_occurrences(term, allowed_document_ids=scope)
        if n == 0:
            absent_terms.append(term)
    print(f"Absent-topic terms verified absent: {len(absent_terms)} of {len(ABSENT_CANDIDATES)} candidates")

    # -------------------------------------------------------------- run

    present_rows: list[dict] = []
    wrong_val_rows: list[dict] = []
    absent_rows: list[dict] = []

    for item_id, item in enumerate(present_items):
        questions = build_questions(item["topic"], item["comparator"], item["number"],
                                    item["unit"], reverse_glossary)
        for wording, q in questions.items():
            present_rows.append(score_present(conn, item, wording, q, scope, log, item_id))

        wrong_number = pick_wrong_number(item["number"], item["sentence"])
        wrong = build_wrong_value_questions(
            item["topic"], item["comparator"], item["number"], item["unit"],
            item["sentence"], reverse_glossary)
        if wrong and wrong_number is not None:
            for wording, q in wrong.items():
                wrong_val_rows.append(
                    score_wrong_value(item, wrong_number, wording, q, scope, log, item_id))

    for term_id, term in enumerate(absent_terms):
        questions = build_questions(term, "eq", "0", "", reverse_glossary)
        for wording, q in questions.items():
            absent_rows.append(score_absent(term_id, wording, q, scope, log))

    log.close()
    rows = present_rows + wrong_val_rows + absent_rows
    print(f"\nTotal questions scored: {len(rows)}")
    print(f"  present: {len(present_rows)}")
    print(f"  wrong_value: {len(wrong_val_rows)}")
    print(f"  absent: {len(absent_rows)}")

    # ----------------------------------------------------------- reporting

    print("\n" + "=" * 72)
    print("FALSE REFUSALS AT THE CURRENT FLOOR, BY WORDING (answer-present only)")
    print("=" * 72)
    for wording in WORDINGS:
        subset = [r for r in present_rows if r["wording"] == wording]
        if not subset:
            continue
        refused = sum(1 for r in subset if r["answer_type"] != "extract")
        print(f"  {wording:8s}  {refused} of {len(subset)} refused"
             f"  ({100 * refused / len(subset):.0f}%)")

    print("\n" + "=" * 72)
    print("PRESENT QUESTIONS: WHAT WAS ANSWERED "
         "(exact vs same-value vs correct-with-options vs really wrong)")
    print("=" * 72)
    n_present = len(present_rows)
    exact = sum(1 for r in present_rows if r["answered_exact"])
    same_value = sum(1 for r in present_rows if r["answered_same_value"])
    correct_with_options = sum(1 for r in present_rows if r["correct_with_options"])
    really_wrong = sum(1 for r in present_rows if r["answered_really_wrong"])
    refused_p = sum(1 for r in present_rows if r["answer_type"] != "extract")
    options_mode_n = sum(1 for r in present_rows if r["condition_mode"] == "options")
    matched_mode_n = sum(1 for r in present_rows if r["condition_mode"] == "matched")
    print(f"  answered, exact expected chunk:        {exact} of {n_present}")
    print(f"  answered, different chunk SAME value:  {same_value} of {n_present}")
    print(f"  answered, correct clause AMONG OPTIONS: {correct_with_options} of {n_present}")
    print(f"  answered, different chunk WRONG value: {really_wrong} of {n_present}  <- really wrong")
    print(f"  refused:                                {refused_p} of {n_present}")
    print(f"  condition_choice mode=options:          {options_mode_n} of {n_present}")
    print(f"  condition_choice mode=matched:          {matched_mode_n} of {n_present}")

    print("\n" + "=" * 72)
    print("WRONG-VALUE QUESTIONS: WHAT THE RETURNED PASSAGE ACTUALLY SAYS")
    print("=" * 72)
    n_wv = len(wrong_val_rows)
    for outcome, label in (
        ("confident_wrong", "confident wrong (passage has the fabricated number, not the true one)"),
        ("corrected_with_evidence", "corrected with evidence (passage has the TRUE number)"),
        ("other_extract", "answered, neither number in the passage"),
        ("refused", "refused"),
    ):
        n = sum(1 for r in wrong_val_rows if r["outcome"] == outcome)
        print(f"  {label}: {n} of {n_wv}")

    print("\n" + "=" * 72)
    print("ABSENT-TOPIC QUESTIONS ANSWERED - PER-QUESTION BREAKDOWN (counts/shapes only)")
    print("=" * 72)
    answered_absent = [r for r in absent_rows if r["answer_type"] == "extract"]
    print(f"  {len(answered_absent)} of {len(absent_rows)} absent-topic questions answered")
    for i, r in enumerate(answered_absent, 1):
        print(f"  #{i}: top_score={r['top_score']}  lexical_ok={r['lexical_ok']}  "
             f"shares {r['lexical_covered']} of {r['lexical_total']} distinctive terms")

    print("\n" + "=" * 72)
    print("SCORE DISTRIBUTIONS (rerank score of the TOP hit)")
    print("=" * 72)
    right_top = [r["top_score"] for r in present_rows if r["top_is_right"] and r["top_score"] is not None]
    wrong_top = [r["top_score"] for r in present_rows if not r["top_is_right"] and r["top_score"] is not None]
    absent_top = [r["top_score"] for r in absent_rows if r["top_score"] is not None]
    for label, values in (("right-top (exact OR same-value)", right_top),
                         ("wrong-top (different chunk, different value)", wrong_top),
                         ("absent (absent-topic questions)", absent_top)):
        p = _percentiles(values)
        print(f"  {label}: n={len(values)}  min={p['min']} p10={p['p10']} "
             f"median={p['median']} p90={p['p90']} max={p['max']}")

    print("\n" + "=" * 72)
    print("SCORE SWING ACROSS THE 4 WORDINGS (same expected chunk, present items only)")
    print("=" * 72)
    by_item: dict[int, list[float]] = {}
    for r in present_rows:
        if r["expected_score"] is not None:
            by_item.setdefault(r["item_id"], []).append(r["expected_score"])
    swings = [max(scores) - min(scores) for scores in by_item.values() if len(scores) >= 2]
    if swings:
        print(f"  n={len(swings)}  median swing={statistics.median(swings):.2f}  max swing={max(swings):.2f}")
    else:
        print("  no item had the expected chunk scored under 2+ wordings - no swing computed")

    print("\n" + "=" * 72)
    print("FLOOR SWEEP (candidate D: score >= floor AND lexical gate passes)")
    print("=" * 72)
    print(f"  {'floor':>6}  {'false_refusals':>15}  {'confident_wrong':>16}")
    total_rows = len(rows)
    floor = -8.0
    while floor <= 2.0 + 1e-9:
        fr = sum(1 for r in present_rows
                 if not (r["lexical_ok"] and r["top_score"] is not None and r["top_score"] >= floor))
        cw_absent = sum(1 for r in absent_rows
                        if r["lexical_ok"] and r["top_score"] is not None and r["top_score"] >= floor)
        cw_wrong = sum(1 for r in present_rows
                       if not r["top_is_right"] and r["lexical_ok"]
                       and r["top_score"] is not None and r["top_score"] >= floor)
        cw_val = sum(1 for r in wrong_val_rows
                    if r["outcome"] == "confident_wrong" and r["lexical_ok"]
                    and r["top_score"] is not None and r["top_score"] >= floor)
        print(f"  {floor:>6.1f}  {fr:>6} of {n_present:<7}"
             f"  {cw_absent + cw_wrong + cw_val:>6} of {total_rows:<7}")
        floor += 0.5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
