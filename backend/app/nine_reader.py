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

import hashlib
import json
import logging
import re
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


@dataclass
class ReadResult:
    sheet: FactSheet
    #: counts and codes only (the record's `produced_json` of role 1)
    produced: dict[str, Any] = field(default_factory=dict)
    #: "ran" / "ran_partly" / "not_run", with the plain reason when not "ran"
    state: str = "ran"
    why: str | None = None


def page_blocks(paper_id: str, page: int, picture: bool) -> list[nine_call.Block]:
    """The blocks of one page, BY REFERENCE: the seam loads the stored page text and renders the picture itself (Claude only). No text passes here."""
    blocks = [nine_call.Block("paper", paper_id, (page,))]
    if picture:
        blocks.append(nine_call.Block("paper", paper_id, (page,), picture=True))
    return blocks


_FORMS: dict[tuple[str, ...], str] = {}


class QuestionNotRegistered(LookupError):
    """A field group the app did not register at import (a field list that changed after the app started): the page says so; nothing is sent."""


def register_group(group: list[Field]) -> str:
    """Register the question of one field group (IMPORT time only: the registries are frozen when the app starts): the form reader's own prompt (the app's
    fixed words and the reference data's field lines; NO page text) under an id that names its words. The page number is its only parameter."""
    key = tuple(f.key for f in group)
    if key not in _FORMS:
        text = build_prompt(group, "", 0).rstrip()
        head = text[: -len("PAGE 0:")]
        assert text.endswith("PAGE 0:")
        words = head.replace("{", "{{").replace("}", "}}") + "PAGE {page}:\n"
        tid = (
            "nine_reader_form_" + hashlib.sha256(words.encode("utf-8")).hexdigest()[:16]
        )
        _FORMS[key] = nine_call.template(tid, words, page="int")
    return _FORMS[key]


def form_template(group: list[Field]) -> str:
    """The registered question of a field group; never registers (a run cannot add words to the app)."""
    try:
        return _FORMS[tuple(f.key for f in group)]
    except KeyError:
        raise QuestionNotRegistered from None


def _register_forms() -> None:
    """Every field group the Reader can ask, from the app's fixed field lists: one list per equipment-type key of the reference data (the mandatory
    table, the checklist table) and the generic one, cut into batches exactly as `batches` cuts them at run time."""
    rules = datasheet_checks.load_rules()
    types: list[str | None] = [
        None,
        *rules["mandatory"],
        *(rules.get("checklists") or {}),
    ]
    for t in dict.fromkeys(
        t for t in types if t is None or not t.startswith("_") or t == "_generic"
    ):
        for group in batches(field_list_for(t, rules)):
            register_group(group)


_register_forms()


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
    answered_keys: list[str] = field(
        default_factory=list
    )  # the field keys the model was ASKED and answered (an answer of "not on the page" included)
    shapes: list[str] = field(
        default_factory=list
    )  # the SHAPE of each reply the parser rejected (never content)
    retried: int = 0  # groups asked a second time because the first reply was malformed


def reply_shape(text: object) -> str:
    """The SHAPE of a reply the parser rejected, for the record: its length, the type of its first level and the key names there (only names of
    letters and underscores, at most six, each cut at 24 characters). NO prefix of the reply is kept: the first characters of a reply can be words of the
    paper, and no document word may reach the record or a log line. A reply that is not JSON at all is named `unreadable` (and its reason code logged)."""
    raw = str(text or "")
    kind, keys = "unreadable", ""
    try:
        body = json.loads(form_reader.unfenced_whole(raw))
    except (ValueError, TypeError) as exc:
        log.info(
            "nine reader: a malformed reply is not JSON (%s)", type(exc).__name__
        )  # the type name only, never a word of the reply
    else:
        kind = type(body).__name__
        if isinstance(body, dict):
            keys = ",".join(
                k[:24]
                for k in body
                if isinstance(k, str) and re.fullmatch(r"[A-Za-z_]+", k)
            )[:60]
    return f"{kind}; chars {len(raw)}; keys {keys or '-'}"


def _read_page(
    ask: Callable[..., nine_call.Answer],
    paper_id: str,
    page: int,
    text: str,
    picture: bool,
    fields: list[Field],
    rules: Mapping,
    dropped: Counter,
) -> _Page:
    out = _Page()
    # a group is asked whole when ANY of its fields' labels is printed on the page (the group's words are fixed and registered; a page that prints none of
    # them is read by code, not asked)
    groups = [
        g
        for g in batches(fields)
        if any(form_reader.label_on_page(f, text, dict(rules)) for f in g)
    ]
    out.asked = len(groups)
    out.unread = [f.key for g in groups for f in g]
    for group in groups:
        try:
            question = (form_template(group), {"page": page})
        except QuestionNotRegistered:
            out.errors.append("question_not_registered")
            continue
        for attempt in (
            1,
            2,
        ):  # a malformed reply is asked ONE more time (the first page of a datasheet is the most important one)
            answer = ask(page_blocks(paper_id, page, picture), question)
            held = [
                code
                for _doc, code in answer.not_sent
                if not code.startswith("picture_")
            ]  # a picture that could not be made is text only, not a held page
            if held or (answer.reads and not _sent_this_text(answer, paper_id, text)):
                out.not_sent = held[0] if held else "stored_text_differs"
                return out
            if answer.error_code == "role_budget":
                out.budget = True
                return out
            if not answer.ok or answer.text is None:
                break
            parsed, err = form_reader.parse_answer(answer.text, {f.key for f in group})
            if err is not form_reader.Reason.MODEL_MALFORMED:
                break
            out.shapes.append(reply_shape(answer.text))
            if attempt == 1:
                out.retried += 1
        if not answer.ok or answer.text is None:
            dropped[form_reader.Reason.MODEL_FAILED.value] += len(group)
            out.errors.append(answer.error_code or answer.state)
            continue
        if err is not None:
            dropped[err.value] += len(group)
            out.errors.append(err.value)
            continue
        out.facts.extend(_verified(parsed, group, text, page, rules, dropped))
        out.answered += 1
        out.unread = [k for k in out.unread if k not in {f.key for f in group}]
        out.answered_keys.extend(f.key for f in group)
        out.picture = (
            out.picture or sum(r.pictures for r in answer.reads) > 0
        )  # the picture counts only when the seam really sent it
    return out


def _sent_this_text(answer: nine_call.Answer, paper_id: str, text: str) -> bool:
    """What the seam really sent for the page is the text the quotes are checked against (its checksum is in the read row)."""
    want = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return any(
        r.document_id == paper_id and not r.pictures and r.text_sha256 == want
        for r in answer.reads
    )


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
    pictures: bool,
    fields: list[Field],
    rules: Mapping,
    dropped: Counter,
    deadline: float | None,
    local: bool,
    unread: dict[int, list[str]],
    asked: dict[int, list[str]],
    notes: dict[str, Any],
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
                    pictures and not local,
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
            if r.shapes:
                notes.setdefault("shapes", []).append(
                    f"p{page}: " + " / ".join(r.shapes)
                )
            notes["retried"] = notes.get("retried", 0) + r.retried
            facts.extend(r.facts)
            if r.unread and r.answered:
                unread[page] = r.unread
            if r.answered_keys:
                asked[page] = r.answered_keys
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
    pictures: bool = True,
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
    asked: dict[int, list[str]] = {}
    notes: dict[
        str, Any
    ] = {}  # malformed replies: their SHAPES (never content) and how many groups were asked a second time
    try:
        read, reads, stopped = _read_pages(
            ask,
            paper_id,
            pages,
            total,
            pictures,
            fields,
            rules,
            dropped,
            deadline,
            engine == "local",
            unread,
            asked,
            notes,
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
        **({"malformed_retried": notes["retried"]} if notes.get("retried") else {}),
        **(
            {"malformed_reply_shapes": " | ".join(notes["shapes"])[:200]}
            if notes.get("shapes")
            else {}
        ),
        "pages_with_picture": len(picture_pages),
        "conflicts": sheet.conflicts,
        "fields_not_read": {str(p): u for p, u in unread.items()},
        # the fields the model was asked about and answered, per page: a field is "not stated" only when it is here for a page that was read in full;
        # a field of a group nobody asked (the page prints none of its labels) is in neither list
        "fields_asked": {str(p): k for p, k in asked.items()},
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
    "page_blocks",
    "read_paper",
]
