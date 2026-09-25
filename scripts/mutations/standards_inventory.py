"""Mutations of `backend/app/standards_inventory.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M505", phase=61,
        description="read a family only when it is at the START of the "
                    "identifier, so a number-first citation ('02-SAMSS-014') "
                    "is silently read as OTHER instead of SAMSS",
        path=APP / "standards_inventory.py",
        anchor='    match = _FAMILY_TOKEN.search(identifier or "")',
        replacement='    match = _FAMILY_TOKEN.match(identifier or "")',
        target="tests/test_standards_inventory.py",
        keyword="a_known_family_is_read_from_the_identifier",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M506", phase=61,
        description="claim a copyrighted standard's licence position is "
                    "unknown instead of licensed-not-held, hiding the "
                    "owner's missing-list from the ones that actually "
                    "need a licence",
        path=APP / "standards_inventory.py",
        anchor="    if family in COPYRIGHTED_FAMILIES:\n"
               "        return LICENCE_LICENSED_NOT_HELD",
        replacement="    if False:\n"
                    "        return LICENCE_LICENSED_NOT_HELD",
        target="tests/test_standards_inventory.py",
        keyword="a_missing_copyrighted_standard_is_licensed_not_held",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M507", phase=61,
        description="default EVERY missing standard to licensed_not_held, "
                    "so a missing SAES/SAMSS document (the client's own, "
                    "not a copyright gap) is reported as needing a licence",
        path=APP / "standards_inventory.py",
        anchor="    return LICENCE_UNKNOWN",
        replacement="    return LICENCE_LICENSED_NOT_HELD",
        target="tests/test_standards_inventory.py",
        keyword="a_missing_own_or_unrecognised_standard_is_unknown",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M508", phase=61,
        description="read three cover pages instead of two, so a body "
                    "reference on page 3 is mistaken for the document's own "
                    "number",
        path=APP / "standards_inventory.py",
        anchor="_COVER_PAGES = 2",
        replacement="_COVER_PAGES = 3",
        target="tests/test_standards_inventory.py",
        keyword="a_body_reference_on_a_later_page_is_not_read_as_the_covers_own_number",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M509", phase=61,
        description="stop zero-padding a two-digit SAES series number, so "
                    "SAES-A-4 and the library's own SAES-A-004 read as two "
                    "different standards",
        path=APP / "standards_inventory.py",
        anchor='                    value=f"SAES-{match.group(1).upper()}-{int(match.group(2)):03d}",',
        replacement='                    value=f"SAES-{match.group(1).upper()}-{match.group(2)}",',
        target="tests/test_standards_inventory.py",
        keyword="a_two_digit_series_number_is_zero_padded_to_three",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M510", phase=61,
        description="mark every standard as cited by a submittal regardless "
                    "of whether any readable submittal actually names it",
        path=APP / "standards_inventory.py",
        anchor='            "cited_by_submittal": bool(key) and key in cited,',
        replacement='            "cited_by_submittal": True,',
        target="tests/test_standards_inventory.py",
        keyword="a_standard_not_cited_by_any_readable_submittal_is_not_flagged",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M511", phase=61,
        description="scope the citation query on document role alone, "
                    "dropping the caller's own grants, so a submittal "
                    "outside the caller's access still marks a standard "
                    "cited (CLAUDE.md rule 5 - narrow only, never union)",
        path=APP / "standards_inventory.py",
        anchor="        f\"\"\"SELECT ch.text FROM chunks ch\n"
               "            JOIN document_classification c ON c.document_id = ch.document_id\n"
               "            WHERE ch.document_id IN ({marks})\n"
               "              AND c.document_role = 'CONTRACTOR_SUBMITTAL'\"\"\",\n"
               "        sorted(allowed_document_ids)).fetchall()",
        replacement="        \"\"\"SELECT ch.text FROM chunks ch\n"
                    "            JOIN document_classification c ON c.document_id = ch.document_id\n"
                    "            WHERE c.document_role = 'CONTRACTOR_SUBMITTAL'\"\"\"\n"
                    "        ).fetchall()",
        target="tests/test_standards_inventory.py",
        keyword="a_citation_in_a_submittal_outside_the_callers_grants_does_not_count",
        tags=("permission", "inventory", "critical"),
    ),
    Mutation(
        id="M512", phase=61,
        description="backfill a document_number even when one is already "
                    "set, so a human-confirmed or previously-backfilled "
                    "number is silently overwritten on a re-run",
        path=APP / "standards_inventory.py",
        anchor="    if existing[\"document_number\"] is None and meta.document_number is not None:",
        replacement="    if meta.document_number is not None:",
        target="tests/test_standards_inventory.py",
        keyword="an_already_confirmed_document_number_is_never_overwritten",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M513", phase=61,
        description="read 'Previous Issue' as the effective date, so a "
                    "standard's date is recorded as the PRIOR revision's "
                    "date instead of the current one",
        path=APP / "standards_inventory.py",
        anchor='    r"\\b(?:Issue\\s+Date|Effective\\s+Date)\\s*[:#]?\\s*"',
        replacement='    r"\\b(?:Issue\\s+Date|Effective\\s+Date|Previous\\s+Issue)\\s*[:#]?\\s*"',
        target="tests/test_standards_inventory.py",
        keyword="previous_issue_is_not_read_as_the_effective_date",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M514", phase=61,
        description="fill effective_date even when one is already set, "
                    "overwriting a confirmed date on a re-run",
        path=APP / "standards_inventory.py",
        anchor='    if existing["effective_date"] is None and meta.effective_date is not None:',
        replacement='    if meta.effective_date is not None:',
        target="tests/test_standards_inventory.py",
        keyword="an_already_set_effective_date_is_never_overwritten",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M515", phase=61,
        description="store an unparsed date fragment as effective_date "
                    "instead of leaving it UNKNOWN, so a caller can no "
                    "longer trust every stored date is ISO",
        path=APP / "standards_inventory.py",
        anchor="                if iso is not None:\n"
               "                    effective_date = CoverField(\n"
               "                        value=iso, page=page[\"page_no\"],\n"
               "                        quote=match.group(0).strip())",
        replacement="                effective_date = CoverField(\n"
                    "                    value=iso or match.group(1),\n"
                    "                    page=page[\"page_no\"],\n"
                    "                    quote=match.group(0).strip())",
        target="tests/test_standards_inventory.py",
        keyword="extract_cover_metadata_also_refuses_an_unparseable_captured_date",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M518", phase=61,
        description="report a citation as missing even when it resolves to "
                    "a held standard, re-flagging six real standards as "
                    "gaps the way the pre-existing bug this rule was built "
                    "to prevent once did",
        path=APP / "standards_inventory.py",
        anchor="        matched = _match_referenced(library, [identifier])\n"
               "        if matched:\n"
               "            continue  # held - not a gap",
        replacement="        matched = _match_referenced(library, [identifier])\n"
                    "        if False:\n"
                    "            continue  # held - not a gap",
        target="tests/test_standards_inventory.py",
        keyword="a_standard_cited_by_a_submittal_and_actually_held_is_not_reported",
        tags=("honesty", "inventory", "critical"),
    ),
    Mutation(
        id="M519", phase=61,
        description="scan every requirement_type for a cited document, not "
                    "just applicability_trigger, so an ordinary numeric "
                    "limit that names a standard in passing is reported as "
                    "a normative reference",
        path=APP / "standards_inventory.py",
        anchor='              AND r.requirement_type = ?""",\n'
               "        [*sorted(allowed_document_ids), APPLICABILITY_TRIGGER]).fetchall()",
        replacement='              AND 1 = 1""",\n'
                    "        [*sorted(allowed_document_ids)]).fetchall()",
        target="tests/test_standards_inventory.py",
        keyword="a_requirement_that_is_not_an_applicability_trigger_is_not_scanned",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M520", phase=61,
        description="drop the superseded_by filter, so a superseded "
                    "standard revision's own citations are still reported "
                    "as a live gap",
        path=APP / "standards_inventory.py",
        anchor="              AND c.document_role = 'COMPANY_STANDARD'\n"
               "              AND c.superseded_by IS NULL\n"
               "              AND r.requirement_type = ?\"\"\",",
        replacement="              AND c.document_role = 'COMPANY_STANDARD'\n"
                    "              AND r.requirement_type = ?\"\"\",",
        target="tests/test_standards_inventory.py",
        keyword="a_superseded_standards_requirement_citations_are_not_reported",
        tags=("honesty", "inventory"),
    ),
    Mutation(
        id="M521", phase=61,
        description="key the missing-standards report by citation instead "
                    "of by normalised identifier, so the same standard "
                    "cited twice produces two rows instead of one grouping "
                    "both citations",
        path=APP / "standards_inventory.py",
        anchor='        entry = by_key.setdefault(key, {\n'
               '            "identifier": identifier,',
        replacement='        entry = by_key.setdefault(str(len(by_key)), {\n'
                    '            "identifier": identifier,',
        target="tests/test_standards_inventory.py",
        keyword="two_citations_of_the_same_missing_standard_are_one_row_listing_both",
        tags=("honesty", "inventory"),
    ),
)
