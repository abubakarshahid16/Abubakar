"""Claude-first chat (owner order 2026-09-27): Claude is the conversation
brain, and the system gives it tools.

Replaces the router+gate+template pipeline (`intent.route` -> `_document_
answer`/`chat_answers.small_talk`/`chat_answers.general`) for a DOCUMENT,
EITHER or GENERAL turn, WHEN Model=Claude and Claude is available. Every
other route (Web-consent, rewrite, action, records) is untouched - see
`chat.ask`'s call site. `answer()` returns None to mean "fall back to the
existing pipeline exactly as it is" (Model=Local, Claude unavailable, or the
FIRST call of the loop refused for budget/provider reasons); once a SECOND or
later call fails mid-loop, there is no clean way back to the old pipeline
(tool results already changed what would be searched), so that failure is
answered honestly instead, never silently swallowed.

SAFETY THIS MODULE MUST NOT WEAKEN (mirrors CLAUDE.md and the owner's own
list): every tool call is permission-scoped inside `chat_tools` before this
module ever sees a result (rule 5, intersection never union); every document
claim in the final text is run through `answer.verify_claims` - THE SAME
function the rest of the chat already uses - against the SAME numbered
sources the tools returned, so a citation that does not resolve is removed
and counted, never displayed; Claude never decides a compliance verdict (the
system prompt says so, and the caller still adds `intent.ENGINEER_NOTICE`
exactly as before for a compliance-shaped question); the budget is checked
by `claude_spend.ensure_affordable` before EVERY Claude call in the loop,
including each tool round-trip, because that check lives inside
`ClaudeProvider.reason`, not here - this module cannot bypass it by
constructing a Packet, only by not calling `reason` at all; Stop cancels the
loop within 2 s because `chat_stream.cancelled()` is checked before every
call this loop makes, and a Claude call already in flight is itself
cancellable (`ClaudeProvider.stream`/`_claude_stream`, the same mechanism the
existing pipeline uses).
"""

from __future__ import annotations

import re
import time

from . import chat_model, chat_tools, claude_spend
from . import reasoning_provider as rp
from .config import settings

CHAT_STEP = "chat"

#: Claude-first applies to a NEW question (not `explain_of`) when the caller
#: did not narrow to the local engine and Claude is actually usable.
def wants_claude_first(preference: str | None) -> bool:
    if preference == chat_model.LOCAL:
        return False
    ok, _why = chat_model.claude_ready()
    return ok


SYSTEM_PROMPT = """You are the RAG Intelligence assistant for KJO engineers, reviewing \
contractor submittals against specifications. Answer naturally and helpfully, the way \
Claude normally does - a short greeting gets a short, warm reply, not a canned template.

For anything about the user's documents or standards, use the tools you are given \
(search_documents, read_document, get_datasheet_fields, list_cited_standards, and \
look_at_page for images) rather than guessing. Use as many or as few tool calls as the \
question actually needs.

CITATION RULE, NON-NEGOTIABLE: every fact you state from a document must carry a \
citation in the exact form [Sn "the exact words on the page"], quoting VERBATIM from a \
numbered source a tool gave you - never paraphrase inside the quotation marks. A \
citation whose quote does not appear on the page it names is stripped before the reader \
sees it, so an invented quote helps nobody. When a fact came only from an image with no \
text layer (look_at_page will say so), write it in your own words and cite it as \
[Sn] with no quotation marks. Anything you know from general training rather than from a \
tool result must be clearly marked as general knowledge, in its own short section if the \
answer mixes both.

You never decide whether a submittal complies with a standard - that is an engineer's \
judgement, not yours. Describe what the documents say and let the reader (or the \
existing review workflow) draw that conclusion. If the documents do not contain \
something, say so plainly rather than guessing.

Answer in whatever format the user actually asked for - a paragraph, a short list, a \
table, simpler, or with more detail - and keep small talk brief and tool-free."""

#: Extended thinking (owner addendum 2026-09-27): only for a question shaped
#: like it needs real reasoning, not "hi" or a one-fact lookup.
_COMPLEX = re.compile(
    r"\b(compar|compliance|complian|comply|difference between|overview|summari|"
    r"summariz|across (all|both|these|the) document|multiple document|every "
    r"standard|gap analysis|does .* meet|conflict)", re.IGNORECASE)


def _is_complex(question: str) -> bool:
    return bool(_COMPLEX.search(question))


#: [Sn "quote"] (quote optional) - the same shape `answer.verify_claims` reads,
#: reused here only to relabel an IMAGE-ONLY citation before verify_claims
#: ever sees it (see module docstring and `chat_tools.run_look_at_page`).
_ANY_CITATION = re.compile(r'\[S(\d+)(?:\s*[:,]?\s*["“]([^"”\]]+)["”])?\]')


def _relabel_image_only_citations(text: str, sources: list[dict]) -> tuple[str, int]:
    """A citation naming a page `look_at_page` read with no text layer is not
    run through `verify_claims` (there is no page text to check a quote
    against) - it is relabelled here, kept, never silently dropped."""
    relabelled = 0

    def repl(match: re.Match) -> str:
        nonlocal relabelled
        n = int(match.group(1))
        if 1 <= n <= len(sources):
            s = sources[n - 1]
            if s.get("read_from_image") and not s.get("has_text_layer"):
                relabelled += 1
                return f"[{s['filename']}, page {s['page_start']}, read from image - check the page]"
        return match.group(0)

    return _ANY_CITATION.sub(repl, text), relabelled


def _source_block(n: int, s: dict) -> str:
    where = (f"{s['filename']}, page {s['page_start']}"
             if s.get("page_start") == s.get("page_end")
             else f"{s['filename']}, pages {s.get('page_start')}-{s.get('page_end')}")
    return f'[S{n}] ({where})\n{s["text"]}'


def _available_tools(*, web_enabled: bool) -> tuple[dict, ...]:
    tools = list(chat_tools.ALL_TOOLS)
    if web_enabled:
        from . import chat_web
        ok, _why = chat_web.available()
        if ok:
            tools.append(chat_tools.WEB_SEARCH)
    tools.append(chat_tools.LOOK_AT_PAGE)
    return tuple(tools)


class _Fallback(Exception):
    """The first Claude call could not run at all: tell the caller to use
    the existing pipeline, unchanged."""


def answer(question: str, *, history: str, allowed_document_ids: frozenset[str],
          web_enabled: bool, preference: str | None) -> dict | None:
    """One Claude-first turn, or None to fall back to the existing pipeline.

    `history` is the SAME permission-filtered, labelled-as-context string
    `chat_model.transcript(chat_model.history(...))` already builds for the
    old pipeline - nothing new is read from the conversation here.
    """
    from . import chat_stream

    if not wants_claude_first(preference):
        return None

    engine = chat_model.provider(preference)
    if not isinstance(engine, rp.ClaudeProvider):
        return None  # narrowed to local by the caller's own preference

    tools = _available_tools(web_enabled=web_enabled)
    messages: list[dict] = [{"role": "user", "content": question}]
    sources: list[dict] = []
    steps: list[dict] = []
    pages_used: list = []
    tool_calls_made = 0
    started = time.time()
    thinking_seconds: float | None = None
    used_thinking = _is_complex(question) and settings.chat_thinking_budget_tokens > 0

    system = SYSTEM_PROMPT
    if history:
        system = f"{system}\n\n{history}"

    turn = chat_stream.current()
    if turn is not None:
        # ONCE, not per loop iteration: `prepare` resets the sentence gate's
        # `shown`/buffer, and `sources` is handed by REFERENCE - a tool result
        # appended to it later is visible to the gate immediately, without
        # re-preparing (which would also erase what earlier turns already
        # showed, losing it from a cancelled answer's partial text).
        turn.prepare(passages=sources, verify=True, general=False)
    on_text = turn.text if turn is not None else (lambda _piece: None)

    def cancelled() -> bool:
        return bool(turn and turn.cancel.is_set())

    try:
        while True:
            if cancelled():
                return _cancelled(turn, sources, steps, started)
            offer_tools = tools if tool_calls_made < settings.chat_tool_max_calls else ()
            thinking_budget = (settings.chat_thinking_budget_tokens
                              if used_thinking and tool_calls_made == 0 else None)
            max_tokens = settings.chat_max_output_tokens + (thinking_budget or 0)
            packet = rp.Packet(
                prompt="", num_ctx=200_000, num_predict=max_tokens,
                temperature=settings.chat_temperature_document,
                system=system, step=CHAT_STEP, prompt_version="chat-claude-first-v1",
                messages=tuple(messages), tools=offer_tools, thinking_budget=thinking_budget,
                images=tuple(_images_for_accounting(sources)),
            )
            try:
                # STREAMED, never `.reason()`: `.stream()` is the only entry
                # point that takes `cancel`, and a call already in flight is
                # exactly what Stop must be able to interrupt within 2 s -
                # the same guarantee, through the same mechanism, the
                # existing pipeline already has. Document sentences stream
                # through the SAME sentence gate (`chat_stream`) the existing
                # pipeline uses, verified against `sources` as they arrive.
                response = engine.stream(packet, on_text, turn.cancel if turn else None)
            except (rp.ProviderRefused, claude_spend.BudgetExceeded) as exc:
                if tool_calls_made == 0 and not sources:
                    raise _Fallback(str(exc)) from exc
                return _budget_or_provider_failure(str(exc), sources, steps, started)
            if response.finish_reason == "cancelled":
                return _cancelled(turn, sources, steps, started)

            if thinking_budget:
                # `or 0.0`, never a falsy skip: a fast answer that still
                # thought is "Thought for under 1 s", not silence about it.
                thinking_seconds = response.wall_time_s or 0.0

            messages.append({"role": "assistant", "content": list(response.content_blocks) or
                             [{"type": "text", "text": response.text}]})

            tool_uses = [b for b in response.content_blocks if b.get("type") == "tool_use"]
            if response.finish_reason != "tool_use" or not tool_uses:
                if turn is not None:
                    turn.flush()
                return _finish(response, sources, steps, started, thinking_seconds)

            tool_results = []
            for block in tool_uses:
                if cancelled():
                    return _cancelled(turn, sources, steps, started)
                tool_calls_made += 1
                try:
                    run, image = chat_tools.dispatch(
                        block.get("name"), block.get("input") or {},
                        allowed_document_ids=allowed_document_ids, pages_used=pages_used)
                except chat_tools.ConsentRequired as consent:
                    from . import chat_web
                    result = chat_web.consent(consent.query, allowed_document_ids=allowed_document_ids)
                    result["route"] = "web"
                    return result
                first_n = len(sources) + 1
                sources.extend(run.sources_added)
                steps.append({"label": run.label, "count": len(run.sources_added) or None,
                             "done": run.ok})
                content: list[dict] = []
                if run.sources_added:
                    blocks_text = "\n\n".join(
                        _source_block(first_n + i, s) for i, s in enumerate(run.sources_added))
                    content.append({"type": "text", "text": blocks_text})
                    if image is not None:
                        content.append({"type": "image", "source": {
                            "type": "base64", "media_type": image.media_type, "data": image.data}})
                elif run.note:
                    content.append({"type": "text", "text": run.note})
                else:
                    content.append({"type": "text", "text": "no results"})
                tool_results.append({"type": "tool_result", "tool_use_id": block.get("id"),
                                    "content": content,
                                    **({"is_error": True} if not run.ok else {})})
            messages.append({"role": "user", "content": tool_results})
    except _Fallback:
        return None


def _images_for_accounting(sources: list[dict]):
    """`packet.images` is read only for the pre-call budget estimate
    (`ClaudeProvider.reason`'s `image_tokens`) - the images themselves already
    ride inside `messages`'s tool_result blocks, built above."""
    from .reasoning_provider import PageImage

    out = []
    for s in sources:
        if s.get("read_from_image"):
            # A rendered page is capped well under vision_reader's own
            # MAX_EDGE_PX; this is a worst-case estimate, not the real size.
            out.append(PageImage("image/png", "", 1500, 1500))
    return out


#: Fields `schemas.AnswerResult` requires with no default - every result dict
#: this module returns must carry them, whichever branch built it.
_REQUIRED_DEFAULTS = {"retrieval_mode": "claude_tools", "reranked": False,
                     "candidates_considered": 0, "timings": {}}


def _cancelled(turn, sources: list[dict], steps: list[dict], started: float) -> dict:
    # THE SAME RULE `answer.stopped` uses: what the reader was already shown
    # (sentences that already passed the quote-verification gate), never more.
    partial = " ".join(turn.shown).strip() if turn is not None else ""
    return {**_REQUIRED_DEFAULTS, "answer_type": "cancelled", "answer": partial or None,
           "reason": "stopped by the reader",
           "cancelled": True, "passages": sources, "steps": steps, "cited": [], "claims": [],
           "seconds": round(time.time() - started, 3)}


def _budget_or_provider_failure(message: str, sources: list[dict], steps: list[dict],
                                started: float) -> dict:
    return {**_REQUIRED_DEFAULTS, "answer_type": "model_unavailable", "answer": None,
           "reason": f"the spending cap would be exceeded partway through this answer: {message}",
           "passages": sources, "steps": steps, "cited": [], "claims": [],
           "seconds": round(time.time() - started, 3)}


def _finish(response, sources: list[dict], steps: list[dict], started: float,
           thinking_seconds: float | None) -> dict:
    from . import answer as answer_mod

    text = (response.text or "").strip()
    used_tools = bool(sources)
    verification = claims = None
    removed = 0
    image_relabelled = 0
    if used_tools:
        text, image_relabelled = _relabel_image_only_citations(text, sources)
        text, verification, claims, removed = answer_mod.verify_claims(text, sources)
    else:
        text = answer_mod.drop_citations(text)
    if used_tools and not text:
        return {**_REQUIRED_DEFAULTS, "answer_type": "insufficient_evidence", "answer": None,
               "reason": "none of the answer's points could be found on the pages read",
               "passages": sources, "steps": steps, "verification": verification,
               "claims_removed": removed, "cited": [], "claims": [],
               "provider": response.provider, "model": response.model_tag,
               "cost_usd": response.cost_usd, "seconds": round(time.time() - started, 3),
               "candidates_considered": len(sources)}
    cited = sorted({c["n"] for c in (claims or [])})
    base = {
        **_REQUIRED_DEFAULTS,
        "answer_type": "generated" if used_tools else "general",
        "answer": text, "reason": None,
        "passages": sources, "cited": cited, "claims": claims or [],
        "claims_removed": removed, "verification": verification,
        "steps": steps, "input_kind": "document" if used_tools else "general",
        "provider": response.provider, "model": response.model_tag,
        "cost_usd": response.cost_usd, "seconds": round(time.time() - started, 3),
        "candidates_considered": len(sources),
        "truncated": response.truncated, "rejected_citations": [],
    }
    if thinking_seconds is not None:
        base["thought_seconds"] = round(thinking_seconds, 1)
    if image_relabelled:
        base["notices"] = [f"{image_relabelled} point(s) were read from a page image with no "
                           "text layer - check the page"]
    return base
