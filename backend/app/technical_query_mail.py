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
from collections import Counter
from functools import lru_cache

from .technical_query_items import ITEM_MARK

_SIGNOFF = re.compile(
    r"^(--|(best|kind|warm|many|with)?\s*(regards|wishes|thanks)|thanks|thank you|(thanks|thank you|many thanks)\s*(and|&|,)\s*"
    r"((best|kind|warm)\s+)?regards|rgds|regards|sincerely|"
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
    r"este (correo|mensaje)\b.{0,60}\bconfidencial)|"
    # the other common notice shape (lead-4, 26 Nov 2026: 54 stored notices said neither "this e-mail" nor "disclaimer"): it names
    # the intended recipient AND says confidential, in one line
    r"^(?=.*\bconfidential)(?=.*\bintended (recipient|addressee|solely|only)\b)",
    re.IGNORECASE,
)
#: A line that asks or requests something: a block holding one is never taken out, whatever it starts with. A notice's own requests
#: ("please notify the sender and delete it") are not questions.
_ASK_WORDS = re.compile(
    r"\b(please|kindly|request|advise|confirm|clarify|could you|can you|would you)\b",
    re.IGNORECASE,
)
#: A request inside a line beyond a pointer's own "please": a question mark or a verb that asks something of the engineer.
_REQUEST_IN = re.compile(
    r"\?|\b(request|advise|confirm|clarify|approve|could you|can you|would you|let us know whether)\b",
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
    main = _CID.sub("", split_body(text)[0])
    return re.sub(
        r"\n{3,}", "\n\n", "\n".join(_without_headers(main.splitlines()))
    ).strip()


#: A picture's place-holder in a mail's text ("[cid:image001.png@...]"): never words of the message.
_CID = re.compile(r"\[cid:[^\]]*\]", re.IGNORECASE)


#: The address-list header lines (To, Cc, Bcc) whose wrapped lines follow them.
_LIST_HEADER = re.compile(r"^(to|cc|bcc|an|para)\s*:", re.IGNORECASE)


def _address_list(line: str) -> bool:
    """A line that is a list of people: two or more addresses, an address with a semicolon, or short NAMES joined by semicolons - never a
    line that asks something ("Please confirm: (a) size; (b) rating; (c) material?" is a question; review of update 14, R2)."""
    if line.count("@") >= 2 or ("@" in line and ";" in line):
        return True
    parts = [p for p in line.split(";") if p.strip()]
    return (
        len(parts) >= 3
        and not _REQUEST_IN.search(line)
        and all(len(p.split()) <= 4 for p in parts)
    )


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


#: A line that only points to the attachment ("Please find attached our TQ ...", "Attached is ...") asks nothing of its own, whatever
#: words its title holds (lead-4, 26 Nov 2026: the live intro was proposed as the question).
_COVER = re.compile(
    r"\b(please|kindly)\W+(find|see|refer to|note|review)\b[^?]{0,80}?\b(attach|enclos)|^\W*(attached|enclosed)\W+(is|are|please|herewith)\b|"
    r"\b(attached|enclosed) herewith\b|\bwe (are )?(attach|enclos|send|submit|forward)(ing|ed)?\b|"
    # a short line that says "attached" and names a TQ or CFC ("Please, find attached our TQ: <number> - <title>"; lead-4, 26 Nov 2026)
    r"^(?=.{0,240}$)(?=.*\b(attach(ed)?|enclosed)\b)(?=.*\b(tq|cfc|technical query|query)\b)",
    re.IGNORECASE,
)
#: A courtesy line ("Please do not hesitate to contact us", "Let us know if you need anything"): it asks nothing of the engineer.
_COURTESY = re.compile(
    r"\b(do not|don't) hesitate\b|\bfeel free\b|\blet (us|me) know\b|\bshould you (have|need|require)\b|\bif you (have|need|require) any\b|"
    r"\bfor your (information|reference|records|kind (attention|review|information))\b|\bthank(s| you)\b",
    re.IGNORECASE,
)
#: A greeting line ("Dear All,", "Hi Team"): never question text.
_GREETING = re.compile(
    r"^(dear|hi|hello|greetings|good (morning|afternoon|evening))\b[^.?!]{0,60}[,!:]?$",
    re.IGNORECASE,
)


def _question_line(line: str) -> bool:
    """A line that can be question text: not a greeting, and not a line that only points to the attachment or is a courtesy."""
    stripped = line.strip()
    pointer = _COVER.search(stripped) or _COURTESY.search(stripped)
    # a pointer line that also asks for something ("We submit the attached TQ; confirm the rating") is question text (R2)
    return not _GREETING.match(stripped) and not (
        pointer and not _REQUEST_IN.search(stripped)
    )


#: A line that names the question ("Question: ...", "Query - ..."): the question starts there.
_QUESTION_MARK = re.compile(r"^\s*(question|query)\s*[:\-]\s*", re.IGNORECASE)
NO_QUESTION = "No question in the email text."


#: A web address (a link wrapper's "?" is not a question mark).
_URL = re.compile(r"<?\bhttps?://\S+>?", re.IGNORECASE)
#: A line in at least this many of a mailbox's received messages (and in at least BOILERPLATE_SHARE of them) is boilerplate - a footer
#: or a standing notice every mail carries - and never question text (lead-4, 26 Nov 2026: one footer line made every stored mail "ask").
BOILERPLATE_MIN = 5
BOILERPLATE_SHARE = 0.3


#: An e-mail address inside a line.
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
#: The longest text shown as the question in the mail: a question is a sentence or a short block, not a third of the mail.
QUESTION_CAP = 600
#: A line that starts a numbered or lettered item ("1.", "2)", "(3)", "a.", "(b)", "i)") or a bullet: an item of the request's list.
_ITEM = re.compile(
    rf"(?m)^\s*{ITEM_MARK}\s+\S"
)  # the same marker the item splitter uses (technical_query_items.ITEM_MARK)
#: A request that is a LIST of items may be longer than one question: up to this, then cut with a visible mark.
LIST_CAP = 6000
LIST_CUT = "… The rest of the list is in the email files."


def _norm(line: str) -> str:
    return " ".join(_URL.sub(" ", line).split()).casefold()


@lru_cache(maxsize=8)
def _repeated(bodies: tuple[str, ...]) -> frozenset[str]:
    if len(bodies) < BOILERPLATE_MIN:
        return frozenset()
    counts: Counter[str] = Counter()
    for body in bodies:
        counts.update(
            {_norm(line) for line in body.splitlines() if len(_norm(line)) >= 20}
        )
    need = max(BOILERPLATE_MIN, int(len(bodies) * BOILERPLATE_SHARE))
    return frozenset(line for line, n in counts.items() if n >= need)


def boilerplate(mailbox_id: str | None) -> frozenset[str]:
    """The lines repeated across a mailbox's received messages (normalised), read from the stored mail; empty for a query by hand."""
    if not mailbox_id:
        return frozenset()
    from .db import connect

    with connect() as conn:
        rows = conn.execute(
            "SELECT body FROM query_messages WHERE mailbox_id=? AND is_inbound=1 ORDER BY id",
            (mailbox_id,),
        ).fetchall()
    return _repeated(tuple(r[0] or "" for r in rows))


def email_question(text: str | None, common: frozenset[str] = frozenset()) -> str:
    """The question in a mail's own text, by the CURRENT rules (computed each time, never trusted from an older stored copy): the message
    itself without headers, people lists, picture place-holders, web addresses, greetings, signatures, notices, lines repeated across the
    mailbox (`common`, from `boilerplate`) and lines that only point to the attachment, from a "Question:" line when there is one; "" when
    nothing in it asks anything."""
    message = message_itself(text)
    lines = message.splitlines()
    marked = next(
        (i for i, line in enumerate(lines) if _QUESTION_MARK.match(line)), None
    )
    if marked is not None:
        message = "\n".join(
            [_QUESTION_MARK.sub("", lines[marked], count=1), *lines[marked + 1 :]]
        ).strip()
    kept = [
        _URL.sub("", line).rstrip()
        for line in message.splitlines()
        if _question_line(line)
        and _norm(line) not in common
        and (not line.strip() or _URL.sub("", line).strip())
    ]
    # a line holding an e-mail address (a template line, a forwarded header) is never question text (lead-4, F's test on update 13)
    kept = [line for line in kept if not _ADDRESS.search(line)]
    # only the paragraphs that ask: a signature's left-over lines (a name, a telephone number) are not the question
    paragraphs = re.split(r"\n\s*\n", "\n".join(kept))
    asking = [any(_asks(line) for line in p.splitlines()) for p in paragraphs]
    # A NUMBERED LIST is the request's substance when the mail asks something (lead-4's blind test of the owner's approved answers,
    # 26 Nov 2026: a request lists its conflicts as statements 1-8 and only its closing "Accordingly, COMPANY is requested to confirm
    # ..." asks; every item was dropped, so the reply answered a vague question). Every paragraph holding an item is kept with it.
    listed = [bool(_ITEM.search(p)) for p in paragraphs]
    # the line that introduces the list ("We note the following conflicts:") says what the items are: kept with them
    leads = [
        p.rstrip().endswith(":") and n + 1 < len(paragraphs) and listed[n + 1]
        for n, p in enumerate(paragraphs)
    ]
    question = "\n\n".join(
        p.strip()
        for p, a, n, lead in zip(paragraphs, asking, listed, leads, strict=True)
        if a or ((n or lead) and any(asking))
    ).strip()
    if (
        any(asking) and any(listed)
    ):  # a list of requests: never dropped for its length; cut with a visible mark (rule: no silent cut)
        from .technical_query_items import cut_whole_words

        return cut_whole_words(question, LIST_CAP, LIST_CUT)
    if (
        len(question) > QUESTION_CAP
    ):  # a long block is not a question: only its asking lines, and none when even those are long
        question = "\n".join(line.strip() for line in kept if _asks(line)).strip()
    return question if len(question) <= QUESTION_CAP else ""


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
    question = (
        (saved or "").strip()
        if typed
        else email_question(source, boilerplate(first.get("mailbox_id")))
    )
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


#: A paragraph at least this long that an EARLIER mail on the same query page already shows is folded in the later mail.
REPEAT_CHARS = 80


def _key(paragraph: str) -> str:
    """A paragraph as compared across mails: quote marks ("> ") and spacing do not count."""
    return (
        re.sub(r"\s+", " ", re.sub(r"(?m)^\s*(>\s*)+", "", paragraph)).strip().lower()
    )


def page_bodies(texts: list[str | None]) -> list[tuple[str, str]]:
    """`page_body` for every mail of one query page, oldest first, with the earlier mail a reply quotes shown once (lead-4, 26 Nov 2026:
    a reply quoting the thread showed the same paragraphs and notices up to five times on one page). A paragraph of REPEAT_CHARS or
    more that an earlier mail on the page already shows moves to the later mail's folded part, and the later mail says so in one line;
    nothing is cut without that mark, the full text is behind "show", and the stored text is never changed."""
    shown: set[str] = set()
    out: list[tuple[str, str]] = []
    for text in texts:
        main, folded = page_body(text)
        kept: list[str] = []
        moved: list[str] = []
        for paragraph in re.split(r"\n\s*\n", main):
            key = _key(paragraph)
            (moved if len(key) >= REPEAT_CHARS and key in shown else kept).append(
                paragraph
            )
        if moved:
            mark = f"({len(moved)} paragraph{'s' if len(moved) != 1 else ''} of earlier mail already shown above on this page: under show)"
            main = "\n\n".join([*kept, mark])
            folded = "\n\n".join(part for part in ("\n\n".join(moved), folded) if part)
        shown.update(
            k
            for k in (_key(p) for p in re.split(r"\n\s*\n", main))
            if len(k) >= REPEAT_CHARS
        )
        out.append((main, folded))
    return out
