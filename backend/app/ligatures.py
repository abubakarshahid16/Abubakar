"""Repairing ligatures that failed to extract.

Some PDFs encode `ti`, `fi`, `ff` and `fl` as single glyphs whose embedded
font mapping is wrong, so extraction yields the wrong character entirely:

    Introduction  ->  Introduc,on      (ti -> ,)
    Section       ->  Sec3on           (ti -> 3)
    Definitions   ->  DeEinitions      (fi -> Ei)

No retrieval change can fix this. "introduction" cannot match "Introduc,on"
because the text is not there - it is a COVERAGE limit, not a ranking one.

MEASURED ON book4 (1,400 pages, 2,030,224 characters) before writing any of
this:

    pattern     pages   % pages   hits     clean pages   coexist
    ti -> ,       177     12.6%     233          1196        171
    ti -> 3        93      6.6%     119          1196         91
    fi -> Ei       89      6.4%     133           613         35
    ff -> ?        37      2.6%      50             0          0

    pages with at least one corruption: 292 (20.9%)
    corrupted tokens: 535  =  0.68% of words on affected pages
                             0.18% of the whole document

Widespread but sparse - and the impact is far larger than 0.18% suggests,
because the damage lands on STRUCTURAL words. The commonest corruptions are
"Sec3on" (91), "Introduc,on" (83) and "Ques,on" (51): exactly the words a
"what is section 3.4 about" question matches on.

WHY A REPAIR IS DEFENSIBLE HERE. The corrupt and clean forms coexist in the
same document - 177 pages carry "X,on" while 1,196 carry a clean "Xtion" - so
the repair can be validated by applying it to the clean pages and requiring
that it changes NOTHING. That is the difference between a repair and a guess,
and it is the test this module exists to pass.

WHAT IS NOT REPAIRED. `ff -> ?` has 50 hits and no clean reference measured in
this document, so there is nothing to validate a rule against. It is recorded
as a limitation rather than guessed at.
"""

from __future__ import annotations

import re

#: `ti` mis-mapped to `,` or `3`, at a word ending in -tion/-tions.
#:
#: Anchored tightly on purpose. The pattern requires letters immediately before
#: the substituted character with NO space, because clean prose writes "value,
#: on which" with a space and this document writes "Introduc,on" without one.
#: The word must also END in "on" or "ons", which is what makes it a -tion
#: ending rather than an arbitrary comma.
_TI_SUBSTITUTED = re.compile(r"\b([A-Za-z]{2,})[,3](ons?)\b")

#: `fi` mis-mapped to `Ei` INSIDE a word - "DeEinitions", "speciEied".
#:
#: Requires a lowercase letter before the E, so a word legitimately starting
#: with "Ei" is untouched: "Einstein" has no preceding letter and "Eigen" is
#: capitalised at a word start. The tail must be lowercase letters, so an
#: acronym containing E followed by I is not rewritten.
_FI_SUBSTITUTED = re.compile(r"\b([a-z]+)Ei([a-z]{2,})\b|\b([A-Z][a-z]*)Ei([a-z]{2,})\b")


def repair(text: str) -> str:
    """Undo the substitutions above. Returns the text unchanged if none apply.

    Deliberately narrow. Every rule here is anchored on a shape that cannot
    occur in correctly extracted prose, and `validate` proves that against
    over a thousand clean pages of the same document.
    """
    if not text:
        return text

    repaired = _TI_SUBSTITUTED.sub(lambda m: f"{m.group(1)}ti{m.group(2)}", text)

    def fi(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            return f"{m.group(1)}fi{m.group(2)}"
        return f"{m.group(3)}fi{m.group(4)}"

    return _FI_SUBSTITUTED.sub(fi, repaired)


def count_corruptions(text: str) -> int:
    """How many substituted tokens this text carries."""
    return len(_TI_SUBSTITUTED.findall(text)) + len(_FI_SUBSTITUTED.findall(text))


def validate(clean_texts: list[str]) -> list[tuple[str, str]]:
    """Apply the repair to text known to be CLEAN and report any change.

    An empty result is the safety property: the repair cannot alter correctly
    extracted text. This is the guard that makes the difference between a
    targeted repair and a rewrite of the corpus on a hunch.
    """
    changed: list[tuple[str, str]] = []
    for text in clean_texts:
        after = repair(text)
        if after != text:
            for before_line, after_line in zip(text.splitlines(), after.splitlines()):
                if before_line != after_line:
                    changed.append((before_line, after_line))
    return changed
