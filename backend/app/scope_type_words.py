"""Words of a division's construction against the sheet's own type (order 210, FIX 2).

A standard's division limited to "centrifugal pumps" applies to a sheet whose
equipment type or title already says "Centrifugal Pump". The model was asked
whether the equipment is of that construction and answered "unsure" without
quoting the type line (21 of 35 replies on the invented set), which held the
whole standard. `construction_in_type` is the code-side check of the words: it
is a DRAFT, OFF until the owner says yes (`scope_type_words_rule_enabled`), and
it only lets a clause be checked; it never passes one. Nothing names a
standard, a type or a layout.

The module also holds what a datasheet STATES about its construction
(`stated_construction`, `datasheet_heading`, `names`, `named_anywhere`), moved
from `ai_applicability` to keep that module under its size limit.
"""

from __future__ import annotations

import re

from . import subject_scope

#: Function words that carry no construction ("pumps FOR the oil service").
FUNCTION_WORDS = frozenset(
    {"a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with", "by"}
)
#: The note on a requirement of a standard's title block whose scope was not confirmed.
SCOPE_NOT_CONFIRMED = (
    "the standard's own scope sentence could not be tied to this equipment "
    "(the model was unsure or did not answer); the clause is compared as usual"
)


def words(text: object, least: int = 4) -> set[str]:
    """The words of `text` of `least` letters or more, a plural "s" dropped."""
    return {
        w[:-1] if w.endswith("s") else w
        for w in re.findall(rf"[a-z]{{{least},}}", subject_scope._fold(text))
    } - {""}


def construction_in_type(construction: str, classification: dict | None) -> bool:
    """Is EVERY word of the division's construction ("centrifugal pumps")
    already in the sheet's equipment type or title ("Centrifugal Pump")? Every
    word counts, a short one too (a plural "s" aside; only function words are
    left out), so "magnetic-drive pumps" does not match "Centrifugal Pump"."""
    classification = classification or {}
    named = f"{classification.get('equipment_type') or ''} {classification.get('title') or ''}"
    need = words(construction, least=1) - FUNCTION_WORDS
    return bool(need) and need <= words(named, least=1)


# ----------------------------- what the datasheet states about its construction
#: The words of the stated lines the model reads (the task reads ~300).
STATED_WORDS = 220


def names(value: object, construction: str) -> bool:
    """Does `value` name any word of `construction` (four letters or more;
    a plural "s" does not count, so "vessel" names "vessels")?"""
    return bool(words(value) & words(construction))


def named_anywhere(
    construction: str, classification: dict | None, facts: list[dict]
) -> bool:
    """Does ANY stated value of the datasheet (every fact, uncut), or its
    classification, name the construction? A main part or only a seal: not
    for code to say, so such a division is never excluded."""
    values = [
        *(classification or {}).values(),
        *datasheet_heading(classification),
        *(
            f.get("field_value") or f.get("raw_value")
            for f in facts
            if not f.get("is_blank")
        ),
    ]
    return any(names(v, construction) for v in values if isinstance(v, str) and v)


_HEADING_LINES, _HEADING_WORDS = 2, 8


def _lead(line: str) -> str:
    """A short line whole; a long line only up to its first field label
    ("Doc No.:"), since a form's heading and fields often share one line. A
    long line with no label is prose, not a heading."""
    words = line.split()
    if len(words) <= _HEADING_WORDS:
        return " ".join(words)
    labels = [n for n, word in enumerate(words) if word.endswith(":")]
    head = words[: labels[0]] if labels else []
    return " ".join(head) if len(head) <= _HEADING_WORDS else ""


def datasheet_heading(classification: dict | None) -> list[str]:
    """The first short lines of the datasheet's first page: a sheet says what
    it is in its heading even when no equipment type or title was stored. The
    page text is read (it keeps its line breaks); a document with none falls
    back to its first chunk, which may be ONE line. Its own words, no word
    list: `names` decides whether a line names the construction."""
    from .db import connect

    doc = (classification or {}).get("document_id")
    if not doc:
        return []
    conn = connect()
    sql = "SELECT text FROM pages WHERE document_id = ? AND page_no = 1"
    row = conn.execute(sql, (doc,)).fetchone()
    if not (row and (row["text"] or "").strip()):
        sql = "SELECT text FROM chunks WHERE document_id = ? AND page_start = 1 ORDER BY ordinal LIMIT 1"
        row = conn.execute(sql, (doc,)).fetchone()
    lines = (_lead(ln) for ln in (row["text"] if row else "").splitlines())
    return [ln for ln in lines if ln][:_HEADING_LINES]


def stated_construction(classification: dict | None, facts: list[dict]) -> list[str]:
    """What the datasheet states about what its equipment is and is made of:
    the classification's equipment type and title, its first-page heading, then
    the facts the role tests read as a material or an equipment class
    (`conditions`), one line per distinct value, within `STATED_WORDS`."""
    from . import conditions

    classification = classification or {}
    lines = [
        f"{label}: {classification[key]}"
        for key, label in (("equipment_type", "equipment type"), ("title", "title"))
        if classification.get(key)
    ]
    lines += [f"heading: {head}" for head in datasheet_heading(classification)]
    seen: set[str] = set()
    for shape in (conditions.SHAPE_MATERIAL, conditions.SHAPE_CLASS):
        for fact in conditions._candidate_facts(shape, facts):
            value = str(fact.get("field_value") or "").strip()
            if (
                fact.get("is_blank")
                or conditions._is_empty(value)
                or value.casefold() in seen
            ):
                continue
            seen.add(value.casefold())
            lines.append(
                f"{fact.get('field_label') or fact.get('field_name')}: {value}"
            )
    out: list[str] = []
    words = 0
    for line in lines:
        words += len(line.split())
        if words > STATED_WORDS:
            break
        out.append(" ".join(line.split()))
    return out
