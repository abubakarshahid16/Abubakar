"""The paper's NAME in every review and CRS sentence, and the sentence that says what was NOT checked (K2, order 13).

ONE home. A sentence of a review or a CRS names the paper by its DECIDED kind ("this contract", "this procedure", "this
transmittal", "this datasheet"; "document" when the kind is unknown), never always "datasheet". The kind is the engineer's
confirmed kind when there is one, else the code's reading of the cover (`paper_kind.decide_paper_kind`, a pure reading); a
datasheet, and a paper whose kind cannot be read, keep the words they always had.

`not_checked_sentence` is the ONE plain sentence a review that checked nothing of a paper carries (no checklist held for its
kind, no requirement asked of it): it says what was not checked and why, and says that silence is not acceptance
(CLAUDE.md rule 4: "not mentioned" is never "compliant"). Words and a kind only: no document text, no file name.

Reads only; no model, no network.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import kind_review_table, paper_kind

DATASHEET = "datasheet"
UNKNOWN_NOUN = "document"
#: kind -> the noun a sentence uses. A kind outside the table is a "document".
NOUNS = {
    "datasheet": "datasheet",
    "procedure": "procedure",
    "contract": "contract",
    "transmittal": "transmittal",
    "calculation": "calculation",
    "specification": "specification",
    "drawing": "drawing",
    "test_record": "test record",
}


def noun_of_kind(kind: str | None) -> str:
    """The noun for a decided kind; "document" for an unknown or other kind."""
    return NOUNS.get(str(kind or "").strip().lower().replace(" ", "_"), UNKNOWN_NOUN)


def decided_kind(document_id: str) -> str | None:
    """The kind of a stored paper, or None when none can be read: an engineer's confirmed kind, else the cover's reading.
    A kind that is only a guess still names the paper (the sentence does not claim more than the noun)."""
    from . import doc_router, document_kind
    from .db import connect

    stored = document_kind.stored_kind(document_id)
    if stored is not None and stored[1] == doc_router.STATE_CONFIRMED and stored[0]:
        return paper_kind.to_paper_kind(stored[0])
    pages = [
        dict(r)
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    if not pages:
        return None
    got = paper_kind.decide_paper_kind(pages)
    return None if got.source_kind == "unknown" else got.paper_kind


def noun_of_document(document_id: str) -> str:
    """The noun for a stored paper (`decided_kind`)."""
    return noun_of_kind(decided_kind(document_id))


def is_datasheet_like(kind: str | None) -> bool:
    """A datasheet, or a paper whose kind is not known: the reviews and the CRS keep their older behaviour for them."""
    return not kind or str(kind).strip().lower() == DATASHEET


def not_checked_sentence(kind: str | None) -> str | None:
    """The one plain sentence for a review that asked NO requirement of a paper of this kind, or None for a datasheet or an
    unknown kind (their own sentences stay). Says what was not checked and why; silence is not acceptance."""
    if is_datasheet_like(kind):
        return None
    noun = noun_of_kind(kind)
    row = kind_review_table.row(kind)
    if row["review"] == "completeness":
        return (
            f"This {noun} is checked only against the library (documents listed against documents held); "
            "nothing else in it was checked."
        )
    if kind_review_table.checklist_ending(kind) is None:
        why = f"No {noun} checklist is held, so no point of this {noun} was checked"
    else:
        why = f"No requirement of an applicable standard asks this {noun} for a value, so nothing in it was compared"
    return f"{why}; that does not mean the {noun} is acceptable."


HELD = "NEEDS_ENGINEER_REVIEW"
NOTE_NOT_CHECKED = "What was not checked"
NOTE_HELD = "Findings held for an engineer"


def held_sentence(held: int, rows: int) -> str:
    """The count of findings held for an engineer, with its boundary (whose findings it counts)."""
    return (
        f"{held} finding{'s' if held != 1 else ''} of this review run were held for an engineer (needs engineer review) "
        f"and are counted here, not listed as rows; this CRS has {rows} row{'s' if rows != 1 else ''}. "
        "Counted over this run's own findings only."
    )


def crs_meta(
    meta: dict,
    document_id: str,
    outcome: dict | None,
    findings: list[dict],
    rows: list[dict],
) -> dict:
    """The CRS meta of a run on a paper that is NOT a datasheet (a datasheet's CRS is unchanged: bench-proven): the quality export
    (one row per problem, a page or its reason, comments cut between words), a Review notes line that says what was NOT checked
    and why (never a silent empty CRS), and the count of findings held for an engineer with its boundary."""
    kind = decided_kind(document_id)
    # a datasheet keeps every word it had; and a CONTRACTOR copy of a paper that is not a datasheet stays as it was until the kind
    # is scored (owner: no new kind on a contractor copy before it is scored): only the internal copy changes
    if is_datasheet_like(kind) or meta.get("copy") != "internal":
        return meta
    comp = (outcome or {}).get("completeness") or {}
    sentence = comp.get("not_checked_plain") or (
        not_checked_sentence(kind) if comp.get("fields_required") == 0 else None
    )
    notes = list(meta.get("review_notes") or [])
    if sentence:
        notes.append(
            {
                "note": NOTE_NOT_CHECKED,
                "standard": "",
                "count": None,
                "detail": sentence,
            }
        )
    # a run stored before this change still says "datasheet": the CRS names the paper by its decided kind (the stored run is not changed)
    said = {
        **comp,
        "paper_noun": noun_of_kind(kind),
        **({"not_checked_plain": sentence} if sentence else {}),
    }
    meta = {
        **meta,
        "recommended_code_reason": in_noun(
            meta.get("recommended_code_reason") or "", said
        ),
    }
    held = sum(1 for f in findings if f.get("compliance_status") == HELD)
    if held:
        notes.append(
            {
                "note": NOTE_HELD,
                "standard": "",
                "count": held,
                "detail": held_sentence(held, len(rows)),
            }
        )
    return {
        **meta,
        "review_notes": notes,
        "export_quality": True,
        "paper_noun": said["paper_noun"],
    }


_WORD = re.compile(r"\bdatasheet(s?)\b", re.I)
_ROW_TEXT = ("comment", "page_section", "ai_review_comment", "reasoning")


def _swap(text: str, noun: str) -> str:
    return _WORD.sub(
        lambda m: (noun.capitalize() if m.group(0)[0].isupper() else noun) + m.group(1),
        text,
    )


_TEMPLATE_FILES = (
    "crs_mapping",
    "crs_page_words",
    "held_findings",
    "recommendations",
    "crs_blank_fields",
    "absence",
)
_MIN_TEMPLATE = 20


class TemplateSourceError(RuntimeError):
    """A row-builder file's source cannot be read: loud, never a silent "nothing to swap" (K2)."""


@lru_cache(maxsize=1)
def templates() -> tuple[str, ...]:
    """The system's OWN sentence fragments that name the paper "datasheet", read from the string constants of the six row-builder files
    (the places they are written), longest first. Only these exact fragments are ever rewritten for another kind: a quote from the
    paper or the rule book, a standard's or a file's title and a field label are never an exact copy of one, so they pass through
    untouched. No identifier ("datasheet_check") and nothing shorter than twenty characters qualifies (a short generic fragment such as "The datasheet " would also open a quote)."""
    import ast
    import importlib.util

    found: set[str] = set()
    for name in _TEMPLATE_FILES:
        spec = importlib.util.find_spec(f"{__package__}.{name}")
        if spec is None or not spec.origin:
            raise TemplateSourceError(
                f"the source of {name} cannot be found: no sentence of it could be named for another kind"
            )
        tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
            ):
                text = node.value
                if (
                    len(text) >= _MIN_TEMPLATE
                    and _WORD.search(text)
                    and not re.fullmatch(r"[a-z0-9_ ]+_[a-z0-9_ ]*", text)
                ):
                    found.add(text)
    return tuple(sorted(found, key=len, reverse=True))


_OPEN_CLOSE = {'"': '"', "\u201c": "\u201d", "\u2018": "\u2019", "'": "'"}


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """The INTERIORS of every quoted passage in `text`, as the row builders write them: straight and curly, double and single marks.
    A straight single mark is an opening only after a space, an opening bracket or the start (an apostrophe is not a quote). A quote
    that never closes runs to the end of the text, so what follows it is left alone: the safe side."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        opens = ch in _OPEN_CLOSE and (ch != "'" or i == 0 or text[i - 1] in " ([")
        if not opens:
            i += 1
            continue
        close, j = _OPEN_CLOSE[ch], i + 1
        while j < n and not (
            text[j] == close
            and (close != "'" or j + 1 == n or not text[j + 1].isalnum())
        ):
            j += 1
        spans.append((i + 1, j))
        i = j + 1
    return spans


def in_templates(text: str, noun: str) -> str:
    """`text` with the system's own datasheet-worded sentence fragments (`templates`) said of this paper's kind; everything else, quotes
    and titles and labels included, is returned as it was. A fragment that touches the inside of a quoted passage is never rewritten,
    whatever its length: text between quote marks is the paper's or the rule book's own."""
    fragments = templates()
    if not fragments:
        raise TemplateSourceError(
            "no template fragment is known: nothing could be said of this paper's kind"
        )
    spans = quoted_spans(text)
    pattern = re.compile("|".join(re.escape(f) for f in fragments))
    out, last = [], 0
    for m in pattern.finditer(text):
        if any(m.start() < b and a < m.end() for a, b in spans):
            continue
        out += [text[last : m.start()], _swap(m.group(0), noun)]
        last = m.end()
    return "".join(out) + text[last:]


def name_the_paper(view: dict, meta: dict) -> None:
    """The internal CRS VIEW of a paper that is not a datasheet (`meta["paper_noun"]`, set by `crs_meta` for the internal copy only)
    names the paper by its decided kind in the system's own sentences (`in_templates`: exact template fragments only; a quote, a title
    or a field label is never rewritten). The Comment By machine-draft labels become one set. Done on the BUILT view, never on the
    rows a numbering or an issue reads (a confirmed number keeps comparing its words with the rows as they were built)."""
    from . import crs_export_quality

    noun = meta.get("paper_noun")
    if not noun:
        return
    rows, notes = view.get("rows") or [], view.get("review_notes") or []
    for row in rows:
        for key in _ROW_TEXT:
            if isinstance(row.get(key), str):
                row[key] = in_templates(row[key], noun)
    for note in notes:
        if isinstance(note.get("detail"), str):
            note["detail"] = in_templates(note["detail"], noun)
    crs_export_quality.one_label_set(rows)


def in_noun(thing, completeness: dict | None):
    """The paper's noun in the review's sentences (K2): a run that recorded a decided kind other than a datasheet reads "contract",
    "procedure" ... where the sentences were written "datasheet", and a review that asked nothing of the paper says in one plain
    sentence what was not checked and why. Takes a reason string or a recommendation dict (its "reason" and "details"); a datasheet,
    an unknown kind and a run from before this change come back as they were."""
    noun = noun_in(completeness)
    if isinstance(thing, dict):
        return {
            **thing,
            **{
                k: in_noun(thing[k], completeness)
                for k in ("reason", "details")
                if isinstance(thing.get(k), str)
            },
        }
    if noun == DATASHEET or not isinstance(thing, str):
        return thing
    said = _swap(thing, noun)
    asked_nothing = (
        f"No applicable standard asks this {noun} for a value that was checked."
    )
    plain = (completeness or {}).get("not_checked_plain")
    return said.replace(asked_nothing, plain) if plain else said


def noun_in(completeness: dict | None) -> str:
    """The paper's noun in a sentence of the review: the run's recorded one, else "datasheet" (a run of a datasheet records none)."""
    return str((completeness or {}).get("paper_noun") or DATASHEET)


def run_words(document_id: str, required: int) -> dict:
    """What a run records about the paper's kind in its completeness: nothing for a datasheet or an unknown kind (its record stays
    as it was); else the noun, and, when no requirement was asked of it, the plain not-checked sentence."""
    kind = decided_kind(document_id)
    if is_datasheet_like(kind):
        return {}
    out = {"paper_noun": noun_of_kind(kind)}
    if not required:
        out["not_checked_plain"] = not_checked_sentence(kind)
    return out


def refresh_outcome(run_id: str) -> None:
    """After a run's comparison: a run on a paper that is not a datasheet records its decided noun and, when no requirement was asked
    of it, the plain not-checked sentence in its completeness, and its stored reason and details name the paper by that noun.
    A datasheet's run is not touched (its stored outcome stays byte for byte). Reads and writes this one run's outcome only."""
    import json

    from .db import connect

    conn = connect()
    row = conn.execute(
        "SELECT submittal_document_id, outcome_json FROM review_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None or not row["outcome_json"]:
        return
    outcome = json.loads(row["outcome_json"])
    comp = outcome.get("completeness")
    if not isinstance(comp, dict):
        return
    extra = run_words(
        row["submittal_document_id"], int(comp.get("fields_required") or 0)
    )
    if not extra:
        return
    comp = {**comp, **extra}
    outcome = in_noun({**outcome, "completeness": comp}, comp)
    with conn:
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), run_id),
        )
