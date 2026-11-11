"""CRS files of the AI reviewer: the internal and the contractor workbook (ported from the experiment's exp11/crs_lines.py).

Own xlsx writer (crs_export.py is not touched). Every line shows: the verdict in plain words (Pass, Fail, "AI thinks: met",
"AI thinks: not met" or Query for the engineer); "AI verdict" with the model id the API RESPONSE reported (never a configured
name), or "decided by code" for a number line; the AI's reasoning in one or two plain sentences; the paper quote with its page;
the clause quote with its clause and page; whether code checked both quotes; and a failed AI call. The top of every sheet says
"AI review, engineer to confirm".

Workbooks:
  internal     sheet "CRS": Fail and Query lines in the classic layout (8 heading rows, then the column headings); the summary
               lines of the rules left out and the rule books NOT held (never counted against the system). "Passed" sheet:
               Pass lines. Sheets for held AI "met" lines, not-applicable lines and rules not yet approved. "Run": counts.
  contractor   sheet "CRS": proven Fail lines ONLY (never an "AI thinks" line, never a "should" line, never a rule that is not
               approved), the comment only: no reasoning, model, quotes or queries.
  comment-only the Fail and Query lines with the classic ten columns, for scoring beside the classic engine.

DEFENCE IN DEPTH: every writer REFUSES (UnprovenLineRefused) a line that is Pass or Fail without a tier of owner, engineer or AI
approved on it. Lines get their tier from `agent_review_wording.final_cap`, which every line passes before any output.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import agent_review_wording as wording
from .agent_review_verdict import (
    BY_ABSENCE,
    BY_AI,
    BY_CODE,
    BY_FINAL_CHECK,
    FAIL,
    PASS,
    QUERY,
)
from .agent_run_crs import _cell, _page_cell


class UnprovenLineRefused(ValueError):
    """A writer was handed a Pass or Fail line whose rule tier is not owner, engineer or AI approved."""


def _refuse_unproven(lines: Iterable[Mapping]) -> None:
    for ln in lines:
        why = wording.writer_refusal(ln)
        if why:
            raise UnprovenLineRefused(f"{ln.get('item_id')}: {why}")


TOP_TEXT = "AI review, engineer to confirm"
CRS_SHEET = "CRS"
PASSED_SHEET = "Passed - engineer to tick"
NOT_APPLICABLE_SHEET = (
    "Not applicable (AI, to confirm)"  # Excel: 31 characters at most, no colon
)
UNAPPROVED_SHEET = "Rules not yet approved"  # Excel: 31 characters at most
UNAPPROVED_NOTE = (
    "AI opinion, rule not yet approved. The rule is not AI approved: never a Pass or a Fail, never sent to the "
    "contractor. Not CRS comments."
)
NOT_REVIEWED_SHEET = "Not reviewed"
NOT_REVIEWED_NOTE = (
    "The AI call failed or its answer was cut off: these lines were NOT reviewed (nothing is said about the paper). "
    "Not CRS comments."
)
NOT_APPLICABLE_NOTE = "Not applicable (AI, engineer to confirm). Not CRS comments."
HELD_PASS_SHEET = "AI met, not proven by code"  # Excel: 31 characters at most, no colon
HELD_PASS_NOTE = (
    "AI says met, not proven by code: engineer to tick. The gate reason is in the comment and the "
    "Quotes checked column. Not CRS comments."
)
RUN_SHEET = "Run"
HEADING_ROWS = 8  # the old engine's CRS: 8 rows above the column headings
OLD_HEADERS = (
    "Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By", "Contractor's Response",
    "Final Resolution", "Standard Reference", "Priority", "AI Review Comments",
)  # fmt: skip
INTERNAL_HEADERS = (
    "Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Comment By", "Contractor's Response",
    "Final Resolution", "Standard Reference", "Priority", "Verdict", "Reason code", "AI reasoning", "Paper quote (page)",
    "Clause quote (clause, page)", "Quotes checked by code", "AI call",
)  # fmt: skip
CONTRACTOR_HEADERS = (
    "Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Contractor's Response", "Final Resolution",
    "Standard Reference",
)  # fmt: skip
VERDICT_WORDS = {PASS: "Pass", FAIL: "Fail", QUERY: "Query for the engineer"}
MAX_REASON_SENTENCES = 2
MAX_REASON_WORDS = 60
MAX_COMMENT_WORDS = 40


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def two_sentences(text: Any) -> str:
    """The AI's reasoning cut to at most two sentences and MAX_REASON_WORDS words."""
    parts = re.split(r"(?<=[.!?])\s+", _clean(text))
    out = " ".join(p for p in parts[:MAX_REASON_SENTENCES] if p)
    words = out.split()
    if len(words) > MAX_REASON_WORDS:
        out = " ".join(words[:MAX_REASON_WORDS]).rstrip(".,;") + "."
    return out


def _sentence(text: Any, limit: int = MAX_COMMENT_WORDS) -> str:
    words = _clean(text).split()[:limit]
    s = " ".join(words).rstrip(" .;,")
    return s + "." if s else ""


def field_words(line: Mapping) -> str:
    """The field in plain words: the label as printed on the paper (only when code found it on a sent page), else the
    item's field roles with underscores as spaces, else the rule it checks ("<standard> clause <n>"), else the id."""
    label = _clean(line.get("field"))
    if label:
        return label
    roles = [
        r.replace("_", " ").strip()
        for r in line.get("field_roles") or []
        if str(r).strip()
    ]
    return ", ".join(roles) or against(line) or str(line.get("item_id") or "item")


def line_page(line: Mapping) -> int | None:
    page = line.get("paper_page")
    if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
        return page
    hints = [
        p
        for p in line.get("page_hint") or []
        if isinstance(p, int) and not isinstance(p, bool) and p >= 1
    ]
    return hints[0] if hints else None


def against(line: Mapping) -> str:
    std, clause = _clean(line.get("standard")), _clean(line.get("clause"))
    return " ".join(x for x in (std, f"clause {clause}" if clause else "") if x)


MAX_QUOTE_WORDS = 14
MAX_ASK_WORDS = 30


def _short(text: Any, limit: int) -> str:
    words = _clean(text).split()
    return " ".join(words[:limit]) + (" ..." if len(words) > limit else "")


def asks(line: Mapping) -> str:
    """What the requirement asks, in the held words: the clause quote when code verified it, else the stored
    requirement text of the rule; nothing when neither is held (never invented)."""
    q = line.get("quotes_checked") or {}
    text = line.get("clause_quote") if q.get("clause") else line.get("requirement")
    return _short(text, MAX_ASK_WORDS) if _clean(text) else ""


def stated(line: Mapping) -> str:
    """What the sheet states, in its own words: the paper quote only when code found it on the page."""
    q = line.get("quotes_checked") or {}
    return (
        _short(line.get("paper_quote"), MAX_QUOTE_WORDS)
        if q.get("paper") and _clean(line.get("paper_quote"))
        else ""
    )


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
MIN_ASK_WORDS = 3


def _first_sentence(text: Any) -> str:
    parts = re.split(r"(?<=[.!?])\s+", _clean(text))
    return _sentence(parts[0], MAX_ASK_WORDS) if parts and parts[0] else ""


def ai_ask(line: Mapping, contractor: bool = False) -> str:
    """The AI's own ask in ONE plain sentence: its comment (what to correct or provide), else - on the INTERNAL copy
    only - the first sentence of its reasoning. The contractor copy never carries reasoning (`contractor=True`).
    Refused when it has fewer than MIN_ASK_WORDS words, or carries a number that is not in a quote code VERIFIED (the
    paper quote or the clause quote): never a value the checked quotes do not hold."""
    q = line.get("quotes_checked") or {}
    held = " ".join(
        _clean(x)
        for x in (
            line.get("paper_quote") if q.get("paper") else "",
            line.get("clause_quote") if q.get("clause") else "",
        )
    )
    held_numbers = set(_NUMBER.findall(held))
    sources = (
        (line.get("comment"),)
        if contractor
        else (line.get("comment"), line.get("reasoning"))
    )
    for candidate in (_first_sentence(x) for x in sources):
        if len(candidate.split()) < MIN_ASK_WORDS:
            continue
        if set(_NUMBER.findall(candidate)) <= held_numbers:
            return candidate
    return ""


def is_held_pass(line: Mapping) -> bool:
    """An AI Pass the gate held (quote, length, second opinion, ...): not a comment, ticked by the engineer on its own
    sheet. A Pass held because the value is marked deferred on the sheet IS a comment and stays on the CRS."""
    return (
        line.get("ai_verdict") == PASS
        and line.get("verdict") == QUERY
        and line.get("reason_code") != "value_deferred"
    )


def is_not_applicable(line: Mapping) -> bool:
    """A Query the AI marked not_applicable: not a comment; it goes to its own internal sheet."""
    return line.get("verdict") == QUERY and line.get("reason_code") == "not_applicable"


def company_comment(line: Mapping, contractor: bool = False) -> str:
    """The COMPANY Comments cell, in plain words: the field, the page, what the requirement asks, and what is wrong,
    missing or to be confirmed. Built from the item, the reason code and the code-checked quotes; no reasoning, and
    never a value that is not quoted."""
    if line.get("recommendation") and not line.get(
        "_recommended"
    ):  # order 12: a 'should' rule, marked
        return "Recommendation (should, not shall): " + company_comment(
            {**line, "_recommended": True}, contractor
        )
    page = line_page(line)
    where = f"{field_words(line)} (page {page})" if page else field_words(line)
    rule = against(line) or "the requirement"
    ask = asks(line)
    req = f'{rule} asks: "{ask}"' if ask else f"see {rule}"
    has = stated(line)
    code = line.get("reason_code")
    verdict = line.get("verdict")
    searched = ", ".join(str(p) for p in line.get("pages_searched") or [])
    said = ai_ask(line, contractor)

    def then(fixed: str) -> str:
        return said or fixed

    if verdict == PASS:
        return (
            f'{where}: the sheet states "{has}", which meets {rule}.'
            if has
            else f"{where}: meets {rule}."
        )
    if code == "value_deferred":
        at = (
            f" on page {line.get('deferred_page')}" if line.get("deferred_page") else ""
        )
        return (
            f"{where}: the sheet marks this value as not final{at} (by contractor / to be advised). {req}. "
            + then("Provide the final value.")
        )
    if verdict == FAIL and line.get("decided_by") == BY_CODE:
        head = (
            f'{where}: the stated value "{has}" does not meet {rule}'
            if has
            else f"{where}: does not meet {rule}"
        )
        return f"{head}. {req}." + (f" {said}" if said else "")
    if code in ("absent", "absent_pages_not_named") or (verdict == FAIL and not has):
        pages = f" (pages searched: {searched})" if searched else ""
        return f"{where}: not shown on the sheet{pages}. {req}. " + then("Provide it.")
    if verdict == FAIL:
        return (
            f'{where}: the sheet states "{has}", which does not meet {rule}. {req}.'
            + (f" {said}" if said else "")
        )
    if code == "ai_call_failed":
        return f"{where}: confirm compliance with {rule}. {req}. (Not reviewed: the AI call failed.)"
    if code == "sheet_silent":
        return f"{where}: the sheet does not state this. {req}. " + then("Confirm.")
    if code == "needs_drawing_or_calc":
        return f"{where}: cannot be checked from the sheet alone. {req}. " + then(
            "Provide the drawing or calculation that shows it."
        )
    if code == "not_applicable":
        return f"{where}: the AI judged {rule} not applicable to this paper. Engineer to confirm."
    if has:
        return f'{where}: the sheet states "{has}"; confirm it meets {rule}. {req}.' + (
            f" {said}" if said else ""
        )
    return f"{where}: confirm compliance with {rule}. {req}." + (
        f" {said}" if said else ""
    )


def comment_by(line: Mapping) -> str:
    """'AI verdict (<model from the response>)', 'Decided by code' or 'Query for the engineer'."""
    if wording.is_opinion(line):
        return f"{line['verdict_label']} ({line['verdict_class']})"
    if line.get("verdict") == QUERY:
        return "Query for the engineer"
    if line.get("decided_by") == BY_CODE:
        return "Decided by code"
    model = _clean(line.get("model")) or "model not reported"
    if line.get("decided_by") in (BY_ABSENCE, BY_FINAL_CHECK):
        return f"{line.get('decided_by')} ({model})"
    return f"{BY_AI} ({model})"


def verdict_cell(line: Mapping) -> str:
    cell = _verdict_cell(line)
    return f"{cell}; Recommendation (should)" if line.get("recommendation") else cell


def _verdict_cell(line: Mapping) -> str:
    if wording.is_opinion(
        line
    ):  # order 12: never "Pass" or "Fail" for what code did not prove
        return f"{line['verdict_label']} ({line['verdict_class']}); not proven by code: {_clean(line.get('not_proven_reason'))}"
    word = VERDICT_WORDS.get(line.get("verdict"), VERDICT_WORDS[QUERY])
    if line.get("decided_by") == BY_CODE and line.get("verdict") in (PASS, FAIL):
        return f"{word}, decided by code"
    if line.get("decided_by") == BY_AI and line.get("verdict") in (PASS, FAIL):
        return f"{word}, {BY_AI} ({_clean(line.get('model')) or 'model not reported'})"
    if line.get("decided_by") == BY_ABSENCE and line.get("verdict") == FAIL:
        return f"{word}, {BY_ABSENCE} ({_clean(line.get('model')) or 'model not reported'})"
    if line.get("decided_by") == BY_FINAL_CHECK and line.get("verdict") in (PASS, FAIL):
        return f"{word}, {BY_FINAL_CHECK} ({_clean(line.get('model')) or 'model not reported'})"
    return word


def reason_cell(line: Mapping) -> str | None:
    """The reason code (the AI's from a closed list, or code's own), with the searched pages for 'absent'."""
    code = _clean(line.get("reason_code"))
    if not code:
        return None
    pages = [str(p) for p in line.get("pages_searched") or []]
    return (
        f"{code} (pages searched {', '.join(pages)})"
        if code.startswith("absent") and pages
        else code
    )


def paper_quote_cell(line: Mapping) -> str | None:
    quote = _clean(line.get("paper_quote"))
    if not quote:
        return None
    page = line.get("paper_page")
    return f"{quote} (page {page})" if page not in (None, "") else quote


def clause_quote_cell(line: Mapping) -> str | None:
    quote = _clean(line.get("clause_quote"))
    if not quote:
        return None
    ref = against(line) or "clause"
    page = line.get("clause_page")
    return f"{quote} ({ref}{f', page {page}' if page not in (None, '') else ''})"


def quotes_checked_cell(line: Mapping) -> str:
    q = line.get("quotes_checked") or {}
    paper, clause = bool(q.get("paper")), bool(q.get("clause"))
    if paper and clause:
        return "Yes: code checked both quotes"
    return f"No: paper quote {'checked' if paper else 'not checked'}, clause quote {'checked' if clause else 'not checked'}"


def ai_call_cell(line: Mapping) -> str:
    err = _clean(line.get("error"))
    return f"AI call failed: {err}" if err else "AI call answered"


def internal_row(line: Mapping, paper: str) -> list:
    return [
        line.get("item_id"),
        paper,
        _page_cell(line_page(line)),
        company_comment(line),
        comment_by(line),
        None,
        None,
        against(line) or None,
        line.get("priority"),
        verdict_cell(line),
        reason_cell(line),
        two_sentences(line.get("reasoning")) or None,
        paper_quote_cell(line),
        clause_quote_cell(line),
        quotes_checked_cell(line),
        ai_call_cell(line),
    ]


def held_row(line: Mapping, paper: str) -> list:
    """A held AI Pass: the comment cell says what the AI found and why code did not accept it."""
    row = internal_row(line, paper)
    has = stated(line)
    says = line.get("verdict_label") or "AI says met"
    row[3] = (
        f"{field_words(line)}: {says} ({against(line) or 'the requirement'})"
        + (f'; the sheet states "{has}"' if has else "")
        + f". Not proven by code: {_clean(line.get('why'))}."
    )
    return row


def contractor_row(line: Mapping, paper: str) -> list:
    """The comment only: no reasoning, no model, no quotes, no verdict words."""
    return [
        line.get("item_id"),
        paper,
        _page_cell(line_page(line)),
        company_comment(line, contractor=True),
        None,
        None,
        against(line) or None,
    ]


def old_row(line: Mapping, paper: str) -> list:
    # the comment-only copy is scored as contractor-visible text: the contractor wording (no reasoning)
    return [
        line.get("item_id"),
        paper,
        _page_cell(line_page(line)),
        company_comment(line, contractor=True),
        comment_by(line),
        None,
        None,
        against(line) or None,
        line.get("priority"),
        None,
    ]


def _heading(ws, meta: Mapping, sheet_note: str) -> None:
    """The 8 heading rows (each under 5 filled cells, so the scorer never counts them as comment rows)."""
    rows = [
        [TOP_TEXT],
        ["COMMENT RESOLUTION SHEET"],
        ["Paper:", meta.get("paper")],
        [
            "Lead model (from the API response):",
            ", ".join(meta.get("lead_models") or []) or "not reported",
        ],
        [
            "Second opinion model (from the API response):",
            ", ".join(meta.get("second_models") or []) or "none",
        ],
        ["Run:", meta.get("run_id"), "Date:", meta.get("date")],
        [sheet_note],
        [],
    ]
    for r in rows[:HEADING_ROWS]:
        ws.append([_cell(v) for v in r])


def _sheet(
    wb,
    title: str,
    meta: Mapping,
    note: str,
    headers: Iterable[str],
    rows: Iterable[list],
    first: bool = False,
):
    ws = wb.active if first else wb.create_sheet(title)
    ws.title = title
    _heading(ws, meta, note)
    ws.append(list(headers))
    for r in rows:
        ws.append([_cell(v) for v in r])
    return ws


def _wb():
    import openpyxl

    return openpyxl.Workbook()


def _rule_summary(ws_crs, block: Mapping | None) -> None:
    """The rules not asked (counts, one summary line each) and the rule books the library does not hold."""
    if not block:
        return
    ws_crs.append([])
    for text in block.get("summary_lines") or []:
        ws_crs.append([_cell(text)])
    held_books = block.get("missing_rule_books") or []
    if held_books:
        ws_crs.append(
            [
                _cell(
                    "Rule books not held by the library (not counted against the system, excluded from "
                    "every score):"
                )
            ]
        )
        for b in held_books:
            ws_crs.append([_cell(f"{b.get('rule_book')} ({b.get('why')})")])


def _run_sheet(wb, all_lines: list[Mapping], meta: Mapping) -> None:
    ws = wb.create_sheet(RUN_SHEET)
    ws.append([TOP_TEXT])
    counts = {**run_counts(all_lines), **(meta.get("order12_counts") or {})}
    for key, value in counts.items():
        ws.append(
            [key, _cell(value if not isinstance(value, (dict, list)) else str(value))]
        )


def write_internal(lines: list[Mapping], path: str | Path, meta: Mapping) -> Path:
    _refuse_unproven(lines)
    paper = str(meta.get("paper") or "")
    all_lines = lines
    unapproved = [
        ln for ln in lines if wording.is_unapproved(ln)
    ]  # their own sheet, off the CRS and off every Pass list
    not_reviewed = [
        ln
        for ln in lines
        if wording.is_not_reviewed(ln) and not wording.is_unapproved(ln)
    ]  # their own sheet: never a CRS comment, never a verdict
    lines = [
        ln
        for ln in lines
        if not wording.is_unapproved(ln) and not wording.is_not_reviewed(ln)
    ]
    problems = [
        ln
        for ln in lines
        if ln.get("verdict") in (FAIL, QUERY)
        and not is_not_applicable(ln)
        and not is_held_pass(ln)
    ]
    held = [ln for ln in lines if is_held_pass(ln)]
    passed = [ln for ln in lines if ln.get("verdict") == PASS]
    not_applicable = [ln for ln in lines if is_not_applicable(ln)]
    wb = _wb()
    ws_crs = _sheet(
        wb,
        CRS_SHEET,
        meta,
        f"Fail and Query lines; Pass lines are on the sheet '{PASSED_SHEET}'.",
        INTERNAL_HEADERS,
        (internal_row(ln, paper) for ln in problems),
        first=True,
    )
    _rule_summary(ws_crs, meta.get("rule_labels"))
    _sheet(
        wb,
        PASSED_SHEET,
        meta,
        "Pass lines: the engineer ticks each one. Not CRS comments.",
        INTERNAL_HEADERS,
        (internal_row(ln, paper) for ln in passed),
    )
    _sheet(
        wb,
        NOT_APPLICABLE_SHEET,
        meta,
        NOT_APPLICABLE_NOTE,
        INTERNAL_HEADERS,
        (internal_row(ln, paper) for ln in not_applicable),
    )
    _sheet(
        wb,
        HELD_PASS_SHEET,
        meta,
        HELD_PASS_NOTE,
        INTERNAL_HEADERS,
        (held_row(ln, paper) for ln in held),
    )
    if not_reviewed:
        _sheet(
            wb,
            NOT_REVIEWED_SHEET,
            meta,
            NOT_REVIEWED_NOTE,
            INTERNAL_HEADERS,
            (internal_row(ln, paper) for ln in not_reviewed),
        )
    if unapproved:
        _sheet(
            wb,
            UNAPPROVED_SHEET,
            meta,
            UNAPPROVED_NOTE,
            INTERNAL_HEADERS,
            (internal_row(ln, paper) for ln in unapproved),
        )
    _run_sheet(wb, all_lines, meta)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def write_contractor(lines: list[Mapping], path: str | Path, meta: Mapping) -> Path:
    _refuse_unproven(lines)
    paper = str(meta.get("paper") or "")
    wb = _wb()
    contractor_meta = {
        **meta,
        "lead_models": [],
        "second_models": [],
    }  # the contractor copy names no model
    ws = wb.active
    ws.title = CRS_SHEET
    for r in (
        [TOP_TEXT],
        ["COMMENT RESOLUTION SHEET"],
        ["Paper:", paper],
        ["Date:", contractor_meta.get("date")],
        [],
        [],
        [],
        [],
    ):
        ws.append([_cell(v) for v in r])
    ws.append(list(CONTRACTOR_HEADERS))
    for ln in lines:
        if (
            ln.get("verdict") == FAIL
            and wording.writer_refusal(ln) is None
            and not wording.is_opinion(ln)
            and not ln.get("recommendation")
            and not wording.is_unapproved(ln)
        ):  # proven Fail only; a 'should' never
            ws.append([_cell(v) for v in contractor_row(ln, paper)])
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def write_comment_only(lines: list[Mapping], path: str | Path, meta: Mapping) -> Path:
    _refuse_unproven(lines)
    paper = str(meta.get("paper") or "")
    wb = _wb()
    _sheet(
        wb,
        CRS_SHEET,
        meta,
        "Comment-only copy of the Fail and Query lines, for scoring beside the old engine.",
        OLD_HEADERS,
        (
            old_row(ln, paper)
            for ln in lines
            if ln.get("verdict") in (FAIL, QUERY)
            and not is_not_applicable(ln)
            and not is_held_pass(ln)
            and not wording.is_unapproved(ln)
            and not wording.is_not_reviewed(ln)
        ),
        first=True,
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def run_counts(lines: list[Mapping]) -> dict:
    """Counts only (no text): lines, verdicts, how decided, quote check rate, AI call failures."""
    n = len(lines)
    by_verdict = {
        v: sum(1 for ln in lines if ln.get("verdict") == v) for v in (PASS, FAIL, QUERY)
    }
    both = sum(
        1
        for ln in lines
        if (ln.get("quotes_checked") or {}).get("paper")
        and (ln.get("quotes_checked") or {}).get("clause")
    )
    errors: dict[str, int] = {}
    for ln in lines:
        if ln.get("error"):
            errors[str(ln["error"])] = errors.get(str(ln["error"]), 0) + 1
    with_verdict = by_verdict[PASS] + by_verdict[FAIL]
    order12 = (
        wording.counts(lines) if any("verdict_class" in ln for ln in lines) else {}
    )
    return {
        **order12,
        "lines": n,
        "pass": by_verdict[PASS],
        "fail": by_verdict[FAIL],
        "query": by_verdict[QUERY],
        "query_not_applicable": sum(1 for ln in lines if is_not_applicable(ln)),
        "held_ai_pass": sum(1 for ln in lines if is_held_pass(ln)),
        "value_deferred": sum(
            1 for ln in lines if ln.get("reason_code") == "value_deferred"
        ),
        "lines_with_a_verdict": f"{with_verdict} of {n}",
        "decided_by_ai": sum(
            1
            for ln in lines
            if ln.get("decided_by") == BY_AI and ln.get("verdict") != QUERY
        ),
        "decided_by_code": sum(
            1
            for ln in lines
            if ln.get("decided_by") == BY_CODE and ln.get("verdict") != QUERY
        ),
        "decided_after_final_check": sum(
            1
            for ln in lines
            if ln.get("decided_by") == BY_FINAL_CHECK and ln.get("verdict") != QUERY
        ),
        "decided_absence_checked": sum(
            1
            for ln in lines
            if ln.get("decided_by") == BY_ABSENCE and ln.get("verdict") == FAIL
        ),
        "both_quotes_checked": f"{both} of {n}",
        "ai_call_failures": errors,
    }
