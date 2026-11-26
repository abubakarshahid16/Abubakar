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
#: A LEGAL NOTICE only (review of update 12, R4: "Important: please confirm ...?" is a question, not a notice): it starts as one, or it
#: says the mail is confidential / meant for the addressee.
_NOTICE = re.compile(
    r"^(disclaimer|confidentiality notice|legal notice|privileged and confidential|haftungsausschluss|avis de confidentialit|"
    r"aviso legal|aviso de confidencialidad)\b|"
    r"\bthis (e-?mail|message|communication)\b.{0,80}\b(confidential|intended (only )?for|privileged)\b|"
    r"\b(diese (e-?mail|nachricht)\b.{0,60}\bvertraulich|ce (courriel|message)\b.{0,60}\bconfidentiel|"
    r"este (correo|mensaje)\b.{0,60}\bconfidencial)",
    re.IGNORECASE,
)
#: A line that asks or requests something: a block holding one is never taken out, whatever it starts with. A notice's own requests
#: ("please notify the sender and delete it") are not questions.
_ASK_WORDS = re.compile(
    r"\b(please|kindly|request|advise|confirm|clarify|could you|can you|would you)\b",
    re.IGNORECASE,
)
_NOTICE_WORDS = re.compile(
    r"\b(sender|delete|destroy|notify|recipient|addressee|unauthori[sz]ed|prohibited|virus|disclos)",
    re.IGNORECASE,
)


def _asks(line: str) -> bool:
    return "?" in line or bool(
        _ASK_WORDS.search(line) and not _NOTICE_WORDS.search(line)
    )


_SENT_FROM = re.compile(r"^sent from my\b", re.IGNORECASE)
#: Header lines of quoted or forwarded earlier mail: kept on the page, left out of what the question finder reads.
_HEADER = re.compile(
    r"^(from|sent|date|to|cc|bcc|subject|classification|sensitivity|importance|von|gesendet|an|betreff|de|envoy[ée]|objet|para)\s*:\s|"
    r"^on .{3,160} wrote:\s*$|"
    r"^-{2,}\s*(original|forwarded) message\s*-{2,}$|^_{5,}$|^-{5,}$",
    re.IGNORECASE,
)


def _blocks(lines: list[str]) -> tuple[list[str], list[str]]:
    """(kept lines, removed signature and notice lines). A block runs from its first line to the next blank line; it is taken out only
    when nothing in it asks or requests something (a question is never dropped)."""
    kept: list[str] = []
    removed: list[str] = []
    block: list[str] | None = None

    def close() -> None:
        if block is not None:
            (kept if any(_asks(x) for x in block) else removed).extend(block)

    for line in lines:
        stripped = line.strip()
        starts = bool(
            _SIGNOFF.match(stripped)
            or _NOTICE.search(stripped)
            or _SENT_FROM.match(stripped)
        )
        if (
            block is not None and not stripped
        ):  # a blank line ends the signature or the notice
            close()
            block = None
        if starts and block is None:
            block = []
        if block is not None:
            block.append(line)
        else:
            kept.append(line)
    close()
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
    return re.sub(
        r"\n{3,}", "\n\n", "\n".join(_without_headers(main.splitlines()))
    ).strip()


#: The address-list header lines (To, Cc, Bcc) whose wrapped lines follow them.
_LIST_HEADER = re.compile(r"^(to|cc|bcc|an|para)\s*:", re.IGNORECASE)


def _address_list(line: str) -> bool:
    """A line that is a list of people: two or more addresses, or names joined by semicolons."""
    return line.count("@") >= 2 or line.count(";") >= 2 or ("@" in line and ";" in line)


def _without_headers(lines: list[str]) -> list[str]:
    """The lines without the header lines of quoted or forwarded mail, the wrapped lines of a To / Cc list, and any line that is a list
    of people (lead-4, 26 Nov 2026: a forward's 40-name Cc list was shown as the question)."""
    out: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if _HEADER.match(stripped):
            in_list = bool(_LIST_HEADER.match(stripped))
            continue
        wrapped = (
            in_list
            and stripped
            and (";" in stripped or "@" in stripped or stripped.endswith(","))
        )
        in_list = bool(wrapped)
        if not wrapped and not _address_list(stripped):
            out.append(line)
    return out


#: A line that only points to the attachment ("Please find attached ...") asks nothing of its own.
_COVER = re.compile(
    r"\b(please|kindly)\s+(find|see|refer to|note|review)\b.{0,60}\b(attach|enclos)",
    re.IGNORECASE,
)
#: A line that names the question ("Question: ...", "Query - ..."): the question starts there.
_QUESTION_MARK = re.compile(r"^\s*(question|query)\s*[:\-]\s*", re.IGNORECASE)
NO_QUESTION = "No question in the email text."


def email_question(text: str | None) -> str:
    """The question in a mail's own text, by the CURRENT rules (computed each time, never trusted from an older stored copy): the message
    itself without headers, people lists, signatures and notices, from a "Question:" line when there is one; "" when nothing in it asks
    anything (a cover note such as "please find attached" does not)."""
    message = message_itself(text)
    lines = message.splitlines()
    marked = next(
        (i for i, line in enumerate(lines) if _QUESTION_MARK.match(line)), None
    )
    if marked is not None:
        message = "\n".join(
            [_QUESTION_MARK.sub("", lines[marked], count=1), *lines[marked + 1 :]]
        ).strip()
    asks = any(_asks(line) and not _COVER.search(line) for line in message.splitlines())
    return message if asks else ""


def shown_question(query: dict) -> dict[str, str]:
    """What the query page shows as "Question in the email": recomputed from the first received mail's body (a question typed in by hand,
    `saved`, for a query entered by hand), the signatures and notices folded, and when the mail asks nothing, a note naming the attachment
    the question is in (lead-4, 26 Nov 2026)."""
    from .technical_queries import original_email_question

    messages, proposals = (
        query.get("messages") or [],
        query.get("proposed_questions") or [],
    )
    saved = original_email_question(query.get("extracted_question"))
    first = next(
        (m for m in messages if m.get("is_inbound", 1)), messages[0] if messages else {}
    )
    typed = (
        first.get("provider") in (None, "manual", "synthetic") and (saved or "").strip()
    )
    source = saved if typed else first.get("body")
    question = (saved or "").strip() if typed else email_question(source)
    note = ""
    if not question:
        files = [p.get("filename") for p in proposals or [] if p.get("filename")] + [
            a["filename"]
            for m in messages
            for a in m.get("attachments", [])
            if a.get("document_id") and not a.get("inline_picture")
        ]
        note = NO_QUESTION + (
            f" The question is in the attachment: {files[0]}; "
            + (
                "the proposed question below comes from it."
                if proposals
                else "Prepare evidence to get a proposed question from it."
            )
            if files
            else ""
        )
    return {
        "extracted_question_main": question,
        "extracted_question_folded": split_body(source)[1],
        "email_question_note": note,
    }


#: A list of more people than this is folded on the query page: "To/Cc: 43 people" (lead-4, 26 Nov 2026).
PEOPLE_SHOWN = 5


def _people(lines: list[str]) -> int:
    text = " ".join(
        line.split(":", 1)[-1] if _LIST_HEADER.match(line.strip()) else line
        for line in lines
    )
    return text.count("@") or len([p for p in re.split(r"[;\n]", text) if p.strip()])


def page_body(text: str | None) -> tuple[str, str]:
    """`split_body` for the query page, with every To / Cc list of quoted or forwarded mail longer than PEOPLE_SHOWN people folded to one
    line ("To/Cc: 43 people"); the full list goes to the folded part, shown only on "show"."""
    main, folded = split_body(text)
    out: list[str] = []
    held: list[list[str]] = []
    block: list[str] = []

    def close() -> None:
        if block:
            many = _people(block) > PEOPLE_SHOWN
            out.append(f"To/Cc: {_people(block)} people" if many else "\n".join(block))
            held.extend([block[:]] if many else [])
            block.clear()

    for line in main.splitlines():
        stripped = line.strip()
        if _LIST_HEADER.match(stripped) or (
            block
            and stripped
            and (";" in stripped or "@" in stripped or stripped.endswith(","))
        ):
            block.append(line)
            continue
        close()
        out.append(line)
    close()
    extra = "\n\n".join("\n".join(b) for b in held)
    return "\n".join(out), "\n\n".join(part for part in (folded, extra) if part)
