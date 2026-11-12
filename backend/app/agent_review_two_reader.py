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

from collections.abc import Mapping
from typing import Any

from . import agent_review_verdict as verdict
from . import agent_run_second
from .reader_api import _fold

CLASS_TWO_READERS = "AI verdict, two readers agree"
WORD_MET, WORD_NOT_MET = "AI verdict: met", "AI verdict: not met"
#: ABSENCE VERDICT (separate switch `AGENT_REVIEW_TWO_READER_ABSENCE_ENABLED`): two readers and code found no value anywhere.
WORD_NOT_STATED = "AI verdict: not stated"
WORDS = (WORD_MET, WORD_NOT_MET, WORD_NOT_STATED)
ABSENCE_FIELD = "two_reader_absence"
#: what the line's reason says, and only what was established (no bare "the paper does not state")
ABSENCE_WHY = "Two AI readers each read every page and found no value for this; the reviewer's code found none either"
#: the second reader's absence answers
A_NOT_STATED, A_FOUND, A_CANNOT_TELL = "not stated", "found a value", "cannot tell"
#: the most paper text (characters of every page together) sent whole to the absence reader; a longer paper has no candidate
ABSENCE_MAX_PAGE_CHARS = 60_000
OFF_PAPER_TOO_LONG = "paper_over_size_limit"
#: the second reader's own verdict words
V_MET, V_NOT_MET, V_CANNOT_TELL, V_NOT_APPLICABLE = (
    "met",
    "not met",
    "cannot tell",
    "not applicable",
)
#: the second reader's answer "this rule needs a drawing or a calculation" (the closed reason code needs_drawing_or_calc)
V_NEEDS = "needs a drawing or a calculation"
#: OTHER-PAPER class (own switch `AGENT_REVIEW_TWO_READER_OTHER_PAPER_ENABLED`): not a decision, not a Query, not "Not applicable"
CLASS_NOT_CHECKED_HERE = "Not checked on this paper"
WORD_NEEDS = "Needs a drawing or a calculation"
OTHER_FIELD = "two_reader_other"
OTHER_WHY = "Two AI readers each found that this rule cannot be checked on a datasheet: it needs a drawing or a calculation"
NEEDS_CODE = "needs_drawing_or_calc"
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
    if verdict.quote_is_label_only(
        line
    ):  # a header with no value is no evidence for "met" or for "not met"
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
    spans: Mapping | None = None,
    base: Mapping | None = None,
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
    elif ai == verdict.QUERY and reason_code == NEEDS_CODE:
        word = V_NEEDS
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
        "spans": dict(spans) if spans else None,
        "base": dict(base)
        if base
        else None,  # what the line was before this step: its class and word
        "usd": round(float(usd), 6),
    }


# ---------------------------------------------------------------- same evidence


def _spans_in(page_text: Any, quote: Any) -> list[list[int]]:
    """Every place the (folded) quote stands in the (folded) page text: [[start, end), ...]."""
    fq, fp = _fold(str(quote or "")).strip(), _fold(str(page_text or ""))
    out, i = [], fp.find(fq) if fq else -1
    while i >= 0:
        out.append([i, i + len(fq)])
        i = fp.find(fq, i + 1)
    return out


def span_in(page_text: Any, quote: Any) -> list[int] | None:
    """The first place the quote stands in the page text, else None."""
    got = _spans_in(page_text, quote)
    return got[0] if got else None


def evidence_spans(page_text: Any, first_quote: Any, second_quote: Any) -> dict | None:
    """The two verified quote spans on one page, for `same_evidence`; None when either quote is not on the page. A quote that stands
    in more than one place is pinned only when the code need not choose: the OTHER quote stands in exactly one place and exactly one
    occurrence of the repeated quote lies inside or across it. Otherwise the spans are None and `why` says so in plain words (the
    line then stays what it was)."""
    firsts, seconds = (
        _spans_in(page_text, first_quote),
        _spans_in(page_text, second_quote),
    )
    if not (firsts and seconds):
        return None
    if len(firsts) == 1 and len(seconds) == 1:
        return {"first": firsts[0], "second": seconds[0]}
    one, many = (firsts, seconds) if len(firsts) == 1 else (seconds, firsts)
    if len(one) == 1 and len(many) > 1:
        meet = [m for m in many if one[0][0] < m[1] and m[0] < one[0][1]]
        if len(meet) == 1:
            return (
                {"first": one[0], "second": meet[0]}
                if one is firsts
                else {"first": meet[0], "second": one[0]}
            )
    return {
        "first": None,
        "second": None,
        "why": "a quote stands in more than one place on the page and the code cannot tell which one the other reader meant",
    }


def _figure_keys(text: Any) -> tuple[frozenset, frozenset]:
    """The numbers a quote states and the units beside them, by the repo's own number and unit code (`numparse`, the figure rule
    of `agent_review_verdict.figures_in`); nothing new is parsed here."""
    from . import agent_bind, numparse

    units = set()
    for fig in verdict.figures_in(text):
        m = agent_bind._NUMBER_UNIT.search(fig)
        if m:
            units.add(m.group(1).lower())
    return frozenset(numparse.number_keys(str(text or ""))), frozenset(units)


def same_evidence(line: Mapping, second: Mapping) -> bool:
    """THE one rule (general, no field word): the two verified quotes point at the SAME PLACE and the SAME VALUE. Same page; their
    verified spans in the page text intersect (or one holds the other); and the numbers and units the two quotes state are equal.
    A reader's own field label is never evidence, and three shared words are not a place. Where code cannot establish this (no
    stored spans) it is False and the line stays what it was."""
    p1, p2 = (
        verdict._page_no(line.get("paper_page")),
        verdict._page_no(second.get("paper_page")),
    )
    spans = second.get("spans") if isinstance(second.get("spans"), Mapping) else {}
    a, b = spans.get("first"), spans.get("second")
    if p1 is None or p1 != p2 or not (_is_span(a) and _is_span(b)):
        return False
    if not (a[0] < b[1] and b[0] < a[1]):
        return False
    return _figure_keys(line.get("paper_quote")) == _figure_keys(
        second.get("paper_quote")
    )


def _is_span(v: Any) -> bool:
    return (
        isinstance(v, (list, tuple))
        and len(v) == 2
        and all(isinstance(x, int) for x in v)
        and v[0] < v[1]
    )


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
    label_probe = {
        "paper_quote": second.get("paper_quote"),
        "field_label_ai": line.get("field_label_ai") or second.get("field_label"),
        "field": line.get("field"),
        "field_roles": line.get("field_roles"),
    }
    if verdict.quote_is_label_only(
        label_probe
    ):  # the second reader quoted only a header
        return False
    if (
        ai == verdict.FAIL
    ):  # the Fail-side guards (F1, F3, F4) are the ones a code Fail passes: run by the runner, stored here
        guards = second.get("fail_guards")
        if not (isinstance(guards, Mapping) and guards.get("ok") is True):
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
        "skipped": 0,
        "off": None,
        "usd": 0.0,
    }


# ---------------------------------------------------------------- the absence verdict


def stored_absence(line: Mapping) -> Mapping | None:
    got = line.get(ABSENCE_FIELD)
    return got if isinstance(got, Mapping) else None


def is_absence_candidate(line: Mapping) -> bool:
    """May the second reader be asked whether the paper states a value at all (pure on the stored line)? The first reader said
    the paper should state it and does not (reason "absent", the pages it searched named), nothing was proven, no hold, a held
    RULE (a checklist item has no stored obligation: `agent_review_absence`), approved, with a verified strong clause quote."""
    if line.get("ai_verdict") != verdict.FAIL or line.get("verdict") != verdict.QUERY:
        return False
    if line.get("reason_code") != "absent" or not line.get("pages_searched"):
        return False
    if line.get("source") != "rule" or line.get("checklist") is True or _holds(line):
        return False
    if (
        line.get("rule_tier") == verdict.RULE_NOT_APPROVED
        or line.get("tier") not in verdict.USABLE_TIERS
    ):
        return False
    q = _checks(line)
    return bool(q.get("clause") and q.get("clause_strong"))


def absence_answer(
    *, found: Any, quote: Any, page: Any, clause_quote: Any, paper_ok: bool, clause_ok: bool, strong: bool,
    open_: bool, model: str, usd: float, code_search: Mapping, pages_total: int,
    first_pages: Any = (), second_pages: Any = (), base: Mapping | None = None,
) -> dict:  # fmt: skip
    """The stored absence answer of the second reader. `verdict`: found a value (its quote verified on its page, not a deferral),
    not stated (it says no value anywhere and its clause quote is verified), else cannot tell. `first_pages` / `second_pages`: the
    pages each reader was given (the first reader's searched pages, which are always pages it was sent; every page for the second)."""
    if found is True and paper_ok and not verdict.quote_defers(quote):
        word = A_FOUND
    elif found is False and not open_ and clause_ok and strong:
        word = A_NOT_STATED
    else:
        word = A_CANNOT_TELL
    return {
        "verdict": word, "model": model, "paper_quote": quote or None, "paper_page": verdict._page_no(page),
        "clause_quote": clause_quote or None,
        "quotes_checked": {"paper": bool(paper_ok), "clause": bool(clause_ok), "clause_strong": bool(strong), "both": bool(paper_ok and clause_ok)},
        "code_search": dict(code_search), "pages_total": int(pages_total),
        "first_pages": sorted({int(p) for p in first_pages or ()}), "second_pages": sorted({int(p) for p in second_pages or ()}),
        "base": dict(base) if base else None, "usd": round(float(usd), 6),
    }  # fmt: skip


def absence_agrees(line: Mapping) -> bool:
    """The absence verdict: the first reader said absent, the second reader (another family) read EVERY page and found no value,
    its clause quote is verified and strong, and the code's own absence search (`agent_review_absence.prove`) found nothing on any
    page, every page being read. Read from the stored line alone."""
    rec = stored_absence(line)
    if (
        rec is None
        or not is_absence_candidate(line)
        or rec.get("verdict") != A_NOT_STATED
    ):
        return False
    q = (
        rec.get("quotes_checked")
        if isinstance(rec.get("quotes_checked"), Mapping)
        else {}
    )
    if not (q.get("clause") and q.get("clause_strong")):
        return False
    code = rec.get("code_search") if isinstance(rec.get("code_search"), Mapping) else {}
    total = rec.get("pages_total")
    if not (
        code.get("proven") is True
        and isinstance(total, int)
        and total >= 1
        and code.get("pages_checked") == total
    ):
        return False
    every = list(
        range(1, total + 1)
    )  # "each read every page" is true only when the stored lists prove it
    if rec.get("first_pages") != every or rec.get("second_pages") != every:
        return False
    return agent_run_second.models_differ(
        [str(line.get("model") or "")], rec.get("model")
    )


def absence_disagrees(line: Mapping) -> bool:
    """The second reader found a value and quoted it, and code verified the quote on the page: two readers disagree."""
    rec = stored_absence(line)
    if (
        rec is None
        or line.get("ai_verdict") != verdict.FAIL
        or line.get("verdict") != verdict.QUERY
    ):
        return False
    q = (
        rec.get("quotes_checked")
        if isinstance(rec.get("quotes_checked"), Mapping)
        else {}
    )
    return rec.get("verdict") == A_FOUND and bool(q.get("paper"))


def class_of(line: Mapping, reason: str) -> dict | None:
    """The class entry of a line that earned it (both rules above), else None: the word and the reason shown."""
    if agrees(line):
        return {
            "verdict_label": word_of(line),
            "verdict_class": CLASS_TWO_READERS,
            "not_proven_reason": reason,
        }
    if absence_agrees(line):
        return {
            "verdict_label": WORD_NOT_STATED,
            "verdict_class": CLASS_TWO_READERS,
            "not_proven_reason": ABSENCE_WHY,
        }
    return None


# ---------------------------------------------------------------- the other-paper class


def stored_other(line: Mapping) -> Mapping | None:
    got = line.get(OTHER_FIELD)
    return got if isinstance(got, Mapping) else None


def independent(line: Mapping) -> Mapping | None:
    """The independent second reader's stored answer of whichever step asked it (value, absence or other-paper)."""
    return stored(line) or stored_absence(line) or stored_other(line)


def is_other_candidate(line: Mapping) -> bool:
    """The first reader's own answer says the rule cannot be checked on this paper: its stored CLOSED reason code is
    `needs_drawing_or_calc` (`agent_review_request.REASON_CODES`, read by `reason_of`; never free text), no verdict, no error, a
    verified clause quote, an approved rule or a checklist item."""
    if line.get("reason_code") != NEEDS_CODE or line.get("verdict") != verdict.QUERY:
        return False
    if line.get("ai_verdict") not in (verdict.QUERY, None) or _holds(line):
        return False
    if line.get("rule_tier") == verdict.RULE_NOT_APPROVED:
        return False
    if not (line.get("checklist") is True or line.get("tier") in verdict.USABLE_TIERS):
        return False
    return bool(_checks(line).get("clause"))


def other_agrees(line: Mapping) -> bool:
    """Both readers say it needs a drawing or a calculation, both clause quotes verified by code, the models differ."""
    rec = stored_other(line)
    if rec is None or not is_other_candidate(line) or rec.get("verdict") != V_NEEDS:
        return False
    q = (
        rec.get("quotes_checked")
        if isinstance(rec.get("quotes_checked"), Mapping)
        else {}
    )
    if not q.get("clause"):
        return False
    return agent_run_second.models_differ(
        [str(line.get("model") or "")], rec.get("model")
    )


def other_disagrees(line: Mapping) -> bool:
    """The second reader gave a verdict (met or not met) and code verified both of its quotes: a disagreement."""
    rec = stored_other(line)
    if (
        rec is None
        or line.get("verdict") != verdict.QUERY
        or line.get("reason_code") != NEEDS_CODE
    ):
        return False
    q = (
        rec.get("quotes_checked")
        if isinstance(rec.get("quotes_checked"), Mapping)
        else {}
    )
    return rec.get("verdict") in (V_MET, V_NOT_MET) and bool(
        q.get("paper") and q.get("clause")
    )


def other_class(line: Mapping) -> dict | None:
    """The class "Not checked on this paper" entry of a line both readers say needs a drawing or a calculation, else None."""
    if other_agrees(line):
        return {
            "verdict_label": WORD_NEEDS,
            "verdict_class": CLASS_NOT_CHECKED_HERE,
            "not_proven_reason": OTHER_WHY,
        }
    return None
