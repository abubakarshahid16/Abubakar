"""Mutations of `backend/app/corpus.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from CORPUS_QUESTIONS --------------------------------------------
    #: Document Q&A answered "there are 12 distinct standards" from three retrieved
    #: passages, of a library holding 272. Both halves of the fix, both sides.
    Mutation(
        id="M252", phase=25,
        description="the guard finds the count and bounds nothing - the rule "
                    "itself, not only its wiring",
        path=APP / "corpus.py",
        anchor="        if match is None or _BOUNDED.search(sentence):",
        replacement="        if match is None or True:",
        target="tests/test_corpus_questions.py",
        keyword="every_unbounded_count_of_documents_is_bounded",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M253", phase=25,
        description="stop honouring 'retrieved', rewriting a model that had "
                    "ALREADY named its boundary",
        path=APP / "corpus.py",
        anchor="        if match is None or _BOUNDED.search(sentence):",
        replacement="        if match is None:",
        target="tests/test_corpus_questions.py",
        keyword="already_names_its_boundary or bounded_by_their_citation",
    ),
    Mutation(
        id="M255", phase=25,
        description="COUNT DOCUMENTS OUTSIDE THE GRANT SET, so a corpus "
                    "answer reveals how many standards you may not read",
        path=APP / "corpus.py",
        anchor="            WHERE d.id IN ({marks})",
        replacement="            WHERE 1 = 1 OR d.id IN ({marks})",
        target="tests/test_corpus_questions.py",
        keyword="outside_the_grant_set",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M256", phase=25,
        description="call a standard still being processed 'loaded'",
        path=APP / "corpus.py",
        anchor='        slot["loaded" if r["status"] in _LOADED else "not_loaded"] += r["n"]',
        replacement='        slot["loaded"] += r["n"]',
        target="tests/test_corpus_questions.py",
        keyword="still_processing_is_not_counted_as_loaded",
        tags=("honesty",),
    ),
    Mutation(
        id="M257", phase=25,
        description="answer a question about BOTH with the library alone, so "
                    "'how many standards cover hydrotesting' never searches",
        path=APP / "corpus.py",
        anchor="    return CorpusQuestion(kind=kind, role=role, qualified=bool(content),",
        replacement="    return CorpusQuestion(kind=kind, role=role, qualified=False,",
        target="tests/test_corpus_questions.py",
        keyword="gets_both_in_separate_fields or marked_for_both",
    ),
    Mutation(
        id="M263", phase=25,
        description="let Markdown around the number hide the count again - "
                    "the REAL model's '**five** distinct standards' slipped "
                    "past the first version of the guard",
        path=APP / "corpus.py",
        anchor='COUNT_CLAIM = re.compile(r"(?<![A-Za-z0-9])" + _NUMBER + _MD + r"\\s+" + _MD',
        replacement='COUNT_CLAIM = re.compile(r"(?<![A-Za-z0-9])" + _NUMBER + r"\\s+" + _MD',
        target="tests/test_corpus_questions.py",
        keyword="real_models_own_words or markdown_around_the_count",
        tags=("honesty",),
    ),
)
