"""The AI reviewer's gate: when a line may be called Pass or Fail (order 12, ported from the experiment's verdict.py).

Pure functions, no I/O, no model call, no network. A line is Pass or Fail ONLY when code proved it (both quotes verified
word for word, figures compared by code, a different model family agreeing on verified quotes); every doubt is a Query and
a guard can only make a verdict LESS confident, never more.

PUBLIC API OF THE AGENT REVIEW CORE (one docstring index for all core modules; model calls are always injected)
  agent_review_verdict   gate: check_quotes, textual_verdict, number_verdict, needs_second_opinion, compare_figures,
                         figures_by_code, widen_to_sentence, hold_conditional_fail (F1), hold_table_note_fail (F3),
                         cap_unapproved, silence_is_query / hold_silence (a silent paper is a Query), apply_holds (the order the runner applies them in), restore_holds (a stored
                         answer decided again), calls_allowed(item), item_tier(item, lookup), USABLE_TIERS
  agent_review_context   F4: fingerprint, quote_on_page, neighbour_pages, build_parts, evaluate, held_decision,
                         check_fail (the whole code decision; the model call is an injected callable)
  agent_review_rules     rule choice: decide_rule, filter_rows, count_left_out, summary_lines, left_out_record, label_block,
                         rules_used, missing_rule_books, filter_skill_items (F2), skill_fits, paper_equipment_types, tier_lookup (the
                         CURRENT tier from the label table, for final_cap)
  agent_review_items     build_items (agent_review_standards: its clause reader), batch_by_page, validate, applicable_rules, rule_item, skill_item
  agent_review_pages     page_image, image_source, image_tokens, ImageToolBox, to_api_messages, PageImageUnavailable
  agent_review_absence   prove, comment, ABSENCE_WHY, Proof (an absence Fail proven by code)
  agent_review_wording   classify, apply, final_cap / final_cap_all (ONE cap at the exit), writer_refusal, counts, is_opinion,
                         is_unapproved, CLASS_*
  agent_review_crs       write_internal, write_contractor, write_comment_only, run_counts (refuse unproven Pass/Fail)

THE RUNNER MUST (guards that live only in the experiment's Runner; HB2's runner re-creates each one, each with a test; R10)
  1. reason_of / TIGHTENING: a reason code "absent", "absent_pages_not_named" or "verdict_and_reason_differ" forces the AI verdict
     to Query; a line with reason "absent" becomes Query ("not shown on the sheet; code cannot prove an absence") BEFORE the
     absence proof runs; the absence proof only for an AI Fail and only if calls_allowed(item).
  2. The second opinion: asked only when needs_second_opinion AND calls_allowed AND the stop flag is clear, by a model of a
     DIFFERENT family than the lead; the lead's model name comes from the API response (unnamed = never a Pass); a stored
     second opinion is reused, never asked again; widening a short clause quote drops the stored second opinion.
  3. final check / tiebreak: only when the second disagreed (agree False), the models differ, the AI said Fail (a Pass only
     with its own switch) and the item is not unapproved.
  4. widen: only a verified but weak clause quote, AI Fail (a Pass only with its switch), never an annex rule, re-verified
     strong; figures_by_code only when both quotes are verified, the AI said Pass or Fail, and the figures are not already inside.
  5. held_texts: the clause quote is checked against the held text it stands in, the requirement first; whole_requirement is
     passed only when that text is the requirement block.
  6. THE ORDER of the decide path: gate -> absence -> F1 -> F3 -> cap (apply_holds, with a tier-derived item: use item_tier) ->
     F4 (a Fail only, never for an unapproved item, in_scope False in a free redecide) -> deferral guard on a Pass (pass_guard) ->
     silence (hold_silence, inside final_cap(..., paper_kind=)) -> final_cap_all at the exit WITH tier_lookup -> writers.
  7. The deferral guard is given ALL pages of the paper (1..total from the database), not only the pages sent to the model.
  8. Cap stops: the ledger reserves before and settles after EVERY call (lead, second, absence second, final check, context);
     a fatal exception (budget stop) halts the run: pass `fatal` to check_fail and halt on `result.fatal`; only the app's
     claude_spend / reader_transport lane.
  9. Refusals before any call: a tiered item list without the order-12 switches; a runner paper kind that differs from the
     filter's kind; the context check on without rule-book pages in the database; the lead and the second or context model of
     the same family.
 10. Redecide / resume: every line restored from a stored run goes through restore_holds and final_cap_all; a stored context
     fingerprint carries over only through check_fail's `stored`.
 11. Items: run agent_review_items.validate() on every item list; a checklist item is one ONLY by is_checklist_item (source
     "skill" and an id in the checklist data and no rule reference); anything else is a rule and needs a tier. Also pass the
     paper's equipment type to decide_rule / tier_lookup (a person's approval for ANY type counts when none is given).

THE RULE. A line is Pass or Fail ONLY when:
  textual line: the paper quote AND the clause quote are both verified by code, the AI's own verdict is Pass or Fail,
                the AI call did not fail, "not mentioned" is not called a Pass, and the second opinion (agent_run_second,
                a DIFFERENT model family, its name from the API response) AGREES. Anything else: Query for the engineer.
  number line:  both quotes verified, each figure stands inside its quote, and `compare_number` (code) DECIDED it.
                The verdict is the code's ("decided by code"), never the AI's. Not decided: Query.
A failed AI call (error, timeout, refusal, unparseable, no answer for the item) gives Query, with the error kept so the CRS
line shows it. A failure can only make a line LESS confident, never more.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import agent_bind, agent_run_second, agent_tools, blank_markers
from .reader_api import _fold

PASS, FAIL, QUERY = "Pass", "Fail", "Query"
VERDICTS = (PASS, FAIL, QUERY)
COLOUR_OF = {PASS: "GREEN", FAIL: "RED"}
VERDICT_OF = {"GREEN": PASS, "RED": FAIL, "YELLOW": QUERY}
BY_AI, BY_CODE, BY_ENGINEER = "AI verdict", "decided by code", "engineer"
BY_ABSENCE = "AI verdict, absence checked by code"  # step D: an absence Fail proven by code (exp11.absence)
BY_FINAL_CHECK = "AI verdict, after a final check"  # step D round 2 (c): the lead and second disagreed; a third check
MAX_SENTENCE_CHARS = 600
MIN_QUOTE_CHARS = agent_tools.MIN_QUOTE_CHARS
NUMBER_KINDS = frozenset({"limit"})


def ai_verdict_word(raw: Any) -> str | None:
    """The AI's verdict word: Pass, Fail or Query (GREEN/RED/YELLOW accepted as aliases), else None."""
    if not isinstance(raw, str):
        return None
    word = raw.strip().lower()
    for v in VERDICTS:
        if word == v.lower():
            return v
    return VERDICT_OF.get(word.upper())


@dataclass(frozen=True)
class QuoteCheck:
    """What code verified. `paper` / `clause`: the quote stands verbatim (folded) in the page / clause text."""

    paper: bool
    clause: bool
    paper_why: str | None = None
    clause_why: str | None = None
    clause_strong: bool = (
        False  # agent_bind.clause_quote_ok: 40+ characters and not the clause heading
    )

    @property
    def both(self) -> bool:
        return self.paper and self.clause

    def to_json(self) -> dict:
        return {
            "paper": self.paper,
            "clause": self.clause,
            "both": self.both,
            "paper_why": self.paper_why,
            "clause_why": self.clause_why,
            "clause_strong": self.clause_strong,
        }


def _page_no(page: Any) -> int | None:
    if isinstance(page, bool):
        return None
    if isinstance(page, int):
        return page if page >= 1 else None
    if isinstance(page, str) and page.strip().isdigit():
        return int(page.strip()) or None
    return None


def check_paper_quote(
    quote: Any, page: Any, pages: Mapping[int, str]
) -> tuple[bool, str | None]:
    """The paper quote stands on the page it names, among the pages that were sent (record_finding's check)."""
    text = str(quote or "").strip()
    if not text:
        return False, "no paper quote"
    n = _page_no(page)
    if n is None:
        return False, "no page"
    page_text = pages.get(n)
    if not page_text or not str(page_text).strip():
        return False, "page not read"
    if len(text) < MIN_QUOTE_CHARS:
        return False, "paper quote too short"
    if _fold(text) not in _fold(str(page_text)):
        return False, "paper quote not on the page"
    return True, None


def check_clause_quote(
    quote: Any, clause_text: str | None, whole_requirement: str | None = None
) -> tuple[bool, str | None, bool]:
    """(verified, why not, strong). Verified: verbatim (folded) in the cached clause text. Strong: also
    `agent_bind.clause_quote_ok` (40+ characters, not the clause heading), OR the quote is (folded) the WHOLE stored
    requirement text of the rule (a short rule sentence quoted complete), which a Pass or Fail needs."""
    text = str(quote or "").strip()
    if not text:
        return False, "no clause quote", False
    if not clause_text or not str(clause_text).strip():
        return False, "clause text not held", False
    if len(text) < MIN_QUOTE_CHARS:
        return False, "clause quote too short", False
    if _fold(text) not in _fold(str(clause_text)):
        return False, "clause quote not in the clause", False
    whole = bool(whole_requirement) and _fold(text) == _fold(str(whole_requirement))
    return True, None, agent_bind.clause_quote_ok(text, clause_text) or whole


def check_quotes(
    answer: Mapping,
    pages: Mapping[int, str],
    clause_text: str | None,
    whole_requirement: str | None = None,
) -> QuoteCheck:
    paper, paper_why = check_paper_quote(
        answer.get("paper_quote"), answer.get("paper_page"), pages
    )
    clause, clause_why, strong = check_clause_quote(
        answer.get("clause_quote"), clause_text, whole_requirement
    )
    return QuoteCheck(paper, clause, paper_why, clause_why, strong)


def says_absent(answer: Mapping) -> bool:
    """The AI's own words say the paper does not state it (agent_tools.NOT_MENTIONED_WORDS): never a Pass."""
    text = _fold(
        " ".join(
            str(answer.get(k) or "") for k in ("reasoning", "comment", "paper_quote")
        )
    )
    return (
        any(_fold(w) in text for w in agent_tools.NOT_MENTIONED_WORDS)
        or answer.get("mentioned") is False
    )


def is_number_item(item: Mapping) -> bool:
    """A line decided by compare_number: the held rule is a limit (a comparator and a value)."""
    return item.get("rule_kind") in NUMBER_KINDS


def needs_second_opinion(
    ai_verdict: str | None, checks: QuoteCheck, error: str | None, absent: bool = False
) -> bool:
    """Ask the second opinion only when a Pass or Fail could still stand (saves money; the rule is the same)."""
    if (
        error
        or ai_verdict not in (PASS, FAIL)
        or not (checks.both and checks.clause_strong)
    ):
        return False
    return not (ai_verdict == PASS and absent)


def _query(why: str, by: str = BY_ENGINEER, **extra: Any) -> dict:
    return {"verdict": QUERY, "decided_by": by, "why": why, **extra}


def textual_verdict(
    ai_verdict: str | None,
    checks: QuoteCheck,
    second: Mapping | None,
    lead_model: str | None,
    *,
    error: str | None = None,
    absent: bool = False,
) -> dict:
    """{'verdict', 'decided_by', 'why', 'second_opinion'} for a textual line (rule 3b, 3e).

    `second` is agent_run_second.ask_second_opinion's {'agree': bool | None, 'model': str} or None (not asked)."""
    if error:
        return _query(f"AI call failed: {error}", second_opinion="not asked")
    if ai_verdict not in (PASS, FAIL):
        return _query("the AI did not give pass or fail", second_opinion="not asked")
    if not checks.paper:
        return _query(
            f"paper quote not verified by code ({checks.paper_why})",
            second_opinion="not asked",
        )
    if not checks.clause:
        return _query(
            f"clause quote not verified by code ({checks.clause_why})",
            second_opinion="not asked",
        )
    if not checks.clause_strong:
        return _query(
            "clause quote is too short or is the clause heading",
            second_opinion="not asked",
        )
    if ai_verdict == PASS and absent:
        return _query("not mentioned is never a pass", second_opinion="not asked")
    if second is None:
        return _query("no second opinion", second_opinion="not asked")
    agree = second.get("agree")
    agree = agree if isinstance(agree, bool) else None
    same = not agent_run_second.models_differ([lead_model or ""], second.get("model"))
    out = agent_run_second.apply_second_opinion(
        {"color": COLOUR_OF[ai_verdict]}, agree, ran=True, same_model=same
    )
    verdict = VERDICT_OF.get(str(out.get("color")), QUERY)
    if verdict == QUERY:
        return _query(
            str(out.get("reason") or "second opinion did not agree"),
            second_opinion=out.get("second_opinion") or "no answer",
        )
    return {
        "verdict": verdict,
        "decided_by": BY_AI,
        "why": None,
        "second_opinion": "agreed",
    }


def figures_inside(answer: Mapping) -> bool:
    """Each figure stands inside its own quote, with number and unit (agent_bind's figure rule)."""
    pf, cf = (
        str(answer.get("paper_figure") or "").strip(),
        str(answer.get("clause_figure") or "").strip(),
    )
    if not pf or not cf:
        return False
    if _fold(pf) not in _fold(str(answer.get("paper_quote") or "")):
        return False
    if _fold(cf) not in _fold(str(answer.get("clause_quote") or "")):
        return False
    return agent_bind.has_figure(pf) and agent_bind.has_figure(cf)


def number_verdict(
    compare: Mapping | None,
    checks: QuoteCheck,
    answer: Mapping,
    *,
    error: str | None = None,
) -> dict:
    """{'verdict', 'decided_by', 'why'} for a number line: only compare_number decides (labelled 'decided by code')."""
    if error:
        return _query(f"AI call failed: {error}")
    if not checks.paper:
        return _query(f"paper quote not verified by code ({checks.paper_why})")
    if not checks.clause:
        return _query(f"clause quote not verified by code ({checks.clause_why})")
    if not figures_inside(answer):
        return _query("no figure with its unit inside both quotes")
    if not isinstance(compare, Mapping) or compare.get("decided") is not True:
        reason = (compare or {}).get("reason") if isinstance(compare, Mapping) else None
        return _query(
            f"code could not compare the figures ({reason or 'not compared'})",
            by=BY_CODE,
        )
    if compare.get("verdict") == "meets":
        return {"verdict": PASS, "decided_by": BY_CODE, "why": None}
    if compare.get("verdict") == "does_not_meet":
        return {"verdict": FAIL, "decided_by": BY_CODE, "why": None}
    return _query("code could not compare the figures", by=BY_CODE)


def compare_figures(box: Any, answer: Mapping) -> dict | None:
    """compare_number (ToolBox, code) on the two figures; None when there are no two figures to compare."""
    if not figures_inside(answer):
        return None
    res = box.compare_number(
        str(answer.get("paper_figure")).strip(),
        str(answer.get("clause_figure")).strip(),
    )
    inner = res.get("result") if isinstance(res, dict) else None
    return inner if isinstance(inner, dict) else None


# ---------------------------------------------------------------- step D round 2 (a): the figure found by code


def figures_in(text: Any) -> list[str]:
    """Every figure (a number WITH a unit, agent_bind's figure rule: dates and part-number-like tokens masked) in text."""
    masked = agent_bind._NOT_FIGURE.sub(" ", str(text or ""))
    return [
        m.group(0).strip()
        for m in agent_bind._NUMBER_UNIT.finditer(masked)
        if agent_bind.claims.is_unit(m.group(1))
    ]


def figures_by_code(answer: Mapping) -> dict | None:
    """(a) The AI gave no usable figures: code reads them from the two VERIFIED quotes. A copy of the answer with
    paper_figure / clause_figure set when each quote holds EXACTLY ONE figure; None for none or several (Query)."""
    paper, clause = (
        figures_in(answer.get("paper_quote")),
        figures_in(answer.get("clause_quote")),
    )
    if len(paper) != 1 or len(clause) != 1:
        return None
    return {
        **answer,
        "paper_figure": paper[0],
        "clause_figure": clause[0],
        "figures_by": "code",
    }


def compare_quotes(box: Any, answer: Mapping) -> dict | None:
    """compare_number (code) on the two whole verified quotes: it checks the subject of both and the quantity."""
    res = box.compare_number(
        str(answer.get("paper_quote") or ""), str(answer.get("clause_quote") or "")
    )
    inner = res.get("result") if isinstance(res, dict) else None
    return inner if isinstance(inner, dict) else None


# ---------------------------------------------------------------- step D round 2 (b): the short quote widened by code

_SENTENCE_END = re.compile(
    r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'])|\n\s*\n|\n(?=\s*(?:[a-z]\)|\(?[a-z0-9]{1,3}\)|\d+(?:\.\d+)+\s))"
)


def sentences(text: str) -> list[str]:
    """The stored clause text cut into sentences by code (an end mark then a capital, a blank line, a list item)."""
    return [
        " ".join(p.split())
        for p in _SENTENCE_END.split(str(text or ""))
        if p and p.strip()
    ]


_NOTE_OR_EXAMPLE = re.compile(
    r"^\W*(?:note|notes|example|examples|e\.?\s?g\.?)\b", re.IGNORECASE
)


def is_note_or_example(sentence: str | None) -> bool:
    """Review 7: the clause text marks the sentence as an informative note or example (it starts NOTE / EXAMPLE)."""
    return bool(_NOTE_OR_EXAMPLE.match(str(sentence or "")))


def widen_to_sentence(quote: Any, clause_text: str | None) -> str | None:
    """(b) The ONE whole sentence of the stored clause text that holds the (verified) short quote, else None: the
    quote not found, found in several sentences, spanning two, or a sentence longer than MAX_SENTENCE_CHARS."""
    q = _fold(str(quote or ""))
    if not q or not clause_text:
        return None
    hits = [s for s in sentences(clause_text) if q in _fold(s)]
    if (
        len(hits) != 1
        or len(hits[0]) > MAX_SENTENCE_CHARS
        or _fold(hits[0]) == q
        or is_note_or_example(hits[0])
    ):
        return None
    return hits[0]


# ---------------------------------------------------------------- order 12 F1: a conditional rule's Fail is never proven

#: Plain conditional words only (no equipment, service or scoping words: rule 13).
_CONDITIONAL = re.compile(
    r"\b(?:if|when|where|unless|provided that|in case|except|only|otherwise)\b",
    re.IGNORECASE,
)
CONDITIONAL_WHY = "the rule is conditional; code cannot prove the condition holds"


def is_conditional(*texts: Any) -> bool:
    """A text states a condition by a plain conditional word (if, when, where, unless, provided that, in case, except,
    only, otherwise)."""
    return any(_CONDITIONAL.search(str(t or "")) for t in texts)


def hold_conditional_fail(
    decision: Mapping, clause_quote: Any, requirement: Any
) -> dict:
    """A Fail of a rule whose clause quote or stored rule words state a condition is held: the answer schema carries no paper
    quote for the condition, so code cannot prove the condition holds on the paper. The line becomes a Query (the CRS shows it
    as the AI's opinion). A Pass and every other decision come back unchanged; this only makes a verdict less confident."""
    if decision.get("verdict") == FAIL and is_conditional(clause_quote, requirement):
        return {
            **decision,
            "verdict": QUERY,
            "decided_by": BY_ENGINEER,
            "why": CONDITIONAL_WHY,
            "conditional": True,
        }
    return dict(decision)


# ---------------------------------------------------------------- order 12 F3: a table row or a note loses its conditions

#: Stored requirement types that mark a row cut from a table (`standard_requirements.requirement_type`).
TABLE_TYPES = frozenset({"table_row", "table_value"})
#: A cache entry whose clause text came from a table page (`exp11.items`: source "table_page").
TABLE_SOURCES = frozenset({"table_page"})
TABLE_NOTE_WHY = (
    "the rule is a table row or a note; its conditions may lie outside the quote"
)
_NOTE_START = re.compile(
    r"^[\W_]{0,3}(?:notes?\s*(?:[\d:.)(\[]|$)|[\[(]\s*\d{1,3}\s*[\])]|[\u00b9\u00b2\u00b3\u2070-\u2079]+)",
    re.IGNORECASE,
)


def is_note_start(text: Any) -> bool:
    """The text begins with a note marker: Note / NOTE / Notes then a number or a colon, a bracketed note number, or a
    superscript digit."""
    return bool(_NOTE_START.match(str(text or "")))


def table_or_note_why(
    item: Mapping, rule_text: Any, clause_sources: Iterable[Any] = ()
) -> str | None:
    """Which of (a) the stored requirement is a table row, (b) the rule's quote begins with a note marker, (c) the clause text
    came from a table fired; None when none did."""
    if (
        item.get("requirement_type") in TABLE_TYPES
        or item.get("table_row") is not None
        or item.get("clause_from") == "table_caption"
    ):
        return "a"
    if is_note_start(rule_text):
        return "b"
    if any(str(src) in TABLE_SOURCES for src in clause_sources):
        return "c"
    return None


def hold_table_note_fail(
    decision: Mapping, item: Mapping, rule_text: Any, clause_sources: Iterable[Any] = ()
) -> dict:
    """A Fail of a table row or note rule is held (it becomes a Query shown as the AI's opinion). Pass and everything else
    come back unchanged: this only makes a verdict less confident."""
    if decision.get("verdict") == FAIL and (
        why := table_or_note_why(item, rule_text, clause_sources)
    ):
        return {
            **decision,
            "verdict": QUERY,
            "decided_by": BY_ENGINEER,
            "why": TABLE_NOTE_WHY,
            "table_note": why,
        }
    return dict(decision)


# ---------------------------------------------------------------- the tier of a rule, and the cap of a rule not AI approved

OWNER_TIER, ENGINEER_TIER, AI_TIER = "owner", "engineer", "AI approved"
#: The ONLY tiers a Pass or a Fail may stand on (the same words `rule_labels.usable_tier` returns).
USABLE_TIERS = frozenset({OWNER_TIER, ENGINEER_TIER, AI_TIER})
TIER_NOT_APPROVED = (
    "not AI approved"  # the tier word shown for a rule asked although not approved
)
RULE_NOT_APPROVED = "not_approved"  # the item/line field `rule_tier` of such a rule; the cap is keyed on it
NOT_A_RULE = "not a rule"  # a checklist item: no stored rule, so no tier applies
CLASS_UNAPPROVED_WHY = "the rule is not AI approved: {parts}"
TIER_NOT_ESTABLISHED = "its approval tier could not be established"


def unapproved_why(item: Mapping) -> str:
    return CLASS_UNAPPROVED_WHY.format(
        parts=item.get("rule_unapproved_why") or "not agreed"
    )


_CHECKLIST_IDS: list[
    frozenset[str]
] = []  # filled only by a COMPLETE load: a failed load is never remembered


def checklist_ids() -> frozenset[str]:
    """The item ids ("S-<id>") of every checklist the app holds (`agent_skills`): the data a checklist item must come from.
    Remembered only when every checklist loaded; a load that failed (a missing file, a test's patch) is asked again next time,
    never kept as an empty set."""
    if _CHECKLIST_IDS:
        return _CHECKLIST_IDS[0]
    from . import agent_skills

    ids: set[str] = set()
    complete = True
    for kind in agent_skills.KINDS:
        try:
            skill = agent_skills.load_skill(kind)
        except agent_skills.SkillError:
            complete = False
            continue
        ids |= {f"S-{it['id']}" for it in skill["items"]}
    found = frozenset(ids)
    if complete and found:
        _CHECKLIST_IDS.append(found)
    return found


def is_checklist_item(
    item: Mapping | None, skill_ids: Collection[str] | None = None
) -> bool:
    """A checklist item ONLY when: source is exactly "skill", its id is a checklist id that exists in the checklist data
    (`skill_ids`, default `checklist_ids()`), and it holds no rule reference (no rule version, rule quote, requirement type or
    tier marker). Anything else is a RULE and needs a tier: the marker is never taken on trust."""
    if not isinstance(item, Mapping) or item.get("source") != "skill":
        return False
    ids = checklist_ids() if skill_ids is None else skill_ids
    if item.get("item_id") not in ids:
        return False
    return not any(
        item.get(k)
        for k in (
            "rule_version_id",
            "rule_quote_ref",
            "requirement_type",
            "rule_tier",
            "rule_label",
        )
    )


def item_tier(
    item: Mapping | None,
    lookup: Callable[[Mapping], str | None] | None = None,
    skill_ids: Collection[str] | None = None,
) -> str:
    """The CURRENT tier of an item: one of USABLE_TIERS, RULE_NOT_APPROVED or NOT_A_RULE (a checklist item, see
    `is_checklist_item`).

    Every other item is a rule. A rule whose tier cannot be established is NOT approved: `rule_tier == "not_approved"` on the
    item, a label tier that is not usable, or no tier at all all give RULE_NOT_APPROVED; so does an item that is not a
    checklist item but says it is. With `lookup(item)` (e.g. `rules.tier_lookup`) the CURRENT label table decides instead of
    the carried tier. An item that says it is not approved is never promoted by a lookup. No item at all is a rule whose tier is
    not established."""
    if item is None:
        return RULE_NOT_APPROVED
    if is_checklist_item(item, skill_ids):
        return NOT_A_RULE
    if item.get("rule_tier") == RULE_NOT_APPROVED:
        return RULE_NOT_APPROVED
    if (
        lookup is not None
    ):  # the CURRENT label table decides, whatever tier the item carried when it was built
        got = lookup(item)
        return str(got) if got in USABLE_TIERS else RULE_NOT_APPROVED
    label = item.get("rule_label")
    carried = label.get("tier") if isinstance(label, Mapping) else None
    return str(carried) if carried in USABLE_TIERS else RULE_NOT_APPROVED


def calls_allowed(
    item: Mapping | None,
    lookup: Callable[[Mapping], str | None] | None = None,
    skill_ids: Collection[str] | None = None,
) -> bool:
    """May a model call beyond the lead's own answer be bought for this item (second opinion, absence second opinion,
    final check, context check)? Never for a rule that is not approved (its line is capped, so the call could change
    nothing but the bill), never for a rule whose tier cannot be established. A checklist item: yes."""
    return item_tier(item, lookup, skill_ids) != RULE_NOT_APPROVED


def cap_unapproved(decision: Mapping, item: Mapping | None) -> dict:
    """THE cap: a line whose rule is not AI approved can never be a Pass or a Fail, whatever the gate proved. It becomes a
    Query (shown as the AI's opinion, rule not yet approved). Everything else comes back unchanged. Keyed on the item's
    own `rule_tier` marker; `final_cap` (agent_review_wording) is the exit version that re-derives the tier."""
    if (item or {}).get("rule_tier") == RULE_NOT_APPROVED and decision.get(
        "verdict"
    ) in (PASS, FAIL):
        return {
            **decision,
            "verdict": QUERY,
            "decided_by": BY_ENGINEER,
            "why": unapproved_why(item or {}),
            "unapproved_cap": True,
        }
    return dict(decision)


def apply_holds(
    decision: Mapping,
    item: Mapping,
    *,
    clause_quote: Any,
    requirement: Any,
    clause_sources: Iterable[Any] = (),
) -> dict:
    """The holds of the decide path, in the experiment's order: F1 (conditional words), F3 (table row or note), THEN the cap
    of a rule not AI approved. (F4, the page-context check, follows in agent_review_context.) Each only makes the verdict
    less confident."""
    out = hold_conditional_fail(decision, clause_quote, requirement)
    out = hold_table_note_fail(out, item, requirement, clause_sources)
    return cap_unapproved(out, item)


_DECISION_KEYS = ("verdict", "decided_by", "why")


def restore_holds(
    line: Mapping, item: Mapping, *, clause_sources: Iterable[Any] = ()
) -> dict:
    """The same guards on a line RESTORED from a stored answer (a redecide, a resume): the cap first, then F1 and F3 on a
    restored code Fail. Nothing a restore does lifts a hold."""
    out = dict(line)
    capped = cap_unapproved(out, item)
    if capped.get("unapproved_cap"):
        out.update({k: capped[k] for k in _DECISION_KEYS}, unapproved_cap=True)
    held = hold_conditional_fail(out, out.get("clause_quote"), out.get("requirement"))
    if held.get("conditional"):
        out.update({k: held[k] for k in _DECISION_KEYS}, conditional_hold=True)
    held = hold_table_note_fail(out, item, out.get("requirement"), clause_sources)
    if held.get("table_note"):
        out.update(
            {k: held[k] for k in _DECISION_KEYS}, table_note_hold=held["table_note"]
        )
    return out


# ---------------------------------------------------------------- owner 16.3: when the paper is silent, the answer is a Query

#: Reason codes of a line whose verdict rests on absence (the paper does not state it).
SILENCE_CODES = frozenset({"absent", "absent_pages_not_named", "sheet_silent"})
SILENCE_WHY = "the paper is silent on this; a missing statement is not a failure"


def silence_is_query(paper_kind: Any) -> bool:
    """THE one switch point: for which paper kinds does a silent paper give a Query (never "not met")? Every kind except a
    datasheet (a datasheet has a fixed set of entries, so an absent required entry stays the AI's opinion "not met"). An
    unknown kind is silent too: the safe side. Change this function, and only this one, to change the rule."""
    return str(paper_kind or "").strip().lower() != "datasheet"


def hold_silence(line: Mapping, paper_kind: Any) -> dict:
    """A line resting on absence, on a paper kind where silence is a Query, is a Query whatever the verdict said."""
    if (
        line.get("reason_code") in SILENCE_CODES
        and silence_is_query(paper_kind)
        and line.get("verdict") in (FAIL, QUERY)  # a Pass is never touched
    ):
        return {
            **dict(line),
            "verdict": QUERY,
            "decided_by": BY_ENGINEER,
            "why": SILENCE_WHY,
            "silence_query": True,
        }
    return dict(line)


# ---------------------------------------------------------------- N9: an "AI thinks: met" the code cannot stand behind is a Query

DEFERRED_WHY = "the paper defers or leaves open this value, so 'met' cannot stand"
UNVERIFIED_PAPER_WHY = "the quoted paper text could not be verified by code"
UNVERIFIED_CLAUSE_WHY = "the quoted clause text could not be verified by code"
DISAGREE_WHY = "two AI readers disagree on this line"
_CELL_SPLIT = re.compile(r"[\r\n|\t]+")


def quote_defers(quote: Any) -> bool:
    """The paper quote defers or leaves open the value: a deferral phrase anywhere in it ("by contractor", "to be confirmed",
    "TBA", "vendor to advise") or a cell of it that is wholly a marker ("later", "hold", "-", "*", "by others"). ONE word list:
    `blank_markers` (rule 8); this adds no words of its own."""
    text = str(quote or "")
    if blank_markers.names_a_marker(text):
        return True
    return any(
        blank_markers.is_marker(cell)
        for cell in _CELL_SPLIT.split(text)
        if cell.strip()
    )


def met_unsafe_why(line: Mapping) -> str | None:
    """Why an AI opinion "met" (ai_verdict Pass, the gate's verdict not Pass) must be a Query, else None. (a) the paper quote
    it rests on defers the value; (b) the paper quote or the clause quote was not verified by code (a line with no record of
    the check counts as not verified). Never touches a proven Pass or any other AI word: it only makes a line less confident."""
    if line.get("ai_verdict") != PASS or line.get("verdict") == PASS:
        return None
    if quote_defers(line.get("paper_quote")):
        return DEFERRED_WHY
    checks = line.get("quotes_checked")
    checks = checks if isinstance(checks, Mapping) else {}
    if not checks.get("paper"):
        return UNVERIFIED_PAPER_WHY
    if not checks.get("clause"):
        return UNVERIFIED_CLAUSE_WHY
    # The line field `second_opinion` tells the three apart: None = not asked; {"agree": True} = agreed;
    # {"agree": False} = DISAGREED; {"agree": None} = asked but no usable answer (failed / not run). Only an explicit
    # False moves the line; "not asked" and "failed" are neither agreement nor disagreement.
    second = line.get("second_opinion")
    if isinstance(second, Mapping) and second.get("agree") is False:
        return DISAGREE_WHY
    return None
