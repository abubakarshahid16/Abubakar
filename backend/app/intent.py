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
    farewell, about_the_assistant, not_a_question."""
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

    return DOCUMENT_QUESTION


def is_document_question(question: str) -> bool:
    return classify(question) == DOCUMENT_QUESTION


# ------------------------------------------------------------------ examples


def _clean_title(section: str) -> str:
    """The title without its clause number or trailing parenthetical."""
    title = section.split(" ", 1)[1] if " " in section else section
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip(" .")
    return title


def example_questions(limit: int = 3) -> list[str]:
    """Questions drawn from the documents that are actually loaded.

    Suggesting "what is the NDFT for coating system no. 1" to someone whose
    corpus is two textbooks would be a worse first impression than suggesting
    nothing. Every example here is built from a real clause heading in a
    document that can currently answer, so every one of them works.
    """
    try:
        rows = connect().execute(
            """SELECT c.filename, c.section, COUNT(*) AS n
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.retrievable = 1 AND c.section IS NOT NULL
                 AND d.status IN ('ready', 'partially_searchable')
               GROUP BY c.document_id, c.section
               -- substantial sections first: a clause with more chunks makes a
               -- better example than a one-line heading. No minimum, or a
               -- small corpus would offer nothing at all.
               ORDER BY c.document_id, n DESC"""
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
