"""Mutations of `backend/app/classification.py`."""

from __future__ import annotations

from ._base import APP, _B176_TARGET, _EQUIPMENT_TYPE_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_2 -----------------------------------------------------
    Mutation(
        id="M11", phase=2,
        description="make the metadata filter UNION with the caller's scope instead of intersecting",
        path=APP / "classification.py",
        anchor="    return frozenset(matched & set(scope.allowed_document_ids)), True",
        replacement="    return frozenset(matched | set(scope.allowed_document_ids)), True",
        target="tests/test_document_metadata_filters.py",
        keyword="intersect or narrow or cannot_widen",
        tags=("permission",),
    ),
    Mutation(
        id="M14", phase=2,
        description="make the metadata filter fall back to the whole corpus when it matches nothing",
        path=APP / "classification.py",
        anchor="    if wanted.is_empty:\n        return scope.allowed_document_ids, False",
        replacement="    if True:\n        return scope.allowed_document_ids, False",
        target="tests/test_document_metadata_filters.py",
        keyword="matches_nothing or narrow",
        tags=("permission",),
    ),
    # ---- from ROLES_FIX ---------------------------------------------------
    #: Document roles: the watched folder's subfolder convention, and the bulk
    #: assignment endpoint. Not a phase - a contained fix between phases 5B and 6.
    #:
    #: M73 IS THE ONE THAT MATTERS. Every other mutation here breaks something a
    #: user would notice. M73 makes the watcher guess a role from the filename,
    #: which on this corpus is right 272 times out of 280 and would look like an
    #: improvement in a diff.
    Mutation(
        id="M81", phase=8,
        description="let set_role report a change when the value is identical",
        path=APP / "classification.py",
        # RE-ANCHORED after `set_role` and `set_discipline` were refactored
        # onto one writer, which turned the column name into an f-string hole.
        # The old anchor stopped matching and the harness said "anchor matched
        # 0 times" instead of reporting a pass - the guard working, and the
        # reason an anchor must match EXACTLY once rather than at least once.
        anchor='            f" WHERE document_classification.{column}"\n'
               '            f" IS NOT excluded.{column}{guard}",',
        replacement='            f" WHERE 1 = 1{guard}",',
        target="tests/test_document_roles.py",
        keyword="separates_documents_it_changed or reports_whether_it_changed",
        tags=("honesty",),
    ),
    # ---- from DISCIPLINE --------------------------------------------------
    #: Part A of the extraction preparation: the discipline each standard's own
    #: cover page names. M84 is the one with teeth - the letter map is the rule
    #: anyone would reach for, and it is wrong for whole families of this corpus.
    Mutation(
        id="M91", phase=8,
        description="accept a blank discipline, which reads as classified and "
                    "matches nothing",
        path=APP / "classification.py",
        anchor='        raise ValueError("discipline must not be blank; leave it NULL instead")',
        replacement="        pass",
        target="tests/test_standard_discipline.py",
        keyword="refuses_a_blank_value",
    ),
    # ---- from DISCIPLINE_CANONICAL ----------------------------------------
    #: The discipline overlay: one canonical value, the raw one kept intact.
    Mutation(
        id="M234", phase=21,
        description="filter on the RAW column again, so the same question "
                    "asked two ways gets two different answers",
        path=APP / "classification.py",
        anchor='            f"COALESCE(c.discipline_canonical, c.discipline) IN ({marks})")',
        replacement='            f"c.discipline IN ({marks})")',
        target="tests/test_discipline_canonical.py",
        keyword="finds_both_spellings_whichever_one_is_asked_for",
    ),
    Mutation(
        id="M235", phase=21,
        description="stop canonicalising the REQUESTED value, so an alias "
                    "spelling in the query matches nothing at all",
        path=APP / "classification.py",
        anchor="        wantedcanon = [disciplines_mod.canonical(d) or d\n"
               "                       for d in wanted.disciplines]",
        replacement="        wantedcanon = list(wanted.disciplines)",
        target="tests/test_discipline_canonical.py",
        keyword="finds_both_spellings_whichever_one_is_asked_for",
    ),
    Mutation(
        id="M236", phase=21,
        description="drop the COALESCE, so a row written before the column "
                    "existed vanishes from every filtered result",
        path=APP / "classification.py",
        anchor='            f"COALESCE(c.discipline_canonical, c.discipline) IN ({marks})")',
        replacement='            f"c.discipline_canonical IN ({marks})")',
        target="tests/test_discipline_canonical.py",
        keyword="written_before_the_column_existed_is_still_findable",
    ),
    Mutation(
        id="M242", phase=21,
        description="DROP A VALUE from the suggestion INSERT - the exact "
                    "defect that would have failed every document ingest",
        path=APP / "classification.py",
        anchor='            " VALUES (?,?,?,?,?,?,?,NULL,NULL)"',
        replacement='            " VALUES (?,?,?,?,?,?,NULL,NULL)"',
        target="tests/test_discipline_canonical.py",
        keyword="suggestion_is_written_with_its_canonical_beside_it",
        tags=("critical",),
    ),
    # ---- from B9_EQUIPMENT_TYPE -------------------------------------------
    #: B9: automated, evidence-based `equipment_type` for CONTRACTOR_SUBMITTAL,
    #: wired into the same ingestion-completion point as B19's fact extraction.
    Mutation(
        id="M360", phase=46,
        description="drop the CONTRACTOR_SUBMITTAL role gate, so a "
                    "COMPANY_STANDARD (and an unclassified document) gets an "
                    "equipment_type guessed for it too",
        path=APP / "classification.py",
        anchor='    if existing is None or existing["document_role"] != "CONTRACTOR_SUBMITTAL":\n'
               '        return None',
        replacement='    if existing is None or False:\n        return None',
        target=_EQUIPMENT_TYPE_TEST,
        keyword="test_a_company_standard_never_gets_equipment_type_set"
                " or test_an_unclassified_document_gets_no_equipment_type",
        tags=("critical",),
    ),
    Mutation(
        id="M361", phase=46,
        description="drop the confirmed-classification guard, so the "
                    "automated classifier overwrites an administrator's own "
                    "confirmed equipment_type",
        path=APP / "classification.py",
        anchor='    if existing["confirmed_by"] is not None:\n        return None',
        replacement='    if False:\n        return None',
        target=_EQUIPMENT_TYPE_TEST,
        keyword="test_a_confirmed_classification_is_not_overwritten_by_the_classifier",
        tags=("critical",),
    ),
    Mutation(
        id="M362", phase=46,
        description="drop the 'nothing matched' guard, so a document with no "
                    "real evidence is no longer left NULL",
        path=APP / "classification.py",
        anchor="    evidence = suggest_equipment_type(chunks)\n"
               "    if evidence is None:\n        return None",
        replacement="    evidence = suggest_equipment_type(chunks)\n"
                    "    if False:\n        return None",
        target=_EQUIPMENT_TYPE_TEST,
        keyword="test_a_document_with_no_evidence_stays_unclassified",
        tags=("critical", "honesty"),
    ),
    Mutation(
        id="M363", phase=46,
        description="audit every first-time classification too (drop the "
                    "'old_value is not None' guard), so a reclassification's "
                    "audit trail is no longer distinguishable from an "
                    "ordinary first ingest",
        path=APP / "classification.py",
        anchor="    if old_value is not None and evidence.equipment_type != old_value:",
        replacement="    if evidence.equipment_type != old_value:",
        target=_EQUIPMENT_TYPE_TEST,
        keyword="test_reclassification_is_versioned_not_silently_overwritten",
        tags=("critical",),
    ),
    Mutation(
        id="M364", phase=46,
        description="drop the reclassification audit call entirely, so a "
                    "changed equipment_type silently loses its old value "
                    "with no trace",
        path=APP / "classification.py",
        anchor="    if old_value is not None and evidence.equipment_type != old_value:\n"
               "        _audit_equipment_type_change(\n"
               "            document_id, old_value=old_value, evidence=evidence,\n"
               "            classified_by=classified_by)\n"
               "    return evidence",
        replacement="    return evidence",
        target=_EQUIPMENT_TYPE_TEST,
        keyword="test_reclassification_is_versioned_not_silently_overwritten",
        tags=("critical",),
    ),
    # ---- from B176_SUBMITTAL_METADATA -------------------------------------
    Mutation(
        id="M420", phase=54,
        description="resolve disagreeing pages by taking the first value, so "
                    "a submittal whose sheets carry two different revisions "
                    "or document numbers is given one of them as fact (#176)",
        path=APP / "classification.py",
        anchor="        if len(keys) > 1:\n"
               "            conflicts[field_name]",
        replacement="        if False:\n"
                    "            conflicts[field_name]",
        target=_B176_TARGET,
        keyword="disagreeing_revisions_are_a_conflict or "
                "disagreeing_document_numbers_are_a_conflict",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M421", phase=54,
        description="let the revision value sit on the NEXT line, so a "
                    "revision-table header's row number reads as the "
                    "document's revision (#176)",
        path=APP / "classification.py",
        anchor='    r"^[ \\t]*REV(?:ISION)?\\b\\.?[ \\t]*(?:NO\\b\\.?)?[ \\t]*:?[ \\t]*"',
        replacement='    r"^[ \\t]*REV(?:ISION)?\\b\\.?[ \\t]*(?:NO\\b\\.?)?[ \\t]*:?\\s*"',
        target=_B176_TARGET,
        keyword="revision_table_row_number",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M422", phase=54,
        description="accept a project NAME with no identifier, so 'Project: "
                    "<prose>' becomes a filter key (#176)",
        path=APP / "classification.py",
        anchor='        if re.search(r"\\d", value) and not _is_placeholder(value):\n'
               '            hits.append((value, _line_of(text, match)))',
        replacement='        if not _is_placeholder(value):\n'
                    '            hits.append((value, _line_of(text, match)))',
        target=_B176_TARGET,
        keyword="project_name_without_an_identifier",
        tags=("honesty",),
    ),
    Mutation(
        id="M423", phase=54,
        description="stop refusing the duty word CONTINUOUS, so API 610's "
                    "'SERVICE: CONTINUOUS' duty cell becomes the equipment's "
                    "service (#176)",
        path=APP / "classification.py",
        anchor='    "CONTINUOUS", "INTERMITTENT", "STANDBY", "SPARE", "CYCLIC", "BATCH",\n',
        replacement='    "INTERMITTENT", "STANDBY", "SPARE", "CYCLIC", "BATCH",\n',
        target=_B176_TARGET,
        keyword="duty_field_labelled_service",
        tags=("honesty",),
    ),
    Mutation(
        id="M424", phase=54,
        description="make the colon after a same-line SERVICE label optional, "
                    "so 'SERVICE ORDER NO. ...' is read as a service (#176)",
        path=APP / "classification.py",
        anchor='    r"^[ \\t]*SERVICE[ \\t]*:[ \\t]*(?P<value>',
        replacement='    r"^[ \\t]*SERVICE[ \\t]*:?[ \\t]*(?P<value>',
        target=_B176_TARGET,
        keyword="service_near_misses or vessel_title_block",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M425", phase=54,
        description="stop removing parenthetical remarks from a tag line, so "
                    "a location code inside '(for AREA-9 ...)' becomes a tag "
                    "(#176)",
        path=APP / "classification.py",
        anchor='        value = _PARENTHETICAL.sub(" ", value)',
        replacement='        value = value',
        target=_B176_TARGET,
        keyword="psv_title_block or tag_near_misses",
        tags=("honesty",),
    ),
    Mutation(
        id="M426", phase=54,
        description="read the discipline title phrase on every page, so a "
                    "body section heading becomes the document's discipline "
                    "(#176)",
        path=APP / "classification.py",
        anchor='            if field_name == "discipline" and page_no != first_page:',
        replacement='            if False:',
        target=_B176_TARGET,
        keyword="discipline_is_read_from_the_title_block_page_only",
        tags=("honesty",),
    ),
    Mutation(
        id="M427", phase=54,
        description="overwrite a value the classifier did not write, so a "
                    "discipline set by the register or a backfill is replaced "
                    "by a title-phrase match (#176)",
        path=APP / "classification.py",
        anchor="        if current is not None and not ours:\n"
               "            continue",
        replacement="        if False:\n"
                    "            continue",
        target=_B176_TARGET,
        keyword="value_the_classifier_did_not_write",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M428", phase=54,
        description="stop auditing a replaced value, so a reclassification "
                    "leaves no audit_events row (#176 criterion 4)",
        path=APP / "classification.py",
        anchor="            replaced.append((field_name, current, evidence))",
        replacement="            pass",
        target=_B176_TARGET,
        keyword="reclassification_is_audited or "
                "controlled_vocabulary_reclassification",
        tags=("honesty", "critical"),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M461", phase=57,
        description="PUT #183 BACK: the equipment classifier reads retrievable "
                    "chunks only, so a stripped title block is never evidence",
        path=APP / "classification.py",
        anchor="    evidence = suggest_equipment_type_from_title(title_block_lines(pages))\n",
        replacement="    evidence = None\n",
        target="tests/test_183_title_block.py",
        keyword="chunker_stripped or reprinted_header",
        tags=("honesty",),
    ),
    Mutation(
        id="M462", phase=57,
        description="treat every line of every page as the title block, so a "
                    "body sentence naming other equipment names the sheet (#183)",
        path=APP / "classification.py",
        anchor="        edge = lines[:n] + lines[-n:] if len(lines) > 2 * n else lines\n",
        replacement="        edge = lines\n",
        target="tests/test_183_title_block.py",
        keyword="body_sentence",
        tags=("honesty",),
    ),
    Mutation(
        id="M463", phase=57,
        description="ignore the header a datasheet reprints on every page, so "
                    "the more specific name it carries is never read (#183)",
        path=APP / "classification.py",
        anchor="            if page_no == first_page or (norm in running and norm not in seen):\n",
        replacement="            if page_no == first_page:\n",
        target="tests/test_183_title_block.py",
        keyword="reprinted_header",
        tags=("honesty",),
    ),
)
