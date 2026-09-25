"""Mutations of `backend/app/applicability.py`."""

from __future__ import annotations

from ._base import APP, _B18_GUARD, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_5A ----------------------------------------------------
    #: Phase 5A: applicability selection. `phase=6` because --phase 5 already
    #: selects phase 4; the ids are the stable handle.
    Mutation(
        id="M57", phase=6,
        description="stop matching standards the datasheet explicitly names",
        path=APP / "applicability.py",
        anchor="        if entry is not None:\n            out[entry[\"id\"]] = {",
        replacement="        if False:\n            out[entry[\"id\"]] = {",
        target="tests/test_applicability.py",
        keyword="named_in_the_datasheet_is_selected or citation_of_a_part",
        tags=("selection",),
    ),
    Mutation(
        id="M58", phase=6,
        description="silently drop a referenced standard the library lacks",
        path=APP / "applicability.py",
        anchor="        if normalise_identifier(identifier) not in matched_keys",
        replacement="        if False",
        target="tests/test_applicability.py",
        keyword="absent_from_the_library_is_reported_missing",
        tags=("honesty", "missing"),
    ),
    Mutation(
        id="M59", phase=6,
        description="let a semantically retrieved standard satisfy a missing "
                    "reference - THE failure this phase exists to prevent",
        path=APP / "applicability.py",
        anchor="    selected, missing = _semantic_cannot_cover_a_missing_reference(selected, missing)",
        replacement="    missing = [m for m in missing if not selected]",
        target="tests/test_applicability.py",
        keyword="semantically_retrieved_standard_does_not_satisfy",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M60", phase=6,
        description="select superseded standards again",
        path=APP / "applicability.py",
        anchor="    ids = standards.selectable_standard_ids(allowed_document_ids=allowed_document_ids)",
        replacement="    ids = frozenset(r[0] for r in connect().execute(\"SELECT document_id FROM document_classification WHERE document_role = 'COMPANY_STANDARD'\"))",
        target="tests/test_applicability.py",
        keyword="superseded_standard_is_not_selected",
        tags=("supersession",),
    ),
    Mutation(
        id="M61", phase=6,
        description="stop recording standards considered and ruled out",
        path=APP / "applicability.py",
        anchor="        if entry[\"id\"] in selected:\n            continue",
        replacement="        if True:\n            continue",
        target="tests/test_applicability.py",
        keyword="keeps_its_exclusion_reason",
        tags=("audit",),
    ),
    Mutation(
        id="M62", phase=6,
        description="stop auditing an engineer override",
        path=APP / "applicability.py",
        # Disables the audit WITHOUT raising. Calling a name that does not
        # exist fails the test with a NameError - the right verdict for the
        # wrong reason, and indistinguishable from a real detection. That is
        # honesty-audit entries 10 and 12, and this is the third time the
        # same shortcut has been reached for, so the reasoning lives here at
        # the mutation rather than only in the audit file.
        anchor='    """Durable record of a selection decision. Ids and counts only."""\n'
               '    conn = connect()',
        replacement='    """Durable record of a selection decision. Ids and counts only."""\n'
                    '    return\n'
                    '    conn = connect()',
        target="tests/test_applicability.py",
        keyword="override_writes_an_audit_row",
        tags=("audit",),
    ),
    Mutation(
        id="M63", phase=6,
        description="drop the confidence ceiling, allowing a high confidence",
        path=APP / "applicability.py",
        anchor="    confidence = min(float(confidence), ceiling)",
        replacement="    confidence = float(confidence)",
        target="tests/test_applicability.py",
        keyword="confidence_is_never_high",
        tags=("honesty",),
    ),
    # ---- from DATASHEET ---------------------------------------------------
    #: The datasheet side: which strings are citations, where a unit lives, and
    #: what is not a fact at all.
    Mutation(
        id="M104", phase=8,
        description="stop zero-padding the library filename, so a standard "
                    "cannot be matched to itself",
        path=APP / "applicability.py",
        anchor='    return f"{match.group(1).upper()}-{match.group(2).upper()}-{int(match.group(3)):03d}"',
        replacement='    return f"{match.group(1).upper()}-{match.group(2).upper()}-{match.group(3)}"',
        target="tests/test_reference_identifiers.py",
        keyword="padded_number or matches_the_citation_key",
    ),
    # ---- from CRS_EXPORT --------------------------------------------------
    #: The CRS export: who may export, and what the file is allowed to say.
    Mutation(
        id="M239", phase=22,
        description="print the NORMALISED key, so a contractor reads "
                    "'32SAMSS004' and has to guess what was meant",
        # RE-ANCHORED IN THE SAME CHANGE THAT MOVED ITS LINE (audit entry 43
        # was a mutation going silently inert under exactly such a move). The
        # rule now lives in applicability.missing_references.
        path=APP / "applicability.py",
        anchor="            missing.append(name.strip())",
        replacement="            missing.append(key)",
        target="tests/test_crs_endpoint.py",
        keyword="keeps_the_spelling_the_submittal_used",
    ),
    # ---- from MISSING_REFERENCES ------------------------------------------
    #: A gap row must be TRUE, not just present. The dashboard and the CRS both
    #: reported every cited standard missing, because their check compared an
    #: identifier against a dict keyed by document id.
    Mutation(
        id="M248", phase=24,
        description="PUT THE DEFECT BACK: call every cited standard missing, "
                    "so the CRS tells a contractor held standards are absent",
        path=APP / "applicability.py",
        anchor="        if not _match_referenced(library, [name]):",
        replacement="        if True:",
        target="tests/test_crs_endpoint.py",
        keyword="library_holds_gets_no_gap_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M249", phase=24,
        description="the same defect, seen from the Dashboard tile that read "
                    "'21 of 21 cited standards are not in the library'",
        path=APP / "applicability.py",
        anchor="        if not _match_referenced(library, [name]):",
        replacement="        if True:",
        target="tests/test_review_dashboard.py",
        keyword="library_holds_is_not_counted_missing",
        tags=("honesty",),
    ),
    Mutation(
        id="M250", phase=24,
        description="read identifiers back out of ONE combined match, keyed "
                    "by document - so two spellings of a held standard collide "
                    "and the loser is reported missing",
        path=APP / "applicability.py",
        anchor="        if not _match_referenced(library, [name]):\n"
               "            missing.append(name.strip())",
        replacement="        held = {normalise_identifier(v[\"identifier\"])\n"
                    "                for v in _match_referenced(library, referenced).values()}\n"
                    "        if key not in held:\n"
                    "            missing.append(name.strip())",
        target="tests/test_applicability.py",
        keyword="two_spellings_of_one_held_standard",
    ),
    # ---- from B18_UNMEASURED_FACTOR ---------------------------------------
    #: B18: completeness dropped an UNMEASURED extraction factor and reported the
    #: other half alone - 1.0 and "sufficient" with the datasheet never measured.
    Mutation(
        id="M313", phase=35,
        description="applicability: the same, in the other home",
        path=APP / "applicability.py",
        anchor=_B18_GUARD,
        replacement="    if False:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="extraction_was_never_measured",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M315", phase=35,
        description="applicability: hide M-03's determinate 0.0 behind None",
        path=APP / "applicability.py",
        anchor=_B18_GUARD,
        replacement="    if extraction is None:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="keeps_m03",
        tags=("honesty",),
    ),
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M522", phase=61,
        description="call a selected standard with zero extracted "
                    "requirements assessable, so a review claims to have "
                    "compared against a standard nothing was ever read from",
        path=APP / "applicability.py",
        anchor="            if requirement_counts.get(std_id):",
        replacement="            if True:",
        target="tests/test_applicability_with_reasons.py",
        keyword="a_selected_standard_with_no_requirements_needs_another_document",
        tags=("honesty", "applicability", "critical"),
    ),
    Mutation(
        id="M523", phase=61,
        description="skip the standard's-own-attributes check, so a "
                    "standard recording no equipment_type/discipline/"
                    "service/project of its own is called NOT APPLICABLE "
                    "instead of UNKNOWN",
        path=APP / "applicability.py",
        anchor="        if not submittal_has_profile or not standard_has_profile:",
        replacement="        if not submittal_has_profile:",
        target="tests/test_applicability_with_reasons.py",
        keyword="a_standard_with_no_comparable_fields_is_unknown_not_not_applicable",
        tags=("honesty", "applicability", "critical"),
    ),
    Mutation(
        id="M524", phase=61,
        description="drop the case-insensitive/blank guard on the mismatch "
                    "comparison, so a field either side left blank is "
                    "reported as a stated conflict that was never observed",
        path=APP / "applicability.py",
        anchor="            for field in _COMPARABLE_FIELDS\n"
               "            if (entry.get(field) or \"\").strip()\n"
               "            and (profile.get(field) or \"\").strip()\n"
               "            and entry[field].strip().lower() != profile[field].strip().lower()",
        replacement="            for field in _COMPARABLE_FIELDS\n"
                    "            if entry.get(field) != profile.get(field)",
        target="tests/test_applicability_with_reasons.py",
        keyword="a_field_blank_on_one_side_is_never_reported_as_a_stated_mismatch",
        tags=("honesty", "applicability"),
    ),
)
