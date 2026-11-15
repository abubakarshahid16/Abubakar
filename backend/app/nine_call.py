"""THE ONE CALL SEAM of the nine-role review (owner order, 15 Nov 2026; SPEC sections B and F).

Every model call of roles 1 to 6 and 9 is made by `ask(...)` and by nothing else. A request is built from BLOCKS that carry their
origin (document id and kind, pages, chapter, part, text or picture). The SAME block list is

    (a) the request: the message content is serialised FROM the blocks, in order;
    (b) the approval declaration: `claude_approved.carrying(...)` is given exactly the documents of the blocks that were kept;
    (c) the role record: one read row per block (`nine_record.call_sent`), with the size and the checksum of the text that was sent.

So the record cannot say something else than what was sent. Written by code, in one function, before the body leaves.

A HELD DOCUMENT NEVER REACHES A BODY. Before the request is built each document is put to the one gate (`claude_approved.refusal`,
inside the run's context): not on the run's stored list (`review_shown`), not approved, blocked (the register), a contract without
the explicit choice, or a run barred from Claude: its blocks are DROPPED and named in `Answer.not_sent`; the call goes on with what is
left. No block left, or a run barred: the call is `refused`, no body, no ledger line.

MONEY. One step name per role (`nine_contract.STEP_OF_ROLE`): each role has its own ledger line and USD 5 cap in `claude_spend`, which
is NOT changed; the run cap stays. A role also has a design budget (`ROLE_BUDGET_USD`, under the step cap): a call that would pass it is
not made (`Answer.error_code == "role_budget"`) and the role says "ran partly".

ENGINES. Claude goes through `agent_claude._call` (-> `reader_transport`, metered by `claude_spend`): no other socket. Local goes through
the injected `local_send` or `model_transport`; it writes a call row with the cost NULL and no ledger line. Nothing here logs document
text; a failure is a code. Tests inject `send` (a Messages transport; `FakeTransport`) and `local_send`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from . import agent_claude, claude_approved, claude_spend, nine_record
from .claude_image_tokens import json_counts
from .db import connect
from .nine_contract import ROLE_NAMES, STEP_OF_ROLE, ReadEntry

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


class NineCallError(ValueError):
    """A wrong use of the seam (a role that cannot call a model, no blocks and no question): a programming error, never a document fact."""


@dataclass(frozen=True)
class Block:
    """One document block of a request. Ids and numbers describe it; `text` / `picture` are what is sent, unchanged."""

    document_id: str
    document_kind: (
        str  # paper | rule_book | project_document | earlier_revision | review_record
    )
    pages: tuple[int, ...] = ()
    text: str | None = None
    #: {"media_type": "image/png", "data": "<base64>"}: a page picture (Claude only; the local model reads no pictures)
    picture: dict | None = None
    chapter_id: str | None = None
    part_no: int | None = None
    part_of: int | None = None
    #: mark the end of a stable prefix for the prompt cache
    cache: bool = False

    def __post_init__(self) -> None:
        if self.text is None and self.picture is None:
            raise NineCallError("a block holds a text or a picture")
        if self.document_kind not in nine_record.KINDS:
            raise NineCallError(f"unknown document kind {self.document_kind!r}")


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
            nine_record.role_usd(run_id, self.role_no, conn) + float(worst_usd)
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
    kept: tuple[str, ...]  # document ids of the blocks that were sent
    not_sent: tuple[
        tuple[str, str], ...
    ]  # (document id, code): blocks dropped before the request was built
    reads: tuple[ReadEntry, ...] = field(default=())


# ---------------------------------------------------------------------------------------------------------- the gate


def _dropped(run_id: str, blocks: list[Block]) -> dict[str, str]:
    """{document id: code} for each document the one gate would refuse in this run. A run barred from Claude (Local only) refuses all."""
    out: dict[str, str] = {}
    for doc in dict.fromkeys(b.document_id for b in blocks):
        with claude_approved.carrying([doc]), claude_approved.reviewing(run_id):
            found = claude_approved.refusal()
        if found is not None:
            out[doc] = found[0]
    return out


# ------------------------------------------------------------------------------------------------------- the request


def _label(n: int, b: Block) -> str:
    """Words from the block's own metadata (never a file name or a title): which kind of document, which pages."""
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


def _content(kept: list[Block], question: str) -> list[dict]:
    """The message content, serialised FROM the blocks, in order, then the question. One function: a block cannot enter a request
    without being in `kept`, and the read rows are derived from the same list."""
    out: list[dict] = []
    for n, b in enumerate(kept, 1):
        out.append({"type": "text", "text": _label(n, b)})
        if b.text is not None:
            block: dict = {"type": "text", "text": b.text}
            if b.cache:
                block["cache_control"] = dict(agent_claude._CACHE)
            out.append(block)
        if b.picture is not None:
            out.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": b.picture["media_type"],
                        "data": b.picture["data"],
                    },
                }
            )
    out.append({"type": "text", "text": question})
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reads(role_no: int, call_id: str, kept: list[Block]) -> list[ReadEntry]:
    return [
        ReadEntry(
            role_no=role_no,
            call_id=call_id,
            document_id=b.document_id,
            document_kind=b.document_kind,  # type: ignore[arg-type]
            pages=tuple(b.pages),
            chapter_id=b.chapter_id,
            part_no=b.part_no,
            part_of=b.part_of,
            chars=len(b.text or ""),
            text_sha256=_sha(b.text or ""),
            pictures=1 if b.picture is not None else 0,
        )
        for b in kept
    ]


def _json_of(text: str) -> dict | None:
    return agent_claude.parse_json_object(text)


# --------------------------------------------------------------------------------------------------------------- ask


def ask(
    run_id: str,
    role_no: int,
    blocks: list[Block],
    question: str,
    *,
    engine: str = "claude",
    system: str | None = None,
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
    """Make ONE model call of a nine-role request and record it. Never raises for a refusal or a failed call: the answer says which
    (`state`, `error_code`) and what was left out (`not_sent`); a wrong use raises `NineCallError`."""
    conn = conn or connect()
    if role_no not in ROLE_NAMES:
        raise NineCallError(f"no role {role_no!r}")
    if engine not in ("claude", "local"):
        raise NineCallError("a model call is on Claude or on the local model")
    if role_no not in STEP_OF_ROLE:
        raise NineCallError(f"role {role_no} is code: it makes no model call")
    if not blocks or not str(question or "").strip():
        raise NineCallError("a request holds at least one block and a question")
    step = STEP_OF_ROLE[role_no]
    model = (
        model
        or DEFAULT_MODEL.get(role_no)
        or (agent_claude.LEAD_MODEL if engine == "claude" else _local_model())
    )
    call_id = call_id or uuid.uuid4().hex[:16]
    nine_record.ensure_schema(conn)
    gate = gate or RoleGate.for_role(role_no)

    # 1. the one gate, per document, BEFORE anything is built (a held block is dropped; the run goes on with the rest)
    kept_list = list(blocks)
    not_sent: dict[str, str] = {}
    if engine == "claude":
        not_sent = _dropped(run_id, blocks)
        kept_list = [b for b in blocks if b.document_id not in not_sent]
    else:  # the local model reads no pictures: the text of the block is kept, the picture is named as not read
        kept_list = [
            b if b.picture is None else _text_only(b)
            for b in blocks
            if b.text is not None or b.picture is not None
        ]
        kept_list = [b for b in kept_list if b.text is not None]
    dropped = tuple(sorted(not_sent.items()))
    if not kept_list:
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine=engine,
            model=model,
            error_code="no_block_left",
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            "no_block_left",
            None,
            None,
            None,
            model,
            (),
            dropped,
        )

    # 2. the request, FROM the kept blocks; the same list gives the read rows and the declaration
    content = _content(kept_list, question)
    reads = _reads(role_no, call_id, kept_list)
    kept_ids = tuple(dict.fromkeys(b.document_id for b in kept_list))
    parts: dict = {"messages": [{"role": "user", "content": content}]}
    if system:
        parts["system"] = [
            {"type": "text", "text": system, "cache_control": dict(agent_claude._CACHE)}
        ]

    if engine == "claude":
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
    )


def _text_only(b: Block) -> Block:
    return (
        Block(
            b.document_id,
            b.document_kind,
            b.pages,
            b.text,
            None,
            b.chapter_id,
            b.part_no,
            b.part_of,
            b.cache,
        )
        if b.text is not None
        else b
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
            kept_ids,
            dropped,
        )

    def on_request(
        digest: str, body: dict
    ) -> None:  # the `sent` row and the read rows, before the body leaves
        nine_record.call_sent(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            request_sha256=digest,
            reads=reads,
            conn=conn,
        )

    try:
        with (
            claude_approved.carrying(kept_ids),
            claude_approved.reviewing(run_id),
            claude_spend.for_run(run_id),
        ):
            answer, usd = agent_claude._call(
                model,
                parts,
                max_tokens,
                send,
                env,
                meter,
                step=step,
                on_request=on_request,
            )
    except agent_claude.AgentBadReply as exc:
        return _end(
            run_id,
            role_no,
            call_id,
            conn,
            "failed",
            exc.code,
            getattr(exc, "usd", None),
            model,
            kept_ids,
            dropped,
            reads,
        )
    except (agent_claude.AgentBudgetStop, agent_claude.AgentGateClosed) as exc:
        return _end(
            run_id,
            role_no,
            call_id,
            conn,
            "refused",
            exc.code,
            None,
            model,
            kept_ids,
            dropped,
            reads,
        )
    except agent_claude.AgentTransportError as exc:
        return _end(
            run_id,
            role_no,
            call_id,
            conn,
            "failed",
            exc.code,
            None,
            model,
            kept_ids,
            dropped,
            reads,
        )
    text = "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    answered = agent_claude._answered_model(answer)
    return _end(
        run_id,
        role_no,
        call_id,
        conn,
        "answered",
        None,
        usd,
        answered,
        kept_ids,
        dropped,
        reads,
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
    )
    sender = local_send or _ollama_send
    try:
        got = sender({"model": model, "max_tokens": int(max_tokens), **parts})
    except Exception as exc:  # noqa: BLE001 - a code only: the text of an error may carry document words
        return _end(
            run_id,
            role_no,
            call_id,
            conn,
            "failed",
            "local_" + type(exc).__name__,
            None,
            model,
            kept_ids,
            dropped,
            reads,
        )
    text = str((got or {}).get("text") or "")
    name = str((got or {}).get("model") or model)
    return _end(
        run_id,
        role_no,
        call_id,
        conn,
        "answered",
        None,
        None,
        name,
        kept_ids,
        dropped,
        reads,
        text=text,
    )


def _end(
    run_id,
    role_no,
    call_id,
    conn,
    state,
    code,
    usd,
    model,
    kept_ids,
    dropped,
    reads,
    *,
    text=None,
) -> Answer:
    ok = state == "answered"
    nine_record.call_end(
        run_id,
        call_id,
        state,
        error_code=code,
        usd=usd,
        model=model if ok else None,
        conn=conn,
    )
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
        kept_ids,
        dropped,
        tuple(reads),
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
