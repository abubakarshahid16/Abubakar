"""Mutations of `backend/app/answer.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from CORPUS_QUESTIONS --------------------------------------------
    #: Document Q&A answered "there are 12 distinct standards" from three retrieved
    #: passages, of a library holding 272. Both halves of the fix, both sides.
    # ----------------------------------------- part 1: the count is bounded
    Mutation(
        id="M251", phase=25,
        description="PUT THE DEFECT BACK: drop the guard on generated text, so "
                    "'there are 12 distinct standards' reaches the reader as a "
                    "fact about the library",
        path=APP / "answer.py",
        anchor="    text, counts_bounded = corpus_mod.bound_counts(text, len(passages))",
        replacement="    counts_bounded = 0",
        target="tests/test_corpus_questions.py",
        keyword="counting_question_names_its_boundary",
        tags=("honesty", "critical"),
    ),
    # --------------------------------- part 2: the library answers itself
    Mutation(
        id="M254", phase=25,
        description="SEND A LIBRARY QUESTION TO RETRIEVAL AGAIN - the routing "
                    "that let three passages answer for 272 standards",
        path=APP / "answer.py",
        anchor="    corpus_q = corpus_mod.classify(question) if document_id is None else None",
        replacement="    corpus_q = None",
        target="tests/test_corpus_questions.py",
        keyword="answered_without_searching",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M258", phase=25,
        description="consult the library for a question scoped to ONE "
                    "document, where 'how many standards' means what it cites",
        path=APP / "answer.py",
        anchor="    corpus_q = corpus_mod.classify(question) if document_id is None else None",
        replacement="    corpus_q = corpus_mod.classify(question)",
        target="tests/test_corpus_questions.py",
        keyword="scoped_to_one_document",
    ),
)
