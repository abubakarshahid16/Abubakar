"""Mutations of `backend/app/keyword.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B14_GLOSSARY_PHRASE -----------------------------------------
    #: B14: the glossary-phrase pass had no test that could fail - the existing one
    #: passed with the pass deleted, because two chunks can crowd nothing out.
    Mutation(
        id="M305", phase=32,
        description="delete the exact-phrase pass, so a glossary definition is "
                    "crowded out of the candidate list by scattered-word matches",
        path=APP / "keyword.py",
        anchor="    phrase = build_phrase_query(question)",
        replacement='    phrase = ""',
        target="tests/test_keyword.py",
        keyword="survives_a_crowd",
    ),
    # ---- from B12_SCOPED_CORRECTIONS --------------------------------------
    #: B12: a spelling correction named a word found only in a document the caller
    #: may not read, because fts5vocab is one term list for the whole index.
    Mutation(
        id="M306", phase=33,
        description="offer the closest corpus-wide word without checking the "
                    "caller's scope - the presence oracle B12 closed",
        path=APP / "keyword.py",
        anchor="        if term_occurrences(\n"
               "            candidate, document_id, allowed_document_ids=allowed_document_ids\n"
               "        ) > 0:",
        replacement="        if True:",
        target="tests/test_keyword.py",
        keyword="unreadable_document or closer_word",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M307", phase=33,
        description="scope REFUSES instead of filtering: an out-of-scope best "
                    "match hides the in-scope word the caller may be offered",
        path=APP / "keyword.py",
        anchor="        ) > 0:\n            return candidate\n    return None",
        replacement="        ) > 0:\n            return candidate\n        break\n    return None",
        target="tests/test_keyword.py",
        keyword="closer_word",
        tags=("permission",),
    ),
)
