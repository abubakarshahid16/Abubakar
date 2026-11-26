"""The part of a query mail that is the message itself, apart from its signature, legal notices and quoted earlier mail (lead-4 and the
planner, 26 Nov 2026: each query showed the long disclaimer twice, and the question finder read it).

ONE rule (`split_body`), used by the page (the rest is folded behind "show") and by the question finder (which reads only the message
itself). The stored text is never changed. The rule cuts at the FIRST line that starts a signature, a notice or a quoted earlier mail;
when that is the first line, nothing is cut (a mail is never folded away whole). No model.
"""

from __future__ import annotations

import re

_STARTS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^(--|__+|-{3,})\s*$",  # the conventional signature separator, or a rule line
        r"^(best|kind|warm|many|with)?\s*(regards|wishes|thanks)\s*[,.!]?$",
        r"^(thanks|thank you|thanks and regards|thanks & regards|regards|sincerely|yours sincerely|cheers)\s*[,.!]?$",
        r"^(disclaimer|confidentiality( notice)?|important( notice)?|legal notice|privileged and confidential)\b",
        r"^this (e-?mail|message|communication)\b.{0,80}\b(confidential|intended|privileged)",
        r"^on .{3,160} wrote:\s*$",  # a quoted earlier mail
        r"^-{2,}\s*(original|forwarded) message\s*-{2,}$",
        r"^sent from my\b",
    )
]
_FROM = re.compile(r"^from:\s*\S", re.IGNORECASE)
_SENT = re.compile(r"^(sent|date):\s*\S", re.IGNORECASE)


def split_body(text: str | None) -> tuple[str, str]:
    """(the message itself, the rest: signature, notices and quoted mail) of a mail body. The rest is "" when nothing is cut."""
    body = str(text or "")
    lines = body.splitlines()
    for n, line in enumerate(lines):
        stripped = line.strip()
        starts = any(rx.search(stripped) for rx in _STARTS) or (
            _FROM.search(stripped)
            and any(
                _SENT.search(x.strip()) for x in lines[n + 1 : n + 4]
            )  # a quoted header block
        )
        if starts and n > 0 and "\n".join(lines[:n]).strip():
            return "\n".join(lines[:n]).rstrip(), "\n".join(lines[n:]).strip()
    return body, ""


def message_itself(text: str | None) -> str:
    """The message itself (`split_body`): what the question finder reads."""
    return split_body(text)[0]
