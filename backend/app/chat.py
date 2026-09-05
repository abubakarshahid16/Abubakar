"""Conversations, messages, and follow-up resolution.

Two rules govern this module, and the second one is the important one.

1. A follow-up must be answerable. "and its curing time" is a real question
   an engineer types, and on its own it retrieves nothing. The last few USER
   questions in the same conversation supply the missing subject.

2. A previous ANSWER is never evidence. Retrieval reads documents and nothing
   else. Prior assistant messages are stored for display and replay, and are
   never fed into search, into the prompt, or into follow-up resolution. If
   they were, a wrong answer would become the grounds for the next one and the
   whole citation guarantee would quietly stop meaning anything.

Resolution is deliberately conservative and inspectable. It carries forward
identifiers and designators - the terms whose absence produces a confidently
wrong answer rather than an empty one - and reports exactly what it carried,
so the reader can see what was assumed instead of the question being silently
rewritten underneath them.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from . import answer as answer_mod
from . import intent as intent_mod
from . import keyword
from . import search as search_mod
from .db import connect

#: How many previous USER questions resolution may look at. Beyond about three
#: turns the subject has usually moved on, and carrying stale terms turns a
#: fresh question into a constrained one.
FOLLOWUP_WINDOW = 3

#: A follow-up carries at most this many topic words, so a long earlier
#: question cannot swamp a short new one.
MAX_TOPIC_TERMS = 4

TITLE_MAX = 80

#: Words that mark a question as pointing back at something already said.
ANAPHORA = {
    "it", "its", "that", "this", "they", "them", "their", "those", "these",
    "there", "same", "one", "ones", "above", "former", "latter",
}

#: Openers that continue a previous question rather than starting a new one.
FOLLOWUP_OPENERS = (
    "and ", "but ", "what about", "how about", "also ", "then ",
    "so ", "why", "ok ", "okay ",
)

#: Finite verbs that turn a noun phrase into a question. A clause has one; a
#: bare noun phrase does not, and that is the difference the completeness test
#: turns on. Auxiliaries and copulas only - deliberately NOT a list of lexical
#: verbs, which would never be complete and would drift with the corpus.
FINITE_VERBS = {
    "is", "are", "was", "were", "be", "am",
    "does", "do", "did", "done",
    "has", "have", "had",
    "can", "could", "shall", "should", "will", "would", "must", "may", "might",
    "need", "needs", "gives", "give", "says", "say", "means", "mean",
    "applies", "apply", "requires", "require", "specifies", "specify",
    "stands", "stand", "allows", "allow", "happens", "happen",
}


def is_complete_question(question: str) -> bool:
    """Can this question stand on its own, grammatically?

    A COMPLETE question contains a finite verb - "what is the warranty period",
    "how often must humidity be checked". A bare noun phrase does not -
    "system 4?", "the minimum", "warranty".

    This replaces a word-count test, `len(_content_words(question)) < 3`, which
    was not a test of whether a question is a follow-up at all. It classified
    "what is the warranty period" - a complete, self-contained question with
    two content words - as a follow-up, so it inherited terms from whatever was
    asked before it. Measured over 200 shuffled orderings of the evaluation
    set, that single misclassification made 72 of them return a confident wrong
    answer where a refusal was correct: 36% of conversations, and the ONLY
    failure in any of them.

    Length was never the signal. Completeness is.
    """
    words = set(_WORD.findall(question.lower()))
    return bool(words & FINITE_VERBS)


#: Function words. Excluded when judging whether a question carries enough of
#: its own subject to stand alone. Deliberately does NOT include specification
#: verbs like "shall", "required" or "specified", which are meaningful here.
STOPWORDS = {
    "what", "about", "how", "why", "which", "the", "for", "and", "but", "is",
    "are", "of", "in", "to", "a", "an", "does", "do", "did", "that", "this",
    "it", "its", "they", "them", "those", "these", "there", "same", "when",
    "where", "who", "with", "on", "at", "be", "was", "were", "will", "would",
    "can", "could", "any", "all", "then", "so", "ok", "okay", "also", "me",
    "you", "my", "our", "tell", "give", "show", "please",
    # pure connectives inside a designator phrase: "system no. 1" is
    # normalised to "system 1", so these carry no meaning on their own
    "no.", "no", "number", "nr", "nr.",
}

_WORD = re.compile(r"[\w.\-/]{2,}")


def _now() -> str:
    """Millisecond precision on purpose.

    At second precision, creating two conversations and asking in the first
    left both with the same updated_at, so "most recently used first" fell
    through to created_at DESC and listed them backwards. A timestamp used for
    ordering has to be finer-grained than the thing it orders.
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class ConversationNotFound(Exception):
    pass


class MessageNotFound(Exception):
    pass


# ------------------------------------------------------- follow-up resolution


def _content_words(question: str) -> list[str]:
    return [
        w for w in (t.lower() for t in _WORD.findall(question))
        if w not in STOPWORDS
    ]


def is_followup(question: str) -> bool:
    """Does this question lean on an earlier one to make sense?

    Three independent signals, any of which is enough:
      * it contains an anaphor ("its curing time")
      * it opens as a continuation ("and the roughness requirement")
      * it is grammatically INCOMPLETE - a bare noun phrase with no finite
        verb ("system 4?", "the minimum")

    The third signal used to be `len(_content_words(question)) < 3`. Word count
    is not a test of dependence: "what is the warranty period" is complete and
    self-contained, and being two content words long is not a reason to feed it
    somebody else's subject. See is_complete_question.
    """
    lowered = question.strip().lower()
    if not lowered:
        return False
    words = set(_WORD.findall(lowered))
    if words & ANAPHORA:
        return True
    if lowered.startswith(FOLLOWUP_OPENERS):
        return True
    return not is_complete_question(lowered)


def _designator_words(question: str) -> set[str]:
    """The designator NOUNS present, e.g. {"system"} for "system 4"."""
    return {d.partition(" ")[0] for d in keyword.find_designators(question)}


def resolve_followup(
    question: str, prior_questions: list[str]
) -> tuple[str, list[str]]:
    """Return the question retrieval should actually run, and what was carried.

    `prior_questions` are earlier USER questions, oldest first. Assistant
    answers are not accepted here and must never be passed in.
    """
    # A greeting is short enough to look like a follow-up. Carrying "system 1"
    # into "hi" would search the corpus for a word the reader never asked
    # about, which is the bug this ordering exists to prevent.
    if not intent_mod.is_document_question(question):
        return question, []
    # A definition is not context-dependent. "what is ndft" asks what the
    # letters mean, and carrying "system 4" in from the previous turn changes
    # the question into a different one. Restricted to a single-word term, so
    # "what is its curing time" stays a follow-up and keeps inheriting its
    # subject - that one genuinely does depend on what came before.
    term = search_mod.definitional_term(question)
    if term and len(term.split()) == 1 and term.lower() not in ANAPHORA:
        return question, []

    if not prior_questions or not is_followup(question):
        return question, []

    have_identifiers = set(keyword.IDENTIFIER.findall(question))
    have_designator_words = _designator_words(question)
    have_words = set(_content_words(question))

    carried: list[str] = []

    # Most recent first: the nearest question is the one being followed up.
    for prior in reversed(prior_questions[-FOLLOWUP_WINDOW:]):
        for ident in keyword.IDENTIFIER.findall(prior):
            if ident not in have_identifiers and ident not in carried:
                carried.append(ident)
                have_identifiers.add(ident)
        for des in keyword.find_designators(prior):
            word = des.partition(" ")[0]
            # The conflict rule, and the reason this module exists in this
            # shape: if the new question says "system 4", carrying "system 1"
            # from the previous turn would retrieve the wrong system and read
            # perfectly plausible doing it.
            if word in have_designator_words:
                continue
            if des not in carried:
                carried.append(des)
                have_designator_words.add(word)

    # A question that still has almost no subject of its own also borrows the
    # earlier topic words. These are OR-ed by the query builder rather than
    # required, so they steer retrieval without excluding anything.
    if len(_content_words(question)) < 3:
        borrowed_from = " ".join(prior_questions[-FOLLOWUP_WINDOW:])
        # Every token belonging to a designator in the earlier text is off
        # limits. A designator dropped by the conflict rule above must not
        # sneak back in as a loose topic word - carrying the "1" out of
        # "system no. 1" into a question about system 4 is the same wrong
        # answer by a quieter route.
        designator_tokens = {
            t for d in keyword.find_designators(borrowed_from)
            for t in d.lower().split()
        }
        skip = have_words | {w for c in carried for w in _content_words(c)}
        topics: list[str] = []
        for w in _content_words(borrowed_from):
            if w in skip or w in topics or w in designator_tokens:
                continue
            topics.append(w)
            if len(topics) >= MAX_TOPIC_TERMS:
                break
        carried.extend(topics)

    if not carried:
        return question, []
    return f"{question} {' '.join(carried)}", carried


# ------------------------------------------------------------- conversations


def create_conversation(title: str = "New conversation", document_id: str | None = None) -> dict:
    conn = connect()
    now = _now()
    cid = f"conv_{uuid.uuid4().hex[:12]}"
    with conn:
        conn.execute(
            """INSERT INTO conversations (id, title, document_id, message_count,
                                          created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            (cid, title[:TITLE_MAX], document_id, now, now),
        )
    return get_conversation(cid)


def get_conversation(conversation_id: str) -> dict:
    row = connect().execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise ConversationNotFound(conversation_id)
    return dict(row)


def list_conversations(limit: int = 20, offset: int = 0) -> dict:
    conn = connect()
    rows = conn.execute(
        """SELECT c.*,
                  (SELECT text FROM messages m
                    WHERE m.conversation_id = c.id AND m.role = 'user'
                    ORDER BY m.ordinal LIMIT 1) AS first_question
           FROM conversations c
           ORDER BY c.updated_at DESC, c.created_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "conversations": [dict(r) for r in rows],
    }


def delete_conversation(conversation_id: str) -> int:
    get_conversation(conversation_id)
    conn = connect()
    with conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return cur.rowcount


def _row_to_message(r) -> dict:
    return {
        "id": r["id"],
        "conversation_id": r["conversation_id"],
        "ordinal": r["ordinal"],
        "role": r["role"],
        "text": r["text"],
        "resolved_question": r["resolved_question"],
        "carried_terms": json.loads(r["carried_terms"]) if r["carried_terms"] else [],
        "answer_type": r["answer_type"],
        "reason": r["reason"],
        "explains_id": r["explains_id"],
        "payload": json.loads(r["payload"]) if r["payload"] else None,
        "created_at": r["created_at"],
    }


def get_messages(conversation_id: str) -> list[dict]:
    get_conversation(conversation_id)
    rows = connect().execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY ordinal",
        (conversation_id,),
    ).fetchall()
    return [_row_to_message(r) for r in rows]


def prior_user_questions(conversation_id: str, window: int = FOLLOWUP_WINDOW) -> list[str]:
    """The last `window` USER questions, oldest first.

    Restricted to role='user' in SQL rather than filtered afterwards, so no
    future edit here can accidentally start feeding answers back in.

    A greeting is stored as a user turn - it belongs in the transcript - but
    it is not a question and must never become context for one. Typing "hi",
    "thanks", then "what is ndft" searched for "what is ndft hi thanks" and
    refused a question the document answers. Non-questions are dropped here,
    and a wider window is read so dropping them does not silently shorten it.
    """
    rows = connect().execute(
        """SELECT text FROM messages
           WHERE conversation_id = ? AND role = 'user' AND text IS NOT NULL
           ORDER BY ordinal DESC LIMIT ?""",
        (conversation_id, window * 4),
    ).fetchall()
    questions = [
        r["text"] for r in rows if intent_mod.is_document_question(r["text"])
    ]
    return list(reversed(questions[:window]))


def _insert_message(conn, conversation_id: str, **fields) -> dict:
    """Append one message and advance the conversation, in one transaction.

    The message and the conversation's counters move together for the same
    reason every other state transition in this codebase does: a stored
    message with a stale message_count is a conversation that renders wrong.
    """
    now = _now()
    mid = f"msg_{uuid.uuid4().hex[:12]}"
    with conn:
        ordinal = conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO messages
                 (id, conversation_id, ordinal, role, text, resolved_question,
                  carried_terms, answer_type, reason, explains_id, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                conversation_id,
                ordinal,
                fields["role"],
                fields.get("text"),
                fields.get("resolved_question"),
                json.dumps(fields["carried_terms"]) if fields.get("carried_terms") else None,
                fields.get("answer_type"),
                fields.get("reason"),
                fields.get("explains_id"),
                json.dumps(fields["payload"]) if fields.get("payload") is not None else None,
                now,
            ),
        )
        conn.execute(
            """UPDATE conversations
               SET message_count = message_count + 1, updated_at = ?
               WHERE id = ?""",
            (now, conversation_id),
        )
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
    return _row_to_message(row)


def _title_from(question: str) -> str:
    cleaned = " ".join(question.split())
    return cleaned[:TITLE_MAX] if cleaned else "New conversation"


#: The parts of an answer worth replaying when a conversation is reopened.
#: Deliberately explicit rather than storing the whole response, so a future
#: field cannot silently start being persisted.
_PAYLOAD_KEYS = (
    "passage", "supporting", "passages", "cited", "rejected_citations",
    "retrieval_mode", "reranked", "candidates_considered", "model",
    "prompt_tokens", "output_tokens", "seconds", "timings",
    "input_kind", "examples", "answer_passages", "lexical",
)


def _payload(result: dict) -> dict:
    return {k: result[k] for k in _PAYLOAD_KEYS if k in result}


def ask(
    conversation_id: str,
    question: str,
    tier: str = "extract",
    document_id: str | None = None,
    limit: int = 3,
    explain_of: str | None = None,
) -> dict:
    """Answer a question inside a conversation and persist both turns.

    `explain_of` is the Tier 2 path: it upgrades an existing extract answer
    rather than asking a new question, so the conversation does not grow a
    duplicate user turn every time the reader presses Explain, and the
    already-resolved question is reused rather than resolved a second time.
    """
    conversation = get_conversation(conversation_id)
    document_id = document_id or conversation["document_id"]
    conn = connect()

    if explain_of is not None:
        target = conn.execute(
            "SELECT * FROM messages WHERE id = ? AND conversation_id = ?",
            (explain_of, conversation_id),
        ).fetchone()
        if target is None or target["role"] != "assistant":
            raise MessageNotFound(explain_of)
        asked = conn.execute(
            """SELECT * FROM messages
               WHERE conversation_id = ? AND role = 'user' AND ordinal < ?
               ORDER BY ordinal DESC LIMIT 1""",
            (conversation_id, target["ordinal"]),
        ).fetchone()
        if asked is None:
            raise MessageNotFound(explain_of)
        user_message = _row_to_message(asked)
        resolved = asked["resolved_question"] or asked["text"]
        original = asked["text"]
    else:
        original = question
        resolved, carried = resolve_followup(
            question, prior_user_questions(conversation_id)
        )
        user_message = _insert_message(
            conn,
            conversation_id,
            role="user",
            text=original,
            resolved_question=resolved,
            carried_terms=carried,
        )
        if conversation["message_count"] == 0:
            with conn:
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (_title_from(original), conversation_id),
                )

    result = answer_mod.answer(
        resolved, tier=tier, document_id=document_id, limit=limit
    )

    assistant_message = _insert_message(
        conn,
        conversation_id,
        role="assistant",
        text=result.get("answer"),
        answer_type=result["answer_type"],
        reason=result.get("reason"),
        explains_id=explain_of,
        payload=_payload(result),
    )

    return {
        **result,
        # after the spread, so the question shown is the one the reader typed
        # rather than the rewritten one retrieval ran
        "conversation": get_conversation(conversation_id),
        "user_message": user_message,
        "assistant_message": assistant_message,
        "question": original,
        "resolved_question": resolved,
        "carried_terms": user_message["carried_terms"],
    }
