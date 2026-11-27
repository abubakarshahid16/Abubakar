"""Checks on a technical query's draft reply BEFORE it is kept (owner, 27 Nov 2026 12:32 PKT, on the live Queries page: "hard to read, too
much text, some answers look wrong"; lead-4's order: two code checks, plus one cost/schedule message).

A reply is COMPANY's words to a contractor, so:

  1. NO FIRST-PERSON ADVICE. The local model sometimes ends with "What I'd do: ..." although the query-reply prompt forbids it. That
     paragraph is cut out of the reply and kept beside it as a note for the engineer (`split_advice`); it never reaches the contractor.
     Any first person left after that ("I would ...", "I recommend ...") is a fault (`first_person`): the draft is written again once,
     then stopped with a plain note, as a false quote is.
  2. EVERY [Sn] IS A SOURCE THIS REPLY WAS GIVEN. The answer lane drops a tag whose number it did not supply (`rejected_citations`) and
     keeps the sentence; in a reply that leaves a claim with no source at all. Here a dropped tag, or a tag in the text that is not one of
     the reply's own cited sources, is a fault (`unknown_sources`). The citation rows themselves are matched by `citations_of`.
  3. A COMPANY POSITION WITH A SOURCE. A sentence that states COMPANY's position ("COMPANY confirms ...", "COMPANY does not accept ...")
     and cites no source is marked on the reply for the engineer (`unsourced_positions`); it is not stopped: the engineer may know it.
  4. ONE COST / SCHEDULE MESSAGE. The page always offers COMPANY's usual cost/schedule sentence beside the reply
     (`technical_query_position`), so the prompt's old stand-in sentence is taken out of a new draft (`drop_cost_standin`).

Text handling only, on this computer; nothing is sent anywhere. Nothing here decides an engineering answer.
"""

from __future__ import annotations

import re
from typing import Any

#: A paragraph that opens with first-person advice: "What I'd do:", "**What I would do**", "My recommendation:", "- My advice ...".
_ADVICE_HEAD = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?\s*(?:what\s+i(?:['’]d|\s+would)\s+do|my\s+(?:advice|recommendation|suggestion))\b",
    re.IGNORECASE,
)
#: First person in a sentence (outside quotation marks). "I" alone is not matched: it is also a part or class numeral ("Schedule I").
_FIRST_PERSON = re.compile(
    r"(?<![\w'’])(?:I['’](?:d|ll|m|ve)|I\s+(?:would|recommend|suggest|think|believe|advise|propose|can|will|have|am|need|feel)"
    r"|[Mm]y\s+(?:view|advice|recommendation|suggestion|opinion|understanding)|[Ii]n\s+my\s+(?:view|opinion))(?![\w'’])"
)
#: Words that make a following "I" a numeral, not a person ("Schedule I would apply" is not first person).
_NUMERAL_BEFORE = re.compile(
    r"(?:schedule|attachment|annex|appendix|exhibit|part|phase|class|type|zone|division|section|volume|grade|category|level|stage|"
    r"article|table|figure|item)\s*$",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'["“][^"“”\n]*["”]')
_LABEL = re.compile(r"\[S(\d+)")
_ITEM_START = re.compile(r"^\s*(?:[-*•]\s*)?(?:\*\*)?\s*(?:\d{1,2}[.)]|(?:items?|requests?)\s+\d)", re.IGNORECASE)
_BULLET = re.compile(r"^\s*[-*•]\s+")
#: The stand-in the query-reply prompt used to ask for; the page now offers COMPANY's usual sentence instead.
_COST_STANDIN = re.compile(r"\s*\**COMPANY to confirm the cost and schedule position\.?\**", re.IGNORECASE)
#: A sentence that states COMPANY's position (not "COMPANY to confirm ...", which leaves it open).
_POSITION = re.compile(
    r"\bCOMPANY\s+(?:hereby\s+)?(?:confirms|accepts|agrees|approves|requires|rejects|finds|considers|has\s+no\s+objection|"
    r"does\s+not\s+(?:accept|agree|approve|object)|cannot\s+accept|is\s+not\s+in\s+agreement)\b"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: A request's answer that is only "Yes." / "No." / "Partly." (the prompt forbids a bare one: it hides what was found, N3).
_BARE = re.compile(r"^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*(?:\d{1,2}[.)]\s*)?(?:\*\*)?\s*(?:yes|no|partly)\s*[.!]?\s*(?:\*\*)?\s*$", re.IGNORECASE)
#: A sentence that states a cost or schedule POSITION (not only a money or time word): only with a source may it stand in the reply.
_COST_POSITION = re.compile(
    r"\b(?:COMPANY|impact|change\s+orders?|variation\s+orders?|variations?|entitle\w*|compensat\w*|no\s+(?:basis|grounds)|"
    r"extensions?\s+of\s+time|reimburs\w*|claims?)\b",
    re.IGNORECASE,
)
#: A last line that stops mid-sentence: it ends on a lower-case word or a comma, colon, semicolon or dash (N1).
_MID_SENTENCE = re.compile(r"[a-z,;:\u2013-]\s*$")

#: The note when a draft still speaks as "I" after the advice was taken out (shown where the reply would be).
FIRST_PERSON_NOTE = (
    "the draft spoke as “I” instead of as COMPANY, so it is not shown: press Write the reply again (under Redo), "
    "or write the reply yourself"
)
#: The note when a draft names a source it was not given.
UNKNOWN_SOURCE_NOTE = (
    "the draft named a source it was not given, so it is not shown: press Write the reply again (under Redo), "
    "or write the reply yourself"
)
#: The note when a draft was cut off before its end (the model stopped mid-sentence, N1).
CUT_OFF_NOTE = (
    "the draft stopped in the middle of a sentence, so it is not shown: press Write the reply again (under Redo), "
    "or write the reply yourself"
)
#: The note when a request is answered with a bare "Yes." or "No." (N3).
BARE_NOTE = (
    "the draft answered a request with a bare \u201cYes\u201d or \u201cNo\u201d, so it is not shown: press Write the reply again "
    "(under Redo), or write the reply yourself"
)
#: The mark on a cost or schedule sentence with no source, taken out of the reply (for the engineer only).
COST_MARK = "The AI also wrote about cost or schedule with no source. It is not part of the reply: "
#: The mark beside the reply on the advice that was taken out of it (for the engineer only).
ADVICE_MARK = "The AI also gave advice. It is not part of the reply to the contractor: "
#: The mark on an older AI draft (written before these checks) that speaks as "I"; such a draft is not approved.
FIRST_PERSON_MARK = "This reply speaks as \u201cI\u201d, not as COMPANY."
#: The mark on a COMPANY position that cites no source.
UNSOURCED_MARK = "A COMPANY position in this reply cites no source. Check it before you approve."


def split_advice(answer: str) -> tuple[str, str | None]:
    """The reply without its first-person advice paragraphs, and that advice (None when there was none). An advice paragraph runs from
    its heading line to the next blank line, with the bullet lines straight after it; a numbered answer after it stays in the reply."""
    lines = (answer or "").replace("\r", "").split("\n")
    kept: list[str] = []
    advice: list[str] = []
    cutting = False
    for line in lines:
        if _ADVICE_HEAD.match(line):
            cutting = True
            advice.append(line.strip())
            continue
        if cutting:
            if not line.strip():
                cutting = "blank"  # the paragraph ended; plain bullets straight after it still belong to it
                continue
            # inside the advice paragraph every line is the advice's own (its steps may be numbered); after its blank line, only plain
            # bullets are, and a numbered answer or a "Request N" line is the reply again
            if cutting == "blank" and (_ITEM_START.match(line) or not _BULLET.match(line)):
                cutting = False
            else:
                advice.append(line.strip())
                continue
        kept.append(line)
    if not advice:
        return answer, None
    reply = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    words = " ".join(re.sub(r"^\s*(?:[-•]\s+)?", "", a.replace("*", "")) for a in advice).strip()
    return reply, words or None


def first_person(answer: str) -> bool:
    """The reply speaks as a person ("I would ...", "I recommend ...", "in my view"), outside quoted words."""
    text = _QUOTED.sub(" ", answer or "")
    for m in _FIRST_PERSON.finditer(text):
        if m.group(0)[0] == "I" and _NUMERAL_BEFORE.search(text[: m.start()]):
            continue
        return True
    return False


def unknown_sources(result: dict[str, Any]) -> list[int]:
    """The source numbers the draft named that it was not given: tags the answer lane dropped, and tags left in the text that are not
    among its cited sources or past the sources supplied."""
    given = len(result.get("passages") or [])
    cited = {n for n in (result.get("cited") or []) if isinstance(n, int)}
    dropped = [n for n in (result.get("rejected_citations") or []) if isinstance(n, int)]
    named = {int(n) for n in _LABEL.findall(result.get("answer") or "")}
    return sorted(set(dropped) | {n for n in named if n < 1 or n > given or n not in cited})


def unsourced_positions(answer: str) -> int:
    """How many sentences state COMPANY's position and cite no source."""
    count = 0
    for sentence in _SENTENCE.split(_QUOTED.sub(" ", answer or "")):
        if _POSITION.search(sentence) and not _LABEL.search(sentence):
            count += 1
    return count


def drop_cost_standin(answer: str) -> str:
    """The reply without the prompt's old stand-in cost/schedule sentence (the page offers COMPANY's usual sentence beside it)."""
    out = _COST_STANDIN.sub("", answer or "")
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def cited_in(answer: str, cited: list[int]) -> list[int]:
    """The cited sources still named in the reply (after advice was cut out of it), in their order."""
    named = {int(n) for n in _LABEL.findall(answer or "")}
    return [n for n in cited if n in named]


def stored_first_person(draft: dict[str, Any] | None) -> bool:
    """An AI draft kept before these checks that gives first-person advice or speaks as "I". An engineer's own reply is the engineer's."""
    if not draft or not draft.get("model"):
        return False
    answer = draft.get("answer") or ""
    return any(_ADVICE_HEAD.match(line) for line in answer.splitlines()) or first_person(answer)


def cut_off(result: dict[str, Any]) -> bool:
    """The draft stopped before its end: the model ran out of room, or its last line ends mid-sentence."""
    if result.get("truncated"):
        return True
    last = next((line for line in reversed((result.get("answer") or "").splitlines()) if line.strip()), "")
    return bool(_MID_SENTENCE.search(last.replace("*", "").rstrip()))


def bare_answer(answer: str) -> bool:
    """A line of the reply that is only "Yes.", "No." or "Partly." (numbered or not)."""
    return any(_BARE.match(line) for line in (answer or "").splitlines())


def split_unsourced_cost(answer: str) -> tuple[str, str | None]:
    """The reply without its cost or schedule POSITION sentences that cite no source, and those sentences (None when there were none).
    The page offers COMPANY's usual sentence beside the reply, so an unsourced one in it would be a second, and maybe a different,
    message (builder H's table, 27 Nov 2026: 16 replies held their own sentence beside the usual one)."""
    from .technical_query_position import raises_cost

    kept_lines: list[str] = []
    moved: list[str] = []
    for line in (answer or "").split("\n"):
        pieces = _SENTENCE.split(line)
        keep = []
        for piece in pieces:
            bare = _QUOTED.sub(" ", piece)
            if raises_cost(bare) and _COST_POSITION.search(bare) and not _LABEL.search(piece):
                moved.append(piece.strip())
            else:
                keep.append(piece)
        if keep or not line.strip():
            kept_lines.append(" ".join(keep))
        # a line that held only such sentences goes with them
    if not moved:
        return answer, None
    reply = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    return reply, " ".join(m.replace("*", "") for m in moved).strip() or None


def states_cost(answer: str) -> bool:
    """The reply states a cost or schedule position (any sentence, sourced or not), or holds COMPANY's usual sentence."""
    from .technical_query_position import POSITION_LINE, raises_cost

    text = answer or ""
    if POSITION_LINE in text:
        return True
    return any(raises_cost(b) and _COST_POSITION.search(b) for b in (_QUOTED.sub(" ", p) for p in _SENTENCE.split(text)))
