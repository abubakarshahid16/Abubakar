"""What a viewer sees of an AI datasheet line whose rule book he may not read (CLAUDE.md rule 5): an ALLOW-LIST, never a scrub.

`review_points.for_viewer` decides (one decision: `review_points.documents_hidden`) and calls `shown` here. The shown line holds
ONLY the safe fields: the paper's own field and its own quote and page (as code checked them), the line's class and verdict words,
codes and counts. Every rule-side field (book name, clause, the rule's words, why, the reader's comment and reasoning, the second
reader's reason, figures, the engineer's text) is the ONE fixed sentence `HIDDEN_RULE`, or left out. Nothing is numbered and no
text is searched and replaced, so no fragment, line break or name variant of the book can slip through.

The AI run file is drawn from the FULL lines (its grouping, its split between sheets, its row order and Status are exactly a reader
of the book's), and only the cells of a hidden line's rows are drawn from its shown line (`view_for`): the same rows and counts for
every viewer, never the book's words for him.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

HIDDEN_RULE = (
    "the rule for this line comes from a rule book that is not available to you"
)
HIDDEN_SENTENCE = HIDDEN_RULE[:1].upper() + HIDDEN_RULE[1:] + "."
#: the private mark of a shown line (never printed)
HIDDEN_KEY = "_rule_hidden"
#: a paper quote code did not verify, kept on a shown line for the grouping only (`crs_comments._evidence`), never printed
STORED_QUOTE_KEY = "_paper_quote_stored"
#: the keys of a line that are the paper's own, the line's class, or a code: copied as they are
SAFE_KEYS = frozenset(
    (
        "item_id", "source", "verdict", "verdict_class", "verdict_label", "word", "ai_verdict", "decided_by", "paper_page", "field", "field_label_ai", "field_roles", "reason_code", "rule_tier", "tier", "recommendation", "rule_kind",
        "model", "page_hint", "pages_searched", "standard_document_id", "deferred_page", "raw_unit", "strength", "priority",
        "engineer_by", "engineer_added",
    )
)  # fmt: skip
#: the rule-side text keys: said as `HIDDEN_RULE` when the line has them
RULE_TEXT_KEYS = (
    "standard", "clause_quote", "requirement", "why", "not_proven_reason", "comment", "reasoning", "clause_figure", "figure",
    "engineer_text",
)  # fmt: skip
#: the flags that only say a step happened (their own values may be words): kept as the fixed sentence
FLAG_KEYS = (
    "context_check",
    "conditional_hold",
    "table_note_hold",
    "unapproved_cap",
    "not_mentioned_hold",
    "context_hold",
    "silence_query",
)
#: what a CRS / Not-a-comment / Evidence row of a hidden line keeps from the full row (by column), every other filled cell is the sentence
KEEP_MAIN = frozenset(
    (0, 1, 2, 4, 8, 9)
)  # Item No, Document, Page, Comment By, Priority, Status
KEEP_OTHER = frozenset((0, 1, 2, 4, 6))  # Item No, Document, Page, What it is, Status
KEEP_EVIDENCE = frozenset(
    (
        "Item No",
        "Status",
        "Paper quote",
        "Paper page",
        "Paper quote check",
        "AI calls (models)",
        "Reason code",
        "Item id (internal)",
    )
)


def is_shown(line: object) -> bool:
    return isinstance(line, Mapping) and line.get(HIDDEN_KEY) is True


def shown(line: Mapping) -> dict:
    """THE shown line of a hidden datasheet line: the safe fields, the rule-side text as `HIDDEN_RULE`, the code-checked paper
    quote flag and the decision flags only (no value, no reason)."""
    out = {k: line[k] for k in SAFE_KEYS if k in line}
    out.update({k: HIDDEN_RULE for k in RULE_TEXT_KEYS if line.get(k)})
    q = line.get("quotes_checked")
    if isinstance(q, Mapping):
        out["quotes_checked"] = {"paper": q.get("paper"), "clause": q.get("clause")}
    from .crs_ai_actions import verified_quote

    if verified_quote(
        line
    ):  # the paper's own words, only as code found them on its page
        out["paper_quote"] = line["paper_quote"]
    elif line.get(
        "paper_quote"
    ):  # never shown: kept only so the comments group as for a reader of the book
        out[STORED_QUOTE_KEY] = line["paper_quote"]
    cmp = line.get("compare")
    if isinstance(cmp, Mapping):
        out["compare"] = {
            k: cmp[k] for k in ("decided", "verdict", "code_said") if k in cmp
        }
    second = line.get("second_opinion")
    if isinstance(second, Mapping):
        out["second_opinion"] = {"agree": second.get("agree")}
    label = line.get("rule_label")
    if isinstance(label, Mapping):
        out["rule_label"] = {k: label[k] for k in ("tier", "field") if k in label}
    out.update(
        {k: HIDDEN_RULE for k in FLAG_KEYS if line.get(k)}
    )  # the step happened; its words are the rule's
    out[HIDDEN_KEY] = True
    return out


def comment(line: Mapping) -> str:
    """The three parts of a hidden line's comment: the fixed sentence, the paper's own quote when code verified it (else the fixed
    sentence, never "no verified quote": the rule side is what is not shown), and what the engineer checks."""
    from .agent_review_crs import line_page_words
    from .crs_ai_actions import verified_quote

    quote, page = verified_quote(line), line_page_words(line)
    at = f", page {page}" if page else ""
    shows = (
        f'The paper states "{quote}"{at} (checked by code).'
        if quote
        else HIDDEN_SENTENCE
    )
    if line.get("engineer_text"):
        from .agent_general_crs import ENGINEER_HIDDEN

        return "\n".join(
            (
                HIDDEN_SENTENCE,
                shows,
                ENGINEER_HIDDEN[:1].upper() + ENGINEER_HIDDEN[1:] + ".",
            )
        )
    return "\n".join((HIDDEN_SENTENCE, shows, action_words(line)))


def action_words(line: Mapping) -> str:
    """What the engineer checks on a hidden line, in one clean sentence: its field and page against its rule book."""
    from .agent_review_crs import field_words, line_page_words

    page = line_page_words(line)
    return f"Engineer to check {field_words(line) or 'this line'}{f', page {page}' if page else ''} against its rule book."


def _masked(row: list, keep: frozenset[int]) -> list:
    return [
        v if i in keep or v in (None, "") else HIDDEN_RULE for i, v in enumerate(row)
    ]


def view_for(
    lines: list[Mapping], meta: Mapping, copy: str, hidden: Callable[[Mapping], bool]
) -> dict:
    """The AI run file's view (`crs_ai_workbook.layout_view`) for a viewer: drawn from the FULL lines, then every cell of a hidden
    line's row that is not on the keep list is `HIDDEN_RULE`, its comment is `comment`, a comment led by a line he may read lists
    only its other lines he may read and counts the rest, and the books used name only books he may read (the rest counted)."""
    from . import crs_ai_words as words
    from . import crs_ai_workbook as wb
    from . import crs_comments
    from .agent_review_crs import EVIDENCE_COLUMNS
    from .crs_ai_actions import verified_quote

    view = wb.layout_view(lines, meta, copy)
    missing = list((meta.get("rule_labels") or {}).get("missing_rule_books") or [])
    read = words.read_now(lines, missing)
    if not any(
        hidden(ln) for ln in read
    ):  # nothing hidden from him: the file exactly as a reader of every book has it
        return view
    contractor = copy == "contractor"
    items, others = wb._split(read)
    if contractor:
        items, others = (
            wb._contractor_items(wb.item_lines(read), meta.get("paper_kind")),
            [],
        )
    for n, (ln, st, o) in enumerate(items):
        view["rows"][n] = _main_row(view["rows"][n], ln, st, o, hidden, contractor)
    said = _books_said(
        meta, [ln for ln, _s, _o in items] if contractor else read, hidden, contractor
    )
    cover = crs_comments.coverage_note(
        [{**ln, "standard": ""} if hidden(ln) else ln for ln in read]
    )
    labels = (wb.BOOKS_SHOWN, wb.BOOKS_REVIEWED)
    view["header"] = [
        (a, said if a in labels else (cover if a == "Coverage note:" else b))
        for a, b in view["header"]
    ]
    if contractor:
        return view
    for k, (ln, _kind) in enumerate(others):
        if hidden(ln):
            view["other"]["rows"][k] = _masked(view["other"]["rows"][k], KEEP_OTHER)
    keep = frozenset(i for i, c in enumerate(EVIDENCE_COLUMNS) if c in KEEP_EVIDENCE)
    unverified = keep - {
        EVIDENCE_COLUMNS.index("Paper quote")
    }  # a quote code did not verify is not shown either
    for j, ln in enumerate([ln for ln, _s, _o in items] + [ln for ln, _k in others]):
        if hidden(ln):
            mine = keep if verified_quote(ln) else unverified
            view["evidence"]["rows"][j] = _masked(view["evidence"]["rows"][j], mine)
    view["notes"]["rows"] = [
        [
            a,
            {
                wb.BOOKS_REVIEWED.rstrip(":"): said,
                "Rules not asked": HIDDEN_RULE,
                "Coverage note": cover,
            }.get(a, b),
        ]
        for a, b in view["notes"]["rows"]
    ]
    return view


def _books_said(
    meta: Mapping,
    lines: list[Mapping],
    hidden: Callable[[Mapping], bool],
    contractor: bool,
) -> str:
    """The books used, as `crs_ai_workbook.layout_view` says them, naming only books of lines he may read; the rest counted."""
    from . import crs_ai_workbook as wb

    mine = [
        ln
        for ln in lines
        if not hidden(ln) and (contractor or not wb.wording.is_not_reviewed(ln))
    ]
    books = wb._books_used(mine)
    away = {
        wb._clean(ln.get("standard"))
        for ln in lines
        if hidden(ln) and wb._clean(ln.get("standard"))
    } - set(books)
    if isinstance(meta.get("editions"), dict):
        books = [
            f"{b} ({wb.words.edition_words(meta['editions'].get(b))})" for b in books
        ]
    return "; ".join(books) + (
        f"{'; ' if books else ''}{len(away)} more: {HIDDEN_RULE}" if away else ""
    )


def _main_row(
    row: list,
    ln: Mapping,
    st: str,
    o: int,
    hidden: Callable[[Mapping], bool],
    contractor: bool,
) -> list:
    """One CRS row: a hidden line's row masked with its own comment; a row led by a line he may read whose other lines are hidden:
    its comment drawn again with only the lines he may read, and the hidden ones counted."""
    from . import crs_ai_workbook as wb

    c = ln.get("_comment") or {}
    others = c.get("others") or []
    if hidden(ln):
        out = _masked(row, KEEP_MAIN)
        out[3] = wb.comment_cell(comment(shown(ln)))
        return out
    away = [m for m in others if hidden(m)]
    if not away or ln.get("engineer_text"):
        return row
    kept = {**ln, "_comment": {**c, "others": [m for m in others if not hidden(m)]}}
    text = (
        wb.layout_comment(kept, st, o)
        + f"\nAlso: {len(away)} more line(s) of this comment: {HIDDEN_RULE}."
    )
    return [*row[:3], wb.comment_cell(text), *row[4:]][: 9 if contractor else None]
