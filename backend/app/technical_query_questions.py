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
PROMPT_VERSION = "tq-questions-v2"
MAX_PER_PAGE = 12
MAX_TOTAL = 30
MODEL_UNAVAILABLE = "model_unavailable"
#: Why nothing was proposed, recorded on the query and said on its page (lead-4, 26 Nov 2026: an empty proposal with no reason was a hidden
#: failure): the AI listed no question at all, or every one it listed was not word for word on the page (so it was dropped).
NONE_FOUND = "none_found"
NOT_ON_PAGE = "not_on_page"
SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
}
SYSTEM = (
    "You read ONE page of a query a contractor sent to an engineer. List every separate technical question the page asks, each copied "
    "EXACTLY as printed (same words, same numbers). A request the contractor makes of the engineer counts as a question even without a "
    "question mark: a point to confirm, approve, clarify or answer, often a numbered point under a heading such as Question. Do not "
    "answer, summarise, merge, reword or add anything. A heading, a label, a reference number or a plain statement of fact is not a "
    "question. If the page asks nothing, return an empty list."
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
    """`(proposals, note)`. A proposal is `{"question", "filename", "page"}`; the note is "" when something was proposed, else why not:
    `MODEL_UNAVAILABLE`, `NONE_FOUND` or `NOT_ON_PAGE` (the pages are then shown to the engineer as they are)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    listed = 0
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
        listed += len(found)
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
    if out or not any(str(part.get("text") or "").strip() for part in context):
        return out, ""
    return out, NOT_ON_PAGE if listed else NONE_FOUND


#: A form's question field label ("Question:", "Query", "Description of query", "Details of the query"), alone or before its text.
_FIELD = re.compile(
    r"^\s*(technical\s+)?(question|query|description|clarification required|details of (the )?(query|question)|description of (the )?"
    r"(query|question))\s*(?P<sep>:|-|$)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
#: The next field of the form ends the question's text.
_NEXT_FIELD = re.compile(
    r"^\s*(answer|reply|response|proposed (answer|solution)|contractor|company|date|ref(erence)?|attachments?|prepared by|"
    r"signature|remarks|discipline|status|originator)\b.{0,40}[:\-]?\s*$|^\s*(answer|reply|response)\s*[:\-]",
    re.IGNORECASE,
)
#: A short heading standing alone that names the request (six words at most, below the form's title lines): "Question", or a CFC form's
#: heading naming the contractor's clarification (lead-4, 26 Nov 2026: learned from the label shapes of the stored forms, quoting none).
_SECTION_LABEL = re.compile(
    r"^(?!.*\b(cfc|tq)\b)(?=.*\b(clarifications?|questions?|query|queries)\b)[^\W\d][\w'\u2019/&() .-]{0,58}:?\s*$",
    re.IGNORECASE,
)
TITLE_LINES = 3
#: A references block at the start of a question section: skipped up to the next blank line (the request follows it).
_REFERENCES = re.compile(r"^\s*references?\s*:?\s*$", re.IGNORECASE)
#: A section heading that ends a question SECTION (a label standing alone, the form's next part): the answer, approval or sign-off part.
_SECTION_END = re.compile(
    r"^\s*(answer|reply|response|approved|approval|signature|name|position|date|company|contractor('s)? (proposal|response)|"
    r"proposed (answer|solution)|query no\.?|to be (answered|completed|filled)\b.*)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
MAX_FIELD = 1200
CUT = " [cut here: the rest of the section is in the attachment text]"


def form_question(context: list[dict[str, Any]]) -> str:
    """The text of the attached form's own question field, as printed (the first one found), or "" when the form has none. A label with
    its text on the same line ("Question: ...") gives that text up to the next field or a blank line; a label standing ALONE (a section
    heading, "Question") gives its whole section, blank lines included, up to the next section heading (lead-4, 26 Nov 2026: the real
    forms hold a section of numbered requests with no question mark). Longer than MAX_FIELD: cut with a visible mark. Used when the model
    proposed no question and the mail itself asks nothing: the question is never taken from the mail's introduction."""
    for part in context:
        lines = str(part.get("text") or "").splitlines()
        for i, line in enumerate(lines):
            field = _FIELD.match(line)
            heading = (
                i >= TITLE_LINES
                and len(line.split()) <= 6
                and _SECTION_LABEL.match(line.strip())
            )
            if field and field.group(2).lower() == "query" and not field.group("sep"):
                field = None  # "Technical Query" alone is the form's title, not its question field
            if not field and not heading:
                continue
            rest = field.group("rest").strip() if field else ""
            taken = [rest] if rest else []
            section: list[str] = []
            for following in lines[i + 1 :]:
                if rest and (_NEXT_FIELD.match(following) or not following.strip()):
                    break
                if not rest and _SECTION_END.match(following):
                    break
                section.append(following)
            body = [line for line in section if line.strip()]
            if not rest and body and _REFERENCES.match(body[0]):
                # a references block first: skipped up to the next blank line, when one ends it (else nothing is skipped)
                start = next((n for n, line in enumerate(section) if line.strip()), 0)
                blank = next(
                    (
                        n
                        for n in range(start + 1, len(section))
                        if not section[n].strip()
                    ),
                    None,
                )
                if blank is not None and any(line.strip() for line in section[blank:]):
                    body = [line for line in section[blank:] if line.strip()]
            taken += [line.strip() for line in body]
            text = " ".join(taken).strip()
            if text:
                return (
                    text if len(text) <= MAX_FIELD else text[:MAX_FIELD].rstrip() + CUT
                )
    return ""
