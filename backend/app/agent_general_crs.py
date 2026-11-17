"""The files of a general review (#1690, #781; order 13: ONE layout).

The workbooks are drawn by `crs_layout.build_layout_crs`, the drawing code the rule review shares: the nine company columns and
Status on the CRS sheet, then the sheets "Not reviewed or not applicable", Evidence and Notes (internal copy). The words come
from `crs_ai_words` (the Statuses, the priority rule, the plain-text filter). A general review has no rule book to hold the paper
to, so a line is never Pass or Fail: an AI note is Status "AI opinion", a question for the engineer is "Query" (worded
"Contractor to confirm ..."), a line that was not reviewed or a rule book we do not hold goes to the second sheet. A comment has
three parts: what the rule (or checklist point, or project paper) requires, what the paper shows (ONLY a quote code verified,
with its page, else one neutral sentence; the AI's own words are on the Evidence sheet, never in the comment), what the
contractor must do. (The shared exporter joins the three parts with line breaks and flattens them: its own fix.) The header block
is the datasheet review's own; what the mode is (no Pass or Fail) is said on the internal Notes sheet only.

The contractor copy and the comment-only copy hold the nine company columns and NO rows: a general review proves no Fail, and the
contractor copy shows proven Fail only. Every line is re-run through the single exit first, so a writer can only ever carry a
line of the four classes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from . import agent_general_review as core
from . import crs_ai_words as words
from . import crs_ai_workbook as workbook
from . import crs_export, crs_layout, kind_review_table
from .agent_general_review import (
    CLASS_NOT_CHECKED,
    CLASS_NOT_REVIEWED,
    CLASS_NOTE,
    CLASS_QUERY,
)
from .agent_review_crs import line_page, line_page_words
from .agent_run_crs import _cell, _page_cell

COPY_NAMES = ("crs-contractor.xlsx", "crs-scoring-comment-only.xlsx")
NO_FAIL_NOTE = "General review: no rule book, so no Pass or Fail. The contractor copy shows proven Fail only, so it holds no rows."
#: A line of the general review -> the Status word and the row order of the one layout.
ITEM_STATUS = {
    CLASS_NOTE: (words.STATUS_AI, words.ORDER_AI_NOT_MET),
    CLASS_QUERY: (words.STATUS_QUERY, words.ORDER_QUERY),
}
OTHER_KIND = {
    CLASS_NOT_REVIEWED: words.KIND_NOT_REVIEWED,
    CLASS_NOT_CHECKED: words.KIND_NOT_HELD,
}
EVIDENCE_COLUMNS = (
    "Item No", "Status", "Part", "Sub-kind", "Paper quote", "Paper page", "Other quote", "Other page", "Other document",
    "Quotes checked by code", "Figures (by code)", "AI reviewer's words", "Second reader's reason", "Text source", "Line id (internal)",
)  # fmt: skip
EVIDENCE_WIDTHS = (
    9.0,
    13.0,
    22.0,
    26.0,
    50.0,
    9.0,
    50.0,
    9.0,
    26.0,
    16.0,
    26.0,
    60.0,
    40.0,
    20.0,
    24.0,
)
OTHER_COLUMNS = (
    "Item No", "Document Name", "Part", "Rule book or document", "What it is", "Reason",
)  # fmt: skip
OTHER_WIDTHS = (9.0, 26.0, 20.0, 26.0, 30.0, 90.0)
UNREAD_WHAT = "the content of the pages that were not read as text"


def _c(text) -> str:
    return " ".join(str(text or "").split())


def _paper_quote(ln: Mapping) -> Mapping | None:
    return ln.get("quote_a") or ln.get("quote_paper")


def _other_quote(ln: Mapping) -> Mapping | None:
    return ln.get("quote_b") or ln.get("quote_other")


# ------------------------------------------------------------------------------------------------ LP2: a general line on any CRS row
# A general review's line (stored with `"general": true` by `agent_general_job.store_lines`) holds its point in its OWN keys (topic,
# sub-kind, part, project paper, the quote code verified, its words and whose words they are). The rule review's cells
# (`crs_ai_workbook`) read none of them, so on the paper's one CRS and on the AI run's file every such line said only "Engineer to
# check the item." (order 14 live proof, 17 Nov 2026). `question_row` decides EVERY wording cell of such a row together (REVIEW.md:
# one function decides the whole row's wording); this file's own parts 1 and 2 come from the same functions.

#: Set on a line by the caller that knows the viewer (`review_points.general_hidden`) when a row of it may name or quote a document he
#: may not read, or its free words may name a held book he may not read. `viewed` then empties every such key (the ONE guard).
HIDE_KEY = "_general_words_hidden"
NO_PAGE = "page not recorded"
NO_QUOTE = "The AI reviewer holds no verified quote from the paper for this point."
AI_WORDS = "the AI reviewer's words, not proven by code"
REVIEW_REASON = "the review's own reason"
NO_REASON = "no reason was recorded with this point"
HIDDEN = "its words are not shown here: they may name a document you may not read"
UNNAMED_BOOKS = "a rule book (not named here)"
HIDDEN_DOCUMENT = "a document you may not read"
#: what a viewer who may not read the document sees of an engineer's edit or reason on a hidden line (his words may quote it), by
#: what the engineer did (`engineer_hidden_words`)
ENGINEER_HIDDEN = (
    "an engineer edited this line (details not shown: a document you may not read)"
)
ENGINEER_REMOVED = (
    "an engineer removed this line (details not shown: a document you may not read)"
)
ENGINEER_KEPT = (
    "an engineer kept this line (details not shown: a document you may not read)"
)


def engineer_hidden_words(state) -> str:
    """The sentence for an engineer's hidden words by his decision: removed, kept, else edited."""
    return {"remove": ENGINEER_REMOVED, "keep": ENGINEER_KEPT}.get(
        str(state or ""), ENGINEER_HIDDEN
    )


#: no document of this name exists: a quote of another paper that does not say whose it is can never be shown (fail closed)
UNKNOWN_DOCUMENT = "\x00a quote that names no document"
#: every key of a general line that may name a document other than the paper, or hold free words (the AI's, or a sentence code
#: built around a name): emptied under HIDE_KEY, so no reader of the line (a CRS cell, the Evidence sheet, the page's point) prints it
SCRUBBED = (
    "topic", "rule_book", "held_rule_books", "standard", "clause", "clause_quote", "requirement", "reasoning", "second_model_reason",
    "code_words", "model_words", "why", "not_proven_reason", "field", "field_label_ai", "what", "reason", "paper_quote",
)  # fmt: skip
PAPER_QUOTES, OTHER_QUOTES = ("quote_a", "quote_paper"), ("quote_b", "quote_other")
FIXED_SUBKINDS = frozenset(
    (core.SUB_SELF, core.SUB_REF, core.SUB_OPEN, core.SUB_COUNT, core.SUB_ENGINEERING, core.SUB_CHECKLIST, core.SUB_CONCERN,
     core.SUB_UNREAD, core.SUB_SILENT)
)  # fmt: skip


class QuestionRow(NamedTuple):
    """Every wording cell of ONE general-review line shown as a CRS row, decided together."""

    point: str  # the paper's point the engineer checks
    page: str  # "page N", or "page not recorded"
    requires: str  # part 1: what the point rests on
    shows: str  # part 2: what the paper shows (a quote code verified, with its page)
    action: str  # part 3: the question: the point, the page and the reason
    paper_quote: str  # the paper quote code verified, "" when none

    @property
    def cells(self) -> tuple[str, str, str]:
        return self.requires, self.shows, self.action


def is_general(line: object) -> bool:
    return isinstance(line, Mapping) and line.get("general") is True


def verified(line: Mapping, *keys: str) -> Mapping | None:
    """The first of `keys` that holds a quote, only when code checked the line's quotes (`quotes_verified_by_code` is exactly True)."""
    q = next((line.get(k) for k in keys if line.get(k)), None)
    return (
        q
        if isinstance(q, Mapping) and line.get("quotes_verified_by_code") is True
        else None
    )


def quote_of(q: Mapping | None) -> tuple[str, object]:
    """(quote text, page) of a verified quote, or ('', None)."""
    return (_c(q.get("text")), q.get("page")) if q else ("", None)


def _where(page) -> str:
    return f", page {page}" if page not in (None, "") else ""


def _books(line: Mapping) -> str:
    return _c(line.get("rule_book") or ", ".join(line.get("held_rule_books") or []))


def _other(line: Mapping) -> str:
    return _c(line.get("other_document"))


def _quote_document(line: Mapping, key: str) -> str | None:
    """Whose words a quote of the line holds: its own `document`; a paper quote without one is the paper's; another paper's quote
    without one is `UNKNOWN_DOCUMENT` (never readable). None when the key holds no quote."""
    q = line.get(key)
    if not isinstance(q, Mapping):
        return None
    own = _c(q.get("document"))
    return own or (
        _c(line.get("document")) if key in PAPER_QUOTES else UNKNOWN_DOCUMENT
    )


def documents_named(line: Mapping) -> frozenset[str]:
    """Every document other than the paper itself that a row of the line may name or quote (its project paper, the document of each
    of its quotes): each must be readable by the viewer, else the line is shown through `viewed` with HIDE_KEY."""
    paper = _c(line.get("document"))
    found = {
        _other(line),
        *(_quote_document(line, k) for k in (*PAPER_QUOTES, *OTHER_QUOTES)),
    }
    return frozenset(d for d in found if d and d != paper)


def viewed(line: Mapping) -> Mapping:
    """THE one guard of every reader of a general line (CLAUDE.md rule 5): a line with HIDE_KEY set comes back with every name and
    word that may belong to a document the viewer may not read emptied (`SCRUBBED`), its project paper and a sub-kind that names one
    said as `HIDDEN_DOCUMENT`, its rule books as `UNNAMED_BOOKS`, its words as `HIDDEN`, and only the quotes of the paper itself kept.
    Any other line comes back as it is."""
    if not (is_general(line) and line.get(HIDE_KEY)):
        return line
    paper, sub = _c(line.get("document")), line.get("subkind")
    out = {**line, **dict.fromkeys(SCRUBBED), "held_rule_books": [], "text": HIDDEN}
    out["rule_book"] = UNNAMED_BOOKS if _books(line) else None
    out["other_document"] = HIDDEN_DOCUMENT if _other(line) else None
    if line.get(
        "engineer_text"
    ):  # the engineer's words on the line are hidden like the AI's
        out["engineer_text"] = ENGINEER_HIDDEN
    out["subkind"] = (
        sub
        if sub is None or sub in FIXED_SUBKINDS
        else core.SUB_DISAGREES.format(document=HIDDEN_DOCUMENT)
    )
    for key in (*PAPER_QUOTES, *OTHER_QUOTES):
        if line.get(key) is not None and _quote_document(line, key) != paper:
            out[key] = None
    return out


def free_words(line: Mapping) -> str:
    """Every free word and document name a row of the line may print (its words, topic, rule books, project paper): what the caller
    tests against the books the viewer may not read before it lets them through (`HIDE_KEY`)."""
    parts = (
        line.get("text"),
        line.get("topic"),
        _books(line),
        line.get("other_document"),
    )
    return " ".join(_c(p) for p in parts if _c(p))


def point_words(line: Mapping) -> str:
    """The paper's point: the checklist point by its topic, the rule books a part-1 line names, else its sub-kind (or part) and the
    project paper it is held against. Never empty."""
    topic, sub, other = _c(line.get("topic")), _c(line.get("subkind")), _other(line)
    if topic:
        return f'the checklist point "{topic}"'
    if line.get("part") == 1 and _books(line):
        return f"the paper against {_books(line)}"
    kind = sub or core.PART_WORDS.get(line.get("part")) or "general review"
    return f"the paper's point ({kind})" + (
        f" against {other}" if other and other not in kind else ""
    )


def field_label(line: Mapping) -> str:
    """The "Field or item" of a general line: what the point is about, never a fixed phrase when the line says it. Its topic; the rule
    books a part-1 line names; else its kind in plain words (its sub-kind, or its part), with the project paper it is held against.
    Read through `viewed`, so a hidden name never appears; "" for any other line (the grouping key is the caller's, never this)."""
    if not is_general(line):
        return ""
    line = viewed(line)
    topic, sub, other = _c(line.get("topic")), _c(line.get("subkind")), _other(line)
    if topic:
        return topic
    if line.get("part") == 1 and _books(line):
        return _books(line)
    kind = sub or core.PART_WORDS.get(line.get("part")) or "general review"
    word = (
        _c(line.get("word")) or core.WORD_OF.get(line.get("verdict_class")) or "Point"
    )
    return f"{word}: {kind}" + (
        f" against {other}" if other and other not in kind else ""
    )


def page_words(line: Mapping) -> str:
    """THE page of the line (`agent_review_crs.line_page_words`, a page hint said as one), or "page not recorded"."""
    page = line_page_words(line)
    return f"page {page}" if page else NO_PAGE


def rests_on(line: Mapping) -> str:
    """The reason the point rests on, each part labelled as whose words it is (CLAUDE.md rule 4): a finding whose sentence code built
    around the AI reviewer's words (`code_words` + `model_words`) says both, each with its label; a finding in the AI reviewer's own
    words (`text_source` says so) is labelled as its words; anything else is the review's own reason (code wrote its sentence). Plain
    words only (`crs_ai_words.plain`: no code word, no nothing-to-do phrase)."""
    text = words.plain(line.get("text")).rstrip(" .")
    if not text:
        return NO_REASON
    if line.get(HIDE_KEY):
        return HIDDEN
    finding = line.get("verdict_class") in (CLASS_NOTE, CLASS_QUERY)
    frame = words.plain(line.get("code_words")).rstrip(" .;:")
    said = words.plain(line.get("model_words")).rstrip(" .")
    if finding and frame and said:
        return f'{REVIEW_REASON}: {frame}; {AI_WORDS}: "{said}"'
    if finding and line.get("text_source") == core.TEXT_FROM_MODEL:
        return f'{AI_WORDS}: "{text}"'
    return f"{REVIEW_REASON}: {text}"


def requires_words(line: Mapping) -> str:
    """Part 1: what the point rests on. In a general review the 'rule' is the checklist point, the paper itself, a project paper's own
    requirement (its quote only when code verified it), or good practice; a part-1 line rests on no rule book that was checked."""
    part, other = (
        line.get("part"),
        _other(line) or ("A project paper" if line.get("part") == 4 else ""),
    )
    if part == 1:
        books = _books(line)
        return "No rule book was checked for this point" + (
            f" (named: {books})." if books else "."
        )
    if part == 2:
        topic = _c(line.get("topic"))
        return (
            f"The completeness checklist for this kind of paper asks for: {topic}."
            if topic
            else "The completeness checklist for this kind of paper applies."
        )
    if part == 3:
        return (
            "The paper must agree with itself and every reference in it must resolve."
        )
    if part == 4:
        other = other[:1].upper() + other[1:] if other == HIDDEN_DOCUMENT else other
        oq = quote_of(verified(line, *OTHER_QUOTES))[0]
        return f'{other} requires: "{oq}".' if oq else f"{other} applies to this paper."
    return (
        "No rule book applies to this point; it is an engineering comment on the paper."
    )


def shows_words(line: Mapping, view: str = "") -> str:
    """Part 2: what the paper shows: ONLY a quote code verified, with its page (`NO_QUOTE` when there is none); for a line of the paper
    against itself, its second quote too. `view`: a fixed sentence placed before the figures (the general file's AI note)."""
    text, page = quote_of(verified(line, "quote_a", "quote_paper"))
    out = f'The paper states "{text}"{_where(page)}.' if text else NO_QUOTE
    b_text, b_page = (
        quote_of(verified(line, "quote_b", "quote_other"))
        if line.get("part") == 3
        else ("", None)
    )
    if b_text:
        out += f' It also states "{b_text}"{_where(b_page)}.'
    if view:
        out += f" {view}"
    if line.get("figures"):
        out += f" Figures: {_c(line['figures'])}."
    return out


def question_row(line: Mapping) -> QuestionRow | None:
    """THE one decision of every wording cell of a general review's line on a CRS row; None for any other line. Every branch reads
    the line through `viewed` (the one guard): under HIDE_KEY no cell can name or quote a document the viewer may not read."""
    if not is_general(line):
        return None
    line = viewed(line)
    point, page = point_words(line), page_words(line)
    return QuestionRow(
        point=point,
        page=page,
        requires=requires_words(line),
        shows=shows_words(line),
        action=f"Engineer to check {point}, {page}: {rests_on(line)}.",
        paper_quote=quote_of(verified(line, "quote_a", "quote_paper"))[0],
    )


def _page_text(ln: Mapping) -> str | None:
    # the one page of a line (`agent_review_crs.line_page`): the page, the team file and this file agree
    return _page_cell(line_page(ln))


def _what(ln: Mapping) -> str:
    """What a Query asks the contractor to confirm: the checklist point, the project paper's requirement, or the unread pages."""
    other = _c(ln.get("other_document"))
    if ln.get("subkind") == core.SUB_UNREAD:
        return UNREAD_WHAT
    if ln.get("topic"):
        return _c(ln["topic"])
    if other:
        return f"compliance with {other}"
    return "the point raised"  # never the AI's free text: that is on the Evidence sheet


def _requires(ln: Mapping, status: str) -> str:
    """Part 1: what the rule requires. In this mode the 'rule' is the checklist point, the project paper's own requirement, the paper
    itself, or good practice (`requires_words`, the one home of these words); a question is worded 'Contractor to
    confirm ...'."""
    if status == words.STATUS_QUERY:
        oq = quote_of(verified(ln, "quote_b", "quote_other"))[0]
        tail = f', which requires: "{oq}".' if oq else "."
        return f"Contractor to confirm {_what(ln)}{tail}"
    return requires_words(ln)


AI_VIEW = "The AI reviewer's view, not proven by code: this point needs the engineer's attention."


def _paper_shows(ln: Mapping, status: str) -> str:
    """Part 2: what the paper shows: ONLY a quote code verified, with its page (`NO_QUOTE` when there is none;
    `shows_words`, the one home of these words). The AI's own words never enter the comment (they are on the
    Evidence sheet); an AI note says, in one fixed sentence, that it is the AI's view."""
    return shows_words(ln, AI_VIEW if status == words.STATUS_AI else "")


def _contractor_to(ln: Mapping, status: str) -> str:
    """Part 3: ONE fixed sentence per Status, completed with a label the line already carries. No free text of the reader."""
    if status == words.STATUS_QUERY:
        if ln.get("subkind") == core.SUB_UNREAD:
            return f"Contractor to confirm {UNREAD_WHAT}, or give them as text."
        return f"Contractor to state {_what(ln)}, or the page where it is shown."
    return "Contractor to check the point against the paper and confirm or correct it."


def comment_of(ln: Mapping, status: str) -> str:
    return "\n".join(
        (_requires(ln, status), _paper_shows(ln, status), _contractor_to(ln, status))
    )


def _sentence(text) -> str:
    said = words.plain(text) or "No reason was given."
    return said[:1].upper() + said[1:]


def _item_lines(final: list[Mapping]) -> list[tuple[Mapping, str, int]]:
    keyed = [
        (
            ITEM_STATUS[ln["verdict_class"]][1],
            pos,
            ln,
            ITEM_STATUS[ln["verdict_class"]][0],
        )
        for pos, ln in enumerate(final)
        if ln["verdict_class"] in ITEM_STATUS
    ]
    keyed.sort(key=lambda k: k[:2])
    return [(ln, st, order) for order, _p, ln, st in keyed]


def _grouped(
    items: list[tuple[Mapping, str, int]],
) -> tuple[list[tuple[Mapping, str, int]], list[tuple[Mapping, str]]]:
    """Order 14 lane B: ONE comment per topic, with the grouping of every CRS file (`crs_comments.group`): (the comment rows, led by the
    strongest line; every other line of a topic as "Part of comment n"). Nothing is dropped: the others are on their own sheet."""
    from . import crs_comments
    from . import review_points as rp

    points = []
    for pos, (ln, st, o) in enumerate(items):
        rank = 3 if st == words.STATUS_AI else 4
        points.append({"id": pos, "name": _c(ln.get("topic")), "rule_book": _c(ln.get("other_document")) or None, "clause": None,
                       "rank": rank, "tile": rp.TILE_OF_RANK[rank], "priority": words.priority(st, ln, o), "tags": []})  # fmt: skip
    rows, merged = [], []
    for c in crs_comments.group(
        points, findings_only=False, near=False
    ):  # R91: exact topics only, never near-same
        rows.append(items[c["strongest"]["id"]])
        merged += [
            (items[i][0], words.KIND_IN_COMMENT.format(n=len(rows)))
            for i in c["member_ids"]
            if i != c["strongest"]["id"]
        ]
    return rows, merged


def _row(n: int, ln: Mapping, paper: str, status: str, order: int, by: str) -> list:
    return [
        n,
        paper,
        _page_text(ln),
        comment_of(ln, status),
        by,
        None,
        None,
        _c(ln.get("other_document")) or None,
        words.priority(status, ln, order) or None,
        status,
    ]


def _table(rows: list[list]) -> list[list]:
    return [[_cell(v) for v in r] for r in rows]


def _evidence_row(n: int, ln: Mapping, status: str) -> list:
    """The Evidence row: the quotes and the AI reviewer's own words (here and nowhere else; never in the comment)."""
    qa, pa = quote_of(_paper_quote(ln))
    qb, pb = quote_of(_other_quote(ln))
    return [
        n, status, core.PART_WORDS[ln["part"]], ln.get("subkind") or "", qa, pa, qb, pb, _c(ln.get("other_document")),
        "verified by code" if ln.get("quotes_verified_by_code") is True else "no verified quote", ln.get("figures") or "",
        words.plain(ln.get("text")), _c(ln.get("second_model_reason")), _c(ln.get("text_source")) or "",
        ln.get("line_id") or "",
    ]  # fmt: skip


def _head_view(items: list, meta: Mapping, copy: str, discipline: str) -> dict:
    """The title, the header block (the datasheet review's own, `crs_ai_workbook._header_pairs`), the sentence and the item rows."""
    paper = str(meta.get("paper") or "")
    contractor = copy == "contractor"
    by = "" if contractor else words.comment_by(discipline)
    # only the books of ANSWERED rows (the item rows): a rule book we do not hold was never checked against, so it is never "used"
    # here (it is on the Notes sheet); a copy with no rows prints no book, like the datasheet review's empty contractor copy
    books = sorted(
        {_c(ln.get("rule_book")) for ln, _s, _o in items if ln.get("rule_book")}
    )
    label = workbook.BOOKS_SHOWN if contractor else workbook.BOOKS_REVIEWED
    return {
        "title": workbook._title(meta),
        "header": workbook._header_pairs({**meta, "discipline": discipline}, books, label),
        "sentence": words.generated_by(crs_export.default_company()),
        "rows": _table([_row(n, ln, paper, st, o, by) for n, (ln, st, o) in enumerate(items, start=1)]),
        "statuses": [st for _l, st, _o in items],
    }  # fmt: skip


def _other_sheet(others: list, paper: str, first_no: int) -> dict:
    rows = [
        [
            first_no + k,
            paper,
            core.PART_WORDS[ln["part"]],
            _c(ln.get("rule_book") or ", ".join(ln.get("held_rule_books") or []))
            or None,
            kind,
            _sentence(ln.get("text")),
        ]
        for k, (ln, kind) in enumerate(others)
    ]
    return {
        "name": words.OTHER_SHEET,
        "columns": OTHER_COLUMNS,
        "rows": _table(rows),
        "widths": OTHER_WIDTHS,
    }


def _evidence_sheet(items: list, others: list) -> dict:
    ev = [_evidence_row(n, ln, st) for n, (ln, st, _o) in enumerate(items, start=1)]
    ev += [
        _evidence_row(len(items) + k, ln, kind)
        for k, (ln, kind) in enumerate(others, start=1)
    ]
    return {
        "columns": EVIDENCE_COLUMNS,
        "rows": _table(ev),
        "statuses": [st for _l, st, _o in items] + [None] * len(others),
        "widths": EVIDENCE_WIDTHS,
    }


def _notes_sheet(
    items: list, others: list, books: list, meta: Mapping, used: list, dropped: Mapping
) -> dict:
    count = Counter(st for _l, st, _o in items)
    models = lambda key: ", ".join(meta.get(key) or []) or "not reported"  # noqa: E731
    notes: list[list] = [
        ["Review mode", core.MODE_WORD + ": " + NO_FAIL_NOTE],
        ["Priority rule", words.priority_rule((words.STATUS_AI, words.STATUS_QUERY))],
        ["Rule books not held", "; ".join(books) or "none"],
        ["Papers used", "; ".join(used) or core.NO_PROJECT_PAPER],
        *[[f"Count: {s}", count.get(s, 0)] for s in (words.STATUS_AI, words.STATUS_QUERY)],
        ["Count: rows on the CRS sheet", len(items)],
        *[[f"Count: {k}", sum(1 for _l, kk in others if kk == k)] for k in OTHER_KIND.values()],
        ["Count: rows on the sheet '" + words.OTHER_SHEET + "'", len(others)],
        *[[f"Dropped, {core.PART_WORDS[int(p)]}: {r}", n] for p, c in dropped.items() for r, n in c.items()],
        ["Run id", _c(meta.get("run_id")) or "not reported"],
        ["Date", _c(meta.get("date")) or "not reported"],
        ["First reader models", models("lead_models")],
        ["Second reader models", models("second_models")],
    ]  # fmt: skip
    return {
        "columns": ("Topic", "Detail"),
        "rows": _table(notes),
        "widths": (44.0, 120.0),
    }


def layout_view(
    lines: list[Mapping],
    meta: Mapping,
    project_papers: list[Mapping],
    dropped: Mapping,
    copy: str,
) -> dict:
    """The whole workbook as plain values for `crs_layout.build_layout_crs`. copy = 'internal' | 'contractor'. The contractor copy
    is the datasheet review's contractor copy: its header block, the nine company columns, no rows (a general review proves no
    Fail). What the mode is (no Pass or Fail) is said on the internal Notes sheet only."""
    final = [
        core.finalize_line(ln) for ln in lines
    ]  # nothing that did not leave through the exit
    h = meta.get("header") or {}
    discipline = _c(
        meta.get("discipline")
        or h.get("discipline")
        or kind_review_table.discipline(meta.get("kind"))
    )
    contractor = copy == "contractor"
    items, merged = ([], []) if contractor else _grouped(_item_lines(final))
    view = _head_view(items, meta, copy, discipline)
    if contractor:
        view["columns"] = list(crs_layout.LAYOUT_COLUMNS[:9])
        view["rows"] = [r[:9] for r in view["rows"]]
        view["plain"] = True
        return view
    others = merged + [
        (ln, OTHER_KIND[ln["verdict_class"]])
        for ln in final
        if ln["verdict_class"] in OTHER_KIND
    ]
    books = sorted({_c(ln.get("rule_book")) for ln in final if ln.get("rule_book")})
    used = [_c(p.get("name")) for p in project_papers if p.get("name")]
    view["other"] = _other_sheet(others, str(meta.get("paper") or ""), len(items) + 1)
    view["evidence"] = _evidence_sheet(items, others)
    view["notes"] = _notes_sheet(items, others, books, meta, used, dropped)
    return view


def write_empty_copy(path: Path, meta: Mapping | None = None) -> None:
    path.write_bytes(
        crs_layout.build_layout_crs(layout_view([], meta or {}, [], {}, "contractor"))
    )


def write_all(
    lines: list[Mapping],
    folder: Path,
    meta: Mapping,
    project_papers: list[Mapping],
    dropped: Mapping,
) -> dict:
    """Write the internal workbook and the two nine-column copies (no rows); returns counts only."""
    folder.mkdir(parents=True, exist_ok=True)
    final = [
        core.finalize_line(ln) for ln in lines
    ]  # the writer takes nothing that did not leave through the exit
    (folder / "crs-internal.xlsx").write_bytes(
        crs_layout.build_layout_crs(
            layout_view(final, meta, project_papers, dropped, "internal")
        )
    )
    for name in COPY_NAMES:
        (folder / name).write_bytes(
            crs_layout.build_layout_crs(
                layout_view(final, meta, project_papers, dropped, "contractor")
            )
        )
    return {
        "lines": len(final),
        "per_class": dict(Counter(ln["verdict_class"] for ln in final)),
    }


__all__ = [
    "COPY_NAMES",
    "NO_FAIL_NOTE",
    "comment_of",
    "layout_view",
    "write_all",
    "write_empty_copy",
]
