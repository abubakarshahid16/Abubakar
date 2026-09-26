"""The chat's model lane: which engine answers, what it is told, what it costs.

OWNER DECISION 2026-09-24/25: the Claude API is the chat's reader and reasoner,
through the one approved transport (`reader_transport`, via
`reasoning_provider.ClaudeProvider`) and under the USD caps `claude_spend`
enforces BEFORE each call. The local Ollama engine stays the offline fallback.
Which one answers is decided by `reasoning_provider.get_provider` - Claude only
when REASONING_PROVIDER=claude AND both standards-reader egress flags AND a key
are set - and the reader may narrow it to the local engine per question. They
can never widen it: choosing Claude when it is not configured still gets the
local engine, and the answer says which engine wrote it.

CONVERSATION MEMORY, AND WHAT IT IS NOT. The model is shown the recent turns of
the conversation so "that", "in points" and "more detail" mean something. It
is shown them as CONTEXT, never as a source: retrieval still reads documents
only (`chat.resolve_followup` uses earlier USER questions and nothing else), a
document claim still has to cite a passage retrieved for THIS question, and the
prompt says outright that the conversation may not be cited. So a wrong earlier
answer can shape the wording of the next one but cannot become its evidence -
the guarantee `chat.py` states is kept where it matters, at the citation.

PERMISSIONS FIRST. History is read through `chat.get_messages`, which withholds
every assistant turn citing a document the caller can no longer read, and a
withheld turn is dropped here entirely - its placeholder text is not sent
either. The filtering happens before a single character is assembled.
"""
from __future__ import annotations

import re

from . import model_transport
from . import reasoning_provider as rp
from .config import settings

#: The budget step every chat call is charged to in the Claude ledger.
CHAT_STEP = "chat"

#: A turn's text is cut to this many characters before it enters the history,
#: so one long quoted passage cannot crowd out every other turn.
TURN_CHARS = 1200

#: Characters per token for the history budget. Generous (English runs nearer
#: four), so the budget errs towards sending less.
CHARS_PER_TOKEN = 3

LOCAL = "local"
CLAUDE = "claude"
#: What the reader may ask for. "auto" is the configured default.
PREFERENCES = ("auto", CLAUDE, LOCAL)


def claude_ready() -> tuple[bool, str]:
    """Whether the Claude lane is configured, and if not, why (never the key)."""
    return rp.claude_available()


def available_models() -> dict:
    """What the composer's Model menu may offer - only what can actually run.

    The local engine is listed as available because it is the configured
    fallback; whether Ollama is up is a health question answered elsewhere
    (System Health), and a model that is down is reported on the answer.
    """
    ok, why = claude_ready()
    models = [
        {"id": CLAUDE, "label": "Claude", "model": settings.claude_reasoning_model,
         "available": ok, "reason": None if ok else why},
        {"id": LOCAL, "label": "Local model", "model": settings.answer_model,
         "available": True, "reason": None},
    ]
    return {"default": CLAUDE if ok else LOCAL, "models": models}


def provider(preference: str | None = None) -> rp.ReasoningProvider:
    """The engine for this answer. A preference can only NARROW to local."""
    if (preference or "auto") == LOCAL:
        return rp.OllamaProvider()
    return rp.get_provider("reasoning", step=CHAT_STEP)


# ----------------------------------------------------------------- history

def history(conversation_id: str, *, allowed_document_ids: frozenset[str],
            before_ordinal: int | None = None, max_turns: int | None = None,
            token_budget: int | None = None) -> list[dict]:
    """The recent turns the model may see, oldest first, as {role, text}.

    Read through `chat.get_messages` - permissions applied there, withheld
    turns dropped here. Newest turns are kept first when the budget runs out,
    because the nearest turn is the one "that" points at. `before_ordinal`
    excludes the turn being answered and anything after it.
    """
    from . import chat

    max_turns = settings.chat_history_turns if max_turns is None else max_turns
    budget_chars = (settings.chat_history_token_budget if token_budget is None
                    else token_budget) * CHARS_PER_TOKEN
    turns = []
    for message in chat.get_messages(conversation_id, allowed_document_ids=allowed_document_ids):
        if before_ordinal is not None and message["ordinal"] >= before_ordinal:
            continue
        if (message.get("payload") or {}).get("withheld"):
            continue
        text = _turn_text(message)
        if text:
            turns.append({"role": message["role"], "text": text})
    kept: list[dict] = []
    used = 0
    for turn in reversed(turns[-max_turns:] if max_turns else []):
        if used + len(turn["text"]) > budget_chars:
            break
        kept.append(turn)
        used += len(turn["text"])
    return list(reversed(kept))


#: A citation marker from an EARLIER answer. It pointed at that answer's
#: sources, not this one's; left in, the model reads "[S1]" in the history as
#: if it named the first source it is about to be given.
_OLD_CITATION = re.compile(r"\s*\[S\d+\]")


def _turn_text(message: dict) -> str:
    text = " ".join(_OLD_CITATION.sub("", message.get("text") or "").split())
    if not text and message["role"] == "assistant":
        # A refusal has no answer text; the model still needs to know one
        # happened, or "try again" and "why not" have nothing to point at.
        reason = message.get("reason")
        text = f"(no answer given: {reason})" if reason else ""
    if len(text) > TURN_CHARS:
        text = text[:TURN_CHARS].rstrip() + " ..."
    return text


def transcript(turns: list[dict]) -> str:
    """The history as a prompt block, labelled as context and not a source."""
    if not turns:
        return ""
    lines = [f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['text']}" for t in turns]
    return ("Conversation so far (context only - it is NOT a source; never cite it, "
            "and never repeat a fact from it unless a numbered source below states it):\n"
            + "\n".join(lines) + "\n\n")


# ---------------------------------------------------------------- generate

def generate(system: str, prompt: str, *, temperature: float, preference: str | None = None,
             timeout: float = 180.0) -> dict:
    """One answer, from whichever engine this chat uses.

    Returns the Ollama-shaped dict `answer.py` already reads (`response`,
    `done_reason`, `model`, token counts), plus `provider` and `cost_usd`.
    The local branch sends exactly the body it always did, with the local
    output cap; Claude gets the chat cap (`chat_max_output_tokens`), a cached
    system block, and the spend check before the call leaves.

    Raises `claude_spend.BudgetExceeded` when the next call could cross a cap
    (nothing was sent), `reasoning_provider.ProviderRefused` when the engine
    would not answer, and lets `model_transport.ModelHostRefused` through.
    """
    engine = provider(preference)
    if isinstance(engine, rp.ClaudeProvider):
        response = engine.reason(rp.Packet(
            prompt=prompt, system=system, num_ctx=settings.num_ctx,
            num_predict=settings.chat_max_output_tokens, temperature=temperature,
            step=CHAT_STEP, prompt_version="chat-v1", timeout_s=timeout))
        return {
            "response": response.text,
            "done_reason": response.finish_reason,
            "model": response.model_tag,
            "prompt_eval_count": response.tokens_in,
            "eval_count": response.tokens_out,
            "provider": rp.CLAUDE,
            "cost_usd": response.cost_usd,
        }
    body = {
        "model": settings.answer_model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            # The local cap, not the chat cap: this engine's window must hold
            # the evidence as well (context_budget subtracts this number).
            "num_predict": settings.max_output_tokens,
            "num_ctx": settings.num_ctx,
            "num_thread": settings.num_thread,
            "num_batch": settings.num_batch,
        },
        # hold the model resident between turns so the cold load is paid once
        "keep_alive": "30m",
    }
    raw = model_transport.post_json("/api/generate", body, timeout=timeout)
    return {**raw, "provider": rp.OLLAMA, "cost_usd": None}
