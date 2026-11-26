"""The questions a contractor's query attachment asks, proposed ONE BY ONE with their page, for an engineer to confirm each (order 14, F4).

Before, every new line of the first five pages was copied into one block of text. Now the LOCAL model reads one page at a time and lists
each separate question it finds; a proposal is kept only if its words stand on that page as printed (a question the model made up is
dropped), and it carries its file and page. Nothing here is an answer, a verdict or a pass: the engineer ticks the questions that are
real and confirms them. No document text leaves the machine (the local engine only, never Claude). A page whose reading fails says so;
it never makes up questions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

STEP = "technical_query_questions"
PROMPT_VERSION = "tq-questions-v1"
MAX_PER_PAGE = 12
MAX_TOTAL = 30
MODEL_UNAVAILABLE = "model_unavailable"
SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
}
SYSTEM = (
    "You read ONE page of a query a contractor sent to an engineer. List every separate technical question the page asks, each copied "
    "EXACTLY as printed (same words, same numbers). Do not answer, summarise, merge, reword or add anything. A heading, a label, a "
    "reference number or a statement is not a question. If the page asks nothing, return an empty list."
)


def _squash(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _ask(page_text: str) -> list[str]:
    """The model's list for one page. Raises when the local model cannot answer."""
    from . import reasoning_provider as rp

    packet = rp.Packet(
        prompt="Page text:\n" + page_text[:12000],
        num_ctx=8192,
        num_predict=1500,
        json_schema=SCHEMA,
        system=SYSTEM,
        step=STEP,
        prompt_version=PROMPT_VERSION,
        timeout_s=240.0,
    )
    response = rp.OllamaProvider(timeout=240.0).reason(packet)
    data = json.loads(response.text or "{}")
    return [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()]


def from_pages(
    context: list[dict[str, Any]], progress=None
) -> tuple[list[dict[str, Any]], str]:
    """`(proposals, note)`. A proposal is `{"question", "filename", "page"}`; the note is "" or `MODEL_UNAVAILABLE` (the pages are then
    shown to the engineer as they are, with no questions proposed)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, part in enumerate(context, 1):
        if progress:
            progress(
                n - 1, len(context), f"reading attachment page {n} of {len(context)}"
            )
        page_text = str(part.get("text") or "")
        if not page_text.strip():
            continue
        try:
            found = _ask(page_text)
        except Exception as exc:  # noqa: BLE001 - logged and said on the query: the engineer writes the questions, nothing is invented
            log.warning(
                "technical query: questions not proposed (%s)", type(exc).__name__
            )
            return out, MODEL_UNAVAILABLE
        printed = _squash(page_text)
        for question in found[:MAX_PER_PAGE]:
            key = _squash(question)
            if (
                key and key in printed and key not in seen
            ):  # only words that stand on the page as printed
                seen.add(key)
                out.append(
                    {
                        "question": question,
                        "filename": part.get("filename"),
                        "page": part.get("page"),
                    }
                )
        if len(out) >= MAX_TOTAL:
            return out[:MAX_TOTAL], ""
    return out, ""


#: A form's question field label ("Question:", "Query", "Description of query", "Details of the query"), alone or before its text.
_FIELD = re.compile(
    r"^\s*(technical\s+)?(question|query|description|clarification required|details of (the )?(query|question)|description of (the )?"
    r"(query|question))\s*(:|-|$)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
#: The next field of the form ends the question's text.
_NEXT_FIELD = re.compile(
    r"^\s*(answer|reply|response|proposed (answer|solution)|contractor|company|date|ref(erence)?|attachments?|prepared by|"
    r"signature|remarks|discipline|status|originator)\b.{0,40}[:\-]?\s*$|^\s*(answer|reply|response)\s*[:\-]",
    re.IGNORECASE,
)
MAX_FIELD = 1200


def form_question(context: list[dict[str, Any]]) -> str:
    """The text of the attached form's own question field (the first one found, as printed, at most MAX_FIELD characters), or "" when
    the form has none. Used when the model proposed no question and the mail itself asks nothing (lead-4, 26 Nov 2026): the question is
    never taken from the mail's introduction."""
    for part in context:
        lines = str(part.get("text") or "").splitlines()
        for i, line in enumerate(lines):
            if not (field := _FIELD.match(line)):
                continue
            taken = [field.group("rest").strip()] if field.group("rest").strip() else []
            for following in lines[i + 1 :]:
                if _NEXT_FIELD.match(following) or (not following.strip() and taken):
                    break
                if following.strip():
                    taken.append(following.strip())
            text = " ".join(taken).strip()
            if text:
                return text[:MAX_FIELD]
    return ""
