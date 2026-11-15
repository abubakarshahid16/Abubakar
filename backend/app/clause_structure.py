"""Numbered clauses written like BODY TEXT, read from the standard's own evidence taken together (owner, 16 Nov 2026: "fix the heading reader").

`subject_scope._headings` recognises a numbered clause only when a title word (3+ letters, capitalised) follows its number. A clause that starts like a sentence ("7.1.2.4
A corrosion allowance ... is not required ...") opens and closes nothing: the clause before it runs on, often to the END OF THE BOOK, and the clause itself is "not found".

This pass finds those clauses and nothing else. A line is a body-text clause ONLY when ALL of this holds:
  1. it starts with a dotted id of two components or more ("7.1.2.4");
  2. the id is the IMMEDIATE successor, in the sequence the book itself establishes, of the last clause accepted before it: its first child (7.1.2.3 -> 7.1.2.3.1), its next sibling
     (-> 7.1.2.4) or the next sibling of one of its ancestors (-> 7.1.3, 7.2). The sequence restarts ONLY at a titled heading `_headings` already read (as certain as the start);
     a body-text number never restarts it: after a missed clause the rest of the run is "boundary not certain" until the next titled heading;
  3. the line before it (across a page break, past running headers and footers and page numbers) ends a sentence or is a heading;
  4. it is no running header or footer (a digit-free form repeated at the page edges) and stands on no contents page;
  5. the first word after the id starts with a capital letter and is no unit, month or cross-reference word, and the line is no table row or contents entry (it ends in a number,
     has dot leaders, or holds three figures or more).
Everything else stays what it was: not a heading. When the evidence is not enough the reader says nothing, and consumers keep today's behaviour ("boundary not certain").
Pure: lines in, a dict out. No database, no model, no book-specific rule.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence

_ID = re.compile(r"^(?P<id>\d{1,3}(?:\.\d{1,3}){1,5})\.?\s+(?P<rest>\S.*)$")
_FIRST_WORD = re.compile(r"^[\(\[]?(?P<w>[A-Za-z][A-Za-z\-]*)")
#: words after an id that make it a REFERENCE or a value, never a clause: "7.4 applies where", "7.2 of this standard", "7.5 times", "12.05 November"
_NOT_A_START = frozenset(
    {
        *[
            "of",
            "and",
            "or",
            "to",
            "through",
            "applies",
            "apply",
            "applicable",
            "per",
            "see",
            "accordance",
        ],
        *[
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
            "jan",
            "feb",
            "mar",
            "apr",
            "jun",
            "jul",
            "aug",
            "sep",
            "sept",
            "oct",
            "nov",
            "dec",
        ],
        *[
            "mm",
            "cm",
            "km",
            "ft",
            "psi",
            "bar",
            "mpa",
            "kpa",
            "gpa",
            "hz",
            "khz",
            "mhz",
            "kg",
            "mg",
            "lb",
            "deg",
            "degc",
            "degf",
        ],
    }
)  # a sentence starter that is also a lower-case reference word ("If", "When", "Where", "In") is NOT here: a capital letter already separates "7.4 applies" from "7.4 If"
_CAPITAL_UNITS = frozenset(
    {"MPa", "GPa", "Pa", "Hz", "MHz", "kPa", "kHz", "Nm", "kW", "MW", "Btu"}
)
_ENDS_SENTENCE = re.compile(r"[.;:?!][\"'”\)\]]*$")
_DOT_LEADERS = re.compile(r"\.{3,}|(?:\.\s){3,}")
_FIGURE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?(?![A-Za-z])")
_ALONE = re.compile(r"^(?P<id>\d{1,3}(?:\.\d{1,3}){1,5})\.?$")
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?\d{1,4}(?:\s+of\s+\d{1,4})?$", re.IGNORECASE)


def ids(ident: str) -> tuple[int, ...]:
    return tuple(int(p) for p in ident.split("."))


def immediate_successor(ident: tuple[int, ...], last: tuple[int, ...]) -> bool:
    """Is `ident` the very next clause after `last`: its first child, its next sibling, or the next sibling of one of its ancestors (4.1 -> 4.1.1, 4.2, 5)?"""
    if ident == (*last, 1):
        return True
    return any(ident == (*last[:k], last[k] + 1) for k in range(len(last)))


def is_next(head: str, clause: str) -> bool:
    """Is the id `head` the IMMEDIATE successor of the id `clause` (both plain dotted numbers)?"""
    plain = re.compile(r"\d{1,3}(?:\.\d{1,3}){0,5}")
    return bool(
        plain.fullmatch(head)
        and plain.fullmatch(clause)
        and immediate_successor(ids(head), ids(clause))
    )


def _is_table_or_contents_entry(rest: str) -> bool:
    return bool(
        _DOT_LEADERS.search(rest)
        or re.search(r"\s[\d.,]+$", rest)
        or len(_FIGURE.findall(rest)) >= 3
    )


def _previous_content_line(
    lines: Sequence[str], index: int, running: set[str]
) -> int | None:
    """The nearest earlier line that is neither a running header or footer nor a page number (the text really before the line, across a page break)."""
    for j in range(index - 1, -1, -1):
        line = lines[j]
        if (
            not line.strip()
            or _PAGE_NUMBER.match(line.strip())
            or re.sub(r"\d+", "#", line) in running
        ):
            continue
        return j
    return None


def _ending(line: str) -> str:
    last = line.rstrip()[-1:] if line.strip() else ""
    return (
        "a closing bracket"
        if last in ")]"
        else "a digit"
        if last.isdigit()
        else "a comma"
        if last == ","
        else "a letter"
        if last.isalpha()
        else "another sign"
    )


class BodyClauses:
    """The clauses found, and why the others were not (counts, for the measurement and the tests)."""

    def __init__(self) -> None:
        self.heads: dict[int, tuple[str, str]] = {}
        #: the indexes of numbered heads (titled ones and the ones found here) whose START is as sure as a clause start: the line before ends a sentence or is a heading, no
        #: running line, no table row. Only these can END a clause for certain when they are its immediate successor; another heading closes it softly, as before.
        self.sure: set[int] = set()
        self.rejected: Counter = Counter()
        #: how the line before ended, for the lines refused because it did not end a sentence (the measurement of what is left)
        self.before_ended: Counter = Counter()


def body_clauses(
    lines: Sequence[str],
    heads: Sequence[tuple[str, str] | None],
    bare: set[int],
    running: set[str],
    contents: set[int],
) -> BodyClauses:
    """The body-text clauses of a standard. `lines`: every line in reading order; `heads`: the heading each line opens (`subject_scope._headings`); `bare`: the bare ones;
    `running`: the digit-free forms of the running lines; `contents`: the indexes of the lines on contents pages."""
    out = BodyClauses()
    last: tuple[int, ...] | None = None
    for i, line in enumerate(lines):
        head = heads[i]
        if head is not None and head[0] == "number":
            before = _previous_content_line(lines, i, running)
            # a one-component number ("5 Carbon steel flanges") may be a table row inside the clause before it: never sure
            sure = (
                "." in head[1]
                and re.sub(r"\d+", "#", line) not in running
                and not _is_table_or_contents_entry(line[len(head[1]) :])
                and (
                    before is None
                    or heads[before] is not None
                    or bool(_ENDS_SENTENCE.search(lines[before].rstrip()))
                )
            )
            if i not in bare:
                last = ids(
                    head[1]
                )  # a titled heading restarts the sequence: as certain as the start of it
                if sure:
                    out.sure.add(i)
            elif sure and "." in head[1]:
                # a BARE heading ("7.1.3" alone, its title on the next line) is as sure as a titled one when it has two components or more (a page number has one), is the
                # immediate successor of the clause before it (`_headings` checked), and the line before ends a sentence: it may then END a clause, and restarts the sequence
                out.sure.add(i)
                last = ids(head[1])
            continue
        if head is not None or i in contents:
            continue
        alone = _ALONE.match(line)
        if alone:
            # a clause number ALONE on its line with a body sentence on the next ("7.1.2.4" / "A corrosion allowance (C.A.) is not required ..."): the same evidence as a
            # numbered line, and the next line must start a sentence (a capital letter) and be no running line, no other number and no table row
            ident = ids(alone.group("id"))
            before = _previous_content_line(lines, i, running)
            following = lines[i + 1] if i + 1 < len(lines) else ""
            if re.sub(r"\d+", "#", line) in running:
                out.rejected["running line"] += 1
            elif last is None or not immediate_successor(ident, last):
                out.rejected["not the next clause"] += 1
            elif (
                before is not None
                and heads[before] is None
                and not _ENDS_SENTENCE.search(lines[before].rstrip())
            ):
                out.rejected["the line before does not end a sentence"] += 1
                out.before_ended[_ending(lines[before])] += 1
            elif not following[:1].isupper():
                out.rejected[
                    "starts with a lower-case word or a figure (alone number)"
                ] += 1
            elif (
                re.sub(r"\d+", "#", following) in running
                or _ALONE.match(following)
                or _is_table_or_contents_entry(following)
            ):
                out.rejected["table row or contents entry"] += 1
            else:
                out.heads[i] = ("number", alone.group("id"))
                out.sure.add(i)
                last = ident
            continue
        found = _ID.match(line)
        if not found:
            continue
        ident = ids(found.group("id"))
        rest = found.group("rest")
        word = _FIRST_WORD.match(rest)
        shape_ok = (
            word is not None
            and word.group("w")[0].isupper()
            and word.group("w").lower() not in _NOT_A_START
            and word.group("w") not in _CAPITAL_UNITS
            and not _is_table_or_contents_entry(rest)
        )
        before = _previous_content_line(lines, i, running)
        sentence_ok = (
            before is None
            or heads[before] is not None
            or bool(_ENDS_SENTENCE.search(lines[before].rstrip()))
        )
        successor = last is not None and immediate_successor(ident, last)
        if re.sub(r"\d+", "#", line) in running:
            out.rejected["running line"] += 1
        elif not successor:
            out.rejected[
                "well-formed but not the next clause (after a break, or a stray number)"
                if shape_ok and sentence_ok
                else "not the next clause"
            ] += 1
        elif word is None:
            out.rejected["starts with a figure or sign"] += 1
        elif not word.group("w")[0].isupper():
            out.rejected["starts with a lower-case word"] += 1
        elif not shape_ok:
            out.rejected["cross-reference, unit or date word"] += 1
        elif not sentence_ok:
            out.rejected["the line before does not end a sentence"] += 1
        else:
            out.heads[i] = ("number", found.group("id"))
            out.sure.add(i)
            last = ident
    return out


def contents_lines(
    pages: Sequence[Sequence[str]],
    shape_of: Callable[[str], tuple | None],
    least: int,
    share: float,
) -> set[int]:
    """The indexes (over all lines in reading order) of the lines on contents pages: a page where at least `share` of the heading-shaped lines (`least` or more of them) are
    contents entries. The same test `subject_scope._headings` applies."""
    out: set[int] = set()
    base = 0
    for lines in pages:
        shapes = [s for s in map(shape_of, lines) if s]
        if len(shapes) >= least and sum(s[2] for s in shapes) >= share * len(shapes):
            out.update(range(base, base + len(lines)))
        base += len(lines)
    return out
