"""THE FORM READER: one general path for any datasheet layout.

OWNER RULE (binding). No code recognises a datasheet's table shape, label
spelling or layout. The model fills the equipment type's FIXED FIELD LIST
(`form_reader_fields.field_list_for`, derived from the reference data only)
with value + unit + a verbatim quote from the page. Code only VERIFIES:

  1. the quote is on that page (whitespace, case and the owner's approved
     typographic characters folded - `model_evidence.APPROVED_CHARACTER_MAP`);
  2. the quote is a few cells, not the page (`claude_datasheet` limits);
  3. the value is inside the quote (`numparse.value_in_text`);
  4. the field's label, or a spelling of it from the reference data, is
     inside the quote (`datasheet_checks.label_search`);
  5. a unit, when given, is one `claims` knows, is printed in the quote (or
     in its column's header), and is of the field's unit kind;
  6. two runs of the same page give the same answer.

A field that fails is REJECTED WITH A NAMED REASON (counted), never silently
dropped; a field the model cannot fill stays MISSING. Two pages giving two
different verified values keep BOTH, marked CONFLICT for the engineer. The
comparison stays in the existing deterministic code: this module only
produces facts in the shape `datasheets._write_ai_reading` already writes.

NEVER RAISES INTO INGESTION: a failing, malformed, timed-out or capped model
is a recorded reason and the fields stay MISSING. Opens no socket; the engine
is `datasheet_ai.model_call_for` (or a caller's / test's callable).
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from . import (
    blank_markers,
    claims,
    claude_datasheet,
    datasheet_ai,
    datasheet_checks,
    numparse,
)
from .claude_spend import StopRun
from .datasheets import normalise_field_name, primary_unit
from .form_reader_fields import (
    FOUND,
    MAX_BATCH,
    NOT_ON_PAGE,
    PROMPT_VERSION,
    STATUSES,
    Field,
    batches,
    build_prompt,
    field_list_for,
    schema_for,
)
from .model_evidence import APPROVED_CHARACTER_MAP

log = logging.getLogger(__name__)

READER = "form_reader"
#: Facts are the model's, exactly as `datasheet_ai` writes them.
EXTRACTION_METHOD = claude_datasheet.EXTRACTION_METHOD
CONFIDENCE = claude_datasheet.CONFIDENCE
#: Every value is read as the vendor's stated (offered) value.
KIND = "offered"
#: The local engine's answer budget for one batch of up to 25 fields.
NUM_PREDICT = 4096
FILLED, MISSING, CONFLICT = "filled", "missing", "conflict"
#: Unit kinds a physical unit can be checked against (`kind` in the data).
_MEASURED_KINDS = frozenset({"pressure", "temperature", "flow", "length", "percent",
                             "area", "density", "viscosity"})
#: `claims` dimension -> the reference data's unit kind, where they differ.
_DIMENSION_KIND = {"volumetric_flow": "flow", "mass_flow": "flow"}
_APPROVED = str.maketrans(APPROVED_CHARACTER_MAP)


class Reason(Enum):
    """Why a field's reading was not kept. Always named, always counted."""

    MODEL_FAILED = "model_failed"
    MODEL_TIMED_OUT = "model_timed_out"
    MODEL_MALFORMED = "model_malformed"
    MODEL_STOPPED = "model_stopped_by_a_limit"
    MODEL_UNSTABLE = "model_unstable"
    #: The model left the field out of its answer: not a statement that the
    #: page lacks it, so the field is MISSING, not "not on page".
    FIELD_NOT_ANSWERED = "field_not_answered"
    STATUS_UNKNOWN = "status_unknown"
    VALUE_MISSING = "value_missing"
    VALUE_IS_BLANK_MARKER = "value_is_blank_marker"
    QUOTE_MISSING = "quote_missing"
    QUOTE_NOT_ON_PAGE = "quote_not_on_page"
    QUOTE_TOO_BROAD = "quote_too_broad"
    VALUE_NOT_IN_QUOTE = "value_not_in_quote"
    LABEL_NOT_IN_QUOTE = "label_not_in_quote"
    UNIT_UNRECOGNISED = "unit_unrecognised"
    UNIT_NOT_IN_QUOTE = "unit_not_in_quote"
    WRONG_UNIT_KIND = "wrong_unit_kind"


@dataclass
class FormReading:
    """One document's form. `status` maps every field key to FILLED,
    CONFLICT, NOT_ON_PAGE or MISSING; `rejected` holds `{field_key, page,
    reason}`; `errors` the pages that could not be read at all, with why."""

    fields: list[Field]
    facts: list[dict] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)
    errors: dict[int, str] = field(default_factory=dict)
    pages_read: list[int] = field(default_factory=list)
    stopped: str | None = None
    timed_out: list[int] = field(default_factory=list)
    seconds: float = 0.0

    def counts(self) -> dict:
        tally = Counter(self.status.values())
        return {"fields": len(self.fields), "filled": tally[FILLED],
                "not_on_page": tally[NOT_ON_PAGE], "missing": tally[MISSING],
                "conflicts": tally[CONFLICT], "pages_read": len(self.pages_read),
                "pages_failed": len(self.errors),
                "rejected_by_reason": dict(sorted(Counter(r["reason"] for r in self.rejected).items()))}


# ------------------------------------------------------------- verification

def _fold(text: str | None) -> str:
    return claude_datasheet._fold(str(text or "").translate(_APPROVED))


def quote_on_page(quote: str, page_text: str) -> bool:
    folded = _fold(quote)
    return bool(folded) and claude_datasheet._contains(_fold(page_text), folded)


def label_in_quote(f: Field, printed: str, rules: dict) -> bool:
    """The field's label - its role patterns, its words near each other, or a
    spelling from the reference data - is inside the quote."""
    if datasheet_checks.label_search(f.key, rules, {1: printed}):
        return True
    return any(claude_datasheet._field_in_quote(s, printed) for s in (f.name, *f.synonyms))


def unit_kind_of(unit: str, rules: dict) -> str | None:
    """The unit kind a unit spelling belongs to, from the reference data's
    unit lists first, then `claims`' dimension table. None when unknown."""
    base = primary_unit(unit) or unit
    kind = datasheet_checks._unit_kind(base, rules)
    if kind is None:
        dimension = claims.unit_dimension(base)
        kind = _DIMENSION_KIND.get(dimension, dimension) if dimension else None
    return kind


def _check_unit(f: Field, item: dict, printed: str, page_text: str, rules: dict) -> Reason | None:
    unit, value = item["unit"], item["value"]
    if unit:
        if not claude_datasheet._unit_recognised(unit):
            return Reason.UNIT_UNRECOGNISED
        if not (claude_datasheet._contains(printed, _fold(unit))
                or claude_datasheet._unit_in_column_header(unit, item["quote"], value, page_text)):
            return Reason.UNIT_NOT_IN_QUOTE
    shown = unit or datasheet_ai.ai_unit({"value": value})     # a unit printed inside the value
    if shown and f.unit_kind in _MEASURED_KINDS:
        kind = unit_kind_of(shown, rules)
        if kind is not None and kind != f.unit_kind:
            return Reason.WRONG_UNIT_KIND
    return None


def verify(f: Field, item: dict, page_text: str, rules: dict) -> Reason | None:
    """None when every gate holds for this field's reading, else the reason."""
    value, quote = item["value"], item["quote"]
    if not value:
        return Reason.VALUE_MISSING
    if blank_markers.classify(value)[0]:
        return Reason.VALUE_IS_BLANK_MARKER
    if not quote.strip():
        return Reason.QUOTE_MISSING
    if not quote_on_page(quote, page_text):
        return Reason.QUOTE_NOT_ON_PAGE
    if claude_datasheet._quote_too_broad(quote, _fold(page_text)):
        return Reason.QUOTE_TOO_BROAD
    printed = claude_datasheet.without_fill(_fold(quote))
    if not numparse.value_in_text(value, printed):
        return Reason.VALUE_NOT_IN_QUOTE
    if not label_in_quote(f, printed, rules):
        return Reason.LABEL_NOT_IN_QUOTE
    return _check_unit(f, item, printed, page_text, rules)


# ------------------------------------------------------------- one answer

def _item(raw: dict) -> dict:
    value = str(raw.get("value") or "").strip()
    unit = str(raw.get("unit") or "").strip()
    if unit and value.lower().endswith(unit.lower()) and len(value) > len(unit):
        value = value[:-len(unit)].strip()          # the unit given twice
    return {"value": value, "unit": unit, "quote": str(raw.get("quote") or ""),
            "status": str(raw.get("status") or "").strip().lower()}


def parse_answer(raw: object, keys: set[str]) -> tuple[dict[str, dict], Reason | None]:
    """`({field_key: item}, None)` or `({}, MODEL_MALFORMED)`. Strict JSON
    (one Markdown fence allowed); an object for a key not asked for is
    ignored; the first object for a key wins."""
    try:
        body = json.loads(claude_datasheet._unfenced(raw))
    except (json.JSONDecodeError, TypeError):
        return {}, Reason.MODEL_MALFORMED
    rows = body.get("fields") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return {}, Reason.MODEL_MALFORMED
    out: dict[str, dict] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("field_key") in keys and row["field_key"] not in out:
            out[row["field_key"]] = _item(row)
    return out, None


def _identity(item: dict | None) -> tuple:
    if item is None or item["status"] != FOUND:
        return (item or {}).get("status") or NOT_ON_PAGE, None, None
    return FOUND, numparse.fold_numbers(item["value"]), _fold(item["unit"])


def _call(model_call, prompt: str) -> tuple[str | None, Reason | None]:
    """A limit (`StopRun`) is NOT caught here: it goes up to `_read_page`,
    which records WHICH limit (its `count_key`, e.g. "document_not_approved")
    as `datasheet_ai` does - not one generic "stopped" for every cap."""
    try:
        return model_call(prompt), None
    except StopRun:
        raise
    except Exception as exc:  # noqa: BLE001 - never into ingestion; the failure is recorded as a named reason
        log.info("form_reader: model call failed (%s)", type(exc).__name__)
        return None, Reason.MODEL_TIMED_OUT if datasheet_ai.is_timeout(exc) else Reason.MODEL_FAILED


def _runs(model_call, prompt: str, keys: set[str], runs: int) -> tuple[list[dict], Reason | None]:
    answers = []
    for _ in range(runs):
        raw, err = _call(model_call, prompt)
        if err is None:
            parsed, err = parse_answer(raw, keys)
        if err is not None:
            return [], err
        answers.append(parsed)
    return answers, None


def _fact(f: Field, item: dict, page: int) -> dict:
    return {"field": f.name, "field_name": normalise_field_name(f.name), "field_key": f.key,
            "value": item["value"], "unit": item["unit"] or None, "quote": item["quote"],
            "kind": KIND, "page": page, "extraction_method": EXTRACTION_METHOD,
            "confidence": CONFIDENCE,
            "provenance": {"reader": READER, "field_key": f.key, "page": page,
                           "quote": item["quote"], "prompt_version": PROMPT_VERSION}}


def read_batch(fields: list[Field], page_text: str, page: int, model_call, rules: dict,
               runs: int = 2) -> tuple[list[dict], list[dict], set[str], Reason | None]:
    """One batch on one page: `(facts, rejected, not_on_page keys, error)`."""
    keys = {f.key for f in fields}
    answers, err = _runs(model_call, build_prompt(fields, page_text, page), keys, runs)
    if err is not None:
        return [], [{"field_key": k, "page": page, "reason": err.value} for k in sorted(keys)], set(), err
    facts, rejected, absent = [], [], set()
    for f in fields:
        first = answers[0].get(f.key)
        if any(_identity(a.get(f.key)) != _identity(first) for a in answers[1:]):
            reason = Reason.MODEL_UNSTABLE
        elif first is None:
            reason = Reason.FIELD_NOT_ANSWERED
        elif first["status"] == NOT_ON_PAGE:
            absent.add(f.key)
            continue
        elif first["status"] not in STATUSES:
            reason = Reason.STATUS_UNKNOWN
        else:
            reason = verify(f, first, page_text, rules)
        if reason is None:
            facts.append(_fact(f, first, page))
        else:
            rejected.append({"field_key": f.key, "page": page, "reason": reason.value})
    return facts, rejected, absent, None


# ------------------------------------------------------------- the document

def _decide(reading: FormReading, found: dict[str, list[dict]], absent: dict[str, int]) -> None:
    """Per field: one verified value -> FILLED (first page kept, the others
    named); two different values -> CONFLICT, every one kept and marked;
    none -> NOT_ON_PAGE when every page read said so, else MISSING."""
    for f in reading.fields:
        facts = found.get(f.key, [])
        values = {_identity({**x, "status": FOUND}) for x in facts}
        if len(values) == 1:
            keep = facts[0]
            keep["provenance"]["also_on_pages"] = [x["page"] for x in facts[1:]]
            reading.facts.append(keep)
            reading.status[f.key] = FILLED
        elif len(values) > 1:
            pages = [x["page"] for x in facts]
            for x in facts:
                x["form_conflict"] = True
                x["provenance"]["conflict_pages"] = pages
            reading.facts.extend(facts)
            reading.status[f.key] = CONFLICT
        elif reading.pages_read and absent.get(f.key) == len(reading.pages_read) \
                and not any(r["field_key"] == f.key for r in reading.rejected):
            reading.status[f.key] = NOT_ON_PAGE
        else:
            reading.status[f.key] = MISSING


def read_form(page_texts: dict[int, str], equipment_type: str | None, model_call, *,
              runs: int = 2, batch_size: int = MAX_BATCH, max_seconds: float | None = None,
              rules: dict | None = None, fields: list[Field] | None = None) -> FormReading:
    """Fill the equipment type's form from every page. `runs=2` (the default)
    keeps a reading only when both runs agree; `runs=1` reads once."""
    rules = rules or datasheet_checks.load_rules()
    reading = FormReading(fields=fields if fields is not None else field_list_for(equipment_type, rules))
    found: dict[str, list[dict]] = {}
    absent: Counter = Counter()
    started = time.monotonic()
    for page in sorted(page_texts):
        text = page_texts[page] or ""
        why = _page_skip(reading, text, started, max_seconds)
        if why:
            reading.errors[page] = why
            continue
        _read_page(reading, page, text, model_call, rules, runs, batch_size, found, absent)
    reading.seconds = round(time.monotonic() - started, 1)
    _decide(reading, found, absent)
    return reading


def _page_skip(reading: FormReading, text: str, started: float, max_seconds: float | None) -> str | None:
    if reading.stopped:
        return f"not read: a limit stopped the form reader ({reading.stopped})"
    if not text.strip():
        return "no text on this page"
    if max_seconds is not None and time.monotonic() - started >= max_seconds:
        reading.stopped = "time_budget"
        return f"not read: the form reader's time budget ({max_seconds:g} s) ran out"
    return None


def _read_page(reading: FormReading, page: int, text: str, model_call, rules: dict, runs: int,
               batch_size: int, found: dict, absent: Counter) -> None:
    errors: list[Reason] = []
    groups = batches(reading.fields, batch_size)
    for group in groups:
        try:
            facts, rejected, gone, err = read_batch(group, text, page, model_call, rules, runs)
        except StopRun as exc:
            facts, gone, err = [], set(), Reason.MODEL_STOPPED
            rejected = [{"field_key": f.key, "page": page, "reason": err.value} for f in group]
            reading.stopped = exc.count_key
        reading.rejected.extend(rejected)
        absent.update(gone)
        for fact in facts:
            found.setdefault(fact["field_key"], []).append(fact)
        if err is not None:
            errors.append(err)
            if err is Reason.MODEL_STOPPED:
                break
    if errors and len(errors) >= len(groups):
        reading.errors[page] = f"form reader could not read this page ({errors[0].value})"
        if Reason.MODEL_TIMED_OUT in errors:
            reading.timed_out.append(page)
    else:
        reading.pages_read.append(page)


__all__ = [
    "CONFLICT",
    "EXTRACTION_METHOD",
    "FILLED",
    "KIND",
    "MISSING",
    "NOT_ON_PAGE",
    "READER",
    "FormReading",
    "Reason",
    "build_prompt",
    "field_list_for",
    "label_in_quote",
    "parse_answer",
    "quote_on_page",
    "read_batch",
    "read_form",
    "schema_for",
    "unit_kind_of",
    "verify",
]
