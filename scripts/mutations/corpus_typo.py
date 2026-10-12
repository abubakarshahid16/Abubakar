"""Mutation for typo-tolerant library counts (2026-10-01, M1850).
File: backend/app/corpus.py. Target: backend/tests/test_corpus_questions.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1850", phase=1850,
             description="a misspelt noun is no longer repaired, so the count goes to retrieval",
             path=APP / "corpus.py",
             anchor='return " ".join(_repair(w) for w in words)',
             replacement='return " ".join(words)',
             target="tests/test_corpus_questions.py", keyword="typo", tags=("corpus_typo",)),
)
