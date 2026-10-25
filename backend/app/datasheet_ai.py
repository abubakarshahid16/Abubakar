"""AI READS, CODE CHECKS: the datasheet reader with two interchangeable engines.

WHAT THIS IS. `datasheets.extract_facts` reads label/value pairs with rule
readers (grid, text blocks, table shapes). `claude_datasheet.read_page` reads
a page with a model and keeps a proposal only when code can re-derive it from
the page: the quote is on the page, the value and the label's main word are in
the quote, the unit is one `claims` knows, and two runs agree. Until now that
reader was reachable only by one API route. This module makes it a second,
INDEPENDENT reading inside extraction, behind `settings.datasheet_ai_reader`
("off" by default - off is the old extraction, byte for byte).

TWO ENGINES, ONE CALLABLE SHAPE (prompt -> raw text):

  * "ollama" - the local engine, through `reasoning_provider.OllamaProvider`,
    which reaches the socket only through `model_transport` (the URL is
    re-validated by `config.check_model_url` before every request; it is also
    asked once here first, through `model_transport.endpoint`, so a refused
    host is a reason, not a failure).
  * "claude" - the Claude API, only when `reasoning_provider.claude_unavailable`
    says Claude may be used (REASONING_PROVIDER=claude AND both
    STANDARDS_READER_* egress flags AND a key), through
    `reader_transport.transport()` wrapped in `claude_spend.metered` (the USD
    5 per step / USD 20 total caps are checked BEFORE each call leaves, and
    each call is written to the one ledger) and `claude_budget.Budget` (the
    per-run call cap). It is the `claude_api` routes' exact chain, plus the
    REASONING_PROVIDER check those routes lack. NOT through
    `ClaudeProvider.reason`: that path answers a repeated prompt from its
    response cache, which would make rule 6 of `claude_datasheet.accept` (two
    runs must agree) agree with itself.

NOTHING HERE RAISES INTO INGESTION. An engine that is off, unavailable,
failing, answering malformed JSON, or refused by a budget cap leaves the page
to the rule readers and says why (`model_call_for` returns the reason;
`read_pages` records one per page). A cap refusal stops the calls for the rest
of the document - it would refuse every one of them anyway.

THE MERGE IS PURE. `merge_readings(rule_facts, ai_facts)` takes dicts and
returns decisions; `datasheets._extract_facts` applies them. A benchmark can
call `read_page_text_with_ai` and `merge_readings` without a database.

This module imports no HTTP client and opens no socket
(`tests/test_socket_containment.py`).
"""

from __future__ import annotations

import contextlib
import re
import time
from contextvars import ContextVar

from . import (
    claims,
    claude_datasheet,
    datasheet_inputs,
    datasheets,
    errors,
    job_progress,
)
from .ai import output_limits
from .claude_spend import StopRun
from .config import settings

# ---------------------------------------------------------------- vocabulary

OFF = "off"
OLLAMA = "ollama"
CLAUDE = "claude"
ENGINES = (OFF, OLLAMA, CLAUDE)

#: The `claude_spend` step every Claude call from this reader is charged to,
#: so the USD 5 per-step cap applies to this reader's own spend.
STEP = "datasheet-ai-reader"

#: Written into `bbox` provenance (`reader`) on every fact this reader wrote
#: or touched, beside the engine name.
READER = "datasheet_ai"

#: An AI-only fact is written exactly as `claude_datasheet.store_facts` writes
#: one: `extraction_method="model"` at confidence 0.5. Since the planner
#: decision of 2026-10-11 it DECIDES like a code-read fact, because its quote
#: was proved on the page (`quote_on_page` in its provenance,
#: `comparison.ai_quote_proved`); the finding says an AI-read value decided it.
#: The ENGINE is recorded in the fact's provenance (`bbox`), not in the method,
#: so every existing reader of "model" keeps working.
EXTRACTION_METHOD = claude_datasheet.EXTRACTION_METHOD
AI_CONFIDENCE = claude_datasheet.CONFIDENCE

#: Rules and AI read the SAME value from the same page, independently. That
#: is more evidence than either alone (rule reader 0.6, model 0.5), so it is
#: written higher than both - and still below `comparison`'s 0.9 ceiling for
#: a deterministic comparison: CLAUDE.md rule 4, confidence is never "high".
AGREED_CONFIDENCE = 0.7

#: Decisions `merge_readings` returns.
AGREED = "agreed"
CONFLICT = "conflict"
AI_ONLY = "ai_only"
RULES_ONLY = "rules_only"

#: How a rule reading and an AI reading of one field relate (`reading_relation`).
SAME = "same"                    # the same value: agreement
AI_UNIT = "ai_unit"              # the same number; only the AI has a unit, and its quote shows it
UNIT_DIFFERS = "unit_differs"    # the same number in two different units: a conflict
DIFFERENT = "different"          # different values: a conflict

#: Written into a rules-only fact's provenance when the AI reader READ its
#: page and did not confirm it. A flag for the engineer, not a verdict: the
#: fact is kept exactly as the rules read it, confidence unchanged.
UNCONFIRMED = "the AI reader read this page and did not read this value"

#: Local engine packet sizes. A datasheet page plus the prompt does not fit
#: the answer model's 4096-token window, and a page's JSON answer is longer
#: than a chat answer.
OLLAMA_NUM_CTX = 8192
OLLAMA_NUM_PREDICT = 2048


def _effective_window() -> int:
    """The window the reader really runs at: the transport raises every local
    call to the shared size, so a larger `LOCAL_NUM_CTX` changes what the model
    sees. The stored-answer key uses this, never the literal above."""
    return max(OLLAMA_NUM_CTX, int(settings.num_ctx), int(settings.local_num_ctx))


PROMPT_VERSION = "datasheet-ai-1"

#: What the local engine is asked to return (enforced in the engine by
#: Ollama's `format`; `claude_datasheet.parse_response` checks it again).
_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"field": {"type": "string"}, "value": {"type": "string"},
                       "unit": {"type": ["string", "null"]}, "quote": {"type": "string"},
                       "kind": {"type": "string"}},
        "required": ["field", "value", "quote", "kind"]}}},
    "required": ["facts"],
}


class EngineFailed(RuntimeError):
    """The engine answered, but not in a way that can be read (truncated)."""


class AnswerCutOff(EngineFailed):
    """The local engine's answer reached the output limit (Ollama's
    `done_reason` "length"); `text` is what it wrote before the cut.

    Order 139 (#882): on a dense page the model writes a long, VALID list of
    facts and is cut off at `OLLAMA_NUM_PREDICT` - measured on a real 7-page
    sheet, 3 pages lost every reading as "engine failed". A cut-off answer is
    still never parsed as a whole one: `_read` reads the page again in smaller
    parts (`split_text`), and only a part still cut off at the last split
    keeps the facts it had FINISHED (`claude_datasheet.parse_or_cut`, the
    Claude lane's rule), marked `cut_off`."""

    def __init__(self, text: str | None):
        super().__init__("the answer was truncated")
        self.text = text or ""


# ------------------------------------------------------------ the engines

def engine_setting() -> str:
    """`settings.datasheet_ai_reader`, folded. Anything unknown is returned as
    written, and `model_call_for` refuses it with a reason."""
    return (str(settings.datasheet_ai_reader or OFF).strip().lower() or OFF)


def _claude_call():
    from . import claude_budget, claude_spend, reader_api, reader_transport
    from .reasoning_provider import claude_unavailable_for_task

    # #501: this reader's own engine setting, under the provider switch.
    code, why = claude_unavailable_for_task(engine_setting())
    if code is not None:
        return None, f"claude engine unavailable ({code}: {why})"
    transport = reader_transport.transport()
    if transport is None:
        return None, "claude engine unavailable (EGRESS_OFF: no transport)"
    # A PAGE OF VALUES, NOT ONE SENTENCE (R32, 2026-10-11). The reader lane's
    # own defaults are sized for `read_sentence` (512 tokens out, 30 s): a
    # whole datasheet page's facts were cut off mid-JSON and read as
    # "engine answer unusable". Same destination, same flags, same key check
    # (`build_request`); only the answer budget, the time and the model are
    # this reader's own. The model is the configured reasoning model unless
    # STANDARDS_READER_MODEL names one.
    import dataclasses
    import os
    base = reader_api.ReaderSettings.from_env()
    model = (os.environ.get("STANDARDS_READER_MODEL") or "").strip() or settings.claude_reasoning_model
    cfg = dataclasses.replace(base, model=model,
                              timeout_seconds=float(settings.datasheet_ai_timeout_seconds))
    # #456: the route table sets the cap (DATASHEET_AI_CLAUDE_MAX_TOKENS); a
    # cut-off reply keeps its complete facts and is marked `cut_off` by
    # `claude_datasheet.parse_or_cut` (#501). The local lane's cut-off
    # (`AnswerCutOff`) reads the page again in parts first, and keeps the
    # finished facts the same way only at the last split - neither parsed whole.
    call = claude_budget.Budget(output_limits.model_call_for(
        claude_spend.metered(transport, STEP, unbilled=reader_transport.unbilled),
        output_limits.ROUTE_DATASHEET_READ, cfg=cfg, salvage=True))
    call.engine = CLAUDE
    call.model = model
    call.step = STEP
    return call, None


def _ollama_call(packet_shape: dict | None = None):
    """`packet_shape` (form reader, #form-reader): the JSON schema, prompt
    version and answer budget of a caller with its own answer shape. None -
    this reader's own `_SCHEMA` and sizes, exactly as before."""
    from . import ai_task_runner, model_transport
    from .reasoning_provider import OllamaProvider, Packet, schema_errors

    # The same gate every request passes (`model_transport.endpoint` ->
    # `config.check_model_url`), asked once up front so a refused host is a
    # reason for the whole document rather than a failure on every page.
    try:
        model_transport.endpoint("/api/generate")
    except Exception as exc:  # noqa: BLE001 - a refused host is a reason, not a crash
        return errors.fell_back("datasheet_ai: the local engine is unavailable; no AI read", exc, (None, f"ollama engine unavailable ({type(exc).__name__})"))
    # Owner order 2026-10-11: the local model is slow - every call has its
    # own timeout (DATASHEET_AI_TIMEOUT_SECONDS), not the provider's 15 min.
    model = settings.datasheet_ai_ollama_model or settings.answer_model
    provider = OllamaProvider(
        model, timeout=float(settings.datasheet_ai_timeout_seconds), retry_timeouts=True
    )
    shape = {"json_schema": _SCHEMA, "prompt_version": PROMPT_VERSION,
             "num_predict": OLLAMA_NUM_PREDICT, **(packet_shape or {})}

    asked: dict[str, int] = {}

    def call(prompt: str) -> str:
        # REUSE (order 163.3): the stored answer to the same prompt (page text
        # + rule inputs), prompt version, answer shape and model; see
        # `ai_task_runner.reuse_or_ask`. Only an answer that parses into the
        # expected JSON shape is kept: a malformed or empty one is asked
        # again next time. The text goes through every gate a fresh one does.
        def ask() -> str:
            response = provider.reason(
                Packet(
                    prompt=prompt,
                    num_ctx=OLLAMA_NUM_CTX,
                    num_predict=shape["num_predict"],
                    temperature=0.0,
                    json_schema=shape["json_schema"],
                    step=STEP,
                    prompt_version=shape["prompt_version"],
                )
            )
            if response.truncated:
                # A cut-off JSON answer is not an answer; never parsed as one.
                # Its text goes with the refusal, for `_read`'s smaller parts.
                raise AnswerCutOff(response.text)
            return response.text

        return ai_task_runner.reuse_or_ask(
            STEP,
            shape["prompt_version"],
            model,
            shape["json_schema"],
            f"{_effective_window()}/{shape['num_predict']}\x00{prompt}",
            ask,
            asked=asked,
            keep_if=lambda text: (
                shape["json_schema"] is not None
                and not schema_errors(text, shape["json_schema"])
            ),
        )

    call.engine = OLLAMA
    call.model = model
    return call, None


#: A model call handed in by the caller for the length of one `with
#: using_model_call(...)` block - the offline benchmark's counted engine, or a
#: test's fake - used in place of the configured engine. None (the default,
#: and always in production) changes nothing. A ContextVar, so another
#: thread's extraction cannot see it. It never switches the reader ON: with
#: DATASHEET_AI_READER off, `model_call_for` still answers "off".
_CALL_OVERRIDE: ContextVar = ContextVar("datasheet_ai_call_override", default=None)


@contextlib.contextmanager
def using_model_call(model_call):
    """Within the block, `model_call_for` returns `model_call` for any engine
    but "off". Restored on the way out, even on an exception."""
    token = _CALL_OVERRIDE.set(model_call)
    try:
        yield model_call
    finally:
        _CALL_OVERRIDE.reset(token)


def model_call_for(engine: str | None = None, packet_shape: dict | None = None):
    """`(model_call, None)` for the engine, or `(None, reason)`.

    `engine` defaults to the configured one. NEVER RAISES: an engine that is
    off, unknown or unavailable is a reason the caller records, and the page
    stays with the rule readers. The callable carries `.engine`.
    `packet_shape` is handed to the local engine only (`_ollama_call`); the
    Claude engine states the shape in the prompt and is checked in code.
    """
    name = (engine if engine is not None else engine_setting()).strip().lower()
    if name == OFF:
        return None, "DATASHEET_AI_READER is off"
    override = _CALL_OVERRIDE.get()
    if override is not None:
        return override, None
    try:
        if name == OLLAMA:
            return _ollama_call(packet_shape) if packet_shape else _ollama_call()
        if name == CLAUDE:
            return _claude_call()
    except Exception as exc:  # noqa: BLE001 - never into ingestion
        return errors.fell_back("datasheet_ai: the AI reader engine could not be built; no AI read", exc, (None, f"{name} engine unavailable ({type(exc).__name__})"))
    return None, f"DATASHEET_AI_READER={name!r} is not one of {', '.join(ENGINES)}"


# ------------------------------------------------------------ one page

def _empty(page_no: int, engine: str | None, **extra) -> dict:
    return {"page": page_no, "engine": engine, "accepted": [], "rejected": [],
            "counts": {}, **extra}


#: A page whose answer is cut off is read again in two halves, and a half
#: still cut off in two quarters: at most 2 ** MAX_SPLITS parts, two runs
#: each - a bounded number of calls, inside the pass's time budget.
MAX_SPLITS = 2
#: The second part starts this many lines (words, on a one-line text) before
#: the cut: a label on one line and its value on the next are read together
#: in one part at least. A fact read in both parts is kept once.
OVERLAP_LINES = 2
OVERLAP_WORDS = 8


def _halves(text: str, sep: str, overlap: int) -> list[str]:
    pieces = text.split(sep)
    if len(pieces) < 2:
        return []
    middle, ends, at = len(text) // 2, [], -len(sep)
    for piece in pieces[:-1]:
        at += len(piece) + len(sep)
        ends.append(at)  # where the k-th cut (k = 1..) falls
    k = 1 + min(range(len(ends)), key=lambda i: (abs(ends[i] - middle), i))
    head = sep.join(pieces[:k]).strip()
    tail = sep.join(pieces[max(1, k - overlap) :]).strip()
    return [head, tail] if head and tail else []


def split_text(text: str) -> list[str]:
    """Two parts of about equal length, cut at the line end nearest the
    middle (a space when the text is one line); the second part repeats the
    last `OVERLAP_LINES` lines (`OVERLAP_WORDS` words) before the cut. Each
    part is a piece of the text as printed; nothing is dropped. [] when the
    text cannot be cut."""
    text = (text or "").strip()
    return _halves(text, "\n", OVERLAP_LINES) or _halves(text, " ", OVERLAP_WORDS)


#: A part that does not start the page is shown the page's first lines above
#: it, CONTEXT ONLY (`with_context`): at most this many lines and characters.
CONTEXT_LINES = 8
CONTEXT_CHARS = 800
CONTEXT_OPEN = (
    "[CONTEXT ONLY - the top of this page, for column names; "
    "do not read values from these lines]"
)
CONTEXT_CLOSE = "[END OF CONTEXT - read values only from the lines below]"
#: A part's reading whose quote is not on the part's own lines.
QUOTE_NOT_IN_PART = "quote_not_in_part"
#: Written into the provenance of a part's reading whose kind its lines do not name.
KIND_UNCONFIRMED = (
    "read from part of a split page whose own lines do not name the column "
    "(required / offered / measured); an engineer checks the value"
)
#: Said on a part still cut off at the last split before it finished a value.
CUT_BEFORE_ANY = "the answer was cut off before one value was finished"


def _keeping_the_cut(model_call):
    """`model_call`, but a cut-off answer is RETURNED (its text) instead of
    raised, so `claude_datasheet.parse_or_cut` keeps the facts the model
    finished and `read_page` marks the reading `cut_off`. `call.cut` says
    whether an answer was cut off."""

    def call(prompt: str) -> str:
        try:
            return model_call(prompt)
        except AnswerCutOff as exc:
            call.cut = True
            return exc.text

    call.cut = False
    return call


def _part_failure(exc: BaseException) -> str:
    if is_timeout(exc):
        return TIMED_OUT.format(seconds=_seconds(settings.datasheet_ai_timeout_seconds))
    return f"engine failed ({type(exc).__name__})"


def _read_part(
    state: dict, part: str, depth: int, page_text: str, page_no: int, model_call
) -> list:
    """One part of a cut-off page, its outcome added to `state`. Returns the
    parts to read next in its place: its halves when it was cut off again."""
    last = depth >= MAX_SPLITS
    call = _keeping_the_cut(model_call) if last else model_call
    try:
        shown = with_context(part, page_text)
        got = claude_datasheet.read_page(
            shown, page_no, None, call, gate_text=page_text
        )
    except AnswerCutOff:
        state["cut_again"] += 1
        return [(p, depth + 1) for p in split_text(part)] or [(part, MAX_SPLITS)]
    except StopRun as exc:
        state["stopped"] = exc.count_key
        state["unread"].append(f"a limit stopped the AI reader ({exc.count_key})")
        return []
    except Exception as exc:  # noqa: BLE001 - never into ingestion; the part is counted unread
        errors.fell_back("datasheet_ai: the AI read of a page part failed", exc, None)
        state["timed_out"] = state["timed_out"] or is_timeout(exc)
        state["unread"].append(_part_failure(exc))
        return []
    if got.get("error"):
        cut = getattr(call, "cut", False)
        state["unread"].append(
            CUT_BEFORE_ANY if cut else f"engine answer unusable ({got['error']})"
        )
        return []
    state["read"] += 1
    state["cut"] = state["cut"] or bool(got.get("cut_off"))
    state["rejected"].extend(got["rejected"])
    for p in got["accepted"]:
        p = _part_fact(p, part, shown)
        if p.get("reason"):
            state["rejected"].append(p)
            continue
        # the overlap reads a row twice: one fact, whichever part quoted it
        key = tuple(p.get(k) for k in ("field_name", "value", "unit", "kind"))
        if key not in state["seen"]:
            state["seen"].add(key)
            state["accepted"].append({**p, "page": page_no})
    return []


#: How a line is cut into cells: a pipe, a tab, or a run of two spaces.
_CELLS = re.compile(r"\s*(?:\||\t| {2,})\s*")


def header_kinds(line: str) -> set[str]:
    """The kinds a HEADER line names (#1175 review): a line with no digit at
    all - a header names columns, it holds no value - one of whose cells IS a
    kind's word (`_KIND_WORDS`, whole cell, case-folded). A data row that only
    contains such a word ("Vendor reference | ABC") names no column."""
    if re.search(r"\d", line or ""):
        return set()
    cells = {claude_datasheet._fold(c) for c in _CELLS.split(line.strip()) if c.strip()}
    return {kind for kind, words in _KIND_WORDS.items() if cells & set(words)}


def _nearest_header(lines: list[str], below: int) -> int | None:
    """The index of the nearest header line above line `below`, or None."""
    return next((i for i in range(below - 1, -1, -1) if header_kinds(lines[i])), None)


def with_context(part: str, page_text: str) -> str:
    """The part as the model is shown it: when the part does not start the
    page, lines above it go first, marked CONTEXT ONLY - the page's first
    `CONTEXT_LINES` lines, and the nearest header line above the cut when it
    is further down - so the column names (required / offered) printed above
    the cut are seen. Values are not read from there (`_part_fact`)."""
    start = page_text.find(part)
    above = page_text[:start].strip() if start > 0 else ""
    if not above:
        return part
    lines = above.split("\n")
    shown = lines[:CONTEXT_LINES]
    header = _nearest_header(lines, len(lines))
    if header is not None and header >= CONTEXT_LINES:
        shown.append(lines[header])
    context = "\n".join(shown)[-CONTEXT_CHARS:]
    return f"{CONTEXT_OPEN}\n{context}\n{CONTEXT_CLOSE}\n{part}"


def _part_fact(p: dict, part: str, shown: str) -> dict:
    """A part's accepted reading, checked against what the part's model was
    SHOWN (`shown`, `with_context`). A quote not on the part's own lines (read
    from the context) is refused (`QUOTE_NOT_IN_PART`). The kind is confirmed
    only by the nearest header line above the quote among the lines shown
    (`header_kinds`): a kind no header names may be a guess - a split can
    leave the column names above the cut - so the reading is marked
    `kind_unconfirmed`: it is kept, and `datasheets` writes it for an
    engineer (never deciding a verdict)."""
    quote = claude_datasheet._fold(p.get("quote") or "")
    if not claude_datasheet._contains(claude_datasheet._fold(part), quote):
        return {**p, "reason": QUOTE_NOT_IN_PART}
    lines = shown.split("\n")
    first = next(
        (
            claude_datasheet._fold(x)
            for x in (p.get("quote") or "").splitlines()
            if x.strip()
        ),
        "",
    )
    own_from = len(lines) - len(part.split("\n"))
    at = next(
        (
            i
            for i in range(own_from, len(lines))
            if first and first in claude_datasheet._fold(lines[i])
        ),
        None,
    )
    header = _nearest_header(lines, at + 1) if at is not None else None
    if header is not None and p.get("kind") in header_kinds(lines[header]):
        return p
    box = {**(p.get("provenance") or {}), "kind_unconfirmed": KIND_UNCONFIRMED}
    return {**p, "kind_unconfirmed": True, "provenance": box}


def _parts_outcome(state: dict, page_no: int, engine: str | None) -> dict:
    """The page's reading from its parts, in `_read`'s shape."""
    read, unread = state["read"], state["unread"]
    out = {
        "page": page_no,
        "engine": engine,
        "accepted": state["accepted"],
        "rejected": state["rejected"],
        "counts": claude_datasheet.rejection_counts(state["rejected"]),
        "parts": {
            "read": read,
            "not_read": len(unread),
            "cut_again": state["cut_again"],
        },
    }
    if state["cut"]:
        out["cut_off"] = True
    if state["stopped"] is not None:
        out["stopped"] = state["stopped"]
    if state["timed_out"]:
        out["timed_out"] = True
    why = "; ".join(dict.fromkeys(unread))
    if not read:
        out["error"] = f"{CUT_OFF_UNREAD} ({why})"
    elif unread:
        out["partial"] = (
            f"read in {read + len(unread)} parts after the answer was cut off; "
            f"{len(unread)} part(s) not read ({why})"
        )
    return out


#: Said on a page whose answer was cut off and no part of which was read.
CUT_OFF_UNREAD = (
    "the answer was cut off by the output limit and no part of the page was read"
)


def _read_in_parts(
    page_text: str, page_no: int, model_call, engine: str | None, deadline: float | None
) -> dict:
    """A page whose answer was cut off, read again part by part (order 139).

    Each part is read with the same two runs and the same gate as a page, and
    the gate checks every quote against the WHOLE page (`gate_text`). A part
    still cut off is halved again up to `MAX_SPLITS`; at the last split its
    finished facts are kept and the page is marked `cut_off`. Nothing is
    silent: a part not read (time budget, failure, limit) is counted and
    named in `partial`, and a page no part of which was read is an `error`."""
    pending = [(part, 1) for part in split_text(page_text)] or [(page_text, MAX_SPLITS)]
    state = {
        "accepted": [],
        "rejected": [],
        "unread": [],
        "seen": set(),
        "read": 0,
        "cut_again": 0,
        "cut": False,
        "timed_out": False,
        "stopped": None,
    }
    while pending:
        part, depth = pending.pop(0)
        if state["stopped"] is not None:
            state["unread"].append(
                f"a limit stopped the AI reader ({state['stopped']})"
            )
        elif deadline is not None and time.monotonic() >= deadline:
            state["unread"].append("the time budget ran out")
        else:
            pending[0:0] = _read_part(
                state, part, depth, page_text, page_no, model_call
            )
    return _parts_outcome(state, page_no, engine)


def _read(
    page_text: str,
    page_no: int,
    model_call,
    engine: str | None,
    deadline: float | None = None,
) -> dict:
    """`claude_datasheet.read_page` for one page, WITHOUT the rule readers'
    fields as `known_fields`: this is a second, independent reading, and a
    field the rules also read is exactly what agreement is measured on.

    Returns the read_page shape plus `engine`; `error` when the page could
    not be read (engine failure, malformed answer) and `stopped` (the limit's
    count key) when a budget cap refused a call. An answer cut off by the
    output limit reads the page again in parts (`_read_in_parts`), within
    `deadline` (`time.monotonic()`). Only the exception's TYPE is kept - a
    message could carry a URL, never a page's words, but the type is all a
    reader of the result needs."""
    try:
        out = claude_datasheet.read_page(page_text, page_no, None, model_call)
    except AnswerCutOff:
        return _read_in_parts(page_text, page_no, model_call, engine, deadline)
    except StopRun as exc:
        return _empty(page_no, engine, error=f"stopped by a limit ({exc.count_key})",
                      stopped=exc.count_key)
    except Exception as exc:  # noqa: BLE001 - never into ingestion
        errors.fell_back("datasheet_ai: the AI read of a page failed; the page is recorded empty", exc, None)
        if is_timeout(exc):
            return _empty(page_no, engine, error=TIMED_OUT.format(
                seconds=_seconds(settings.datasheet_ai_timeout_seconds)), timed_out=True)
        return _empty(page_no, engine, error=f"engine failed ({type(exc).__name__})")
    if out.get("error"):
        out["error"] = f"engine answer unusable ({out['error']})"
    out["engine"] = engine
    out["accepted"] = [{**p, "page": page_no} for p in out["accepted"]]
    return out


#: Said on a page the model did not answer in time. The page keeps the rule
#: readers' reading (code only) - owner order 2026-10-11.
TIMED_OUT = "the AI reader timed out after {seconds} s; the code readers' reading stands"
#: Said on every page left unread once the document's time budget is spent.
OUT_OF_TIME = ("not read: the AI reader's time budget for this document ({seconds} s) ran out; "
               "the code readers' reading stands")


def _seconds(value) -> str:
    return f"{float(value):g}"


def is_timeout(exc: BaseException) -> bool:
    """A call that ran out of time, by type: the transport's timeout
    (httpx's `TimeoutException` family) or a plain `TimeoutError` - on the
    exception or anywhere down its cause chain, because the Ollama provider
    re-raises every transport failure as `ProviderRefused` (measured on F1,
    2026-10-11: every timed-out page read "engine failed (ProviderRefused)").
    Only types are looked at - never a message."""
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, TimeoutError) or any("Timeout" in k.__name__ for k in type(exc).__mro__):
            return True
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return False


def read_page_text_with_ai(page_text: str, page_no: int, engine_or_callable) -> dict:
    """One page's text through the AI reader; the accepted facts and why the
    rest were dropped. `engine_or_callable` is an engine name ("ollama",
    "claude") or a `prompt -> text` callable (a benchmark's, or a test's
    fake). Never raises; `error` says why nothing was read."""
    if callable(engine_or_callable):
        call, engine = engine_or_callable, getattr(engine_or_callable, "engine", "custom")
    else:
        engine = str(engine_or_callable)
        call, why = model_call_for(engine)
        if call is None:
            return _empty(page_no, engine, error=why)
    if not (page_text or "").strip():
        return _empty(page_no, engine, error="no text on this page")
    return _read(page_text, page_no, call, engine)


def read_pages(page_texts: dict[int, str], engine_or_callable=None) -> dict:
    """Every page of one document through the reader, in page order.

    Returns `{"engine", "model", "unavailable", "pages": {page: read result},
    "reasons": {page: why this page has no AI reading}, "partly_read": {page:
    which parts were not read}, "stopped", "timed_out", "seconds"}`. After a
    budget refusal no further call is made: the remaining pages are recorded
    as not read, with that reason. The same
    once the document's TIME budget (DATASHEET_AI_MAX_SECONDS) is spent:
    the local model is slow, and a review must not wait on it without end -
    the rest of the pages keep the code readers' reading, said per page."""
    if engine_or_callable is None or not callable(engine_or_callable):
        engine = (engine_or_callable or engine_setting())
        call, why = model_call_for(engine)
        engine = getattr(call, "engine", engine)
    else:
        call, why = engine_or_callable, None
        engine = getattr(call, "engine", "custom")
    pages: dict[int, dict] = {}
    reasons: dict[int, str] = {}
    partly: dict[int, str] = {}
    stopped = None
    timed_out: list[int] = []
    budget = float(settings.datasheet_ai_max_seconds)
    started = time.monotonic()
    for index, page_no in enumerate(sorted(page_texts), start=1):
        job_progress.page(index, len(page_texts))  # order 95 piece 3b: display only
        text = page_texts[page_no] or ""
        if call is None:
            reasons[page_no] = why
            continue
        if stopped is not None:
            reasons[page_no] = (OUT_OF_TIME.format(seconds=_seconds(budget)) if stopped == "time_budget"
                                else f"not read: a limit stopped the AI reader ({stopped})")
            continue
        if text.strip() and time.monotonic() - started >= budget:
            stopped = "time_budget"
            reasons[page_no] = OUT_OF_TIME.format(seconds=_seconds(budget))
            continue
        if not text.strip():
            reasons[page_no] = "no text on this page"
            continue
        out = _read(text, page_no, call, engine, deadline=started + budget)
        pages[page_no] = out
        if out.get("stopped"):
            stopped = out["stopped"]
        # order 139: `reasons` and `timed_out` are pages with NO AI reading; a
        # page read only in part keeps its readings, and says which parts
        # were not read, under `partly_read` - never a clean page.
        if out.get("error"):
            reasons[page_no] = out["error"]
            if out.get("timed_out"):
                timed_out.append(page_no)
        elif out.get("partial"):
            partly[page_no] = out["partial"]
    return {
        "engine": engine,
        "model": getattr(call, "model", None),
        "unavailable": why,
        "pages": pages,
        "reasons": reasons,
        "partly_read": partly,
        "stopped": stopped,
        "timed_out": timed_out,
        "seconds": round(time.monotonic() - started, 1),
    }


def parts_summary(ai_run: dict) -> dict:
    """Order 139, for `datasheets.reader_summary`, only when there is
    something: `partly_read` (page -> which parts the AI did not read; the
    page HAS an AI reading, so it is never in `code_only`) and
    `read_in_parts` (page -> how many parts, after a cut-off answer)."""
    partly = {
        str(p): why for p, why in sorted((ai_run.get("partly_read") or {}).items())
    }
    parts = {
        str(p): out["parts"]["read"] + out["parts"]["not_read"]
        for p, out in sorted(ai_run["pages"].items())
        if out.get("parts")
    }
    return {
        **({"partly_read": partly} if partly else {}),
        **({"read_in_parts": parts} if parts else {}),
    }


def page_text(stored_path: str | None, page_no: int, chunks: list) -> str:
    """The text the AI reader reads for one page: the PDF's own text layer
    for THAT page first (a chunk may span several pages, and a quote proved
    against a neighbour's text would be cited to the wrong page), then the
    stored chunk text only when a chunk covers exactly this page (an OCR'd
    scan has no text layer).

    An OFFICE datasheet (DATASHEET_OFFICE_INPUT on, a workbook or Word file)
    is never handed to MuPDF: MuPDF opens an .xlsx and reads its numbers
    without their labels, so the AI would read "42 60 2900" where the sheet
    says "Capacity | m3/h | 42". Its page text is `datasheet_inputs`' rendered
    page - the same text the rule readers pair and the chunks were cut from
    (found by the benchmark's production-path run, 2026-09-30)."""
    if stored_path and datasheet_inputs.is_office_input(stored_path):
        pages = datasheet_inputs.office_pages(stored_path)
        return pages[page_no - 1].text if 1 <= page_no <= len(pages) else ""
    text = claude_datasheet._pdf_page_text(stored_path, page_no) if stored_path else ""
    if text.strip():
        return text
    own = [c for c in chunks
           if c["page_start"] == page_no and (c["page_end"] or c["page_start"]) == page_no]
    return "\n".join((c["text"] or "") for c in own).strip()


# ------------------------------------------------------------ the merge

#: Words in a rule fact's column header that say whose value it is - the
#: same three kinds `claude_datasheet.KINDS` names. A column the rules did not
#: name (or named "MIN", "RATED") has no kind, and is compatible with any.
_KIND_WORDS = {
    "required": ("required", "spec", "specified", "purchaser"),
    "offered": ("offered", "vendor", "proposed", "supplier"),
    "measured": ("measured", "test", "actual", "as built"),
}


def _label_column(fact: dict) -> tuple[str, str | None]:
    """`(row label, column header)` of a rule fact. The table-shape reader
    names a cell "<row label> - <column header>" ("Maximum flow - Offered",
    `datasheets.pairs_from_table_shape`) and records no `value_column`; the
    geometry table reader records the column and names the cell "<row label>
    <column header>". Either way the column says WHOSE value it is, not
    which field."""
    label = str(fact.get("field_label") or fact.get("field") or "")
    column = fact.get("value_column")
    if column:
        return label, str(column)
    head, sep, tail = label.rpartition(" - ")
    if sep and head.strip() and tail.strip():
        return head.strip(), tail.strip()
    return label, None


def rule_kind(fact: dict) -> str | None:
    """Whose value a rule fact is, when its column header says so."""
    column = " ".join(str(_label_column(fact)[1] or "").lower().split())
    if not column:
        return None
    for kind, words in _KIND_WORDS.items():
        if any(w in column for w in words):
            return kind
    return None


def ai_raw_value(fact: dict) -> str:
    """The AI reading as one cell of text, value then unit."""
    return " ".join(p for p in (fact.get("value"), fact.get("unit")) if p)


def _printed_unit(text: str | None) -> str | None:
    """The unit a value's own text prints - a quantity's or a range's."""
    text = text or ""
    unit = datasheets.measure_value(text)[1]
    if unit:
        return unit
    found = datasheets.parse_range(text)
    return found[2] if found else None


def rule_unit(fact: dict) -> str | None:
    """The unit a rule fact carries: the stored one, else its value's own."""
    return (fact.get("raw_unit") or fact.get("unit")
            or _printed_unit(fact.get("field_value")))


def ai_unit(fact: dict) -> str | None:
    return fact.get("unit") or _printed_unit(fact.get("value"))


def unit_in_quote(unit: str, quote: str | None) -> bool:
    """Does the AI's QUOTE - the words `claude_datasheet.accept` proved are on
    the page - print this unit? Whole, case-folded; a number may touch it
    ("75kW") but a letter may not ("m3/h" is not in "Nm3/h")."""
    folded = claude_datasheet._fold(unit)
    return bool(folded) and re.search(
        r"(?<![^\W\d_])" + re.escape(folded) + r"(?![^\W_])",
        claude_datasheet._fold(quote or "")) is not None


def same_unit(a: str, b: str) -> bool:
    """One unit, spelled once or twice. The REFERENCE must match (a gauge and
    an absolute pressure differ by an atmosphere); then the same spelling, or
    two spellings `claims` converts to one canonical unit ("mm" and "m")."""
    base_a, ref_a = claims.split_reference(a)
    base_b, ref_b = claims.split_reference(b)
    if ref_a != ref_b:
        return False
    fold_a, fold_b = claims._fold_unit(base_a or ""), claims._fold_unit(base_b or "")
    if fold_a == fold_b:
        return True
    canon_a = claims.normalise("1", base_a or "").normalized_unit
    return canon_a is not None and canon_a == claims.normalise("1", base_b or "").normalized_unit


def reading_relation(rule_fact: dict, ai_fact: dict) -> str:
    """How the AI's reading of a field relates to the rules' reading of it.

      DIFFERENT     the values differ (the geometry reader's agreement rule,
                    `datasheets._geometry_agrees`: numbers as numbers,
                    normalised when both normalise; text folded);
      UNIT_DIFFERS  the NUMBERS are equal and the two readings carry two
                    different units - "75 kW" and "75 hp" are not one value,
                    and nothing here may pick one;
      AI_UNIT       the numbers are equal, the rules' reading LOST its unit
                    ("75" read from a grid whose unit sits in its own column)
                    and the AI's quote - checked on the page - prints the
                    unit it gives: the AI's unit is proven;
      SAME          otherwise: the same value. A unit only the rules carry,
                    or an AI unit its own quote does not print, adds nothing.
    """
    raw = ai_raw_value(ai_fact)
    blank, _marker = datasheets.is_blank_value(raw)
    if not datasheets._geometry_agrees(raw, blank, rule_fact):
        return DIFFERENT
    if blank or rule_fact.get("is_blank") or rule_fact.get("raw_value") is None:
        return SAME
    theirs, ours = rule_unit(rule_fact), ai_unit(ai_fact)
    if theirs and ours:
        return SAME if same_unit(theirs, ours) else UNIT_DIFFERS
    if ours and unit_in_quote(ours, ai_fact.get("quote")):
        return AI_UNIT
    return SAME


def values_agree(rule_fact: dict, ai_fact: dict) -> bool:
    """Do the rules and the AI read the same value? See `reading_relation`:
    the same number in two different units is NOT agreement."""
    return reading_relation(rule_fact, ai_fact) in (SAME, AI_UNIT)


def field_key(fact: dict) -> str:
    """The field a reading is about. A table reader names a value "<row>
    <column>" ("Rated power Value", column "Value"); the column says WHOSE
    value it is (`rule_kind`), not which field, so it is not part of the
    field the AI's "Rated power" is matched on."""
    name = fact.get("field_name") or datasheets.normalise_field_name(fact.get("field") or "")
    label, column = _label_column(fact)
    if column is None:
        return name
    if not fact.get("value_column"):
        return datasheets.normalise_field_name(label) or name
    column = datasheets.normalise_field_name(column)
    if column and name.endswith(" " + column):
        return name[:-len(column) - 1].strip()
    return name


def _key(fact: dict) -> tuple:
    return (fact.get("page"), field_key(fact))


def merge_readings(rule_facts: list[dict], ai_facts: list[dict]) -> list[dict]:
    """Merge the rule readers' facts and the AI reader's accepted facts.

    PURE: dicts in, decisions out, no database. Facts are matched by page and
    normalised field name, and only across compatible kinds (a rule fact
    whose column names no kind is compatible with any). Per field:

      * AGREED     - a rule fact and an AI fact of a compatible kind read the
                     same value: one fact, `{"rule", "ai"}`. When the rule
                     reading lost its unit and the AI's quote proves one
                     (`reading_relation` AI_UNIT), the decision carries
                     `"unit": <the AI's unit>` and the one fact takes it.
                     The same number in DIFFERENT units is a CONFLICT.
      * CONFLICT   - they read different values: BOTH kept, `{"rules": [...],
                     "ai": [...]}`, for an engineer. Never silently one. An AI
                     reading of the same kind as a pair that AGREED, with a
                     different value, is a conflict too: the page then states
                     two values where the rules read one, and the agreeing
                     reading is kept on the decision as `agreed_ai`.
      * AI_ONLY    - no rule fact of a compatible kind: `{"ai"}`.
      * RULES_ONLY - no AI reading of a compatible kind: `{"rule"}`. The
                     caller knows whether the AI read the page at all; when it
                     did, the fact is kept and recorded as unconfirmed
                     (`UNCONFIRMED`), never deleted and never raised.

    Deterministic: input order within a field, fields in (page, name) order.
    """
    groups: dict[tuple, tuple[list, list]] = {}
    for r in rule_facts:
        groups.setdefault(_key(r), ([], []))[0].append(r)
    for a in ai_facts:
        groups.setdefault(_key(a), ([], []))[1].append(a)

    def order(key):
        page, name = key
        return (page if page is not None else -1, name or "")

    out: list[dict] = []
    for key in sorted(groups, key=order):
        page, name = key
        rules, ais = groups[key]
        base = {"page": page, "field_name": name}
        # 1. Agreement, greedily, in input order. An AI reading not yet
        #    paired is preferred; failing one, a reading already paired may
        #    confirm a SECOND rule fact of the same value - two code readers
        #    (text and table) reading one cell are two facts the one AI
        #    reading confirms, and neither is left looking unconfirmed.
        partner: dict[int, int] = {}          # rule index -> ai index
        used_ai: set[int] = set()
        for ri, r in enumerate(rules):
            rk = rule_kind(r)
            fits = [ai_i for ai_i, a in enumerate(ais)
                    if (rk is None or rk == a.get("kind")) and values_agree(r, a)]
            fresh = [ai_i for ai_i in fits if ai_i not in used_ai]
            if fresh or fits:
                partner[ri] = (fresh or fits)[0]
                used_ai.add(partner[ri])

        def kind_of(ri: int) -> str | None:
            # A rule fact with no named column takes its partner's kind once
            # an AI reading agreed with it.
            return rule_kind(rules[ri]) or (
                ais[partner[ri]].get("kind") if ri in partner else None)

        # 2. Every AI reading left over contradicts each kind-compatible rule
        #    fact on this field - or, with none, stands alone.
        against: dict[int, list[int]] = {}    # rule index -> contradicting ai indexes
        alone: list[int] = []
        for ai_i, a in enumerate(ais):
            if ai_i in used_ai:
                continue
            compatible = [ri for ri in range(len(rules))
                          if kind_of(ri) is None or kind_of(ri) == a.get("kind")]
            # #501: A SECOND COPY OF A READING THAT AGREES IS NOT A CONFLICT.
            # The model sometimes reports one cell twice. The second copy was
            # left over after the first had paired, and every left-over
            # reading was taken as a contradiction without comparing it: the
            # same number and unit flagged the value for an engineer and two
            # true Meets became questions (a real sheet, 2026-10-12). Only a
            # reading whose VALUE differs contradicts.
            hits = [ri for ri in compatible if not values_agree(rules[ri], a)]
            for ri in hits:
                against.setdefault(ri, []).append(ai_i)
            if not compatible:
                alone.append(ai_i)
        for ri, r in enumerate(rules):
            if ri in against:
                decision = {**base, "outcome": CONFLICT, "rules": [r],
                            "ai": [ais[i] for i in against[ri]]}
                if ri in partner:
                    decision["agreed_ai"] = ais[partner[ri]]
                out.append(decision)
            elif ri in partner:
                a = ais[partner[ri]]
                decision = {**base, "outcome": AGREED, "rule": r, "ai": a}
                if reading_relation(r, a) == AI_UNIT:
                    decision["unit"] = ai_unit(a)
                out.append(decision)
            else:
                out.append({**base, "outcome": RULES_ONLY, "rule": r})
        out.extend({**base, "outcome": AI_ONLY, "ai": ais[i]} for i in alone)
    return out


def outcome_counts(decisions: list[dict]) -> dict[str, int]:
    counts = {AGREED: 0, CONFLICT: 0, AI_ONLY: 0, RULES_ONLY: 0}
    for d in decisions:
        counts[d["outcome"]] += 1
    return counts


__all__ = [
    "AGREED",
    "AGREED_CONFIDENCE",
    "AI_CONFIDENCE",
    "AI_ONLY",
    "AI_UNIT",
    "CLAUDE",
    "CONFLICT",
    "DIFFERENT",
    "ENGINES",
    "EXTRACTION_METHOD",
    "MAX_SPLITS",
    "OFF",
    "OLLAMA",
    "READER",
    "RULES_ONLY",
    "SAME",
    "STEP",
    "UNCONFIRMED",
    "UNIT_DIFFERS",
    "AnswerCutOff",
    "ai_unit",
    "engine_setting",
    "field_key",
    "header_kinds",
    "merge_readings",
    "model_call_for",
    "outcome_counts",
    "page_text",
    "parts_summary",
    "read_page_text_with_ai",
    "read_pages",
    "reading_relation",
    "rule_kind",
    "rule_unit",
    "same_unit",
    "split_text",
    "unit_in_quote",
    "using_model_call",
    "values_agree",
]
