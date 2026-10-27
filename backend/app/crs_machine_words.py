"""Order 152.2: NO MACHINE WORDS IN THE CONTRACTOR'S COPY.

A comment that reaches the contractor is read by an engineer at another
company. Wording that only makes sense inside this program - a field code, a
stored document id, the name of a model, "the synonym table" - tells them
nothing and shows a machine wrote it. The issue gate (`crs_issue.open_items`,
which the issue route runs first) uses this module to refuse such a copy.

GENERAL BY CONSTRUCTION (owner order 143): nothing here names a datasheet, a
field label, an equipment tag or a standard. NO SHAPE DETECTORS: a pattern
such as "word_word" or "camelCase" also matches text quoted from a contractor's
own document (tags, standard numbers, product names), so a word counts only if
it is one of the program's own names:

  1. field codes: the keys of the checklist reference data
     (`datasheet_checks.load_rules()["roles"]`) that contain "_", whole token,
     case-sensitive. Plain words never match.
  2. a stored document id: "doc_" + 12 hex digits, whatever the first digit
     (`upload.py`: f"doc_{sha256[:12]}").
  3. model ids as written in the `*_model` settings (4+ characters), and the
     names of the local engines (`datasheet_ai.ENGINES` minus "off" and the
     hosted one, the OCR engine's name).
  4. a short phrase list (`PHRASES`).

ONLY MACHINE-WRITTEN TEXT IS SCANNED. The COMMENT cell of a row an engineer
worded is skipped: edited rows, an engineer's chat comment, an AI/web item
the engineer re-worded, and a carried-forward row (a stored issued snapshot).
Page/section and standard reference are program-written on every row and are
always scanned. Rows the issue copy would not carry are not scanned.
Read only; no network; no document text is logged.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .crs_mapping import (
    ROW_KIND_CARRIED_FORWARD,
    ROW_KIND_ENGINEER_COMMENT,
    ROW_KIND_SAFETY_TICK,
    row_has_no_text,
)

COMMENT, PAGE_SECTION, STANDARD_REFERENCE = (
    "comment",
    "page_section",
    "standard_reference",
)
CELLS = (COMMENT, PAGE_SECTION, STANDARD_REFERENCE)
CELL_NAMES = {
    COMMENT: "Comment",
    PAGE_SECTION: "Page and section",
    STANDARD_REFERENCE: "Standard reference",
}

_EDGE_L = r"(?<![A-Za-z0-9_])"
_EDGE_R = r"(?![A-Za-z0-9_])"

#: The stored id of a document (`upload.py`: f"doc_{sha256[:12]}").
DOC_ID = re.compile(r"\bdoc_[0-9a-f]{12}\b")
#: The program's id for a kind B check ("Datasheet check PSV-14") and the engine sentence of an
#: AI draft ("Written by ollama:hf.co/..."): internal names, whatever the check or the model.
DATASHEET_CHECK_ID = re.compile(r"\bDatasheet check [A-Z]+-[A-Z0-9]+\b")
WRITTEN_BY_ENGINE = re.compile(r"\bWritten by \w+:")

#: Internal wording, each true of any document:
#:  synonym table / containment match / matched by containment - how the
#:      program linked two field names (the bare word "containment" is
#:      ordinary engineering English, so it is not listed)
#:  language model / llm - the AI that read or worded something
#:  engineer to check / this system - the program talking to the engineer
#:      ("Engineer to check whether ...: no field this system read ...");
#:      such a row, once ticked, must be reworded before it can be issued
#:  no field read from / validation state / page reader / automatic result /
#:      engineer to tick / this engine - the program's own account of how it read or decided
#:      (K7/K8, order 224): the engineer's cell to read, not the contractor's
#:  this engine can evaluate / drafts about this field differ / blanks, one answer / places,
#:      one answer / model-assigned field name - the same, found on a real relief-valve run (order 228.3)
PHRASES = (
    "synonym table",
    "containment match",
    "matched by containment",
    "language model",
    "llm",
    "engineer to check",
    "this system read",
    "no field read from",
    "read with validation state",
    "by the page reader",
    "automatic result",
    "engineer to tick",
    "this engine reads",
    "this engine cannot",
    "this engine can evaluate",
    "drafts about this field differ",
    "blanks, one answer",
    "places, one answer",
    "model-assigned field name",
)


class Names:
    """The program's own names, read once per scan."""

    def __init__(self) -> None:
        self.cased = _named(tuple(_field_codes()), 0)
        self.phrases = _named(
            tuple(PHRASES) + tuple(_model_and_engine_names()), re.IGNORECASE
        )


def _field_codes() -> list[str]:
    from . import datasheet_checks

    return sorted(k for k in datasheet_checks.load_rules()["roles"] if "_" in k)


def _model_and_engine_names() -> list[str]:
    from . import datasheet_ai, ocr
    from .config import settings

    names = {
        value.strip()
        for key, value in settings.model_dump().items()
        if key.endswith("_model") and isinstance(value, str) and len(value.strip()) >= 4
    }
    names.update(
        e
        for e in datasheet_ai.ENGINES
        if e not in (datasheet_ai.OFF, datasheet_ai.CLAUDE)
    )
    engine = str(ocr.ENGINE)
    names.update({engine, re.split(r"[-\d]", engine)[0]})
    return sorted((n for n in names if len(n) >= 4), key=len, reverse=True)


@lru_cache(maxsize=16)
def _named(words: tuple[str, ...], flags: int) -> re.Pattern:
    body = "|".join(re.escape(w) for w in words) or r"(?!)"
    return re.compile(_EDGE_L + "(?:" + body + ")" + _EDGE_R, flags)


def find_machine_words(text: str | None, names: Names | None = None) -> list[str]:
    """The machine words in one text, as written, each once, in order of
    appearance. [] for a text with none (and for no text)."""
    text = str(text or "")
    if not text.strip():
        return []
    names = names or Names()
    found: list[tuple[int, str]] = []
    for pattern in (
        names.cased,
        names.phrases,
        DOC_ID,
        DATASHEET_CHECK_ID,
        WRITTEN_BY_ENGINE,
    ):
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


def _comment_is_engineers(row: dict) -> bool:
    return (
        row.get("edited") is True
        or row.get("engineer_worded") is True
        or row.get("row_kind") in (ROW_KIND_ENGINEER_COMMENT, ROW_KIND_CARRIED_FORWARD)
    )


def scan_issue_rows(rows: list[dict]) -> list[dict]:
    """[{comment, cell, words}] for every machine-written cell of the issue
    copy that holds a machine word. `comment` is the number the contractor
    sees in Item No: the permanent CRS number, else the position on the issue
    copy (counted as `build_crs_view` counts it)."""
    names = Names()
    hits: list[dict] = []
    position = 0
    for row in rows:
        if not _carried_by_issue_copy(row):
            continue
        position += 1
        label = str(row.get("crs_ref") or position)
        for cell in CELLS:
            if cell == COMMENT and _comment_is_engineers(row):
                continue
            words = find_machine_words(row.get(cell), names)
            if words:
                hits.append({"comment": label, "cell": cell, "words": words})
    return hits


def _list(items: list[str], limit: int = 10) -> str:
    return ", ".join(items[:limit]) + (", ..." if len(items) > limit else "")


def blockers(hits: list[dict]) -> list[str]:
    """The gate's sentences for `scan_issue_rows`' result: one per kind of
    problem, each naming the comment numbers, the cell and the words, and the
    action that clears it."""
    kinds = {
        "comment": [],
        "std_id": [],
        "cell": [],
    }
    for hit in hits:
        if hit["cell"] == COMMENT:
            kinds["comment"].append(hit)
        elif hit["cell"] == STANDARD_REFERENCE and any(
            DOC_ID.fullmatch(w) for w in hit["words"]
        ):
            kinds["std_id"].append(hit)
        else:
            kinds["cell"].append(hit)

    def parts(group: list[dict]) -> tuple[str, str]:
        numbers = list(dict.fromkeys(h["comment"] for h in group))
        words = list(dict.fromkeys(w for h in group for w in h["words"]))
        return _list(numbers), _list([repr(w) for w in words], 5)

    out: list[str] = []
    if kinds["comment"]:
        numbers, words = parts(kinds["comment"])
        out.append(
            f"{CELL_NAMES[COMMENT]} of comment(s) {numbers} holds wording only the "
            f"program uses ({words}) - edit its wording in plain words"
        )
    if kinds["std_id"]:
        numbers, words = parts(kinds["std_id"])
        out.append(
            f"{CELL_NAMES[STANDARD_REFERENCE]} of comment(s) {numbers} shows a stored "
            f"id ({words}) because the standard has no readable name on record - "
            "name that standard's document in the library"
        )
    if kinds["cell"]:
        numbers, words = parts(kinds["cell"])
        cells = " / ".join(dict.fromkeys(CELL_NAMES[h["cell"]] for h in kinds["cell"]))
        out.append(
            f"{cells} of comment(s) {numbers} holds wording only the program uses "
            f"({words}) - it is written by the program, not typed, so ask the "
            "engineer to correct the item at its source"
        )
    return out
