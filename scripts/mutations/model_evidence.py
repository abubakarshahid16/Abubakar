"""Mutations of `backend/app/model_evidence.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M527", phase=61,
        description="drop the whitespace collapse, so a real quotation that "
                    "the page breaks across two lines is rejected",
        path=APP / "model_evidence.py",
        anchor="    return needle in _collapse(source_text)",
        replacement="    return (quote or '') in (source_text or '')",
        target="tests/test_model_evidence.py",
        keyword="a_quote_joining_a_line_break_is_verified",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M528", phase=61,
        description="fold case before comparing, so a lower-cased paraphrase "
                    "passes as a quotation (case is not on the approved list)",
        path=APP / "model_evidence.py",
        anchor='    return _WHITESPACE.sub(" ", text).strip()',
        replacement='    return _WHITESPACE.sub(" ", text).strip().lower()',
        target="tests/test_model_evidence.py",
        keyword="a_case_difference_is_not_verified",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M538", phase=61,
        description="drop the en dash item from the closed list, so a model's "
                    "re-typed hyphen no longer verifies",
        path=APP / "model_evidence.py",
        anchor=r'    "–": "-",                  # en dash' + "\n",
        replacement="",
        target="tests/test_model_evidence.py",
        keyword="en_dash_matches_hyphen",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M539", phase=61,
        description="drop the curly double quote item - the scope-pilot "
                    "SAES-L-109 failure shape comes back",
        path=APP / "model_evidence.py",
        anchor=r"""    "“": '"', "”": '"',   # curly double quotes""" + "\n",
        replacement="",
        target="tests/test_model_evidence.py",
        keyword="curly_double_quotes_match_straight",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M574", phase=61,
        description="a discipline word anywhere on a title line counts as STATED "
                    "(the 'Process' signature-cell case is accepted)",
        path=APP / "model_evidence.py",
        anchor="    if line is not None and _TITLE_CUE.search(line) and states:\n",
        replacement="    if line is not None and states:\n",
        target="tests/test_discipline_evidence.py",
        keyword="signature_cell_word_is_inferred",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M575", phase=61,
        description="a discipline counts as STATED although the quote does not "
                    "say it (inferred from a document number)",
        path=APP / "model_evidence.py",
        anchor="    if line is not None and _TITLE_CUE.search(line) and states:\n",
        replacement="    if line is not None and _TITLE_CUE.search(line):\n",
        target="tests/test_discipline_evidence.py",
        keyword="inferred_from_a_document_number",
        tags=("honesty", "model"),
    ),
)
