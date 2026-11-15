"""Role 1, the Reader: reads EVERY page of the paper (text, and for Claude the page picture too) and writes the paper's fact sheet (SPEC A, rows 1).

  * the equipment type's FIXED field list (`form_reader_fields.field_list_for`, from the reference data; no layout is known here) is the question;
  * Claude: one request per page batch, the page text and the page picture as BLOCKS handed to the one call seam (`ask`, B1's `nine_call.ask`); no
    other path out. Local: text only, through `form_reader.read_form` (the local model; nothing leaves). A page with no stored text on Local is
    "not read" with the reason; recognised text (`page_ocr`) counts as stored text when held;
  * code decides what is kept: a value whose quote is not on the page (or whose value, label or unit fails `form_reader.verify`) is DROPPED and
    counted by reason; stored and read values are merged in `nine_facts.merge` (a disagreement is `conflict`, never used; a stale stored value is not used);
  * nothing is written to `submittal_facts`; the sheet goes to `nine_facts.store` per run.

No verdict, class or word is made here. Words and counts only; no document text is logged.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import (
    datasheet_checks,
    form_reader,
    nine_facts,
)
from .claude_spend import StopRun
from .form_reader_fields import (
    FOUND,
    LEFT_BLANK,
    Field,
    batches,
    build_prompt,
    field_list_for,
)
from .nine_contract import ROLE_NAMES, STEP_OF_ROLE, Engine, FactSheet, PageRead

log = logging.getLogger(__name__)

ROLE_NO = 1
STEP = STEP_OF_ROLE[ROLE_NO]
NO_TEXT_LOCAL = "no stored text and pictures are not read on the local model"
NO_TEXT_CLAUDE = (
    "no stored text: a quote from a picture alone cannot be checked by code"
)
#: a page batch is asked once on Claude (the second run of the form reader is for the free local model)
CLAUDE_RUNS = 1


class Answer(Protocol):
    """What the call seam gives back for one request (B1's `nine_call.ask` result): the model's text, or none with why."""

    text: str | None
    state: str  # answered | failed | refused | reused
    error_code: str | None


#: `ask(role_no, blocks, question) -> Answer`. A block is `{document_id, document_kind, pages, chapter_id, part, text | picture}`.
Seam = Callable[[int, list[dict], str], Answer]
#: a page picture (PNG bytes) for a page number, or raises `agent_review_pages.PageImageUnavailable`
PictureOf = Callable[[int], bytes]


@dataclass
class ReadResult:
    sheet: FactSheet
    #: counts and codes only (the record's `produced_json` of role 1)
    produced: dict[str, Any] = field(default_factory=dict)
    #: "ran" / "ran_partly" / "not_run", with the plain reason when not "ran"
    state: str = "ran"
    why: str | None = None


def page_block(
    document_id: str, page: int, text: str | None = None, picture: bytes | None = None
) -> dict:
    """ONE block of one page, in the shape the seam serialises and records from (the same list is the request, the document declaration and the role record)."""
    block: dict[str, Any] = {
        "document_id": document_id,
        "document_kind": "paper",
        "pages": [page],
        "chapter_id": None,
        "part": None,
    }
    if text is not None:
        block["text"] = text
    if picture is not None:
        block["picture"] = picture
    return block


def estimate(
    pages: Mapping[int, str], pictures: Mapping[int, bytes] | None = None
) -> dict[str, int]:
    """Input tokens the Reader would send, for the dry run: the text by the cap estimator's own ratio (characters / 3), each picture by the app's
    IMAGE rule (`claude_image_tokens`, size from the PNG header, never the base64 length)."""
    from . import agent_review_pages

    return {
        "text_tokens": sum(len(t or "") for t in pages.values()) // 3,
        "picture_tokens": agent_review_pages.image_tokens(pictures or {}),
        "pages": len(pages),
        "pictures": len(pictures or {}),
    }


# ------------------------------------------------------------------ Claude: one page, through the seam


def _drop(counts: Counter, reason: str, n: int = 1) -> None:
    counts[reason] += n


def _claude_batch(
    seam: Seam,
    document_id: str,
    page: int,
    text: str,
    picture: bytes | None,
    group: list[Field],
    rules: Mapping,
    dropped: Counter,
) -> tuple[list[dict], str | None]:
    """(verified readings of one batch on one page, an error word). The question names the fields; the page goes as blocks."""
    blocks = [page_block(document_id, page, text=text)]
    if picture is not None:
        blocks.append(page_block(document_id, page, picture=picture))
    question = build_prompt(group, "", page)
    answer = seam(ROLE_NO, blocks, question)
    if answer.state not in ("answered", "reused") or answer.text is None:
        _drop(dropped, form_reader.Reason.MODEL_FAILED.value, len(group))
        return [], answer.error_code or answer.state
    keys = {f.key for f in group}
    parsed, err = form_reader.parse_answer(answer.text, keys)
    if err is not None:
        _drop(dropped, err.value, len(group))
        return [], err.value
    out: list[dict] = []
    for f in group:
        item = parsed.get(f.key)
        if item is None:
            _drop(dropped, form_reader.Reason.FIELD_NOT_ANSWERED.value)
            continue
        if item["status"] == form_reader.NOT_ON_PAGE:
            continue
        if item["status"] not in (FOUND, LEFT_BLANK):
            _drop(dropped, form_reader.Reason.STATUS_UNKNOWN.value)
            continue
        if item["status"] == LEFT_BLANK:
            reason = form_reader.verify_blank(f, item, text, dict(rules))
        else:
            item = form_reader.reading_as_printed(item, text)
            reason = form_reader.verify(f, item, text, dict(rules))
        if reason is not None:
            _drop(
                dropped, reason.value
            )  # the quote is not on the page, the value is not in the quote, ...: dropped and counted
            continue
        out.append(form_reader._fact(f, item, page))
    return out, None


def _read_claude(
    seam: Seam,
    document_id: str,
    pages: Mapping[int, str],
    picture_of: PictureOf | None,
    fields: list[Field],
    rules: Mapping,
    pages_total: int,
    dropped: Counter,
    deadline: float | None,
) -> tuple[list[dict], list[PageRead], str | None]:
    facts: list[dict] = []
    reads: list[PageRead] = []
    stopped: str | None = None
    for page in range(1, pages_total + 1):
        text = pages.get(page, "")
        if not text.strip():
            reads.append(PageRead(page, False, False, NO_TEXT_CLAUDE))
            continue
        if stopped:
            reads.append(
                PageRead(
                    page,
                    False,
                    False,
                    f"not read: a limit stopped the Reader ({stopped})",
                )
            )
            continue
        if deadline is not None and time.monotonic() >= deadline:
            stopped = "time_budget"
            reads.append(
                PageRead(
                    page, False, False, "not read: the Reader's time budget ran out"
                )
            )
            continue
        picture = _picture(picture_of, page)
        asked = [
            f for f in fields if form_reader.label_on_page(f, text, dict(rules))
        ] or []
        errors: list[str] = []
        got: list[dict] = []
        try:
            for group in batches(asked):
                one, err = _claude_batch(
                    seam, document_id, page, text, picture, group, rules, dropped
                )
                got.extend(one)
                if err:
                    errors.append(err)
        except StopRun as exc:
            stopped = exc.count_key
            reads.append(
                PageRead(
                    page,
                    False,
                    False,
                    f"not read: a limit stopped the Reader ({stopped})",
                )
            )
            continue
        facts.extend(got)
        failed = bool(errors) and len(errors) >= max(1, len(batches(asked)))
        reads.append(
            PageRead(
                page,
                not failed,
                picture is not None and not failed,
                f"not read: the model gave no usable answer ({errors[0]})"
                if failed
                else None,
            )
        )
    return facts, reads, stopped


def _picture(picture_of: PictureOf | None, page: int) -> bytes | None:
    if picture_of is None:
        return None
    try:
        return picture_of(page)
    except Exception as exc:  # noqa: BLE001 - no picture for a page is "text only", never a failed review; only the class is logged
        log.info("nine reader: no picture for a page (%s)", type(exc).__name__)
        return None


# ------------------------------------------------------------------ Local: text only, through the form reader


def _read_local(
    local_call: Callable[[str], str] | None,
    pages: Mapping[int, str],
    equipment_type: str | None,
    rules: Mapping,
    fields: list[Field],
    pages_total: int,
    dropped: Counter,
    max_seconds: float | None,
) -> tuple[list[dict], list[PageRead], str | None]:
    text_pages = {p: t for p, t in pages.items() if t.strip() and p <= pages_total}
    reading = form_reader.FormReading(fields=fields)
    if text_pages:
        call = local_call or _default_local()
        reading = form_reader.read_form(
            text_pages,
            equipment_type,
            call,
            rules=dict(rules),
            fields=fields,
            max_seconds=max_seconds,
        )
    for r in reading.rejected:
        _drop(dropped, r["reason"])
    reads: list[PageRead] = []
    for page in range(1, pages_total + 1):
        if page not in text_pages:
            reads.append(PageRead(page, False, False, NO_TEXT_LOCAL))
        elif page in reading.errors:
            reads.append(PageRead(page, False, False, reading.errors[page]))
        else:
            reads.append(PageRead(page, True, False, None))
    return list(reading.facts), reads, reading.stopped


def _default_local() -> Callable[[str], str]:
    from . import datasheet_ai

    call, why = datasheet_ai.model_call_for("ollama")
    if call is None:
        raise RuntimeError(why or "no local model")
    return call


# ------------------------------------------------------------------ the role


def read_paper(
    *,
    run_id: str,
    paper_id: str,
    pages: Mapping[int, str],
    stored_facts: Sequence[Mapping],
    engine: Engine,
    equipment_type: str | None = None,
    tables: Mapping[int, list] | None = None,
    pages_total: int | None = None,
    seam: Seam | None = None,
    picture_of: PictureOf | None = None,
    local_call: Callable[[str], str] | None = None,
    model: str | None = None,
    rules: Mapping | None = None,
    max_seconds: float | None = None,
) -> ReadResult:
    """The whole paper, page by page, into one fact sheet. `engine` is the review's choice ("claude" needs `seam`; "local" sends nothing).
    Never raises into the review: a page that could not be read says why, and the role is "ran partly"."""
    rules = rules if rules is not None else datasheet_checks.load_rules()
    total = pages_total if pages_total is not None else max([*pages, 0])
    fields = field_list_for(equipment_type, dict(rules))
    dropped: Counter = Counter()
    deadline = time.monotonic() + max_seconds if max_seconds else None
    if engine == "claude" and seam is None:
        return _not_run(run_id, paper_id, total, engine, "the call seam was not given")
    try:
        if engine == "claude":
            assert seam is not None
            read, reads, stopped = _read_claude(
                seam,
                paper_id,
                pages,
                picture_of,
                fields,
                rules,
                total,
                dropped,
                deadline,
            )
        else:
            read, reads, stopped = _read_local(
                local_call,
                pages,
                equipment_type,
                rules,
                fields,
                total,
                dropped,
                max_seconds,
            )
    except StopRun as exc:
        return _not_run(
            run_id,
            paper_id,
            total,
            engine,
            f"a limit stopped the Reader ({exc.count_key})",
        )
    except Exception as exc:  # noqa: BLE001 - a failing reader never fails the review; the role says it did not run and why
        log.warning("nine reader: did not run (%s)", type(exc).__name__)
        return _not_run(
            run_id,
            paper_id,
            total,
            engine,
            f"the reader did not run: an error ({type(exc).__name__})",
        )
    picture_pages = {r.page for r in reads if r.picture_read}
    facts, counts = nine_facts.merge(
        stored_facts,
        [_as_reading(f) for f in read],
        pages,
        read_source="ai_picture" if picture_pages else "ai_text",
        model=model,
        tables=tables,
        rules=rules,
    )
    sheet = nine_facts.sheet_of(
        run_id, paper_id, total, reads, facts, engine, [model] if model else []
    )
    not_read = {r.page: r.not_read_why for r in reads if not r.text_read}
    produced = {
        "facts": len(facts),
        "pages_read": sum(r.text_read for r in reads),
        "pages_with_picture": len(picture_pages),
        "conflicts": sheet.conflicts,
        "pages_not_read": {str(p): w for p, w in not_read.items()},
        "dropped_by_reason": dict(sorted(dropped.items())),
        "dropped": sum(dropped.values()),
        "stale_stored_values": counts.get("stale", 0),
        "stored_only": counts.get("rules_only", 0),
        "agreed": counts.get("agreed", 0),
    }
    partly = bool(not_read) or bool(stopped)
    why = None
    if partly:
        why = (
            "; ".join(sorted({w for w in not_read.values() if w}))
            or f"a limit stopped the Reader ({stopped})"
        )
    return ReadResult(sheet, produced, "ran_partly" if partly else "ran", why)


def _as_reading(f: Mapping) -> dict:
    """A form-reader fact as the merge reads it (`field`, `value`, `unit`, `quote`, `page`, `kind`)."""
    return {
        "field": f.get("field"),
        "value": f.get("value"),
        "unit": f.get("unit"),
        "quote": f.get("quote"),
        "page": f.get("page"),
        "kind": f.get("kind") or "offered",
        "tag": f.get("tag"),
    }


def _not_run(
    run_id: str, paper_id: str, total: int, engine: Engine, why: str
) -> ReadResult:
    sheet = nine_facts.sheet_of(run_id, paper_id, total, [], [], engine, [])
    return ReadResult(
        sheet, {"facts": 0, "pages_read": 0, "reason": why}, "not_run", why
    )


__all__ = [
    "NO_TEXT_CLAUDE",
    "NO_TEXT_LOCAL",
    "ROLE_NAMES",
    "STEP",
    "ReadResult",
    "estimate",
    "page_block",
    "read_paper",
]
