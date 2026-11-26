"""The part of a query mail that is the message, apart from its signatures and legal notices (lead-4 and the planner, 26 Nov 2026: each
query showed the long notice twice, and the question finder read it).

ONE rule, block by block: a SIGNATURE (from a sign-off line such as "Best regards," or the "--" separator) and a NOTICE (a paragraph that
starts as a legal notice or says the mail is confidential, in English, German, French or Spanish) run to the next blank line and are taken
out wherever they stand; everything else stays, the quoted or forwarded earlier mail included (review of update 12, N5: a forward's
question sits below its forwarded-message header, and a rule line may stand above a question). `split_body` gives the page the message and
the removed blocks (folded behind "show"); `message_itself` gives the question finder the message without the header lines of quoted mail.
The stored text is never changed. No model.
"""

from __future__ import annotations

import re

_SIGNOFF = re.compile(
    r"^(--|(best|kind|warm|many|with)?\s*(regards|wishes|thanks)|thanks|thank you|thanks (and|&) regards|regards|sincerely|"
    r"yours sincerely|yours faithfully|cheers|mit freundlichen gr(ue|ü)(ss|ß)en|cordialement|saludos|atentamente)\s*[,.!]?$",
    re.IGNORECASE,
)
_NOTICE = re.compile(
    r"^(disclaimer|confidentiality( notice)?|important( notice)?|legal notice|privileged and confidential|haftungsausschluss|"
    r"avis de confidentialit|aviso legal|aviso de confidencialidad)\b|"
    r"\b(this (e-?mail|message|communication)\b.{0,80}\b(confidential|intended|privileged)|vertraulich|confidentiel|confidencial)\b",
    re.IGNORECASE,
)
_SENT_FROM = re.compile(r"^sent from my\b", re.IGNORECASE)
#: Header lines of quoted or forwarded earlier mail: kept on the page, left out of what the question finder reads.
_HEADER = re.compile(
    r"^(from|sent|date|to|cc|subject|von|gesendet|an|betreff|de|envoy[ée]|objet)\s*:\s|^on .{3,160} wrote:\s*$|"
    r"^-{2,}\s*(original|forwarded) message\s*-{2,}$|^_{5,}$|^-{5,}$",
    re.IGNORECASE,
)


def _blocks(lines: list[str]) -> tuple[list[str], list[str]]:
    """(kept lines, removed signature and notice lines)."""
    kept, removed, skipping = [], [], False
    for line in lines:
        stripped = line.strip()
        if (
            _SIGNOFF.match(stripped)
            or _NOTICE.search(stripped)
            or _SENT_FROM.match(stripped)
        ):
            skipping = True
        elif skipping and not stripped:  # a blank line ends the signature or the notice
            skipping = False
        if skipping:
            removed.append(line)
        else:
            kept.append(line)
    return kept, removed


def split_body(text: str | None) -> tuple[str, str]:
    """(the message, the signatures and notices taken out) of a mail body; the second is "" when there are none. Nothing is taken
    out when it would leave no message."""
    body = str(text or "")
    kept, removed = _blocks(body.splitlines())
    main = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if not main or not removed:
        return body, ""
    return main, "\n".join(removed).strip()


def message_itself(text: str | None) -> str:
    """What the question finder reads: the message without signatures, notices and the header lines of quoted or forwarded mail (the
    quoted message's own words stay: a forward's question is there)."""
    main, _ = split_body(text)
    lines = [line for line in main.splitlines() if not _HEADER.match(line.strip())]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
