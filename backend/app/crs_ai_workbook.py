"""What the cells of the AI reviewer's CRS say (order 13): the item rows, the sheet of lines that are not item rows, Evidence and Notes.

`agent_review_crs` decides WHERE a line goes (`sheet_of`, still the one decision); this module reads it (`status_of`) and decides the words
(fixed sentences and the plain-phrase table are in `crs_ai_words`). `crs_layout` draws the workbook. Every count printed on the Notes sheet
is the length of the rows written, taken from the same lists. No new AI call: only what the stored line holds. U5: the Query action and
the AI's reasoning line come from `crs_ai_actions`, the priority from `crs_ai_words.priority_ai`.

ORDER 14 LANE B (owner, 16 Nov 2026). The sheet CRS holds ONE comment per field or topic, grouped by the same function as the paper's one
CRS (`crs_comments.group`): the strongest line leads, the other lines of that field are listed on it and stand on the sheet "Not a comment"
as "Part of comment n". A field that carries no finding (met, a "N rules could not be matched" line) is not a comment: it is on that sheet
too, counted, and the coverage lines become ONE coverage note on the first sheet. Every line keeps its own row on Evidence (completeness).
What a rule requires is the clause quote code verified in the book, whole; when there is none the comment says so in plain words and
shows our checklist's or the stored rule's words only labelled as such, never as the book's."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from . import agent_review_local as local_words
from . import agent_review_two_reader as two
from . import agent_review_wording as wording
from . import crs_ai_words as words
from . import crs_comments, crs_export, crs_layout, kind_review_table
from .agent_review_crs import (
    HELD_PASS_SHEET,
    NOT_APPLICABLE_SHEET,
    NOT_CHECKED_HERE_SHEET,
    NOT_REVIEWED_SHEET,
    OTHER_COLUMNS,
    OTHER_WIDTHS,
    PASSED_SHEET,
    UNAPPROVED_SHEET,
    _deferred_mark,
    _other_reason,
    against,
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
from .crs_ai_actions import query_action, reason_for, reasoning_part

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


def item_field(line: Mapping) -> str:
    """The ITEM's own field, the same in every run (order 14, lane A's G6 analysis): a rule's field role from its label ("set_pressure"
    -> "Set pressure"), a checklist item's topic; '' when the item names none."""
    if line.get("source") == "skill":
        return _skill_item(line.get("item_id")).get("topic", "")
    label = line.get("rule_label")
    role = (
        _clean(label.get("field")).replace("_", " ")
        if isinstance(label, Mapping)
        else ""
    )
    return role[:1].upper() + role[1:]


def field_name(line: Mapping) -> str:
    """The field in words a reader knows: the item's own field (`item_field`, not the label the AI happened to quote, which varies
    between runs), else the label printed on the paper, else the item's field roles; never an item id."""
    label = (
        item_field(line)
        or _clean(line.get("field"))
        or _clean(line.get("field_label_ai"))
    )
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
    label = _clean(line.get("field")) or _clean(
        line.get("field_label_ai")
    )  # the paper's own label, as the AI quoted it
    base = _page_cell(page) or ""
    return f"{base} - {label}" if base and label else base or label


_WORDING: list[
    dict
] = []  # filled only by a COMPLETE load, like `agent_review_verdict.checklist_ids`


def _skill_item(item_id: object) -> dict:
    """A checklist item's "expected" wording and "topic" by item id, through the app's one loader (`agent_skills`), plain words; {}
    when the item or the data is not found on this machine. Kept only after a COMPLETE load."""
    if not _WORDING:
        from . import agent_skills

        found: dict[str, dict] = {}
        complete = True
        for kind in agent_skills.KINDS:
            try:
                skill = agent_skills.load_skill(kind)
            except agent_skills.SkillError:
                complete = False
                continue
            found.update(
                {
                    f"S-{it['id']}": {
                        k: words.plain(it.get(k)) for k in ("expected", "topic")
                    }
                    for it in skill["items"]
                }
            )
        if not (complete and found):
            return found.get(str(item_id)) or {}
        _WORDING.append(found)
    return _WORDING[0].get(str(item_id)) or {}


def checklist_wording(item_id: object) -> str:
    """The checklist item's own requirement wording ("Expected") by item id; '' when not found on this machine."""
    return _skill_item(item_id).get("expected", "")


def _item_ask(line: Mapping) -> str:
    """The words shown as the rule book's own: the clause quote ONLY when code verified it in the book, WHOLE (never cut, never our
    checklist's wording, never the stored rule text); '' when there is none (the comment then says so: `_no_quote`)."""
    q = line.get("quotes_checked") or {}
    return _clean(line.get("clause_quote")) if q.get("clause") else ""


NO_QUOTE = "No verified quote of this clause is held: the engineer reads the clause."


def _no_quote(line: Mapping) -> str:
    """What a comment says when no verified clause quote is held: that, in plain words, then the words we do hold, each labelled as what
    it is (our checklist's wording; the stored rule text that code did not find in the book). Never shown as the book's words."""
    out = NO_QUOTE
    ours = (
        checklist_wording(line.get("item_id")) if line.get("source") == "skill" else ""
    )
    if ours:
        out += f' Our checklist asks (our words, not the book\'s): "{ours}".'
    elif (stored := _clean(line.get("requirement"))) and line.get("source") != "group":
        out += f' The stored rule text, not found in the book by code: "{stored}".'
    return out


def _requires(line: Mapping, status: str) -> str:
    """Part 1: what the rule requires: the clause quote code verified in the book, else `_no_quote`."""
    ref, ask, field = against(line), _item_ask(line), field_name(line)
    verb = (
        "recommends"
        if line.get("recommendation") or line.get("rule_kind") == "advice"
        else "requires"
    )
    if (
        status == words.STATUS_QUERY and (mark := _deferred_mark(line)) is not None
    ):  # lane D: the sheet leaves it to the vendor
        head = f"Vendor to provide {field or 'the value asked for'}{mark}; {ref or 'the rule'}"
        return head + (f' {verb}: "{ask}".' if ask else f" applies. {_no_quote(line)}")
    if status == words.STATUS_QUERY:
        head = f"Contractor to confirm {field + ' against' if field else 'compliance with'} {ref or 'the rule'}"
        return head + (f', which {verb}: "{ask}".' if ask else f". {_no_quote(line)}")
    if ask:
        return f'{ref or "The rule"} {verb}: "{ask}".'
    return (
        f"{ref or 'The rule'} applies"
        + (f" to {field}." if field else ".")
        + f" {_no_quote(line)}"
    )


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
        return words.absence_cell(line, field_name(line) or _item_ask(line))
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
        out = f"{words.verdict_prefix(two.is_independent(line), order == words.ORDER_AI_VERDICT_MET)} {out}"
    if status == words.STATUS_AI:
        view = OPINION_MET if order == words.ORDER_AI_MET else OPINION_NOT_MET
        out = f"{words.AI_VIEW_PREFIX}{view}. {out}"
    why = reason_for(line, words.why_phrase(guard or line.get("not_proven_reason")))
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
    if guard:  # N9: a "met" the guard moved: one reader's view, marked, never the conclusion (lane B: never "no correction needed")
        view = words.plain(
            " ".join(str(line.get("comment") or line.get("reasoning") or "").split())[
                :400
            ]
        )
        out += f" {wording.ONE_READER}the requirement is met." + (
            f" {view}" if view else ""
        )
    if draft := words.ai_draft_words(
        line
    ):  # lane A: a code check against an AI-draft limit, said as such
        out += f" {draft}"
    return out + reasoning_part(line, status, guard)


def _contractor_to(line: Mapping, status: str, order: int) -> str:
    """Part 3: what the contractor must do: ONE fixed sentence per Status, completed with the field label and the rule reference the
    line already carries. No free text of the AI reader reaches it (its suggested action is on the Evidence sheet). Pass and AI
    opinion (met): no action line."""
    if (
        line.get("ai_draft") is True
    ):  # lane A: the limit is an AI draft: the engineer confirms it first
        return f"Engineer to confirm the AI-draft limit of {against(line) or 'the rule'}, then the comparison."
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
    if status == words.STATUS_QUERY and (action := wording.reader_query_action(line)):
        return action  # a question for the engineer, never worded for the contractor
    what, ref = field_name(line) or "the item", against(line)
    if status == words.STATUS_FAIL:
        return f"Contractor to revise {what} to meet {ref or 'the requirement'} and resubmit the paper."
    if status in (words.STATUS_AI, words.STATUS_AI_VERDICT):
        return f"Contractor to check {what}{' against ' + ref if ref else ''} and confirm or correct it."
    return query_action(line, what, ref)


def layout_comment(line: Mapping, status: str, order: int) -> str:
    """The COMPANY Comments cell: three short parts, one per line: what the rule requires, what the paper shows, what the
    contractor must do. Built from the stored line only; no new AI call; no code word (`words.has_banned`)."""
    if line.get("source") == "group":  # rule choice v2: one sentence for the engineer
        return str(line.get("why") or "")
    return "\n".join(
        (
            _requires(line, status),
            _paper_shows(line, status, order),
            _contractor_to(line, status, order),
            *crs_comments.also_words(line),
        )
    )


def _row(
    n: int,
    line: Mapping,
    paper: str,
    status: str,
    order: int,
    by: str,
    contractor: bool = False,
) -> list:
    if (
        contractor and status == words.STATUS_AI_VERDICT
    ):  # a flagged kind's "not met" row, worded as a comment with no AI word
        return [
            n, paper, _page_text(line), layout_comment(line, words.STATUS_FAIL, words.ORDER_FAIL), by, None, None,
            against(line) or None, words.priority_ai(status, line, order) or None, CONTRACTOR_COMMENT,
        ]  # fmt: skip
    return [
        n,
        paper,
        _page_text(line),
        line.get("engineer_text") or layout_comment(line, status, order),
        f"Engineer: {line['engineer_by']}" if by and line.get("engineer_by") else by,
        None,
        None,
        against(line) or None,
        words.priority_ai(status, line, order) or None,
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
        *crs_layout.engine_rows(h),
    ]


def _title(meta: Mapping) -> str:
    h = meta.get("header") or {}
    return "\n".join(
        p for p in (crs_export.default_company(), _clean(h.get("project"))) if p
    )


def item_lines(lines: Iterable[Mapping]) -> list[tuple[Mapping, str, int]]:
    """Every line that is an item (one row each before grouping) in the internal order (Fail, AI opinion not met, Query, AI opinion met,
    Pass); a 'should' Fail after the 'shall' Fails; each group keeps the order the lines came in."""
    keyed = []
    for pos, ln in enumerate(lines):
        got = status_of(ln)
        if got is not None:
            keyed.append(
                (got[1], 1 if ln.get("recommendation") else 0, pos, ln, got[0])
            )
    keyed.sort(key=lambda k: k[:3])
    return [(ln, status, order) for order, _r, _p, ln, status in keyed]


def _split(
    lines: Iterable[Mapping],
) -> tuple[list[tuple[Mapping, str, int]], list[tuple[Mapping, str]]]:
    """(the comment rows, every other line with what it is called). ONE comment per field or topic (`crs_comments.group`), led by its
    strongest line, which carries its other lines (`_comment`); a field with no finding and a coverage line are not comments. Each
    line is in exactly one of the two lists: comment rows + other lines = every line."""
    lines = list(lines)
    rows, kind_of = _grouped(item_lines(lines))
    out = []
    for ln in lines:
        kind = OTHER_KIND_OF_SHEET.get(sheet_of(ln)) or kind_of.get(id(ln))
        if kind is not None:
            out.append((ln, kind))
    return rows, out


def _grouped(items: list) -> tuple[list, dict[int, str]]:
    return crs_comments.group_lines(items)


def contractor_rows(
    lines: Iterable[Mapping], kind: str | None = None
) -> list[tuple[Mapping, str, int]]:
    """The contractor copy's rows: the lines it may issue (`_contractor_items`, chosen line by line, so a proven Fail is never hidden
    behind a field's other lines), then ONE row per field or topic among them."""
    return _grouped(
        _contractor_items(item_lines([wording.read_time(ln) for ln in lines]), kind)
    )[0]


def ordered_item_lines(lines: Iterable[Mapping]) -> list[tuple[Mapping, str, int]]:
    """The comment rows of the sheet CRS, worst first: ONE per field or topic (`_split`)."""
    return _split(lines)[0]


def other_lines(lines: Iterable[Mapping]) -> list[tuple[Mapping, str]]:
    """Every line that is not a comment row, with what it is called, in the order the lines came in: not reviewed, does not apply, rule
    not yet approved, not checked here; checked with nothing to change; a coverage line; part of comment n (`_split`)."""
    return _split(lines)[1]


def _models(names: Iterable[str] | None) -> str:
    return ", ".join(names or []) or "not reported"


def _count_rows(
    meta: Mapping, items: list, others: list, missing: list
) -> list[tuple[str, object]]:
    """The Notes sheet's counts: Status per comment row, the review's decisions over every item line, the lines that are not
    comments by kind, and the one coverage note (order 14 lane B)."""
    every = meta.get("_item_lines") or [ln for ln, _s, _o in items]
    kinds = {
        k: sum(1 for _l, kk in others if kk == k)
        for k in (*words.OTHER_KINDS, *words.NOT_A_COMMENT_KINDS)
    }
    kinds[words.KIND_NOT_HELD] = len(missing)
    merged = len(others) - sum(v for k, v in kinds.items() if k != words.KIND_NOT_HELD)
    rows = [
        (f"Count: {s}", sum(1 for _l, st, _o in items if st == s))
        for s in words.STATUSES
    ]
    rows += wording.group_rows(every)
    rows += words.decisions_rows(
        wording.decisions_of(
            (ln.get("verdict_class"), ln.get("verdict_label")) for ln in every
        )
    )
    rows.append(
        ("Count: rows on the CRS sheet", len(items))
    )  # one comment per field or topic
    rows.append(
        ("Count: lines merged into a comment (listed as 'Part of comment n')", merged)
    )
    rows += [
        (f"Count: {k}", kinds[k])
        for k in (*words.OTHER_KINDS, *words.NOT_A_COMMENT_KINDS)
    ]
    rows.append(
        (
            f"Count: rows on the sheet '{words.NOT_A_COMMENT_SHEET}'",
            len(others) + len(missing),
        )
    )
    return rows + (
        [("Coverage note", meta["_coverage"])] if meta.get("_coverage") else []
    )


def _notes_rows(
    meta: Mapping, items: list, others: list, missing: list
) -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = [("Priority rule", words.PRIORITY_RULE_AI)]
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
    rows += _count_rows(meta, items, others, missing)
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
            "; " + local_words.SECOND_UNAVAILABLE_WORDS
            if off == local_words.OFF_SECOND_UNAVAILABLE
            else f"; switched off for the rest of the run ({off.replace('_', ' ')})"
            if off
            else ""
        )
        + "."
    )


def _clean(text) -> str:
    return " ".join(str(text or "").split())


CONTRACTOR_COMMENT = (
    "Comment"  # the Status cell of such a row on the contractor copy: no AI word
)


def _guarded_not_met(ln: Mapping) -> bool:
    """An "AI verdict: not met" row fit for the contractor copy once its kind is flagged: the word is "not met" (never "not stated" or
    "met"), both quotes verified by code, a rule not a recommendation, the rule approved."""
    q = ln.get("quotes_checked") or {}
    return (
        ln.get("verdict_label") == two.WORD_NOT_MET
        and bool(q.get("paper") and q.get("clause"))
        and not ln.get("recommendation")
        and not wording.is_unapproved(ln)
        and wording.is_two_reader(ln)
        and not ln.get("engineer_text")
    )


def _contractor_items(items: list, kind: str | None = None) -> list:
    """The proven Fail rows only: a 'should' never, an opinion never, a rule not yet approved never. When the run's paper kind is flagged
    in the kind table's `contractor_copy_ai_verdict` (false for every kind today) the guarded "AI verdict: not met" rows are added."""
    out = [
        (ln, st, o)
        for ln, st, o in items
        if ln.get("engineer_text")
        or (
            st == words.STATUS_FAIL
            and wording.writer_refusal(ln) is None
            and not wording.is_opinion(ln)
            and not ln.get("recommendation")
            and not wording.is_unapproved(ln)
        )
    ]
    if kind_review_table.contractor_copy_ai_verdict(kind):
        out += [
            (ln, st, o)
            for ln, st, o in items
            if st == words.STATUS_AI_VERDICT and _guarded_not_met(ln)
        ]
        out.sort(key=lambda t: t[2])
    return out


def comment_cell(value) -> str | None:
    """The COMPANY Comments cell with its three parts on three lines: each line cleaned like any cell (whitespace, tabs, control
    characters, never a formula), a real line break between the parts, and a full stop at the end of each part."""
    if value is None:
        return None
    lines = [
        " ".join(part.split())
        for part in str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    lines = [ln if ln[-1] in ".!?" else ln + "." for ln in lines if ln]
    text = "\n".join(lines)
    return " " + text if text[:1] in ("=", "+", "-", "@") else text


def _table(rows: list[list], lines_col: int | None = None) -> list[list]:
    """Every cell through `_cell` (one line, never a formula); the one `lines_col` (the comment) keeps its line breaks."""
    return [
        [comment_cell(v) if i == lines_col else _cell(v) for i, v in enumerate(r)]
        for r in rows
    ]


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
            (status_of(ln) or (None,))[0]
            if kind == words.KIND_NOTHING_TO_CHANGE
            else None,
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
        "name": words.NOT_A_COMMENT_SHEET,
        "columns": OTHER_COLUMNS,
        "rows": _table(rows),
        "widths": OTHER_WIDTHS,
    }


def screen_text(line_json: str | None) -> str:
    """The AI review tab's text for a stored line: the SAME three lines the file's COMPANY Comments cell holds (one source), for a line
    that is an item row; '' for any other line (the screen keeps its stored reason) or a line that cannot be read."""
    try:
        line = json.loads(line_json or "")
    except ValueError:
        return ""
    line = wording.read_time(line) if isinstance(line, dict) else line  # read time
    ruled = isinstance(line, dict) and line.get("source") in (
        "rule",
        "skill",
    )  # a general review's line is not an item row
    got = status_of(line) if ruled else None
    return comment_cell(layout_comment(line, *got)) or "" if got else ""


def layout_view(lines: list[Mapping], meta: Mapping, copy: str) -> dict:
    """The whole workbook as plain values for `crs_layout.build_layout_crs`. copy = 'internal' | 'contractor'. The contractor copy
    is the proven Fail rows only, with no Comment By, no Evidence sheet, no Notes sheet, no sheet of lines that were not item rows,
    no model, no run number."""
    paper = str(meta.get("paper") or "")
    contractor = copy == "contractor"
    lines = [wording.read_time(ln) for ln in lines]  # read time
    items, others = _split(lines)
    discipline = meta.get("discipline") or (meta.get("header") or {}).get("discipline")
    by = "" if contractor else words.comment_by(discipline)
    if contractor:
        items = [
            ({**ln, "_comment": {**ln["_comment"], "contractor": True}}, st, o)
            for ln, st, o in _grouped(
                _contractor_items(item_lines(lines), meta.get("paper_kind"))
            )[0]
        ]
        books, label = _books_used(ln for ln, _s, _o in items), BOOKS_SHOWN
    else:  # the books of the lines the AI reviewer answered (a not-reviewed line used no book)
        books = _books_used(ln for ln in lines if not wording.is_not_reviewed(ln))
        label = BOOKS_REVIEWED
    coverage = crs_comments.coverage_note(lines) if not contractor else ""
    if isinstance(
        meta.get("editions"), dict
    ):  # lane G: what the edition cutoff says of each held book
        books = [f"{b} ({words.edition_words(meta['editions'].get(b))})" for b in books]
    view: dict = {
        "title": _title(meta),
        "header": _header_pairs(meta, books, label)
        + ([("Coverage note:", coverage)] if coverage else []),
        "sentence": words.generated_by(crs_export.default_company()),
        "rows": _table(
            [
                _row(n, ln, paper, st, o, by, contractor)
                for n, (ln, st, o) in enumerate(items, start=1)
            ],
            lines_col=3,
        ),
        "statuses": [
            CONTRACTOR_COMMENT if contractor and st == words.STATUS_AI_VERDICT else st
            for _l, st, _o in items
        ],
    }
    if contractor:  # nine company columns, plain styling: nothing that encodes an internal judgement
        view["columns"] = list(crs_layout.LAYOUT_COLUMNS[:9])
        view["rows"] = [r[:9] for r in view["rows"]]
        view["plain"] = True
        return view
    missing = list((meta.get("rule_labels") or {}).get("missing_rule_books") or [])
    view["other"] = _other_sheet(others, missing, paper, len(items) + 1)
    from .agent_review_crs import evidence_sheet

    view["evidence"] = evidence_sheet(items, others)
    rows = _notes_rows(
        {
            **meta,
            "books_used": books,
            "_coverage": coverage,
            "_item_lines": [ln for ln, _s, _o in item_lines(lines)],
        },
        items,
        others,
        missing,
    )
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
