"""Conversations, messages, and follow-up resolution.

Two rules govern this module, and the second one is the important one.

1. A follow-up must be answerable. "and its curing time" is a real question
   an engineer types, and on its own it retrieves nothing. The last few USER
   questions in the same conversation supply the missing subject.

2. A previous ANSWER is never evidence. Retrieval reads documents and nothing
   else. Prior assistant messages are stored for display and replay, and are
   never fed into search or into follow-up resolution. If they were, a wrong
   answer would become the grounds for the next one and the whole citation
   guarantee would quietly stop meaning anything.

   CHANGED 2026-09-26 (owner order, chat redesign), and only this far: the
   MODEL now sees the recent conversation, permission-filtered, so "that",
   "in points" and "more detail" work (`chat_model.history`). It sees it as
   context labelled "not a source", and a document claim still has to cite a
   passage retrieved for THIS question - so an earlier answer can shape the
   wording but never become the evidence. Retrieval is unchanged.

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
from . import chat_answers
from . import chat_model
from . import chat_presentation
from . import intent as intent_mod
from . import keyword
from . import search as search_mod
from . import understanding as understanding_mod
from .config import settings
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
    # A substantial noun phrase is often a complete search request even when
    # it has no finite verb (for example, "inherent problems of P&IDs"). Do
    # not inject an unrelated prior designator into it. Short designator
    # phrases such as "system 4?" remain follow-ups through the completeness
    # rule below.
    if len(_content_words(question)) >= 2 and not keyword.find_designators(question):
        return False
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
    #
    # Threshold is < 2, not < 3. "tell me about system design" has two content
    # words of its own ("system", "design") - a complete, self-sufficient
    # subject - and used to still qualify under < 3, dragging in up to four
    # unrelated topic words from whatever was asked earlier in the same
    # conversation (a prior "wave equation" question leaking "wave", "4.00",
    # "inherent" into a plain system-design query, and burying the real
    # subject under noise the corpus has nothing to match). A question with
    # only zero or one content words of its own ("the minimum", "curing
    # time") still has no real subject and still needs the borrow; two or
    # more content words is already enough of a subject on its own.
    if len(_content_words(question)) < 2:
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


def create_conversation(title: str = "New conversation", document_id: str | None = None,
                        owner_user_id: str | None = None) -> dict:
    """Start a conversation, recording who started it.

    `owner_user_id` is what every later read is checked against. It was a
    column for weeks before anything wrote it - 0 of 81 rows populated on the
    demo database - and the existence of the column made the table LOOK owned
    while every read path ignored it. Under `disabled` there is no identity and
    the owner is NULL; under `demo_required` the route refuses to create a
    conversation with no owner, because a conversation nobody owns is one
    nobody can ever read again.
    """
    conn = connect()
    now = _now()
    cid = f"conv_{uuid.uuid4().hex[:12]}"
    with conn:
        conn.execute(
            """INSERT INTO conversations (id, title, document_id, message_count,
                                          created_at, updated_at, owner_user_id)
               VALUES (?, ?, ?, 0, ?, ?, ?)""",
            (cid, title[:TITLE_MAX], document_id, now, now, owner_user_id),
        )
    return get_conversation(cid)


def get_conversation(conversation_id: str) -> dict:
    row = connect().execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise ConversationNotFound(conversation_id)
    return dict(row)


#: `list_conversations(owner=EVERYONE)` means the unrestricted scope - auth is
#: off and there is no identity to filter by. It is a distinct sentinel and not
#: None, because None is the OWNER VALUE of every legacy row, and a caller that
#: passed None meaning "no filter" would be handed exactly the conversations
#: the plan says nobody may read. The two must not be confusable.
EVERYONE = object()


def list_conversations(limit: int = 20, offset: int = 0,
                       owner: str | None | object = EVERYONE,
                       include_unowned: bool = False) -> dict:
    """Recent conversations, most recently used first.

    Filtered IN THE QUERY on `owner_user_id`, for the reason /api/documents
    already gives: dropping rows in Python works while there is no LIMIT and
    turns into a leak the day there is one. Both the page and `total` are
    filtered, so the count never admits to rows the page will never show.

    An owner of None (an unauthenticated caller under demo_required) matches
    NOTHING - `owner_user_id = NULL` is false in SQL for every row, including
    the legacy rows whose owner is NULL. That is the behaviour plan line 1017
    requires and it falls out of the comparison rather than from a branch.

    `include_unowned` adds the NULL-owner rows to `owner`'s own. The route
    passes it for the admin capability only - the decision for the legacy rows
    - and it is a separate flag rather than a magic owner value so that a
    caller passing owner=None can never receive them by accident.
    """
    conn = connect()
    if owner is EVERYONE:
        where, args = "", []
    elif include_unowned:
        where, args = " WHERE (c.owner_user_id = ? OR c.owner_user_id IS NULL)", [owner]
    else:
        where, args = " WHERE c.owner_user_id = ?", [owner]
    rows = conn.execute(
        f"""SELECT c.*,
                  (SELECT text FROM messages m
                    WHERE m.conversation_id = c.id AND m.role = 'user'
                    ORDER BY m.ordinal LIMIT 1) AS first_question
           FROM conversations c{where}
           ORDER BY c.updated_at DESC, c.created_at DESC
           LIMIT ? OFFSET ?""",
        [*args, limit, offset],
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM conversations c" + where, args).fetchone()[0]
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
    } | _lifted(r["payload"])


def _lifted(raw: str | None) -> dict:
    try:
        payload = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        payload = {}
    return {k: payload[k] for k in _LIFTED if isinstance(payload, dict) and k in payload}


#: What a reopened assistant turn shows when it cites a document the caller
#: can no longer read. Fixed text: the notice itself must not name the document.
WITHHELD_TEXT = (
    "This answer cited a document you no longer have access to, so it is not shown."
)
_ID_LIST_KEYS = frozenset({"scope_ids", "document_ids"})


def referenced_document_ids(value) -> set[str]:
    """Every document id a stored payload refers to, at any depth.

    Walks the whole structure rather than a list of known keys, so a field
    added to the payload later is covered without anyone remembering this.
    """
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "document_id" and isinstance(item, str):
                found.add(item)
            elif key in _ID_LIST_KEYS and isinstance(item, list):
                found.update(x for x in item if isinstance(x, str))
            else:
                found |= referenced_document_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= referenced_document_ids(item)
    return found


def _withhold(message: dict) -> dict:
    return {
        **{k: v for k, v in message.items() if k not in _LIFTED},
        "text": WITHHELD_TEXT,
        "payload": {"withheld": True},
        "reason": "cited document no longer readable",
        "answer_type": None,
    }


def get_messages(conversation_id: str, *, allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every turn, filtered by what the caller may read NOW.

    A stored answer is a copy of document text taken when it was asked. A
    grant revoked since then must still hide it, so an assistant turn citing
    any document outside `allowed_document_ids` is withheld whole - text and
    payload - not partially redacted: its prose quotes the passages too.
    Required and keyword-only, like every other scope parameter.
    """
    get_conversation(conversation_id)
    rows = connect().execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY ordinal",
        (conversation_id,),
    ).fetchall()
    messages = []
    for r in rows:
        message = _row_to_message(r)
        if (message["role"] == "assistant"
                and referenced_document_ids(message["payload"]) - allowed_document_ids):
            message = _withhold(message)
        messages.append(message)
    return messages


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
    # Without this, reopening a conversation would show a complete-looking
    # answer with the partial-coverage warning silently gone - worse than
    # never having shipped the field.
    "coverage", "evidence_removed",
    # The same reason, three more times. Reopened without `corpus`, a two-part reply
    # would lose its database half; without `counts_bounded`, a re-bounded
    # count would lose the note that says it was; without `truncated`, a cut-off
    # answer would reopen looking complete.
    "corpus", "counts_bounded", "truncated",
    # B6C: what the question was understood to be about, and any document
    # ambiguity - reopened without them, a scoped answer would look unscoped.
    "understanding", "scope_ambiguity",
    # B8: the answer-level verdict, reopened exactly as it was given.
    "answerability",
    # Chat redesign (2026-09-26): what the answer says about itself - see
    # chat_presentation. Additive: a turn stored before these existed simply
    # has none of them, and renders as it always did.
    "answer_kind", "used_line", "sources", "verification", "steps",
    "suggestions", "draft", "provider", "cost_usd", "history_turns",
    "route", "notices", "claims", "claims_removed", "rewrite_of", "records",
)

#: Payload keys lifted to the top of a message, so the Chat screen reads one
#: shape for a fresh answer and a reopened one.
_LIFTED = ("answer_kind", "used_line", "sources", "verification", "steps",
           "suggestions", "draft", "notices", "model", "provider", "seconds", "cost_usd")


def _payload(result: dict) -> dict:
    return {k: result[k] for k in _PAYLOAD_KEYS if k in result}


def ask(
    conversation_id: str,
    question: str,
    tier: str = "extract",
    document_id: str | None = None,
    limit: int = 3,
    explain_of: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
    progress_id: str | None = None,
    model: str | None = None,
    include_unowned_records: bool = False,
) -> dict:
    """Answer a question inside a conversation and persist both turns.

    `explain_of` is the Tier 2 path: it upgrades an existing extract answer
    rather than asking a new question, so the conversation does not grow a
    duplicate user turn every time the reader presses Explain, and the
    already-resolved question is reused rather than resolved a second time.
    """
    conversation = get_conversation(conversation_id)
    selected_document = document_id
    document_id = document_id or conversation["document_id"]
    conn = connect()
    understood: dict | None = None
    route_kind = intent_mod.DOCUMENT
    routed: dict = {"styles": [], "small_talk": None, "compliance": False, "text": question}

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
        # the scope the original answer was retrieved under, reused
        try:
            understood = (json.loads(target["payload"] or "{}") or {}).get("understanding")
        except (TypeError, ValueError):
            understood = None
    else:
        original = question
        # OWNER ORDER 2026-09-26 (chat redesign, 2c): ROUTED BEFORE ANYTHING
        # IS SEARCHED. Only a document-kind message reaches retrieval; small
        # talk, general questions, rewrites, actions and record searches never
        # do - so none of them can produce a passage, a citation or a finding.
        previous = last_answer(conversation_id, allowed_document_ids=allowed_document_ids)
        routed = intent_mod.route(
            question, has_previous_answer=previous is not None,
            document_in_scope=bool(selected_document or conversation["document_id"]))
        route_kind = routed["kind"]
        tier = routed.get("tier") or tier
        carried: list[str] = []
        resolved = question
        if route_kind in (intent_mod.DOCUMENT, intent_mod.EITHER):
            resolved, carried = resolve_followup(
                routed["text"], prior_user_questions(conversation_id)
            )
            # B6C: what the question is about - document scope, clause,
            # ambiguity. Retrieval input only; never an answer. The resolved
            # query is stored and shown, as the follow-up rewrite already was.
            understanding = understanding_mod.understand(
                resolved,
                allowed_document_ids=allowed_document_ids,
                documents=understanding_mod.document_names(allowed_document_ids),
                conversation_document_id=conversation["document_id"],
                context=understanding_mod.prior_context(conversation_id),
            )
            understood = understanding.to_dict()
            resolved = understanding.retrieval_query
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

    def memory(always: bool = False) -> str:
        """The permission-filtered conversation for the model (chat_model)."""
        if not always and tier != "generated":
            return ""
        local = (model == chat_model.LOCAL) or not chat_model.claude_ready()[0]
        turns = chat_model.history(
            conversation_id, allowed_document_ids=allowed_document_ids,
            before_ordinal=user_message["ordinal"],
            token_budget=(settings.chat_history_local_token_budget if local
                          else settings.chat_history_token_budget))
        memory.turns = len(turns)
        return chat_model.transcript(turns)
    memory.turns = 0

    if explain_of is not None or route_kind in (intent_mod.DOCUMENT, intent_mod.EITHER):
        result, resolved = _document_answer(
            conversation_id, resolved, understood, tier=tier, document_id=document_id,
            selected_document=selected_document, limit=limit,
            allowed_document_ids=allowed_document_ids, progress_id=progress_id,
            model=model, history=memory())
        if (route_kind == intent_mod.EITHER
                and result["answer_type"] == "insufficient_evidence"):
            # NO DOCUMENT SIGNAL, AND THE DOCUMENTS DO NOT ANSWER IT: general
            # knowledge, labelled, with a note that the documents were checked.
            general = chat_answers.general(original, styles=routed["styles"],
                                           history=memory(always=True), preference=model)
            if general["answer_type"] == "general":
                route_kind = intent_mod.GENERAL
                result = {**general, "notices": [
                    "Your documents don't cover this, so this answer is general knowledge."]}
    elif route_kind == intent_mod.GENERAL and routed["small_talk"]:
        result = chat_answers.small_talk(
            routed["small_talk"],
            examples=intent_mod.example_questions(allowed_document_ids=allowed_document_ids))
        result["question"] = original
    elif route_kind == intent_mod.GENERAL:
        result = chat_answers.general(
            original, styles=routed["styles"], history=memory(always=True), preference=model,
            input_kind=intent_mod.classify(original))
    elif route_kind == intent_mod.REWRITE and "check_documents" in routed["styles"]:
        # "Check against my documents": the previous QUESTION, asked of the
        # documents - a real retrieval, not a rewrite of an earlier answer.
        asked = _previous_user_question(conversation_id, before=user_message["ordinal"])
        route_kind = intent_mod.DOCUMENT
        result, resolved = _document_answer(
            conversation_id, asked or original, None, tier="generated", document_id=document_id,
            selected_document=selected_document, limit=limit,
            allowed_document_ids=allowed_document_ids, progress_id=progress_id,
            model=model, history=memory(always=True))
    elif route_kind == intent_mod.REWRITE:
        result = chat_answers.rewrite(previous, styles=routed["styles"], history=memory(always=True),
                                      preference=model, question=original)
    elif route_kind == intent_mod.ACTION:
        result = chat_answers.rewrite(
            previous, styles=routed["styles"], history=memory(always=True), preference=model,
            question=original, kind="action",
            extra=("as a short, polite review comment to the contractor: what is missing or "
                   "unclear, and what they should provide"))
    else:  # records
        result = chat_answers.records(routed["text"], allowed_document_ids=allowed_document_ids,
                                      include_unowned=include_unowned_records)

    result["route"] = route_kind
    result["history_turns"] = memory.turns
    if route_kind in (intent_mod.DOCUMENT, intent_mod.EITHER) and routed.get("compliance"):
        # THE CHAT NEVER RECORDS A VERDICT: a compliance question is answered
        # from the evidence and ends with the engineer notice.
        result["notices"] = [*(result.get("notices") or []), intent_mod.ENGINEER_NOTICE]
    result.update(chat_presentation.present(result))

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


def last_answer(conversation_id: str, *, allowed_document_ids: frozenset[str]) -> dict | None:
    """The most recent assistant turn the caller may still read, with text."""
    for message in reversed(get_messages(conversation_id, allowed_document_ids=allowed_document_ids)):
        if message["role"] != "assistant":
            continue
        if (message.get("payload") or {}).get("withheld") or not (message.get("text") or "").strip():
            return None
        return message
    return None


def _previous_user_question(conversation_id: str, *, before: int) -> str | None:
    row = connect().execute(
        """SELECT text FROM messages WHERE conversation_id = ? AND role = 'user'
           AND ordinal < ? ORDER BY ordinal DESC LIMIT 1""", (conversation_id, before)).fetchone()
    return row["text"] if row else None


def _document_answer(conversation_id: str, resolved: str, understood: dict | None, *, tier: str,
                     document_id: str | None, selected_document: str | None, limit: int,
                     allowed_document_ids: frozenset[str], progress_id: str | None,
                     model: str | None, history: str) -> tuple[dict, str]:
    """The document pipeline, as it was before the router: scope, retrieve,
    answer, ambiguity, the B8 re-judgement. Returns (result, resolved)."""
    # SCOPE ONLY NARROWS (CLAUDE.md rule 5). A document the reader selected
    # wins over a name in the question; a named or referenced document narrows
    # an unscoped question; several matching documents narrow to those, none
    # of them chosen.
    scoped_allowed = allowed_document_ids
    if understood and not selected_document:
        if understood.get("document_id") in allowed_document_ids:
            document_id = understood["document_id"]
        elif understood.get("scope_ids"):
            scoped_allowed = allowed_document_ids & frozenset(understood["scope_ids"])

    result = answer_mod.answer(
        resolved, tier=tier, document_id=document_id, limit=limit,
        allowed_document_ids=scoped_allowed,
        progress_id=progress_id,
        history=history,
        model=model,
    )
    if understood is not None:
        result["understanding"] = understood
    # B6C: the same text in several documents makes "which document" an
    # accident of ranking. Reported, never resolved silently - only for a
    # question that was not scoped to one document.
    if not document_id:
        same = understanding_mod.ambiguous_source(result)
        if same:
            names = understanding_mod.document_names(frozenset(same))
            result["scope_ambiguity"] = {
                "reason": "the same text appears in more than one document; "
                          "name the document to answer from one of them",
                "documents": [{"document_id": d, "filename": names.get(d)} for d in same],
            }
    # B8: judged again now the scope and ambiguity are known. An accepted
    # model judgement from answer() is kept while the structure still agrees.
    from . import answerability
    rejudged = answerability.assess(resolved, result, allowed_document_ids=scoped_allowed)
    earlier = result.get("answerability") or {}
    if not (rejudged["verdict"] == earlier.get("verdict") == answerability.SUPPORTED
            and (earlier.get("judge") or {}).get("accepted")):
        result["answerability"] = rejudged
    return result, resolved
