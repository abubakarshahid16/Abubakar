"""The CALCULATOR of the one reviewer (owner, 12 Nov 2026, STATE section 37; design `ONE-REVIEWER.md`): the old rule check's number and unit
comparisons, as a tool of the AI review.

"Its number comparisons and unit checks become a tool inside the AI review and appear as normal points in the one list."

PURE. Nothing here reads a database, calls a model or touches the network, and nothing calls it yet (the wiring is a later PR, behind its own
setting). It turns CASES into LINES (dicts the AI review's exit already understands: `agent_review_wording.final_cap`):

  * `numeric_line(case)`: one stored datasheet FACT against one numeric RULE, compared by `comparison.compare` (the one comparison, with the one number reader
    and the unit tables beneath it: no second number reader here);
  * `checklist_lines(...)`: the approved checklist's results, as `datasheet_checks.evaluate` gives them.

A line is "Proven by code" Pass or Fail ONLY when ALL of these hold; otherwise it is a Query that says why:
  1. the code compared a value: `compare` answered COMPLIANT or NON_COMPLIANT with BOTH a limit and an observed value, and no hold on it;
  2. the paper side has a page and a quote that code FOUND in the stored text of that page (`quote_found`);
  3. the clause side has a quote that code FOUND in the clause text (or, for the approved checklist, the approved entry's own wording);
  4. the value is not blank and not a placeholder.
`PROVEN_REQUIRES` names these; `can_be_proven(line)` re-checks them on any line (the exit and the tests use it). A fact whose quote does not
verify is NOT compared into a Pass or Fail: it is a Query with the reason (owner, 12 Nov 2026).

The strength of the rule travels with the line (`rule_kind`: "advice" for a recommendation), so the exit marks a "should" and the CRS and the
points list treat it as one. Words and ids only: no document text is logged here.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import agent_review_code_proof as proof
from . import agent_review_pass_guards as guards
from . import agent_review_verdict as verdict_mod
from . import comparison, hold_reason
from .reader_api import _fold

SOURCE = "code"
#: Item id prefix of every line made here (the model's lines are `R-` and `S-`).
ID_PREFIX = "C-"
#: What the sheet says of an approved checklist check, in plain words (no code word).
APPROVED_CHECKLIST = "Approved checklist"

PASS, FAIL, QUERY = verdict_mod.PASS, verdict_mod.FAIL, verdict_mod.QUERY
COMPLIANT, NON_COMPLIANT = comparison.COMPLIANT, comparison.NON_COMPLIANT

#: What a Pass or Fail made here rests on (for the docs, the tests and `can_be_proven`).
PROVEN_REQUIRES = (
    "the code compared a value (a limit and an observed value, no hold)",
    "the paper quote was found on its page by code",
    "the clause quote was found in the clause by code (or is the approved checklist's own wording)",
    "the value is not blank",
)


def quote_found(quote: object, text: object) -> bool:
    """Is the quote in the text, ignoring case and whitespace? An empty quote or text is never found."""
    q, t = _fold(str(quote or "")), _fold(str(text or ""))
    return bool(q) and bool(t) and q in t


value_near_label = proof.value_near_label  # one home: `agent_review_code_proof`


def _is_page(page: object) -> bool:
    return isinstance(page, int) and not isinstance(page, bool) and page >= 1


def _query(reason: str, code: str) -> dict:
    return {
        "verdict": QUERY,
        "decided_by": verdict_mod.BY_ENGINEER,
        "why": reason,
        "reason_code": code,
    }


def _paper_quote(fact: Mapping) -> str:
    """The text the fact came from: its source cell, else its raw value. The verifier decides whether it is on the page."""
    return str(fact.get("source_text") or fact.get("raw_value") or "").strip()


def requirement_from_item(item: Mapping) -> dict:
    """The requirement `comparison.compare` takes, from an AI-review rule item (`agent_review_items`): the comparator, value, unit, range, exceptions
    and condition the item carries from its stored rule row. Never invents a limit: an item with no figure gives a requirement with none, and
    `compare` answers "needs an engineer"."""
    value = item.get("value")
    return {
        "requirement_type": item.get("requirement_type") or "numeric_limit",
        "operator": item.get("comparator"),
        "raw_value": proof.stored_text(value) or None,
        "raw_unit": item.get("unit") or "",
        "value_low": item.get("value_low"),
        "value_high": item.get("value_high"),
        "standard_document_id": item.get("standard_document_id"),
        "exceptions": item.get("rule_exceptions"),
        "condition": item.get("rule_condition"),
        "table_row": item.get("table_row"),
        "requirement_text": item.get("question") or "",
        "source_text": item.get("question") or "",
    }


def _undecided(base: dict, why: str, code: str, reason: str | None = None) -> dict:
    """The line when the code did not decide: a Query with the reason in words, never a Pass or Fail."""
    note = (
        {"decided": False} if reason is None else {"decided": False, "reason": reason}
    )
    return {**base, **_query(why, code), "compare": note}


def _checks(base: dict, fact: Mapping, page_text: object, clause_text: object) -> dict:
    """The tests behind the two quote flags, each asked of the stored texts: found on the page, the value inside the quote, the quote sitting with the
    field's label, found in the clause, the limit inside the quote. `paper` and `clause` hold all of theirs together."""
    found = bool(
        _is_page(fact.get("page")) and quote_found(base["paper_quote"], page_text)
    )
    value = proof.paper_reason(base["proof_fact"], base["paper_quote"]) is None
    label = fact.get("field_label") or fact.get("field_name")
    field = bool(
        found
        and label
        and guards.belongs({"field_roles": [label]}, base["paper_quote"], page_text)[0]
    )
    c_found = quote_found(base["clause_quote"], clause_text)
    limit = proof.clause_reason(base["proof_requirement"], base["clause_quote"]) is None
    way = (
        proof.direction_reason(base["proof_requirement"], base["clause_quote"]) is None
    )
    return {
        "paper": found and value and field,
        "clause": c_found and limit and way,
        "paper_found": found,
        "paper_value": value,
        "field": field,
        "clause_found": c_found,
        "clause_limit": limit,
        "clause_direction": way,
    }


#: In the order they are asked: the flag that failed, the code, the words.
_QUOTE_FAILS = (
    ("paper_found", "paper_quote_unverified", "the value's quote was not found on its page, so it was not compared into a Pass or Fail"),
    ("paper_value", "paper_value_not_in_quote", "the quote from the paper does not state the value that was compared, with its unit, as a bare number"),
    ("field", "field_not_with_quote", "the quote from the paper does not sit with the field's label, on its line or the line above"),
    ("clause_found", "clause_quote_unverified", "the rule's quote was not found in its clause, so it was not compared into a Pass or Fail"),
    ("clause_limit", "clause_limit_not_in_quote", "the quote from the clause does not state the limit that was compared, with its unit"),
    ("clause_direction", "clause_direction_not_shown", "the clause's wording does not show the direction of the limit"),
)  # fmt: skip


def numeric_line(
    item: Mapping,
    requirement: Mapping,
    fact: Mapping | None,
    *,
    submittal_facts: list[dict] | None,
    page_text: str | None,
    clause_quote: str | None,
    clause_text: str | None,
    page_count: int | None = None,
) -> dict:
    """ONE line for one rule item and the fact paired with it. `page_text`: the stored text of the fact's page; `clause_quote`: the quote of the rule
    the line shows; `clause_text`: the clause's own text it must stand in. The caller pairs (`subject_pairing`) and fetches the texts; this decides,
    by `compare`, and proves the quotes (`agent_review_code_proof`): each must be found, carry the number it stands for, and the paper's sit with its label."""
    f = fact or {}
    base = {
        "item_id": f"{ID_PREFIX}{item.get('item_id')}" + (f"-{f.get('id')}" if f.get("id") else ""),
        "source": SOURCE,
        "code_kind": "numeric",
        "standard": item.get("standard"),
        "clause": item.get("clause"),
        "rule_kind": item.get("rule_kind"),
        "rule_version_id": item.get("rule_version_id"),
        "field": f.get("field_label") or f.get("field_name"),
        "field_roles": item.get("field_roles") or [],
        "equipment_tag": f.get("equipment_tag"),
        "clause_quote": clause_quote or "",
        "paper_quote": _paper_quote(fact) if fact else "",
        "paper_page": f.get("page"),
        "paper_context": proof.context_of(page_text, _paper_quote(fact)) if fact else "",
        "paper_page_count": page_count,
        "quotes_checked": {"paper": False, "clause": False},
        "proof_requirement": {k: requirement.get(k) for k in proof.REQUIREMENT_KEYS},
        "proof_fact": {"raw_value": f.get("raw_value"), "raw_unit": f.get("raw_unit")} if fact else None,
    }  # fmt: skip
    got = comparison.compare(
        dict(requirement), dict(fact) if fact else None, submittal_facts=submittal_facts
    )
    if fact is None:
        return _undecided(
            base, "no value read from the paper answers this rule", "no_fact"
        )
    if fact.get("is_blank"):
        return _undecided(base, "the value on the paper is blank", "blank_value")
    base["limit"], base["observed"] = got.get("limit"), got.get("observed")
    reason = str(got.get("rationale") or "")[:200]
    status = got.get("status")
    if status not in (COMPLIANT, NON_COMPLIANT) or not (
        got.get("limit") and got.get("observed")
    ):
        return _undecided(
            base, reason or "the code could not decide", "not_decided", reason
        )
    if got.get(hold_reason.KEY):
        return _undecided(base, reason or "held for an engineer", "held", reason)
    base["quotes_checked"] = checks = _checks(base, fact, page_text, clause_text)
    for key, code, why in _QUOTE_FAILS:
        if not checks[key]:
            return _undecided(base, why, code, reason)
    line = {
        **base,
        "verdict": PASS if status == COMPLIANT else FAIL,
        "decided_by": verdict_mod.BY_CODE,
        "compare": {"decided": True, "verdict": "meets" if status == COMPLIANT else "does_not_meet", "reason": reason},
    }  # fmt: skip
    if not proof.line_proven(
        line
    ):  # the exit's own ask, made here too: the line is never worse off at the exit than here
        return _undecided(
            base,
            "the proof was recomputed from the line's own texts and values and did not hold",
            "not_proven",
            reason,
        )
    return line


def checklist_lines(
    results: list[Mapping], *, page_texts: Mapping[int, str]
) -> list[dict]:
    """The approved checklist's results (`datasheet_checks.evaluate`: pure, code only) as lines. The clause side is the approved entry's own
    wording (`APPROVED_CHECKLIST`, the entry id as the clause): no document, so its quote is the entry itself. The paper quote must be found on
    its page. A result that is not a decided COMPLIANT or NON_COMPLIANT, or that was held, is a Query with its detail; a check that does not
    apply is not a line."""
    out: list[dict] = []
    for r in results:
        status = r.get("status")
        if status == comparison.NOT_APPLICABLE:
            continue
        fact_id = r.get("fact_id")
        value, page = r.get("value"), r.get("page")
        line = {
            "item_id": f"{ID_PREFIX}{r.get('rule_id')}"
            + (f"-{fact_id}" if fact_id else f"-{r.get('equipment_tag') or 'sheet'}"),
            "source": SOURCE,
            "code_kind": "checklist",
            "approved_checklist": True,
            "rule_id": r.get("rule_id"),
            "standard": r.get("standard") or APPROVED_CHECKLIST,
            "clause": r.get("clause") or r.get("rule_id"),
            "rule_kind": "limit",
            "field": r.get("field"),
            "equipment_tag": r.get("equipment_tag"),
            "clause_quote": str(r.get("text") or ""),
            "paper_quote": str(value or ""),
            "paper_page": page,
            "paper_page_count": max(
                (k for k in page_texts if _is_page(k)), default=None
            ),
            "quotes_checked": {
                "paper": bool(
                    _is_page(page)
                    and value_near_label(r.get("field"), value, page_texts.get(page))
                ),
                "clause": bool(
                    str(r.get("text") or "").strip()
                ),  # the approved entry's own wording: nothing outside it to check against
            },
        }
        detail = str(r.get("detail") or "")[:200]
        decided = (
            status in (COMPLIANT, NON_COMPLIANT)
            and not r.get(hold_reason.KEY)
            and bool(fact_id)
            and bool(value)
        )
        if not decided:
            out.append(
                {
                    **line,
                    **_query(detail or "the check could not decide", "not_decided"),
                    "compare": {"decided": False, "reason": detail},
                }
            )
        elif not line["quotes_checked"]["paper"]:
            out.append({**line, **_query("the value's quote was not found on its page, so it was not compared into a Pass or Fail", "paper_quote_unverified"),
                        "compare": {"decided": False, "reason": detail}})  # fmt: skip
        else:
            met = status == COMPLIANT
            out.append({**line, "verdict": PASS if met else FAIL, "decided_by": verdict_mod.BY_CODE,
                        "compare": {"decided": True, "verdict": "meets" if met else "does_not_meet", "reason": detail}})  # fmt: skip
    return out


def can_be_proven(line: Mapping) -> bool:
    """Re-check, on ANY code line, what `PROVEN_REQUIRES` says (the exit's own check: `agent_review_wording.code_line_proven`)."""
    return proof.line_proven(line)
