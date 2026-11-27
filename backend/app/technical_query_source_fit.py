"""Does a cited source SAY what the reply's sentence claims? A MARK for the engineer, never a stop (owner, 27 Nov 2026 12:32 PKT: "some
answers look wrong"; builder H's table of the 34 live queries: 22 of 33 replies cite a real source that does not support the claim).

Measured before it was built (builder A, 27 Nov 2026, on a clone of the live data against H's labels, local AI only, nothing sent):
word overlap alone caught 11 of 22 with 3 false alarms on 11 clean replies; the local AI asked "does the source state this?" 16 of 22 with
6 false alarms; the AI made to copy the supporting words, checked by code, 18 of 22 with 8 false alarms. This module (both, the AI asked
only below the overlap floor), measured at three floors: 0.34 caught 8 of 22 with 1 false alarm, 0.5 11 with 2, 0.67 15 with 3 (chosen:
a mark only asks for a look, so a missed misfit costs more than one extra look). Not enough to stop a reply.

How: for each sentence that cites [Sn] (a "not found" sentence aside), the share of its key words found in the cited source text. Only
below OVERLAP_FLOOR is the local AI asked to copy, word for word, the source words that state the claim; when it copies none, or words
that are not in the source (the answer lane's own claim check), the sentence's sources are marked. The AI on this computer only, never
Claude; it reads only what the draft was already given. A judge that did not answer is said, never taken as a pass.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

#: Below this share of a sentence's key words in its cited source, the AI is asked to show the supporting words (measured, see above).
OVERLAP_FLOOR = 0.67
#: Sentences with fewer key words than this are not judged (an opening line, a bare reference).
MIN_TERMS = 3
#: At most this many sentences of one reply are judged (each is one local AI call).
MAX_JUDGED = 8

_SYSTEM = (
    "You check one sentence of a reply against the SOURCE it cites. Copy, word for word, the shortest passage of the SOURCE "
    "that states what the sentence claims. If the SOURCE does not state it, write NONE. Write nothing else."
)
#: Words every reply uses: they say nothing about whether a source fits.
_GENERIC = frozenset(
    """company contractor contractors request requests requested clause clauses confirm confirms confirmed item items document
    documents searched found reply query accordance shall provide provided required requires require project specification
    specifications standard standards section sections page pages note notes regarding following respect therefore however also may
    must will would should can could per within under above below stated states state statement information details detail technical
    review reviewed reviews approval approve approved submission submit submitted""".split()
)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-/.]{3,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TAG = re.compile(r"\[S(\d+)[^\]]*\]")
_NOT_FOUND = re.compile(r"not found in the documents|do(?:es)? not (?:contain|state|specify|mention)", re.IGNORECASE)

MARK = "The AI could not show where {tags} says this. Check it before you approve."
NOT_CHECKED = "The check that each source says what its sentence claims did not run: the AI on this computer did not answer."


def _terms(text: str) -> list[str]:
    from .lexical import STOPWORDS

    out = []
    for word in _WORD.findall(_TAG.sub(" ", text)):
        word = word.rstrip(".").lower()
        if len(word) >= 4 and word not in STOPWORDS and word not in _GENERIC:
            out.append(word)
    return list(dict.fromkeys(out))


def overlap(claim: str, source: str) -> float:
    """The share of the claim's key words found in the source (by their first six letters: "requirement" meets "required")."""
    terms = _terms(claim)
    if not terms:
        return 1.0
    seen = {w.lower()[:6] for w in _WORD.findall(source or "")}
    return sum(1 for t in terms if t[:6] in seen) / len(terms)


def _shown(claim: str, source: str) -> bool | None:
    """The local AI copies the source words that state the claim; True when it did and they are in the source, None when it did not
    answer. Never Claude."""
    from . import chat_model
    from .model_evidence import claim_quote_verified

    prompt = f"SOURCE:\n{source[:3500]}\n\nSENTENCE:\n{claim}\n\nThe SOURCE words that state it (or NONE):"
    try:
        out = chat_model.generate(_SYSTEM, prompt, temperature=0.0, preference=chat_model.LOCAL, timeout=60)
    except Exception as exc:  # noqa: BLE001 - logged by its class only; the reply then says the check did not run
        log.info("query source check: the local AI did not answer (%s)", type(exc).__name__)
        return None
    copied = (out.get("response") or "").strip().strip('"“”').strip()
    if not copied or copied.upper().startswith("NONE"):
        return False
    return claim_quote_verified(copied, source)


def marks(answer: str, sources: dict[int, str]) -> list[str]:
    """The marks beside a reply: its sources that the AI could not show saying their sentence's claim, or that the check did not run."""
    weak: list[int] = []
    judged = 0
    silent = False
    for line in (answer or "").split("\n"):
        for sentence in _SENTENCE.split(line):
            tags = [int(n) for n in _TAG.findall(sentence)]
            if not tags or _NOT_FOUND.search(sentence):
                continue
            claim = _TAG.sub(" ", sentence).replace("*", "").strip()
            if len(_terms(claim)) < MIN_TERMS:
                continue
            source = "\n\n".join(sources.get(n, "") for n in tags)
            if overlap(claim, source) >= OVERLAP_FLOOR or judged >= MAX_JUDGED:
                continue
            judged += 1
            shown = _shown(claim, source)
            if shown is None:
                silent = True
            elif not shown:
                weak += [n for n in tags if n not in weak]
    out = []
    if weak:
        out.append(MARK.format(tags=" and ".join(f"[S{n}]" for n in weak)))
    if silent:
        out.append(NOT_CHECKED)
    return out
