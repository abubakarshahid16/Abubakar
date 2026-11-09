"""The judge's tie between a REMOVE and the ROW'S CLAIM (#1690, part of #805). Pure functions; no model, no database.

A REMOVE is the worst mistake the judge can make, so its power is NARROWED to the ONE case code can verify completely:
'already_stated' on a row that asserts an ABSENCE. Everything else ('complies', 'not_applicable') is only a NOTE for the
engineer (UNSURE). `already_stated_problem` is the whole rule; it needs ALL of:

  * the ROW itself asserts an absence (the absence lexicon on the row's own text; a miss means not removable);
  * the row holds no figure with a unit (an absence claim has no figure) and no condition or qualifier outside its subject;
  * the document quote is `<label><separator><value>` and the label equals the row's subject as an ORDERED word sequence
    (no extra word before or after, no No/Not/Without prefix, letters only);
  * the value is exactly NUMBER + UNIT (a nonzero number, a unit of the dimension the subject names: a subject that names
    no quantity can only be stated by a DATE) or a DATE; a digit alone is never a value;
  * the row's page comes ONLY from its page/section cell, the quote is on that page, no cell no REMOVE;
  * the subject has two or more content words, not only generic ones, and no other row shares it (a template prefix);
  * the quote does not repeat six or more consecutive words of the row's comment, and says nothing of absence.
"""

from __future__ import annotations

import re

from . import blank_markers, claims, numparse
from .agent_subject import NEUTRAL_WORDS, _stem
from .agent_tools import NOT_MENTIONED_WORDS

MAX_SUBJECT_WORDS = 5
MIN_SUBJECT_WORDS = 2
REPEAT_RUN = 6
#: Subjects too general to tie a quote to a row: a subject made only of these words can never be removed.
GENERIC_SUBJECT_WORDS = frozenset({"data", "information", "info", "detail", "document", "documentation", "requirement", "item", "general", "note", "design", "equipment", "system", "specification", "drawing", "datum",})  # fmt: skip
#: Absence and negation words the first list does not hold. Matched as WHOLE words ("lacks" is not in "black").
ABSENCE_EXTRA = (
    "omitted", "omit", "omits", "no information", "no info", "does not state", "do not state", "did not state",
    "lacks", "lack", "lacking", "not available", "to be advised", "to be confirmed", "to be provided", "not addressed",
    "not defined", "not included", "none given", "no value", "unspecified", "unknown", "tba", "tbc", "tbd",
    "pending", "void", "empty", "nil", "none", "unavailable", "under review", "to follow", "by others", "see note",
    "in progress", "later", "not indicated", "not listed", "without value", "never issued", "no data", "not applicable",
    "awaiting", "deferred", "withheld", "not declared", "vendor to advise", "as per vendor",
    "to be issued", "not defined", "incomplete", "outstanding", "reserved", "tba", "by vendor", "by supplier",
)  # fmt: skip
_ABSENCE = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(
        re.escape(w).replace(r"\ ", r"\s+")
        for w in (*NOT_MENTIONED_WORDS, *ABSENCE_EXTRA)
    )
    + r")(?![a-z0-9])",
    re.IGNORECASE,
)
_CUT = re.compile(r"[0-9:=(;\[]")
_CLAUSE_REF = re.compile(
    r"\b(?:clause|cl\.|section|sec\.|para(?:graph)?\.?|item|table|figure|fig\.|page|pages|p\.|pp\.|annex|appendix)\s*[a-z]?\d+(?:\.\d+)*[a-z]?",
    re.IGNORECASE,
)
_DOTTED = re.compile(r"\b\d+(?:\.\d+){2,}\b")
_FIGURE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([A-Za-z%°/][A-Za-z0-9%°/.²³]*)")
_PAGE_WORD = re.compile(
    r"\b(?:pages?|pp?\.?)\s*(\d+(?:\s*(?:,|and|&)\s*\d+)*)", re.IGNORECASE
)


def _content_words(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z]+", str(text).lower())]


def head_words(text: object) -> tuple[str, ...]:
    """The content words at the head of `text` IN ORDER, stemmed (see head_subject)."""
    head = _CUT.split(str(text or ""))[0]
    out: list[str] = []
    for raw in re.findall(r"[a-z]+", head.lower()):
        word = _stem(raw)
        neutral = raw in NEUTRAL_WORDS or word in NEUTRAL_WORDS
        if neutral and not out:
            continue  # leading articles and the like
        if neutral:
            break
        out.append(word)
    return tuple(out)


def head_subject(text: object) -> frozenset[str]:
    """The content words at the head of `text` (see head_words), as a set."""
    return frozenset(head_words(text))


def row_subject(comment: object) -> frozenset[str]:
    """The row's subject, or an EMPTY set when it cannot be used: none, more than MAX_SUBJECT_WORDS words, fewer than
    MIN_SUBJECT_WORDS, or only generic words. Such a row can never be removed."""
    found = head_subject(comment)
    if (
        not (MIN_SUBJECT_WORDS <= len(found) <= MAX_SUBJECT_WORDS)
        or found <= GENERIC_SUBJECT_WORDS
    ):
        return frozenset()
    return found


def row_pages(row: dict) -> list[int]:
    """The pages the row's PAGE/SECTION CELL names ('p. 3', 'pages 3 and 5', a bare number). A number in the comment text is
    never the row's page (it may cite the standard's page); a section number ('4.1') is not a page."""
    cell = str(row.get("page_section") or "").strip()
    pages = [
        int(n)
        for found in _PAGE_WORD.finditer(cell)
        for n in re.findall(r"\d+", found.group(1))
    ]
    if cell.isdigit():
        pages.append(int(cell))
    return list(dict.fromkeys(pages))


def words_in(text: object, words: frozenset[str]) -> bool:
    return words <= set(_content_words(str(text)))


def absence(text: object) -> bool:
    """The text says something is missing, omitted, not provided, to be advised or blank (never a basis for a REMOVE)."""
    return bool(_ABSENCE.search(str(text or ""))) or blank_markers.names_a_marker(
        str(text or "")
    )


def figures_in(comment: object) -> list[tuple[str, str]]:
    """(number, unit) pairs in the comment, after clause references and dotted numbers ('4.1.4.4') are read out."""
    text = _DOTTED.sub(" ", _CLAUSE_REF.sub(" ", str(comment or "")))
    return [(n, u) for n, u in _FIGURE.findall(text) if claims.is_unit(u.rstrip("."))]


def row_numbers(comment: object) -> set:
    """The number keys of the row's own figures."""
    return (
        set().union(*(numparse.number_keys(n) for n, _u in figures_in(comment)))
        if figures_in(comment)
        else set()
    )


def numeric_row(comment: object) -> bool:
    return bool(figures_in(comment))


def repeats_row_text(quote: object, comment: object, run: int = REPEAT_RUN) -> bool:
    """The quote contains a run of `run` or more consecutive words of the row's own comment."""
    q, c = (
        re.findall(r"[a-z0-9]+", str(quote).lower()),
        re.findall(r"[a-z0-9]+", str(comment).lower()),
    )
    grams = {tuple(c[i : i + run]) for i in range(len(c) - run + 1)}
    return any(tuple(q[i : i + run]) in grams for i in range(len(q) - run + 1))


def shared_subjects(rows) -> frozenset:
    """Subjects that head TWO OR MORE rows of the file: a template prefix, not a topic (it ties a quote to nothing)."""
    seen: dict = {}
    for row in rows:
        subject = row_subject(row.get("comment"))
        if subject:
            seen[subject] = seen.get(subject, 0) + 1
    return frozenset(k for k, n in seen.items() if n >= 2)


def removable_at_all(row: dict, shared: frozenset = frozenset()) -> bool:
    """The rules could ever let this row be removed: a usable subject that no other row shares, a page/section cell that
    names a page, a row that itself asserts an absence and holds no figure with a unit."""
    subject = row_subject(row.get("comment"))
    comment = row.get("comment")
    return (
        bool(subject)
        and subject not in shared
        and bool(row_pages(row))
        and absence(comment)
        and not numeric_row(comment)
    )


# ---- the one removal rule: 'already_stated' on an absence row ---------------------------------------------------------

_LABEL_SEP = re.compile(r"[:=|\t]")
_LABEL_OK = re.compile(r"^[A-Za-z][A-Za-z \-]*$")
_VALUE = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*([A-Za-z%\u00b0/][A-Za-z0-9%\u00b0/.\u00b2\u00b3]*)\.?$"
)
_MON3 = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)
_MONTH_FULL = {"january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december", "sept"}  # fmt: skip
_DATES = (
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$"),
    re.compile(r"^(\d{1,2}) ([A-Za-z]{3,9}),? (\d{4})$"),
    re.compile(r"^([A-Za-z]{3,9}) (\d{1,2}),? (\d{4})$"),
)
#: A qualifier or condition outside the subject: the row speaks of a particular case the label would have to carry.
QUALIFIERS = frozenset({"at", "for", "when", "if", "during", "under", "above", "below", "over", "between", "maximum", "minimum", "max", "min", "normal", "nominal", "design", "operating", "rated", "case", "per", "except", "excluding", "only", "each", "while", "after", "before"})  # fmt: skip
#: The quantity a subject names, and the dimension its unit must have (claims.unit_dimension). Unknown dimension: refused.
QUANTITY_WORDS = {
    "pressure": "pressure", "temperature": "temperature", "length": "length", "diameter": "length", "height": "length",
    "width": "length", "depth": "length", "thickness": "length", "allowance": "length", "flow": "volumetric_flow",
    "voltage": "voltage", "current": "current", "time": "time",
}  # fmt: skip


def _digits(text: str) -> str:
    """Digits of any script as ASCII digits."""
    import unicodedata

    return "".join(
        str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in text
    )


def _is_date(value: str) -> bool:
    import datetime

    for pattern, order in zip(_DATES, ("ymd", "dmy", "dMy", "Mdy"), strict=True):
        found = pattern.match(value)
        if not found:
            continue
        parts = list(found.groups())
        try:
            if order == "ymd":
                y, m, d = (int(x) for x in parts)
            elif order == "dmy":
                d, m, y = (int(x) for x in parts)
            elif order == "dMy":
                d, y = int(parts[0]), int(parts[2])
                m = _month(parts[1])
            else:
                d, y = int(parts[1]), int(parts[2])
                m = _month(parts[0])
            return 1990 <= y <= 2100 and datetime.date(y, m, d) is not None
        except (ValueError, TypeError):
            return False
    return False


def _month(word: str) -> int:
    folded = word.lower()
    if folded[:3] not in _MON3 or not (len(folded) == 3 or folded in _MONTH_FULL):
        raise ValueError(word)
    return _MON3.index(folded[:3]) + 1


def value_problem(value: object, subject: tuple[str, ...]) -> str | None:
    """None when the value is NUMBER + UNIT (nonzero, a real unit, of the dimension the subject names) or a DATE."""
    text = _digits(" ".join(str(value or "").split()))
    if _is_date(text):
        return None
    found = _VALUE.match(text)
    if not found:
        return "value_not_a_quantity_or_date"
    number, unit = found.group(1), found.group(2).rstrip(".")
    if not claims.is_unit(unit):
        return "value_not_a_quantity_or_date"
    if float(number.replace(",", ".")) == 0:
        return "value_is_zero"
    wanted = next((QUANTITY_WORDS[w] for w in subject if w in QUANTITY_WORDS), None)
    if wanted is None:  # a subject that names no quantity can only be stated by a DATE
        return "value_not_a_quantity_or_date"
    if claims.unit_dimension(unit) != wanted:
        return "unit_does_not_match_the_subject"
    return None


def head_raw(text: object) -> tuple[str, ...]:
    """The head words of `text` as written (lowercase, NOT stemmed), in order: what a label must repeat exactly."""
    head = _CUT.split(str(text or ""))[0]
    out: list[str] = []
    for raw in re.findall(r"[a-z]+", head.lower()):
        neutral = raw in NEUTRAL_WORDS or _stem(raw) in NEUTRAL_WORDS
        if neutral and not out:
            continue
        if neutral:
            break
        out.append(raw)
    return tuple(out)


def row_subject_seq(comment: object) -> tuple[str, ...]:
    """The row's subject as written, in order, or () when it cannot be used (see row_subject)."""
    return head_raw(comment) if row_subject(comment) else ()


def row_condition(comment: object, label: tuple[str, ...]) -> bool:
    """The row holds a qualifier or condition ('at', 'for', 'maximum', 'design' ...) that the label does not carry."""
    return any(
        w in QUALIFIERS and w not in label
        for w in re.findall(r"[a-z]+", str(comment or "").lower())
    )


def already_stated_problem(row: dict, doc_quote: object) -> str | tuple | None:
    """The refusal (code, or (code, detail) with words only) of an 'already_stated' REMOVE, or None when it may stand."""
    comment = row.get("comment")
    subject = row_subject_seq(comment)
    if not absence(comment):
        return "row_is_not_an_absence_claim"
    if numeric_row(comment):
        return "row_has_a_figure"
    found = _LABEL_SEP.search(str(doc_quote or ""))
    label = str(doc_quote)[: found.start()].strip() if found else ""
    seen = tuple(re.findall(r"[a-z]+", label.lower())) if _LABEL_OK.match(label) else ()
    if row_condition(comment, seen):
        return "row_has_a_condition"
    if not seen or seen != subject:
        return "subject_mismatch", {"row": list(subject), "document_quote": list(seen)}
    return value_problem(str(doc_quote)[found.end() :], tuple(_stem(w) for w in seen))
