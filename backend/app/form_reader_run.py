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
from .form_reader_fields import PROMPT_VERSION, field_list_for, schema_for

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
                  model_call=None) -> dict:
    """The form reading of one document, as an `ai_run`. `model_call`
    defaults to the configured engine (DATASHEET_AI_READER) asked for this
    reader's flat schema; an unavailable engine or an invalid checklist is a
    reason on every page, and every field stays MISSING."""
    pages = sorted(page_texts)
    try:
        fields = field_list_for(equipment_type)
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
                        max_seconds=float(settings.datasheet_ai_max_seconds))
    run = as_ai_run(reading, pages, engine=engine, model=model, unavailable=None)
    run["equipment_type"] = equipment_type
    return run


__all__ = ["FORM", "MERGE", "MODES", "RULES", "as_ai_run", "equipment_type_of",
           "read_document", "reader_mode"]
