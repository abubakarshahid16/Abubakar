"""The one place numbers, signs and exponents are read (W2, issue #445).

WHY THIS MODULE EXISTS. Before it, eight modules each read numbers with their
own regex, and each regex had a different blind spot:

  * `reader_api` / `claude_datasheet` accepted the value 5 for a quote that
    says "-5" or "2.5" (whole-word containment treats "-" and "." as word
    boundaries): audit F01-F03, issue #446.
  * `-?\\d+` regexes never saw U+2212, so a typographic "-29" was read as +29:
    issue #447.
  * `quality.normalise_text` used NFKC, which turns the superscript exponent in
    "10\u207b\u2076" into the digits "10-6": audit F14, issue #448.
  * Each of `claude_crs_comments`, `claude_recheck`, `ai_engineering_check`,
    `synthesis`, `rule_eval` re-implemented the thousands-separator and
    decimal-comma rules, so "8,300" and "9,0" meant different things in
    different gates.

WHAT IT OWNS. (1) `normalise_text`: NFC plus a small EXPLICIT character map.
(2) `find_numbers`: every number in a piece of text, with its sign, exponent
and span. (3) `parse_value`: one number written alone, strictly. (4)
`value_in_text`: is this figure stated in this text, whole token, same sign.
Units and comparator vocabulary stay in `claims` (one vocabulary, documented
there); this module is only the number and its sign.

WHAT IT NEVER DOES: guess. A token it cannot read as one number ("5.3.2", "1,2,3")
is returned as a COMPOUND whose key is its text, never as a float. A dash that
could be a range separator is not a minus. `parse_value` returns None for the
ambiguous cases (see there).

No import from the rest of the app: this module must stay importable by every
gate without pulling in retrieval or the database.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ------------------------------------------------------------------ characters

#: Unambiguous minus signs: U+2212 MINUS SIGN, U+FE63 SMALL HYPHEN-MINUS,
#: U+FF0D FULLWIDTH HYPHEN-MINUS. A printed one is a minus, never a separator.
MINUS_SIGNS = "\u2212\ufe63\uff0d"
#: Hyphen look-alikes that are used as a hyphen-minus: treated as "-".
HYPHENS = "-\u2010\u2011"
#: Dashes that are BOTH a minus in Word documents and a range separator.
DASHES = "\u2012\u2013\u2014\u2015"

_SUPERSCRIPTS = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
_SUPERSCRIPT_SIGNS = "\u207a\u207b"
_SUPER_TO_ASCII = str.maketrans(_SUPERSCRIPTS + _SUPERSCRIPT_SIGNS,
                                "0123456789+-")

#: Every character that can sit directly before digits as a minus OR a joiner.
DASH_LIKE = HYPHENS + MINUS_SIGNS + DASHES

#: What may stand directly before a hyphen for it to be a sign rather than a
#: joiner: the start of the text, whitespace, an opening bracket, a comparator
#: or a separator. NOT a slash ("+/-0.5" is a tolerance, not a negative), a
#: letter or a digit ("T-29", "29-343", "P-101").
_SIGN_LEAD = set(" \t\r\n\u00a0\u202f\u2009([{=<>:;,~\u2264\u2265")


# --------------------------------------------------------------- normalisation

#: The EXPLICIT map that replaces NFKC (audit F14). Only what NFKC did that the
#: product relies on is kept; everything else NFKC did (circled digits, roman
#: numeral characters, CJK compatibility forms, vulgar fractions) is no longer
#: rewritten. The characters here are listed one by one so a reviewer can see
#: exactly what changes in a document's text.
CHARACTER_MAP = {
    # Ligatures a PDF font emits as one code point.
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    # Spaces: all become one plain space.
    "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ", "\u2005": " ",
    "\u2006": " ", "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ", "\u205f": " ", "\u3000": " ",
    # Temperature and micro signs, as the unit tables spell them.
    "\u2103": "\u00b0C", "\u2109": "\u00b0F", "\u00b5": "\u03bc",
    # Ellipsis.
    "\u2026": "...",
    # The unambiguous minus signs: one hyphen-minus, so every later regex sees
    # one spelling (issue #447).
    **dict.fromkeys(MINUS_SIGNS, "-"),
    # Hyphen look-alikes.
    "\u2010": "-", "\u2011": "-",
    # Chemical subscripts as plain digits: H\u2082S is H2S.
    **{chr(0x2080 + d): str(d) for d in range(10)},
    # The few CJK-compatibility unit squares a Word document can carry.
    "\u339c": "mm", "\u339d": "cm", "\u339e": "km", "\u33a1": "m2", "\u33a5": "m3",
    "\u338f": "kg", "\u338e": "mg", "\u3396": "ml", "\u33a9": "Pa", "\u33aa": "kPa",
    "\u33ab": "MPa", "\u33ac": "GPa", "\u3390": "Hz", "\u3391": "kHz", "\u33c8": "dB",
    "\u33be": "kW", "\u33bf": "MW", "\u33b3": "ms",
}
# Fullwidth ASCII (U+FF01..U+FF5E) maps to ASCII by a fixed offset.
CHARACTER_MAP.update({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)
                      if chr(c) != "\uff0d"})
_CHARACTER_TABLE = str.maketrans(CHARACTER_MAP)

#: A run of superscript digits, with an optional superscript sign.
_SUPER_RUN = re.compile(f"([{_SUPERSCRIPT_SIGNS}]?)([{_SUPERSCRIPTS}]+)")
_AFTER_BASE_TEN = re.compile(r"(?<![0-9.,])10\s?$")


def _rewrite_superscripts(text: str) -> str:
    """A superscript EXPONENT stays an exponent: "10\u207b\u2076" -> "10^-6",
    "10\u00b2" -> "10^2", "s\u207b\u00b9" -> "s^-1". A bare superscript digit
    after anything else is a printing choice for a unit power ("m\u00b2",
    "kg/m\u00b3") and becomes the plain digit, as the unit tables spell it
    ("m2"), which is what NFKC did and what stored text already holds."""
    def repl(m: re.Match) -> str:
        sign = m.group(1).translate(_SUPER_TO_ASCII)
        digits = m.group(2).translate(_SUPER_TO_ASCII)
        if sign or _AFTER_BASE_TEN.search(m.string[:m.start()]):
            return "^" + sign + digits
        return digits
    return _SUPER_RUN.sub(repl, text)


def normalise_text(text: str) -> str:
    """NFC plus `CHARACTER_MAP`, plus superscript exponents kept as exponents.

    Replaces `unicodedata.normalize("NFKC", ...)` in text extraction. NFKC
    folded the superscript in 10\u207b\u2076 into "10-6" (ten minus six), so a
    resistivity or a pressure of 1e-6 was read as an arithmetic expression."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _rewrite_superscripts(text)
    return text.translate(_CHARACTER_TABLE)


# --------------------------------------------------------------------- numbers

_D = "[0-9]"
_E10 = (r"(?:\s?\^\s?(?P<{p}e>[-+" + MINUS_SIGNS + r"]?[0-9]+)"
        r"|(?P<{p}s>[" + _SUPERSCRIPT_SIGNS + r"]?[" + _SUPERSCRIPTS + r"]+))")
_TOKEN = re.compile(
    # 1.5 x 10^-6, 1.5\u00d710\u207b\u2076
    r"(?P<mant>[0-9]+(?:[.,][0-9]+)?)\s?[x\u00d7*\u00b7]\s?10" + _E10.format(p="m")
    # 10^-6 on its own
    + r"|(?<![0-9.,])(?P<ten>10)" + _E10.format(p="t")
    # 1.5e-6, 2E+3: an exponent only with an explicit sign, so a tag such as
    # "12E45" is not read as 1.2e46
    + r"|(?P<sci>[0-9]+(?:\.[0-9]+)?[eE][-+" + MINUS_SIGNS + r"][0-9]+)(?![0-9A-Za-z])"
    # everything else: one token of digits with . or , between groups
    + r"|(?P<plain>[0-9]+(?:[.,][0-9]+)*)"
    # a leading-dot decimal after whitespace, a sign or the start (not a letter:
    # "p.4" is page 4): ".5"
    + r"|(?<![\w.,])(?P<lead>\.[0-9]+)")

_GROUPED = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")
_COMMA_DECIMAL = re.compile(r"[0-9]+,[0-9]+")
_DOT_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")
#: d.ddd with 1-3 leading digits (not 0) and exactly three decimals: the
#: decimal 4.000 or the EU thousands 4,000 - the text alone cannot say.
_EU_THOUSANDS_LOOKALIKE = re.compile(r"[1-9][0-9]{0,2}\.[0-9]{3}")


@dataclass(frozen=True)
class Number:
    """One number found in a text.

    `value` is None for a COMPOUND (a token that is not one number: the clause
    "5.3.2", the list "1,2,3"); its `key` is then its text, never a float.
    `start`/`end` index the text that was searched and INCLUDE a sign
    character. `sign` is "-" (a minus), "+" (unsigned) or "?" (a dash that
    could equally be a range separator - not a minus; `value` is positive).
    `ambiguous` is True for d.ddd, which may be a decimal or EU thousands."""
    value: float | None
    raw: str
    start: int
    end: int
    sign: str = "+"
    ambiguous: bool = False
    #: index of the first digit (`start` is the sign character when there is one)
    digits_at: int = 0

    @property
    def key(self) -> float | str:
        return self.value if self.value is not None else self.raw


def _plain_value(token: str) -> tuple[float | None, bool]:
    if _GROUPED.fullmatch(token):
        return float(token.replace(",", "")), False
    if _COMMA_DECIMAL.fullmatch(token):
        return float(token.replace(",", ".")), False
    if _DOT_DECIMAL.fullmatch(token):
        return float(token), bool(_EU_THOUSANDS_LOOKALIKE.fullmatch(token))
    return None, False


def _exponent(sign_digits: str) -> int:
    return int(sign_digits.translate(_SUPER_TO_ASCII).replace("\u2212", "-"))


def sign_before(text: str, start: int) -> tuple[str, int]:
    """(sign, index the token including its sign starts at) for a number whose
    first digit is at `start`: "-" a minus, "?" a dash that may be a range
    separator, "+" no sign."""
    if start == 0:
        return "+", start
    c = text[start - 1]
    if c == "+":
        return "+", start - 1
    lead = text[start - 2] if start >= 2 else ""
    if c in MINUS_SIGNS:
        # Unambiguous minus; but "29\u2212343" is a subtraction/range.
        if lead and (lead.isdigit() or lead in ")]"):
            return "+", start
        return "-", start - 1
    if c in "-\u2010\u2011":
        if lead == "" or lead in _SIGN_LEAD:
            if lead.isspace() and _prev_nonspace_is_number_end(text, start - 2):
                return "?", start
            return "-", start - 1
        return "+", start
    if c in DASHES:
        if lead == "" or lead in _SIGN_LEAD:
            if lead.isspace() and _prev_nonspace_is_number_end(text, start - 2):
                return "?", start
            return "-", start - 1
        return "+", start
    return "+", start


def _prev_nonspace_is_number_end(text: str, i: int) -> bool:
    while i >= 0 and text[i].isspace():
        i -= 1
    return i >= 0 and (text[i].isdigit() or text[i] == ")")


def find_numbers(text: str) -> list[Number]:
    """Every number in `text`, left to right, with sign and exponent read.

    Does not normalise: indices refer to `text` as given, so callers that
    need offsets (the figure check in `answer`) can use them."""
    out: list[Number] = []
    for m in _TOKEN.finditer(text or ""):
        value: float | None
        ambiguous = False
        if m.group("mant") is not None:
            e = m.group("me") or m.group("ms")
            mant = m.group("mant").replace(",", ".")
            value = float(mant) * 10.0 ** _exponent(e)
        elif m.group("ten") is not None:
            e = m.group("te") or m.group("ts")
            value = 10.0 ** _exponent(e)
        elif m.group("sci") is not None:
            value = float(m.group("sci").replace("\u2212", "-"))
        elif m.group("lead") is not None:
            value, ambiguous = float(m.group("lead")), False
        else:
            value, ambiguous = _plain_value(m.group("plain"))
        sign, begin = sign_before(text, m.start())
        if value is not None and sign == "-":
            value = -value
        out.append(Number(value, m.group(0), begin, m.end(), sign, ambiguous, m.start()))
    return out


def canonical(n: Number) -> str:
    """The text form two spellings of one UNSIGNED number share ("9,0" and
    "9.0" are "9.0"); a compound keeps its own text. The sign is not part of
    it: callers that need the sign read `Number.sign`."""
    return repr(abs(n.value)) if n.value is not None else n.raw


def canonical_token(token: str) -> str:
    """`canonical` for one token already cut out of a text."""
    found = find_numbers(token)
    return canonical(found[0]) if len(found) == 1 else token


def number_keys(text: str) -> set[float | str]:
    """The set of numbers a text states, for "every number in the answer must
    appear in the source" gates. Signed: -5 and 5 are different members. A
    compound token ("5.3.2") is a member as its text."""
    return {n.key for n in find_numbers(text)}


def as_number(text: str | float | int | None) -> float | None:
    """`text` read as exactly ONE number and nothing else, else None. "8,300"
    is 8300, "9,0" is 9.0, "-5" and "\u22125" are -5, "2.5 mm" is None (it is
    a figure with a unit, not a bare number)."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    found = find_numbers(s)
    if len(found) != 1:
        return None
    n = found[0]
    if n.value is None or n.sign == "?" or n.start != 0 or n.end != len(s):
        return None
    return n.value


# ------------------------------------------------------- strict single values

_SPACE_GROUPED = re.compile(r"\d{1,3}(?:[ \u00a0\u202f\u2009]\d{3})+(?:[.,]\d+)?")


def parse_value(value_str: str) -> float | None:
    """Parse a written number. Anything unparseable or ambiguous is None,
    never a guess.

    * Comma decimals ("9,0") are decimals - NORSOK writes them so. A comma
      followed by exactly three digits ("1,200") is a thousands separator.
    * Space may separate thousands ONLY as groups of exactly three digits after
      a first group of 1-3 digits ("1 200", "12 345 678"). "34 3", "5 10" and
      "1 2 3" are two or three numbers, not one: None.
    * d.ddd with a leading integer part of 1-3 digits other than 0 and EXACTLY
      three decimals ("4.000", "1.200", "12.345") is ambiguous between the
      decimal 4.000 and the EU thousands 4,000: None. "0.125" (EU thousands
      never start with 0), "6.89", "3.5" and "1234.567" are unambiguous. The
      comparison then goes to NEEDS_ENGINEER_REVIEW rather than guessing.
    * U+2212 is a minus. An en/em dash directly before the digits is a minus
      only when it begins the value or follows whitespace or a comparator; a
      dash separated from its digits ("- 29"), glued to a letter, or inside a
      range ("29-343") is ambiguous: None.
    """
    s = (value_str or "").strip()
    for c in MINUS_SIGNS:
        s = s.replace(c, "-")
    m = re.fullmatch(r"(?P<cmp>[^\d]*?)\s*(?P<num>[-+]?\d[\d.,\s]*)", s)
    if not m:
        return None
    prefix = s[:m.start("num")]
    stripped = prefix.rstrip()
    negative_dash = False
    if stripped and stripped[-1] in "-" + DASHES:
        if prefix != stripped:
            return None          # "- 29": dash separated from its digits
        before = stripped[:-1]
        if stripped[-1] in DASHES:
            if before and not (before[-1].isspace() or not before[-1].isalnum()):
                return None      # "T\u201329": glued to a letter
            negative_dash = True
        else:
            return None          # "x-29" / "- 29" with an ASCII hyphen: not a sign
    num = m.group("num")
    if re.search(r"\s", num):
        if not _SPACE_GROUPED.fullmatch(num.lstrip("+-")):
            return None
        num = re.sub(r"\s", "", num)
    sign = ""
    if num[:1] in "+-":
        sign, num = num[0], num[1:]
    if negative_dash:
        if sign:
            return None
        sign = "-"
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", num):
        num = num.replace(",", "")
    elif re.fullmatch(r"\d+,\d+", num):
        num = num.replace(",", ".")
    elif re.fullmatch(r"[1-9]\d{0,2}\.\d{3}", num):
        return None
    try:
        return float(sign + num)
    except ValueError:
        return None


# ------------------------------------------------------- a figure in a text

_WS = re.compile(r"\s+")


def fold(text: object) -> str:
    """Case- and whitespace-insensitive form with the minus signs unified:
    what two spellings of the same words are compared in."""
    s = _WS.sub(" ", str(text)).strip().lower()
    return s.translate(_CHARACTER_TABLE) if s else s


def contains_whole(haystack: str, needle: str) -> bool:
    """Whole-word containment on folded text, for NON-numeric values.

    A needle that STARTS with a digit must not start inside a longer number
    (preceded by a digit, a "." or "," after a digit, or a minus sign): "5 mm"
    is not stated by "-5 mm", "2.5 mm" or "15 mm". One that ENDS with a digit
    must not end inside a longer number ("10" in "10.5", "100").

    Words are matched with lookarounds rather than `\\b` because a subject or a
    unit can end in a bracket ("noise level dB(A)")."""
    if not needle:
        return False
    negative_starts = {n.start + 1 for n in find_numbers(haystack)
                       if n.sign == "-" and n.start < n.end}
    word_start, word_end = bool(re.match(r"\w", needle)), bool(re.search(r"\w$", needle))
    digit_start, digit_end = needle[0].isdigit(), needle[-1].isdigit()
    for m in re.finditer(re.escape(needle), haystack):
        s, e = m.start(), m.end()
        before, after = haystack[s - 1:s] if s else "", haystack[e:e + 1]
        starts_inside = (
            (word_start and re.match(r"\w", before) is not None)
            or (digit_start and s in negative_starts)
            or (digit_start and before in (".", ",") and haystack[s - 2:s - 1].isdigit()))
        ends_inside = (
            (word_end and re.match(r"\w", after) is not None)
            or (digit_end and after in (".", ",") and haystack[e + 1:e + 2].isdigit()))
        if not starts_inside and not ends_inside:
            return True
    return False


def value_in_text(value: object, text: object) -> bool:
    """Is the figure `value` stated in `text`?

    A value that is one bare number is compared AS A NUMBER, sign included,
    against every number the text states: 5 is not stated by "-5" or "2.5",
    and 370.0 is stated by "370". Any other value ("10 barg", "316L", "DN50")
    must occur as whole words with the same boundary rules (`contains_whole`).
    Both sides are folded first, so U+2212 and a hyphen-minus are one spelling.
    """
    if value is None or str(value).strip() == "":
        return False
    wanted = as_number(value)
    if wanted is not None:
        return any(n.value == wanted for n in find_numbers(fold(text))
                   if n.value is not None)
    return contains_whole(_strip_thousands(fold(text)), _strip_thousands(fold(value)))


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def _strip_thousands(text: str) -> str:
    """"8,300" -> "8300" so the two printings of one number compare equal."""
    return _THOUSANDS.sub("", text)


def fold_numbers(text: object) -> str:
    """`fold` with thousands separators removed: "8,300" and "8300" are one
    spelling, "-5" and "U+2212 then 5" are one spelling, "5" and "-5" are not."""
    return _strip_thousands(fold(text))
