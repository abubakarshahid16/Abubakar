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
