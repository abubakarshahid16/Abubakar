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
string. HOW: one GENERAL shape - issuing body (ANSI/ISA allowed), optional
series letters, a whole number, an optional part or division, any year
ignored - reads every body it has never seen (IEC 61511-1, EN 13445 Part 3,
ISA 84.00.01, ...). Six families whose layout differs (API, ASME B, ASME BPVC
sections, ISO, NACE, and the SAES/SAMSS company series) have their own SHAPE.
No equivalence is written in code: which names are one standard (NACE MR0175 =
ISO 15156), which body prefixes adopt another's standard (BS EN = EN) and which
words after "API" are not identity all live in the editable file
`reference/standard_identifiers.json`.

- the family absorbs the ways engineers write it: "API RP 520", "API Std 520",
  "API-520" are API 520; "Section VIII Div 1", "Sec VIII Div. 1", "BPVC VIII-1"
  are ASME BPVC VIII division 1; NACE MR0175 and ISO 15156 are one standard
  (from the file); BS EN 13445-3 is EN 13445 Part 3 (from the file);
- the number is compared WHOLE: 65, 650 and 6500 are three standards;
- a part or division must agree when BOTH sides state one (Part I is not
  Part II); when only one side states it, a citation of part of a standard is
  a citation of that standard, which is what the old prefix rule was for.

A string that parses as nothing falls back to an exact comparison of its
punctuation-free key - never a prefix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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


#: THE EDITABLE PART: which names are one standard, which body prefixes adopt
#: another body's standard, and which words after "API" are not identity. Code
#: below holds only shapes; an equivalence lives in this file (#452).
VOCABULARY_PATH = Path(__file__).parent / "reference" / "standard_identifiers.json"


@lru_cache(maxsize=1)
def vocabulary() -> dict:
    """The editable vocabulary, read once. Keys upper-cased; see the file's _comment."""
    data = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
    return {
        "equivalent": [list(group) for group in data.get("equivalent") or []],
        "body_aliases": {k.upper(): v.upper() for k, v in (data.get("body_aliases") or {}).items()},
        "api_document_words": [w.upper() for w in data.get("api_document_words") or []],
        "citation_bodies": [b.upper() for b in data.get("citation_bodies") or []],
        "class_designations": {k.upper(): [x.upper() for x in v]
                               for k, v in (data.get("class_designations") or {}).items()},
    }


def reload_vocabulary() -> None:
    """Forget the cached vocabulary and every parse made with it. A test (or a
    future admin edit) that rewrites the file calls this."""
    for cached in (vocabulary, _specific, _equivalences, parse_all, _citation_patterns):
        cached.cache_clear()


@dataclass(frozen=True)
class StandardId:
    """A parsed standard identifier. `part` is a part or division number, or None."""
    family: str
    number: str
    part: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        """(family, number), after the equivalences in the vocabulary file."""
        return _equivalences().get((self.family, self.number), (self.family, self.number))

    def key(self) -> str:
        """One stable comparison key, for de-duplicating and sorting."""
        family, number = self.identity
        return f"{family} {number}" + (f" PART {self.part}" if self.part else "")

    def literal_key(self) -> str:
        """The key WITHOUT the vocabulary's equivalences: two spellings of one
        identifier meet ("API 610", "API-610"), two equivalent standards do not
        ("NACE MR0175" and "ISO 15156" are both cited, so both are listed)."""
        return f"{self.family} {self.number}" + (f" PART {self.part}" if self.part else "")


@lru_cache(maxsize=1)
def _equivalences() -> dict[tuple[str, str], tuple[str, str]]:
    """(family, number) -> the canonical (family, number), from `equivalent`.
    Each name in the file is read by this module's own parser, so the file is
    written the way engineers write identifiers, not in an internal format."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for group in vocabulary()["equivalent"]:
        idents = [parse(name) for name in group]
        if not idents or idents[0] is None:
            continue
        canonical = (idents[0].family, idents[0].number)
        for ident in idents[1:]:
            if ident is not None:
                out[(ident.family, ident.number)] = canonical
    return out


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


@lru_cache(maxsize=1)
def _specific() -> list[tuple[re.Pattern, object]]:
    """Families whose SHAPE differs from the general one, found ANYWHERE in the
    text: where their section, division or company series sits. Shapes only -
    no equivalence and no word list is written here (API's document words come
    from the vocabulary file). A number is read whole: it must not run on into
    more digits or a decimal point."""
    api_words = "|".join(re.escape(w) for w in vocabulary()["api_document_words"]) or "(?!)"
    return [
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
        (re.compile(r"\bAPI[-\s]*(?:(?:" + api_words + r")\.?[-\s]*)?"
                    r"(?P<num>\d{1,4}[A-Z]{0,2})" + _END + _PART), _api),
    ]


#: THE GENERAL SHAPE, for every other body (IEC 61511-1, EN 13445 Part 3,
#: ISA 84.00.01, NFPA 20, IEEE 1584, MSS SP 58, PIP VEFV1100, KOC-ME-003, the
#: invented STD-A-001): issuing body (one word, or two joined by "/" as in
#: ANSI/ISA), optional series letters (BS EN, MSS SP), a whole number (dotted
#: allowed: 84.00.01), optional part or division; a trailing year (":2019",
#: "-2022", " 2021") is not part of the identity and is ignored. Read only at
#: the START of the text, where a citation or a library filename puts the
#: identifier, so a number later in a title is never taken.
_GENERIC = re.compile(
    r"^\s*(?P<fam>[A-Z]{2,6}(?:/[A-Z]{2,6})?)(?P<series>(?:[-\s]*[A-Z]{1,4}(?=[-\s]*\d))?)[-\s]*"
    r"(?P<num>\d{1,5}(?:\.\d{1,3})*[A-Z]?)" + _END + _PART)


def _clean(text: str) -> str:
    return _DASHES.sub("-", " ".join((text or "").split())).upper()


@lru_cache(maxsize=4096)
def parse_all(text: str) -> tuple[StandardId, ...]:
    """Every standard identifier in `text`, in reading order."""
    clean = _clean(text)
    found: list[tuple[int, StandardId]] = []
    taken: list[tuple[int, int]] = []
    for pattern, build in _specific():
        for m in pattern.finditer(clean):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue  # already read by a more specific family
            found.append((m.start(), build(m)))
            taken.append((m.start(), m.end()))
    if not found:
        m = _GENERIC.match(clean)
        if m:
            family = m.group("fam") + (" " + re.sub(r"[-\s]", "", m.group("series")) if m.group("series").strip("- ") else "")
            # A national adoption is the adopted standard (BS EN 13445 = EN 13445):
            # the vocabulary file's body_aliases, never a list in code.
            family = vocabulary()["body_aliases"].get(family, family)
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


# ------------------------------------------------------------ the citation reader
#
# THE SAME GRAMMAR, used to FIND identifiers in running text (a datasheet, a
# requirement) instead of reading one identifier (#623). The matcher above was
# only as good as what the reader handed it: the old reader in `datasheets` was
# a list of families, and an IEC, EN, ISA or ISO-with-a-part citation never
# reached the matcher, so it was neither matched nor listed missing.

#: "Part 1" / "Pt-1" in any case: running text is not upper-cased for the
#: general shape, so the part word must not need to be.
_PART_ANY_CASE = _PART.replace("(?:PART|PT)", "(?i:PART|PT)")

#: In running text a short API, SAES or SAMSS number is far more often a
#: quantity or a truncation than a citation - the reader's long-standing rule,
#: kept: API needs 3-4 digits, or 1-2 digits with a letter suffix (6D, 5L);
#: SAES and SAMSS need a 3-4 digit series number as written ("SAES-B-14" in
#: prose is not read; the forgiving padded read is for FILENAMES only).
_API_IN_TEXT = re.compile(r"\d{3,4}[A-Z]{0,2}|\d{1,2}[A-Z]{1,2}")
_FOUR_DIGIT_YEAR_AFTER = re.compile(r"-\d{4}(?![\dA-Za-z])")
#: One more level of part after a part: the "-1" of "IEC 60534-2-1".
_SUB_PART = re.compile(r"-\d{1,2}(?![\dA-Za-z])")


@lru_cache(maxsize=1)
def _citation_patterns() -> tuple[re.Pattern, list[re.Pattern]]:
    """The general shape for the vocabulary's `citation_bodies`, and the
    class-letter shapes for its `class_designations`. Bodies, never standards,
    and both from the editable file."""
    v = vocabulary()
    bodies = sorted({b.upper() for b in v.get("citation_bodies") or []}, key=len, reverse=True)
    alt = "|".join(re.escape(b) for b in bodies) or "(?!)"
    general = re.compile(
        r"(?P<body>(?:" + alt + r")(?:/(?:" + alt + r"))?)"
        r"(?P<series>(?:[-\s]+[A-Z]{1,4}(?=[-\s]*\d))?)[-\s]*"
        r"(?P<num>\d{2,5}(?:\.\d{1,3})*[A-Z]?)" + _END + _PART_ANY_CASE
        + r"(?P<year>:\d{4}(?!\d))?")
    classes = [re.compile(re.escape(body.upper()) + r"[-\s]+(?:(?i:CLASS)[-\s]*)?(?:"
                          + "|".join(re.escape(letter) for letter in letters) + r")\b")
               for body, letters in (v.get("class_designations") or {}).items()]
    return general, classes


def _same_length_upper(text: str) -> str:
    """`text` upper-cased and dashes folded, character for character, so a match
    position in it is the same position in `text`."""
    folded = _DASHES.sub("-", text)
    return "".join(c.upper() if len(c.upper()) == 1 else c for c in folded)


def _standalone(text: str, start: int, end: int) -> bool:
    """A citation stands on its own: it is not the middle of a hyphen-joined
    code (a tag "21-PV-1234", a document number "P-1234-0001-SP-9999") and
    nothing alphanumeric is glued to either end. A four-digit edition year after
    a dash ("API 610-2010") is allowed; any other "-X" continuation is not."""
    if start > 0:
        before = text[start - 1]
        if before.isalnum():
            return False
        if before == "-" and start > 1 and text[start - 2].isalnum():
            return False
    if end < len(text):
        after = text[end]
        if after.isalnum():
            return False
        if after == "-" and end + 1 < len(text) and text[end + 1].isalnum() \
                and not _FOUR_DIGIT_YEAR_AFTER.match(text, end):
            return False
    return True


def _strict_enough(build, m: re.Match) -> bool:
    if build is _api:
        return bool(_API_IN_TEXT.fullmatch(m.group("num")))
    if build in (_saes, _samss):
        return len(m.group("num")) >= 3
    return True


def find_citations(text: str) -> list[tuple[str, int, int]]:
    """Every standard identifier cited in running `text`: (spelling as printed,
    start, end), in reading order, never overlapping. The special shapes are
    read in any case; the general shape and class letters only for a body
    written in upper case, so ordinary words never become citations. Plain
    numbers, tags, line numbers and document numbers are not read: a citation
    needs an issuing body, and must stand on its own (`_standalone`)."""
    text = text or ""
    upper = _same_length_upper(text)
    folded = _DASHES.sub("-", text)
    found: list[tuple[int, int]] = []
    for pattern, build in _specific():
        for m in pattern.finditer(upper):
            if _strict_enough(build, m):
                found.append((m.start(), m.end()))
    general, classes = _citation_patterns()
    for pattern in [general, *classes]:
        for m in pattern.finditer(folded):
            found.append((m.start(), m.end()))
    out: list[tuple[str, int, int]] = []
    taken_until = -1
    # Reading order; at one start the longer reading wins ("BS EN 13445-3", not "BS").
    for start, end in sorted(found, key=lambda span: (span[0], -span[1])):
        # A sub-part chain belongs to the citation: "IEC 60534-2-1" is part 2-1,
        # not "IEC 60534-2" followed by a stray "-1" (which `_standalone` would
        # then reject as a glued-on code).
        while (sub := _SUB_PART.match(text, end)) is not None:
            end = sub.end()
        if start < taken_until or not _standalone(text, start, end):
            continue
        out.append((" ".join(text[start:end].split()), start, end))
        taken_until = end
    return out


def cited_standards(text: str) -> list[str]:
    """The standards cited in `text`, one per identifier, as first printed.
    Two spellings of one identifier are one entry; two EQUIVALENT standards
    (NACE MR0175, ISO 15156) are two, because both were cited."""
    seen: dict[str, str] = {}
    for raw, _, _ in find_citations(text):
        ident = parse(raw)
        seen.setdefault(ident.literal_key() if ident else flat_key(raw), raw)
    return list(seen.values())
