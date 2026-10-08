"""Mutations of the engineering-synonym glossary and its three uses."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_engineering_synonyms.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1371", phase=1371, description="keyword search ignores the glossary",
             path=APP / "keyword.py",
             anchor="    for word, phrases in _glossary_variants(question).items():",
             replacement="    for word, phrases in {}.items():",
             target=_T, keyword="lay_word_reaches", tags=("retrieval",)),
    Mutation(id="M1372", phase=1371, description="the lexical gate ignores the glossary",
             path=APP / "lexical.py",
             anchor="        forms.extend(expanded.get(term.lower(), ()))",
             replacement="        pass",
             target=_T, keyword="measured_misses_now_answer", tags=("retrieval",)),
    Mutation(id="M1373", phase=1371, description="the reranker never scores the document's wording",
             path=APP / "search.py",
             anchor="        worded = glossary.rewrite(question) if synonyms else None",
             replacement="        worded = None",
             target=_T, keyword="measured_misses_now_answer", tags=("retrieval",)),
    Mutation(id="M1374", phase=1371, description="'salt spray' is widened to chlorides",
             path=APP / "glossary.py",
             anchor="        if following in NOT_BEFORE.get(word, frozenset()):\n            continue",
             replacement="        pass",
             target=_T, keyword="salt_spray_is_never_widened", tags=("honesty",)),
    Mutation(id="M1375", phase=1371, description="the synonyms searched are not reported",
             path=APP / "search.py",
             anchor='        "synonyms_searched": synonyms,',
             replacement='        "synonyms_searched": {},',
             target=_T, keyword="expansion_is_reported", tags=("honesty",)),
    Mutation(id="M1376", phase=1371, description="the rewrite's score replaces the reader's own",
             path=APP / "search.py",
             anchor="            scored = [(cid, max(score, also.get(cid, score))) for cid, score in scored]",
             replacement="            scored = list(also.items())",
             target=_T, keyword="higher_of_the_two", tags=("retrieval",)),
)
