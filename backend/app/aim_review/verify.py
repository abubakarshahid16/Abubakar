"""Code checks of the general review: every quote is found in the stored text; every number and unit comparison is made here,
never by the model.

No second number reader (CLAUDE.md, `scripts/check_second_number_reader.py`): a number is read only by `numparse`; a unit is read,
converted and compared only by the app's unit code (`claims.normalise`, `claims.compare_across_units`, `claims._compatible`, the
same calls `conditions.py` makes). Look-alike characters are folded by `word_fold.fold_compat`, never by a fold of our own.
"""

from __future__ import annotations

import re
from functools import lru_cache

#: Typography folded before a quote is looked for (by code point): curly quotes, dashes, the minus sign, no-break space, bullet.
_SUBS = {
    chr(0x2018): "'",
    chr(0x2019): "'",
    chr(0x201C): '"',
    chr(0x201D): '"',
    chr(0x2013): "-",
    chr(0x2014): "-",
    chr(0x2212): "-",
    chr(0x00A0): " ",
    chr(0x2022): " ",
}
MIN_QUOTE = 8


@lru_cache(maxsize=8192)
def norm(text: str) -> str:
    """Whitespace, case and typography folded; look-alike letters folded by the app's one word fold."""
    from app import word_fold

    s = word_fold.fold_compat(str(text or ""), lower=False, decompose=False)
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().casefold()


def _squeeze(s: str) -> str:
    """No spaces at all: survives a table cell split over two lines or a hyphen break."""
    return re.sub(r"[\s\-]", "", s)


@lru_cache(maxsize=4096)
def _hay(text: str) -> tuple[str, str]:
    h = norm(text)
    return h, _squeeze(h)


def quote_in(quote: str, text: str) -> bool:
    """True when `quote` (whitespace/case/typography folded; '...' allowed between parts, each part found in order) appears in
    `text`. A part shorter than MIN_QUOTE characters proves nothing and fails."""
    q = norm(quote)
    if len(q) < MIN_QUOTE:
        return False
    hay, hay_sq = _hay(str(text or ""))
    parts = [p.strip() for p in re.split(r"\.\.\.|\u2026|\[\.\.\.\]", q) if p.strip()]
    if not parts:
        return False
    pos, pos_sq = 0, 0
    for p in parts:
        if len(p) < MIN_QUOTE and len(parts) > 1:
            continue
        i = hay.find(p, pos)
        if i >= 0:
            pos = i + len(p)
            continue
        j = hay_sq.find(_squeeze(p), pos_sq)
        if j < 0:
            return False
        pos_sq = j + len(_squeeze(p))
    return True


def find_page(quote: str, pages: dict[int, str], hint: int | None = None) -> int | None:
    """The page that holds `quote`: the hinted page first, then any page. None when no page does."""
    order = ([hint] if hint in pages else []) + [n for n in sorted(pages) if n != hint]
    for n in order:
        if quote_in(quote, pages[n]):
            return n
    return None


# ------------------------------------------------------------------ numbers

OPS = ("<=", ">=", "<", ">", "==", "!=")
#: Two numbers with NO unit on either side (a count, a ratio): compared as numbers. Any unit goes through `claims`.
_PLAIN = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: abs(a - b) <= 1e-9 * max(1.0, abs(b)),
    "!=": lambda a, b: abs(a - b) > 1e-9 * max(1.0, abs(b)),
}
NOT_COMPARED = (
    "the units cannot be compared by the app's unit table; no conversion is guessed"
)


def _cannot(why: str) -> dict:
    return {"result": "cannot", "why": why}


def compare(
    paper_value: str, paper_unit: str, op: str, rule_value: str, rule_unit: str
) -> dict:
    """Code's comparison: {"result": "pass"|"fail"|"cannot", "why", "paper", "rule"}.

    Numbers by `numparse`; units by the app's unit code: two units of one quantity are converted by `claims.compare_across_units`
    (it holds a value whose answer the units leave open); one unit, or a unit that code does not convert, by `claims._compatible`
    (a length is never compared with a temperature; gauge against absolute is never compared). Anything else: "cannot"."""
    from app import claims, numparse

    if op not in OPS:
        return _cannot(f"operator {op!r} is not one code compares")
    pv, rv = (
        numparse.parse_value(str(paper_value)),
        numparse.parse_value(str(rule_value)),
    )
    if pv is None or rv is None:
        return _cannot("a value is not a number")
    pu, ru = str(paper_unit or "").strip(), str(rule_unit or "").strip()
    note = ""
    if not pu and not ru:
        ok = _PLAIN[op](pv, rv)
    elif not pu or not ru:
        return _cannot("one value has a unit and the other has none")
    else:
        equality = op in ("==", "!=")
        observed = claims.normalise(str(paper_value), pu)
        limit = claims.normalise(str(rule_value), ru, None if equality else op)
        crossed = claims.compare_across_units(observed, limit)
        if crossed is not None:
            verdict, note = crossed.verdict, str(crossed.note or "")
            if verdict is None:
                return _cannot(str(crossed.obstacle or NOT_COMPARED))
        else:
            verdict = claims._compatible(observed, limit)
            if verdict is None:
                return _cannot(f"unit {pu} or {ru}: {NOT_COMPARED}")
        ok = (not verdict) if op == "!=" else bool(verdict)
    shown = f"{paper_value} {pu}".strip() + f" {op} " + f"{rule_value} {ru}".strip()
    why = f"{shown}: {'true' if ok else 'false'}" + (f" ({note})" if note else "")
    return {
        "result": "pass" if ok else "fail",
        "why": why,
        "paper": [pv, pu],
        "rule": [rv, ru],
    }


#: The comparison words of the app's one comparator vocabulary (`claims`), as the operators `compare` takes.
_OP_OF = {
    "max": "<=",
    "min": ">=",
    "<=": "<=",
    ">=": ">=",
    "<": "<",
    ">": ">",
    "==": "==",
}


def quoted_value(value, quote: str) -> dict | None:
    """The number `value` as the verified `quote` itself states it: {"value", "unit", "op"} read by code from the quote's own
    words (`claims.extract_measurements` for a number with its unit, else `numparse.find_numbers` for a bare number; the operator
    from the words before it, `claims.comparator_ending`). None when the quote does not state that number. Nothing is taken from
    the model here: a code stamp rests only on what the quotes say."""
    from app import claims, numparse

    target = numparse.parse_value(str(value if value is not None else ""))
    if target is None or not quote:
        return None
    for m in claims.extract_measurements(quote):
        got = numparse.parse_value(str(m.raw_value))
        if got is not None and abs(got - target) < 1e-9:
            return {
                "value": str(m.raw_value),
                "unit": str(m.raw_unit or ""),
                "op": _OP_OF.get(str(m.comparator or "")),
            }
    for n in numparse.find_numbers(quote):
        if n.value is not None and abs(n.value - target) < 1e-9 and n.sign != "-":
            words = claims.comparator_ending(quote[: n.start]) or ""
            return {
                "value": quote[n.start : n.end].strip(),
                "unit": "",
                "op": _OP_OF.get(words),
            }
    return None


def rule_operator(rule_quote: str) -> str | None:
    """The ONE comparison the rule's verified words name, with no number needed ("shall not exceed the allowed pressure" -> "<="),
    read by the app's one comparator vocabulary (`claims.comparator_ending`, at every word end). None when the words name none,
    or name two different ones (ambiguous: never guessed)."""
    from app import claims

    text = str(rule_quote or "")
    found = set()
    for m in re.finditer(r"\S+", text):
        words = claims.comparator_ending(text[: m.end()])
        op = _OP_OF.get(str(words or ""))
        if op:
            found.add(op)
    return found.pop() if len(found) == 1 else None


# ------------------------------------------------------------------ a clause number is shown only if the book prints it

CLAUSE_NOT_FOUND = "clause not found in the book"
#: How many pages before the rule's own page a clause's heading may stand.
CLAUSE_PAGES_BEFORE = 3
_CLAUSE_WORDS = r"(?:clause|section|sec\.?|paragraph|para\.?|\u00a7|annex|appendix)"


def clause_in_book(clause: str, pages: dict[int, str], near: int | None) -> bool:
    """Does the book print `clause` AS a clause: at the start of a line, or after a clause word ("clause 4.2", "section 4.2"), on
    the rule's page or the CLAUSE_PAGES_BEFORE pages before it (the whole book when the page is not known)? A number that only
    appears inside a sentence or a formula ("M = 28.96") is not a clause. A clause with no digit (a heading word) is found when
    the words stand on those pages. An empty clause has nothing to check."""
    c = " ".join(str(clause or "").split())
    if not c:
        return True
    wanted = (
        {n: pages[n] for n in range(near - CLAUSE_PAGES_BEFORE, near + 1) if n in pages}
        if isinstance(near, int) and near in pages
        else pages
    )
    if not re.search(r"\d", c):
        return any(norm(c) in norm(t) for t in wanted.values())
    body = r"\s*".join(re.escape(part) for part in c.split())
    pat = re.compile(
        r"(?:^[ \t]*(?:"
        + _CLAUSE_WORDS
        + r"[ \t]*)?|\b"
        + _CLAUSE_WORDS
        + r"\s*)"
        + body
        + r"(?![0-9]|\.[0-9])",
        re.IGNORECASE | re.MULTILINE,
    )
    return any(pat.search(t or "") for t in wanted.values())


def keep_clause_if_found(line: dict, text, near: int | None) -> None:
    """A line's clause is kept only when its book prints it (`clause_in_book`); else the standard stays, the clause is blank and
    the code note says CLAUSE_NOT_FOUND."""
    book = line.get("book_document_id")
    if not book or not line.get("clause"):
        return
    if not clause_in_book(str(line["clause"]), text.pages(str(book)), near):
        line["clause"] = ""
        if (
            line.get("code") not in _whole_notes()
        ):  # a line never judged keeps its one note (it is no finding)
            line["code"] = "; ".join(
                x for x in (line.get("code"), CLAUSE_NOT_FOUND) if x
            )


def _whole_notes() -> tuple[str, ...]:
    """The notes that are a line's whole content (not judged, not on any page, does not apply): never extended. Read from their
    one home each."""
    from . import NOT_JUDGED
    from .engine import NOT_CITED
    from .steps import NOT_ON_ANY_PAGE

    return (NOT_JUDGED, NOT_ON_ANY_PAGE, NOT_CITED)
