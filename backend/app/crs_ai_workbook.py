"""What the cells of the AI reviewer's CRS say (order 13): the item rows, the sheet of lines that are not item rows, Evidence and Notes.

`agent_review_crs` decides WHERE a line goes (`sheet_of`, still the one decision); this module reads it (`status_of`) and decides the words
(fixed sentences and the plain-phrase table are in `crs_ai_words`). `crs_layout` draws the workbook. Every count printed on the Notes sheet
is the length of the rows written, taken from the same lists. No new AI call: only what the stored line holds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from . import agent_review_two_reader as two
from . import agent_review_wording as wording
from . import crs_ai_words as words
from . import crs_export, crs_layout
from .agent_review_crs import (
    HELD_PASS_SHEET,
    NOT_APPLICABLE_SHEET,
    NOT_CHECKED_HERE_SHEET,
    NOT_REVIEWED_SHEET,
    PASSED_SHEET,
    UNAPPROVED_SHEET,
    against,
    asks,
    line_page,
    sheet_of,
    stated,
)
from .agent_review_verdict import (
    BY_ABSENCE,
    BY_CODE,
    DEFERRED_WHY,
    FAIL,
    NO_VALUE_WHY,
    PASS,
    SILENCE_CODES,
    met_unsafe_why,
    moved_by_guard,
)
from .agent_run_crs import _cell, _page_cell

OPINION_MET = "met"
OPINION_NOT_MET = "not met"


def status_of(line: Mapping) -> tuple[str, int] | None:
    """(Status word, row order) of an ITEM row of the CRS sheet, or None when the line is not an item row (it goes to the
    sheet 'Not reviewed or not applicable'). Order: Fail, AI opinion (not met), Query, AI opinion (met), Pass."""
    bucket = sheet_of(line)
    if bucket in OTHER_KIND_OF_SHEET:
        return None
    if bucket == PASSED_SHEET:
        return words.STATUS_PASS, words.ORDER_PASS
    if bucket == HELD_PASS_SHEET:
        return words.STATUS_AI, words.ORDER_AI_MET
    proven = line.get("verdict_class") == wording.CLASS_PROVEN
    if proven and line.get("verdict") == FAIL:
        return words.STATUS_FAIL, words.ORDER_FAIL
    if wording.is_two_reader(
        line
    ):  # two AI readers agreed independently: its own Status, never Pass or Fail
        met = line.get("verdict_label") == two.WORD_MET
        return words.STATUS_AI_VERDICT, (
            words.ORDER_AI_VERDICT_MET if met else words.ORDER_AI_VERDICT_NOT_MET
        )
    if wording.is_opinion(line):
        met = line.get("verdict_label") == wording.THINKS_MET
        return words.STATUS_AI, words.ORDER_AI_MET if met else words.ORDER_AI_NOT_MET
    return words.STATUS_QUERY, words.ORDER_QUERY


OTHER_KIND_OF_SHEET = {
    NOT_APPLICABLE_SHEET: words.KIND_NOT_APPLICABLE,
    NOT_REVIEWED_SHEET: words.KIND_NOT_REVIEWED,
    UNAPPROVED_SHEET: words.KIND_UNAPPROVED,
    NOT_CHECKED_HERE_SHEET: words.KIND_NOT_CHECKED_HERE,
}


def field_name(line: Mapping) -> str:
    """The field in words a reader knows: the label printed on the paper, else the item's field words; never an item id."""
    label = _clean(line.get("field")) or _clean(line.get("field_label_ai"))
    if label:
        return label
    roles = [
        str(r).replace("_", " ").strip()
        for r in line.get("field_roles") or []
        if str(r).strip()
    ]
    return ", ".join(roles)


def _page_text(line: Mapping) -> str:
    page = line_page(line)
    label = _clean(line.get("field")) or _clean(line.get("field_label_ai"))
    base = _page_cell(page) or ""
    return f"{base} - {label}" if base and label else base or label


_WORDING: list[
    dict
] = []  # filled only by a COMPLETE load, like `agent_review_verdict.checklist_ids`


def checklist_wording(item_id: object) -> str:
    """The checklist item's own requirement wording ("Expected") by item id, through the app's one loader (`agent_skills`).
    '' when the item or the data is not found on this machine (the caller then falls back to the line's own text)."""
    if not _WORDING:
        from . import agent_skills

        found: dict[str, str] = {}
        complete = True
        for kind in agent_skills.KINDS:
            try:
                skill = agent_skills.load_skill(kind)
            except agent_skills.SkillError:
                complete = False
                continue
            found.update(
                {f"S-{it['id']}": _clean(it.get("expected")) for it in skill["items"]}
            )
        if not (complete and found):
            return words.plain(found.get(str(item_id)))
        _WORDING.append(found)
    return words.plain(_WORDING[0].get(str(item_id)))


def _item_ask(line: Mapping) -> str:
    """The words of what is asked: a checklist line's own item wording first, else the verified clause quote or stored rule text."""
    if line.get("source") == "skill":
        wording_text = checklist_wording(line.get("item_id"))
        if wording_text:
            return " ".join(wording_text.split()[:30])
    return asks(line)


def _requires(line: Mapping, status: str) -> str:
    """Part 1: what the rule requires, in the rule's own held words (a checklist item's own wording, the verified clause quote, else the stored rule text)."""
    ref, ask, field = against(line), _item_ask(line), field_name(line)
    verb = (
        "recommends"
        if line.get("recommendation") or line.get("rule_kind") == "advice"
        else "requires"
    )
    if status == words.STATUS_QUERY:
        head = f"Contractor to confirm {field + ' against' if field else 'compliance with'} {ref or 'the rule'}"
        return head + (f', which {verb}: "{ask}".' if ask else ".")
    if ask:
        return f'{ref or "The rule"} {verb}: "{ask}".'
    return f"{ref or 'The rule'} applies" + (f" to {field}." if field else ".")


def _searched(line: Mapping) -> str:
    return ", ".join(str(p) for p in line.get("pages_searched") or [])


def _paper_shows(line: Mapping, status: str, order: int) -> str:
    """Part 2: what the paper shows (only a quote code verified), or that it does not state the value. An AI opinion says it is
    the AI reviewer's view and that code did not prove it."""
    field, has, page = (
        field_name(line) or "the value asked for",
        stated(line),
        line.get("paper_page"),
    )
    where = f", page {page}" if page not in (None, "") else ""
    if (
        line.get("verdict_label") == two.WORD_NOT_STATED
        and status == words.STATUS_AI_VERDICT
    ):
        return f"The AI reviewer's verdict, to be confirmed by an engineer: {two.ABSENCE_WHY}."  # only what was established
    code = line.get("reason_code")
    silent = code in SILENCE_CODES or line.get("silence_query")
    guard = met_unsafe_why(line) if moved_by_guard(line) else ""
    if code == "value_deferred" or guard == DEFERRED_WHY:
        out = (
            f'The paper leaves {field} open ("{has}"{where}).'
            if has
            else f"The paper leaves {field} open."
        )
    elif line.get("verdict") == FAIL and line.get("decided_by") == BY_CODE and has:
        out = f'The paper states "{has}"{where}, which does not meet the requirement.'
    elif line.get("verdict") == FAIL and line.get("decided_by") == BY_ABSENCE:
        # the ONLY place a fact about the paper is stated: the absence check's own proof (decided by code and a second reader)
        searched = _searched(line)
        out = f"The paper does not state {field}" + (
            f" (pages searched: {searched})." if searched else "."
        )
    elif silent and not has:
        searched = _searched(line)
        out = f"The AI reviewer did not find {field} in the paper" + (
            f" (pages searched: {searched})." if searched else "."
        )
    elif guard == NO_VALUE_WHY:
        out = f"The quote from the paper holds only the label {field}, with nothing after it{where}."
    elif code == "needs_drawing_or_calc":
        out = "This cannot be checked from the paper alone."
    elif line.get("verdict") == PASS:
        out = (
            f'The paper states "{has}"{where}, which meets the requirement.'
            if has
            else f"The paper meets the requirement{where}."
        )
    elif has:
        out = f'The paper states "{has}"{where}.'
    else:
        out = "The AI reviewer holds no verified quote from the paper for this point."
    if status == words.STATUS_AI_VERDICT:
        view = OPINION_MET if order == words.ORDER_AI_VERDICT_MET else OPINION_NOT_MET
        out = (
            f"The AI reviewer's verdict, reached independently by two AI readers and to be confirmed by an engineer: "
            f"the requirement is {view}. {out}"
        )
    if status == words.STATUS_AI:
        view = OPINION_MET if order == words.ORDER_AI_MET else OPINION_NOT_MET
        out = f"{words.AI_VIEW_PREFIX}{view}. {out}"
    why = words.why_phrase(guard or line.get("not_proven_reason"))
    if (
        status in (words.STATUS_AI, words.STATUS_QUERY)
        and why
        not in (
            "",
            words.UNKNOWN_WHY,
        )  # an empty phrase carries no information: never printed
        and guard != NO_VALUE_WHY
    ):
        out += f" Not confirmed: {why}."
    if guard and (
        view := words.plain(
            " ".join(str(line.get("comment") or line.get("reasoning") or "").split())[
                :400
            ]
        )
    ):
        out += f" {wording.ONE_READER}{view}"  # N9: a "met" the guard moved: one reader's view, marked, never the conclusion
    return out


def _contractor_to(line: Mapping, status: str, order: int) -> str:
    """Part 3: what the contractor must do: ONE fixed sentence per Status, completed with the field label and the rule reference the
    line already carries. No free text of the AI reader reaches it (its suggested action is on the Evidence sheet). Pass and AI
    opinion (met): no action line."""
    if status == words.STATUS_PASS:
        return "No action."
    if status == words.STATUS_AI and order == words.ORDER_AI_MET:
        return "No action unless the engineer disagrees with the AI reviewer's view."
    if status == words.STATUS_AI_VERDICT and order == words.ORDER_AI_VERDICT_MET:
        return "No action unless the engineer disagrees with the AI reviewer's verdict."
    if (
        line.get("verdict_label") == two.WORD_NOT_STATED
        and status == words.STATUS_AI_VERDICT
    ):
        return f"Contractor to state {field_name(line) or 'the value asked for'}, or the page where it is shown."
    what, ref = field_name(line) or "the item", against(line)
    if (
        line.get("verdict_label") == two.WORD_NOT_STATED
        and status == words.STATUS_AI_VERDICT
    ):
        return f"Contractor to state {what}, or the page where it is shown."
    if status == words.STATUS_FAIL:
        return f"Contractor to revise {what} to meet {ref or 'the requirement'} and resubmit the paper."
    if status in (words.STATUS_AI, words.STATUS_AI_VERDICT):
        return f"Contractor to check {what}{' against ' + ref if ref else ''} and confirm or correct it."
    return f"Contractor to state {what}, or the page where it is shown."


def layout_comment(line: Mapping, status: str, order: int) -> str:
    """The COMPANY Comments cell: three short parts, one per line: what the rule requires, what the paper shows, what the
    contractor must do. Built from the stored line only; no new AI call; no code word (`words.has_banned`)."""
    return "\n".join(
        (
            _requires(line, status),
            _paper_shows(line, status, order),
            _contractor_to(line, status, order),
        )
    )


def _mandatory_rank(line: Mapping, status: str, order: int) -> str:
    return words.priority(status, line, order)


def _row(n: int, line: Mapping, paper: str, status: str, order: int, by: str) -> list:
    return [
        n,
        paper,
        _page_text(line),
        layout_comment(line, status, order),
        by,
        None,
        None,
        against(line) or None,
        _mandatory_rank(line, status, order) or None,
        status,
    ]


def _books_used(lines: Iterable[Mapping]) -> list[str]:
    return sorted(
        {_clean(ln.get("standard")) for ln in lines if _clean(ln.get("standard"))}
    )


BOOKS_SHOWN = "Rule books used (rows shown):"
BOOKS_REVIEWED = "Rule books used (reviewed lines):"


def _header_pairs(meta: Mapping, books: list[str], label: str) -> list[tuple[str, str]]:
    h = meta.get("header") or {}
    return [
        ("Project:", _clean(h.get("project"))),
        ("Document number:", _clean(h.get("document_number"))),
        ("Document title:", _clean(h.get("title"))),
        ("Revision:", _clean(h.get("revision"))),
        ("Date:", _clean(h.get("date"))),
        ("Discipline:", _clean(meta.get("discipline") or h.get("discipline"))),
        (label, "; ".join(books)),
    ]


def _title(meta: Mapping) -> str:
    h = meta.get("header") or {}
    return "\n".join(
        p for p in (crs_export.default_company(), _clean(h.get("project"))) if p
    )


def ordered_item_lines(lines: Iterable[Mapping]) -> list[tuple[Mapping, str, int]]:
    """The item rows in the internal order (Fail, AI opinion not met, Query, AI opinion met, Pass); a 'should' Fail after the
    'shall' Fails; each group keeps the order the lines came in."""
    keyed = []
    for pos, ln in enumerate(lines):
        got = status_of(ln)
        if got is not None:
            keyed.append(
                (got[1], 1 if ln.get("recommendation") else 0, pos, ln, got[0])
            )
    keyed.sort(key=lambda k: k[:3])
    return [(ln, status, order) for order, _r, _p, ln, status in keyed]


def other_lines(lines: Iterable[Mapping]) -> list[tuple[Mapping, str]]:
    """The lines that are not item rows, with what each is called, in the order the lines came in."""
    out = []
    for ln in lines:
        kind = OTHER_KIND_OF_SHEET.get(sheet_of(ln))
        if kind is not None:
            out.append((ln, kind))
    return out


def _other_reason(line: Mapping, kind: str) -> str:
    if kind == words.KIND_NOT_APPLICABLE:
        return (
            words.plain(line.get("comment"))
            or "The AI reviewer judged the rule not applicable to this paper."
        )
    if kind == words.KIND_NOT_CHECKED_HERE:
        return two.OTHER_WHY + "."
    if kind == words.KIND_UNAPPROVED:
        view = {wording.THINKS_MET: "met", wording.THINKS_NOT_MET: "not met"}.get(
            str(line.get("verdict_label"))
        )
        tail = (
            f" The AI reviewer's view ({view}) is not shown as a comment."
            if view
            else ""
        )
        return "The rule has not been approved yet." + tail
    text = (
        words.why_phrase(line.get("not_proven_reason"))
        or "the AI reviewer gave no answer"
    )
    return (
        text[:1].upper() + text[1:] + "."
    )  # only the first letter: never "the ai reviewer"


OTHER_COLUMNS = (
    "Item No",
    "Document Name",
    "Page No./Section",
    "Standard Reference",
    "What it is",
    "Reason",
)
OTHER_WIDTHS = (9.0, 26.0, 20.0, 26.0, 30.0, 90.0)
EVIDENCE_COLUMNS = (
    "Item No", "Status", "AI reasoning", "AI reader's suggested action", "Paper quote", "Paper page", "Clause quote", "Rule book and clause",
    "Paper quote check", "Clause quote check", "Second reader", "AI calls (models)", "Reason code", "Item id (internal)",
    "Rule id (internal)", "Independent reader: verdict", "Independent reader: paper quote", "Independent reader: paper page",
    "Independent reader: clause quote", "Independent reader: paper quote check", "Independent reader: clause quote check",
)  # fmt: skip
EVIDENCE_WIDTHS = (
    9.0,
    13.0,
    60.0,
    45.0,
    45.0,
    9.0,
    45.0,
    26.0,
    16.0,
    16.0,
    18.0,
    30.0,
    22.0,
    24.0,
    30.0,
    16.0,
    45.0,
    9.0,
    45.0,
    16.0,
    16.0,
)


def _check_word(ok: bool) -> str:
    return "verified" if ok else "not verified"


def _second_reader(line: Mapping) -> str:
    second = line.get("second_opinion")
    if isinstance(second, Mapping):
        return "asked: agreed" if second.get("agree") else "asked: disagreed"
    return "not asked"


def _calls(line: Mapping) -> str:
    second = line.get("second_opinion")
    parts = []
    if _clean(line.get("model")):
        parts.append(f"first reader {_clean(line['model'])}")
    if isinstance(second, Mapping) and _clean(second.get("model")):
        parts.append(f"second reader {_clean(second['model'])}")
    indep = two.stored(line)
    if indep is not None and _clean(indep.get("model")):
        parts.append(f"independent reader {_clean(indep['model'])}")
    return "; ".join(parts) or "none"


def _independent_cells(line: Mapping) -> list:
    """The independent second reader's verdict, its two quotes and both quote checks (blank when it was not asked)."""
    indep = two.independent(line)
    if indep is None:
        return [None] * 6
    if (
        indep.get("verdict") == two.A_NOT_STATED
    ):  # it found nothing: there is no paper quote to check
        q = indep.get("quotes_checked") or {}
        return [
            "not stated", None, None, _clean(indep.get("clause_quote")) or None,
            "no quote: nothing found", _check_word(bool(q.get("clause"))),
        ]  # fmt: skip
    q = (
        indep.get("quotes_checked")
        if isinstance(indep.get("quotes_checked"), Mapping)
        else {}
    )
    return [
        indep.get("verdict"),
        _clean(indep.get("paper_quote")) or None,
        indep.get("paper_page"),
        _clean(indep.get("clause_quote")) or None,
        _check_word(bool(q.get("paper"))),
        _check_word(bool(q.get("clause"))),
    ]


def _evidence_row(n: int, line: Mapping, status: str) -> list:
    q = line.get("quotes_checked") or {}
    label = line.get("rule_label")
    page = line.get("clause_page")
    ref = against(line) + (f", page {page}" if page not in (None, "") else "")
    return [
        n,
        status,
        _clean(line.get("reasoning")) or None,
        _clean(line.get("comment")) or None,
        _clean(line.get("paper_quote")) or None,
        line.get("paper_page"),
        _clean(line.get("clause_quote")) or None,
        ref or None,
        _check_word(bool(q.get("paper"))),
        _check_word(bool(q.get("clause"))),
        _second_reader(line),
        _calls(line),
        _clean(line.get("reason_code")) or None,
        line.get("item_id"),
        label.get("label_key") if isinstance(label, Mapping) else None,
        *_independent_cells(line),
    ]


def _models(names: Iterable[str] | None) -> str:
    return ", ".join(names or []) or "not reported"


def _notes_rows(
    meta: Mapping, items: list, others: list, missing: list
) -> list[tuple[str, object]]:
    count = {s: sum(1 for _l, st, _o in items if st == s) for s in words.STATUSES}
    kinds = {k: sum(1 for _l, kk in others if kk == k) for k in words.OTHER_KINDS}
    kinds[words.KIND_NOT_HELD] = len(missing)
    rows: list[tuple[str, object]] = [("Priority rule", words.PRIORITY_RULE)]
    if any(ln.get("source") == "skill" for ln, _s, _o in items):
        have = any(
            checklist_wording(ln.get("item_id"))
            for ln, _s, _o in items
            if ln.get("source") == "skill"
        )
        rows.append(
            (
                "Checklist wording",
                "from the checklist data"
                if have
                else "not available on this machine: the comment shows the line's own text",
            )
        )
    block = meta.get("rule_labels") or {}
    rows.append(
        (BOOKS_REVIEWED.rstrip(":"), "; ".join(meta.get("books_used") or []) or "none")
    )
    rows.append(
        (
            "Rule books not held",
            "; ".join(
                f"{b.get('rule_book')} ({words.plain(b.get('why')) or 'not in the library'})"
                for b in missing
            )
            or "none",
        )
    )
    rows += [(f"Count: {s}", count[s]) for s in words.STATUSES]
    rows.append(("Count: rows on the CRS sheet", len(items)))
    rows += [(f"Count: {k}", kinds[k]) for k in words.OTHER_KINDS]
    rows.append(
        (f"Count: rows on the sheet '{words.OTHER_SHEET}'", len(others) + len(missing))
    )
    for (
        key,
        label,
    ) in (  # the optional second-reader steps: counts and the one code that switched each off (internal only)
        ("two_reader_step", "Second-reader step"),
        ("two_reader_absence_step", "Second-reader absence step"),
        ("two_reader_other_step", "Second-reader other-paper step"),
    ):
        if isinstance(meta.get(key), Mapping):
            rows.append((label, _step_words(meta[key])))
    rows += [("Rules not asked", _clean(t)) for t in block.get("summary_lines") or []]
    stopped = (meta.get("order12_counts") or {}).get("page_reread_stopped")
    if stopped:  # PR #1760's notice, kept in the new layout (internal copy only)
        rows.append(("Second reading of pages", _clean(stopped)))
    cut = (meta.get("order12_counts") or {}).get("page_reread_cut_off")
    if cut:  # C4b: re-reads cut off twice at the token limit, counted in plain words (internal copy only)
        rows.append(("Second reading of pages, cut off", _clean(cut)))
    rows += [
        ("Run id", _clean(meta.get("run_id")) or "not reported"),
        ("Date", _clean(meta.get("date")) or "not reported"),
        ("First reader models", _models(meta.get("lead_models"))),
        ("Second reader models", _models(meta.get("second_models"))),
        (
            "Cost (USD)",
            meta.get("usd") if meta.get("usd") is not None else "not reported",
        ),
    ]
    return rows


def _step_words(step: Mapping) -> str:
    off = _clean(step.get("off"))
    return (
        f"{step.get('candidates', 0)} lines were candidates, {step.get('asked', 0)} asked in {step.get('calls', 0)} calls; "
        f"{step.get('agreed', 0)} agreed, {step.get('disagreed', 0)} disagreed, {step.get('unconfirmed', 0)} not confirmed"
        + (
            f"; {step['skipped']} not asked: the first reader was not given every page of the paper"
            if step.get("skipped")
            else ""
        )
        + (
            f"; switched off for the rest of the run ({off.replace('_', ' ')})"
            if off
            else ""
        )
        + "."
    )


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _contractor_items(items: list) -> list:
    """The proven Fail rows only: a 'should' never, an opinion never, a rule not yet approved never."""
    return [
        (ln, st, o)
        for ln, st, o in items
        if st == words.STATUS_FAIL
        and wording.writer_refusal(ln) is None
        and not wording.is_opinion(ln)
        and not ln.get("recommendation")
        and not wording.is_unapproved(ln)
    ]


def _table(rows: list[list]) -> list[list]:
    return [[_cell(v) for v in r] for r in rows]


def _other_sheet(others: list, missing: list, paper: str, first_no: int) -> dict:
    """The sheet of the lines that are not item rows, numbered on from the CRS rows, then the rule books not held."""
    rows = [
        [
            first_no + k,
            paper,
            _page_text(ln) or None,
            against(ln) or None,
            kind,
            _other_reason(ln, kind),
        ]
        for k, (ln, kind) in enumerate(others)
    ]
    for b in missing:
        why = words.plain(b.get("why"))
        rows.append(
            [first_no + len(rows), paper, None, _clean(b.get("rule_book")) or None, words.KIND_NOT_HELD,
             "The rule book is not in the library" + (f" ({why})." if why else ".")]
        )  # fmt: skip
    return {
        "name": words.OTHER_SHEET,
        "columns": OTHER_COLUMNS,
        "rows": _table(rows),
        "widths": OTHER_WIDTHS,
    }


def _evidence_sheet(items: list, others: list) -> dict:
    rows = [_evidence_row(n, ln, st) for n, (ln, st, _o) in enumerate(items, start=1)]
    rows += [
        _evidence_row(len(items) + k, ln, kind)
        for k, (ln, kind) in enumerate(others, start=1)
    ]
    return {
        "columns": EVIDENCE_COLUMNS,
        "rows": _table(rows),
        "statuses": [st for _l, st, _o in items] + [None] * len(others),
        "widths": EVIDENCE_WIDTHS,
    }


def layout_view(lines: list[Mapping], meta: Mapping, copy: str) -> dict:
    """The whole workbook as plain values for `crs_layout.build_layout_crs`. copy = 'internal' | 'contractor'. The contractor copy
    is the proven Fail rows only, with no Comment By, no Evidence sheet, no Notes sheet, no sheet of lines that were not item rows,
    no model, no run number."""
    paper = str(meta.get("paper") or "")
    contractor = copy == "contractor"
    items = ordered_item_lines(lines)
    discipline = meta.get("discipline") or (meta.get("header") or {}).get("discipline")
    by = "" if contractor else words.comment_by(discipline)
    if contractor:
        items = _contractor_items(items)
        books, label = _books_used(ln for ln, _s, _o in items), BOOKS_SHOWN
    else:  # the books of the lines the AI reviewer answered (a not-reviewed line used no book)
        books = _books_used(ln for ln in lines if not wording.is_not_reviewed(ln))
        label = BOOKS_REVIEWED
    view: dict = {
        "title": _title(meta),
        "header": _header_pairs(meta, books, label),
        "sentence": words.generated_by(crs_export.default_company()),
        "rows": _table(
            [
                _row(n, ln, paper, st, o, by)
                for n, (ln, st, o) in enumerate(items, start=1)
            ]
        ),
        "statuses": [st for _l, st, _o in items],
    }
    if contractor:  # nine company columns, plain styling: nothing that encodes an internal judgement
        view["columns"] = list(crs_layout.LAYOUT_COLUMNS[:9])
        view["rows"] = [r[:9] for r in view["rows"]]
        view["plain"] = True
        return view
    others = other_lines(lines)
    missing = list((meta.get("rule_labels") or {}).get("missing_rule_books") or [])
    view["other"] = _other_sheet(others, missing, paper, len(items) + 1)
    view["evidence"] = _evidence_sheet(items, others)
    rows = _notes_rows({**meta, "books_used": books}, items, others, missing)
    view["notes"] = {
        "columns": ("Topic", "Detail"),
        "rows": _table([[a, b] for a, b in rows]),
        "widths": (44.0, 120.0),
    }
    return view


def write(lines: list[Mapping], path: str | Path, meta: Mapping, copy: str) -> Path:
    """Write one copy ('internal' | 'contractor') through the one exporter's drawing code. The caller refused the unproven lines."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(crs_layout.build_layout_crs(layout_view(lines, meta, copy)))
    return out
