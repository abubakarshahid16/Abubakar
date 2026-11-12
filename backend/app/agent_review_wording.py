"""The words of a verdict (owner decision 2, 11 Nov 2026). Pure functions, no I/O, no model call.

Proven by code -> "Pass" / "Fail" (the gate's own Pass or Fail: both quotes verified by code, figures compared by code, or a
second model agreeing on verified quotes). An AI verdict the gate did not let stand -> "AI thinks: met" / "AI thinks: not
met", class "AI opinion, engineer to confirm", with the gate's reason. A rule that is not yet AI approved -> class "AI
opinion, rule not yet approved". No AI verdict -> "Query for the engineer". The classes are counted apart; a line of an
AI class is never a Pass or a Fail, never on the contractor copy.

`final_cap` is the ONE function every line passes before any output is written (lines, both xlsx copies, counts, rules-used):
it takes the line AND its item's CURRENT tier and applies the cap and these words. A stored Pass or Fail of a rule that is now
not approved can never stay Pass or Fail.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping

from . import agent_review_two_reader as two_reader
from .agent_review_verdict import (
    AI_TIER,
    BY_ABSENCE,
    BY_CODE,
    BY_ENGINEER,
    DISAGREE_WHY,
    FAIL,
    NOT_A_RULE,
    PASS,
    QUERY,
    RULE_NOT_APPROVED,
    SILENCE_WHY,
    TIER_NOT_APPROVED,
    TIER_NOT_ESTABLISHED,
    USABLE_TIERS,
    hold_silence,
    item_tier,
    met_unsafe_why,
)

CLASS_PROVEN = "Proven by code"
CLASS_OPINION = "AI opinion, engineer to confirm"
CLASS_QUERY = "Query for the engineer"
CLASS_UNAPPROVED = "AI opinion, rule not yet approved"
CLASS_NOT_APPLICABLE = "Not applicable"
CLASS_NOT_REVIEWED = "Not reviewed"
CLASS_TWO_READERS = two_reader.CLASS_TWO_READERS
WORD_NOT_REVIEWED = "Not reviewed"
ERROR_WORDS = {"stop_max_tokens": "no answer from the AI: answer cut off"}
CLASSES = (
    CLASS_PROVEN,
    CLASS_TWO_READERS,
    CLASS_OPINION,
    CLASS_UNAPPROVED,
    CLASS_QUERY,
    CLASS_NOT_APPLICABLE,
    CLASS_NOT_REVIEWED,
)
THINKS_MET, THINKS_NOT_MET = "AI thinks: met", "AI thinks: not met"
WORD_QUERY = "Query for the engineer"
RECOMMENDATION = "recommendation"
KEYS = ("verdict_label", "verdict_class", "not_proven_reason", "recommendation")


REREAD_NO_VALUE_WHY = "two AI readers found no value for this in the stored text of the pages they were given"  # C4: said only after a second reader answered
REREAD_QUOTE_NOT_FOUND_WHY = "a second AI reader pointed to text that code did not accept as a quote from the stored page text; it was not used"
REREAD_NOT_CONFIRMED_WHY = "one AI reader pointed to text on page {page}, the other AI reader did not confirm it"
REREAD_OUTCOME_WHY = {
    "no_value": REREAD_NO_VALUE_WHY,
    "quote_not_found": REREAD_QUOTE_NOT_FOUND_WHY,
}
#: Owner, 12 Nov 2026: "Proven Pass always means the code compared a value." A Pass whose line holds no passed code comparison is
#: not proven; it is "AI verdict, two readers agree" (internal copy only) when the quotes and the second reader hold, else "AI thinks".
NO_COMPARISON_WHY = "the code compared no value on this line"
NO_PROOF_WHY = "the code compared no value on this line and proved no absence"
ONE_READER = "One AI reader's view, not confirmed: "
SECOND_DISAGREED = "The second AI reader disagreed. "


def _moved_reason(line: Mapping, unsafe: str) -> str:
    """THE text the engineer reads for a "met" the guard made a Query (screen reason, workbook comment and verdict cells):
    the guard's reason first; for two readers who disagree, a plain sentence saying the second reader disagreed; then the
    first reader's own words ONLY marked as one reader's view that is not confirmed. Never the line's conclusion."""
    out = unsafe + "."
    if unsafe == DISAGREE_WHY:
        out += " " + SECOND_DISAGREED.strip()
    view = " ".join(str(line.get("comment") or line.get("reasoning") or "").split())
    return f"{out} {ONE_READER}{view[:400]}" if view else out


def _early(line: Mapping, unapproved: bool, why: str) -> dict | None:
    """Steps 1, 2 and 2b of `classify`: the AI gave no answer (Not reviewed); a silent paper (Query); an AI "met" whose paper
    defers the value or whose quotes code could not verify (Query, N9). None when none applies."""
    if line.get(
        "error"
    ):  # 1. not reviewed, never a Query about the paper, whatever the rule's tier
        return {
            "verdict_label": WORD_NOT_REVIEWED,
            "verdict_class": CLASS_NOT_REVIEWED,
            "not_proven_reason": ERROR_WORDS.get(
                str(line["error"]), f"no answer from the AI: {line['error']}"
            ),
        }
    also = "; the rule is also not AI approved" if unapproved else ""
    if line.get(
        "silence_query"
    ):  # 2. the owner's rule: a silent paper is a Query, never "not met"
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": SILENCE_WHY + also,
        }
    if unsafe := met_unsafe_why(
        line
    ):  # 2b. N9: the guard's reason leads; one reader's view follows, marked
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": _moved_reason(line, unsafe)
            + (f"; {why}" if unapproved else ""),
        }
    if got := two_reader.other_class(
        line
    ):  # 2d. both readers: needs a drawing or a calculation, not checked here
        return got
    if (
        two_reader.disagrees(line)
        or two_reader.absence_disagrees(line)
        or two_reader.other_disagrees(line)
    ):  # 2c. the independent second reader reached the opposite verdict: a Query
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": DISAGREE_WHY,
        }
    return None


def classify(line: Mapping) -> dict:
    """verdict_label, verdict_class, not_proven_reason (None when proven) for one line.

    THE ORDER at the exit (the first that applies wins): 1. Not reviewed (the AI gave no answer); 2. silence (a non-datasheet
    paper that is silent: Query, and when the rule is also not AI approved the reason says both); 3. the cap of a rule that is
    not AI approved; 4. proven Pass / Fail, then the AI opinions, then Query."""
    line = demote_unproven(
        line
    )  # owner, 12 Nov 2026: a proven Pass is one the code compared; here too, not only at the exit
    verdict, ai = line.get("verdict"), line.get("ai_verdict")
    unapproved = line.get("rule_tier") == RULE_NOT_APPROVED
    why = f"the rule is not AI approved: {line.get('rule_unapproved_why') or 'not agreed'}"
    if early := _early(
        line, unapproved, why
    ):  # 1. no answer, 2. silence, 2b. an unsafe "met"
        return early
    if unapproved:  # 3. never proven, whatever the stored verdict says
        if ai in (PASS, FAIL):
            return {
                "verdict_label": THINKS_MET if ai == PASS else THINKS_NOT_MET,
                "verdict_class": CLASS_UNAPPROVED,
                "not_proven_reason": why,
            }
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": why,
        }
    if verdict in (PASS, FAIL):  # 4. proven, then the AI opinions, then Query
        return {
            "verdict_label": verdict,
            "verdict_class": CLASS_PROVEN,
            "not_proven_reason": None,
        }
    if (
        verdict == QUERY and line.get("reason_code") == "not_applicable"
    ):  # the AI judged the rule not for this paper
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_NOT_APPLICABLE,
            "not_proven_reason": "the AI judged the rule not applicable to this paper",
        }
    held = (
        line.get("conditional_hold")
        or line.get("table_note_hold")
        or line.get("context_hold")
    )
    if held and ai != FAIL:  # a held code Fail: no AI opinion to show
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": str(line.get("why") or ""),
        }
    if verdict == QUERY and ai in (PASS, FAIL) and not line.get("error"):
        reason = str(
            line.get("why") or line.get("reason_code") or "the gate did not accept it"
        ).strip()
        if (
            got := two_reader.class_of(line, reason)
        ):  # 4b. two independent readers (value or absence verdict), every quote verified, no guard
            return got
        return {
            "verdict_label": THINKS_MET if ai == PASS else THINKS_NOT_MET,
            "verdict_class": CLASS_OPINION,
            "not_proven_reason": reason,
        }
    return {
        "verdict_label": WORD_QUERY,
        "verdict_class": CLASS_QUERY,
        "not_proven_reason": str(line.get("why") or line.get("reason_code") or "")
        or None,
    }


def apply(line: Mapping) -> dict:
    """The line with the words added (idempotent). A 'should' rule is marked a recommendation. A line the second reader
    re-read says what the code saw after its reason (`reread.outcome`: no_value, quote_not_found or not_confirmed); a failed
    re-read and a recovered line say nothing."""
    out = {**line, **classify(line), RECOMMENDATION: line.get("rule_kind") == "advice"}
    reread = line.get("reread")
    outcome = reread.get("outcome") if isinstance(reread, Mapping) else None
    words = (
        REREAD_NOT_CONFIRMED_WHY.format(page=reread.get("page"))
        if outcome == "not_confirmed"
        else REREAD_OUTCOME_WHY.get(outcome)
    )
    if words and out["verdict_class"] in (CLASS_QUERY, CLASS_OPINION, CLASS_UNAPPROVED):
        base = str(out.get("not_proven_reason") or "").rstrip(" .;")
        out["not_proven_reason"] = f"{base}; {words}" if base else words
    return out


def code_compared(line: Mapping) -> bool:
    """The code itself compared a value and it passed: the number path (`number_verdict`: a decided `compare_number`, decided by code)."""
    cmp = line.get("compare")
    return (
        line.get("decided_by") == BY_CODE
        and isinstance(cmp, Mapping)
        and cmp.get("decided") is True
        and cmp.get("verdict") == "meets"
    )


def code_proved_fail(line: Mapping) -> bool:
    """The code itself proved the Fail: a decided `compare_number` that did not meet (decided by code), or the code's own absence
    proof (`BY_ABSENCE`: every page read, no field words on any page, a strong verified clause quote)."""
    cmp = line.get("compare")
    by_value = (
        line.get("decided_by") == BY_CODE
        and isinstance(cmp, Mapping)
        and cmp.get("decided") is True
        and cmp.get("verdict") == "does_not_meet"
    )
    return by_value or line.get("decided_by") == BY_ABSENCE


def demote_unproven(line: Mapping) -> dict:
    """The owner's limit (12 Nov 2026, applied to Fail by the lead, to be confirmed by the owner): "Proven by code" means the code
    compared a value, or proved an absence. A Pass with no passed code comparison, and a Fail with neither a failed comparison nor
    the absence proof, is a Query that keeps the AI's verdict (`textual_pass` / `textual_fail`: it stood on two verified quotes and a
    second reader), classified by `classify`. Never touches a Query or what the code proved. Idempotent."""
    out = dict(line)
    if out.get("verdict") == PASS and not code_compared(out):
        out.update(
            verdict=QUERY,
            decided_by=BY_ENGINEER,
            why=NO_COMPARISON_WHY,
            textual_pass=True,
        )
    elif out.get("verdict") == FAIL and not code_proved_fail(out):
        out.update(
            verdict=QUERY, decided_by=BY_ENGINEER, why=NO_PROOF_WHY, textual_fail=True
        )
    return out


demote_uncompared_pass = demote_unproven  # the name of the first version (Pass only)


def final_cap(
    line: Mapping,
    item: Mapping | None,
    lookup: Callable[[Mapping], str | None] | None = None,
    skill_ids: Collection[str] | None = None,
    paper_kind: str | None = None,
) -> dict:
    """THE exit cap. The line with its item's CURRENT tier written on it (`tier`), the cap applied and the words added.

    * the tier is `item_tier(item, lookup)`: re-derived through `lookup` when the item carries none; a rule item whose tier
      cannot be established is NOT approved;
    * a rule that is not approved: a Pass or Fail becomes a Query (`unapproved_cap`), `rule_tier` is set so every writer
      files it as "AI opinion, rule not yet approved"; a line stored by an earlier run keeps nothing it does not now earn;
    * a rule that is approved: a stale `rule_tier` marker of an earlier run is dropped (a capped Query stays a Query);
    * a checklist item has no tier; its line is unchanged.
    * a line that rests on absence (`reason_code` absent / sheet_silent) on a paper kind where silence is a Query (every kind
      but a datasheet; an unknown or missing `paper_kind` counts as silent) is a Query: `hold_silence`.
    Idempotent. Only makes a line less confident."""
    out = hold_silence(line, paper_kind)
    tier = item_tier(item, lookup, skill_ids)
    if tier == NOT_A_RULE:
        out.pop("rule_tier", None)
        out["tier"] = None
        out["checklist"] = True
        return apply(demote_unproven(out))
    out["checklist"] = False
    if tier == RULE_NOT_APPROVED:
        out["rule_tier"] = RULE_NOT_APPROVED
        out["tier"] = TIER_NOT_APPROVED
        why = (item or {}).get("rule_unapproved_why") or out.get("rule_unapproved_why")
        out["rule_unapproved_why"] = why or TIER_NOT_ESTABLISHED
        if out.get("verdict") in (PASS, FAIL):
            out.update(
                verdict=QUERY,
                decided_by=BY_ENGINEER,
                why=f"the rule is not AI approved: {out['rule_unapproved_why']}",
                unapproved_cap=True,
            )
        return apply(out)
    out.pop("rule_tier", None)
    out.pop("rule_unapproved_why", None)
    out["tier"] = tier
    return apply(demote_unproven(out))


def final_cap_all(
    lines: Iterable[Mapping],
    items_by_id: Mapping[str, Mapping],
    lookup: Callable[[Mapping], str | None] | None = None,
    skill_ids: Collection[str] | None = None,
    paper_kind: str | None = None,
) -> list[dict]:
    """`final_cap` for every line, each with its own item (found by `item_id`). A stored line with NO item is a rule line whose
    tier is not established: capped, whatever source the line claims."""
    return [
        final_cap(
            ln, items_by_id.get(str(ln.get("item_id"))), lookup, skill_ids, paper_kind
        )
        for ln in lines
    ]


def writer_refusal(line: Mapping) -> str | None:
    """Why a CRS writer must refuse this line, or None. A Pass or Fail needs: a checklist line, or a rule line whose tier is
    owner, engineer or AI approved (written by `final_cap`). Defence in depth: nothing else may be written as Pass/Fail."""
    if line.get("verdict") not in (PASS, FAIL):
        return None
    if line.get("tier") in USABLE_TIERS:
        return None
    if (
        line.get("checklist") is True and line.get("tier") is None
    ):  # set only by final_cap for a real checklist item
        return None
    return f"a {line.get('verdict')} line may not be written without an approved rule tier (tier={line.get('tier')!r})"


def is_opinion(line: Mapping) -> bool:
    return line.get("verdict_class") in (CLASS_OPINION, CLASS_UNAPPROVED)


def is_not_reviewed(line: Mapping) -> bool:
    """The AI gave no answer for the item. Computed from the line itself (`classify`), never trusted from a stored class."""
    return classify(line)["verdict_class"] == CLASS_NOT_REVIEWED


def is_two_reader(line: Mapping) -> bool:
    """The line is of the class "AI verdict, two readers agree". Computed from the line itself (`classify`), never trusted from
    a stored class."""
    return classify(line)["verdict_class"] == CLASS_TWO_READERS


def is_not_checked_here(line: Mapping) -> bool:
    """The line is of the class "Not checked on this paper" (computed from the line, never from a stored class)."""
    return classify(line)["verdict_class"] == two_reader.CLASS_NOT_CHECKED_HERE


def is_unapproved(line: Mapping) -> bool:
    return line.get("rule_tier") == RULE_NOT_APPROVED


def decisions_of(pairs: Iterable[tuple[str, str]]) -> dict:
    """THE one count of decisions (owner, 12 Nov 2026) from (class, word) pairs: "Proven by code" (Pass or Fail: the code compared a value or
    proved an absence) plus "AI verdict, two readers agree" with the word met or not met. "Not stated" and every "AI thinks" are not decisions."""
    code = two_reader_n = 0
    for cls, word in pairs:
        if cls == CLASS_PROVEN:
            code += 1
        elif cls == CLASS_TWO_READERS and word in (
            two_reader.WORD_MET,
            two_reader.WORD_NOT_MET,
        ):
            two_reader_n += 1
    return {"code": code, "two_reader": two_reader_n, "total": code + two_reader_n}


def counts(lines: Iterable[Mapping]) -> dict:
    """The classes counted apart: proven pass/fail, AI thinks met/not met (approved and not-yet-approved rules apart), query."""
    ls = [apply(ln) for ln in lines]

    def n(label: str, cls: str) -> int:
        return sum(
            1
            for ln in ls
            if ln["verdict_label"] == label and ln["verdict_class"] == cls
        )

    dec = decisions_of((ln["verdict_class"], ln["verdict_label"]) for ln in ls)
    return {
        "decisions": dec["total"],
        "decisions_code": dec["code"],
        "decisions_two_reader": dec["two_reader"],
        "proven_pass": n(PASS, CLASS_PROVEN),
        "proven_fail": n(FAIL, CLASS_PROVEN),
        "ai_thinks_met": n(THINKS_MET, CLASS_OPINION),
        "ai_thinks_not_met": n(THINKS_NOT_MET, CLASS_OPINION),
        "ai_verdict_met": n(two_reader.WORD_MET, CLASS_TWO_READERS),
        "ai_verdict_not_met": n(two_reader.WORD_NOT_MET, CLASS_TWO_READERS),
        "ai_verdict_not_stated": n(two_reader.WORD_NOT_STATED, CLASS_TWO_READERS),
        "not_checked_here": n(two_reader.WORD_NEEDS, two_reader.CLASS_NOT_CHECKED_HERE),
        "unapproved_ai_thinks_met": n(THINKS_MET, CLASS_UNAPPROVED),
        "unapproved_ai_thinks_not_met": n(THINKS_NOT_MET, CLASS_UNAPPROVED),
        "unapproved_lines": sum(
            1 for ln in ls if ln.get("rule_tier") == RULE_NOT_APPROVED
        ),
        "query_for_the_engineer": n(WORD_QUERY, CLASS_QUERY),
        "not_applicable": n(WORD_QUERY, CLASS_NOT_APPLICABLE),
        "not_reviewed": sum(
            1 for ln in ls if ln["verdict_class"] == CLASS_NOT_REVIEWED
        ),
        "not_reviewed_answer_cut_off": sum(
            1
            for ln in ls
            if ln["verdict_class"] == CLASS_NOT_REVIEWED
            and ln.get("error") == "stop_max_tokens"
        ),
        "silent_paper_queries": sum(1 for ln in ls if ln.get("silence_query")),
        "recommendation_lines": sum(1 for ln in ls if ln[RECOMMENDATION]),
    }


__all__ = [
    "AI_TIER",
    "CLASSES",
    "CLASS_NOT_APPLICABLE",
    "CLASS_NOT_REVIEWED",
    "CLASS_OPINION",
    "CLASS_PROVEN",
    "CLASS_QUERY",
    "CLASS_TWO_READERS",
    "CLASS_UNAPPROVED",
    "THINKS_MET",
    "THINKS_NOT_MET",
    "apply",
    "classify",
    "counts",
    "decisions_of",
    "final_cap",
    "final_cap_all",
    "is_not_reviewed",
    "is_opinion",
    "is_two_reader",
    "is_unapproved",
    "writer_refusal",
]
