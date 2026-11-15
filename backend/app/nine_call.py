"""THE ONE CALL SEAM of the nine-role review (owner order, 15 Nov 2026; SPEC sections B and F; strict by construction after review R63).

Every model call of roles 1 to 6 and 9 is made by `ask(...)` and by nothing else. Nothing a caller hands in is trusted as TEXT:

* THE ENGINE IS DERIVED FROM THE RUN. `ask` reads the run's own stored decision (`review_engine.bar_state`, the context bar): a run whose
  plan kept the AI review on this computer is Local, whatever context the caller is in. A caller may ask for Local, never for Claude
  over a Local run (`run_is_local`).
* QUESTION AND SYSTEM WORDS ARE TEMPLATES, never free strings: `template(id, text, **params)` registers fixed words with named
  parameters of four kinds (`id`, `int`, `token`, `role`: ids, counts, short tokens with no newline); `ask(system=(id, params),
  question=(id, params))`. A value that is not of its kind is refused (`text_not_from_block`). The template id and a digest of the
  parameters are written in the call's record row.
* TEXT BLOCKS ARE LOADED BY THE SEAM. A stored-text block names `(document_id, pages[, char_from, char_to])`; the seam reads the stored
  page text itself (`agent_review_standards.read_book`: the pages, and the recognised text of a scanned page) and slices it. A caller
  cannot put other words under a document's id. A picture block names `(document_id, one page)` and is rendered by the seam
  (`agent_review_pages.page_image`).
* A DERIVED block (the fact-sheet digest, the context note, earlier findings) is the kind `review_record`: it names `sources`, every
  document any of its words came from, and carries `items`, rows of short tokens that code renders. The gate must pass for EVERY
  source, else the block is dropped and named. Each source gets a read row (kind `review_record`, the block name as its chapter).
  What code CAN enforce: sources present, every source gated, tokens short and one-line, total length capped. What stays a builder
  obligation: that the tokens really come from those sources; `scripts/nine_record_check.py` verifies the rows afterwards.

The SAME block list is (a) the request, (b) the declaration to the approval gate (`claude_approved.carrying`), and (c) the role record
(`nine_record`: one read row per block, one per source of a derived block). The `sent` row is written by a transport wrapper only AFTER
the spend reservation succeeded, so a call refused at the reservation has no read rows.

A HELD DOCUMENT NEVER REACHES A BODY: each document (and each source) is put to the one gate (`claude_approved.refusal` inside the
run): not on the stored list, not approved, blocked (the register), a contract without the explicit choice, or a barred run. A refused
block is dropped before the request is built and named in `Answer.not_sent`; none left = the call is `refused`, no body, no ledger line.

MONEY. One step name per role (`nine_contract.STEP_OF_ROLE`): its own ledger line and USD 5 cap in `claude_spend`, which is NOT changed.
A role's design budget (`ROLE_BUDGET_USD`, not a cap) counts known costs and, for a failed call of unknown cost, the reserved amount.

Claude goes through `agent_claude._call` (-> `reader_transport`): no other socket. Local goes through the injected `local_send` or
`model_transport`: a call row with the cost NULL and no ledger line. Nothing here logs document text; a failure is a code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from . import agent_claude, claude_approved, claude_spend, nine_record
from .claude_image_tokens import json_counts
from .db import connect
from .nine_contract import ROLE_NAMES, STEP_OF_ROLE, ReadEntry

log = logging.getLogger(__name__)

#: design budgets per role (SPEC F.2): not a cap, under the USD 5 step cap; the run cap is the backstop
ROLE_BUDGET_USD: dict[int, float] = {
    1: 0.50,
    2: 1.00,
    3: 0.25,
    4: 4.00,
    5: 2.00,
    6: 3.00,
    9: 0.50,
}
DEFAULT_MODEL: dict[int, str] = {6: agent_claude.SECOND_MODEL}
DEFAULT_MAX_TOKENS = 2048
STORED_KINDS = ("paper", "rule_book", "project_document", "earlier_revision")
DERIVED_KIND = "review_record"
MAX_DERIVED_CHARS = 30_000  # a derived block is a digest, not a copy
MAX_TOKEN_CHARS = 60
MAX_TEMPLATE_CHARS = 20_000
TEXT_NOT_FROM_BLOCK = "text_not_from_block"

_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_TOKEN = re.compile(r"^[^\s\x00-\x1f][^\x00-\x1f]{0,%d}$" % (MAX_TOKEN_CHARS - 1))
_ROLE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class NineCallError(ValueError):
    """A wrong use of the seam: a programming error, never a document fact."""


class TemplateError(NineCallError):
    """A template parameter that is not an id, a count, a short token or a role name (`text_not_from_block`)."""

    code = TEXT_NOT_FROM_BLOCK


# --------------------------------------------------------------------------------------------------------- templates

_TEMPLATES: dict[str, tuple[str, dict[str, str]]] = {}
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def template(template_id: str, text: str, **params: str) -> str:
    """Register the FIXED words of a question or system prompt. `params` maps each `{name}` placeholder of `text` to its kind: `id`
    (letters, digits, `_ . : -`, 64 at most), `int` (a count), `token` (one line, 60 characters at most) or `role` (a lower-case name).
    Called by a role module at import. The same id with other words is refused. Returns the id."""
    if not _ID.match(template_id) or len(text) > MAX_TEMPLATE_CHARS:
        raise NineCallError(
            "a template has an id of letters and digits and words under 20,000 characters"
        )
    names = set(_PLACEHOLDER.findall(text))
    if names != set(params) or any(
        k not in ("id", "int", "token", "role") for k in params.values()
    ):
        raise NineCallError(
            "a template names exactly its parameters, each an id, int, token or role"
        )
    known = _TEMPLATES.get(template_id)
    if known is not None and known != (text, dict(params)):
        raise NineCallError(f"template {template_id!r} already holds other words")
    _TEMPLATES[template_id] = (text, dict(params))
    return template_id


def _check_param(kind: str, value) -> str:
    if kind == "int":
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 10**9
        ):
            raise TemplateError("an int parameter is a count")
        return str(value)
    text = value if isinstance(value, str) else ""
    ok = (
        (kind == "id" and _ID.match(text))
        or (kind == "role" and _ROLE.match(text))
        or (kind == "token" and _TOKEN.match(text))
    )
    if not ok:
        raise TemplateError(f"a {kind} parameter is not from the app's own words")
    return text


def render(use: tuple[str, dict]) -> tuple[str, str, str]:
    """(id, the words, the digest of id + parameters) of one template use. Raises `TemplateError` for any value that is not of its kind."""
    template_id, params = use
    if template_id not in _TEMPLATES:
        raise TemplateError("an unknown template")
    text, kinds = _TEMPLATES[template_id]
    if set(params) != set(kinds):
        raise TemplateError("a template use gives exactly its parameters")
    values = {k: _check_param(kinds[k], params[k]) for k in kinds}
    digest = hashlib.sha256(
        json.dumps([template_id, values], sort_keys=True).encode("utf-8")
    ).hexdigest()
    return template_id, text.format(**values), digest


# ------------------------------------------------------------------------------------------------------------ blocks


@dataclass(frozen=True)
class Block:
    """One block of a request. A STORED-TEXT block names where its words are stored (the seam loads them); a picture block names one page;
    a DERIVED block (`review_record`) names its sources and carries rows of short tokens. Nothing here is free text."""

    document_kind: str
    document_id: str = (
        ""  # stored-text and picture blocks; derived blocks name `sources` instead
    )
    pages: tuple[int, ...] = ()
    char_from: int | None = (
        None  # offsets into the joined text of `pages` (a chapter part)
    )
    char_to: int | None = None
    picture: bool = False  # one page, rendered by the seam (Claude only)
    chapter_id: str | None = None
    part_no: int | None = None
    part_of: int | None = None
    cache: bool = False
    # derived
    name: str = ""
    sources: tuple[str, ...] = ()
    items: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.document_kind in STORED_KINDS:
            if not self.document_id or not self.pages or self.items or self.sources:
                raise NineCallError(
                    "a stored-text block names a document and its pages, and nothing derived"
                )
            if self.picture and len(self.pages) != 1:
                raise NineCallError("a picture block names one page")
        elif self.document_kind == DERIVED_KIND:
            if (
                not _ID.match(self.name)
                or not self.sources
                or not self.items
                or self.document_id
                or self.picture
            ):
                raise NineCallError(
                    "a derived block has a name, its source documents and rows of tokens"
                )
            for row in self.items:
                if not row or any(
                    not isinstance(c, str) or not _TOKEN.match(c) for c in row
                ):
                    raise TemplateError("a derived row holds short one-line tokens")
            if sum(len(c) + 3 for row in self.items for c in row) > MAX_DERIVED_CHARS:
                raise TemplateError("a derived block is a digest, not a copy")
        else:
            raise NineCallError(f"unknown block kind {self.document_kind!r}")

    def gate_ids(self) -> tuple[str, ...]:
        return (
            tuple(self.sources)
            if self.document_kind == DERIVED_KIND
            else (self.document_id,)
        )


@dataclass(frozen=True)
class RoleGate:
    """A role's design budget. `fits(worst)` is asked before every call; the role's own spend comes from the record."""

    role_no: int
    budget_usd: float

    @classmethod
    def for_role(cls, role_no: int, budget_usd: float | None = None) -> RoleGate:
        return cls(
            role_no,
            ROLE_BUDGET_USD[role_no] if budget_usd is None else float(budget_usd),
        )

    def fits(self, run_id: str, worst_usd: float, conn=None) -> bool:
        return (
            nine_record.role_spend(run_id, self.role_no, conn) + float(worst_usd)
            <= self.budget_usd
        )


@dataclass(frozen=True)
class Answer:
    ok: bool
    call_id: str
    role_no: int
    #: answered | failed | refused (a call that never left, or was stopped by a gate) | reused
    state: str
    error_code: str | None
    text: (
        str | None
    )  # the model's words, for the caller to parse; never stored by this module
    data: dict | None  # the first JSON object in the text, or None
    usd: float | None  # None on the local model and for a call that did not happen
    model: str | None
    engine: str  # derived from the run
    kept: tuple[str, ...]  # document ids whose blocks were sent
    not_sent: tuple[
        tuple[str, str], ...
    ]  # (document id, code): blocks dropped before the request was built
    reads: tuple[ReadEntry, ...] = field(default=())


# ------------------------------------------------------------------------------------------------------- the engine


def engine_of_run(run_id: str, conn=None) -> str:
    """ "local" for a run whose stored decision keeps Claude out (`review_engine.bar_state`, and the context bar), else "claude". A run
    with no stored decision and no job (a test) follows the context bar alone."""
    from . import review_engine

    conn = conn or connect()
    if review_engine.claude_barred():
        return "local"
    job = conn.execute(
        "SELECT id FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if job is not None:
        barred, _why = review_engine.bar_state(conn, job["id"])
        if barred:
            return "local"
    elif (stored := review_engine.stored(conn, run_id)) is not None and stored[
        "bar_claude"
    ]:
        return "local"
    return "claude"


# ------------------------------------------------------------------------------------------------------ the gate


def _dropped(run_id: str, blocks: list[Block]) -> dict[str, str]:
    """{document id: code} for each document (and each source of a derived block) the one gate refuses in this run."""
    out: dict[str, str] = {}
    for doc in dict.fromkeys(i for b in blocks for i in b.gate_ids()):
        with claude_approved.carrying([doc]), claude_approved.reviewing(run_id):
            found = claude_approved.refusal()
        if found is not None:
            out[doc] = found[0]
    return out


# ------------------------------------------------------------------------------------------------------- loading


@dataclass(frozen=True)
class Loaded:
    block: Block
    text: str | None = None
    picture: dict | None = None  # {"media_type", "data"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _derived_text(b: Block) -> str:
    return "\n".join(" | ".join(row) for row in b.items)


def _load(
    conn, blocks: list[Block], engine: str
) -> tuple[list[Loaded], dict[str, str]]:
    """Read the words and pictures each block names, from the stored pages. A block whose pages are not stored is dropped and named."""
    from . import agent_review_pages, agent_review_standards

    books: dict[str, object] = {}
    out: list[Loaded] = []
    missing: dict[str, str] = {}
    for b in blocks:
        if b.document_kind == DERIVED_KIND:
            out.append(Loaded(b, text=_derived_text(b)))
            continue
        if b.picture:
            if engine != "claude":
                missing[b.document_id] = "picture_not_read_locally"
                continue
            try:
                ref = agent_review_pages.document_ref(conn, b.document_id)
                png = agent_review_pages.page_image(ref, b.pages[0])
                block = agent_review_pages.image_block({"png": png})
                out.append(
                    Loaded(
                        b,
                        picture={
                            "media_type": block["source"]["media_type"],
                            "data": block["source"]["data"],
                        },
                    )
                )
            except agent_review_pages.PageImageUnavailable as exc:
                missing[b.document_id] = "picture_" + str(exc)
            continue
        book = books.setdefault(
            b.document_id, agent_review_standards.read_book(conn, b.document_id)
        )
        pages = getattr(book, "pages", {})
        if any(p not in pages or not str(pages[p]).strip() for p in b.pages):
            missing[b.document_id] = "no_stored_text"
            continue
        text = "\n".join(pages[p] for p in sorted(b.pages))
        if b.char_from is not None or b.char_to is not None:
            text = text[
                b.char_from or 0 : b.char_to if b.char_to is not None else len(text)
            ]
        if not text.strip():
            missing[b.document_id] = "no_stored_text"
            continue
        out.append(Loaded(b, text=text))
    return out, missing


# ------------------------------------------------------------------------------------------------------- the request


def _label(n: int, b: Block) -> str:
    """Words from the block's own metadata (never a file name or a title): which kind of document, which pages."""
    if b.document_kind == DERIVED_KIND:
        return f"[derived block {n}: {b.name}]"
    pages = ""
    if b.pages:
        pages = (
            f", page {b.pages[0]}"
            if len(b.pages) == 1
            else f", pages {b.pages[0]} to {b.pages[-1]}"
        )
    chap = f", chapter {b.chapter_id}" if b.chapter_id else ""
    part = f", part {b.part_no} of {b.part_of}" if b.part_no and b.part_of else ""
    return (
        f"[document block {n}: {b.document_kind.replace('_', ' ')}{pages}{chap}{part}]"
    )


def _content(loaded: list[Loaded], question: str) -> list[dict]:
    """The message content, serialised FROM the loaded blocks, in order, then the question. One function: a block cannot enter a request
    without being in `loaded`, and the read rows are derived from the same list."""
    out: list[dict] = []
    for n, item in enumerate(loaded, 1):
        out.append({"type": "text", "text": _label(n, item.block)})
        if item.text is not None:
            block: dict = {"type": "text", "text": item.text}
            if item.block.cache:
                block["cache_control"] = dict(agent_claude._CACHE)
            out.append(block)
        if item.picture is not None:
            out.append({"type": "image", "source": {"type": "base64", **item.picture}})
    out.append({"type": "text", "text": question})
    return out


def _reads(role_no: int, call_id: str, loaded: list[Loaded]) -> list[ReadEntry]:
    rows: list[ReadEntry] = []
    for item in loaded:
        b = item.block
        text = item.text or ""
        common = dict(
            role_no=role_no,
            call_id=call_id,
            chars=len(text),
            text_sha256=_sha(text),
            pictures=1 if item.picture else 0,
        )
        if (
            b.document_kind == DERIVED_KIND
        ):  # one row per source: the gate and the checker see every document the words came from
            rows += [
                ReadEntry(
                    document_id=s,
                    document_kind=DERIVED_KIND,
                    pages=(),
                    chapter_id=b.name,
                    part_no=None,
                    part_of=None,
                    **common,
                )  # type: ignore[arg-type]
                for s in b.sources
            ]
        else:
            rows.append(
                ReadEntry(
                    document_id=b.document_id,
                    document_kind=b.document_kind,
                    pages=tuple(b.pages),
                    chapter_id=b.chapter_id,  # type: ignore[arg-type]
                    part_no=b.part_no,
                    part_of=b.part_of,
                    **common,
                )
            )
    return rows


def _json_of(text: str) -> dict | None:
    return agent_claude.parse_json_object(text)


# --------------------------------------------------------------------------------------------------------------- ask


def ask(
    run_id: str,
    role_no: int,
    blocks: list[Block],
    question: tuple[str, dict],
    *,
    system: tuple[str, dict] | None = None,
    engine: str | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    send: Callable | None = None,
    local_send: Callable[[dict], dict] | None = None,
    env: dict | None = None,
    meter: agent_claude.SpendMeter | None = None,
    gate: RoleGate | None = None,
    call_id: str | None = None,
    conn=None,
) -> Answer:
    """Make ONE model call of a nine-role request and record it. `engine` is DERIVED from the run; a caller may ask for "local" but never
    for Claude over a Local run. Never raises for a refusal or a failed call: the answer says which (`state`, `error_code`) and what was
    left out (`not_sent`); a wrong use (including a text that is not from a template or a block) raises `NineCallError`."""
    conn = conn or connect()
    if role_no not in ROLE_NAMES:
        raise NineCallError(f"no role {role_no!r}")
    if role_no not in STEP_OF_ROLE:
        raise NineCallError(f"role {role_no} is code: it makes no model call")
    if not blocks:
        raise NineCallError("a request holds at least one block")
    question_id, question_text, q_digest = render(question)
    system_id, system_text, s_digest = render(system) if system else (None, None, "")
    params_sha = _sha(q_digest + s_digest)
    nine_record.ensure_schema(conn)
    step = STEP_OF_ROLE[role_no]
    derived = engine_of_run(run_id, conn)
    wanted = engine or derived
    if wanted not in ("claude", "local"):
        raise NineCallError("a model call is on Claude or on the local model")
    call_id = call_id or uuid.uuid4().hex[:16]
    model = (
        model
        or DEFAULT_MODEL.get(role_no)
        or (agent_claude.LEAD_MODEL if wanted == "claude" else _local_model())
    )
    gate = gate or RoleGate.for_role(role_no)

    def refused(code: str, kept=(), dropped=()) -> Answer:
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine=wanted,
            model=model,
            error_code=code,
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            code,
            None,
            None,
            None,
            model,
            wanted,
            kept,
            tuple(dropped),
        )

    if wanted == "claude" and derived == "local":
        return refused(
            "run_is_local"
        )  # this run's plan keeps Claude out: a caller cannot choose it

    not_sent: dict[str, str] = _dropped(run_id, blocks) if wanted == "claude" else {}
    gated = [b for b in blocks if not any(i in not_sent for i in b.gate_ids())]
    loaded, missing = _load(conn, gated, wanted)
    not_sent.update(missing)
    dropped = tuple(sorted(not_sent.items()))
    if not loaded:
        return refused("no_block_left", dropped=dropped)

    content = _content(loaded, question_text)
    reads = _reads(role_no, call_id, loaded)
    kept_ids = tuple(dict.fromkeys(i for item in loaded for i in item.block.gate_ids()))
    parts: dict = {"messages": [{"role": "user", "content": content}]}
    if system_text:
        parts["system"] = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": dict(agent_claude._CACHE),
            }
        ]
    meta = dict(question_id=question_id, system_id=system_id, params_sha256=params_sha)
    if wanted == "claude":
        return _ask_claude(
            run_id,
            role_no,
            call_id,
            step,
            model,
            max_tokens,
            parts,
            reads,
            kept_ids,
            dropped,
            send,
            env,
            meter,
            gate,
            conn,
            meta,
        )
    return _ask_local(
        run_id,
        role_no,
        call_id,
        step,
        model,
        max_tokens,
        parts,
        reads,
        kept_ids,
        dropped,
        local_send,
        conn,
        meta,
    )


def _ask_claude(
    run_id,
    role_no,
    call_id,
    step,
    model,
    max_tokens,
    parts,
    reads,
    kept_ids,
    dropped,
    send,
    env,
    meter,
    gate,
    conn,
    meta,
) -> Answer:
    chars, images = json_counts(parts.get(k) for k in ("messages", "system"))
    worst = claude_spend.worst_case_usd(
        model, chars, int(max_tokens), image_tokens=images
    )
    if not gate.fits(run_id, worst, conn):
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            error_code="role_budget",
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            "role_budget",
            None,
            None,
            None,
            model,
            "claude",
            kept_ids,
            dropped,
        )
    written = {"sent": False}
    try:
        raw = agent_claude._transport(send)
    except agent_claude.AgentGateClosed as exc:
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            error_code=exc.code,
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            exc.code,
            None,
            None,
            None,
            model,
            "claude",
            kept_ids,
            dropped,
        )

    def wrapped(url, *, headers, body, timeout):
        # reached only AFTER the spend reservation succeeded (claude_spend.metered reserves first): the rows are written now, from the
        # blocks, with the digest of the finished body, just before it leaves
        nine_record.call_sent(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            request_sha256=agent_claude.request_digest(body),
            reads=reads,
            conn=conn,
            **meta,
        )
        written["sent"] = True
        return raw(url, headers=headers, body=body, timeout=timeout)

    try:
        with (
            claude_approved.carrying(kept_ids),
            claude_approved.reviewing(run_id),
            claude_spend.for_run(run_id),
        ):
            answer, usd = agent_claude._call(
                model, parts, max_tokens, wrapped, env, meter, step=step
            )
    except agent_claude.AgentBadReply as exc:
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            written,
            "failed",
            exc.code,
            getattr(exc, "usd", None),
            worst,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
        )
    except (agent_claude.AgentBudgetStop, agent_claude.AgentGateClosed) as exc:
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            written,
            "refused",
            exc.code,
            None,
            None,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
        )
    except agent_claude.AgentTransportError as exc:
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            written,
            "failed",
            exc.code,
            None,
            worst,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
        )
    text = "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    return _finish(
        run_id,
        role_no,
        call_id,
        conn,
        written,
        "answered",
        None,
        usd,
        None,
        agent_claude._answered_model(answer),
        kept_ids,
        dropped,
        reads,
        step,
        meta,
        text=text,
    )


def _ask_local(
    run_id,
    role_no,
    call_id,
    step,
    model,
    max_tokens,
    parts,
    reads,
    kept_ids,
    dropped,
    local_send,
    conn,
    meta,
) -> Answer:
    digest = _sha(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str))
    nine_record.call_sent(
        run_id,
        role_no,
        call_id,
        step=step,
        engine="local",
        model=model,
        request_sha256=digest,
        reads=reads,
        conn=conn,
        **meta,
    )
    sender = local_send or _ollama_send
    try:
        got = sender({"model": model, "max_tokens": int(max_tokens), **parts})
    except Exception as exc:  # noqa: BLE001 - a code only: the text of an error may carry document words
        log.warning("nine local call failed (%s)", type(exc).__name__)
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            {"sent": True},
            "failed",
            "local_" + type(exc).__name__,
            None,
            None,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
            engine="local",
        )
    text = str((got or {}).get("text") or "")
    return _finish(
        run_id,
        role_no,
        call_id,
        conn,
        {"sent": True},
        "answered",
        None,
        None,
        None,
        str((got or {}).get("model") or model),
        kept_ids,
        dropped,
        reads,
        step,
        meta,
        text=text,
        engine="local",
    )


def _finish(
    run_id,
    role_no,
    call_id,
    conn,
    written,
    state,
    code,
    usd,
    reserved,
    model,
    kept_ids,
    dropped,
    reads,
    step,
    meta,
    *,
    text=None,
    engine="claude",
) -> Answer:
    ok = state == "answered"
    if written["sent"]:
        nine_record.call_end(
            run_id,
            call_id,
            state,
            error_code=code,
            usd=usd,
            usd_reserved=reserved if usd is None else None,
            model=model if ok else None,
            conn=conn,
        )
    else:  # it never reached the transport (the reservation or a gate refused it): a refused call with no read rows
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine=engine,
            model=model,
            error_code=code or state,
            conn=conn,
        )
        state = "refused"
    return Answer(
        ok,
        call_id,
        role_no,
        state,
        code,
        text if ok else None,
        _json_of(text or "") if ok else None,
        usd,
        model,
        engine,
        kept_ids,
        dropped,
        tuple(reads) if written["sent"] else (),
    )


def _local_model() -> str:
    from . import agent_local_lead

    return agent_local_lead.DEFAULT_MODEL


def _ollama_send(parts: dict) -> dict:
    """The local lane: the ONE local socket, `model_transport`. The system words and the user content are plain text (no pictures)."""
    from . import model_transport

    system = "".join(str(s.get("text") or "") for s in parts.get("system") or [])
    user = "\n\n".join(
        str(c.get("text") or "")
        for m in parts["messages"]
        for c in m["content"]
        if isinstance(c, dict) and c.get("type") == "text"
    )
    body = {
        "model": parts["model"],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": int(parts["max_tokens"])},
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": "user", "content": user}],
    }
    answer = model_transport.post_json_retrying("/api/chat", body, timeout=300.0)
    msg = answer.get("message") if isinstance(answer, dict) else None
    return {
        "text": (msg or {}).get("content") or "",
        "model": (answer or {}).get("model") or parts["model"],
    }


def record_reused(
    run_id: str,
    role_no: int,
    blocks: list[Block],
    request_sha256: str,
    *,
    engine: str = "claude",
    model: str | None = None,
    conn=None,
) -> str:
    """A role that finds a stored answer of the SAME request (a restart) does not call again: it records the call as `reused` (the
    request digest and the blocks it read, no cost, no ledger line) and returns the call id. Never paid twice."""
    conn = conn or connect()
    if role_no not in STEP_OF_ROLE:
        raise NineCallError(f"role {role_no} is code: it makes no model call")
    call_id = uuid.uuid4().hex[:16]
    loaded, _missing = _load(conn, list(blocks), engine)
    nine_record.call_sent(
        run_id,
        role_no,
        call_id,
        step=STEP_OF_ROLE[role_no],
        engine=engine,
        model=model or agent_claude.LEAD_MODEL,
        request_sha256=request_sha256,
        reads=_reads(role_no, call_id, loaded),
        conn=conn,
    )
    nine_record.call_end(run_id, call_id, "reused", usd=None, conn=conn)
    return call_id


# ------------------------------------------------------------------------------------------------------ for the tests


class FakeTransport:
    """A Messages transport that answers from a queue and keeps the bodies it was handed (tests only: no network, no key).
    `answers` are strings (the model's words) or dicts (the whole reply). `ENV` opens the lane for it."""

    ENV = {
        "REASONING_PROVIDER": "claude",
        "AGENT_REVIEW_ENGINE": "claude",
        "STANDARDS_READER_ENABLED": "1",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
        "ANTHROPIC_API_KEY": "test-key-not-real",
    }
    USAGE = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    def __init__(
        self,
        answers=("{}",),
        usage: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.answers = list(answers)
        self.usage = dict(usage or self.USAGE)
        self.raises = raises
        self.bodies: list[dict] = []

    def __call__(self, url, *, headers, body, timeout):  # noqa: ARG002
        self.bodies.append(json.loads(json.dumps(body, default=str)))
        if self.raises is not None:
            raise self.raises
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(item, dict):
            return item
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": str(item)}],
            "usage": dict(self.usage),
        }
