"""#805 plan change 6, part A: a compile's verified rows become rows of the version 2 tables. Writes nothing else.

The compile's own table stays as it is: a later compile or re-proof replaces its rows, so nothing here points at them.
Every quote is checked again on the stored page by the one quote check; what fails is dropped and counted by reason.

THE RULE'S KEY is the standard's name, who the rule is for, the field and the condition: no clause number, no edition,
no figure, so a changed limit or a renumbered clause is another version of the same rule, and the same reading in a new
edition keeps its version and gains a source. Rows sharing a key take a place by page, so two rules on one thing never
read as one superseding the other. A rule not seen in a later compile is not retired: only a person retires a rule.

THE REQUIREMENT is shaped here. A number, its comparator and its unit make a limit. Two ends make a range and two
choices alternatives: neither holds a single figure. A sentence with no figure holds none. One that sends the reader to
another document says so, and is never a pass. Applicability today is the reader's words, as `subject` and `condition`;
the report counts them by type. Generic only (rule 13): nothing here knows a layout or a standard.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from . import compiled_rule_report as report
from . import numparse, rulebook_v2
from .claims import unit_dimension
from .compiled_rule_proof import quote_verified
from .config import settings
from .converter_gates import fold as _fold
from .rulebook_v2 import Reading
from .rulebook_v2_check import (
    ALTERNATIVES,
    COMPARATORS,
    DEFERS_TO,
    LIMIT,
    NO_FIGURE,
    NO_UNIT,
    RANGE,
)

BOUNDARY = "this standard's rows in the rulebook tables of this database copy"
_ACTOR_PREFIX = "compile:"
_RANGE = re.compile(
    r"^\s*(?:between\s+)?(?P<low>\S+?)\s*(?:\bto\b|\band\b|[-\N{EN DASH}\N{EM DASH}])\s*(?P<high>\S+)\s*$",
    re.IGNORECASE,
)
_CHOICES = re.compile(r"\s+or\s+|\s*/\s*", re.IGNORECASE)
_DEFERS = re.compile(
    r"\b(?:in\s+accordance\s+with|comply\s+with|conform\s+to|as\s+specified\s+in|as\s+required\s+by|as\s+per)\s+"
    r"(?P<target>[^.;]+)",
    re.IGNORECASE,
)


def _without_figure(field: str, quote: str, words: str | None) -> dict:
    target = None if words else _DEFERS.search(quote or "")
    if target:
        return {
            "kind": DEFERS_TO,
            "field": field,
            "value_text": " ".join(target["target"].split()),
        }
    return {"kind": NO_FIGURE, "field": field, "value_text": words}


def requirement_of(row) -> dict:
    """Field, comparator, value, unit, or the same with no single figure when the sentence does not state one."""
    field = " ".join((row["field"] or "").split())
    words = " ".join((row["limit_text"] or "").split()) or None
    unit = (row["unit"] or "").strip() or None
    if words is None:
        return _without_figure(field, row["quote"], None)
    figure = {
        "unit": unit or NO_UNIT,
        "unit_dimension": unit_dimension(unit) if unit else None,
    }
    number = numparse.as_limit(words)
    if number is not None:
        if row["comparator"] not in COMPARATORS:
            return _without_figure(field, row["quote"], words)
        return {
            "kind": LIMIT,
            "field": field,
            "comparator": row["comparator"],
            "value": number,
            **figure,
        }
    ends = _RANGE.match(words)
    if ends:
        low, high = numparse.as_limit(ends["low"]), numparse.as_limit(ends["high"])
        if low is not None and high is not None and low <= high:
            return {
                "kind": RANGE,
                "field": field,
                "value_low": low,
                "value_high": high,
                "value_text": words,
                **figure,
            }
    if len(_CHOICES.split(words)) > 1:
        return {
            "kind": ALTERNATIVES,
            "field": field,
            "value_text": words,
            "unit": unit,
        }
    return _without_figure(field, row["quote"], words)


def _applicability(row) -> tuple[tuple[str, str, int | None], ...]:
    out = []
    subject = " ".join((row["applies_to"] or "").split())
    if subject:
        out.append(("subject", subject, row["applies_to_verified"]))
    condition = " ".join((row["condition_text"] or "").split())
    if condition:
        out.append(
            ("condition", condition, 1)
        )  # the proof dropped any condition not on the page
    return tuple(out)


def _identity(row) -> tuple[str, str, str]:
    return _fold(row["applies_to"]), _fold(row["field"]), _fold(row["condition_text"])


def _key_of(standard: str, identity: tuple[str, str, str], place: int) -> str:
    parts = [_fold(standard), *identity, str(place)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _proved(row, pages: dict[int, str]) -> tuple[str | None, str | None]:
    """(quote hash, None), or (None, why it is dropped)."""
    quote = " ".join((row["quote"] or "").split())
    digest = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    if row["quote_sha256"] and row["quote_sha256"] != digest:
        return None, "quote_hash_differs"
    if not quote_verified(quote, pages.get(row["page"])):
        return None, "quote_not_on_page"
    if not (row["model"] or "").strip():
        return None, "model_not_recorded"
    return digest, None


def _source(row, digest: str) -> dict:
    return {
        "standard_document_id": row["standard_document_id"],
        "edition": row["edition"],
        "clause": row["clause"],
        "page": row["page"],
        "quote": " ".join(row["quote"].split()),
        "quote_sha256": digest,
        "quote_start": row["quote_start"],
        "quote_end": row["quote_end"],
        "page_source": row["page_source"],
        "page_min_conf": row["page_min_conf"],
        "text_sha256": row["text_sha256"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "batch_id": row["batch_id"],
        "compile_run_id": row["run_id"],
    }


def _readings(rows, standard: str, pages) -> tuple[list[tuple], Counter]:
    """(compiled row id, reading) for the rows that pass, each with its key. The same reading twice in one compile is
    one reading."""
    dropped, readings, places, seen = Counter(), [], Counter(), set()
    for row in rows:
        digest, why = _proved(row, pages)
        if why:
            dropped[why] += 1
            continue
        requirement = requirement_of(row)
        applicability = _applicability(row)
        exception = " ".join((row["exception_text"] or "").split())
        exceptions = (exception,) if exception else ()
        content = rulebook_v2.content_hash_of(
            requirement,
            row["strength"],
            row["sentence_strength"],
            row["context_flag"],
            applicability,
            exceptions,
            digest,
        )
        if content in seen:
            dropped["same_reading_twice"] += 1
            continue
        seen.add(content)
        identity = _identity(row)
        reading = Reading(
            rule_key=_key_of(standard, identity, places[identity]),
            standard=standard,
            requirement=requirement,
            strength=row["strength"],
            sentence_strength=row["sentence_strength"],
            context_flag=row["context_flag"],
            applicability=applicability,
            exceptions=exceptions,
            provenance=_source(row, digest),
        )
        readings.append((row["id"], reading))
        places[identity] += 1
    return readings, dropped


def ingest_latest(conn, document_id: str) -> dict:
    """The newest compile of one standard into the tables, one transaction, one snapshot. Run again it adds nothing."""
    rulebook_v2.require_on()
    rulebook_v2.ensure_schema(conn)
    run = report.latest_compile(conn, document_id)
    if run is None:
        return {"status": report.NOT_COMPILED, "boundary": BOUNDARY}
    rows = report.compiled_rows(conn, run["id"])
    readings, dropped = _readings(
        rows, run["standard"], report.pages_of(conn, document_id)
    )
    actor = _ACTOR_PREFIX + run["prompt_version"]
    with conn:
        written = Counter()
        for row_id, reading in readings:
            what, version_id = rulebook_v2.append_reading(conn, reading, actor)
            written[what] += 1
            rulebook_v2.link_compiled_row(conn, run["id"], row_id, version_id)
        counts = {
            "compiled_rows": len(rows),
            "written": dict(sorted(written.items())),
            "dropped": dict(sorted(dropped.items())),
            "compile_status": run["status"],
            "proof_proposed": int(run["counts"].get("proposed") or 0),
            "proof_dropped": run["counts"].get("dropped") or {},
        }
        snapshot = rulebook_v2.take_snapshot(
            conn, run["id"], document_id, counts, actor, standard=run["standard"]
        )
    return {**counts, "snapshot_id": snapshot, "boundary": BOUNDARY}


def after_compile(conn, document_id: str) -> None:
    """The seam: the compiler's one line after it stores a run. Off: nothing, not even a table."""
    if settings.rulebook_v2_enabled:
        ingest_latest(conn, document_id)


def report_row(conn, document_id: str) -> dict:
    """Counts for the version-1-beside-version-2 table. Off: nothing, so that table is what it was."""
    if not settings.rulebook_v2_enabled:
        return {}
    if not rulebook_v2.has_schema(conn):
        return {"tables": "not created"}
    pages = report.pages_of(conn, document_id)
    sources = conn.execute(
        "SELECT quote, page FROM rulebook_provenance WHERE standard_document_id = ?",
        (document_id,),
    ).fetchall()
    versions = conn.execute(
        "SELECT DISTINCT v.id, v.rule_id, v.kind, v.value FROM rulebook_version v"
        " JOIN rulebook_provenance p ON p.rule_version_id = v.id WHERE p.standard_document_id = ?",
        (document_id,),
    ).fetchall()
    ids = [v[0] for v in versions]
    marks = ",".join("?" for _ in ids)
    applicability = conn.execute(
        f"SELECT key_type, rule_version_id FROM rulebook_applicability WHERE rule_version_id IN ({marks})",
        ids,
    ).fetchall()
    exceptions = conn.execute(
        f"SELECT COUNT(*) FROM rulebook_exception WHERE rule_version_id IN ({marks})",
        ids,
    ).fetchone()[0]
    snapshot = conn.execute(
        "SELECT counts_json, rules_total, rules_in_force FROM rulebook_snapshot"
        " WHERE standard_document_id = ? ORDER BY rowid DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    return {
        "boundary": BOUNDARY,
        "rules": len({v[1] for v in versions}),
        "versions": len(versions),
        "by_kind": dict(sorted(Counter(v[2] for v in versions).items())),
        "with_single_figure": sum(1 for v in versions if v[3] is not None),
        "applicability_rows": len(applicability),
        "applicability_by_type": dict(
            sorted(Counter(r[0] for r in applicability).items())
        ),
        "versions_with_applicability": len({r[1] for r in applicability}),
        "exception_rows": exceptions,
        "sources": len(sources),
        "sources_quote_verified": sum(
            1 for s in sources if quote_verified(s[0], pages.get(s[1]))
        ),
        "versions_approved": sum(
            1 for i in ids if rulebook_v2.approval_in_force(conn, i)
        ),
        "book_rules_in_last_snapshot": snapshot[1] if snapshot else 0,
        "book_rules_in_force_in_last_snapshot": snapshot[2] if snapshot else 0,
        "last_ingest": json.loads(snapshot[0]) if snapshot else {},
    }
