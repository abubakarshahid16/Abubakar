"""The chat's non-document answers: general knowledge, rewrites, actions, records.

OWNER ORDER 2026-09-26 (chat redesign, 2c). The document pipeline
(`answer.answer`) is unchanged and still the only way a document claim reaches
the reader. Everything here either
  * answers from the model's general knowledge - LABELLED as such, never
    carrying a document citation, never creating a finding; or
  * re-renders the PREVIOUS answer in a new style without searching again -
    a document answer keeps exactly its sources, and its rewritten claims are
    checked against those same passages like any other; or
  * searches the workflow records (`structured_search`), as the Chat screen's
    old records box did.

No function here records a verdict, writes a finding or edits a review. An
action answer returns a DRAFT for the reader to confirm (section 2g).
"""
from __future__ import annotations

from . import answer as answer_mod
from . import chat_model
from . import claude_spend
from . import intent as intent_mod
from . import reasoning_provider as rp
from .config import settings
from .rates import Timer

GENERAL_SYSTEM = """You are the chat assistant in an engineering document system. This question is answered from your GENERAL knowledge, not from the user's documents.

Rules:
- Lead with a short, direct answer. Then bullet points if they help. End with "What I'd do:" only when there is a practical next step.
- Be accurate and plain. If you are not sure, say so. Give SI units first.
- Never claim to have read the user's documents, and never cite a document, page or clause: this answer is labelled general knowledge.
- Never state that anything is compliant, approved or acceptable - that is an engineer's decision.
- Follow any style the user asks for (points, one paragraph, simpler, more detail, for an engineer).
- Use markdown: **bold**, bullet lists, short tables when they help. No preamble."""

#: What each rewrite style asks the model for.
STYLE_WORDS = {
    "points": "as short bullet points",
    "paragraph": "as one short paragraph",
    "more_detail": "with more detail",
    "shorter": "shorter - keep only what matters",
    "simpler": "simply, for someone who is not an engineer, with an everyday comparison",
    "engineer": "for an engineer - precise, technical, with units",
    "manager": "as a short summary for a manager - the decision, the risk, the next step",
}


def instruction(styles: list[str]) -> str:
    words = [STYLE_WORDS[s] for s in styles if s in STYLE_WORDS]
    return " and ".join(words)


def _engine_label(provider: str | None) -> str:
    return "Claude" if provider == rp.CLAUDE else "Local model"


def _failed(base: dict, exc: Exception, timer: Timer) -> dict:
    if isinstance(exc, claude_spend.BudgetExceeded):
        reason = f"the Claude spending cap would be exceeded, so no answer was generated ({exc})"
    elif isinstance(exc, rp.ProviderRefused):
        reason = f"the answer model would not answer ({str(exc).split(':')[0]})"
    else:
        reason = f"the answer model could not be reached ({type(exc).__name__})"
    return {**base, "answer_type": "model_unavailable", "answer": None, "reason": reason,
            "seconds": timer.seconds()}


def _base(question: str, input_kind: str) -> dict:
    return {"question": question, "retrieval_mode": "not_searched", "reranked": False,
            "timings": {}, "candidates_considered": 0, "passages": [], "examples": [],
            "input_kind": input_kind}


def _generate(system: str, prompt: str, temperature: float, preference: str | None) -> dict:
    answer_mod._prepare_stream(None, general=True)
    return chat_model.generate(system, prompt, temperature=temperature, preference=preference)


# ------------------------------------------------------------- general

def general(question: str, *, styles: list[str], history: str, preference: str | None,
            input_kind: str = "general_question") -> dict:
    """A general-knowledge answer. Never searched, never cited, always labelled."""
    timer = Timer()
    base = _base(question, input_kind)
    style = instruction(styles)
    prompt = f"{history}Question: {question}" + (f"\n\nAnswer {style}." if style else "")
    try:
        raw = _generate(GENERAL_SYSTEM, prompt, settings.chat_temperature_general, preference)
    except Exception as exc:  # noqa: BLE001 - reported as unavailable, never a crash
        return _failed(base, exc, timer)
    if raw.get("cancelled"):
        return answer_mod.stopped(base, raw, timer)
    text = answer_mod.strip_half_citation((raw.get("response") or "").strip())
    # A general answer may not carry a document citation, whatever the model
    # wrote: "[S1]" here would point at no source at all.
    text = answer_mod.drop_citations(text)
    if not text:
        return {**base, "answer_type": "model_unavailable", "answer": None,
                "reason": "the model returned no answer", "seconds": timer.seconds()}
    return {**base, "answer_type": "general", "answer": text, "reason": None,
            "truncated": raw.get("done_reason") == "length",
            "model": raw.get("model"), "provider": raw.get("provider"),
            "cost_usd": raw.get("cost_usd"), "seconds": timer.seconds()}


# ------------------------------------------------------------- rewrite

def _previous_passages(previous: dict) -> list[dict]:
    payload = previous.get("payload") or {}
    if previous.get("answer_type") == "generated":
        return list(payload.get("passages") or [])
    if previous.get("answer_type") == "extract":
        return list(payload.get("answer_passages") or
                    ([payload["passage"]] if payload.get("passage") else []))
    return []


def rewrite(previous: dict | None, *, styles: list[str], history: str, preference: str | None,
            question: str, extra: str = "", kind: str = "rewrite") -> dict:
    """Re-render the previous answer. A document answer keeps its sources and
    its rewritten claims are checked against them exactly as a fresh answer's."""
    timer = Timer()
    base = _base(question, kind)
    if previous is None or not (previous.get("text") or "").strip():
        return {**base, "answer_type": "guidance", "reason": None,
                "answer": "There is no earlier answer in this conversation to rework yet - ask a question first.",
                "seconds": timer.seconds()}
    how = " and ".join(p for p in (instruction(styles), extra) if p) or "more clearly"
    passages = _previous_passages(previous)
    if not passages:
        prompt = (f"{history}Previous answer:\n{previous['text']}\n\n"
                  f"Rewrite the previous answer {how}. Keep its meaning; add nothing it did not say.")
        try:
            raw = _generate(GENERAL_SYSTEM, prompt, settings.chat_temperature_general, preference)
        except Exception as exc:  # noqa: BLE001
            return _failed(base, exc, timer)
        if raw.get("cancelled"):
            return answer_mod.stopped(base, raw, timer)
        text = answer_mod.drop_citations(raw.get("response") or "")
        return {**base, "answer_type": "general", "answer": text or None, "reason": None,
                "rewrite_of": previous["id"], "model": raw.get("model"),
                "provider": raw.get("provider"), "cost_usd": raw.get("cost_usd"),
                "seconds": timer.seconds()}
    # A DOCUMENT answer: the same passages, numbered as before, and the
    # rewrite goes through the document answer's own citation checks.
    instruction_text = (f"Rewrite the previous answer {how}. Use only the numbered sources; "
                        f"keep every claim cited.\n\nPrevious answer:\n{previous['text']}")
    result = answer_mod.generate_from_passages(
        instruction_text, passages, history=history, preference=preference, timer=timer,
        base={**base, "retrieval_mode": "reused", "rewrite_of": previous["id"]})
    return result


# ------------------------------------------------------------- records

def records(query: str, *, allowed_document_ids: frozenset[str], include_unowned: bool) -> dict:
    """The workflow-records search the old Chat screen offered, now "/records"."""
    from . import structured_search

    timer = Timer()
    base = _base(query, "records")
    if not query.strip():
        return {**base, "answer_type": "records", "reason": None, "records": [],
                "answer": "Type what to look for after /records - for example: /records pump seal",
                "seconds": timer.seconds()}
    # The same scope the records box used: the caller's documents, plus the
    # rows with no document only for the admin capability.
    found = structured_search.search(query, allowed_document_ids=allowed_document_ids,
                                     include_unowned=include_unowned)
    lines = [f"- **{r.get('title') or r.get('label') or r.get('id')}**"
             + (f" - {r['kind']}" if r.get("kind") else "") for r in found[:10]]
    text = (f"Found {len(found)} workflow record{'' if len(found) == 1 else 's'} for \"{query}\":\n"
            + "\n".join(lines)) if found else f"No workflow records match \"{query}\"."
    return {**base, "answer_type": "records", "answer": text, "reason": None,
            "records": found[:10], "seconds": timer.seconds()}


def small_talk(kind: str, *, examples: list[str]) -> dict:
    ok, _ = chat_model.claude_ready()
    who = ("Answers are written by Claude: your question and the passages it needs are sent to it, "
           "within the spending caps set for this system." if ok else
           "Answers are written by the local model on this machine; nothing you type leaves it.")
    return {**_base("", kind), "answer_type": "guidance",
            "answer": intent_mod.small_talk_reply(kind, provider_line=who),
            "reason": None, "examples": examples, "seconds": 0.0}
