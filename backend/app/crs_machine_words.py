"""Order 152.2: NO MACHINE WORDS IN THE CONTRACTOR'S COPY.

A comment that reaches the contractor is read by an engineer at another
company. Wording that only makes sense inside this program - a field code
(`max_working_pressure`), a verdict code (`NEEDS_ENGINEER_REVIEW`), the name of
a model or engine, "the synonym table" - tells them nothing and shows a
machine wrote it. The issue gate (`crs_issue.open_items`, which the
issue route runs first) uses this module to refuse such a copy; the fix is to
edit the comment's wording.

GENERAL BY CONSTRUCTION (owner order 143): nothing here names a datasheet, a
field label, an equipment tag or a standard. What counts as a machine word is
a SHAPE (rules 1 and 2 below) or something read from this program's own
settings and constants (rule 3), or one of the few phrases of rule 4, each
true of ANY document:

  1. snake_case identifier (`word_word`, letters first in every part) - no
     sentence of an engineer's wording joins words with underscores.
  2. UPPER_CASE code (`WORD_WORD`) and a camelCase name (`wordWord`, two or
     more lower-case letters each side so units such as kWh, mmHg, mA stay
     clear) and a dotted call (`name.part(`).
  3. The names this program runs: every `*_model` setting's value (and its
     part before ":" - the model family), the engine names of
     `datasheet_ai.ENGINES` (except "off") and the OCR engine's name.
  4. A short phrase list (`PHRASES`): internal wording for how a match was
     made or which part of the program spoke.

ONLY MACHINE-WRITTEN CELLS ARE SCANNED. A row an engineer edited
(`edited` True: the words are theirs) is skipped; an engineer owns what they
type and no word list may veto it. Rows the issue copy would not carry (not
confirmed, rejected, a safety tick, an AI draft) are not scanned either.
Read only; no network; no document text is logged.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .crs_mapping import ROW_KIND_SAFETY_TICK, row_has_no_text

#: Cells of a row that are written by the program for the contractor.
SCANNED_CELLS = ("comment", "page_section", "standard_reference")

_EDGE_L = r"(?<![A-Za-z0-9_])"
_EDGE_R = r"(?![A-Za-z0-9_])"

#: Rules 1 and 2: shapes. Each is a code name, never a sentence.
_SHAPES = (
    re.compile(_EDGE_L + r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+" + _EDGE_R),
    re.compile(_EDGE_L + r"[A-Z][A-Z0-9]*(?:_[A-Z][A-Z0-9]*)+" + _EDGE_R),
    re.compile(_EDGE_L + r"[a-z]{2,}[A-Z][a-z]{2,}[A-Za-z0-9]*" + _EDGE_R),
    re.compile(_EDGE_L + r"[A-Za-z_]\w*\.[A-Za-z_]\w*\("),
)

#: Rule 4. Each phrase is the program's own vocabulary, not a contractor's:
#:  synonym table      the internal lookup that links two field names
#:  containment match  the matcher's method name (the bare word is ordinary
#:                     engineering English, e.g. "secondary containment")
#:  matched by containment   the same, as the comments word it
#:  matcher            the program's pairing step
#:  language model, llm   the AI that read or worded something
#:  embedding          the retrieval vectors
PHRASES = (
    "synonym table",
    "containment match",
    "matched by containment",
    "matcher",
    "language model",
    "llm",
    "embedding",
    "embeddings",
)


def _engine_and_model_names() -> list[str]:
    """Rule 3: read from the program, so a changed model or a new engine is
    covered without an edit here."""
    from . import datasheet_ai, ocr
    from .config import settings

    names: set[str] = set()
    for key, value in settings.model_dump().items():
        if key.endswith("_model") and isinstance(value, str):
            value = value.strip()
            if len(value) >= 4:
                names.add(value)
                family = value.split(":")[0]
                if len(family) >= 4:
                    names.add(family)
    names.update(e for e in datasheet_ai.ENGINES if e != datasheet_ai.OFF)
    engine = str(ocr.ENGINE)
    names.add(engine)
    names.add(re.split(r"[-\d]", engine)[0])
    return sorted((n for n in names if len(n) >= 4), key=len, reverse=True)


@lru_cache(maxsize=16)
def _named(words: tuple[str, ...]) -> re.Pattern:
    return re.compile(
        _EDGE_L + "(?:" + "|".join(re.escape(w) for w in words) + ")" + _EDGE_R,
        re.IGNORECASE,
    )


def find_machine_words(text: str | None) -> list[str]:
    """The machine words in one text, as written, each once, in order of
    appearance. [] for a text with none (and for no text)."""
    text = str(text or "")
    if not text.strip():
        return []
    found: list[tuple[int, str]] = []
    patterns = [
        *_SHAPES,
        _named(PHRASES),
        _named(tuple(_engine_and_model_names())),
    ]
    for pattern in patterns:
        found.extend((m.start(), m.group(0)) for m in pattern.finditer(text))
    found.sort()
    return list(dict.fromkeys(word for _at, word in found))


def _carried_by_issue_copy(row: dict) -> bool:
    """The rows `crs_export.build_crs_view` puts on the issue copy."""
    return (
        row.get("engineer_confirmed") is True
        and not row.get("engineer_rejected")
        and row.get("row_kind") != ROW_KIND_SAFETY_TICK
        and not str(row.get("ai_review_comment") or "").strip()
        and not row_has_no_text(row)
    )


def scan_issue_rows(rows: list[dict]) -> list[dict]:
    """[{comment, cell, words}] for every machine-written cell of the issue
    copy that holds a machine word. `comment` is the number the contractor
    sees in Item No: the permanent CRS number, else the position on the issue
    copy (counted as `build_crs_view` counts it). Rows an engineer edited are
    skipped - their words are theirs."""
    hits: list[dict] = []
    position = 0
    for row in rows:
        if not _carried_by_issue_copy(row):
            continue
        position += 1
        if row.get("edited") is True:
            continue
        label = str(row.get("crs_ref") or position)
        for cell in SCANNED_CELLS:
            words = find_machine_words(row.get(cell))
            if words:
                hits.append({"comment": label, "cell": cell, "words": words})
    return hits


def blocker(hits: list[dict]) -> str | None:
    """The gate's sentence for `scan_issue_rows`' result, or None. Names the
    comments and the words, and the action that clears it."""
    if not hits:
        return None
    numbers = list(dict.fromkeys(h["comment"] for h in hits))
    words = list(dict.fromkeys(w for h in hits for w in h["words"]))
    return (
        f"{len(numbers)} comment(s) on the sheet contain wording only the "
        f"program uses ({', '.join(numbers[:10])}"
        f"{', ...' if len(numbers) > 10 else ''}; for example "
        f"{', '.join(repr(w) for w in words[:5])}) - edit the wording of "
        "each in plain words before issuing"
    )
