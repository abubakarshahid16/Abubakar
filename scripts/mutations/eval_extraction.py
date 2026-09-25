"""Mutations of `scripts/eval_extraction.py`."""

from __future__ import annotations

from ._base import REPO, _EVAL, _SCORERS_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B179_EXTRACTION_QUALITY_2 -----------------------------------
    #: Issue #179, second pass. Phase 52, ids M400-M409.
    Mutation(
        id="M400", phase=52,
        description="stop telling a DUPLICATE extracted row from a SPURIOUS "
                    "one in the scoring harness's breakdown, so 150 repeats "
                    "of one row read as 150 invented facts (issue #179)",
        path=_EVAL,
        anchor="        if identity in matched_identities or identity in spurious_seen:",
        replacement="        if False:",
        target="tests/test_eval_extraction_harness.py",
        keyword="duplicates_and_spurious or nobody_asked_for",
        tags=("honesty",),
    ),
    Mutation(
        id="M401", phase=52,
        description="let an EMPTY gold denominator through the scoring "
                    "harness, so a sheet that parsed to nothing prints F1 "
                    "0.0000 as if it were a measurement (issue #179)",
        path=_EVAL,
        anchor="    if not any(not g[\"is_blank\"] for g in gold_fields):",
        replacement="    if False:",
        target="tests/test_eval_extraction_harness.py",
        keyword="empty_gold_denominator or empty_denominator",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M402", phase=52,
        description="let ZERO extracted rows through the scoring harness "
                    "without the explicit waiver, so a wrong --doc or --db "
                    "scores as a real zero (issue #179)",
        path=_EVAL,
        anchor="    if not got_fields and not allow_empty_extraction:",
        replacement="    if False:",
        target="tests/test_eval_extraction_harness.py",
        keyword="zero_extracted_rows",
        tags=("honesty",),
    ),
    Mutation(
        id="M403", phase=52,
        description="drop the breakdown from the persisted scoring JSON, so "
                    "the only record a reader finds is the folded F1 "
                    "(issue #179 criterion 3)",
        path=_EVAL,
        anchor='        "breakdown": breakdown(gold_fields, got_fields),\n',
        replacement="",
        target="tests/test_eval_extraction_harness.py",
        keyword="persists_the_breakdown",
        tags=("honesty",),
    ),
    # ---- from B193_PAIRING ------------------------------------------------
    #: Master order B4, issue #193: pairing measured against gold and made
    #: precise. Phase 58.
    Mutation(
        id="M480", phase=58,
        description="the extraction scorer counts superseded rows again, so "
                    "every re-read field is scored twice (#193, audit 52)",
        path=REPO / "scripts" / "eval_extraction.py",
        # Re-anchored 2026-09-25: the range-aware scorer prefixes this line
        # with the optional value_min/value_max columns, so "FROM" now
        # carries a leading space inside the string literal.
        anchor='        " FROM submittal_facts WHERE submittal_document_id = ? " + current +\n',
        replacement='        " FROM submittal_facts WHERE submittal_document_id = ? " +\n',
        target=_SCORERS_TEST, keyword="eval_extraction",
        tags=("honesty",),
    ),
    # ---- from B4_PUMP_LAYOUTS ---------------------------------------------
    #: Master order B4: the pump datasheet's layout defects. Phase 59.
    Mutation(
        id="M485", phase=59,
        description="the extraction scorer compares the normalised name again, "
                    "so a correctly read field whose clause reference left the "
                    "name counts as missed (B4 measurement)",
        path=REPO / "scripts" / "eval_extraction.py",
        anchor='            "field_name": (r["field_label"] or r["field_name"] or "").strip(),\n',
        replacement='            "field_name": (r["field_name"] or r["field_label"] or "").strip(),\n',
        target="tests/test_scorers_read_current_facts.py", keyword="printed_label",
        tags=("honesty",),
    ),
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M525", phase=61,
        description="skip the range branch, so a correctly stored range "
                    "(value_min=5, value_max=150) is scored by raw-string "
                    "comparison against the gold '5 - 150' and reported as "
                    "a wrong value on every run (B4 s16.22 gap)",
        path=REPO / "scripts" / "eval_extraction.py",
        anchor="    if g_range is not None or e_range is not None:\n"
               "        return ranges_agree(gold, got, g_range, e_range)",
        replacement="    if False:\n"
                    "        return ranges_agree(gold, got, g_range, e_range)",
        target="tests/test_eval_extraction_harness.py",
        keyword="a_stored_range_matches_the_gold_range",
        tags=("honesty", "scorer"),
    ),
    Mutation(
        id="M526", phase=61,
        description="compare only the LOW bound of a range, so '5 - 120' is "
                    "credited against a gold '5 - 150'",
        path=REPO / "scripts" / "eval_extraction.py",
        anchor="        if (_within(g_lo.normalized_value, e_lo.normalized_value)\n"
               "                and _within(g_hi.normalized_value, e_hi.normalized_value)):",
        replacement="        if _within(g_lo.normalized_value, e_lo.normalized_value):",
        target="tests/test_eval_extraction_harness.py",
        keyword="a_range_with_a_different_bound_is_a_wrong_value",
        tags=("honesty", "scorer"),
    ),
)
