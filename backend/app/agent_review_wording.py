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

from .agent_review_verdict import (
    AI_TIER,
    BY_ENGINEER,
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
WORD_NOT_REVIEWED = "Not reviewed"
ERROR_WORDS = {"stop_max_tokens": "no answer from the AI: answer cut off"}
CLASSES = (
    CLASS_PROVEN,
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
    if unsafe := met_unsafe_why(line):  # 2b. N9
        return {
            "verdict_label": WORD_QUERY,
            "verdict_class": CLASS_QUERY,
            "not_proven_reason": unsafe + (f"; {why}" if unapproved else ""),
        }
    return None


def classify(line: Mapping) -> dict:
    """verdict_label, verdict_class, not_proven_reason (None when proven) for one line.

    THE ORDER at the exit (the first that applies wins): 1. Not reviewed (the AI gave no answer); 2. silence (a non-datasheet
    paper that is silent: Query, and when the rule is also not AI approved the reason says both); 3. the cap of a rule that is
    not AI approved; 4. proven Pass / Fail, then the AI opinions, then Query."""
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
    """The line with the words added (idempotent). A 'should' rule is marked a recommendation."""
    return {**line, **classify(line), RECOMMENDATION: line.get("rule_kind") == "advice"}


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
        return apply(out)
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
    return apply(out)


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


def is_unapproved(line: Mapping) -> bool:
    return line.get("rule_tier") == RULE_NOT_APPROVED


def counts(lines: Iterable[Mapping]) -> dict:
    """The classes counted apart: proven pass/fail, AI thinks met/not met (approved and not-yet-approved rules apart), query."""
    ls = [apply(ln) for ln in lines]

    def n(label: str, cls: str) -> int:
        return sum(
            1
            for ln in ls
            if ln["verdict_label"] == label and ln["verdict_class"] == cls
        )

    return {
        "proven_pass": n(PASS, CLASS_PROVEN),
        "proven_fail": n(FAIL, CLASS_PROVEN),
        "ai_thinks_met": n(THINKS_MET, CLASS_OPINION),
        "ai_thinks_not_met": n(THINKS_NOT_MET, CLASS_OPINION),
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
    "CLASS_UNAPPROVED",
    "THINKS_MET",
    "THINKS_NOT_MET",
    "apply",
    "classify",
    "counts",
    "final_cap",
    "final_cap_all",
    "is_not_reviewed",
    "is_opinion",
    "is_unapproved",
    "writer_refusal",
]
