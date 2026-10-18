"""#456 (C-H5): one output cap per model-call route, and a reply the cap cut
off is a NAMED state - `truncated` - never a complete answer.

WHY. Every route used to pick its own `max_tokens` where it built its request
(a literal in one module, a setting in another, `reader_api.ReaderSettings`'s
512 for whoever forgot), and whether a reply had hit that cap was checked in
some callers and not others: `analysis.py` compared `finish_reason` with
`"max_tokens"` when both engines report `"length"`, so a cut-off summary read
as complete; the Claude `model_call(prompt) -> str` lane dropped the stop
reason altogether, so a half-written JSON object reached a parser as
"malformed" and its cause was lost. Measured twice in Phase A and once on a
real datasheet (#501): half an answer parsed as a whole one.

WHAT. `ROUTE_MAX_TOKENS` is the one table. A route is a short stable name; its
value is either a token count or the NAME of a `Settings` field, so a cap the
owner tunes in `.env` stays tunable and still has one home. A route not in the
table gets `DEFAULT_MAX_TOKENS`, the lane's previous global value, so nothing
unlisted changes silently.

`state_of` turns an engine's stop reason into one of three words. `COMPLETE`
may be parsed. `TRUNCATED` is raised (`Truncated`) or returned by name and is
never parsed, cached or stored as a verdict. `UNKNOWN` is a reply that cannot
be read at all (nothing came back, the engine reported an error). Logs carry
route names and token counts only, never reply text (rule 1).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ----------------------------------------------------------------- routes

ROUTE_DATASHEET_READ = "datasheet_read"
ROUTE_SELECT_STANDARDS = "select_standards"
ROUTE_MATCH = "match"
ROUTE_CRS_WORDING = "crs_wording"
ROUTE_APPLICABILITY = "applicability"
ROUTE_CLAUSE_APPLICABILITY = "clause_applicability"
ROUTE_ENGINEERING_CHECK = "engineering_check"
ROUTE_CHAT = "chat"
ROUTE_RECHECK = "recheck"

#: `reader_api.ReaderSettings.max_tokens`, the lane's previous global value:
#: one sentence in, one small JSON object out. A test pins the two equal.
DEFAULT_MAX_TOKENS = 512

#: route -> output cap: an int, or the name of the `Settings` field that
#: holds it (read when asked, so a change in `.env` applies).
ROUTE_MAX_TOKENS: dict[str, int | str] = {
    #: A whole page of facts (#501: 512 cut a dense page mid-fact).
    ROUTE_DATASHEET_READ: "datasheet_ai_claude_max_tokens",
    #: A short list of standard indexes with one reason each.
    ROUTE_SELECT_STANDARDS: 512,
    #: One index and one sentence (`schemas.PairChoice`).
    ROUTE_MATCH: 200,
    #: One reworded CRS comment.
    ROUTE_CRS_WORDING: 300,
    #: yes / no / unsure, a reason code and a quote.
    ROUTE_APPLICABILITY: 400,
    #: The clause-applicability AI task (`ai_applicability.TASK`).
    ROUTE_CLAUSE_APPLICABILITY: 300,
    #: The full engineering check: many items, owner-tunable.
    ROUTE_ENGINEERING_CHECK: "review_ai_check_max_output_tokens",
    #: Chat answers, owner-tunable.
    ROUTE_CHAT: "chat_max_output_tokens",
    #: agree / disagree, a reason and a quote - twice per finding.
    ROUTE_RECHECK: 600,
}


def max_tokens_for(route: str | None) -> int:
    """This route's output cap, or `DEFAULT_MAX_TOKENS` for a route the
    table does not list. A setting-backed entry is read now, not at import."""
    value = ROUTE_MAX_TOKENS.get(str(route or ""), DEFAULT_MAX_TOKENS)
    if isinstance(value, str):
        from ..config import settings
        value = getattr(settings, value)
    return int(value)


# ----------------------------------------------------------------- states

COMPLETE = "complete"
TRUNCATED = "truncated"
UNKNOWN = "unknown"
STATES = (COMPLETE, TRUNCATED, UNKNOWN)

#: The stop reasons that mean "the cap ended it": Ollama's `done_reason`
#: (`length`) and Anthropic's `stop_reason` (`max_tokens`), either spelling.
LENGTH_STOPS = frozenset({"length", "max_tokens"})
#: Nothing readable came back: no stop reason at all, or the engine's own
#: error word (`reasoning_provider._answered` for an empty payload).
UNREADABLE_STOPS = frozenset({"", "error"})


class Truncated(RuntimeError):
    """The reply hit its output cap. It is not an answer and is never parsed
    as one; the caller reports `TRUNCATED` and stores no verdict."""

    state = TRUNCATED

    def __init__(self, route: str | None, tokens_out: int | None = None) -> None:
        self.route = str(route or "")
        self.tokens_out = tokens_out
        super().__init__(f"{TRUNCATED}: the {self.route or 'model'} reply hit its output cap")


class Unreadable(RuntimeError):
    """Nothing readable came back (an empty or error reply). The caller
    reports `UNKNOWN`: it could not check, and says so."""

    state = UNKNOWN

    def __init__(self, route: str | None, finish_reason: str = "") -> None:
        self.route = str(route or "")
        self.finish_reason = finish_reason
        super().__init__(f"{UNKNOWN}: no readable {self.route or 'model'} reply")


def state_of(finish_reason: str | None, text: str | None) -> str:
    """One of `STATES` for a reply with this stop reason and this text.
    The cap is checked FIRST: a length stop with text is still truncated."""
    reason = str(finish_reason or "").strip().lower()
    if reason in LENGTH_STOPS:
        return TRUNCATED
    if reason in UNREADABLE_STOPS or not str(text or "").strip():
        return UNKNOWN
    return COMPLETE


def state_of_payload(payload) -> str:
    """`state_of` for a raw Anthropic Messages payload (the `model_call`
    lane, before `reader_api.response_text` flattens it)."""
    from ..reader_api import response_text
    if not isinstance(payload, dict):
        return UNKNOWN
    return state_of(payload.get("stop_reason"), response_text(payload))


def state_of_response(response) -> str:
    """`state_of` for a `reasoning_provider.Response`."""
    return state_of(getattr(response, "finish_reason", ""), getattr(response, "text", ""))


def complete_text(response, route: str | None) -> str:
    """`response.text` when the reply is complete; `Truncated` when the cap
    ended it; `Unreadable` when nothing readable came back. The one check a
    caller about to parse JSON or store a verdict makes."""
    state = state_of_response(response)
    if state == TRUNCATED:
        _log(route, TRUNCATED, getattr(response, "tokens_out", None))
        raise Truncated(route, getattr(response, "tokens_out", None))
    if state == UNKNOWN:
        _log(route, UNKNOWN, getattr(response, "tokens_out", None))
        raise Unreadable(route, str(getattr(response, "finish_reason", "") or ""))
    return str(response.text)


def _log(route: str | None, state: str, tokens_out) -> None:
    # Route name, state and a count only - never the reply (rule 1).
    log.info("model reply %s: route=%s tokens_out=%s", state, route or "-", tokens_out)


# ------------------------------------------------- the `model_call` lane

def model_call_for(transport, route: str, *, cfg=None, env=None, salvage: bool = False):
    """`reader_api.model_call_via` with THIS route's cap and the named
    states. `transport` is a metered Messages transport
    (`claude_spend.metered(...)`); the returned `model_call(prompt) -> str`
    raises `Truncated` when the reply hit the cap and `Unreadable` when no
    text came back, so no caller parses either as an answer.

    `salvage=True` names the state in the log and returns the text as it
    stands (empty for an unreadable reply) instead of raising, for the ONE
    caller that walks a cut-off JSON array for the complete items before
    the cut and marks the page `cut_off` itself, and reports an empty reply
    as its own named error (`claude_datasheet.parse_or_cut`, owner-measured,
    #501)."""
    import dataclasses

    from .. import reader_api

    base = cfg if cfg is not None else reader_api.ReaderSettings.from_env(env)
    cfg = dataclasses.replace(base, max_tokens=max_tokens_for(route))

    def model_call(prompt: str) -> str:
        request = reader_api.build_request(prompt, cfg=cfg, env=env)
        payload = transport(request["url"], headers=request["headers"],
                            body=request["body"], timeout=request["timeout"])
        state = state_of_payload(payload)
        if state == COMPLETE:
            return reader_api.response_text(payload)
        answer = payload if isinstance(payload, dict) else {}
        tokens_out = (answer.get("usage") or {}).get("output_tokens")
        _log(route, state, tokens_out)
        if salvage:
            return reader_api.response_text(payload) if state == TRUNCATED else ""
        if state == TRUNCATED:
            raise Truncated(route, tokens_out)
        raise Unreadable(route, str(answer.get("stop_reason") or ""))

    model_call.route = route
    model_call.max_tokens = cfg.max_tokens
    return model_call


__all__ = [
    "COMPLETE",
    "DEFAULT_MAX_TOKENS",
    "LENGTH_STOPS",
    "ROUTE_APPLICABILITY",
    "ROUTE_CHAT",
    "ROUTE_CLAUSE_APPLICABILITY",
    "ROUTE_CRS_WORDING",
    "ROUTE_DATASHEET_READ",
    "ROUTE_ENGINEERING_CHECK",
    "ROUTE_MATCH",
    "ROUTE_MAX_TOKENS",
    "ROUTE_RECHECK",
    "ROUTE_SELECT_STANDARDS",
    "STATES",
    "TRUNCATED",
    "UNKNOWN",
    "Truncated",
    "Unreadable",
    "complete_text",
    "max_tokens_for",
    "model_call_for",
    "state_of",
    "state_of_payload",
    "state_of_response",
]
