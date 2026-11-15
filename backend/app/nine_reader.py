"""Role 1, the Reader: reads EVERY page of the paper (text, and for Claude the page picture too) and writes the paper's fact sheet (SPEC A, row 1).

  * the equipment type's FIXED field list (`form_reader_fields.field_list_for`, from the reference data; no layout is known here) is the question;
  * every request is made by the ONE call seam (`nine_call.ask`, role 1): one `Block` per page (its text, and on Claude its picture), the field list as
    the question. The seam gates what may leave, records the call and the read rows, and drops the pictures on the local model (nothing leaves there);
  * code decides what is kept: a value whose quote is not on the page (or whose value, label or unit fails `form_reader.verify`) is DROPPED and counted
    by reason; stored and read values are merged in `nine_facts.merge` (a disagreement is `conflict`, never used; a stale stored value is not used);
  * a page with no stored text is "not read" with the reason (recognised text counts as stored text when the caller passes it); a page whose block the
    gate held comes back in `Answer.not_sent` and is "not read: not sent", never "read"; the role's budget (`RoleGate`) ends the role "ran partly";
  * nothing is written to `submittal_facts`; the sheet goes to `nine_facts.store` per run.

No verdict, class or word is made here. Words and counts only; no document text is logged.
"""

from __future__ import annotations

import base64
import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import datasheet_checks, form_reader, nine_call, nine_facts
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
PICTURES_LOCAL = "pictures not read on Local"
NOT_SENT = "not read: not sent"
CODE_ONLY = "read by code: no field label found"
BUDGET = "not read: the Reader's budget was reached (role_budget)"

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
    document_id: str, page: int, text: str, picture: bytes | None = None
) -> nine_call.Block:
    """ONE block of one page, in the seam's shape (the same list is the request, the document declaration and the role record)."""
    pic = (
        {"media_type": "image/png", "data": base64.b64encode(picture).decode("ascii")}
        if picture
        else None
    )
    return nine_call.Block(document_id, "paper", (page,), text=text, picture=pic)


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


# ------------------------------------------------------------------ one page, through the seam


def _verified(
    parsed: Mapping[str, dict],
    group: list[Field],
    text: str,
    page: int,
    rules: Mapping,
    dropped: Counter,
) -> list[dict]:
    """The readings of one batch that code accepts. A value whose quote is not on the page, whose value is not in its quote, ... is dropped and counted."""
    out: list[dict] = []
    for f in group:
        item = parsed.get(f.key)
        if item is None:
            dropped[form_reader.Reason.FIELD_NOT_ANSWERED.value] += 1
        elif item["status"] == form_reader.NOT_ON_PAGE:
            continue
        elif item["status"] not in (FOUND, LEFT_BLANK):
            dropped[form_reader.Reason.STATUS_UNKNOWN.value] += 1
        else:
            if item["status"] == LEFT_BLANK:
                reason = form_reader.verify_blank(f, item, text, dict(rules))
            else:
                item = form_reader.reading_as_printed(item, text)
                reason = form_reader.verify(f, item, text, dict(rules))
            if reason is None:
                out.append(form_reader._fact(f, item, page))
            else:
                dropped[reason.value] += 1
    return out


@dataclass
class _Page:
    facts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    picture: bool = False
    not_sent: str | None = None
    budget: bool = False
    asked: int = 0
    answered: int = 0
    unread: list[str] = field(default_factory=list)  # the field keys no answer covered


def _read_page(
    ask: Callable[..., nine_call.Answer],
    paper_id: str,
    page: int,
    text: str,
    picture: bytes | None,
    fields: list[Field],
    rules: Mapping,
    dropped: Counter,
) -> _Page:
    out = _Page()
    groups = batches(
        [f for f in fields if form_reader.label_on_page(f, text, dict(rules))]
    )
    out.asked = len(groups)
    out.unread = [f.key for g in groups for f in g]
    for group in groups:
        answer = ask(
            [page_block(paper_id, page, text, picture)], build_prompt(group, "", page)
        )
        if answer.not_sent:
            out.not_sent = answer.not_sent[0][1]
            return out
        if answer.error_code == "role_budget":
            out.budget = True
            return out
        if not answer.ok or answer.text is None:
            dropped[form_reader.Reason.MODEL_FAILED.value] += len(group)
            out.errors.append(answer.error_code or answer.state)
            continue
        parsed, err = form_reader.parse_answer(answer.text, {f.key for f in group})
        if err is not None:
            dropped[err.value] += len(group)
            out.errors.append(err.value)
            continue
        out.facts.extend(_verified(parsed, group, text, page, rules, dropped))
        out.answered += 1
        out.unread = [k for k in out.unread if k not in {f.key for f in group}]
        out.picture = (
            out.picture or sum(r.pictures for r in answer.reads) > 0
        )  # the picture counts only when the seam really sent it
    return out


def _picture(picture_of: PictureOf | None, page: int) -> bytes | None:
    if picture_of is None:
        return None
    try:
        return picture_of(page)
    except Exception as exc:  # noqa: BLE001 - no picture for a page is "text only", never a failed review; only the class is logged
        log.info("nine reader: no picture for a page (%s)", type(exc).__name__)
        return None


def _page_read(page: int, r: _Page) -> PageRead:
    """What the page's record says. A page is read only when EVERY field group got a usable answer; a page nobody asked about is read by code, not by the
    model; a page stopped part of the way keeps the verified values of the groups that answered and says "read partly" (never read)."""
    if r.asked == 0:
        return PageRead(page, False, False, CODE_ONLY)
    why = f"{NOT_SENT} ({r.not_sent})" if r.not_sent else BUDGET if r.budget else None
    if r.answered == r.asked:
        return PageRead(page, True, r.picture, None)
    if r.answered == 0:
        return PageRead(
            page,
            False,
            False,
            why
            or f"not read: the model gave no usable answer ({r.errors[0] if r.errors else 'none'})",
        )
    stop = (why or f"no usable answer ({r.errors[0] if r.errors else 'none'})").replace(
        "not read: ", ""
    )
    return PageRead(
        page,
        False,
        r.picture,
        f"read partly: {r.answered} of {r.asked} field groups ({stop}); fields not read: {', '.join(r.unread)}",
    )


def _read_pages(
    ask: Callable[..., nine_call.Answer],
    paper_id: str,
    pages: Mapping[int, str],
    total: int,
    picture_of: PictureOf | None,
    fields: list[Field],
    rules: Mapping,
    dropped: Counter,
    deadline: float | None,
    local: bool,
    unread: dict[int, list[str]],
) -> tuple[list[dict], list[PageRead], str | None]:
    facts: list[dict] = []
    reads: list[PageRead] = []
    stopped: str | None = None
    for page in range(1, total + 1):
        text = pages.get(page, "")
        if not text.strip():
            reads.append(
                PageRead(page, False, False, NO_TEXT_LOCAL if local else NO_TEXT_CLAUDE)
            )
        elif stopped:
            reads.append(
                PageRead(
                    page,
                    False,
                    False,
                    BUDGET
                    if stopped == "role_budget"
                    else f"not read: a limit stopped the Reader ({stopped})",
                )
            )
        elif deadline is not None and time.monotonic() >= deadline:
            stopped = "time_budget"
            reads.append(
                PageRead(
                    page, False, False, "not read: the Reader's time budget ran out"
                )
            )
        else:
            try:
                r = _read_page(
                    ask,
                    paper_id,
                    page,
                    text,
                    None if local else _picture(picture_of, page),
                    fields,
                    rules,
                    dropped,
                )
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
            if r.budget:
                stopped = "role_budget"
            facts.extend(r.facts)
            if r.unread and r.answered:
                unread[page] = r.unread
            reads.append(_page_read(page, r))
    return facts, reads, stopped


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
    picture_of: PictureOf | None = None,
    model: str | None = None,
    rules: Mapping | None = None,
    max_seconds: float | None = None,
    gate: nine_call.RoleGate | None = None,
    **seam_kwargs: Any,
) -> ReadResult:
    """The whole paper, page by page, into one fact sheet. `engine` is the review's choice ("claude" or "local"); `seam_kwargs` go to `nine_call.ask`
    unchanged (`conn`, `meter`, and for tests `send`, `env`, `local_send`). Never raises into the review: a page that could not be read says why, and the
    role is "ran partly"."""
    rules = rules if rules is not None else datasheet_checks.load_rules()
    total = pages_total if pages_total is not None else max([*pages, 0])
    fields = field_list_for(equipment_type, dict(rules))
    dropped: Counter = Counter()
    deadline = time.monotonic() + max_seconds if max_seconds else None
    gate = gate or nine_call.RoleGate.for_role(ROLE_NO)

    def ask(blocks: list[nine_call.Block], question: str) -> nine_call.Answer:
        return nine_call.ask(
            run_id, ROLE_NO, blocks, question, engine=engine, gate=gate, **seam_kwargs
        )

    unread: dict[int, list[str]] = {}
    try:
        read, reads, stopped = _read_pages(
            ask,
            paper_id,
            pages,
            total,
            picture_of,
            fields,
            rules,
            dropped,
            deadline,
            engine == "local",
            unread,
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
    by_code = {r.page for r in reads if r.not_read_why == CODE_ONLY}
    readings = [{**f, "tag": f.get("tag")} for f in read]
    facts, counts = nine_facts.merge(
        stored_facts,
        readings,
        pages,
        picture_pages=picture_pages,
        model=model,
        tables=tables,
        rules=rules,
    )
    sheet = nine_facts.sheet_of(
        run_id, paper_id, total, reads, facts, engine, [model] if model else []
    )
    not_read = {
        r.page: r.not_read_why
        for r in reads
        if not r.text_read and r.page not in by_code
    }
    produced: dict[str, Any] = {
        "facts": len(facts),
        "pages_read": sum(r.text_read for r in reads),
        "pages_read_by_code_only": len(by_code),
        "pages_with_picture": len(picture_pages),
        "conflicts": sheet.conflicts,
        "fields_not_read": {str(p): u for p, u in unread.items()},
        "pages_not_read": {str(p): w for p, w in not_read.items()},
        "dropped_by_reason": dict(sorted(dropped.items())),
        "dropped": sum(dropped.values()),
        "unverified_dropped": counts.get("unverified_dropped", 0),
        "stale_stored_values": counts.get("stale", 0),
        "stored_only": counts.get("rules_only", 0),
        "agreed": counts.get("agreed", 0),
    }
    if engine == "local":
        produced["pictures"] = PICTURES_LOCAL
    partly = bool(not_read) or bool(stopped)
    why = None
    if partly:
        why = (
            "; ".join(sorted({w for w in not_read.values() if w}))
            or f"a limit stopped the Reader ({stopped})"
        )
    return ReadResult(sheet, produced, "ran_partly" if partly else "ran", why)


def _not_run(
    run_id: str, paper_id: str, total: int, engine: Engine, why: str
) -> ReadResult:
    sheet = nine_facts.sheet_of(run_id, paper_id, total, [], [], engine, [])
    return ReadResult(
        sheet, {"facts": 0, "pages_read": 0, "reason": why}, "not_run", why
    )


__all__ = [
    "BUDGET",
    "NOT_SENT",
    "NO_TEXT_CLAUDE",
    "NO_TEXT_LOCAL",
    "PICTURES_LOCAL",
    "ROLE_NAMES",
    "STEP",
    "ReadResult",
    "estimate",
    "page_block",
    "read_paper",
]
