"""Word folding: how a reader reads a WORD, whatever tricks the spelling plays. Lane 6 (verdict-word and number-word filters).

Not a number reader (`numparse` is the only one): it never produces a value, it only turns styled, accented, circled,
parenthesised, squared, regional-indicator, Cherokee, Cyrillic, Greek and Armenian look-alike letters into plain Latin
letters, and drops marks, format and invisible characters, so "c o m p l i e s", "compl\u00edes", "fa\u00a8ils" and
"\u249e\u24aa..." are read as the words they spell. Pure functions; no model, no database, nothing from the app.
"""

from __future__ import annotations

import re
import unicodedata

# Letters that look like Latin ones, by code point: Cyrillic, Greek, Armenian, Cherokee, small capitals.
_CODES = "0430 0441 0435 043E 0440 0445 0443 0456 0458 0455 043A 043C 0442 043D 0432 0501 04CF 03B1 03BF 03B5 03BD 03B9 03C1 03C4 03BA 03BC 03C7 03C5 03B2 03B7 03C9 0578 057D 0585 0581 0570 0563 0566 1D00 0299 1D04 1D05 1D07 A730 0262 029C 026A 1D0A 1D0B 029F 1D0D 0274 1D0F 1D18 0280 A731 1D1B 1D1C 1D20 1D21 028F 1D22 A7AF 13AA 13F4 13DF 13A0 13AC 13C0 13BB 13AB 13E6 13DE 13B7 13E2 13C3 13A1 13DA 13A2 13D9 13B3 13C6"
_LETTERS = (
    "aceopxyijskmthbdlaoeviptkmxubnwnuoghqqabcdefghijklmnoprstuvwyzqabcdeghjklmpzrstvwi"
)
LOOKALIKE = {chr(int(h, 16)): v for h, v in zip(_CODES.split(), _LETTERS, strict=True)}
# regional indicators, squared and negative circled/squared capitals: A-Z in runs of 26
LOOKALIKE |= {
    chr(b + k): chr(97 + k)
    for b in (0x1F1E6, 0x1F130, 0x1F150, 0x1F170)
    for k in range(26)
}
_DROPPED = ("Cf", "Mn", "Me", "Mc", "Cc")
_INVISIBLE = {chr(c) for c in (0x115F, 0x1160, 0x3164, 0xFFA0, 0x180E, 0x2800)}


def fold_compat(text: object, *, lower: bool = True, decompose: bool = True) -> str:
    """Plain Latin letters for `text`: NFKD (NFKC when `decompose` is False) one character at a time, so only the space NFKD
    itself makes for a spacing accent is dropped, never a space the text had; marks, format and invisible characters are
    dropped; "(c)(o)" runs are joined; look-alikes are mapped; lower case unless `lower` is False."""
    cat = unicodedata.category
    out: list[str] = []
    for ch in str(text or ""):
        d = (
            unicodedata.normalize("NFKD", ch)
            if decompose
            else unicodedata.normalize("NFKC", ch)
        )
        if d[:1] == " " and d[1:] and {cat(x) for x in d[1:]} == {"Mn"}:
            d = d[1:]  # that space is NFKD's, not the text's
        out.extend(
            c
            for c in d
            if c in "\t\n " or (cat(c) not in _DROPPED and c not in _INVISIBLE)
        )
    plain = "".join(out)
    table = str.maketrans(LOOKALIKE)
    plain = plain.translate(
        table
    )  # before lower(): lower() turns a Cherokee capital into a letter this table lacks
    plain = (plain.lower() if lower else plain).translate(table)
    return re.sub(r"\(([A-Za-z])\)", r"\1", plain)
