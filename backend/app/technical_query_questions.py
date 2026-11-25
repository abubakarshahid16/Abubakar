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


def from_pages(context: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """`(proposals, note)`. A proposal is `{"question", "filename", "page"}`; the note is "" or `MODEL_UNAVAILABLE` (the pages are then
    shown to the engineer as they are, with no questions proposed)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in context:
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
