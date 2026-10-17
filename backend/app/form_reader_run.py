"""The form reader inside extraction (DATASHEET_READER_MODE=form).

`datasheets._extract_facts` asks this module for a reading in EXACTLY the
shape `datasheet_ai.read_pages` returns, so the existing merge and write path
(`datasheets._write_ai_reading` -> `datasheet_ai.merge_readings`) is reused
unchanged: the form reader's facts are the AI reading, and the rule readers'
facts become its cross-check (agreement raises confidence, disagreement keeps
both flagged `conflict`, a rule fact the form did not confirm is kept and
marked unconfirmed). Nothing here raises into ingestion.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

from . import datasheet_ai
from .config import settings
from .db import connect
from .form_reader import NUM_PREDICT, FormReading, read_form
from .form_reader_fields import PROMPT_VERSION, field_list_for, schema_for, with_requirement_fields

RULES, MERGE, FORM = "rules", "merge", "form"
MODES = (RULES, MERGE, FORM)


def reader_mode() -> str:
    """`settings.datasheet_reader_mode`, folded ("merge" when unset)."""
    return str(settings.datasheet_reader_mode or MERGE).strip().lower() or MERGE


def equipment_type_of(document_id: str, chunks: list) -> str | None:
    """The document's recorded equipment type; else what its own text names
    (`classification.suggest_equipment_type`); else None (the generic form).
    A database error is a None (the generic form), never a crash."""
    from . import classification
    try:
        row = connect().execute(
            "SELECT equipment_type FROM document_classification WHERE document_id = ?",
            (document_id,)).fetchone()
    except sqlite3.Error:
        row = None
    if row is not None and (row["equipment_type"] or "").strip():
        return row["equipment_type"]
    suggestion = classification.suggest_equipment_type([dict(c) for c in chunks])
    return suggestion.equipment_type if suggestion is not None else None


#: What a requirement's SUBJECT may look like to be a form label: a short plain noun phrase.
_PLAIN_LABEL_WORDS = 8


def requirement_subjects(standard_ids: list[str] | tuple[str, ...]) -> list[str]:
    """The fields the given standards' evaluable requirements are ABOUT, most
    asked first: the subject of a numeric limit, a range, a nominal value, and
    the output field of a two-field comparison. Plain short labels only; a
    long or odd subject is not a form line. [] when there are no standards."""
    from . import requirements_3b

    ids = [i for i in dict.fromkeys(standard_ids or []) if i]
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    types = ("numeric_limit", requirements_3b.RANGE_LIMIT, requirements_3b.NOMINAL_VALUE, requirements_3b.CROSS_FIELD_LIMIT)
    try:
        rows = connect().execute(
            "SELECT requirement_type, subject, source_text FROM standard_requirements"
            f" WHERE superseded_at IS NULL AND standard_document_id IN ({marks})"
            f" AND requirement_type IN ({','.join('?' for _ in types)})", [*ids, *types]).fetchall()
    except sqlite3.Error:
        return []
    counts: Counter = Counter()
    for row in rows:
        subject = row["subject"]
        if row["requirement_type"] == requirements_3b.CROSS_FIELD_LIMIT:
            cross = requirements_3b.parse_cross_field(row["source_text"])
            subject = cross["output"] if cross else None
        text = " ".join(str(subject or "").split()).lower()
        words = text.split()
        if (text and text.isascii() and 1 <= len(words) <= _PLAIN_LABEL_WORDS
                and any(len(w) >= 3 and w.isalpha() for w in words)):
            counts[text] += 1
    return [subject for subject, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def standards_of(document_id: str) -> list[str]:
    """The standards the sheet's form is built for: the latest review run's
    included standards. [] when the sheet has no run yet (the form is then the
    type's own)."""
    try:
        run = connect().execute(
            "SELECT id FROM review_runs WHERE submittal_document_id = ? ORDER BY rowid DESC LIMIT 1",
            (document_id,)).fetchone()
        if run is not None:
            return [r["standard_document_id"] for r in connect().execute(
                "SELECT standard_document_id FROM review_applicable_standards"
                " WHERE review_run_id = ? AND included = 1", (run["id"],))]
    except sqlite3.Error:
        return []
    return []


def _page_counts(rejected: list[dict], page: int) -> dict:
    return dict(Counter(r["reason"] for r in rejected if r["page"] == page))


def as_ai_run(reading: FormReading, page_numbers: list[int], *, engine: str | None,
              model: str | None, unavailable: str | None) -> dict:
    """The `datasheet_ai.read_pages` shape, built from a `FormReading`."""
    pages: dict[int, dict] = {}
    reasons: dict[int, str] = {}
    for page in page_numbers:
        if page in reading.errors or unavailable:
            reasons[page] = unavailable or reading.errors[page]
            if page in reading.errors and not unavailable:
                pages[page] = {"page": page, "engine": engine, "accepted": [], "rejected": [],
                               "counts": {}, "error": reading.errors[page]}
            continue
        pages[page] = {"page": page, "engine": engine,
                       "accepted": [f for f in reading.facts if f["page"] == page],
                       "rejected": [r for r in reading.rejected if r["page"] == page],
                       "counts": _page_counts(reading.rejected, page)}
    return {"engine": engine, "model": model, "unavailable": unavailable, "pages": pages,
            "reasons": reasons, "stopped": reading.stopped, "timed_out": list(reading.timed_out),
            "seconds": reading.seconds, "reader": "form_reader", "form": reading.counts()}


def read_document(page_texts: dict[int, str], equipment_type: str | None,
                  model_call=None, extra_subjects: list[str] | None = None) -> dict:
    """The form reading of one document, as an `ai_run`. `model_call`
    defaults to the configured engine (DATASHEET_AI_READER) asked for this
    reader's flat schema; an unavailable engine or an invalid checklist is a
    reason on every page, and every field stays MISSING."""
    pages = sorted(page_texts)
    try:
        fields = field_list_for(equipment_type)
        if extra_subjects:
            fields = with_requirement_fields(fields, extra_subjects)
    except ValueError as exc:               # a refused local checklist overlay
        empty = FormReading(fields=[])
        return as_ai_run(empty, pages, engine=None, model=None,
                         unavailable=f"form reader: checklist refused ({type(exc).__name__})")
    why = None
    if model_call is None:
        model_call, why = datasheet_ai.model_call_for(None, packet_shape={
            "json_schema": schema_for(fields), "prompt_version": PROMPT_VERSION,
            "num_predict": NUM_PREDICT})
    engine = getattr(model_call, "engine", "custom") if model_call else datasheet_ai.engine_setting()
    model = getattr(model_call, "model", None)
    if model_call is None:
        reading = FormReading(fields=fields, status={f.key: "missing" for f in fields})
        return as_ai_run(reading, pages, engine=engine, model=None, unavailable=why)
    reading = read_form(page_texts, equipment_type, model_call, fields=fields,
                        max_seconds=float(settings.datasheet_ai_max_seconds),
                        batch_size=int(settings.form_reader_batch_size))
    run = as_ai_run(reading, pages, engine=engine, model=model, unavailable=None)
    run["equipment_type"] = equipment_type
    run["form_batch_size"] = int(settings.form_reader_batch_size)    # what the run asked per call
    return run


__all__ = ["FORM", "MERGE", "MODES", "RULES", "as_ai_run", "equipment_type_of",
           "read_document", "reader_mode", "requirement_subjects", "standards_of"]
