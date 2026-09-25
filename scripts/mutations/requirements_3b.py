"""Mutations of `backend/app/requirements_3b.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_3B ----------------------------------------------------
    #: Phase 3B: tables, limits, units, exceptions, conflicts, the queue.
    #: `phase=4` only because `--phase 3` already selects 3A; the ids are the
    #: stable handle and the tags say what each one is about.
    Mutation(
        id="M39", phase=4,
        description="stop reading the unit out of a table header",
        path=APP / "requirements_3b.py",
        anchor="    match = _HEADER_UNIT.search(header or \"\")\n    if not match:",
        replacement="    match = None\n    if not match:",
        target="tests/test_standards_3b.py",
        keyword="numeric_value_is_extracted_from_a_real_table",
        tags=("table", "unit"),
    ),
    Mutation(
        id="M40", phase=4,
        description="coerce an unknown unit to 0 instead of leaving it None",
        path=APP / "requirements_3b.py",
        anchor="    return claims.normalise(raw_value, raw_unit or \"\")",
        replacement="    m = claims.normalise(raw_value, raw_unit or \"\")\n"
                    "    from dataclasses import replace as _r\n"
                    "    return _r(m, normalized_value=m.normalized_value or 0.0)",
        target="tests/test_standards_3b.py",
        keyword="unknown_unit_yields_none",
        tags=("honesty", "unit"),
    ),
    Mutation(
        id="M42", phase=4,
        description="drop the exception clause, turning a compliant PSV into a finding",
        path=APP / "requirements_3b.py",
        anchor="    match = _EXCEPTION.search(sentence)\n    if not match:\n        return []",
        replacement="    match = None\n    if not match:\n        return []",
        target="tests/test_standards_3b.py",
        keyword="psv_exception_is_preserved or exception_is_stored",
        tags=("honesty", "exception"),
    ),
    Mutation(
        id="M43", phase=4,
        description="silently resolve a conflict by keeping only the first limit",
        path=APP / "requirements_3b.py",
        anchor="        if len(distinct) < 2:\n            continue",
        replacement="        if True:\n            continue",
        target="tests/test_standards_3b.py",
        keyword="limiting_the_same_field_differently_is_a_conflict",
        tags=("honesty", "conflict"),
    ),
    Mutation(
        id="M48", phase=4,
        description="record a cross-reference cell ('see 5.2') as a numeric value",
        path=APP / "requirements_3b.py",
        anchor="    if not cell or not _CELL_VALUE.match(cell):\n        return None",
        replacement="    if not cell:\n        return None",
        target="tests/test_standards_3b.py",
        keyword="not_a_number_is_not_recorded",
        tags=("table", "honesty"),
    ),
    # ---- from EXTRACTION --------------------------------------------------
    #: Extraction quality: the unit gate, the page footer, the dedupe, the
    #: descriptive subject, and the orphaned job nobody would ever see.
    Mutation(
        id="M93", phase=8,
        description="keep any word after a number as a unit, so 'locations' "
                    "becomes a unit again",
        path=APP / "requirements_3b.py",
        anchor="    return cleaned if claims.is_unit(cleaned) else None",
        replacement="    return cleaned",
        target="tests/test_extraction_quality.py",
        keyword="not_a_unit_is_not_stored_as_one",
        tags=("honesty",),
    ),
    Mutation(
        id="M94", phase=8,
        description="stop stripping trailing punctuation, restoring the 'g/L.' "
                    "defect that broke the product's worked example",
        path=APP / "requirements_3b.py",
        anchor='    cleaned = text.rstrip(".,;:")',
        replacement="    cleaned = text",
        target="tests/test_extraction_quality.py",
        keyword="full_stop_is_not_part_of_the_unit",
        tags=("critical",),
    ),
    Mutation(
        id="M95", phase=8,
        description="STRIP THE BRACKET OFF dB(A), reopening the phase 5B "
                    "defect from the standards side",
        path=APP / "requirements_3b.py",
        anchor='and cleaned.count("(") < cleaned.count(")"):',
        replacement=":",
        target="tests/test_extraction_quality.py",
        keyword="db_a_survives_the_unit_gate",
        tags=("honesty", "critical"),
    ),
    # ---- from TABLE_AND_UNITS ---------------------------------------------
    #: Table rows, the dimension-aware unit guard, and the identifier rule.
    Mutation(
        id="M119", phase=8,
        description="STOP CLASSIFYING TABLE ROWS, restoring a limit of "
                    "<= 6,900 kPa that the standard never states",
        path=APP / "requirements_3b.py",
        anchor="    if is_table_row(sentence):\n        return TABLE_ROW",
        replacement="    if False:\n        return TABLE_ROW",
        target="tests/test_table_row_requirements.py",
        keyword="classify_prefers_table_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M120", phase=8,
        description="classify a real limit as a table row, so a requirement "
                    "that states its own number stops being checked",
        path=APP / "requirements_3b.py",
        anchor="    if _COMPARATOR_PRESENT.search(text):\n        return False",
        replacement="    if False:\n        return False",
        target="tests/test_table_row_requirements.py",
        keyword="states_its_own_limit_stays_a_numeric_limit or cites_a_table_is_still_a_limit",
        tags=("critical",),
    ),
    # ---- from GATE_FALLOUT ------------------------------------------------
    #: The three defects the model tier's failed gate exposed, plus the default
    #: it was turned off by.
    Mutation(
        id="M161", phase=12,
        description="TREAT AN APPLICABILITY TRIGGER AS A LIMIT - the "
                    "SAES-D-001 9.2.5 defect, reinstated",
        path=APP / "requirements_3b.py",
        anchor="    if is_applicability_trigger(sentence):\n        return APPLICABILITY_TRIGGER",
        replacement="    if False:\n        return APPLICABILITY_TRIGGER",
        target="tests/test_trigger_and_relative.py",
        keyword="defers_to_another_document_is_a_trigger",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M162", phase=12,
        description="let the trigger check swallow a sentence that states its "
                    "OWN quantity, deleting real requirements",
        path=APP / "requirements_3b.py",
        anchor="    without_documents = _DOCUMENT_REF.sub(\" \", remainder)\n"
               "    if _BARE_NUMBER.search(without_documents):\n"
               "        return None\n"
               "    return remainder",
        replacement="    return remainder",
        target="tests/test_trigger_and_relative.py",
        keyword="states_its_own_quantity_is_not_a_trigger",
        tags=("critical",),
    ),
    Mutation(
        id="M163", phase=12,
        description="let the trigger check swallow a table deferral, undoing "
                    "the table_row work",
        path=APP / "requirements_3b.py",
        anchor="    if _TABLE_REFERENCE.search(remainder):\n        # A table is not another document.",
        replacement="    if False:\n        # A table is not another document.",
        target="tests/test_trigger_and_relative.py",
        keyword="predicate_itself_refuses_a_deferral_to_a_table",
    ),
    Mutation(
        id="M164", phase=12,
        description="call a sentence a trigger although it names no document",
        path=APP / "requirements_3b.py",
        anchor="    if not _DOCUMENT_REF.search(remainder):\n        return None",
        replacement="    if False:\n        return None",
        target="tests/test_trigger_and_relative.py",
        keyword="states_its_own_quantity_is_not_a_trigger",
    ),
    Mutation(
        id="M166", phase=12,
        description="TREAT A MARGIN AS AN ABSOLUTE LIMIT - the SAES-D-001 "
                    "14.3 defect, reinstated",
        path=APP / "requirements_3b.py",
        anchor="    if is_relative_limit(sentence):\n        return RELATIVE_LIMIT",
        replacement="    if False:\n        return RELATIVE_LIMIT",
        target="tests/test_trigger_and_relative.py",
        keyword="margin_from_a_reference",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M167", phase=12,
        description="search the whole sentence for the relative phrase instead "
                    "of anchoring it at the parsed limit, deleting a real one",
        path=APP / "requirements_3b.py",
        anchor="    return bool(_RELATIVE_TAIL.match(text[match.start(\"value\"):]))",
        replacement="    return bool(_RELATIVE_TAIL.search(text))",
        target="tests/test_trigger_and_relative.py",
        keyword="comparative_phrase_before_the_limit",
        tags=("critical",),
    ),
    # ---- from B175_CASCADE_AND_CONFIDENCE ---------------------------------
    #: #175: cascaded extractor (table column-scoping, reused from the parked
    #: B58 fix, renumbered M356-M358 -> M365-M367 to avoid colliding with
    #: mutation ids already added on this branch since the two diverged), OCR
    #: fallback routing, and confidence-based NEEDS_ENGINEER_REVIEW routing.
    Mutation(
        id="M371", phase=47,
        description="stop requiring a submission verb before naming an "
                    "evidence noun, so required_evidence_type gets guessed "
                    "off any mention of a document kind",
        path=APP / "requirements_3b.py",
        anchor="    if not sentence or not _EVIDENCE_VERB.search(sentence):\n"
               "        return None",
        replacement="    if not sentence:\n        return None",
        target="tests/test_standards_3b.py",
        keyword="an_evidence_noun_with_no_submission_verb_is_not_enough_alone",
        tags=("honesty",),
    ),
    # ---- from B5_REQUIREMENT_TYPING ---------------------------------------
    #: B5/#193: comparative-adjective and single-word-preposition limit forms
    #: ("closer than", "below 441degC") added to `_LIMIT`/`_OPERATOR`.
    Mutation(
        id="M501", phase=60,
        description="drop the comparative-adjective alternative from _LIMIT, so "
                    "'the gap shall be no closer than 5 mm' states no limit at all "
                    "(B5 comparator fix)",
        path=APP / "requirements_3b.py",
        anchor='    r"|" + _COMPARATIVE_THAN +\n',
        replacement='    r"|(?!)" +\n',
        target="tests/test_standards_3b.py",
        keyword="comparative_adjective_states_a_real_limit",
        tags=("honesty", "requirement-typing"),
    ),
    Mutation(
        id="M502", phase=60,
        description="drop the single-word preposition alternative ('below', "
                    "'under', 'beneath', 'above', 'over') from _LIMIT, so 'the "
                    "design temperature shall be below 441degC' states no limit "
                    "(B5 comparator fix)",
        path=APP / "requirements_3b.py",
        anchor='    r"|\\b(?:below|under|beneath|above|over)\\b)\\s*"',
        replacement='    r")\\s*"',
        target="tests/test_standards_3b.py",
        keyword="comparative_adjective_states_a_real_limit",
        tags=("honesty", "requirement-typing"),
    ),
    Mutation(
        id="M503", phase=60,
        description="swap which side of 'than' maps to < vs >, so 'closer than "
                    "5 mm' is read as a minimum instead of a maximum (B5 "
                    "comparator fix)",
        path=APP / "requirements_3b.py",
        anchor='    **{f"{word} than": "<" for word in _SMALLER_THAN},\n'
               '    **{f"{word} than": ">" for word in _LARGER_THAN},\n',
        replacement='    **{f"{word} than": ">" for word in _SMALLER_THAN},\n'
                    '    **{f"{word} than": "<" for word in _LARGER_THAN},\n',
        target="tests/test_standards_3b.py",
        keyword="comparative_adjective_states_a_real_limit",
        tags=("honesty", "requirement-typing"),
    ),
    Mutation(
        id="M504", phase=60,
        description="swap the single-word preposition operators, so 'below "
                    "441degC' is read as a minimum instead of a maximum (B5 "
                    "comparator fix)",
        path=APP / "requirements_3b.py",
        anchor='    "below": "<", "under": "<", "beneath": "<", "above": ">", "over": ">",',
        replacement='    "below": ">", "under": ">", "beneath": ">", "above": "<", "over": "<",',
        target="tests/test_standards_3b.py",
        keyword="comparative_adjective_states_a_real_limit",
        tags=("honesty", "requirement-typing"),
    ),
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M516", phase=61,
        description="search the whole _DOCUMENT_REF pattern (designation OR "
                    "internal cross-reference) instead of the designation "
                    "alone, so 'refer to clause 5.2' returns 'clause 5.2' "
                    "as if it were a citable standard",
        path=APP / "requirements_3b.py",
        anchor="    match = _DOCUMENT_DESIGNATION.search(remainder)",
        replacement="    match = _DOCUMENT_REF.search(remainder)",
        target="tests/test_trigger_and_relative.py",
        keyword="cited_document_is_none_when_the_deferral_names_no_real_document",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M517", phase=61,
        description="skip the three-gate check entirely, so cited_document "
                    "names a document out of ANY sentence, not just a real "
                    "applicability trigger",
        path=APP / "requirements_3b.py",
        anchor="    remainder = _applicability_remainder(sentence)\n"
               "    if remainder is None:\n"
               "        return None\n"
               "    match = _DOCUMENT_DESIGNATION.search(remainder)",
        replacement="    remainder = sentence or \"\"\n"
                    "    match = _DOCUMENT_DESIGNATION.search(remainder)",
        target="tests/test_trigger_and_relative.py",
        keyword="cited_document_ignores_a_document_named_outside_a_real_trigger",
        tags=("honesty", "inventory", "critical"),
    ),
)
