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
        id="M529", phase=61,
        description="treat EVERY page line as an evidence line (drop the "
                    "title/tag/service filter), so 'COLUMN A' in a table "
                    "header yields Pressure Vessel",
        path=APP / "model_evidence.py",
        anchor="        lines += [line for line in (text or \"\").splitlines() if _LABEL_LINE.match(line)]",
        replacement="        lines += [line for line in (text or \"\").splitlines() if line.strip()]",
        target="tests/test_model_vocabulary.py",
        keyword="column_in_a_table_header_never_produces_pressure_vessel",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M530", phase=61,
        description="match a synonym as a substring, so 'TANKER' counts as "
                    "the Storage Tank synonym 'tank'",
        path=APP / "model_evidence.py",
        anchor='        if re.search(rf"\\b{re.escape(synonym)}\\b", _collapse(quote), re.IGNORECASE):',
        replacement='        if synonym.lower() in _collapse(quote).lower():',
        target="tests/test_model_vocabulary.py",
        keyword="a_synonym_inside_a_longer_word_does_not_count",
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
