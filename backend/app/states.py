"""Document lifecycle state machine.

Documents were being left at `embedding` forever with `indexed_at` null,
because nothing ever moved them on. Every state is defined here, with the
transitions that are legal, so a finished document always reaches a terminal
state and the UI never has to guess.

Ingestion order matters: the keyword index is built BEFORE embedding, so a
document becomes answerable as soon as chunking and FTS are done. Embedding
then upgrades it from keyword-only to hybrid in the background.
"""

from __future__ import annotations

# ---------------------------------------------------------------- states

QUEUED = "queued"
EXTRACTING = "extracting"
CHUNKING = "chunking"
INDEXING_KEYWORD = "indexing_keyword"
PARTIALLY_SEARCHABLE = "partially_searchable"   # keyword search works, vectors pending
READY = "ready"                                  # keyword + vector both complete
#: Processing completed successfully but produced nothing searchable - a fully
#: scanned PDF, or a document whose every chunk was excluded. Calling that
#: "ready" tells an operator the document is usable when it answers nothing.
NO_SEARCHABLE_CONTENT = "no_searchable_content"
FAILED = "failed"

ALL_STATES = (
    QUEUED,
    EXTRACTING,
    CHUNKING,
    INDEXING_KEYWORD,
    PARTIALLY_SEARCHABLE,
    READY,
    NO_SEARCHABLE_CONTENT,
    FAILED,
)

#: States from which no further work happens.
TERMINAL_STATES = frozenset({READY, NO_SEARCHABLE_CONTENT, FAILED})

#: States in which the document can already answer questions.
ANSWERABLE_STATES = frozenset({PARTIALLY_SEARCHABLE, READY})

#: A document is only "ready" when embedding has finished. Anything earlier
#: that can answer is "partially searchable" - never labelled ready.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    QUEUED: frozenset({EXTRACTING, FAILED}),
    EXTRACTING: frozenset({EXTRACTING, CHUNKING, FAILED}),
    CHUNKING: frozenset({INDEXING_KEYWORD, FAILED}),
    INDEXING_KEYWORD: frozenset({PARTIALLY_SEARCHABLE, NO_SEARCHABLE_CONTENT, FAILED}),
    # embedding runs in the background from here; the document stays
    # answerable throughout and only then becomes ready
    # CHUNKING is legal from here for the same reason it is legal from READY:
    # the page text changed and has to be re-chunked. OCR writes recognised
    # text for a scanned page of an already-answerable document, which is a
    # revision of that page's content - so recognition rounds go back through
    # chunking and the keyword index, and the document becomes progressively
    # searchable. Omitting it made every scanned document reach `failed` with
    # "cannot go from 'partially_searchable' to 'chunking'", which only a run
    # from a clean clone surfaced.
    PARTIALLY_SEARCHABLE: frozenset(
        {PARTIALLY_SEARCHABLE, CHUNKING, READY, NO_SEARCHABLE_CONTENT, FAILED}
    ),
    READY: frozenset({CHUNKING, FAILED}),   # re-ingest on a new revision
    NO_SEARCHABLE_CONTENT: frozenset({CHUNKING, EXTRACTING, FAILED}),
    FAILED: frozenset({QUEUED, EXTRACTING, CHUNKING, FAILED}),
}


class IllegalTransition(ValueError):
    pass


def can_transition(current: str, nxt: str) -> bool:
    return nxt in LEGAL_TRANSITIONS.get(current, frozenset())


def check_transition(current: str, nxt: str) -> None:
    if nxt not in ALL_STATES:
        raise IllegalTransition(f"unknown state {nxt!r}")
    if not can_transition(current, nxt):
        raise IllegalTransition(f"cannot go from {current!r} to {nxt!r}")


def is_answerable(state: str) -> bool:
    return state in ANSWERABLE_STATES


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def label(state: str, embedded: int, total: int) -> str:
    """Honest human label. A partially processed document is never 'ready'."""
    if state == READY:
        return "ready"
    if state == NO_SEARCHABLE_CONTENT:
        return "no searchable content"
    if state == PARTIALLY_SEARCHABLE:
        return f"partially searchable - {embedded}/{total} embedded"
    return state.replace("_", " ")
