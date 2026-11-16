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

from . import agent_review_approved_code as approved_code
from . import agent_review_code_proof as code_proof
from . import agent_review_crosscheck as crosscheck
from . import agent_review_two_reader as two_reader
from .agent_review_local import (
    AI_QUERY_WHY,
    LOCAL_TOO_LONG,
    NO_VERDICT_CODE,
    NO_VERDICT_WHY,
    NO_VERDICT_WORDS,
    NOT_ALL_ASKED,
    NOT_ALL_ASKED_WORDS,
    NOT_ASKED_WORDS,
    OLD_NO_PASS_FAIL_WHY,
)
from .agent_review_verdict import (
    AI_TIER,
    BY_ABSENCE,
    BY_CODE,
    BY_ENGINEER,
    DEFERRED_WHY,
    DISAGREE_WHY,
    FAIL,
    NOT_A_RULE,
    OWNER_TIER,
    PASS,
    QUERY,
    RULE_NOT_APPROVED,
    SILENCE_CODES,
    SILENCE_WHY,
    TIER_NOT_APPROVED,
    TIER_NOT_ESTABLISHED,
    USABLE_TIERS,
    hold_silence,
    item_tier,
    met_unsafe_why,
    quote_defers,
)

#: The reason of a line whose second AI reader's answer was cut off by its token limit (`two_reader.second_cut_off`): the two
#: readers did not agree, but the second one never said the opposite, so the words must not say they disagree (order 14).
CUT_OFF_WHY = (
    "the second AI reader's answer was cut off, so the two readers did not agree"
)

CLASS_PROVEN = "Proven by code"
CLASS_OPINION = "AI opinion, engineer to confirm"
CLASS_QUERY = "Query for the engineer"
CLASS_UNAPPROVED = "AI opinion, rule not yet approved"
CLASS_NOT_APPLICABLE = "Not applicable"
CLASS_NOT_REVIEWED = "Not reviewed"
CLASS_TWO_READERS = two_reader.CLASS_TWO_READERS
WORD_NOT_REVIEWED = "Not reviewed"
ERROR_WORDS = {
    "stop_max_tokens": "no answer from the AI: answer cut off",
    LOCAL_TOO_LONG: NOT_ASKED_WORDS,
    NOT_ALL_ASKED: NOT_ALL_ASKED_WORDS,
    NO_VERDICT_CODE: NO_VERDICT_WORDS,
}

# ---- the reader's OWN Query, routed by its reason code (P3, 15 Nov 2026): ONE function for the page and the CRS
GROUP_SILENT, GROUP_DRAWING, GROUP_NOT_APPLICABLE, GROUP_COULD_NOT = (
    "silent",
    "drawing",
    "not_applicable",
    "could_not_decide",
)
GROUP_OF_CODE = {
    "sheet_silent": GROUP_SILENT,
    "needs_drawing_or_calc": GROUP_DRAWING,
    "not_applicable": GROUP_NOT_APPLICABLE,
}
#: the plain reason of each group: what the engineer reads beside the Query (a question for the contractor, for the engineer, or neither)
GROUP_WORDS = {
    GROUP_SILENT: "the sheet does not state this: a question for the contractor",
    GROUP_DRAWING: "needs a drawing or a calculation to judge: a question for the engineer, not the contractor",
    GROUP_NOT_APPLICABLE: "the AI judged the rule not applicable to this paper",
    GROUP_COULD_NOT: "the AI could not decide",
}
COULD_NOT_BECAUSE = {
    "unclear_clause": "the rule's clause is not clear enough to apply",
    "other": "it gave another reason",
}


def no_verdict(line: Mapping) -> bool:
    """The reader gave NO verdict for the item (read time, so earlier runs follow): no AI verdict word, no error, a Query whose gate
    reason says so. Never a reader's own Query (that is a view)."""
    return (
        line.get("ai_verdict") is None
        and not line.get("error")
        and line.get("verdict") == QUERY
        and str(line.get("why") or "") in (NO_VERDICT_WHY, OLD_NO_PASS_FAIL_WHY)
    )


def reader_query_group(line: Mapping) -> str | None:
    """The group of a line the READER called Query (it cannot decide and says why in a reason code), routed by that code; None for any
    other line. Earlier runs stored the gate's old sentence for these: they are read the same way, never rewritten."""
    if line.get("ai_verdict") != QUERY or line.get("error"):
        return None
    code = str(line.get("reason_code") or line.get("reason_code_ai") or "")
    silent_hold = (
        bool(line.get("silence_query")) and code == "sheet_silent"
    )  # the silence hold wrote its own reason
    if not silent_hold and str(line.get("why") or "") not in (
        AI_QUERY_WHY,
        OLD_NO_PASS_FAIL_WHY,
    ):
        return None
    return GROUP_OF_CODE.get(code, GROUP_COULD_NOT)


GROUP_LABELS = {
    GROUP_SILENT: "Questions for the contractor: the sheet does not state it",
    GROUP_DRAWING: "Questions for the engineer: needs a drawing or a calculation",
    GROUP_COULD_NOT: "The AI could not decide",
}


def query_group_counts(lines: Iterable[Mapping]) -> dict[str, int]:
    """How many of the lines the reader called Query sit in each group (ONE count for the page and the first sheet). The group
    "does not apply" is the class "Not applicable" and is counted there."""
    out = dict.fromkeys(GROUP_LABELS, 0)
    for ln in lines:
        if (
            classify(ln)["verdict_class"] == CLASS_QUERY
            and (group := reader_query_group(ln)) in out
        ):
            out[group] += 1
    return out


def reader_query_action(line: Mapping) -> str | None:
    """What the engineer reads as the action of a reader's own Query: a question for the engineer is never worded for the contractor."""
    return {
        GROUP_DRAWING: "Engineer to judge this: it needs a drawing or a calculation.",
        GROUP_COULD_NOT: "Engineer to decide: the AI reviewer could not.",
    }.get(reader_query_group(line) or "")


def group_rows(lines: Iterable[Mapping]) -> list[tuple[str, int]]:
    """The first sheet's Notes rows of the reader's own Query by group (the same count as the page)."""
    got = query_group_counts(lines)
    return [(f"Count: {label}", got[g]) for g, label in GROUP_LABELS.items()]


def reader_query_words(line: Mapping) -> str | None:
    """The plain reason of a reader's own Query by its group (None when the line is not one)."""
    group = reader_query_group(line)
    if group is None:
        return None
    if group == GROUP_COULD_NOT:
        because = COULD_NOT_BECAUSE.get(
            str(line.get("reason_code") or line.get("reason_code_ai") or "")
        )
        return f"{GROUP_WORDS[group]}: {because}" if because else GROUP_WORDS[group]
    return GROUP_WORDS[group]


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
CLAUSE_NOT_IN_BOOK_WHY = "the clause quote is not in the rule book's stored pages (c11), so nothing on this line is proven"
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


def _verified_quote_defers(rec: object) -> bool:
    """A reader's record whose paper quote code verified on its page defers the value (`quote_defers`)."""
    checks = rec.get("quotes_checked") if isinstance(rec, Mapping) else None
    return (
        isinstance(checks, Mapping)
        and bool(checks.get("paper"))
        and quote_defers(rec.get("paper_quote"))
    )


def not_met_deferred_why(line: Mapping) -> str | None:
    """Why an AI opinion "not met" (the gate's verdict Query) must be a Query, else None, when a paper quote code verified on
    its page defers the value ("By Contractor", "TBA", a "*" vendor-to-fill mark: `quote_defers`): (a) the line's OWN quote,
    when its "not met" rests on silence (reason absent, absent_pages_not_named or sheet_silent); (b) the quote of the
    second reader asked whether the paper states the item (`two_reader.stored_absence`), whatever the first reader quoted:
    it found the field marked for the vendor, so the readers do not agree that it is missing (R98: without (b) such a line
    fell through to "AI thinks: not met"). The sheet does not leave the value out, it asks the vendor for it. A proven Fail,
    another reason and an unverified quote pass through. It only makes a line less confident."""
    if line.get("ai_verdict") != FAIL or line.get("verdict") != QUERY:
        return None
    if _verified_quote_defers(two_reader.stored_absence(line)):
        return DEFERRED_WHY
    if str(line.get("reason_code") or "") not in SILENCE_CODES:
        return None
    return DEFERRED_WHY if _verified_quote_defers(line) else None


def _early(line: Mapping, unapproved: bool, why: str) -> dict | None:
    """Steps 1, 2 and 2b of `classify`: the AI gave no answer (Not reviewed); a silent paper (Query); an AI "met" whose paper
    defers the value or whose quotes code could not verify (Query, N9). None when none applies."""
    error = line.get("error") or (NO_VERDICT_CODE if no_verdict(line) else None)
    if (
        error
    ):  # 1. not reviewed, never a Query about the paper, whatever the rule's tier
        return {
            "verdict_label": WORD_NOT_REVIEWED,
            "verdict_class": CLASS_NOT_REVIEWED,
            "not_proven_reason": ERROR_WORDS.get(
                str(error), f"no answer from the AI: {error}"
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
    if (
        deferred := not_met_deferred_why(line)
    ):  # 2b'. a "not met" on silence whose own verified quote defers the value (order 14 lane D)
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": deferred + (f"; {why}" if unapproved else ""),
        }
    if got := two_reader.other_class(
        line
    ):  # 2d. both readers: needs a drawing or a calculation, not checked here
        return got
    if two_reader.absence_disagrees(
        line
    ):  # 2c'. the second reader found a value on a page code verified: the place is named
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": two_reader.absence_disagree_why(line),
        }
    if (
        two_reader.disagrees(line) or two_reader.other_disagrees(line)
    ):  # 2c. the independent second reader reached the opposite verdict, or its answer was cut off: a Query
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": CUT_OFF_WHY
            if two_reader.second_cut_off(line)
            else DISAGREE_WHY,
        }
    if crosscheck.disagrees(line):  # 2e. the second AI (Groq) disagrees: a Query
        also_why = f"; {why}" if unapproved else ""
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": crosscheck.DISAGREE_WHY + also_why,
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
        "not_proven_reason": reader_query_words(line)
        or str(line.get("why") or line.get("reason_code") or "")
        or None,
    }


def read_time(line: Mapping) -> dict:
    """A stored line of ANY run as every reader of it sees it: an item row (rule or checklist) gets the reason sentence the SAME rule gives a
    new line (`classify`), so an earlier run's stored reason (the gate's old sentence for a reader's own Query) is worded truly on the page,
    in the points and in a CRS built from it. Only the reason is taken: the stored class and every other key stay as they are (the
    defences that read the stored class keep working); never rewritten in the table. Any other line is returned as it is."""
    if line.get("source") not in ("rule", "skill"):
        return dict(line)
    return {**line, "not_proven_reason": classify(line)["not_proven_reason"]}


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
    if note := crosscheck.said(line):  # the second AI on, this line not asked: said
        base = str(out.get("not_proven_reason") or "").rstrip(" .;")
        out["not_proven_reason"] = f"{base}; {note}" if base else note
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
    q = out.get("quotes_checked")
    if (
        out.get("verdict") in (PASS, FAIL)
        and isinstance(q, Mapping)
        and q.get("clause") is False
        and not code_proof.is_code_line(out)
    ):  # c11: a Pass or Fail stands on a clause quote verified in the rule book's own pages
        out.update(verdict=QUERY, decided_by=BY_ENGINEER, why=CLAUSE_NOT_IN_BOOK_WHY)
        return out
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


CODE_SOURCE = "code"  # a line made by the calculator (`agent_review_calculator`), never by a model
UNPROVEN_CODE_WHY = "the code line was not proven: a compared value with both quotes found by code is needed"


def code_line_proven(line: Mapping) -> bool:
    """A CODE line may be Pass or Fail ONLY when the proof is made again from its own texts and values (`agent_review_code_proof`): both quotes hold
    the numbers they stand for, the comparison gives the stored verdict, the page is real. A flag on the line is never taken on trust."""
    return code_proof.line_proven(line)


def hold_unproven_code(line: Mapping) -> dict:
    """A line that claims to be a code line (its source in any case, its kind, its approved marker or its `C-` id) and is Pass or Fail without
    `code_line_proven` becomes a Query with the reason. Only makes a line less confident. Idempotent."""
    out = dict(line)
    if (
        code_proof.is_code_line(out)
        and out.get("verdict") in (PASS, FAIL)
        and not code_line_proven(out)
    ):
        out.update(
            verdict=QUERY,
            decided_by=BY_ENGINEER,
            why=UNPROVEN_CODE_WHY,
            reason_code="not_proven",
        )
    return out


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
    out = hold_unproven_code(hold_silence(line, paper_kind))
    tier = (
        OWNER_TIER
        if approved_code.is_approved_code_item(item)
        else item_tier(item, lookup, skill_ids)
    )
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
    proved an absence) plus "AI verdict, two readers agree" with the word met, not met or not stated (lead, 12 Nov 2026: two readers each
    read every page and found no value is a decision "not stated on the paper"). Every "AI thinks" is not a decision."""
    code = two_reader_n = stated_n = 0
    for cls, word in pairs:
        if cls == CLASS_PROVEN:
            code += 1
        elif cls == CLASS_TWO_READERS and word in (
            two_reader.WORD_MET,
            two_reader.WORD_NOT_MET,
            two_reader.WORD_NOT_STATED,
        ):
            two_reader_n += 1
            stated_n += word == two_reader.WORD_NOT_STATED
    return {
        "code": code,
        "two_reader": two_reader_n,
        "not_stated": stated_n,
        "total": code + two_reader_n,
    }


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
    qg = query_group_counts(ls)
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
        "query_contractor_silent": qg[GROUP_SILENT],
        "query_engineer_drawing": qg[GROUP_DRAWING],
        "query_ai_could_not_decide": qg[GROUP_COULD_NOT],
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
    "NO_VERDICT_WORDS",
    "THINKS_MET",
    "THINKS_NOT_MET",
    "apply",
    "classify",
    "counts",
    "decisions_of",
    "final_cap",
    "final_cap_all",
    "group_rows",
    "is_not_reviewed",
    "is_opinion",
    "is_two_reader",
    "is_unapproved",
    "no_verdict",
    "query_group_counts",
    "read_time",
    "reader_query_action",
    "reader_query_group",
    "reader_query_words",
    "writer_refusal",
]
