"""The chat's web lane: ask first, send one phrase, cite what came back.

OWNER ORDER 2026-09-26 (chat redesign PR 6, section 2d). A chat question may
be checked on the public web - "is there a newer edition of X online?" - but
only through the lane that already exists for exactly this and is already
held to its promise (market_phrase, market_providers, market_transport):

  * OFF UNLESS THREE SWITCHES ARE ON: `chat_web_enabled` here, and the market
    lane's own two egress flags. The composer's "Web" toggle is a fourth,
    per-question choice by the reader; it can only turn the lane off.
  * ASK FIRST. A web question produces a CONSENT turn, and nothing leaves:
    it shows the exact phrase that would be sent. Only "Search once" sends it.
  * THE PHRASE IS THE READER'S OWN WORDS, WHITELISTED, AND NOTHING ELSE. It
    is rebuilt on the server from the one stored user message the consent
    answers - never from a client-supplied string, never from the history,
    never from a passage - by `market_phrase`, which strips the caller's
    corpus filenames and drops any word it cannot vouch for. None means "do
    not search", and then nothing is offered.
  * EVERY QUERY IS AUDITED in `audit_events`, as the market route does.
  * THE ANSWER CITES THE WEB AS THE WEB: site, title, date, link, and
    "unverified" - never a document chip, never a finding.
"""
from __future__ import annotations

import json
import time

from . import market_phrase, market_providers, market_transport
from .config import settings
from .db import connect

CONSENT = "web_consent"
WEB = "web"


class NotFound(LookupError):
    """No web question with that id in this conversation."""


class Refused(ValueError):
    """The lane is off, the phrase is unsafe, or it was already searched."""


def _not_searched(question: str) -> dict:
    """The fields every answer carries, stating that no DOCUMENT was searched."""
    return {"question": question, "retrieval_mode": "not_searched", "reranked": False,
            "timings": {}, "candidates_considered": 0, "passages": [], "examples": [],
            "input_kind": "web_question"}


def available() -> tuple[bool, str | None]:
    """Whether a chat web search could send anything, and why not."""
    if not settings.chat_web_enabled:
        return False, "web search is switched off for chat on this system"
    if not market_providers.live_enabled():
        return False, "this system does not permit outbound web searches"
    if not market_providers.tiers_configured():
        return False, "no web search provider is configured"
    return True, None


def filenames(allowed_document_ids: frozenset[str]) -> list[str]:
    """The names the phrase must never carry: every file the caller may read."""
    ids = sorted(allowed_document_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [r["filename"] for r in connect().execute(
        f"SELECT filename FROM documents WHERE id IN ({marks})", ids)]


def consent(question: str, *, allowed_document_ids: frozenset[str]) -> dict:
    """The consent turn: what would be sent, and nothing sent."""
    phrase = market_phrase.market_phrase(question, filenames(allowed_document_ids))
    ok, why = available()
    base = {**_not_searched(question), "answer_type": CONSENT, "reason": None,
            "cited": [], "rejected_citations": [], "seconds": 0.0,
            "web_phrase": phrase, "web_available": ok}
    if not ok:
        return {**base, "web_phrase": None, "answer": (
            f"I can't check the web here: {why}. I can answer from your documents or "
            "from general knowledge instead.")}
    if phrase is None:
        return {**base, "answer": (
            "Nothing in that question is safe to send to a web search - document names "
            "and unrecognised terms are removed - so I won't search. Ask with public "
            "terms, such as a standard's number, and I'll offer the search again.")}
    return {**base, "answer": (
        f'I can search the web for "{phrase}". Only this phrase is sent - nothing from '
        "your documents or this conversation. Search once?")}


def _consent_turn(conversation_id: str, message_id: str) -> tuple[dict, str]:
    conn = connect()
    row = conn.execute(
        "SELECT * FROM messages WHERE id = ? AND conversation_id = ?",
        (message_id, conversation_id)).fetchone()
    if row is None or row["role"] != "assistant" or row["answer_type"] != CONSENT:
        raise NotFound(message_id)
    asked = conn.execute(
        """SELECT text FROM messages WHERE conversation_id = ? AND role = 'user'
           AND ordinal < ? ORDER BY ordinal DESC LIMIT 1""",
        (conversation_id, row["ordinal"])).fetchone()
    if asked is None or not asked["text"]:
        raise NotFound(message_id)
    payload = json.loads(row["payload"] or "{}") or {}
    return payload, asked["text"]


def search(conversation_id: str, consent_message_id: str, *,
           allowed_document_ids: frozenset[str]) -> tuple[dict, list[dict]]:
    """Run the one approved search. Returns (answer result, audit rows)."""
    payload, question = _consent_turn(conversation_id, consent_message_id)
    if payload.get("web_searched"):
        raise Refused("this search has already been run")
    ok, why = available()
    if not ok:
        raise Refused(why or "web search is switched off")
    # REBUILT HERE from the stored question, never taken from the client or
    # from the consent turn's stored copy - the same re-scrub the market
    # route performs, so the only text that can leave is text this server
    # derived from the reader's own words.
    phrase = market_phrase.market_phrase(question, filenames(allowed_document_ids))
    if phrase is None:
        raise Refused("nothing in the question is safe to send")
    started = time.monotonic()
    result = market_providers.search_all(phrase, fetch=market_transport.transport())
    seconds = round(time.monotonic() - started, 3)
    if result.get("tiers_answered"):
        # USED ONCE IT ANSWERED. A search every provider refused (a rate
        # limit, the network) leaves the consent usable, so the reader can
        # try again rather than being locked out by a failure that sent
        # nothing useful.
        conn = connect()
        with conn:
            conn.execute(
                "UPDATE messages SET payload = ? WHERE id = ?",
                (json.dumps({**payload, "web_searched": True}), consent_message_id))
    rows = [r for r in (result.get("rows") or []) if not r.get("is_sample")][:5]
    sources = [{
        "n": i, "kind": "web", "document_id": None,
        "display_name": r.get("publisher") or "Web source",
        "document_number": None, "page": None, "page_end": None,
        "clause": r.get("published"), "text_source": None, "ocr_min_conf": None,
        "url": r.get("url"), "cited": True, "quotes": [], "rows": [],
    } for i, r in enumerate(rows, start=1)]
    if rows:
        lines = [f"{i}. {(r.get('text') or '').strip()[:300]} ({r.get('publisher') or 'web'})"
                 for i, r in enumerate(rows, start=1)]
        answer = (f'What a public web search for "{phrase}" returned. These are web pages, '
                  "not your documents, and nothing here has been checked:\n\n" + "\n".join(lines))
    elif result.get("failure"):
        answer = (f'The web search for "{phrase}" did not complete: {result["failure"]}. '
                  "You can try the search again.")
    else:
        answer = f'A public web search for "{phrase}" found nothing.'
    used = f'Searched the web for "{phrase}" · only this phrase was sent'
    return ({
        **_not_searched(question), "answer_type": WEB, "answer": answer, "reason": None,
        "cited": [], "rejected_citations": [], "seconds": seconds,
        "answer_kind": WEB, "used_line": used, "sources": sources, "verification": None,
        "steps": [], "suggestions": [], "draft": None,
        "notices": ["Web results are unverified. Your contract baseline is the edition it names, "
                    "whatever a website says."],
        "web_phrase": phrase,
    }, list(result.get("audit") or []))
