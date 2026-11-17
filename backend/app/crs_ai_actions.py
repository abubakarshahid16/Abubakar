"""What the contractor is asked, and what the AI reviewer says, on a Query of the AI reviewer's CRS comment (U5, P4 and P5).

The ACTION follows what the line HOLDS about the value, decided by code and never by the reader's words (P4): a value stated on the paper
(a quote code verified) is confirmed or justified, never "stated" again; a value the sheet defers is provided, and the sentence says it is
deferred; a blank field is stated; when code cannot tell, the engineer checks and the contractor is not asked. The comment's second line
carries the AI reviewer's own reasoning, labelled as its view (P5); a proven Pass or Fail has none. No model, no network."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import NamedTuple

from . import agent_review_two_reader as two
from . import crs_ai_words as words
from .agent_review_verdict import SILENCE_CODES, quote_defers

_SAYS = (words.STATUS_AI, words.STATUS_AI_VERDICT, words.STATUS_QUERY)
REASONING_LABEL = "The AI reviewer's reasoning (not proven by code):"


#: The reason a second-opinion reply stores when its answer was cut off by its token limit (`agent_review_run`).
CUT_OFF_REASONS = frozenset({"stop_max_tokens"})


def second_cut_off(line: Mapping) -> bool:
    """The line's second opinion was asked and its answer was CUT OFF (R101: the line's own marker, never the reason text): no true/false
    agree and reason "stop_max_tokens", or a retry that still gave no true/false answer. Lane A's `agent_review_two_reader.second_cut_off`
    holds the same rule; a test keeps the two equal once it is merged."""
    second = line.get("second_opinion")
    if not isinstance(second, Mapping) or isinstance(second.get("agree"), bool):
        return False
    if second.get("retried"):
        return (
            True  # the first reply was cut and its one retry gave no true/false answer
        )
    return (
        second.get("agree") is None
        and str(second.get("reason") or "").strip() in CUT_OFF_REASONS
    )


def action_case(line: Mapping) -> str:
    """The case: "stated" (a paper quote code verified), "deferred" (the stored reason says so, or the verified quote defers the value), "blank"
    (the paper is silent on the field) or "unknown"."""
    if second_cut_off(line):
        return "cut_off"  # R98/R101: the second reader's answer was cut off (its own marker): never "the readers disagree"
    if two.disagrees(line) or two.absence_disagrees(line):
        return "disagree"  # the two readers reached opposite verdicts: code's own flag
    case = _case_of_record(line)
    # FTU-17: a quote code did NOT find on the page never decides the action: a row that would ask the contractor on the reader's own
    # record ("blank", "deferred") while carrying such a quote is the engineer's to check
    from .agent_review_wording import is_two_reader

    if (
        case in ("blank", "deferred")
        and unverified_quote(line)
        and not is_two_reader(line)
    ):
        return (
            UNVERIFIED  # a two-reader verdict keeps its own words (review of PR #1872)
        )
    return case


def _case_of_record(line: Mapping) -> str:
    verified = bool(verified_quote(line))
    if line.get("reason_code") == "value_deferred":
        return "deferred"
    if verified and quote_defers(line.get("paper_quote")):
        return "deferred"
    # FTU-1: the line's OWN reason says the paper does not state it: a found quote that may state it is the engineer's to check (the
    # reader contradicts itself); otherwise the contractor states the value
    if silent_quote(line) == CONTRADICTS:
        return "contradicts"
    if says_silent(line):
        return "blank"
    if verified:
        return "stated"
    return "unknown"


def unverified_quote(line: Mapping) -> bool:
    """FTU-17: the line carries a paper quote that code did NOT find on the page."""
    return bool(" ".join(str(line.get("paper_quote") or "").split())) and not (
        (line.get("quotes_checked") or {}).get("paper")
    )


def verified_quote(line: Mapping) -> str:
    """The line's paper quote when code found it on the page, else ""."""
    checked = (line.get("quotes_checked") or {}).get("paper")
    return " ".join(str(line.get("paper_quote") or "").split()) if checked else ""


def says_silent(line: Mapping) -> bool:
    """The line's OWN record says the paper does not state the value: a silence reason code, the silence query flag or the word
    "not stated" (never the reader's free words)."""
    return (
        line.get("reason_code") in SILENCE_CODES
        or bool(line.get("silence_query"))
        or line.get("verdict_label") == two.WORD_NOT_STATED
    )


LOOKED, CONTRADICTS, DEFERRED = "looked", "contradicts", "deferred"
#: FTU-17: the case of a row whose quote code did not find on the page (`action_case`, `unverified_row`)
UNVERIFIED = "unverified"

#: FTU-1: the reason of a silent row whose found quote is the field's own label alone (code can show it holds no value). FTU-16: the
#: reader's sentence is said ONCE in a row, here; "not evidence of a value" is the paper cell's alone (`SilentRow.note`).
NOT_STATED_REASON = (
    "the paper does not state this value (the reader's reading, not proven by code)"
)
#: FTU-1: the reason of a silent row whose found quote is anything else: it may state the value, code decides neither way
CONTRADICT_REASON = (
    "the reader says the paper does not state this value, but the words it quoted are on the page and may state it; "
    "code did not decide which is right, so the engineer checks"
)
#: FTU-16: the reason of a silent row whose found quote is only a placeholder or a to-be-given marker: the value is deferred
DEFERRED_REASON = "the paper leaves this value to be given: the words quoted are a placeholder, not a value"
#: FTU-17: the reason of a silent row whose found quote holds ANOTHER field's label and none of this field's words (`about_another_field`)
OTHER_FIELD_REASON = "the quoted words are about another field; code did not decide whether the paper states this value, so the engineer checks"
#: FTU-17: the reason of a row whose quote code did NOT find on the page (`unverified_row`): it decides nothing
UNVERIFIED_REASON = "the words the reader quoted were not found on the page by code, so they decide nothing"


class SilentRow(NamedTuple):
    """Every wording cell of ONE silent row, decided together: its kind, Reason, action, the paper cell (note) and the quote's check cell.
    FTU-16: `cell` is the ONE wording of a sheet that puts the paper and the reason in one cell (the AI run's own CRS): the reason once,
    with the quote, never the note and the reason side by side."""

    kind: str
    reason: str
    action: str
    note: str
    check: str
    cell: str = ""


def whole_label(quote: str, labels) -> bool:
    """The quote is exactly one of the field's labels: that label's words IN ORDER and nothing else, once the separators " :|=" and
    "_" are taken out (case, spacing and a plural ending do not count: `agent_subject._stem`). Any other word or mark, however small
    ("Grade: Steel" for "Steel grade", "Set pressure (barg)"), is not the label alone (review R3 of PR #1867)."""
    from .agent_subject import _stem

    def words(text: object) -> list[str]:
        return [_stem(w) for w in re.split(r"[\s:|=_]+", str(text or "").lower()) if w]

    have = words(quote)
    return bool(have) and any(have == words(lab) for lab in labels if lab)


def found_quote_kind(quote: str, labels) -> str:
    """`LOOKED` only when code can show the found quote holds no value (`whole_label`); `CONTRADICTS` for every other quote."""
    return LOOKED if whole_label(quote, labels) else CONTRADICTS


#: FTU-1: the reason of a two-reader "not stated" whose found quote is the field's own label alone: the verdict stands, said as it is
AGREED_NOT_STATED_REASON = (
    "two AI readers each read every page and found no value, and the code searched the pages and found none; "
    "the words quoted are the field's own label, not a value"
)


#: The separators a quote may hold between the field's label and its marker ("Set pressure: TBA", "Set pressure | *", "Flow = TBA").
_SEPARATORS = " :|="


def quote_is_placeholder(quote: str, labels=(), value_field: bool = False) -> bool:
    """FTU-16: the found quote only marks a value still to be given. ONLY when the WHOLE quote, after taking out exactly the field's own
    label at its start and the separators ":", "|", "=", is one fixed deferral form (`blank_markers.is_whole_deferral`: "TBA", "*", a
    run of "_", "later", ... optionally with a unit; "by vendor" / "by contractor" only on a field that asks for a value). No other word
    is dropped: anything else, however it looks ("Rate: A | TBA", "Thickness: M *", "-", "N/A"), is not a placeholder, and the caller
    decides it neutrally (the engineer checks)."""
    from . import blank_markers

    text = " ".join(str(quote or "").split())
    for label in sorted(
        {" ".join(str(x).replace("_", " ").split()) for x in labels if x},
        key=len,
        reverse=True,
    ):
        if (
            label
            and text.lower().startswith(label.lower())
            and text[len(label) : len(label) + 1] in ("", *_SEPARATORS)
        ):
            text = text[len(label) :]
            break
    return blank_markers.is_whole_deferral(
        text.strip(_SEPARATORS), value_field=value_field
    )


def asks_a_value(*texts) -> bool:
    """FTU-16: the rule (or the field's record) asks for a figure: the app's one number reader finds a measurement in it."""
    from .claims import extract_measurements

    return any(t and extract_measurements(" ".join(str(t).split())) for t in texts)


def silent_row_words(
    field: str,
    quote: str,
    labels=(),
    where: str = "",
    agreed: bool = False,
    value_field: bool = False,
) -> SilentRow:
    """FTU-1: THE ONE decision of a silent row (its own record says the paper gives no value) that carries a quote code found on the
    page: the kind and every wording cell with it, so the cells of one row can never disagree. Read by the AI review's lines
    (`silent_row`: the points, both sheets, the reason) and the rule check's points (`review_points.rule_point`).
    FTU-16: a quote that is only a placeholder (`quote_is_placeholder`) means the value is deferred: the contractor states it, never
    "may state it". The reader's own sentence ("the reader says ... not stated") is said once, in the reason; the action and the
    paper cell never repeat it, and "not evidence of a value" is the paper cell's alone."""
    what = field or "the value asked for"
    found = f'"{quote}"{where} (found on the page by code)'
    if quote_is_placeholder(quote, [field, *labels], value_field):
        return SilentRow(
            DEFERRED,
            DEFERRED_REASON,
            f"Contractor to state {what}; the paper leaves it to be given.",
            f"Left to be given on the page: {found}.",
            "a placeholder, not a value",
            f"Not confirmed: {DEFERRED_REASON}; quoted: {found}.",
        )
    if found_quote_kind(quote, [field, *labels]) == LOOKED:
        reason = AGREED_NOT_STATED_REASON if agreed else NOT_STATED_REASON
        return SilentRow(
            LOOKED,
            reason,
            f"Contractor to state {what}, or the page where it is shown.",
            f"The reader looked here: {found}; not evidence of a value.",
            "where the reader looked, not evidence of a value",
            f"Not confirmed: {reason}; it looked here: {found}.",
        )
    if about_another_field(quote, [field, *labels]):
        # FTU-17: the same neutral kind (the engineer checks; every reader of the kind is unchanged), worded for what code saw
        return SilentRow(
            CONTRADICTS,
            OTHER_FIELD_REASON,
            f"Engineer to check {what}: the quoted words are about another field.",
            f"Quoted from the page: {found}, which is about another field.",
            "about another field; the engineer checks",
            f"Not confirmed: {OTHER_FIELD_REASON}; quoted: {found}.",
        )
    return SilentRow(
        CONTRADICTS,
        CONTRADICT_REASON,
        f"Engineer to check {what}: the words quoted from the page may state it.",
        f"Quoted from the page: {found}, which may state it.",
        "may state it; the engineer checks",
        f"Not confirmed: {CONTRADICT_REASON}; quoted: {found}.",
    )


# ---- order 14 LPV V2: a value the paper states is never asked for -------------------------------------------------------------

#: the key a line carries when code found, on the paper, the value its own record says is not stated: {"quote", "page", "from"}
STATED_KEY = "stated_on_paper"
#: where the stated value was found: another line of the same review on the same field (its quote code verified on the page and
#: read as the value), or the paper's stored reading (a label that is the field's own label, its value found on its page by code)
FROM_LINE, FROM_READING = "another point of this review", "the paper's stored reading"
STATED_REASON = (
    "the reader says the paper does not state this value, but code found it stated on the page; the engineer checks the rule "
    "against the stated value"
)


def stated_row_words(field: str, stated: Mapping, where: str = "") -> SilentRow:
    """V2: every wording cell of a row whose own record says "not stated" while code found the value stated on the paper
    (`STATED_KEY`). The neutral kind (`CONTRADICTS`: the engineer checks, the contractor copy never asks to state it); the stated
    quote is cited, never "Contractor to state"."""
    what = field or "the value asked for"
    page = stated.get("page")
    on = f", page {page}" if page not in (None, "") else ""
    found = f'"{stated.get("quote")}"{on}{where} (found on the page by code; from {stated.get("from")})'
    return SilentRow(
        CONTRADICTS,
        STATED_REASON,
        f"Engineer to check {what} against the value the paper states: {found}.",
        f"Stated on the paper: {found}.",
        "stated on the paper; the engineer checks",
        f"Not confirmed: {STATED_REASON}; stated: {found}.",
    )


def _would_ask_to_state(line: Mapping, quote: str, labels) -> bool:
    """The row would ask the contractor to STATE the value: no quote at all (and none code failed to find), or a found quote that
    is the field's label alone. A quote that defers the value (the paper marks it to be given) or may state it (the paper's own
    words, already the engineer's check) keeps its own row."""
    if not quote:
        return not unverified_quote(line)
    return not quote_defers(quote) and not quote_is_placeholder(quote, labels) and whole_label(quote, labels)


def _field_key(line: Mapping) -> str:
    """The field a line is about: its rule's approved label field, else the paper's label it names (folded)."""
    label = (line.get("rule_label") or {}).get("field") if isinstance(line.get("rule_label"), Mapping) else None
    text = label or line.get("field") or ""
    return " ".join(re.findall(r"[a-z0-9]+", str(text).replace("_", " ").lower()))


def _labels_of(line: Mapping) -> list[str]:
    rule = line.get("rule_label") if isinstance(line.get("rule_label"), Mapping) else {}
    return [x for x in (line.get("field"), (rule or {}).get("field"), *(line.get("field_roles") or [])) if x]


def holds_a_value(quote: str, labels) -> bool:
    """The quote is more than the field's label and is no placeholder or deferral: it can hold the value."""
    q = " ".join(str(quote or "").split())
    return bool(q) and not whole_label(q, labels) and not quote_is_placeholder(q, labels) and not quote_defers(q)


def _from_lines(line: Mapping, siblings: list[Mapping]) -> dict | None:
    """A line of the same review on the same field that READ a value: decided by code, or met / not met by the reader, its own
    record not "not stated", its quote verified on the page and holding a value. None when there is none."""
    labels = _labels_of(line)
    for other in siblings:
        if other is line or str(other.get("ai_verdict") or other.get("verdict")) not in ("Pass", "Fail") or says_silent(other):
            continue
        quote = verified_quote(other)
        if holds_a_value(quote, [*labels, *_labels_of(other)]):
            return {"quote": quote, "page": other.get("paper_page"), "from": FROM_LINE}
    return None


def _from_reading(line: Mapping, facts: list[Mapping]) -> dict | None:
    """A stored reading of the paper, on ANY page (not only the page the reader quoted), whose label IS the field's own label
    (`whole_label`), with a value that is no placeholder and whose value and label code found on its page."""
    labels = _labels_of(line)
    for f in facts:
        label, value = str(f.get("field_label") or ""), " ".join(str(f.get("field_value") or "").split())
        if f.get("is_blank") or not whole_label(label, labels) or not holds_a_value(value, labels):
            continue
        if f.get("on_page"):
            return {"quote": f"{label.rstrip(' :')}: {value}", "page": f.get("page"), "from": FROM_READING}
    return None


def mark_stated(lines: list[dict], facts: list[Mapping] = ()) -> list[dict]:
    """V2, THE one place that decides it: on each line whose own record says the paper does not state the value
    (`says_silent`), the value code found stated on the paper (`_from_lines`, then `_from_reading`) under `STATED_KEY`; every
    other line is returned as it is. `facts`: the paper's stored reading with `on_page` (value and label found on its page)."""
    by_field: dict[str, list[Mapping]] = {}
    for ln in lines:
        if key := _field_key(ln):
            by_field.setdefault(key, []).append(ln)
    out = []
    for ln in lines:
        if not says_silent(ln) or proven(ln) or not (key := _field_key(ln)):
            out.append(ln)
            continue
        got = _from_lines(ln, by_field.get(key, [])) or _from_reading(ln, facts)
        out.append({**ln, STATED_KEY: got} if got else ln)
    return out


def paper_reading(paper_id: str | None) -> list[dict]:
    """The paper's stored reading (live facts) with `on_page`: its value and label found on its page by code. [] when none can
    be read (then only the review's own lines can show a stated value)."""
    if not paper_id:
        return []
    import sqlite3

    from .db import connect

    try:
        conn = connect()
        pages = {int(r[0]): " ".join(re.findall(r"[a-z0-9]+", str(r[1] or "").lower())) for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (paper_id,))}  # fmt: skip
        rows = conn.execute(
            "SELECT field_label, field_value, page, is_blank FROM submittal_facts WHERE submittal_document_id = ?"
            " AND superseded_at IS NULL",
            (paper_id,),
        ).fetchall()
    except sqlite3.Error:
        return []

    def on(text: object, page: object) -> bool:
        words = " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))
        return bool(words) and isinstance(page, int) and f" {words} " in f" {pages.get(page, '')} "

    return [
        {"field_label": r[0], "field_value": r[1], "page": r[2], "is_blank": r[3], "on_page": on(r[1], r[2]) and on(r[0], r[2])}
        for r in rows
    ]


@lru_cache(maxsize=1)
def _field_rules() -> tuple[dict, tuple[tuple[str, tuple], ...]]:
    """The approved checklist's rules and (role, the ways a sheet prints its label) of every field of its fixed field list
    (`datasheet_checks`): the one list of field labels; never one sheet's layout (rule 13)."""
    from . import datasheet_checks as dc

    rules = dc.load_rules()
    return rules, tuple(
        (role, tuple(dc.label_patterns(role, rules))) for role in sorted(rules["roles"])
    )


def _own_roles(labels) -> set[str]:
    """The fields of the fixed list this row's labels name: a role written as one, or a label the list reads as that role."""
    from . import datasheet_checks as dc

    rules, _ = _field_rules()
    out = set()
    for lab in labels:
        text = " ".join(str(lab or "").replace("_", " ").split()).lower()
        if not text:
            continue
        if text.replace(" ", "_") in rules["roles"]:
            out.add(text.replace(" ", "_"))
        if role := dc.role_of(text, rules):
            out.add(role)
    return out


def _content_words(text: object) -> set[str]:
    """The words of a label that name its subject: lowercased, plural folded, the subject check's neutral words left out."""
    from .agent_subject import NEUTRAL_WORDS, _stem

    return {
        _stem(w)
        for w in re.findall(r"[a-z0-9]+", str(text or "").replace("_", " ").lower())
        if w not in NEUTRAL_WORDS
    } - NEUTRAL_WORDS


#: The kinds of the fixed field list that are not a measured quantity: two fields of these kinds may describe one thing ("Valve type"
#: and "Bellows"), so a label of one is never said to be about another field of the other (review of PR #1872).
_UNMEASURED_KINDS = frozenset({"text", None})


def about_another_field(quote: str, labels) -> bool:
    """FTU-17: the found quote is about ANOTHER field, by code's own reading only when all of this holds:
      * this row's field is a field of the fixed field list (its roles);
      * the quote's LABEL (its words before the first ":", "|" or "="), WHOLE, is the label of a different field of that list (the
        list's own label patterns, never its value words such as "gas" or "liquid");
      * that label is no label of this field's own roles, and the quote holds none of this field's words;
      * the two fields are of DIFFERENT kinds and at least one is a measured quantity (a flow quote for a pressure field). Two text
        fields ("Valve type", "Bellows"), or two of one kind, may describe one thing: not said.
    Anything less certain is not said to be about another field (the row stays "may state it")."""
    from . import datasheet_checks as dc
    from .datasheets import normalise_field_name

    rules, _ = _field_rules()
    mine = _own_roles(labels)
    own = set().union(*(_content_words(x) for x in [*labels, *mine] if x))
    text = " ".join(str(quote or "").split())
    if not mine or not text or own & _content_words(normalise_field_name(text)):
        return False
    head = re.split(r"[:|=]", text, maxsplit=1)[0]
    other = dc.role_of(
        normalise_field_name(head), rules
    )  # a label alone, or the label before its value
    if not other or other in mine:
        return False
    kinds = {rules["roles"][other].get("kind")}
    mine_kinds = {rules["roles"][r].get("kind") for r in mine}
    return not kinds & mine_kinds and not (kinds | mine_kinds) <= _UNMEASURED_KINDS


def silent_row(line: Mapping, what: str = "", where: str = "") -> SilentRow | None:
    """`silent_row_words` of an AI line whose own record says the paper does not state the value (`says_silent`) and whose quote code
    found on the page does not defer the value (a deferral is read as one); None for any other line, and None for a line code
    proved (a Pass or Fail decided by code: its proof words are its own, `absence_proof`, and the reader's quote is not its evidence).
    A two-reader "not stated" (`agent_review_two_reader.absence_agrees`) keeps its verdict only on a label-alone quote, said so."""
    from .agent_review_crs import field_words

    quote, name = verified_quote(line), what or field_words(line)
    labels = (line.get("field_label_ai"), line.get("field"), *(line.get("field_roles") or []))
    stated = line.get(STATED_KEY)
    if stated and says_silent(line) and not proven(line) and _would_ask_to_state(line, quote, [name, *labels]):
        return stated_row_words(name, stated, where)  # order 14 LPV V2: never ask for a value the paper states
    if not quote or not says_silent(line) or quote_defers(quote) or proven(line):
        return None
    agreed = two.absence_agrees(line)
    value_field = bool(line.get("raw_unit")) or asks_a_value(
        line.get("clause_quote"), line.get("requirement")
    )
    return silent_row_words(name, quote, labels, where, agreed, value_field)


def unverified_row(line: Mapping, what: str = "") -> SilentRow | None:
    """FTU-17: every wording cell of a row whose quote code did NOT find on the page and whose own record would otherwise ask the
    contractor (`action_case` is `UNVERIFIED`): the quote decides nothing, its words are never shown as the paper's, and the engineer
    checks. None for any other line."""
    from .crs_ai_workbook import (
        field_words,
    )  # the comment's own field words, never the reader's unverified label

    if proven(line) or action_case(line) != UNVERIFIED:
        return None
    what = what or field_words(line) or "the value asked for"
    note = "The words the reader quoted were not found on the page by code; they are not evidence."
    return SilentRow(
        UNVERIFIED,
        UNVERIFIED_REASON,
        f"Engineer to check {what}: the words quoted were not found on the page by code.",
        note,
        "not found on the page by code; not evidence",
        f"{note} Not confirmed: {UNVERIFIED_REASON}.",
    )


def engineer_question(line: Mapping) -> bool:
    """FTU-17: the row is the engineer's question by its own record (a quote code did not find, `unverified_row`; a "does not apply"
    without its proof), so NO cell of it asks the contractor."""
    from .agent_review_wording import not_applicable_question

    return unverified_row(line) is not None or not_applicable_question(line)


def proven(line: Mapping) -> bool:
    """A Pass or Fail decided by code (the stored verdict; `agent_review_wording.classify` step 4 calls it proven)."""
    return line.get("verdict") in ("Pass", "Fail")


def absence_proof(line: Mapping) -> str:
    """FTU-1: the reason of a Fail code proved by its own search of every page (decided by absence); "" for any other line."""
    from .agent_review_crs import field_words
    from .agent_review_verdict import BY_ABSENCE, FAIL

    if line.get("verdict") != FAIL or line.get("decided_by") != BY_ABSENCE:
        return ""
    pages = ", ".join(str(p) for p in line.get("pages_searched") or [])
    return (
        f"code searched every page for {field_words(line) or 'the value asked for'} and found no value"
        + (f" (pages searched: {pages})" if pages else "")
    )


def silent_quote(line: Mapping) -> str:
    row = silent_row(line)
    return row.kind if row else ""


def looked_only(line: Mapping) -> bool:
    return silent_quote(line) == LOOKED


def quote_cell(line: Mapping, where: str = "") -> str:
    """FTU-16: the ONE cell of a sheet that says the paper and the reason together for a silent row ("" for any other line); FTU-17: a
    row whose quote code did not find says so there (`unverified_row`), never the quote as the paper's words."""
    row = silent_row(line, where=where) or unverified_row(line)
    return row.cell if row else ""


_STAR = re.compile(r"(?:^|[\s(])\*+(?=[\s)]|$)")


def sheet_mark(line: Mapping) -> str:
    """How the sheet marks a deferred value, from the quote code VERIFIED on the page (lane D): " (marked * on page N)" for a lone star,
    ' (marked "<its words>" on page N)', " (left open on page N)" with no verified quote; "" when not even the page is known."""
    from .agent_review_crs import stated

    has, page = stated(line), line.get("deferred_page") or line.get("paper_page")
    on = f" on page {page}" if page not in (None, "") else ""
    if has and _STAR.search(has):
        return f" (marked *{on})"
    return f' (marked "{has}"{on})' if has else (f" (left open{on})" if on else "")


def provisional(line: Mapping) -> bool:
    """The sheet prints a FIGURE with a unit beside its deferral mark ("340 psig By Contractor"): a provisional value to be confirmed, not
    a blank to be provided. Read by the app's one number reader (`claims.extract_measurements`) in the verified quote only."""
    from .claims import extract_measurements

    quote = (
        " ".join(str(line.get("paper_quote") or "").split())
        if (line.get("quotes_checked") or {}).get("paper")
        else ""
    )
    return bool(quote) and bool(extract_measurements(quote))


def reason_for(line: Mapping, why: str) -> str:
    """The reason shown with a line, made to agree with the line's OWN reason code (FTU-1): a line that says the paper does not state the
    value says so when code can show its found quote is no value (`LOOKED`); when the quote may state it, neutral words (`CONTRADICTS`);
    otherwise the stored reason in plain words."""
    if proof := absence_proof(line):  # FTU-1: a code-proved absence says its proof
        return proof
    row = silent_row(line) or unverified_row(line)
    return row.reason if row else why


def query_action(line: Mapping, what: str, ref: str) -> str:
    """Part 3 of a Query: the sentence for the case the line is in."""
    if row := silent_row(line, what) or unverified_row(
        line, what
    ):  # FTU-1 / FTU-17: a silent row's action is decided with its other cells
        return row.action
    case = action_case(line)
    if case == "stated":
        return f"Contractor to confirm or justify {what}{' against ' + ref if ref else ''}."
    if (
        case == "deferred"
    ):  # lane D: the words follow what the sheet shows (its mark, its page, a provisional figure)
        if provisional(line):
            return f"Contractor to confirm the provisional value of {what}{sheet_mark(line)}{' against ' + ref if ref else ''}."
        return f"Contractor to provide {what}{sheet_mark(line)}; it is deferred on the sheet."
    if case == "disagree":
        return f"Engineer to check {what}: the readers disagree."
    if case == "cut_off":
        return f"Engineer to check {what}: the second AI reader's answer was cut off, so the two readers did not agree."
    if case == "unknown":
        return f"Engineer to check {what}."
    return f"Contractor to state {what}, or the page where it is shown."


def reasoning_part(line: Mapping, status: str, guard: str) -> str:
    """The AI reviewer's own reasoning, plain and labelled as its view, for an opinion, a two-reader verdict or a Query; "" for a proven
    line, and "" when a guard's own view sentence is already printed."""
    if guard or status not in _SAYS:
        return ""
    # the AI's own `reasoning`, WHOLE (no character cut: a cell is never cut without the mark and its full text); never the model's
    # contractor-facing `comment` under this label
    view = words.plain(" ".join(str(line.get("reasoning") or "").split()))
    return f" {REASONING_LABEL} {view}" if view else ""
