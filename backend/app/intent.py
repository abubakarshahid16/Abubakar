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
