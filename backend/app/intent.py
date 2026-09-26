"""What the reader actually typed.

Typing "hi" used to search the corpus, refuse, and offer three unrelated
passages - "2.1.1 What Is Privacy?", "9.5 FINITE DIFFERENCE APPROXIMATIONS",
"9.33 In Section 9.3.12". Almost everyone opens with a greeting, so that was
the first five seconds of the product for most people who ever see it.

A greeting is not a failed question, and answering it with a refusal plus
evidence misrepresents both. Classification happens BEFORE retrieval, so an
input that was never a document query never produces search results at all -
there is nothing to show under "what was considered", because nothing was
considered.

The classifier is deliberately narrow. It recognises conversational openers
and nothing else; anything it is unsure about is treated as a real question
and searched. Over-classifying would be the worse failure: refusing to search
a genuine question because it looked chatty.
"""

from __future__ import annotations

import re

from .db import connect

#: Conversational inputs, matched whole. Kept as exact phrases rather than
#: keywords so "hi" is a greeting but "hi-lo alarm setpoint" is a question.
GREETINGS = {
    "hi", "hii", "hiya", "hello", "helo", "hey", "heya", "yo", "hola",
    "good morning", "good afternoon", "good evening", "good day",
    "salaam", "salam", "assalam", "assalamu alaikum", "as salam alaikum",
    "greetings", "howdy",
}

THANKS = {
    "thanks", "thank you", "thankyou", "thx", "ty", "cheers", "much appreciated",
    "thanks a lot", "thank you very much", "appreciate it",
}

ACKNOWLEDGEMENTS = {
    "ok", "okay", "k", "kk", "sure", "yes", "yeah", "yep", "yup", "no", "nope",
    "fine", "got it", "understood", "cool", "nice", "great", "good", "right",
    "alright", "perfect", "done", "test", "testing",
}

FAREWELLS = {"bye", "goodbye", "see you", "see ya", "later", "good night", "goodnight"}

#: Questions about the assistant rather than about the documents.
ABOUT_THE_ASSISTANT = {
    "who are you", "what are you", "what can you do", "what do you do",
    "how are you", "how do you work", "help", "what is this", "who is this",
    "what should i ask", "what can i ask",
}

#: Everything above, mapped to the kind it belongs to.
_PHRASES: dict[str, str] = {
    **{p: "greeting" for p in GREETINGS},
    **{p: "thanks" for p in THANKS},
    **{p: "acknowledgement" for p in ACKNOWLEDGEMENTS},
    **{p: "farewell" for p in FAREWELLS},
    **{p: "about_the_assistant" for p in ABOUT_THE_ASSISTANT},
}

DOCUMENT_QUESTION = "document_question"
ADVICE_REQUEST = "advice_request"

# ------------------------------------------------- a request for advice
#
# "i would like to implement FEED documentation for an EPC project, can you
# please help me with that?" used to be searched, refused, and described as
# "the documents do not answer this - the closest passages were not a credible
# match". Every word of that is a misdescription: the reader did not ask what a
# document says, so the corpus was never the thing that fell short.
#
# It is recognised HERE rather than after retrieval for the same reason a
# greeting is: nothing was searched, so nothing may be shown as considered.
#
# CONSERVATIVE BY CONSTRUCTION, and deliberately biased towards missing an
# advice request rather than catching a document question. A miss costs the
# reader the older, blunter refusal - which is where they are today. A false
# positive tells someone asking a fair question about their own documents that
# they were not asking about their documents, and never searches. So:
#
#   * a lookup marker anywhere VETOES the whole classification, before any
#     other rule is consulted. "can you help me find what the spec says about
#     surface preparation" is a document question wearing a polite wrapper.
#   * the task verbs name work the reader would CARRY OUT and are chosen to
#     be words an engineering clause rarely uses about the reader. "prepare",
#     "apply", "design", "inspect" and "calculate" were considered and left
#     out: "how should i prepare the surface" is answerable from a coatings
#     spec, and losing it would be exactly the failure above.
#   * the polite-help pattern alone is never enough. "can you help me" must
#     arrive WITH a task verb; on its own it is how half of all questions to
#     an assistant are phrased.

#: Work the reader would do, rather than something a document states.
_TASK_VERB = (
    r"(?:implement|develop|create|build|write|draft|produce|plan|"
    r"set\s?up|roll\s+out|put\s+together|get\s+started\s+with)"
)

#: Any of these means the reader wants something looked up IN the documents,
#: however the sentence around it is phrased. Checked first, and decisive.
_WANTS_A_LOOKUP = re.compile(
    r"\b(?:find|locate|look\s+up|search|tell\s+me|show\s+me|what\s+does|"
    r"what\s+do|what\s+is|what\s+are|where\s+does|where\s+is|"
    r"which\s+document|says?\s+about|according\s+to|in\s+the\s+documents?|"
    r"in\s+the\s+spec|clause|section|page|per\s+the)\b"
)

#: "can you please help me with that", "walk me through it".
_ASKS_FOR_HELP = re.compile(
    r"\b(?:help|assist)\s+(?:me|us)\b"
    r"|\bcan\s+you\s+(?:please\s+)?(?:help|assist)\b"
    r"|\b(?:walk|guide)\s+(?:me|us)\s+through\b"
    r"|\bguide\s+(?:me|us)\b"
)

#: "i would like to implement ...", "we need to write ..."
_STATES_A_TASK = re.compile(
    r"\b(?:i|we)\s*(?:'m|m)?\s+"
    r"(?:would\s+like\s+to|want\s+to|need\s+to|am\s+trying\s+to|"
    r"are\s+trying\s+to|trying\s+to)\s+" + _TASK_VERB + r"\b"
)

#: "how do i set up ...", "how should we roll out ..."
_ASKS_HOW_TO = re.compile(
    r"\bhow\s+(?:do|can|should|would)\s+(?:i|we)\s+" + _TASK_VERB + r"\b"
)

_TASK_VERB_ANYWHERE = re.compile(r"\b" + _TASK_VERB + r"\b")


def _is_advice_request(normalised: str) -> bool:
    """Is the reader asking how to do something, rather than what a document
    says? Two independent signals, and a veto that outranks both."""
    if len(normalised.split()) < 4:
        # too short to carry both signals, and short inputs are where the
        # other classifications live
        return False
    if _WANTS_A_LOOKUP.search(normalised):
        return False
    if _STATES_A_TASK.search(normalised) or _ASKS_HOW_TO.search(normalised):
        return True
    return bool(
        _ASKS_FOR_HELP.search(normalised) and _TASK_VERB_ANYWHERE.search(normalised)
    )


#: A lone token that names something rather than saying something. "NDFT" and
#: "P-101A" are real lookups; "coating" on its own is not, and neither is "ok".
#: Uppercase, digits, or identifier punctuation is what separates them.
_IDENTIFIER_LIKE = re.compile(r"^(?=.*[A-Z0-9])[A-Za-z0-9][A-Za-z0-9.\-/_]*$")

_STRIP_EDGES = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def _normalise(text: str) -> str:
    """Lowercased, trimmed of surrounding punctuation and repeated spaces."""
    return " ".join(_STRIP_EDGES.sub("", text or "").split()).lower()


def classify(question: str) -> str:
    """One of: document_question, empty, greeting, thanks, acknowledgement,
    farewell, about_the_assistant, advice_request, not_a_question."""
    raw = (question or "").strip()
    if not raw:
        return "empty"

    normalised = _normalise(raw)
    if not normalised:
        # punctuation or symbols only - "???" is not a question
        return "not_a_question"

    kind = _PHRASES.get(normalised)
    if kind:
        return kind

    # A greeting with a tail - "hi there", "hello!" - is still a greeting.
    first = normalised.split()[0]
    if first in GREETINGS and len(normalised.split()) <= 3:
        return "greeting"

    words = raw.split()
    if len(words) == 1 and not _IDENTIFIER_LIKE.match(words[0].strip(".,!?;:")):
        # A single lowercase ordinary word is not a question. An identifier is.
        return "not_a_question"

    # Last, and only on what everything above let through: a request for help
    # with a task is not a question about the documents. Unsure means
    # document_question, which is where every borderline phrasing lands.
    if _is_advice_request(normalised):
        return ADVICE_REQUEST

    return DOCUMENT_QUESTION


def is_document_question(question: str) -> bool:
    return classify(question) == DOCUMENT_QUESTION


# ------------------------------------------------------------------ examples


def _clean_title(section: str) -> str:
    """The title without its clause number or trailing parenthetical."""
    title = section.split(" ", 1)[1] if " " in section else section
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip(" .")
    return title


def example_questions(
    limit: int = 3, *, allowed_document_ids: frozenset[str]
) -> list[str]:
    """Questions drawn from the documents this caller may actually read.

    Suggesting "what is the NDFT for coating system no. 1" to someone whose
    corpus is two textbooks would be a worse first impression than suggesting
    nothing. Every example here is built from a real clause heading in a
    document that can currently answer, so every one of them works.

    `allowed_document_ids` is REQUIRED and keyword-only. Every example embeds
    a real FILENAME and a real CLAUSE HEADING, and this ran unscoped: typing
    "hi" - or "thanks" - returned the filenames and section titles of
    documents the caller has no grant on, inside the answer text, and
    `answer()` persists that text to the conversation transcript. A greeting
    was the cheapest way to enumerate the corpus, and the disclosure outlived
    the request.

    An empty scope offers no examples, which is the same answer an empty
    corpus gets and the right one: there is nothing this caller can be shown.
    """
    if not allowed_document_ids:
        return []
    marks = ",".join("?" * len(allowed_document_ids))
    try:
        rows = connect().execute(
            f"""SELECT c.filename, c.section, COUNT(*) AS n
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.retrievable = 1 AND c.section IS NOT NULL
                 AND d.status IN ('ready', 'partially_searchable')
                 AND c.document_id IN ({marks})
               GROUP BY c.document_id, c.section
               -- substantial sections first: a clause with more chunks makes a
               -- better example than a one-line heading. No minimum, or a
               -- small corpus would offer nothing at all.
               ORDER BY c.document_id, n DESC""",
            sorted(allowed_document_ids),
        ).fetchall()
    except Exception:  # noqa: BLE001 - a suggestion is never worth an error
        return []

    seen_files: set[str] = set()
    examples: list[str] = []
    # One per document first, so the examples show the breadth of the corpus
    # rather than three questions about the same clause.
    for pass_no in (1, 2):
        for r in rows:
            if len(examples) >= limit:
                return examples
            if pass_no == 1 and r["filename"] in seen_files:
                continue
            title = _clean_title(r["section"])
            if len(title.split()) < 2 or len(title) > 60:
                continue
            question = f"What does {r['filename']} say about {title}?"
            if question in examples:
                continue
            examples.append(question)
            seen_files.add(r["filename"])
    return examples


#: What to say for each non-question kind. Short, and every one of them points
#: at the thing the reader can actually do next.
_REPLIES = {
    "empty": "I answer questions about your documents. Type a question to begin.",
    "greeting": "Hello. I answer questions about your documents, quoting the source with its page and clause.",
    "thanks": "You're welcome. Ask another question about your documents whenever you like.",
    "acknowledgement": "I answer questions about your documents, quoting the source with its page and clause.",
    "farewell": "Goodbye. Your conversations stay on this machine.",
    "about_the_assistant": (
        "I answer questions about the documents loaded on this machine. I quote "
        "the source with its page and clause, and I say so when the documents "
        "do not contain the answer. Nothing you type leaves this machine."
    ),
    "advice_request": (
        "That is a request for help with a task, not a question about what the "
        "documents say. I quote the documents loaded on this machine and cite "
        "the page and clause; I cannot advise you on how to do the work, and I "
        "will not invent an answer. If one of these documents covers the "
        "subject, ask what it says about it."
    ),
    "not_a_question": "I answer questions about your documents. Try a full question.",
}


def guidance(kind: str, examples: list[str] | None = None) -> str:
    """The reply text for a non-question input, with real examples appended."""
    reply = _REPLIES.get(kind, _REPLIES["not_a_question"])
    examples = examples or []
    if not examples:
        return reply
    lines = "\n".join(f"  • {q}" for q in examples)
    return f"{reply}\n\nTry one of these:\n{lines}"


# =============================================================== the router
#
# OWNER ORDER 2026-09-26 (chat redesign, 2c). Every chat message is routed to
# one of seven answer kinds BEFORE anything is searched. The rules are words,
# not a model, so a routing decision can be read, tested and argued with.
#
# THE ONE ASYMMETRY THAT MATTERS: a question that names a document, a clause,
# an identifier or the reader's own material goes to the DOCUMENTS and is
# never answered from general knowledge - if the documents cannot answer it,
# the reader is told so. Answering "what is the design pressure of our drum"
# from general knowledge would be a confident wrong answer about their plant.
# Only a question with NO document signal may be answered as general
# knowledge, and it is always labelled so.

GENERAL = "general"
DOCUMENT = "document"
WEB = "web"
MIXED = "mixed"
REWRITE = "rewrite"
ACTION = "action"
RECORDS = "records"
#: A question with neither signal: the documents are tried first, and only a
#: question they cannot speak to at all is answered from general knowledge.
EITHER = "either"

#: Small talk: answered naturally, never searched, never a model call.
SMALL_TALK = ("greeting", "thanks", "acknowledgement", "farewell", "about_the_assistant",
              "empty", "not_a_question")

#: Rewrite styles, in the words the chips and the reader use.
STYLES = {
    "points": r"\b(?:in|as|into)\s+(?:bullet\s+)?points\b|\bbullet(?:ed)?\s*(?:points|list)?\b|\bas\s+a\s+list\b",
    "paragraph": r"\b(?:in|as)\s+(?:one\s+|a\s+)?paragraph\b",
    "more_detail": r"\bmore\s+detail(?:ed)?\b|\bin\s+(?:more\s+)?detail\b|\belaborate\b|\bexpand\s+on\b",
    "shorter": r"\bshorter\b|\bbriefer\b|\bmore\s+concise\b|\bin\s+short\b|\btl;?dr\b|\bsummari[sz]e\s+(?:it|that|this)\b",
    "simpler": r"\bsimpl(?:er|y|ify)\b|\bplain\s+(?:english|language|words)\b|\blike\s+i'?m\s+not\s+an?\s+engineer\b|\bfor\s+a\s+(?:beginner|non-?engineer|layman)\b",
    "engineer": r"\bfor\s+an?\s+engineer\b|\bmore\s+technical\b|\btechnical(?:ly)?\s+precise\b",
    "check_documents": r"\bcheck\s+(?:it\s+|this\s+|that\s+)?against\s+(?:my|our|the)\s+documents?\b",
    "manager": r"\bfor\s+(?:my|the|a)\s+manager\b",
}
_STYLE_RES = {name: re.compile(p) for name, p in STYLES.items()}

#: Words that carry no subject of their own in a rewrite request.
_REWRITE_FILLER = {
    "give", "me", "that", "this", "it", "now", "please", "can", "could", "you", "make",
    "put", "write", "rewrite", "redo", "again", "with", "a", "an", "the", "bit", "little",
    "and", "but", "in", "as", "into", "one", "more", "some", "too", "also", "then", "ok",
    "okay", "so", "same", "answer", "version", "just", "do", "say", "explain", "tell",
    "how", "about", "for", "of", "to", "i", "m", "im", "not", "is", "was", "be", "way",
}

_ACTION = re.compile(
    r"\b(?:write|draft|turn|make|put)\s+(?:that|this|it|up)?\s*(?:up\s+)?(?:as|into)?\s*"
    r"(?:a\s+|an\s+)?(?:review\s+)?comment\b"
    r"|\bdraft\s+(?:a\s+)?comment\b"
    r"|\badd\s+(?:that|this|it)\s+to\s+(?:the\s+)?(?:review|comment\s+sheet|crs)\b"
    r"|\bsummari[sz]e\s+(?:that|this|it)\s+for\s+(?:my|the)\s+manager\b"
)

#: The reader's own material, or a place in a document.
_DOCUMENT_WORDS = re.compile(
    r"\b(?:my|our|this|the|that|these|those|your|uploaded)\s+"
    r"(?:datasheets?|data\s+sheets?|submittals?|documents?|docs?|drawings?|specs?|specifications?|"
    r"reports?|files?|pdfs?|vendor\s+documents?|library|standards?)\b"
    r"|\b(?:clause|page|section|sheet|row|paragraph)\s+[\dA-Z]"
    r"|\baccording\s+to\b|\bper\s+the\b|\bin\s+the\s+(?:document|spec|standard|datasheet|library)\b"
    r"|\b(?:datasheet|submittal|standards?\s+library)\b"
    r"|\bcompany\s+standards?\b"
    r"|\b(?:compliant|complies|comply|compliance|conform(?:s|ance)?)\b"
    r"|\bdoes\s+(?:it|this|that)\s+(?:meet|satisfy|pass)\b",
    re.IGNORECASE,
)

#: Asked about the world, not the reader's documents.
_GENERAL_WORDS = re.compile(
    r"\bin\s+general\b|\bgenerally\b|\bexplain\s+(?:it\s+)?like\b|\blike\s+i'?m\b"
    r"|\bwhat(?:'s|\s+is)\s+the\s+difference\s+between\b|\bhow\s+does\s+\w+(?:\s+\w+)?\s+work\b"
    r"|\bwhy\s+(?:does|do|is|are)\b|\bwhat\s+(?:is|are)\s+(?:a|an)\s+\w+"
    r"|\bexplain\b|\bin\s+simple\s+terms\b|\bhistory\s+of\b",
    re.IGNORECASE,
)

#: A compliance question: answered from evidence, and ENDS with the engineer
#: notice - the chat never records a verdict.
COMPLIANCE = re.compile(
    r"\b(?:compliant|complies|comply|compliance|conform(?:s|ance)?|acceptable|approve[ds]?|"
    r"meet(?:s)?|satisf(?:y|ies)|pass(?:es)?)\b", re.IGNORECASE)
ENGINEER_NOTICE = "This needs an engineer's judgement - the passages are evidence, not a verdict"


def styles_in(text: str) -> list[str]:
    """Every rewrite style the text asks for, in a stable order."""
    lowered = (text or "").lower()
    return [name for name, rx in _STYLE_RES.items() if rx.search(lowered)]


def _subject_words(text: str) -> list[str]:
    lowered = (text or "").lower()
    for rx in _STYLE_RES.values():
        lowered = rx.sub(" ", lowered)
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'\-]*", lowered) if w not in _REWRITE_FILLER]


#: Words that ask about the public web rather than the reader's documents.
_WEB_WORDS = re.compile(
    r"\b(?:online|on\s+the\s+(?:web|internet)|search\s+the\s+(?:web|internet)|google|"
    r"(?:latest|newest|newer|current)\s+(?:edition|revision|version|issue)|"
    r"(?:any|recent)\s+news|web\s+search)\b")


def route(message: str, *, has_previous_answer: bool = False,
          document_in_scope: bool = False, web_enabled: bool = False) -> dict:
    """{kind, styles, small_talk, compliance, command, text} for one message.

    `text` is the message with any slash command removed. The order of the
    checks is the order of precedence, and each one says why it is where it is.
    """
    raw = (message or "").strip()
    command = None
    if raw.startswith("/"):
        head, _, rest = raw.partition(" ")
        command = head[1:].lower()
        raw = rest.strip()
    base = {"styles": styles_in(raw), "small_talk": None, "command": command,
            "compliance": bool(COMPLIANCE.search(raw)), "text": raw}
    # 1. Explicit commands win: the reader said exactly what they want.
    if command == "records":
        return {**base, "kind": RECORDS}
    if command == "quote":
        return {**base, "kind": DOCUMENT, "tier": "extract"}
    # 2. Small talk is answered naturally and never searched.
    kind = classify(raw)
    if kind in SMALL_TALK:
        return {**base, "kind": GENERAL, "small_talk": kind}
    # 2b. The public web, ONLY when the reader switched Web on for this
    #     question - otherwise these words are answered as they always were.
    #     A web question gets a consent turn first (chat_web); nothing leaves
    #     until the reader approves the exact phrase.
    if web_enabled and _WEB_WORDS.search(raw.lower()):
        return {**base, "kind": WEB}
    # 3. An action on the previous answer ("write that as a comment").
    if has_previous_answer and _ACTION.search(raw.lower()):
        return {**base, "kind": ACTION}
    # 4. A rewrite: a style asked for, and no subject of its own - "now in
    #    points with more detail". "Explain sulfidation simply" has a subject
    #    and is a new question with a style, not a rewrite.
    if has_previous_answer and base["styles"] and len(_subject_words(raw)) <= 1:
        return {**base, "kind": REWRITE}
    # 5. A request for help with a task is general knowledge, never searched.
    if kind == ADVICE_REQUEST:
        return {**base, "kind": GENERAL}
    # 6. The reader's own material: documents, and never general knowledge.
    from . import keyword
    if (document_in_scope or _DOCUMENT_WORDS.search(raw) or keyword.IDENTIFIER.search(raw)
            or keyword.find_designators(raw)):
        return {**base, "kind": DOCUMENT}
    # 7. The world, not the documents.
    if _GENERAL_WORDS.search(raw):
        return {**base, "kind": GENERAL}
    return {**base, "kind": EITHER}


def small_talk_reply(kind: str, *, provider_line: str) -> str:
    """A natural reply to small talk. `provider_line` says honestly who answers."""
    replies = {
        "greeting": "Hi! Ask me anything - about your documents, a standard, or engineering in general.",
        "thanks": "You're welcome. Anything else?",
        "acknowledgement": "Okay. What would you like to look at next?",
        "farewell": "Goodbye - your conversation is saved here if you want to pick it up later.",
        "about_the_assistant": (
            "I'm the chat in RAG Intelligence. I answer from your documents and show the page each "
            "point came from, and I can answer general engineering questions too - those are "
            f"labelled as general knowledge. {provider_line}"),
        "empty": "Type a question to begin.",
        "not_a_question": "Could you say a little more about what you'd like to know?",
    }
    return replies.get(kind, replies["not_a_question"])
