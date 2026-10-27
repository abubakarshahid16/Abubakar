"""Is a division's "limited" scope reading a real sentence? (order 242.2)

The standard-scope step asks a model for the sentence of a Part that limits it
to one construction, and code checks the sentence is in the standard's text.
That check passes a garbled table fragment just as well ("UHA SA-480 Pipe
SA-333", "Subpart 2 do not contain these properties ..."): on a vessel datasheet 804
requirements were moved out of the listed findings on conditions like these.
A scope condition must be one real sentence, so a reading whose quote is not
one is REFUSED: the Part is kept, compared as before, with the "scope not
confirmed" note, and counted. The test is general (shape of the text, no
standard's words) and errs to the safe side: an oddly punctuated real sentence
is refused too, and its Part is then compared, not held.
Pure functions over two strings.
"""

from __future__ import annotations

import re

MIN_WORDS = 6
MIN_LETTER_SHARE = 0.7
MAX_CODE_TOKEN_SHARE = 0.34
_STOPS = (".", ";", "!", "?")
_WORD = re.compile(r"[^\W\d_]{2,}")


def _code_share(text: str) -> float:
    tokens = text.split()
    if not tokens:
        return 1.0
    coded = sum(
        1 for t in tokens if any(ch.isdigit() for ch in t) or re.search(r"\w[-/]\w", t)
    )
    return coded / len(tokens)


def problems(scope: dict) -> list[str]:
    """Why a reading's quote or construction is not a real sentence; [] when it is.
    Only a "limited: yes" reading is looked at."""
    if scope.get("limited") != "yes":
        return []
    quote = " ".join(str(scope.get("quote") or "").split())
    construction = " ".join(str(scope.get("construction") or "").split())
    found = []
    if not quote or not quote[0].isalpha():
        found.append("the quote does not start like a sentence")
    if not quote.endswith(_STOPS) or "..." in quote or "…" in quote:
        found.append("the quote is cut off, not a whole sentence")
    if len(_WORD.findall(quote)) < MIN_WORDS:
        found.append("the quote is too short to be a sentence")
    letters = sum(ch.isalpha() for ch in quote)
    if quote and letters / max(1, len(quote.replace(" ", ""))) < MIN_LETTER_SHARE:
        found.append("the quote is mostly figures and symbols")
    if _code_share(quote) > MAX_CODE_TOKEN_SHARE:
        found.append("the quote is a run of codes, not a sentence")
    if (
        not any(len(w) >= 4 for w in _WORD.findall(construction))
        or _code_share(construction) > 0.5
    ):
        found.append("the construction is not named in words")
    return found
