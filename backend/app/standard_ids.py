"""ONE matcher for standard identifiers (W3, #452; audit A02, A03).

Every place that asks "is the standard a document cites the same standard as
this library document?" asks it here: review scope (`applicability`), the
"cited but not in your library" lists, the chat named-standard lookup
(`understanding`, `answerability`, `chat_comparison`, `chat_tools`) and the
Claude selection gate. Before this module each of them compared identifiers its
own way, and two of the ways were wrong in opposite directions:

- A02/A03: a PREFIX match (`"API650".startswith("API65")`, or a substring test)
  made "API 65" and "API 6500" the same standard as "API 650".
- The live check of 2026-10-08: a datasheet citing "API RP 520 Pt-1" was not
  matched to the API 520 Part I document in the library, because one key kept
  "RP" and the other did not, so neither key was a prefix of the other. The
  review never used API 520.

So an identifier is PARSED into (family, number, part) instead of compared as a
string:

- the family absorbs the ways engineers write it: "API RP 520", "API Std 520",
  "API-520" are API 520; "Section VIII Div 1", "Sec VIII Div. 1", "BPVC VIII-1"
  are ASME BPVC VIII division 1; NACE MR0175 and ISO 15156 are one standard;
- the number is compared WHOLE: 65, 650 and 6500 are three standards;
- a part or division must agree when BOTH sides state one (Part I is not
  Part II); when only one side states it, a citation of part of a standard is
  a citation of that standard, which is what the old prefix rule was for.

A string that parses as nothing falls back to an exact comparison of its
punctuation-free key - never a prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

_DASHES = re.compile(r"[‐-―−]")
#: A number ends here: no more digits, and no decimal point followed by a digit
#: ("650.pdf" ends at 650; "16.5" does not end at 16).
_END = r"(?!\d|\.\d)"
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
          "IX": 9, "X": 10, "XI": 11, "XII": 12}

#: "Part I", "Pt-1", "Pt 2", ", Part 1" after the number, or a bare "-1" / "-I".
#: One or two digits only, so an edition year ("API 610-2010") is never a part.
_PART = (r"(?:\s*,?\s*(?:PART|PT)\.?\s*-?\s*(?P<part>\d{1,2}|[IVX]{1,4})\b"
         r"|-(?P<dpart>\d{1,2}|[IVX]{1,4})\b)?")


@dataclass(frozen=True)
class StandardId:
    """A parsed standard identifier. `part` is a part or division number, or None."""
    family: str
    number: str
    part: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return _EQUIVALENT.get((self.family, self.number), (self.family, self.number))

    def key(self) -> str:
        """One stable comparison key, for de-duplicating and sorting."""
        family, number = self.identity
        return f"{family} {number}" + (f" PART {self.part}" if self.part else "")


#: Two designations of ONE standard. NACE MR0175 was re-issued as ISO 15156 and
#: is cited both ways ("NACE MR0175/ISO 15156").
_EQUIVALENT = {("NACE", "MR0175"): ("ISO", "15156")}


def _arabic(token: str | None) -> str | None:
    if not token:
        return None
    token = token.upper()
    return str(_ROMAN[token]) if token in _ROMAN else str(int(token))


def _part(m: re.Match) -> str | None:
    groups = m.groupdict()
    return _arabic(groups.get("part") or groups.get("dpart"))


def _api(m: re.Match) -> StandardId:
    return StandardId("API", m.group("num"), _part(m))


def _asme_b(m: re.Match) -> StandardId:
    return StandardId("ASME B", m.group("num"))


def _asme_section(m: re.Match) -> StandardId:
    return StandardId("ASME BPVC", _arabic(m.group("sec")), _arabic(m.group("div") or m.group("ddiv")))


def _iso(m: re.Match) -> StandardId:
    return StandardId("ISO", str(int(m.group("num"))), _part(m))


def _nace(m: re.Match) -> StandardId:
    return StandardId("NACE", f"{m.group('series') or m.group('series_bare')}{m.group('num')}")


def _saes(m: re.Match) -> StandardId:
    # SAES-B-14 (a filename with the zero dropped) is SAES-B-014 (the citation).
    return StandardId("SAES", f"{m.group('letter')}-{int(m.group('num')):03d}")


def _samss(m: re.Match) -> StandardId:
    return StandardId("SAMSS", f"{int(m.group('cat')):02d}-{int(m.group('num')):03d}")


#: Families with a known shape, found ANYWHERE in the text. A number is read
#: whole and must not run on into more digits or a decimal point.
_SPECIFIC: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\b(?P<cat>\d{2})[-\s]*SAMSS[-\s]*(?P<num>\d{1,4})(?!\d)"), _samss),
    (re.compile(r"\bSAES[-\s]*(?P<letter>[A-Z])[-\s]*(?P<num>\d{1,4})(?!\d)"), _saes),
    (re.compile(r"\b(?:NACE[-\s]*(?:STANDARD|STD\.?)?[-\s]*(?P<series>MR|TM|SP|RP)|(?P<series_bare>MR))"
                r"[-\s]?(?P<num>\d{4})(?!\d)"), _nace),
    (re.compile(r"\bISO[-\s]*(?P<num>\d{3,5})" + _END + _PART), _iso),
    (re.compile(r"\b(?:ASME|ANSI)(?:\s*/\s*ANSI)?[-\s]*B[-\s]*(?P<num>\d{1,2}(?:\.\d{1,3}){1,2})" + _END),
     _asme_b),
    (re.compile(r"\bASME[-\s]*(?:BPVC[-\s]*)?,?\s*(?:SEC(?:TION)?\.?[-\s]*)?"
                r"(?P<sec>XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)\b"
                r"(?:\s*,?\s*DIV(?:ISION)?\.?[-\s]*(?P<div>\d)\b|-(?P<ddiv>\d)\b)?"), _asme_section),
    (re.compile(r"\bAPI[-\s]*(?:(?:RP|STD|STANDARD|SPEC|PUBL|MPMS|BULL|TR)\.?[-\s]*)?"
                r"(?P<num>\d{1,4}[A-Z]{0,2})" + _END + _PART), _api),
]

#: Anything else (NFPA 20, IEEE 1584, MSS SP 58, PIP VEFV1100, KOC-ME-003,
#: the invented STD-A-001): a family word, optional series letters, a whole
#: number. Read only at the START of the text, where a citation or a library
#: filename puts the identifier, so a number later in a title is never taken.
_GENERIC = re.compile(
    r"^\s*(?P<fam>[A-Z]{2,6})(?P<series>(?:[-\s]*[A-Z]{1,4}(?=[-\s]*\d))?)[-\s]*"
    r"(?P<num>\d{1,5}(?:\.\d{1,3})*[A-Z]?)" + _END + _PART)


def _clean(text: str) -> str:
    return _DASHES.sub("-", " ".join((text or "").split())).upper()


@lru_cache(maxsize=4096)
def parse_all(text: str) -> tuple[StandardId, ...]:
    """Every standard identifier in `text`, in reading order."""
    clean = _clean(text)
    found: list[tuple[int, StandardId]] = []
    taken: list[tuple[int, int]] = []
    for pattern, build in _SPECIFIC:
        for m in pattern.finditer(clean):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue  # already read by a more specific family
            found.append((m.start(), build(m)))
            taken.append((m.start(), m.end()))
    if not found:
        m = _GENERIC.match(clean)
        if m:
            family = m.group("fam") + (" " + re.sub(r"[-\s]", "", m.group("series")) if m.group("series").strip("- ") else "")
            number = m.group("num")
            number = str(int(number)) if number.isdigit() else number
            found.append((m.start(), StandardId(family, number, _part(m))))
    return tuple(ident for _, ident in sorted(found, key=lambda pair: pair[0]))


def parse(text: str) -> StandardId | None:
    """The first standard identifier in `text`, or None."""
    every = parse_all(text or "")
    return every[0] if every else None


def flat_key(text: str) -> str:
    """Punctuation and spacing dropped, upper-cased: the exact-match fallback."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def key(text: str) -> str:
    """A comparison key for de-duplicating: the parsed key, else the flat key."""
    ident = parse(text)
    return ident.key() if ident else flat_key(text)


def same_identifier(a: StandardId, b: StandardId) -> bool:
    """Same standard; a part or division must agree only when both state one."""
    return a.identity == b.identity and (a.part is None or b.part is None or a.part == b.part)


def same_standard(cited: str, other: str) -> bool:
    """Is `cited` the same standard as `other`? THE rule; see the module docstring."""
    a, b = parse(cited), parse(other)
    if a is not None and b is not None:
        return same_identifier(a, b)
    fa, fb = flat_key(cited), flat_key(other)
    return bool(fa) and fa == fb


#: Families `_SPECIFIC` can find anywhere in running text.
SPECIFIC_FAMILIES = frozenset({"API", "ASME B", "ASME BPVC", "ISO", "NACE", "SAES", "SAMSS"})


def _token_pattern(identifier: str) -> re.Pattern | None:
    """`identifier` as a boundary-safe pattern: its letter and digit runs in order,
    any dash or space between them, each number whole ("STD-A-001" finds
    "STD A 1" but never "STD-A-0012" or "XSTD-A-001")."""
    tokens = re.findall(r"[A-Z]+|\d+", _clean(identifier))
    if not tokens or not any(t.isdigit() for t in tokens):
        return None
    parts = [rf"0*{int(t)}(?!\d)" if t.isdigit() else re.escape(t) for t in tokens]
    return re.compile(r"(?<![A-Z0-9])" + r"[-\s]*".join(parts) + r"(?![A-Z0-9])")


def names_standard(text: str, identifier: str) -> bool:
    """Does `text` (a question, a sentence) name the standard `identifier` anywhere?

    Specific families are parsed out of the text and compared; any other
    identifier is looked for as a boundary-safe token pattern. Never a substring:
    that is how "API 65" was found inside "API 650"."""
    want = parse(identifier)
    if want is not None and want.family in SPECIFIC_FAMILIES:
        return any(same_identifier(want, found) for found in parse_all(text or ""))
    pattern = _token_pattern(identifier)
    return pattern is not None and pattern.search(_clean(text)) is not None
