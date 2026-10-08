"""Front matter: passages that describe a document rather than answer from it.

A foreword, a revision history or a table of contents shares a standard's
vocabulary - "Revision 3 corrected the bolting material for flanged joints"
names everything a bolting question asks - and states none of its
requirements. Quoted as the answer, it was shown with a green "1 of 1 point
found on the page" (#610), which was true of the words and false of the
answer.

Generic by construction: which headings are front matter lives in
`reference/front_matter.json`, not here, and nothing names a document. A
question that asks about the front matter itself ("what changed in revision
3?") is left exactly as it was.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

VOCABULARY_PATH = Path(__file__).parent / "reference" / "front_matter.json"

#: How far into a passage with no section label a front-matter heading is
#: looked for. A document's first chunk is its title line and then the heading.
TEXT_HEADING_WINDOW = 160

#: A leading clause number on a heading ("0.1 Foreword", "A. History").
_NUMBERING = re.compile(r"^\s*(?:[A-Z]|\d+(?:\.\d+)*)[.)]?\s+")


@lru_cache(maxsize=1)
def vocabulary() -> dict:
    """The editable vocabulary, read once. See the file's _comment."""
    data = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
    return {
        "headings": frozenset(h.strip().lower() for h in data.get("headings") or []),
        "text_headings": tuple(h for h in data.get("text_headings") or [] if h.strip()),
        "asked_about_words": frozenset(
            w.strip().lower() for w in data.get("asked_about_words") or []),
    }


def reload_vocabulary() -> None:
    """Forget the cached vocabulary (a test, or an edit in a running process)."""
    vocabulary.cache_clear()
    _text_pattern.cache_clear()


@lru_cache(maxsize=1)
def _text_pattern() -> re.Pattern | None:
    headings = vocabulary()["text_headings"]
    if not headings:
        return None
    alternatives = "|".join(re.escape(h) for h in sorted(headings, key=len, reverse=True))
    # case-SENSITIVE on purpose: a heading is written with a capital
    return re.compile(r"(?<![\w-])(?:" + alternatives + r")(?![\w-])")


def _heading_is_front_matter(heading: str) -> bool:
    name = _NUMBERING.sub("", heading or "").strip().rstrip(":.").lower()
    return bool(name) and name in vocabulary()["headings"]


def is_front_matter(passage: dict) -> bool:
    """Does this hit or passage sit under a front-matter heading?

    Its section label, or any heading in its heading chain, is one; or, when
    it has no section label at all, a front-matter heading opens its text.
    """
    section = (passage.get("section") or "").strip()
    chain = [part for part in re.split(r"\s*>\s*", passage.get("context") or "") if part]
    if any(_heading_is_front_matter(h) for h in [section, *chain] if h):
        return True
    if section or chain:
        return False
    pattern = _text_pattern()
    head = (passage.get("text") or "")[:TEXT_HEADING_WINDOW]
    return bool(pattern and pattern.search(head))


def asked_about(question: str) -> bool:
    """Does the question ask about the front matter itself?"""
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", question or "")}
    return bool(words & vocabulary()["asked_about_words"])


def demoted(passage: dict, question: str) -> bool:
    """Front matter the question did not ask about: ranked below the clauses
    when answering, and never counted as a point that answers the question."""
    return is_front_matter(passage) and not asked_about(question)


def rank_down(hits: list[dict], question: str) -> list[dict]:
    """Retrieval's order, with demoted front matter moved after every other
    hit. Nothing is removed, and the order within each group is kept."""
    if asked_about(question):
        return list(hits)
    keep = [h for h in hits if not is_front_matter(h)]
    if len(keep) == len(hits):
        return list(hits)
    return keep + [h for h in hits if is_front_matter(h)]
