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

from . import agent_review_approved_code as approved_code
from . import agent_review_code_proof as proof
from . import agent_review_pass_guards as guards
from . import agent_review_verdict as verdict_mod
from . import comparison, hold_reason, table_cell
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


def _checks(
    base: dict,
    fact: Mapping,
    page_text: object,
    clause_text: object,
    cell: table_cell.Cell | None = None,
) -> dict:
    """The tests behind the two quote flags, each asked of the stored texts: found on the page, the value inside the quote, the quote sitting with the
    field's label, found in the clause, the limit inside the quote. `paper` and `clause` hold all of theirs together."""
    # a located cell: the quote is the row's own two cells, each found on the page (`table_cell.in_page`); the label is the row's own cell
    found = bool(
        _is_page(fact.get("page"))
        and (
            table_cell.in_page(cell, page_text)
            if cell
            else quote_found(base["paper_quote"], page_text)
        )
    )
    value = proof.paper_reason(base["proof_fact"], base["paper_quote"]) is None
    label = fact.get("field_label") or fact.get("field_name")
    field = bool(
        found
        and label
        and (
            cell is not None
            or guards.belongs({"field_roles": [label]}, base["paper_quote"], page_text)[
                0
            ]
        )
    )
    c_found = quote_found(base["clause_quote"], clause_text)
    limit = proof.clause_reason(base["proof_requirement"], base["clause_quote"]) is None
    subject = (
        proof.subject_reason(
            base["rule_field"], base["proof_requirement"], base["clause_quote"]
        )
        is None
    )
    way = (
        proof.direction_reason(base["proof_requirement"], base["clause_quote"]) is None
    )
    return {
        "paper": found and value and field,
        "clause": c_found and limit and way and subject,
        "paper_found": found,
        "paper_value": value,
        "field": field,
        "clause_found": c_found,
        "clause_limit": limit,
        "clause_direction": way,
        "clause_subject": subject,
    }


#: In the order they are asked: the flag that failed, the code, the words.
_QUOTE_FAILS = (
    ("paper_found", "paper_quote_unverified", "the value's quote was not found on its page, so it was not compared into a Pass or Fail"),
    ("paper_value", "paper_value_not_in_quote", "the quote from the paper does not state the value that was compared, with its unit, as a bare number"),
    ("field", "field_not_with_quote", "the quote from the paper does not sit with the field's label, on its line or the line above"),
    ("clause_found", "clause_quote_unverified", "the rule's quote was not found in its clause, so it was not compared into a Pass or Fail"),
    ("clause_limit", "clause_limit_not_in_quote", "the quote from the clause does not state the limit that was compared, with its unit"),
    ("clause_direction", "clause_direction_not_shown", "the clause's wording does not show the direction of the limit"),
    ("clause_subject", "clause_subject_not_the_field", "the clause's wording does not make the field the subject of the limit"),
)  # fmt: skip


def _numeric_base(
    item: Mapping,
    requirement: Mapping,
    fact: Mapping | None,
    clause_quote: str | None,
    page_count: int | None,
    cell,
    document_id: str | None,
) -> dict:
    """The numeric line before it is decided: what it is about and what it rests on (the exit asks the proof again from the page itself)."""
    f = fact or {}
    return {
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
        "paper_quote": cell.quote if cell else (_paper_quote(fact) if fact else ""),
        "paper_page": f.get("page"),
        "paper_document_id": document_id,
        "rule_field": (guards.field_names(item) or [None])[0],
        "paper_page_count": page_count,
        "cell_ref": cell.ref() if cell else None,
        "cell_label": cell.label_text if cell else None,
        "cell_note": cell.split if cell else None,
        "quotes_checked": {"paper": False, "clause": False},
        "proof_requirement": {k: requirement.get(k) for k in proof.REQUIREMENT_KEYS},
        "proof_fact": {"raw_value": f.get("raw_value"), "raw_unit": f.get("raw_unit")} if fact else None,
    }  # fmt: skip


def column_not_the_rules(base: Mapping, cell: table_cell.Cell | None) -> str | None:
    """Plain words when the value sits in a column that is not clearly the rule's, else None:
    (1) the column header marks another state of the value (previous, old, superseded, a revision): "the value is under the column '<header>'";
    (2) the rule names a condition (design, operating, normal ...) that neither the label nor the header carries: "the table column is <header>; the rule asks for <word>";
    (3) the rule names none, and the header names one, in a table with more than one such column: "the table column is <header>; the rule does not say which".
    None when the value has no cell, no header marks it, or the label carries the rule's word."""
    if not cell:
        return None
    if table_cell.stale_header(cell.header):
        return f"the value is under the column '{cell.header}'"
    asked = table_cell.condition_words(base.get("rule_field"))
    named = table_cell.condition_words(cell.header)
    if asked:
        if asked & (named | table_cell.condition_words(base.get("field"))):
            return None
        return f"the table column is {cell.header or 'not named'}; the rule asks for {' / '.join(sorted(asked))}"
    if (
        named
        and cell.conditions_in_header_row > 1
        and not table_cell.condition_words(base.get("field"))
    ):
        return f"the table column is {cell.header}; the rule does not say which"
    return None


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
    cell: table_cell.Cell | None = None,
    document_id: str | None = None,
) -> dict:
    """ONE line for one rule item and the fact paired with it. `page_text`: the stored text of the fact's page; `clause_quote`: the quote of the rule
    the line shows; `clause_text`: the clause's own text it must stand in. The caller pairs (`subject_pairing`) and fetches the texts; this decides,
    by `compare`, and proves the quotes (`agent_review_code_proof`): each must be found, carry the number it stands for, and the paper's sit with its label."""
    base = _numeric_base(
        item, requirement, fact, clause_quote, page_count, cell, document_id
    )
    got = comparison.compare(
        dict(requirement), dict(fact) if fact else None, submittal_facts=submittal_facts
    )
    if fact is None:
        return _undecided(
            base, "no value read from the paper answers this rule", "no_fact"
        )
    if fact.get("is_blank"):
        return _undecided(base, "the value on the paper is blank", "blank_value")
    # two readings in one tag, named with the table cell beside the label: a question, never a value
    if fact.get("reading_conflict"):
        return _undecided(base, str(fact["reading_conflict"]), "reading_conflict")
    if (why := column_not_the_rules(base, cell)) is not None:
        return _undecided(base, why, "column_not_the_rules")
    base["limit"], base["observed"] = got.get("limit"), got.get("observed")
    reason = " ".join(
        str(got.get("rationale") or "").split()
    )  # WHOLE (order 14 W-C6: it was cut at 200 characters, no mark)
    status = got.get("status")
    if status not in (COMPLIANT, NON_COMPLIANT) or not (
        got.get("limit") and got.get("observed")
    ):
        return _undecided(
            base, reason or "the code could not decide", "not_decided", reason
        )
    if got.get(hold_reason.KEY):
        return _undecided(base, reason or "held for an engineer", "held", reason)
    base["quotes_checked"] = checks = _checks(base, fact, page_text, clause_text, cell)
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


def _checklist_base(
    r: Mapping,
    cell: table_cell.Cell | None,
    page_texts: Mapping[int, str],
    document_id: str | None,
) -> dict:
    """A checklist result as a line before it is decided: the approved entry is its own clause; the quote is the value's cell, else the value."""
    fact_id, value, page = r.get("fact_id"), r.get("value"), r.get("page")
    on_page = _is_page(page) and (
        table_cell.in_page(cell, page_texts.get(page))
        and proof.states(value, "", cell.quote)
        if cell
        else value_near_label(r.get("field"), value, page_texts.get(page))
    )
    tag = r.get("equipment_tag")
    return {
        "item_id": f"{ID_PREFIX}{r.get('rule_id')}"
        + (f"-{fact_id}" if fact_id else f"-{tag or 'sheet'}"),
        "source": SOURCE,
        "code_kind": "checklist",
        "approved_checklist": True,
        "rule_id": r.get("rule_id"),
        "standard": r.get("standard") or APPROVED_CHECKLIST,
        "clause": r.get("clause") or r.get("rule_id"),
        "rule_kind": "limit",
        "field": r.get("field"),
        "equipment_tag": tag,
        "clause_quote": str(r.get("text") or ""),
        "paper_quote": cell.quote if cell else str(value or ""),
        "cell_ref": cell.ref() if cell else None,
        "cell_label": cell.label_text if cell else None,
        "cell_note": cell.split if cell else None,
        "paper_page": page,
        "paper_document_id": document_id,
        "paper_value": value,
        "paper_page_count": max((k for k in page_texts if _is_page(k)), default=None),
        # the clause side is the approved entry's own wording: nothing outside it to check against
        "quotes_checked": {
            "paper": bool(on_page),
            "clause": bool(str(r.get("text") or "").strip()),
        },
    }


#: The words an AI-draft checklist line carries (order 14, lane A): the limit was written from the stored book by an AI and no engineer
#: has confirmed it, so code shows what it compared and the line stays a question (CLAUDE.md rule 4).
AI_DRAFT_WORDS = "AI draft, engineer to confirm"


def ai_draft_ids() -> frozenset[str]:
    """The checklist entries marked `ai_draft` in the checklist data: their lines are never a Pass or Fail, whatever the comparison said.
    Read each time (a small file): a failed read marks nothing, and `datasheet_checks` refuses the same broken file loudly."""
    from . import datasheet_checks

    try:
        table = datasheet_checks.load_rules().get("checklists") or {}
    except (OSError, ValueError):
        return frozenset()
    return frozenset(
        item["id"]
        for entry in table.values()
        if isinstance(entry, Mapping)
        for item in entry.get("items") or []
        if isinstance(item, Mapping)
        and item.get("ai_draft")
        and isinstance(item.get("id"), str)
    )


def presence_counts(results: list[Mapping]) -> dict:
    """How the checks that only ask a field be STATED came out: checked, stated (they make no line), missing (each is already its own Query line)."""
    only = approved_code.presence_only_ids()
    mine = [
        r
        for r in results
        if r.get("rule_id") in only and r.get("status") != comparison.NOT_APPLICABLE
    ]
    stated = sum(1 for r in mine if r.get("status") == COMPLIANT)
    return {
        "presence_checked": len(mine),
        "presence_stated": stated,
        "presence_missing": len(mine) - stated,
    }


def checklist_lines(
    results: list[Mapping],
    *,
    page_texts: Mapping[int, str],
    cells: Mapping[str, table_cell.Cell] | None = None,
    document_id: str | None = None,
    books=None,
) -> list[dict]:
    """The approved checklist's results (`datasheet_checks.evaluate`: pure, code only) as lines. The clause side is the approved entry's own
    wording (`APPROVED_CHECKLIST`, the entry id as the clause): no document, so its quote is the entry itself. The paper quote must be found on
    its page. A result not decided (COMPLIANT or NON_COMPLIANT), or held, is a Query with its detail; a check that does not apply is no line."""
    out: list[dict] = []
    presence_only = approved_code.presence_only_ids()
    drafts = ai_draft_ids()
    for r in results:
        if r.get("rule_id") in drafts:
            # an AI-draft limit the value meets is not a proven Pass and asks nothing: no line (like a presence check that is stated)
            if (r.get("rule_said") or r.get("status")) not in (
                comparison.NOT_APPLICABLE,
                COMPLIANT,
            ):
                out.append(_ai_draft_line(r, page_texts, cells, document_id))
            continue
        status = r.get("status")
        if status == comparison.NOT_APPLICABLE:
            continue
        if status == COMPLIANT and r.get("rule_id") in presence_only:
            continue  # "stated" compares no value: not a proven Pass, and nothing to ask the engineer
        fact_id = r.get("fact_id")
        value = r.get("value")
        cell = (
            (cells or {}).get(str(fact_id)) if fact_id else None
        )  # its quote: the row's two cells
        line = _checklist_base(r, cell, page_texts, document_id)
        detail = " ".join(
            str(r.get("detail") or "").split()
        )  # WHOLE (order 14 W-C6: cut at 200 characters, no mark)
        decided = (
            status in (COMPLIANT, NON_COMPLIANT)
            and not r.get(hold_reason.KEY)
            and bool(fact_id)
            and bool(value)
        )
        if not decided:
            out.append(
                _undecided(
                    line, detail or "the check could not decide", "not_decided", detail
                )
            )
        elif not line["quotes_checked"]["paper"]:
            out.append(
                _undecided(
                    line,
                    "the value's quote was not found on its page, so it was not compared into a Pass or Fail",
                    "paper_quote_unverified",
                    detail,
                )
            )
        else:
            met = status == COMPLIANT
            out.append({**line, "verdict": PASS if met else FAIL, "decided_by": verdict_mod.BY_CODE,
                        "compare": {"decided": True, "verdict": "meets" if met else "does_not_meet", "reason": detail}})  # fmt: skip
    return out if books is None else [with_book(ln, books) for ln in out]


#: How a line names a book the library does not hold (order 14: "book missing", never guessed).
BOOK_MISSING = "book missing: "


def with_book(line: Mapping, books) -> dict:
    """The checklist line with its book's own words (order 14, lane A). `books.cite(standard, clause)` (`agent_review_checklist_books`)
    gives the held clause's stored text found by code in the book's pages, or that the book is held but no such text was found, or
    that the book is not held. The entry's own wording moves to `check_words` and is never shown as the book's quote; a book not held
    shows no clause and no rule words, and its line is never a Pass or Fail."""
    standard = line.get("standard")
    got = (
        books.cite(standard, line.get("clause"))
        if standard and standard != APPROVED_CHECKLIST
        else {}
    )
    if not got:
        return dict(line)
    out = {
        **line,
        "check_words": line.get("check_words") or line.get("clause_quote") or "",
    }
    checks = {**(line.get("quotes_checked") or {})}
    if got.get("missing"):
        out.update(standard=f"{BOOK_MISSING}{got['missing']}", clause="", clause_quote="", book_missing=got["missing"],
                   quotes_checked={**checks, "clause": False})  # fmt: skip
        if out.get("verdict") in (PASS, FAIL):
            reason = (out.get("compare") or {}).get("reason")
            why = f"the book {got['missing']} is not held, so its rule is not shown or decided"
            out = _undecided(out, why, "not_decided", reason)
        return out
    out.update(clause_quote=got.get("quote") or "", clause_page=got.get("page"), standard_document_id=got.get("book_id"),
               quotes_checked={**checks, "clause": bool(got.get("quote"))})  # fmt: skip
    return out


def _ai_draft_line(r: Mapping, page_texts, cells, document_id) -> dict:
    """An AI-draft checklist result as a Query: what code compared, in its own words, behind `AI_DRAFT_WORDS`. Never a Pass or Fail."""
    fact_id = r.get("fact_id")
    cell = (cells or {}).get(str(fact_id)) if fact_id else None
    line = _checklist_base(r, cell, page_texts, document_id)
    detail = " ".join(
        str(r.get("detail") or "").split()
    )  # WHOLE (order 14 W-C6: cut at 200 characters, no mark)
    said = r.get("rule_said") or r.get("status")
    out = _undecided(
        line,
        f"{AI_DRAFT_WORDS}: {detail or 'the check could not decide'}",
        "not_decided",
        detail,
    )
    # the entry is written in our own words, not the book's: never shown as the standard's quote (gate G1), kept under its own key
    out["check_words"], out["clause_quote"] = out.get("clause_quote") or "", ""
    out["quotes_checked"] = {**out["quotes_checked"], "clause": False}
    out["ai_draft"] = True
    out["compare"] = {**out["compare"], "code_said": said}
    return out


def can_be_proven(line: Mapping) -> bool:
    """Re-check, on ANY code line, what `PROVEN_REQUIRES` says (the exit's own check: `agent_review_wording.code_line_proven`)."""
    return proof.line_proven(line)
