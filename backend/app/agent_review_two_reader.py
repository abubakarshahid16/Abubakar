"""The class "AI verdict, two readers agree" (owner order 13, point 10; behind `AGENT_REVIEW_TWO_READER_VERDICT_ENABLED`).

Pure functions and constants. No I/O, no model call, no settings read. The runner's step (`agent_review_two_reader_run`) asks
the second reader; this module says WHICH lines may be asked (`is_candidate`), what the stored second answer is
(`second_answer`), and whether the two answers earn the class (`agrees`) or contradict each other (`disagrees`). The class is
ALWAYS re-derived from the stored line (`agent_review_wording.classify` calls `agrees`), never trusted from a stored word.

THE RULE (all of it, each part checked by code):
  1. the first reader's line is a CANDIDATE (`is_candidate`): an AI "met" or "not met" that code did not prove (verdict Query),
     both quotes verified by code, the reason code "met" / "not_met" (never an absence), no hold of any kind, not a number
     rule (a number is compared by code, never by two readers), the rule is approved (owner, engineer or AI approved) or the
     item is a checklist item, the first reader's own second opinion (if one was asked) did not disagree.
  2. the SECOND reader answered the same question independently (its request is built from the item, the pages and the held
     rule text only: never the first reader's verdict, quotes or reasoning) with the SAME verdict;
  3. code verified the second reader's paper quote on the page it names and its clause quote in the held rule text (a "not
     met" needs a strong clause quote, as a Fail does everywhere else);
  4. SAME EVIDENCE: the two paper quotes are on the same page AND (the quotes overlap, or both readers name the same field
     label). Overlap: one quote lies wholly inside the other, or they share a run of three words in a row;
  5. no guard objects to EITHER answer: the "met" guard (`met_unsafe_why`) on both, and for both verdicts no deferral mark in
     either paper quote, no "not stated" wording, no condition word or note marker in the second reader's clause quote;
  6. the two models differ in family (`agent_run_second.models_differ`; an unknown name fails closed).
A line proven by code is never touched. The class is NEVER a Pass or a Fail.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import agent_review_verdict as verdict
from . import agent_run_second
from .reader_api import _fold

CLASS_TWO_READERS = "AI verdict, two readers agree"
WORD_MET, WORD_NOT_MET = "AI verdict: met", "AI verdict: not met"
WORDS = (WORD_MET, WORD_NOT_MET)
#: the second reader's own verdict words
V_MET, V_NOT_MET, V_CANNOT_TELL, V_NOT_APPLICABLE = (
    "met",
    "not met",
    "cannot tell",
    "not applicable",
)
SECOND_VERDICTS = (V_MET, V_NOT_MET, V_CANNOT_TELL, V_NOT_APPLICABLE)
FIELD = "two_reader"
#: at most this many candidate items in one second-reader call (the first reader's own bound, `MAX_BATCH`)
MAX_BATCH = 8
#: tokens asked for one second-reader call: a base and a part per item (an answer is quotes, one sentence, a verdict)
TOKENS_BASE, TOKENS_PER_ITEM, TOKENS_CAP = 400, 450, 6000
#: run-level reasons the step did not run or stopped (counts and codes only; the run records one)
OFF_LEAD_UNKNOWN = "lead_model_unknown_or_same_family"
OFF_CALL_FAILED = "call_failed"
OFF_CAP = "cap_refused"
OFF_RUN_STOPPED = "run_stopped"

_NOTE_OR_CONDITION = verdict.is_conditional


def verdict_word_of(ai: str | None) -> str | None:
    """The second-reader word of a first-reader verdict (Pass -> met, Fail -> not met)."""
    return {verdict.PASS: V_MET, verdict.FAIL: V_NOT_MET}.get(str(ai))


def _checks(line: Mapping) -> Mapping:
    q = line.get("quotes_checked")
    return q if isinstance(q, Mapping) else {}


def _holds(line: Mapping) -> bool:
    return any(
        (
            line.get("conditional_hold"),
            line.get("table_note_hold"),
            line.get("context_hold"),
            line.get("not_mentioned_hold"),
            line.get("unapproved_cap"),
            line.get("silence_query"),
            line.get("absence_code"),
            line.get("error"),
        )
    )


def is_candidate(line: Mapping) -> bool:
    """May the second reader be asked about this line (rule 1 above)? Pure on the stored line."""
    ai = line.get("ai_verdict")
    if ai not in (verdict.PASS, verdict.FAIL) or line.get("verdict") != verdict.QUERY:
        return False
    if line.get("rule_kind") in verdict.NUMBER_KINDS:
        return False
    if _holds(line) or line.get("rule_tier") == verdict.RULE_NOT_APPROVED:
        return False
    if not (line.get("checklist") is True or line.get("tier") in verdict.USABLE_TIERS):
        return False
    code = str(line.get("reason_code") or "")
    if code != ("met" if ai == verdict.PASS else "not_met"):
        return False
    q = _checks(line)
    if not (q.get("paper") and q.get("clause")):
        return False
    if ai == verdict.FAIL and not q.get("clause_strong"):
        return False
    second = line.get("second_opinion")
    if isinstance(second, Mapping) and second.get("agree") is False:
        return False
    if verdict.met_unsafe_why(line) is not None:
        return False
    if verdict.quote_defers(line.get("paper_quote")) or verdict.says_absent(line):
        return False
    return verdict._page_no(line.get("paper_page")) is not None


# ---------------------------------------------------------------- the stored second answer


def second_answer(
    answer: Mapping,
    *,
    ai: str | None,
    reason_code: str,
    checks: verdict.QuoteCheck,
    absent: bool,
    model: str,
    usd: float,
    two_sentences: Any = None,
) -> dict:
    """The stored form of the second reader's answer for one item (text of the model only inside its own quotes and one short
    reasoning; no new class of data). `verdict` is one of SECOND_VERDICTS; code decides it from the reader's verdict word and
    reason code together: only a Pass with reason "met" is "met" and only a Fail with reason "not_met" is "not met"."""
    if ai == verdict.PASS and reason_code == "met":
        word = V_MET
    elif ai == verdict.FAIL and reason_code == "not_met":
        word = V_NOT_MET
    elif ai == verdict.QUERY and reason_code == "not_applicable":
        word = V_NOT_APPLICABLE
    else:
        word = V_CANNOT_TELL
    reasoning = " ".join(str(answer.get("reasoning") or "").split())
    return {
        "verdict": word,
        "model": model,
        "reason_code": reason_code,
        "paper_quote": answer.get("paper_quote") or None,
        "paper_page": verdict._page_no(answer.get("paper_page")),
        "clause_quote": answer.get("clause_quote") or None,
        "field_label": str(answer.get("field_label") or "").strip() or None,
        "reasoning": (two_sentences(reasoning) if two_sentences else reasoning[:300])
        or None,
        "quotes_checked": checks.to_json(),
        "says_absent": bool(absent),
        "usd": round(float(usd), 6),
    }


# ---------------------------------------------------------------- same evidence


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: Any) -> list[str]:
    return _TOKEN.findall(_fold(str(text or "")))


def quotes_overlap(a: Any, b: Any) -> bool:
    """One quote lies wholly inside the other (folded), or they share a run of three words in a row."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    n = len(short)
    runs = {tuple(long_[i : i + n]) for i in range(len(long_) - n + 1)}
    if tuple(short) in runs:
        return True
    if len(short) < 3:
        return False
    grams = {tuple(long_[i : i + 3]) for i in range(len(long_) - 2)}
    return any(tuple(short[i : i + 3]) in grams for i in range(len(short) - 2))


def same_label(a: Any, b: Any) -> bool:
    fa, fb = _fold(str(a or "")).strip(), _fold(str(b or "")).strip()
    return bool(fa) and fa == fb


def same_evidence(line: Mapping, second: Mapping) -> bool:
    """Rule 4: the same page, and overlapping quotes or the same field label."""
    p1, p2 = (
        verdict._page_no(line.get("paper_page")),
        verdict._page_no(second.get("paper_page")),
    )
    if p1 is None or p1 != p2:
        return False
    return quotes_overlap(
        line.get("paper_quote"), second.get("paper_quote")
    ) or same_label(line.get("field_label_ai"), second.get("field_label"))


# ---------------------------------------------------------------- the decision


def stored(line: Mapping) -> Mapping | None:
    got = line.get(FIELD)
    return got if isinstance(got, Mapping) else None


def _guards_ok(line: Mapping, second: Mapping, ai: str) -> bool:
    """Rule 5 on the SECOND reader's answer (the first reader's was checked by `is_candidate`)."""
    q = (
        second.get("quotes_checked")
        if isinstance(second.get("quotes_checked"), Mapping)
        else {}
    )
    if second.get("says_absent") or verdict.quote_defers(second.get("paper_quote")):
        return False
    if ai == verdict.PASS:
        probe = {
            "ai_verdict": verdict.PASS,
            "verdict": verdict.QUERY,
            "quotes_checked": q,
            "paper_quote": second.get("paper_quote"),
            "field_label_ai": line.get("field_label_ai") or second.get("field_label"),
            "field": line.get("field"),
            "field_roles": line.get("field_roles"),
            "not_mentioned_hold": bool(second.get("says_absent")),
            "second_opinion": None,
        }
        return verdict.met_unsafe_why(probe) is None
    clause = second.get("clause_quote")
    return not (_NOTE_OR_CONDITION(clause) or verdict.is_note_start(clause))


def agrees(line: Mapping) -> bool:
    """True only when the whole rule above holds, read from the stored line alone."""
    second = stored(line)
    if second is None or not is_candidate(line):
        return False
    ai = str(line.get("ai_verdict"))
    if second.get("verdict") != verdict_word_of(ai):
        return False
    q = (
        second.get("quotes_checked")
        if isinstance(second.get("quotes_checked"), Mapping)
        else {}
    )
    if not (q.get("paper") and q.get("clause")):
        return False
    if ai == verdict.FAIL and not q.get("clause_strong"):
        return False
    if str(second.get("reason_code") or "") != (
        "met" if ai == verdict.PASS else "not_met"
    ):
        return False
    if not agent_run_second.models_differ(
        [str(line.get("model") or "")], second.get("model")
    ):
        return False
    if not same_evidence(line, second):
        return False
    return _guards_ok(line, second, ai)


def disagrees(line: Mapping) -> bool:
    """The second reader reached the OPPOSITE verdict (met against not met) on a line the first reader could not get proven."""
    second = stored(line)
    if second is None:
        return False
    ai = line.get("ai_verdict")
    if ai not in (verdict.PASS, verdict.FAIL) or line.get("verdict") != verdict.QUERY:
        return False
    other = V_NOT_MET if ai == verdict.PASS else V_MET
    return second.get("verdict") == other


def word_of(line: Mapping) -> str:
    return WORD_MET if line.get("ai_verdict") == verdict.PASS else WORD_NOT_MET


def stats_template() -> dict:
    """The run-level record of the step (counts and one code; no text). `off` is the code that switched the step off."""
    return {
        "enabled": False,
        "candidates": 0,
        "asked": 0,
        "calls": 0,
        "agreed": 0,
        "disagreed": 0,
        "unconfirmed": 0,
        "off": None,
        "usd": 0.0,
    }
