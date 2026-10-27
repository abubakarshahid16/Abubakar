"""The form reader inside extraction (DATASHEET_READER_MODE=form, the default since #882).

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
from contextlib import contextmanager
from contextvars import ContextVar

from . import claims, datasheet_ai, reader_speed
from .config import settings
from .db import connect
from .form_reader import NUM_PREDICT, FormReading, read_form
from .form_reader_fields import (
    PROMPT_VERSION,
    field_list_for,
    schema_for,
    with_requirement_fields,
)

RULES, MERGE, FORM = "rules", "merge", "form"
MODES = (RULES, MERGE, FORM)


def reader_mode() -> str:
    """`settings.datasheet_reader_mode`, folded ("form", the default, when unset)."""
    return str(settings.datasheet_reader_mode or FORM).strip().lower() or FORM


def equipment_type_of(document_id: str, chunks: list) -> str | None:
    """The document's recorded equipment type; else what its own text names
    (`classification.suggest_equipment_type`); else None (the generic form).
    A database error is a None (the generic form), never a crash."""
    from . import classification

    try:
        row = (
            connect()
            .execute(
                "SELECT equipment_type FROM document_classification WHERE document_id = ?",
                (document_id,),
            )
            .fetchone()
        )
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
    types = (
        "numeric_limit",
        requirements_3b.RANGE_LIMIT,
        requirements_3b.NOMINAL_VALUE,
        requirements_3b.CROSS_FIELD_LIMIT,
    )
    try:
        rows = (
            connect()
            .execute(
                "SELECT requirement_type, subject, source_text FROM standard_requirements"
                f" WHERE superseded_at IS NULL AND standard_document_id IN ({marks})"
                f" AND requirement_type IN ({','.join('?' for _ in types)})",
                [*ids, *types],
            )
            .fetchall()
        )
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
        if (
            text
            and text.isascii()
            and 1 <= len(words) <= _PLAIN_LABEL_WORDS
            and any(len(w) >= 3 and w.isalpha() for w in words)
        ):
            counts[text] += 1
    return [
        subject
        for subject, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


#: The standards a read is made for when the caller KNOWS them (the review has
#: just chosen them, order 211 R2); None: the latest run's, as `standards_of`.
_READING_FOR: ContextVar[tuple[str, ...] | None] = ContextVar(
    "reading_for", default=None
)


@contextmanager
def reading_for(standard_ids):
    """Inside this block `standards_of` answers `standard_ids`, whatever the
    document's latest run says."""
    token = _READING_FOR.set(tuple(dict.fromkeys(i for i in standard_ids if i)))
    try:
        yield
    finally:
        _READING_FOR.reset(token)


def standards_of(document_id: str) -> list[str]:
    """The standards the sheet's form is built for: the ones named by
    `reading_for`, else the latest review run's included standards. [] when
    there are none yet (the form is then the type's own)."""
    forced = _READING_FOR.get()
    if forced is not None:
        return list(forced)
    try:
        run = (
            connect()
            .execute(
                "SELECT id FROM review_runs WHERE submittal_document_id = ? ORDER BY rowid DESC LIMIT 1",
                (document_id,),
            )
            .fetchone()
        )
        if run is not None:
            return [
                r["standard_document_id"]
                for r in connect().execute(
                    "SELECT standard_document_id FROM review_applicable_standards"
                    " WHERE review_run_id = ? AND included = 1",
                    (run["id"],),
                )
            ]
    except sqlite3.Error:
        return []
    return []


def _page_counts(rejected: list[dict], page: int) -> dict:
    return dict(Counter(r["reason"] for r in rejected if r["page"] == page))


def as_ai_run(
    reading: FormReading,
    page_numbers: list[int],
    *,
    engine: str | None,
    model: str | None,
    unavailable: str | None,
) -> dict:
    """The `datasheet_ai.read_pages` shape, built from a `FormReading`."""
    pages: dict[int, dict] = {}
    reasons: dict[int, str] = {}
    for page in page_numbers:
        if page in reading.errors or unavailable:
            reasons[page] = unavailable or reading.errors[page]
            if page in reading.errors and not unavailable:
                pages[page] = {
                    "page": page,
                    "engine": engine,
                    "accepted": [],
                    "rejected": [],
                    "counts": {},
                    "error": reading.errors[page],
                }
            continue
        pages[page] = {
            "page": page,
            "engine": engine,
            "accepted": [f for f in reading.facts if f["page"] == page],
            "rejected": [r for r in reading.rejected if r["page"] == page],
            "counts": _page_counts(reading.rejected, page),
        }
    return {
        "engine": engine,
        "model": model,
        "unavailable": unavailable,
        "pages": pages,
        "reasons": reasons,
        "stopped": reading.stopped,
        "timed_out": list(reading.timed_out),
        "seconds": reading.seconds,
        "reader": "form_reader",
        "form": reading.counts(),
    }


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _same_reading(a: dict, b: dict) -> bool:
    """Are two model readings of one field the same reading? Safe side: a
    different value, or the same number in two different units, is NOT the
    same (it must reach the engineer as a conflict). A unit only one side
    carries adds nothing, as in `datasheet_ai.reading_relation`."""
    va = " ".join(str(a.get("value") or "").lower().split())
    vb = " ".join(str(b.get("value") or "").lower().split())
    na, nb = _number(va), _number(vb)
    if va != vb and (na is None or na != nb):
        return False
    ua, ub = datasheet_ai.ai_unit(a), datasheet_ai.ai_unit(b)
    if not (ua and ub):
        return True
    # The same SPELLING and reference only: `datasheet_ai.same_unit` also
    # calls two convertible units one ("bar" and "psi"), and 10 bar is not
    # 10 psi.
    (base_a, ref_a), (base_b, ref_b) = (
        claims.split_reference(ua),
        claims.split_reference(ub),
    )
    return ref_a == ref_b and claims._fold_unit(base_a or "") == claims._fold_unit(
        base_b or ""
    )


#: Said on a page the whole-page (merge) pass did not read, or read only in
#: part, while the form read it.
MERGE_GAP = "the whole-page AI reading: {why}"


def _form_read(form_run: dict, page) -> bool:
    mine = form_run["pages"].get(page)
    return mine is not None and not mine.get("error")


def _carry_merge_gaps(form_run: dict, merge_run: dict) -> None:
    """Order 139: the merge pass's own gaps are the run's gaps too. A page
    the form read but the whole-page reader did not read, or read only in
    part (cut off, timed out, out of time, failed), used to vanish - the
    form's page looked clean. It is now PARTLY read (`partly_read`): it has
    an AI reading, so it is never "left to the code readers" (`reasons`) nor
    timed out. A page the form did not read keeps the form's own reason."""
    partly = form_run.setdefault("partly_read", {})
    gaps = {**(merge_run.get("reasons") or {}), **(merge_run.get("partly_read") or {})}
    for page, extra in (merge_run.get("pages") or {}).items():
        if extra.get("error") or extra.get("partial"):
            gaps.setdefault(page, extra.get("error") or extra["partial"])
    for page, why in gaps.items():
        if why and _form_read(form_run, page):
            partly.setdefault(page, MERGE_GAP.format(why=why))


def add_merge_reading(form_run: dict, merge_run: dict) -> dict:
    """The form ADDS to the whole-page reading, never replaces it (#1004,
    planner order 41, option b). PF1 17 Oct: where the equipment type's form
    is thin (a transmitter: 2 fields) form-only read 4 fewer values than the
    merge reader and lost 2 defects. So the merge reader's accepted readings
    for every field the form did NOT read on that page are kept beside the
    form's; a page the form could not read takes the merge reading whole.
    Both readings were already checked by their own reader (quote on the
    page, two runs agree), and the same merge with the rule readers follows.
    Pure: no model, no database; `form_run` is returned, updated.

    On a field the form DID read, a merge reading is kept too unless it is the
    same reading as one of the form's (`_same_reading`): a sheet that states a
    field twice (10 and 16) must reach the engineer as a conflict, never as
    the form's one value. `replaced_by_form` counts the repeats dropped."""
    added = 0
    replaced = 0
    by_page: dict[int, dict] = {}
    _carry_merge_gaps(form_run, merge_run)
    for page, extra in (merge_run.get("pages") or {}).items():
        if extra.get("error"):
            continue
        mine = form_run["pages"].get(page)
        if mine is None or mine.get("error"):
            form_run["pages"][page] = extra
            form_run["reasons"].pop(page, None)
            if extra.get("partial"):
                form_run["partly_read"][page] = MERGE_GAP.format(why=extra["partial"])
            added += len(extra.get("accepted") or [])
            by_page[page] = {
                "form": 0,
                "merge_new": len(extra.get("accepted") or []),
                "merge_same": 0,
            }
            continue
        read: dict[str, list[dict]] = {}
        for f in mine["accepted"]:
            read.setdefault(datasheet_ai.field_key(f), []).append(f)
        more = []
        for f in extra.get("accepted") or []:
            theirs = read.get(datasheet_ai.field_key(f))
            # A field the form read keeps a merge reading that CONTRADICTS
            # every form value, so `merge_readings` raises the conflict for
            # the engineer and the sheet's second value is never silently
            # dropped (cloud-2's review of #1004). Only a reading the form
            # repeats is replaced, and it is counted.
            if theirs and any(_same_reading(f, g) for g in theirs):
                replaced += 1
            else:
                more.append(f)
        by_page[page] = {
            "form": len(mine["accepted"]),
            "merge_new": len(more),
            "merge_same": len(extra.get("accepted") or []) - len(more),
        }
        mine["accepted"] = [*mine["accepted"], *more]
        # What the whole-page reader put forward and the code refused is kept
        # apart: a page is "read, no field found" only when NOTHING was
        # proposed (`page_ledger.read_page_empty`). The form's own counts are
        # not touched, so the reader's tallies read as before.
        mine["merge_rejected"] = extra.get("rejected") or []
        mine["merge_counts"] = extra.get("counts") or {}
        mine.update({k: extra[k] for k in ("cut_off", "parts") if extra.get(k)})
        added += len(more)
    form_run["added_from_merge"] = added
    # Per page, counts only (order 246.3): how many readings the form made, how many
    # the whole-page pass ADDED, and how many it merely repeated. A page where the
    # pass adds nothing is a candidate for skipping its call; the counts show which.
    if isinstance(form_run.get("form"), dict):
        form_run["form"]["merge_by_page"] = dict(sorted(by_page.items()))
    form_run["replaced_by_form"] = replaced
    form_run["stopped"] = form_run.get("stopped") or merge_run.get("stopped")
    form_run["seconds"] = round(
        float(form_run.get("seconds") or 0) + float(merge_run.get("seconds") or 0), 1
    )
    return form_run


def read_document(
    page_texts: dict[int, str],
    equipment_type: str | None,
    model_call=None,
    extra_subjects: list[str] | None = None,
) -> dict:
    """The form reading of one document, as an `ai_run`. `model_call`
    defaults to the configured engine (DATASHEET_AI_READER) asked for this
    reader's flat schema; an unavailable engine or an invalid checklist is a
    reason on every page, and every field stays MISSING."""
    pages = sorted(page_texts)
    try:
        fields = field_list_for(equipment_type)
        if extra_subjects:
            fields = with_requirement_fields(fields, extra_subjects)
    except ValueError as exc:  # a refused local checklist overlay
        empty = FormReading(fields=[])
        return as_ai_run(
            empty,
            pages,
            engine=None,
            model=None,
            unavailable=f"form reader: checklist refused ({type(exc).__name__})",
        )
    why = None
    if model_call is None:
        model_call, why = datasheet_ai.model_call_for(
            None,
            packet_shape={
                "json_schema": reader_speed.shorten_schema(schema_for(fields)),
                "prompt_version": reader_speed.version(PROMPT_VERSION),
                "num_predict": NUM_PREDICT,
            },
        )
    engine = (
        getattr(model_call, "engine", "custom")
        if model_call
        else datasheet_ai.engine_setting()
    )
    model = getattr(model_call, "model", None)
    if model_call is None:
        reading = FormReading(fields=fields, status={f.key: "missing" for f in fields})
        return as_ai_run(reading, pages, engine=engine, model=None, unavailable=why)
    reading = read_form(
        page_texts,
        equipment_type,
        model_call,
        fields=fields,
        max_seconds=float(settings.datasheet_ai_max_seconds),
        batch_size=int(settings.form_reader_batch_size),
    )
    run = as_ai_run(reading, pages, engine=engine, model=model, unavailable=None)
    run["equipment_type"] = equipment_type
    # The requirement fields this read asked for, kept in the run's summary so
    # a later review can tell which of its standards' fields were never asked.
    run["asked_subjects"] = [f.name for f in fields if f.key.startswith("req_")]
    # order 224.9: WHICH field was refused and why (counts only, never text)
    run["rejected_fields"] = dict(
        Counter(f"{r['field_key']}: {r['reason']}" for r in reading.rejected)
    )
    run["form_batch_size"] = int(
        settings.form_reader_batch_size
    )  # what the run asked per call
    return run


def read_both(texts: dict[int, str], equipment_type: str | None, standard_ids) -> dict:
    """The form reading, then the whole-page reading added to it
    (`add_merge_reading`). The form is read FIRST, so the whole-page pass can be
    told which fields the form read on each page (`reader_speed`'s
    `skip_form_read` cut; a no-op unless it is on)."""
    form = read_document(
        texts, equipment_type, extra_subjects=requirement_subjects(standard_ids)
    )
    agreed = reader_speed.agreed_pages(texts, form)
    asked = reader_speed.pages_to_ask(texts, agreed)
    with reader_speed.skipping(reader_speed.form_read_labels(form)):
        merge = datasheet_ai.read_pages(asked)
    run = add_merge_reading(form, merge)
    # counts only (order 246.3): the pages the form read fully, and those the whole-page call skipped
    run["form"]["pages_fully_agreed"] = agreed
    run["form"]["pages_merge_skipped"] = [p for p in texts if p not in asked]
    return run


def refusal_summary(ai_run: dict, ai_stats: dict) -> dict:
    """Order 224.9, for `datasheets.reader_summary`: the readings the code gate
    refused BY REASON (`dropped` reasons are prefixed), and the form reader's
    refusals by field. Counts only, never a page's words."""
    dropped = {f"dropped: {k}": n for k, n in (ai_stats.get("dropped") or {}).items()}
    form = ai_run.get("form") or {}
    return {
        "refused_by_reason": {**(ai_stats.get("proposals_rejected") or {}), **dropped},
        "rejected_fields": ai_run.get("rejected_fields") or {},
        # order 246: per page, what the whole-page pass added and which pages the form
        # read fully (page numbers and counts only), so a run shows where minutes go
        "speed_counts": {
            key: form[key]
            for key in ("merge_by_page", "pages_fully_agreed", "pages_merge_skipped")
            if key in form
        },
    }


__all__ = [
    "FORM",
    "MERGE",
    "MODES",
    "RULES",
    "add_merge_reading",
    "as_ai_run",
    "equipment_type_of",
    "read_both",
    "read_document",
    "reader_mode",
    "reading_for",
    "refusal_summary",
    "requirement_subjects",
    "standards_of",
]
