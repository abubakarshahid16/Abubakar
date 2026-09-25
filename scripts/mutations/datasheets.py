"""Mutations of `backend/app/datasheets.py`."""

from __future__ import annotations

from ._base import (
    APP,
    TAG_TAIL,
    _B175_DATASHEET_TEST,
    _B19_TEST,
    _B3_TEST,
    _B40_TEST,
    _B44_TEST,
    _B4_TEST,
    Mutation,
)


_D = 'tests/test_b4_defects.py'

MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_4 -----------------------------------------------------
    #: Phase 4: datasheet intelligence. `phase=5` because --phase 4 already
    #: selects 3B; the ids are the stable handle.
    Mutation(
        id="M49", phase=5,
        description="stop reading the unit off a datasheet value",
        path=APP / "datasheets.py",
        anchor='    unit = (match.group("unit") or "").strip() or None',
        replacement="    unit = None",
        target="tests/test_datasheets.py",
        keyword="value_with_its_unit_is_extracted",
        tags=("datasheet", "unit"),
    ),
    Mutation(
        id="M50", phase=5,
        description="treat a By Contractor field as a filled value, not a blank",
        path=APP / "datasheets.py",
        anchor="    marker = _BLANK_MARKERS.search(text)\n    if marker:",
        replacement="    marker = _BLANK_MARKERS.search(text)\n    if False:",
        target="tests/test_datasheets.py",
        keyword="by_contractor_field_is_recorded_as_blank",
        tags=("honesty", "missing-information"),
    ),
    Mutation(
        id="M51", phase=5,
        description="report a page that yielded nothing as parsed anyway",
        path=APP / "datasheets.py",
        # Re-anchored by B19: the write loop moved inside one transaction, +4.
        # Re-anchored by B3: the reason is kept for the page ledger too, so the
        # mutant now reports the empty page as parsed in BOTH homes.
        anchor="            if page_written == 0:\n"
               "                reason = _unparsed_reason(pairs, dropped)\n",
        replacement="            if False:\n"
                    "                reason = _unparsed_reason(pairs, dropped)\n",
        target="tests/test_datasheets.py",
        keyword="unparsed_page_lowers_completeness",
        tags=("honesty", "completeness"),
    ),
    Mutation(
        id="M52", phase=5,
        description="stop detecting standards referenced by the datasheet",
        path=APP / "datasheets.py",
        anchor="    for match in _REFERENCED_STANDARD.finditer(text or \"\"):",
        replacement="    for match in _REFERENCED_STANDARD.finditer(\"\"):",
        target="tests/test_datasheets.py",
        keyword="referenced_standard_named_in_the_datasheet",
        tags=("datasheet",),
    ),
    Mutation(
        id="M55", phase=5,
        description="drop the scope filter from the datasheet facts read",
        path=APP / "datasheets.py",
        anchor='    where, args = _scope_clause(allowed_document_ids, "f.submittal_document_id")',
        replacement='    where, args = " WHERE 1 = 1", []',
        target="tests/test_datasheets.py",
        keyword="unauthorised_user_sees_no_facts or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M56", phase=5,
        description="promote a value into a field label, inventing blank fields",
        path=APP / "datasheets.py",
        # Re-anchored 2026-09-24: #179 moved this gate into a helper that
        # returns None; the old `continue` anchor matched 0 times.
        anchor="    if not is_field_label(label):\n        return None",
        replacement="    if False:\n        return None",
        target="tests/test_datasheets.py",
        keyword="value_is_never_promoted_into_a_field_label",
        tags=("honesty", "datasheet"),
    ),
    # ---- from DATASHEET ---------------------------------------------------
    #: The datasheet side: which strings are citations, where a unit lives, and
    #: what is not a fact at all.
    Mutation(
        id="M102", phase=8,
        description="MATCH A BARE ASME FAMILY LETTER again, reporting "
                    "'ASME B' as a missing reference nobody can look up",
        path=APP / "datasheets.py",
        anchor=r'    r"|ASME\s*B\d{1,2}\.\d{1,3}(?:\.\d{1,3})?"',
        replacement=r'    r"|ASME\s*[IVXB]+(?:\.\d+)?"',
        target="tests/test_reference_identifiers.py",
        keyword="bare_asme_family_letter",
        tags=("honesty",),
    ),
    Mutation(
        id="M103", phase=8,
        description="drop the SAMSS alternative, making ten citations invisible",
        path=APP / "datasheets.py",
        anchor=r'    r"|\d{2}-SAMSS-\d{3}"',
        replacement=r'    r"|(?!x)x-SAMSS-\d{3}"',
        target="tests/test_reference_identifiers.py",
        keyword="citation_shape_is_read_whole",
    ),
    Mutation(
        id="M105", phase=8,
        description="stop absorbing the unit column, orphaning it as a field "
                    "named after a unit",
        path=APP / "datasheets.py",
        anchor="            if index < len(parts) and _is_numeric_cell(value):",
        replacement="            if False:",
        target="tests/test_datasheet_unit_layouts.py",
        keyword="unit_in_its_own_column",
        tags=("critical",),
    ),
    Mutation(
        id="M106", phase=8,
        description="stop taking the unit out of the label, losing it with no "
                    "trace that it existed",
        path=APP / "datasheets.py",
        # Re-anchored 2026-09-24: one indent level shallower after #179.
        anchor="    label, carried = _unit_in_label(label)",
        replacement="    label, carried = label, None",
        target="tests/test_datasheet_unit_layouts.py",
        keyword="unit_inside_the_label",
        tags=("critical",),
    ),
    Mutation(
        id="M108", phase=8,
        description="lose the gauge reference, comparing a gauge pressure "
                    "against an absolute limit",
        path=APP / "datasheets.py",
        # Re-anchored (B4 quality): the printed unit is split since B4.
        anchor="    base_unit, unit_reference = claims.split_reference(raw_unit)",
        replacement="    base_unit, unit_reference = raw_unit, None",
        target="tests/test_fact_gates.py",
        keyword="reference_is_stored_on_the_fact_row",
        tags=("critical",),
    ),
    Mutation(
        id="M109", phase=8,
        description="call a label furniture after ONE page, deleting real "
                    "fields to remove a header",
        path=APP / "datasheets.py",
        anchor="FURNITURE_PAGE_THRESHOLD = 3",
        replacement="FURNITURE_PAGE_THRESHOLD = 1",
        target="tests/test_fact_gates.py",
        keyword="two_pages_is_kept or repeated_many_times_on_one_page",
    ),
    Mutation(
        id="M110", phase=8,
        description="open the categorical list, letting a signature block back "
                    "in as a fact",
        path=APP / "datasheets.py",
        anchor='    return " ".join((value or "").strip().lower().split()) in _CATEGORICAL_VALUES',
        replacement='    return bool((value or "").strip())',
        target="tests/test_fact_gates.py",
        keyword="free_text_is_not_a_categorical_answer",
        tags=("honesty",),
    ),
    Mutation(
        id="M111", phase=8,
        description="store the chunk's heading as the section even when it is "
                    "another column's value",
        path=APP / "datasheets.py",
        anchor="    return text if is_field_label(text) else None",
        replacement="    return text",
        target="tests/test_fact_gates.py",
        keyword="section_that_is_not_a_label_is_null",
        tags=("honesty",),
    ),
    # ---- from MATCHER -----------------------------------------------------
    #: The containment matcher and the last of the datasheet recall fixes.
    Mutation(
        id="M117", phase=8,
        description="treat a small integer followed by a unit as a line "
                    "number again, discarding most numeric rows on a page",
        path=APP / "datasheets.py",
        # Re-anchored 2026-09-24: #179 split the condition over two lines and
        # added `not value_on_a_slot`; the mutation still removes only the
        # unit-follows exemption.
        anchor=(r'        if (not value_on_a_slot and re.fullmatch(r"\d{1,3}", value)'
                "\n"
                r'                and not _unit_follows(parts, index + 2)):'),
        replacement=r'        if (not value_on_a_slot and re.fullmatch(r"\d{1,3}", value)):',
        target="tests/test_fact_gates.py",
        keyword="line_number or followed_by_a_unit",
        tags=("critical",),
    ),
    Mutation(
        id="M118", phase=8,
        description="record a date as a measurement, so a signature block "
                    "becomes a numeric fact",
        path=APP / "datasheets.py",
        # ANCHORED ON THE PREDICATE, not on the call site in extract_facts.
        # The first version mutated the gate, which only runs inside a full PDF
        # extraction that these fixtures do not drive - so it reported NOT
        # DETECTED against tests that cover the rule perfectly well at the
        # level they can reach. The wiring itself is evidenced by the measured
        # end-to-end run, where the signature fact disappeared.
        anchor="    return bool(_DATE_VALUE.match(value or \"\"))",
        replacement="    return False",
        target="tests/test_fact_gates.py",
        keyword="a_date_is_not_a_quantity",
        tags=("honesty",),
    ),
    # ---- from TABLE_AND_UNITS ---------------------------------------------
    #: Table rows, the dimension-aware unit guard, and the identifier rule.
    Mutation(
        id="M126", phase=8,
        description="accept an equipment tag as a unit again",
        path=APP / "datasheets.py",
        anchor="    return digits >= 2 and letters >= 3",
        replacement="    return False",
        target="tests/test_datasheet_unit_layouts.py",
        keyword="equipment_tag_is_still_refused or no_longer_reads_a_tag_number",
        tags=("honesty",),
    ),
    # ---- from GATE_FALLOUT ------------------------------------------------
    #: The three defects the model tier's failed gate exposed, plus the default
    #: it was turned off by.
    Mutation(
        id="M170", phase=12,
        description="LET A BRACKET-ONLY LINE BECOME A FIELD OF ITS OWN - the "
                    "`material 2` defect, reinstated",
        path=APP / "datasheets.py",
        anchor="        if out and out[-1] and _PARENTHETICAL_ONLY.fullmatch(part):",
        replacement="        if False:",
        target="tests/test_field_name_truncation.py",
        keyword="bracket_only",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M171", phase=12,
        description="let a cross-reference cell take the label position, so "
                    "the real label becomes its value",
        path=APP / "datasheets.py",
        anchor="        if _CROSS_REFERENCE.fullmatch(part):\n            index += 1\n            continue",
        replacement="        if False:\n            index += 1\n            continue",
        target="tests/test_field_name_truncation.py",
        keyword="cross_reference or dotted_clause or bracket_only_line",
        tags=("critical",),
    ),
    # M172 WAS WITHDRAWN, NOT SOLVED. It relaxed the clause-reference rule
    # from two dots to one, so `1.6` would be skipped as a pointer - and no
    # test could see it, because `is_field_label` already refuses a bare
    # number at the label position. Skipping the cell and pairing it into a
    # rejected pair emit the same nothing. The two-dot bound is kept because
    # the rule should be TRUE and not merely harmless, but it changes no
    # output today, and an assertion that claimed otherwise would be the
    # vacuous kind. Recorded in docs/status-honesty-audit.md.
    Mutation(
        id="M173", phase=12,
        description="widen the cross-reference rule until it swallows fields "
                    "whose names merely contain the word",
        path=APP / "datasheets.py",
        anchor=r'    r"\s*[-:]?\s*[A-Za-z0-9]{1,4}(?:\s+of\s+\d{1,3})?"',
        replacement=r'    r".*"',
        target="tests/test_field_name_truncation.py",
        keyword="merely_contains_a_reference_word",
    ),
    # ---- from REPEATED_FORM -----------------------------------------------
    #: A form repeated on every page is not a title block, and the diagnostic
    #: that used to hide it.
    Mutation(
        id="M174", phase=13,
        description="COUNT PAGES ALONE AGAIN, so a form repeated on every "
                    "page is stripped as a header - DS-0000-DAS-I-01 back to "
                    "zero facts from 162 rows",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = False",
        target="tests/test_repeated_form.py",
        keyword="repeated_form_with_per_page_values",
        tags=("critical",),
    ),
    Mutation(
        id="M175", phase=13,
        description="drop condition 1, so a title block with constant text is "
                    "promoted to a field",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = answered * 2 > len(pages)",
        target="tests/test_repeated_form.py",
        keyword="title_block or both_conditions or one_answer_throughout",
        tags=("critical",),
    ),
    Mutation(
        id="M176", phase=13,
        description="DROP CONDITION 2, so a mostly-empty title block that "
                    "caught two stray fragments files them as facts - the "
                    "`onshore facility a` row returning",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = distinct >= 2",
        target="tests/test_repeated_form.py",
        keyword="mostly_empty_label or both_conditions",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M177", phase=13,
        description="answered on exactly half the pages counts as a field, "
                    "an off-by-one on the boundary",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = distinct >= 2 and answered * 2 >= len(pages)",
        target="tests/test_repeated_form.py",
        keyword="exactly_half",
    ),
    Mutation(
        id="M178", phase=13,
        description="count an EMPTY cell as an answer, which makes every "
                    "header look answered on every page",
        path=APP / "datasheets.py",
        # Re-anchored 2026-09-24: #179 added `and states_a_value(value)`.
        # Replacing the whole condition keeps the original meaning - any cell,
        # empty or not, counts as an answer.
        anchor="            if answer and states_a_value(value):\n                answered_pages[name].add(page)",
        replacement="            if True:\n                answered_pages[name].add(page)",
        target="tests/test_repeated_form.py",
        keyword="mostly_empty_label or title_block",
        tags=("critical",),
    ),
    Mutation(
        id="M179", phase=13,
        description="SAY 'no label-value pairs recovered' WHATEVER HAPPENED, "
                    "so a page whose pairs were all filtered reads like a "
                    "page that could not be parsed",
        path=APP / "datasheets.py",
        anchor="    if not pairs:\n        return \"no label-value pairs recovered from this page\"",
        replacement="    if True:\n        return \"no label-value pairs recovered from this page\"",
        target="tests/test_repeated_form.py",
        keyword="names_the_filters or never_claims",
        tags=("honesty",),
    ),
    Mutation(
        id="M180", phase=13,
        description="report the filter counts in any order, so the biggest "
                    "cause no longer reads first",
        path=APP / "datasheets.py",
        anchor="                               key=lambda kv: (-kv[1], kv[0]))",
        replacement="                               key=lambda kv: (kv[1], kv[0]))",
        target="tests/test_repeated_form.py",
        keyword="ordered_by_size",
    ),
    # ---- from RANGES_AND_COMPOUNDS ----------------------------------------
    #: Two numbers in one cell, and two fields in one label.
    Mutation(
        id="M181", phase=14,
        description="stop splitting compound labels, so Design/Operating "
                    "pressure stays one unusable field",
        path=APP / "datasheets.py",
        anchor="    parts = compound_label_parts(label)\n    if parts is None:",
        replacement="    parts = None\n    if parts is None:",
        target="tests/test_ranges_and_compounds.py",
        keyword="compound_label_with_a_matching_value",
        tags=("critical",),
    ),
    Mutation(
        id="M182", phase=14,
        description="SPLIT A COMPOUND LABEL WHOSE VALUE DID NOT SPLIT, "
                    "attaching one number to a field that is half wrong",
        path=APP / "datasheets.py",
        anchor="    if len(values) != len(names) or not all(values):",
        replacement="    if False:",
        target="tests/test_ranges_and_compounds.py",
        keyword="mismatched_separator_count",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M183", phase=14,
        description="parse the value of a compound label that never split, "
                    "recording a number against two fields at once",
        path=APP / "datasheets.py",
        # Re-anchored by B4 fix 5: the condition gained "not one_quantity and".
        anchor="    if not blank and not one_quantity and compound_label_parts(field_label) is not None:",
        replacement="    if False:",
        target="tests/test_ranges_and_compounds.py",
        keyword="did_not_split_stores_no_parsed_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M184", phase=14,
        description="DISTRIBUTE A UNIT ONTO A HALF THAT HAS ITS OWN, "
                    "inventing psig onto a number already in psig",
        path=APP / "datasheets.py",
        anchor="    if units[-1] and not any(units[:-1]):",
        replacement="    if units[-1]:",
        target="tests/test_ranges_and_compounds.py",
        keyword="never_added_to_a_half",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M185", phase=14,
        description="split on a separator inside brackets, so (Cp/Cv) tears "
                    "a real value in half",
        path=APP / "datasheets.py",
        anchor="    masked = _outside_brackets(text)",
        replacement="    masked = text",
        target="tests/test_ranges_and_compounds.py",
        keyword="not_compound_is_left_alone",
    ),
    Mutation(
        id="M186", phase=14,
        description="let `&` split a tight word, so P&ID Reference becomes a "
                    "field called P",
        path=APP / "datasheets.py",
        anchor='_COMPOUND_SEPARATORS = (("/", r"\\s*/\\s*"), ("&", r"\\s+&\\s+"))',
        replacement='_COMPOUND_SEPARATORS = (("/", r"\\s*/\\s*"), ("&", r"\\s*&\\s*"))',
        target="tests/test_ranges_and_compounds.py",
        keyword="not_compound_is_left_alone",
    ),
    Mutation(
        id="M187", phase=14,
        description="READ A UNITLESS PAIR AS A RANGE, so the drum sheet's "
                    "table of contents becomes two facts",
        path=APP / "datasheets.py",
        anchor="    if range_unit is None:\n        return None",
        replacement="    if False:\n        return None",
        target="tests/test_ranges_and_compounds.py",
        keyword="unitless_range",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M188", phase=14,
        description="drop the low-above-high guard, so 10-05 reads as a "
                    "range from ten to five",
        path=APP / "datasheets.py",
        anchor="    if left is None or right is None or left > right:",
        replacement="    if left is None or right is None:",
        target="tests/test_ranges_and_compounds.py",
        keyword="descending_pair_is_refused",
    ),
    Mutation(
        id="M189", phase=14,
        description="accept a range with prose after it, so a P&ID reference "
                    "becomes a quantity",
        path=APP / "datasheets.py",
        anchor='    if rest and not rest.startswith("("):\n        return None',
        replacement="    if False:\n        return None",
        target="tests/test_ranges_and_compounds.py",
        keyword="prose_after_a_range_refuses_it",
        tags=("critical",),
    ),
    Mutation(
        id="M190", phase=14,
        description="REWRITE THE DEGREE GLYPH ANYWHERE, turning any word "
                    "ending in oc into a temperature",
        path=APP / "datasheets.py",
        # Re-anchored 2026-09-24: #179 added the º glyph to the class.
        anchor=r'_DEGREE_GLYPH = re.compile(r"(?<=\d)[Ooº]([CF])\b")',
        replacement=r'_DEGREE_GLYPH = re.compile(r"[Ooº]([CF])\b")',
        target="tests/test_ranges_and_compounds.py",
        keyword="word_ending_in_oc",
        tags=("critical",),
    ),
    Mutation(
        id="M195", phase=14,
        description="drop the range from the value gate, so every range is "
                    "discarded as free text before it reaches create_fact",
        path=APP / "datasheets.py",
        # Re-anchored 2026-09-24: #179 moved the value gate into its one home,
        # `states_a_value`, which `extract_facts` gates on.
        anchor="    if parsed is None and parse_range(value) is not None:\n        parsed = \"range\"",
        replacement="    if False:\n        parsed = \"range\"",
        target="tests/test_ranges_and_compounds.py",
        keyword="survives_the_value_gate",
        tags=("critical",),
    ),
    # ---- from EQUIPMENT_TAG -----------------------------------------------
    #: Which equipment a fact describes.
    Mutation(
        id="M199", phase=16,
        description="read the tag only from the VALUE, so the PSV sheet - "
                    "which puts the key and the tag in one cell - yields no "
                    "tag on any page",
        path=APP / "datasheets.py",
        anchor=TAG_TAIL,
        replacement='    return " ".join((value or "").split()) or None',
        target="tests/test_equipment_tag.py",
        keyword="tag_row_yields_its_tag_verbatim",
        tags=("critical",),
    ),
    Mutation(
        id="M200", phase=16,
        description="TIDY THE TAG, producing an identifier that matches "
                    "nothing anybody searches for",
        path=APP / "datasheets.py",
        anchor='    return tail or " ".join((value or "").split()) or None',
        replacement='    return (tail.split("(")[0].strip() or '
                    '" ".join((value or "").split()) or None)',
        target="tests/test_equipment_tag.py",
        keyword="tag_is_not_tidied",
        tags=("honesty",),
    ),
    Mutation(
        id="M201", phase=16,
        description="let `Tag description` name the equipment, so a fact is "
                    "stamped with what the equipment IS rather than which "
                    "one it is",
        path=APP / "datasheets.py",
        anchor=r'    r"^\s*(?:tag\s*(?:no\.?|number)|item\s*no\.?)\s*[.:\-]*\s*(?P<tail>.*)$",',
        replacement=r'    r"^\s*(?:tag|item)\s*\w*\s*[.:\-]*\s*(?P<tail>.*)$",',
        target="tests/test_equipment_tag.py",
        keyword="what_is_not_a_tag_row",
    ),
    Mutation(
        id="M202", phase=16,
        description="STOP STAMPING A ONE-TAG DOCUMENT'S OTHER PAGES, so the "
                    "drum's facts lose the vessel they describe",
        path=APP / "datasheets.py",
        anchor="    if len(mentioned) == 1:",
        replacement="    if False:",
        target="tests/test_equipment_tag.py",
        keyword="one_tag_in_a_document_stamps_every_page",
        tags=("critical",),
    ),
    Mutation(
        id="M203", phase=16,
        description="INHERIT A TAG ACROSS PAGES THAT NAME DIFFERENT "
                    "EQUIPMENT, filing one valve's numbers against another",
        path=APP / "datasheets.py",
        anchor="    return {page: tags.get(page) for page in pairs_by_page}",
        replacement="    return {page: (tags.get(page) or next(iter(mentioned), None))\n"
                    "            for page in pairs_by_page}",
        target="tests/test_equipment_tag.py",
        keyword="multi_tag_document_keeps_each_page or several_tags_stay",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M207", phase=16,
        description="let the tag row become a fact, so a matcher can pair a "
                    "requirement with an equipment identifier",
        path=APP / "datasheets.py",
        anchor="            if tag_from_pair(label, value) is not None:",
        replacement="            if False:",
        target="tests/test_equipment_tag.py",
        keyword="tag_row_never_becomes_a_fact",
    ),
    # ---- from B19_FACT_EXTRACTION -----------------------------------------
    #: B19: a review never read the datasheet (extract_facts had no caller).
    Mutation(
        id="M318", phase=36,
        description="commit each fact on its own again, so a failure mid-sheet "
                    "leaves a partial set the guard mistakes for a finished one",
        path=APP / "datasheets.py",
        anchor="                        commit=False,\n",
        replacement="",
        target=_B19_TEST,
        keyword="failed_extraction or failed_re_extraction",
        tags=("critical",),
    ),
    # ---- from B40_FACT_GUARD ----------------------------------------------
    #: B40 -> #179: `extract_facts(replace=True)` used to DELETE unconfirmed facts
    #: that findings cite by `fact_id` (B40 guarded it: count, record, refuse).
    #: Since #179 it SUPERSEDES them instead - the rows stay, marked
    #: `superseded_at`, and every reader of current facts leaves them out.
    #: M334-M336 keep their ids, re-anchored on the supersession; M440-M444 cover
    #: the readers and the record. Phase 56.
    Mutation(
        id="M334", phase=56,
        description="PUT B40's DELETE BACK: a re-read deletes the cited rows "
                    "instead of marking them, so the finding's fact_id points "
                    "at nothing again (#179 supersession)",
        path=APP / "datasheets.py",
        anchor='                "UPDATE submittal_facts SET superseded_at = ? WHERE " + superseded_where,\n'
               '                (datetime.now(timezone.utc).isoformat(timespec="seconds"),\n'
               '                 document_id)).rowcount',
        replacement='                "DELETE FROM submittal_facts WHERE " + superseded_where,\n'
                    '                (document_id,)).rowcount',
        target=_B40_TEST, keyword="keeps_the_cited_fact_resolvable",
        tags=("critical",),
    ),
    Mutation(
        id="M335", phase=56,
        description="supersede CONFIRMED facts too, so a human's confirmed "
                    "reading is replaced by a re-parse (#179)",
        path=APP / "datasheets.py",
        anchor='    superseded_where = ("submittal_document_id = ? AND confirmed_by IS NULL"\n'
               '                        " AND superseded_at IS NULL")',
        replacement='    superseded_where = ("submittal_document_id = ?"\n'
                    '                        " AND superseded_at IS NULL")',
        target=_B40_TEST, keyword="confirmed_fact_is_never_superseded",
        tags=("critical",),
    ),
    Mutation(
        id="M440", phase=56,
        description="list_facts returns superseded rows again, so a review "
                    "and the CRS read two readings of one cell (#179)",
        path=APP / "datasheets.py",
        anchor='           " AND f.superseded_at IS NULL")',
        replacement='           "")',
        target=_B40_TEST, keyword="every_current_fact_reader",
        tags=("critical",),
    ),
    Mutation(
        id="M443", phase=56,
        description="drop the supersession record, so a re-read that replaced "
                    "cited facts leaves no audit row (#179)",
        path=APP / "datasheets.py",
        anchor="            if superseded:\n"
               "                orphan_guard.record_facts_superseded(",
        replacement="            if False:\n"
                    "                orphan_guard.record_facts_superseded(",
        target=_B40_TEST, keyword="recorded_without_refusing",
        tags=("honesty",),
    ),
    # ---- from B44_UNREADABLE_FILE -----------------------------------------
    #: B44: a file nobody could open was reported as a page that printed nothing,
    #: and counted as read. M51 was NOT re-anchored - the fix sits before the page
    #: loop and after the return, so `if page_written == 0:` never moved; phase 5
    #: re-run 8/8 to prove it rather than assume it.
    Mutation(
        id="M344", phase=42,
        description="PUT B44 BACK: a damaged file reads as no condition at "
                    "all, so it becomes 'no label-value pairs on this page'",
        path=APP / "datasheets.py",
        anchor='    except pymupdf.FileDataError:\n'
               '        return "pdf_damaged", UNREADABLE["pdf_damaged"], False',
        replacement='    except pymupdf.FileDataError:\n'
                    '        return None, "", False',
        target=_B44_TEST, keyword="b44_an_unreadable_file_is_named",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M345", phase=42,
        description="count a page nobody opened as read, putting it back in "
                    "the parsed_fraction denominator",
        path=APP / "datasheets.py",
        anchor="    if condition is not None:\n        pages = sorted(by_page)",
        replacement="    if False:\n        pages = sorted(by_page)",
        target=_B44_TEST, keyword="b44_a_page_that_was_never_opened",
        tags=("honesty", "completeness", "critical"),
    ),
    Mutation(
        id="M346", phase=42,
        description="ignore is_repaired, so a truncated file that silently "
                    "lost content reports as intact",
        path=APP / "datasheets.py",
        anchor='            return None, "", bool(getattr(doc, "is_repaired", False))',
        replacement='            return None, "", False',
        target=_B44_TEST, keyword="b44_a_truncated_file",
        tags=("honesty",),
    ),
    Mutation(
        id="M347", phase=42,
        description="stop checking needs_pass, so an encrypted file is read "
                    "as a document that simply holds no values",
        path=APP / "datasheets.py",
        anchor="            if doc.needs_pass:",
        replacement="            if False:",
        target=_B44_TEST, keyword="b44_an_encrypted_file",
        tags=("honesty",),
    ),
    # ---- from B175_CASCADE_AND_CONFIDENCE ---------------------------------
    #: #175: cascaded extractor (table column-scoping, reused from the parked
    #: B58 fix, renumbered M356-M358 -> M365-M367 to avoid colliding with
    #: mutation ids already added on this branch since the two diverged), OCR
    #: fallback routing, and confidence-based NEEDS_ENGINEER_REVIEW routing.
    Mutation(
        id="M365", phase=47,
        description="PUT B58 BACK: route ruled-table shapes through the "
                    "bare alternating-pair splitter again",
        path=APP / "datasheets.py",
        anchor="            found.extend(pairs_from_table_shape([list(row) for row in shape]))",
        replacement="            for row in shape:\n"
                    "                found.extend(split_label_value(list(row)))",
        target=_B175_DATASHEET_TEST,
        keyword="a_row_labels_its_own_values or wired_into_extract_facts",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M366", phase=47,
        description="stop carrying a spanning header cell forward, so a "
                    "column under a merged header loses its parent name",
        path=APP / "datasheets.py",
        anchor="            if not out_row[i] and out_row[i - 1]:\n"
               "                out_row[i] = out_row[i - 1]",
        replacement="            if False:\n                out_row[i] = out_row[i - 1]",
        target=_B175_DATASHEET_TEST, keyword="spanning_header_cell_is_carried",
        tags=("honesty",),
    ),
    Mutation(
        id="M367", phase=47,
        description="stop detecting a second header line, so its column "
                    "names get stored as if they were data",
        path=APP / "datasheets.py",
        anchor="        if not row1[0]:",
        replacement="        if False:",
        target=_B175_DATASHEET_TEST, keyword="spanning_header_cell_is_carried",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M368", phase=47,
        description="stop routing low-confidence facts to "
                    "NEEDS_ENGINEER_REVIEW, so a guess is accepted as a "
                    "confirmed fact",
        path=APP / "datasheets.py",
        anchor="    if validation_state is None and confidence is not None                     and confidence < LOW_CONFIDENCE_THRESHOLD:\n"
               "        validation_state = NEEDS_ENGINEER_REVIEW",
        replacement="    pass",
        target=_B175_DATASHEET_TEST,
        keyword="a_low_confidence_fact_is_routed_to_needs_engineer_review",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M369", phase=47,
        description="let a page with native evidence ALSO be read from "
                    "OCR, so a low-confidence guess can overwrite a "
                    "confident native fact",
        path=APP / "datasheets.py",
        # Re-anchored by B4 fix 5: grid_by_page[page] now sits between these
        # two lines, and the guard gained "and not grid_by_page[page]".
        anchor="        found.extend(_pairs_from_pdf_page(stored_path, page))\n"
               "        # B4 fix 5: column grids, read by word position (see grid_facts).\n"
               "        grid_by_page[page] = _grid_facts_from_pdf_page(stored_path, page)\n"
               "        if geometry_on:\n"
               "            # B4 (#193 5.5): read, not yet written - see the write loop.\n"
               "            geometry_by_page[page] = _geometry_rows_from_pdf_page(stored_path, page)\n"
               "            vision_by_page[page] = _vision_reading(\n"
               "                stored_path, page, geometry_by_page[page], vision_provider)\n"
               "        if not found and not grid_by_page[page]:",
        replacement="        found.extend(_pairs_from_pdf_page(stored_path, page))\n"
                    "        grid_by_page[page] = _grid_facts_from_pdf_page(stored_path, page)\n"
                    "        if True:",
        target=_B175_DATASHEET_TEST,
        keyword="a_page_with_no_native_pairs_falls_back_to_its_ocr_text or "
                "a_page_with_native_pairs_never_reaches_the_ocr_tier",
        tags=("critical",),
    ),
    # ---- from B179_ROW_NUMBERED_TABLE_ROWS --------------------------------
    Mutation(
        id="M382", phase=51,
        description="stop routing a row whose column 0 is a bare line "
                    "number through split_label_value, so the row number "
                    "goes back to being scoped-to-header's one row label "
                    "(issue #179: bare-digit field names and page-title "
                    "text leaking into field_label)",
        path=APP / "datasheets.py",
        # Anchor moved by #179's second pass (phase 52), which put the
        # column-aware numbered-row reader inside this same branch.
        anchor="        if re.fullmatch(r\"\\d{1,3}\", label):\n"
               "            if 0 in serials:\n",
        replacement="        if False:\n"
                    "            if 0 in serials:\n",
        target="tests/test_datasheets.py",
        keyword="test_179_a_dual_subform_row_keeps_each_side_s_own_label or "
                "test_179_a_row_numbered_form_does_not_quote_the_page_s_own_title",
        # + tests/test_179_layouts.py's genuine dual-column page, run by M406.
        tags=("honesty", "critical"),
    ),
    # ---- from B179_EXTRACTION_QUALITY_2 -----------------------------------
    #: Issue #179, second pass. Phase 52, ids M400-M409.
    Mutation(
        id="M404", phase=52,
        description="stop collapsing the two readers' readings of one printed "
                    "cell, so a wrapped or double-spaced cell is stored twice "
                    "on the same page (issue #179, valve sheet)",
        path=APP / "datasheets.py",
        anchor="        pairs_by_page[page] = collapse_double_reads(split)",
        replacement="        pairs_by_page[page] = split",
        target="tests/test_179_layouts.py",
        keyword="one_printed_cell_read_by_both_readers",
        tags=("honesty",),
    ),
    Mutation(
        id="M405", phase=52,
        description="drop the page from the duplicate key, so the same value "
                    "for a DIFFERENT valve on another page is deleted as a "
                    "duplicate (issue #179: legitimate repeats must stay)",
        path=APP / "datasheets.py",
        anchor="                key = (page, *_same_cell_key(label, value))",
        replacement="                key = _same_cell_key(label, value)",
        target="tests/test_179_layouts.py",
        keyword="same_value_for_a_different_valve",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M406", phase=52,
        description="stop reading a numbered table row by its columns, so a "
                    "small-integer value is discarded as a line number and a "
                    "clause column takes the label's place (issue #179)",
        path=APP / "datasheets.py",
        anchor="            if 0 in serials:\n",
        replacement="            if False:\n",
        target="tests/test_179_layouts.py",
        keyword="small_integer_in_the_value_column or clause_number_column",
        tags=("honesty",),
    ),
    Mutation(
        id="M407", phase=52,
        description="let a page title carried across every column act as a "
                    "column header again, so it is appended to field labels "
                    "and the equipment tag (issue #179 criterion 2)",
        path=APP / "datasheets.py",
        anchor='    header = [text if i == 0 or spread.get(text, 0) < 3 else ""',
        replacement='    header = [text if True else ""',
        target="tests/test_179_layouts.py",
        keyword="page_title_is_never_part or not_polluted_by_the_page_title",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M408", phase=52,
        description="count a title-block fragment ('OF') as an answer in the "
                    "furniture rule, so a title-block row is promoted to a "
                    "field and a stray number becomes a fact (issue #179)",
        path=APP / "datasheets.py",
        anchor="            if answer and states_a_value(value):",
        replacement="            if answer:",
        target="tests/test_repeated_form.py",
        keyword="title_block_fragment_is_not_an_answer",
        tags=("honesty",),
    ),
    Mutation(
        id="M409", phase=52,
        description="stop cutting an underscore-slot line into its fields, so "
                    "a line of several label + drawn-slot pairs is one "
                    "unlabelled cell again (issue #179, pump sheet recall)",
        path=APP / "datasheets.py",
        anchor="                 for piece in split_drawn_slots(c.strip())]",
        replacement="                 for piece in [c.strip()]]",
        target="tests/test_179_layouts.py",
        keyword="each_drawn_slot_on_a_line_is_its_own_field",
        tags=("honesty",),
    ),
    # ---- from B177_JOB_CLAIM_RETRY_PRIORITY -------------------------------
    Mutation(
        id="M418", phase=53,
        description="fact extraction stops recording its input hash, so a "
                    "fact cannot say what it was read from (#177 gap 4)",
        path=APP / "datasheets.py",
        anchor="                        extractor_version=extractor_version,\n"
               "                        input_hash=inputs,\n",
        replacement="                        extractor_version=extractor_version,\n"
                    "                        input_hash=None,\n",
        target="tests/test_job_queue_177.py",
        keyword="fact_extraction_records",
        tags=("honesty",),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M450", phase=57,
        description="PUT IT BACK: fact extraction computes each page's outcome "
                    "and throws it away again (B3)",
        path=APP / "datasheets.py",
        anchor="        page_ledger.record_fact_pages(conn, document_id, outcomes,\n"
               "                                      extractor_version=extractor_version)\n",
        replacement="",
        target=_B3_TEST, keyword="records_each_pages_outcome or keeps_extractions_own",
        tags=("honesty",),
    ),
    # ---- from B4_PUMP_LAYOUTS ---------------------------------------------
    #: Master order B4: the pump datasheet's layout defects. Phase 59.
    Mutation(
        id="M483", phase=59,
        description="PUT IT BACK: an API clause reference stays in the field "
                    "name as digits ('casing type 6 3 10') (B4 fix 1)",
        path=APP / "datasheets.py",
        anchor="    text = _CLAUSE_REF_BRACKET.sub(\" \", text)\n",
        replacement="",
        target=_B4_TEST, keyword="clause_reference_is_not_part or printed_label_keeps",
        tags=("honesty",),
    ),
    Mutation(
        id="M484", phase=59,
        description="strip ANY bracket holding a digit, so a note number or a "
                    "unit bracket is cut out of a real field name (B4 fix 1, "
                    "negative)",
        path=APP / "datasheets.py",
        anchor='    r"\\(\\s*\\d+(?:\\.\\d+)+(?:\\s*[a-z]\\b)?"\n'
               '    r"(?:\\s*[,;&]?\\s*\\d+(?:\\.\\d+)+(?:\\s*[a-z]\\b)?)*\\s*\\)", re.IGNORECASE)\n',
        replacement='    r"\\([^)]*\\d[^)]*\\)", re.IGNORECASE)\n',
        target=_B4_TEST, keyword="not_a_clause_stays",
        tags=("honesty",),
    ),
    Mutation(
        id="M486", phase=59,
        description="PUT IT BACK: a YES/NO answer is stored as the value of a "
                    "quantity limit ('max relative density = YES') (B4 fix 2)",
        path=APP / "datasheets.py",
        anchor="                if checkbox_on_quantity(label, value):\n",
        replacement="                if False:\n",
        target=_B4_TEST, keyword="page_five_shape",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M487", phase=59,
        description="refuse a yes/no answer on ANY label naming a quantity, so "
                    "a real question ('variable speed required = NO') loses "
                    "its answer (B4 fix 2, negative)",
        path=APP / "datasheets.py",
        anchor="    return bool(_LIMIT_WORD.search(text) and _QUANTITY_NOUN.search(text))\n",
        replacement="    return bool(_QUANTITY_NOUN.search(text))\n",
        target=_B4_TEST, keyword="real_yes_no_question",
        tags=("honesty",),
    ),
    Mutation(
        id="M488", phase=59,
        description="PUT IT BACK: a two-unit cell 'm3/h (USGPM)' becomes a "
                    "field label again (B4 fix 3)",
        path=APP / "datasheets.py",
        anchor="    if is_unit_cell(candidate):\n        return False\n",
        replacement="",
        target=_B4_TEST, keyword="unit_cell_is_never or no_unit_named_field",
        tags=("honesty",),
    ),
    Mutation(
        id="M489", phase=59,
        description="refuse a bare unit word as a label, so the pump sheet's "
                    "'RPM' slot loses its field (B4 fix 3, negative)",
        path=APP / "datasheets.py",
        anchor='    return "(" in (text or "") and primary_unit(text) is not None\n',
        replacement="    return primary_unit(text) is not None\n",
        target=_B4_TEST, keyword="bare_unit_word",
    ),
    Mutation(
        id="M490", phase=59,
        description="ignore the unit a grid row states, so '24.8 (109)' under "
                    "'m3/h (USGPM)' has no unit (B4 fix 3)",
        path=APP / "datasheets.py",
        anchor="    if value is not None and unit is None and unit_hint:\n",
        replacement="    if False:\n",
        target=_B4_TEST, keyword="takes_the_primary_unit",
        tags=("honesty",),
    ),
    Mutation(
        id="M491", phase=59,
        description="let the layout's unit hint override a unit printed in the "
                    "value itself (B4 fix 3, negative)",
        path=APP / "datasheets.py",
        anchor="    if value is not None and unit is None and unit_hint:\n",
        replacement="    if value is not None and unit_hint:\n",
        target=_B4_TEST, keyword="not_overridden",
        tags=("honesty",),
    ),
    Mutation(
        id="M492", phase=59,
        description="stop reading an en dash as a range separator, so '5 - 150 "
                    "M' printed with an en dash loses both ends (B4 fix 4 lock)",
        path=APP / "datasheets.py",
        anchor='(?:to|through|\\.\\.\\.|–|—|-)',
        replacement='(?:to|through|\\.\\.\\.|—|-)',
        target=_B4_TEST, keyword="every_dash_spelling or en_dash_range",
        tags=("honesty",),
    ),
    Mutation(
        id="M493", phase=59,
        description="create_fact stops keeping a range's two ends (B4 fix 4 lock)",
        path=APP / "datasheets.py",
        anchor="    found = None if blank else parse_range(raw_value)\n",
        replacement="    found = None\n",
        target=_B4_TEST, keyword="elevation_row or en_dash_range",
        tags=("honesty",),
    ),
    Mutation(
        id="M494", phase=59,
        description="PUT IT BACK: the column grid reader never runs, so the "
                    "process-data rows (flow, temperature, pressures) stay "
                    "dropped (B4 fix 5)",
        path=APP / "datasheets.py",
        anchor='        grid_by_page[page] = _grid_facts_from_pdf_page(stored_path, page)\n',
        replacement="        grid_by_page[page] = []\n",
        target=_B4_TEST, keyword="each_value_is_read_under_its_column",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M495", phase=59,
        description="a value whose box straddles two columns is filed under "
                    "one of them anyway, inventing which column it is in "
                    "(B4 fix 5, negative)",
        path=APP / "datasheets.py",
        anchor="                column = next((name for left, right, name in value_bands\n"
               "                               if x0 >= left - 0.5 and x1 <= right + 0.5), None)\n",
        replacement="                column = min(value_bands, key=lambda b: abs((b[0] + b[1]) / 2 - (x0 + x1) / 2))[2]\n",
        target=_B4_TEST, keyword="value_between_two_columns",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M496", phase=59,
        description="a grid row with no column decided is written as a "
                    "confident fact rather than routed to an engineer (B4 "
                    "fix 5)",
        path=APP / "datasheets.py",
        anchor='                        validation_state=(None if cell["column"] or grid_blank\n'
               "                                          else NEEDS_ENGINEER_REVIEW),\n",
        replacement="                        validation_state=None,\n",
        target=_B4_TEST, keyword="value_between_two_columns",
        tags=("honesty",),
    ),
    Mutation(
        id="M498", phase=59,
        description="a shared-noun compound like 'DESIGN / OPERATING "
                    "PRESSURE' is treated as one quantity, attaching a real "
                    "number to the wrong half of the pair (B4 fix 5, negative)",
        path=APP / "datasheets.py",
        anchor="    return all(len(part.strip(\" :\").split()) == 1 for part in found[1])\n",
        replacement="    return True\n",
        target=_B4_TEST, keyword="shared_noun_compound_stays_unparsed",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M499", phase=59,
        description="a lone 'OC' with no printed Fahrenheit alternate is "
                    "decoded as degrees anyway (B4 fix 5, negative)",
        path=APP / "datasheets.py",
        anchor="    return primary_unit(text)\n",
        replacement='    return "\\u00b0C" if text.strip().upper() == "OC" else primary_unit(text)\n',
        target=_B4_TEST, keyword="lone_degree_glyph_is_not_decoded",
        tags=("honesty",),
    ),
    Mutation(
        id="M500", phase=59,
        description="every grid cell is treated as blank for routing, so a "
                    "REAL reading with no decided column ('7.6 (110)', "
                    "straddling Rated/Normal) is accepted as confident instead "
                    "of routed to an engineer (B4 fix 5)",
        path=APP / "datasheets.py",
        anchor="                grid_blank, _marker = is_blank_value(cell[\"value\"])\n",
        replacement="                grid_blank, _marker = True, \"*\"\n",
        target=_B4_TEST, keyword="value_between_two_columns",
        tags=("honesty", "critical"),
    ),
    # #193 plan B4 (5.5): geometry reader wired behind its flag.
    Mutation(
        id='M586', phase=63,
        description='B4 wiring: the geometry reader runs with the flag OFF',
        path=APP / 'datasheets.py',
        anchor='    geometry_on = bool(settings.geometry_reader_enabled)\n',
        replacement='    geometry_on = True\n',
        target='tests/test_geometry_wiring.py',
        keyword='off_never_calls',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M587', phase=63,
        description='B4 wiring: geometry readings are read but never written as facts',
        path=APP / 'datasheets.py',
        anchor='            for row in geometry_by_page.get(page, []):\n',
        replacement='            for row in []:\n',
        target='tests/test_geometry_wiring.py',
        keyword='adds_geometry_facts',
        tags=('extraction',),
    ),
    Mutation(
        id='M588', phase=63,
        description='B4 wiring: a geometry reading the rule reader already wrote is written again',
        path=APP / 'datasheets.py',
        anchor='                if any(_geometry_agrees(raw, row["is_blank"], f) for f in same_label):\n',
        replacement='                if False:\n',
        target='tests/test_geometry_wiring.py',
        keyword='rule_reader_fact_wins',
        tags=('extraction', 'honesty'),
    ),
    Mutation(
        id='M589', phase=63,
        description='B4 wiring: a geometry reading that contradicts the rule reader is not marked conflict',
        path=APP / 'datasheets.py',
        anchor='                        validation_state=GEOMETRY_CONFLICT if same_label else None,\n',
        replacement='                        validation_state=None,\n',
        target='tests/test_geometry_wiring.py',
        keyword='disagreement_is_recorded',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M595', phase=63,
        description="B4 wiring: geometry readings alone make a page 'read into fields'",
        path=APP / 'datasheets.py',
        anchor='                page_geometry += 1\n',
        replacement='                page_written += 1\n',
        target='tests/test_geometry_wiring.py',
        keyword='alone_do_not_make_a_page_read',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M596', phase=63,
        description='B4 wiring: the unit the reader split off a non-quantity is lost',
        path=APP / 'datasheets.py',
        anchor='        raw_unit = printed_unit\n',
        replacement='        pass\n',
        target='tests/test_geometry_wiring.py',
        keyword='keeps_the_unit_the_reader',
        tags=('extraction', 'units'),
    ),
    Mutation(
        id='M649', phase=64,
        description='B4 vision: the vision provider is asked with the flag off',
        path=APP / 'datasheets.py',
        anchor=('    if geometry_on:\n'
                '        from . import vision_reader\n'
                '        vision_provider, vision_unavailable = vision_reader.provider()\n'),
        replacement=('    if True:\n'
                     '        from . import vision_reader\n'
                     '        vision_provider, vision_unavailable = vision_reader.provider()\n'),
        target='tests/test_b4_quality.py', keyword='off_never_asks_the_vision_reader',
        tags=('egress', 'critical'),
    ),
    Mutation(
        id='M650', phase=64,
        description='B4 vision: proved vision readings are never written',
        path=APP / 'datasheets.py',
        anchor='            vision_by_page[page] = _vision_reading(\n',
        replacement='            vision_by_page[page] = None and _vision_reading(\n',
        target='tests/test_b4_quality.py', keyword='records_proved_vision_readings',
    ),
    Mutation(
        id='M651', phase=64,
        description='B4 noise: the noise filter never runs on the rule reader',
        path=APP / 'datasheets.py',
        anchor=('                noise = (row_noise.noise_reason(label, value)\n'
                '                         if not blank else None)\n'),
        replacement=('                noise = (row_noise.noise_reason(label, value)\n'
                     '                         if False else None)\n'),
        target='tests/test_b4_quality.py', keyword='noise_filter_runs_with_the_flag_off_too',
    ),
    Mutation(
        id='M652', phase=64,
        description='B4 vision: the ledger no longer says what the vision reader did',
        path=APP / 'datasheets.py',
        anchor='                    reason = f"{reason}; {_vision_ledger_note(reading, page_vision, vision_unavailable)}"\n',
        replacement='                    pass\n',
        target='tests/test_b4_quality.py', keyword='only_vision_readings_is_not_read',
        tags=('honesty',),
    ),
    Mutation(
        id='M653', phase=64,
        description='B4 vision: a unit the quantity reader cannot join is lost',
        path=APP / 'datasheets.py',
        anchor='                        unit=printed_unit, printed_unit=printed_unit,\n',
        replacement='                        printed_unit=printed_unit,\n',
        target='tests/test_b4_quality.py', keyword='keeps_a_unit_the_quantity_reader',
        tags=('units',),
    ),
    Mutation(
        id='M658', phase=64,
        description='B4 vision: a vision reading is stored beside a rule-reader fact it contradicts',
        path=APP / 'datasheets.py',
        anchor=('                if same_label:\n'
                '                    why = ("same as rule/geometry reader"\n'),
        replacement=('                if False:\n'
                     '                    why = ("same as rule/geometry reader"\n'),
        target='tests/test_b4_quality.py',
        keyword='disagrees_with_the_rule_reader or never_a_second_row',
        tags=('honesty', 'critical'),
    ),

    # ---- B4 defects, 2026-09-25 (tests/test_b4_defects.py)
    Mutation(
        id='M700', phase=65, description='B4d: a slash dual is accepted without the two halves agreeing',
        path=APP / 'datasheets.py',
        anchor='        if not same_quantity_twice(dual["v1"], dual["u1"], dual["v2"], dual["u2"]):\n            return None, None, None\n',
        replacement='',
        target=_D, keyword='two_different_quantities_are_never_one_value', tags=('honesty',),
    ),
    Mutation(
        id='M701', phase=65, description='B4d: a slash dual-unit cell is never recognised',
        path=APP / 'datasheets.py',
        anchor='    dual = _DUAL_SLASH.match(" ".join(text.split()))\n',
        replacement='    dual = None\n',
        target=_D, keyword='one_quantity_in_two_systems or bar_and_psi',
    ),
    Mutation(
        id='M702', phase=65, description='B4d: the dual-unit tolerance accepts two different temperatures',
        path=APP / 'datasheets.py',
        anchor='DUAL_UNIT_TOLERANCE = 0.02\n', replacement='DUAL_UNIT_TOLERANCE = 10.0\n',
        target=_D, keyword='two_different_quantities_are_never_one_value', tags=('honesty',),
    ),
    Mutation(
        id='M703', phase=65, description='B4d: a tilde is not a range separator',
        path=APP / 'datasheets.py',
        anchor='(?:to|through|\\.\\.\\.|–|—|-|~)', replacement='(?:to|through|\\.\\.\\.|–|—|-)',
        target=_D, keyword='tilde_range_keeps_both_ends',
    ),
    Mutation(
        id='M704', phase=65, description='B4d: an inch fraction is not read as a size',
        path=APP / 'datasheets.py',
        anchor='    if fraction is not None:\n        return fraction, "in", claims.normalise(fraction, "in")\n',
        replacement='',
        target=_D, keyword='nozzle_size_is_stored_in_inches',
    ),
    Mutation(
        id='M705', phase=65, description='B4d: an improper fraction (4/4) is read as a size',
        path=APP / 'datasheets.py',
        anchor='    if num == 0 or num >= den:\n        return None\n', replacement='',
        target=_D, keyword='ratio_or_code_is_not_a_fraction', tags=('honesty',),
    ),
    Mutation(
        id='M706', phase=65, description='B4d: a leading clause number stays in the field name',
        path=APP / 'datasheets.py',
        anchor='    text = _strip_leading_clause(text)\n', replacement='',
        target=_D, keyword='clause_is_not_part_of_the_name',
    ),
    Mutation(
        id='M707', phase=65, description='B4d: a one-dot rating before a unit is stripped as a clause',
        path=APP / 'datasheets.py',
        anchor='    if match["clause"].count(".") == 1 and claims.is_unit(match["next"]):\n        return text\n',
        replacement='',
        target=_D, keyword='number_that_is_not_a_clause_stays', tags=('honesty',),
    ),
    Mutation(
        id='M708', phase=65, description='B4d: a square-bracketed clause stays in the field name',
        path=APP / 'datasheets.py',
        anchor='    r"[\\(\\[]\\s*\\d+(?:\\.\\d+)+(?:\\s*[a-z]\\b)?"\n',
        replacement='    r"\\(\\s*\\d+(?:\\.\\d+)+(?:\\s*[a-z]\\b)?"\n',
        target=_D, keyword='clause_is_not_part_of_the_name or keeps_the_printed_label',
    ),
    Mutation(
        id='M709', phase=65, description='B4d: YES on a count or a quantity head noun is stored',
        path=APP / 'datasheets.py',
        anchor='    return bool(_COUNT_LABEL.search(text) or quantity_head_noun(text))\n',
        replacement='    return False\n',
        target=_D, keyword='yes_is_never_a_count or keeps_counts_and_drops', tags=('honesty',),
    ),
    Mutation(
        id='M710', phase=65, description='B4d: N/A on a quantity is refused like a YES',
        path=APP / 'datasheets.py',
        anchor='    if answer not in _YES_NO:\n',
        replacement='    if False:\n',
        target=_D, keyword='real_answer_stands',
    ),
    Mutation(
        id='M711', phase=65, description='B4d: a count loses its trailing integer to the line-number rule',
        path=APP / 'datasheets.py',
        anchor='                and not count_answer\n', replacement='',
        target=_D, keyword='keeps_counts_and_drops',
    ),
    Mutation(
        id='M712', phase=65, description='B4d: a count followed by another field keeps a line number as its value',
        path=APP / 'datasheets.py',
        anchor='        count_answer = (index + 2 == len(parts) and _COUNT_LABEL.search(label) is not None)\n',
        replacement='        count_answer = _COUNT_LABEL.search(label) is not None\n',
        target=_D, keyword='count_followed_by_another_field', tags=('honesty',),
    ),
    Mutation(
        id='M713', phase=65, description='B4d: a grid without a Units column is not read',
        path=APP / 'datasheets.py',
        anchor='        unitless = (not units and len(cols) >= 3 and len(cols) == len(header))\n',
        replacement='        unitless = False\n',
        target=_D, keyword='under_its_column_with_the_labels_unit',
    ),
    Mutation(
        id='M714', phase=65, description='B4d: a prose line with column words is taken for a grid header',
        path=APP / 'datasheets.py',
        anchor='        unitless = (not units and len(cols) >= 3 and len(cols) == len(header))\n',
        replacement='        unitless = (not units and len(cols) >= 3)\n',
        target=_D, keyword='prose_with_column_words', tags=('honesty',),
    ),
    Mutation(
        id='M715', phase=65, description='B4d: a field below a unitless grid is filed under a grid column',
        path=APP / 'datasheets.py',
        anchor='                if started and (too_far or own_unit):\n                    break\n',
        replacement='',
        target=_D, keyword='grid_ends_where_its_rows_end', tags=('honesty',),
    ),
    Mutation(
        id='M716', phase=65, description='B4d: the flat reader stores a grid row a second time, garbled',
        path=APP / 'datasheets.py',
        anchor='                    dropped["read as a grid row"] = dropped.get("read as a grid row", 0) + 1\n                    continue\n',
        replacement='                    pass\n',
        target=_D, keyword='flat_reader_does_not_also_store', tags=('honesty',),
    ),
    Mutation(
        id='M717', phase=65, description='B4d: a unit at the end of a grid label is never split off',
        path=APP / 'datasheets.py',
        anchor='    return " ".join(words[:-1]), last\n',
        replacement='    return label, None\n',
        target=_D, keyword='under_its_column_with_the_labels_unit or split_off_a_label_only',
    ),
    Mutation(
        id='M718', phase=65, description='B4d: any last word of a grid label is taken for its unit',
        path=APP / 'datasheets.py',
        anchor='    if not claims.is_unit(unit_base or ""):\n        return label, None\n    return " ".join(words[:-1]), last\n',
        replacement='    return " ".join(words[:-1]), last\n',
        target=_D, keyword='split_off_a_label_only_when_it_is_a_unit', tags=('honesty',),
    ),
)
