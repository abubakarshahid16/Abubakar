"""Mutations for abbreviation <-> spelled-out matching (2026-10-06, M2000-M2009).

A question typed as an abbreviation matches passages that spell it out, and a
spelled-out question matches passages that only print the abbreviation, with
the expansion only ever ADDING match terms and never bypassing the gate.
Files: backend/app/acronyms.py, keyword.py, search.py, lexical.py.
Target: tests/test_r3_retrieval_abbreviations.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_r3_retrieval_abbreviations.py"
_TAG = ("r3_retrieval",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2000", phase=2000,
             description="a hyphenated capitalised expansion word ends a glossary row again",
             path=APP / "acronyms.py",
             anchor='_EXPANSION_WORD = r"[A-Za-z][a-z]*(?:-[A-Za-z][a-z]*)*"',
             replacement='_EXPANSION_WORD = r"[A-Za-z][a-z\\-]*"',
             target=_T, keyword="hyphenated", tags=_TAG),
    Mutation(id="M2001", phase=2001,
             description="the built-in abbreviation list is never consulted",
             path=APP / "acronyms.py",
             anchor="    if is_typed_as_abbreviation:\n        found.update(BUILTIN.get(acronym, ()))",
             replacement="    if False:\n        found.update(BUILTIN.get(acronym, ()))",
             target=_T, keyword="builtin", tags=_TAG),
    Mutation(id="M2002", phase=2002,
             description="the named document's own designation is required inside a passage again",
             path=APP / "search.py",
             anchor="    if document_id and allowed_document_ids and document_id in allowed_document_ids:\n        from . import lexical",
             replacement="    if False:\n        from . import lexical",
             target=_T, keyword="designation", tags=_TAG),
    Mutation(id="M2003", phase=2003,
             description="the reranker no longer scores the abbreviated / spelled-out wording",
             path=APP / "search.py",
             anchor=("        rewordings = ([worded] if worded else []) + acronyms.rewrites(\n"
                     "            question, document_id, allowed_document_ids=allowed_document_ids)"),
             replacement="        rewordings = [worded] if worded else []",
             target=_T, keyword="returns_the_acronym", tags=_TAG),
    Mutation(id="M2004", phase=2004,
             description="an expansion form counts as present although it occurs nowhere (bypasses the gate)",
             path=APP / "lexical.py",
             anchor="            absent.append(term)\n            continue\n\n        present.append(term)",
             replacement=("            if len(forms) > 1:\n"
                          "                present.append(term)\n"
                          "                covered.append(term)\n"
                          "                distinguishing_count += 1\n"
                          "                continue\n"
                          "            absent.append(term)\n            continue\n\n        present.append(term)"),
             target=_T, keyword="still_refuses", tags=_TAG),
    Mutation(id="M2005", phase=2005,
             description="a spelled-out phrase is never expanded to its abbreviation on the keyword side",
             path=APP / "acronyms.py",
             anchor='        if re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", flat):',
             replacement="        if False:",
             target=_T, keyword="spelled_out", tags=_TAG),
    Mutation(id="M2006", phase=2006,
             description="a hyphenated expansion is not also known with spaces",
             path=APP / "acronyms.py",
             anchor='        for spelled in _spellings(expansion)\n        if " " in spelled',
             replacement='        for spelled in [expansion]\n        if " " in spelled',
             target=_T, keyword="spelled_out", tags=_TAG),
    Mutation(id="M2007", phase=2007,
             description="a scoped refusal says 'the indexed documents' again",
             path=APP / "lexical.py",
             anchor="    if document_id and document_id in allowed_document_ids:\n        from .db import connect",
             replacement="    if False:\n        from .db import connect",
             target=_T, keyword="names_the_document", tags=_TAG),
    Mutation(id="M2008", phase=2008,
             description="the tail of a spelled-out form is no longer a retrieval candidate term",
             path=APP / "acronyms.py",
             anchor='    return [" ".join(words[-2:])] if len(words) >= 3 else []',
             replacement="    return []",
             target=_T, keyword="designation", tags=_TAG),
    Mutation(id="M2009", phase=2009,
             description="expansion REPLACES the typed abbreviation instead of adding to it",
             path=APP / "keyword.py",
             anchor="            out[key] = list(dict.fromkeys([key, *equivalents, *tails]))",
             replacement="            out[key] = list(dict.fromkeys([*equivalents, *tails]))",
             target=_T, keyword="never_removed", tags=_TAG),
)
