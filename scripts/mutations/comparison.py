"""Mutations of `backend/app/comparison.py`."""

from __future__ import annotations

from ._base import (
    APP,
    TAG_IN_KEY,
    TAG_SCOPED,
    _B18_GUARD,
    _B3_TEST,
    _B40_TEST,
    Mutation,
)


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_5B ----------------------------------------------------
    #: Phase 5B: the compliance comparison engine. `phase=7` because the lower
    #: numbers are taken; the ids are the stable handle.
    Mutation(
        id="M64", phase=7,
        description="stop comparing numbers, so a breach is never caught",
        path=APP / "comparison.py",
        anchor="    verdict = claims._compatible(observed, limit)",
        replacement="    verdict = True",
        target="tests/test_comparison.py",
        keyword="numeric_breach_is_caught",
        tags=("deterministic",),
    ),
    Mutation(
        id="M65", phase=7,
        description="drop the exception, reporting a false breach against a "
                    "compliant PSV",
        path=APP / "comparison.py",
        anchor="    exception = _applicable_exception(requirement, subject)",
        replacement="    exception = None",
        target="tests/test_comparison.py",
        keyword="psv_at_108_db_is_compliant",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M66", phase=7,
        description="turn a blank By-Contractor field into NON_COMPLIANT",
        path=APP / "comparison.py",
        anchor='            "status": MISSING_INFORMATION,\n            "rationale": f"the submittal leaves this field to be provided ({marker})",',
        replacement='            "status": NON_COMPLIANT,\n            "rationale": f"the submittal leaves this field to be provided ({marker})",',
        target="tests/test_comparison.py",
        keyword="blank_by_contractor_field_is_missing_information",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M67", phase=7,
        description="store a finding whose citations do not resolve",
        path=APP / "comparison.py",
        anchor="    if unresolved:\n        status = NEEDS_ENGINEER_REVIEW",
        replacement="    if False:\n        status = NEEDS_ENGINEER_REVIEW",
        target="tests/test_comparison.py",
        keyword="citation_does_not_resolve or another_document",
        tags=("citation",),
    ),
    Mutation(
        id="M68", phase=7,
        description="guess a comparison when the units cannot be compared",
        path=APP / "comparison.py",
        anchor="    if verdict is None:\n        return {\n            \"status\": NEEDS_ENGINEER_REVIEW,",
        replacement="    if verdict is None:\n        verdict = True\n    if False:\n        return {\n            \"status\": NEEDS_ENGINEER_REVIEW,",
        target="tests/test_comparison.py",
        keyword="unknown_unit_yields_no_comparison",
        tags=("honesty", "unit"),
    ),
    Mutation(
        id="M69", phase=7,
        description="let the model overrule the deterministic comparison",
        path=APP / "comparison.py",
        anchor="    if not model_opinion or model_opinion == deterministic:\n        return deterministic, None\n    return deterministic, (",
        replacement="    if not model_opinion or model_opinion == deterministic:\n        return deterministic, None\n    return model_opinion, (",
        target="tests/test_comparison.py",
        keyword="model_disagreeing_does_not_change",
        tags=("section14", "critical"),
    ),
    Mutation(
        id="M70", phase=7,
        description="approve a review that examined a fraction of the fields",
        path=APP / "comparison.py",
        anchor='    if not completeness.get("sufficient"):',
        replacement="    if False:",
        target="tests/test_comparison.py",
        keyword="low_completeness_forces_manual_review",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M71", phase=7,
        description="allow a code override with no reason",
        path=APP / "comparison.py",
        anchor='    if recommended and code != recommended and not (override_reason or "").strip():',
        replacement="    if False:",
        target="tests/test_comparison.py",
        keyword="overriding_without_a_reason",
        tags=("audit",),
    ),
    Mutation(
        id="M72", phase=7,
        description="let completeness average instead of taking the weakest link",
        path=APP / "comparison.py",
        # Re-anchored 2026-09-24: the line lost its `if parts else None` tail
        # and moved one indent level, so the old anchor matched 0 times.
        anchor="        overall = round(min(parts), 3)",
        replacement="        overall = round(sum(parts) / len(parts), 3)",
        target="tests/test_comparison.py",
        keyword="weakest_link_not_the_average",
        tags=("honesty",),
    ),
    # ---- from MATCHER -----------------------------------------------------
    #: The containment matcher and the last of the datasheet recall fixes.
    Mutation(
        id="M112", phase=8,
        description="MATCH ON A SUBSTRING instead of whole words, so "
                    "'design pressure' matches inside 'redesign pressure'",
        path=APP / "comparison.py",
        anchor=r'    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None',
        replacement="    return needle in haystack",
        target="tests/test_containment_match.py",
        keyword="whole_words",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M113", phase=8,
        description="pick a candidate arbitrarily when two fields tie, instead "
                    "of refusing the match",
        path=APP / "comparison.py",
        anchor='    if len(best) > 1:',
        replacement="    if False:",
        target="tests/test_containment_match.py",
        keyword="genuine_tie_returns_no_match",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M114", phase=8,
        description="take the SHORTEST field name, pairing a requirement with "
                    "the least specific field named in it",
        path=APP / "comparison.py",
        # Re-anchored 2026-09-21: the match_rules integration (ba73a8c) now
        # takes the longest over the hits its rules ALLOWED, and the old
        # anchor on `hits` matched nothing - silently disarming this mutation.
        anchor='    longest = max(len(h["name"]) for h in allowed)',
        replacement='    longest = min(len(h["name"]) for h in allowed)',
        target="tests/test_containment_match.py",
        keyword="longest_field_name_wins",
    ),
    Mutation(
        id="M115", phase=8,
        description="let a CATEGORICAL fact match, reviving the insulation "
                    "false friend",
        path=APP / "comparison.py",
        anchor="        if not fact_has_number(fact):\n            continue",
        replacement="        if False:\n            continue",
        target="tests/test_containment_match.py",
        keyword="categorical_fact_never_matches",
        tags=("honesty",),
    ),
    Mutation(
        id="M116", phase=8,
        description="scope the matcher on the NORMALISED value, silently "
                    "excluding every unconvertible unit including dB(A)",
        path=APP / "comparison.py",
        anchor='    if requirement.get("raw_value") in (None, ""):\n        return none',
        replacement='    if requirement.get("value") is None:\n        return none',
        target="tests/test_containment_match.py",
        keyword="unit_cannot_be_converted_is_still_matched",
        tags=("critical",),
    ),
    # ---- from TABLE_AND_UNITS ---------------------------------------------
    #: Table rows, the dimension-aware unit guard, and the identifier rule.
    Mutation(
        id="M121", phase=8,
        description="let compare() treat a table row as a limit again",
        path=APP / "comparison.py",
        # ANCHORED ON THE SECOND LINE of the condition. The first ends in a
        # backslash continuation, and every attempt to carry that through a
        # string literal produced an anchor that did not match the file -
        # which the harness reported as "matched 0 times" rather than as a
        # pass. Disabling the fact half disables the branch just as well.
        # NOW ALSO CARRYING THE TYPE, because the relative-limit branch added
        # in the next task repeats this line verbatim and the anchor started
        # matching twice - reported as a harness error, which is what it was:
        # the mutation did not run and proved nothing either way.
        anchor=('    if requirement.get("requirement_type") == '
                'requirements_3b.TABLE_ROW \\\n'
                '            and fact is not None and not fact.get("is_blank"):'),
        replacement="    if False:",
        target="tests/test_table_row_requirements.py",
        keyword="compare_refuses_a_table_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M122", phase=8,
        description="drop the row text from the finding, leaving a verdict "
                    "with no way to see the table",
        path=APP / "comparison.py",
        anchor='                f"The row reads: {fragment}"),',
        replacement='                ""),',
        target="tests/test_table_row_requirements.py",
        keyword="quotes_the_row",
    ),
    Mutation(
        id="M123", phase=8,
        description="compare units by SPELLING only, refusing a kPa rule "
                    "against a bar value the engine can convert",
        path=APP / "comparison.py",
        anchor="    if both_normalised:",
        replacement="    if False:",
        target="tests/test_table_row_requirements.py",
        keyword="kpa_rule_and_a_bar_value",
    ),
    Mutation(
        id="M124", phase=8,
        description="compare units by DIMENSION always, so dB(A) and dB - "
                    "which share no dimension - are treated as the same unit",
        path=APP / "comparison.py",
        anchor="    return claims.same_unit(requirement_unit, fact_unit)",
        replacement="    return True",
        target="tests/test_table_row_requirements.py",
        keyword="weighted_unit_and_an_unweighted_one or unconvertible_pair",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M127", phase=8,
        description="present the nominal field denominator as a measured count",
        path=APP / "comparison.py",
        anchor='                f"NOMINAL ESTIMATE of {total} ({pages} pages x "',
        replacement='                f"{total} ({pages} pages x "',
        target="tests/test_comparison.py",
        keyword="denominator",
        tags=("honesty",),
    ),
    # ---- from REACHABLE ---------------------------------------------------
    #: Findings a reviewer can reach, keep and correct.
    Mutation(
        id="M130", phase=8,
        description="DELETE CONFIRMED FINDINGS ON RE-RUN, destroying an "
                    "engineer's decision with a routine maintenance action",
        path=APP / "comparison.py",
        anchor='                "DELETE FROM review_findings WHERE review_run_id = ?"\n                " AND confirmed_by IS NULL",',
        replacement='                "DELETE FROM review_findings WHERE review_run_id = ?",',
        target="tests/test_comparison.py",
        keyword="confirmed",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M131", phase=8,
        description="re-propose a pairing a human already rejected",
        path=APP / "comparison.py",
        # Re-anchored (B4 quality): match_by_field_name has the same line.
        anchor="        return none\n\n    rejected = _rejected_keys_for(requirement)",
        replacement="        return none\n\n    rejected = set()",
        target="tests/test_findings_reachable.py",
        keyword="rejected_pair_is_never_proposed_again",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M132", phase=8,
        description="let a rejection block every fact for that requirement, "
                    "not just the pair",
        path=APP / "comparison.py",
        # The FIRST version of this mutation broadened the SQL, which returns
        # more rejection ROWS without blocking more facts - the tests passed
        # and were right to. This one implements what the description claims.
        anchor='        if fact_key(fact, tag_scoped=tag_scoped) in rejected:',
        replacement="        if rejected:",
        target="tests/test_findings_reachable.py",
        keyword="does_not_block_another_fact",
    ),
    Mutation(
        id="M133", phase=8,
        description="overwrite an existing rejection, losing who refused the "
                    "pairing and why",
        path=APP / "comparison.py",
        anchor='            "INSERT OR IGNORE INTO review_pair_rejections"',
        replacement='            "INSERT OR REPLACE INTO review_pair_rejections"',
        target="tests/test_findings_reachable.py",
        keyword="keeps_the_first_decision",
    ),
    Mutation(
        id="M134", phase=8,
        description="KEY A REJECTION ON THE ROW ID, so an engineer's "
                    "correction stops applying at the next re-extraction",
        path=APP / "comparison.py",
        # A single-line, backslash-free slice. The function body contains
        # escaped quotes and a blank line, and carrying either through a
        # literal broke the file twice.
        anchor='        str(requirement.get("standard_document_id") or ""),',
        replacement='        str(requirement.get("id") or ""),',
        target="tests/test_comparison.py",
        keyword="survives_re_extraction",
        tags=("honesty", "critical"),
    ),
    # ---- from MODEL_TIER --------------------------------------------------
    #: The model tier of the matcher. It may CHOOSE, never NAME.
    Mutation(
        id="M135", phase=11,
        description="SHOW THE MODEL THE NUMBERS, so it can be pulled toward "
                    "whichever pairing makes the arithmetic come out",
        path=APP / "comparison.py",
        anchor="""        lines.append(f"{index}. {fact.get('field_name')}   (section: {section})")""",
        replacement="""        lines.append(f"{index}. {fact.get('field_name')} = {fact.get('raw_value')} {fact.get('raw_unit')}   (section: {section})")""",
        target="tests/test_model_matching.py",
        keyword="prompt_carries_no_value",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M158", phase=11,
        description="LET THE THINKING MODEL THINK, so Ollama answers into "
                    "`thinking` and every call reads as model_malformed",
        path=APP / "comparison.py",
        anchor='        "think": False,',
        replacement='        "think": True,',
        target="tests/test_model_matching.py",
        keyword="turns_thinking_off",
        tags=("critical",),
    ),
    Mutation(
        id="M136", phase=11,
        description="send the whole clause instead of 400 characters",
        path=APP / "comparison.py",
        anchor='        or requirement.get("requirement_text") or "").split())[:400]',
        replacement='        or requirement.get("requirement_text") or "").split())',
        target="tests/test_model_matching.py",
        keyword="capped_at_four_hundred",
    ),
    Mutation(
        id="M137", phase=11,
        description="OFFER CATEGORICAL AND BLANK FACTS as candidates, which is "
                    "how the insulation false friend reaches a model",
        path=APP / "comparison.py",
        anchor='        if not fact_has_number(fact) or fact.get("is_blank"):\n            continue\n        if not _units_comparable(',
        replacement='        if False:\n            continue\n        if not _units_comparable(',
        target="tests/test_model_matching.py",
        keyword="categorical_fact_never_enters or blank_fact_never_enters",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M138", phase=11,
        description="offer facts in ANY unit, so a length can be paired with a "
                    "pressure limit",
        path=APP / "comparison.py",
        anchor="        if not _units_comparable(requirement, fact,\n                                 requirement_unit, _unit_measure(fact)):\n            continue",
        replacement="        if False:\n            continue",
        target="tests/test_model_matching.py",
        keyword="another_dimension_never_enters",
        tags=("critical",),
    ),
    Mutation(
        id="M139", phase=11,
        description="compare unit SPELLINGS in the pre-filter, dropping the "
                    "kPa-against-bar pairing the engine can evaluate exactly",
        path=APP / "comparison.py",
        anchor='    if both_normalised:\n        left = claims.unit_dimension(requirement_unit.raw_unit or "")',
        replacement='    if False:\n        left = claims.unit_dimension(requirement_unit.raw_unit or "")',
        target="tests/test_model_matching.py",
        keyword="another_spelling_is_still_a_candidate",
    ),
    Mutation(
        id="M140", phase=11,
        description="let a pairing an engineer refused back into the model's "
                    "shortlist",
        path=APP / "comparison.py",
        anchor="    refused = _rejected_keys_for(requirement)",
        replacement="    refused = set()",
        target="tests/test_model_matching.py",
        keyword="rejected_pair_never_enters",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M141", phase=11,
        description="remove the candidate cap, so one prompt can carry every "
                    "numeric field on the sheet",
        path=APP / "comparison.py",
        anchor="    return out[:MAX_CANDIDATES]",
        replacement="    return out",
        target="tests/test_model_matching.py",
        keyword="capped_at_twelve",
    ),
    Mutation(
        id="M142", phase=11,
        description="PAIR A LONE CANDIDATE WITHOUT ASKING, turning 'only one "
                    "field was eligible' into a finding about the contractor",
        path=APP / "comparison.py",
        anchor="    candidates = candidate_facts(requirement, facts)\n    if not candidates:",
        replacement=(
            "    candidates = candidate_facts(requirement, facts)\n"
            "    if len(candidates) == 1:\n"
            "        only = candidates[0]\n"
            '        return {"fact": only, "matched_phrase": only.get("field_name"),\n'
            '                "method": METHOD_MODEL_CHOICE, "reason": "only candidate",\n'
            '                "candidates": []}\n'
            "    if not candidates:"),
        target="tests/test_model_matching.py",
        keyword="one_candidate_is_still_asked",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M143", phase=11,
        description="ACCEPT AN INDEX OUTSIDE THE SHORTLIST, letting a model "
                    "reach a fact that was never offered to it",
        path=APP / "comparison.py",
        anchor="    if choice.choice is not None and not 0 <= choice.choice < len(candidates):",
        replacement="    if choice.choice is not None and choice.choice >= len(candidates):",
        target="tests/test_model_matching.py",
        keyword="negative_index",
        tags=("critical",),
    ),
    Mutation(
        id="M144", phase=11,
        description="trust the index when the model's own sentence names a "
                    "DIFFERENT field - it may choose, never name",
        path=APP / "comparison.py",
        anchor="                return None, MODEL_NAMED_OTHER",
        replacement="                pass",
        target="tests/test_model_matching.py",
        keyword="naming_a_different_candidate",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M145", phase=11,
        description="ASK ONCE INSTEAD OF TWICE, so a coin toss becomes a finding",
        path=APP / "comparison.py",
        anchor="    second, reason = _ask_model_once(requirement, candidates)",
        replacement="    second, reason = first, None",
        target="tests/test_model_matching.py",
        keyword="disagree_make_no_pairing",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M146", phase=11,
        description="drop the per-run budget, so a pre-filter defect becomes "
                    "an unbounded number of model calls",
        path=APP / "comparison.py",
        anchor="    if budget is not None and budget.exhausted():\n        return _none_match(MODEL_BUDGET)\n    if budget is not None:\n        budget.spend()\n    first, reason",
        replacement="    if budget is not None:\n        budget.spend()\n    first, reason",
        target="tests/test_model_matching.py",
        keyword="budget",
    ),
    Mutation(
        id="M147", phase=11,
        description="ASK THE MODEL EVEN WHERE CONTAINMENT ALREADY DECIDED, "
                    "replacing evidence with a guess",
        path=APP / "comparison.py",
        anchor='        if (fact is None and match["reason"] != AMBIGUOUS_MATCH',
        replacement='        if (match["reason"] != AMBIGUOUS_MATCH',
        target="tests/test_model_matching.py",
        keyword="containment_takes_precedence",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M148", phase=11,
        description="HAND A TIE TO THE MODEL, replacing 'we could not tell' "
                    "with an answer nobody checked",
        path=APP / "comparison.py",
        anchor='and match["reason"] != AMBIGUOUS_MATCH\n',
        replacement='and match["reason"] != "no tie ever"\n',
        target="tests/test_model_matching.py",
        keyword="tie_never_reaches_the_model",
        tags=("honesty", "critical"),
    ),
    # M149 WAS WITHDRAWN, NOT SOLVED. It flipped a model-paired finding from
    # CONFIDENCE_MODEL_ASSISTED (0.5) to CONFIDENCE_DETERMINISTIC (0.9) and no
    # test could see it: `_confidence_label` has two bands and "high" is
    # forbidden, so 0.5 and 0.9 both print "medium", and the label is the only
    # confidence a finding stores. The design's §11 item - "confidence 0.5 and
    # label medium" - is therefore only half observable. What actually
    # distinguishes a model pairing on screen is `match_method` and the
    # rationale prefix, and those are M147 and M150. Recorded in
    # docs/status-honesty-audit.md rather than proved by a vacuous assertion.
    Mutation(
        id="M150", phase=11,
        description="drop the 'paired by model' prefix, so a guessed pairing "
                    "and a derived one read alike",
        path=APP / "comparison.py",
        anchor="""                f"{MODEL_PAIR_PREFIX}{match.get('reason') or ''}. \"""",
        replacement="""                f"{match.get('reason') or ''}. \"""",
        target="tests/test_model_matching.py",
        keyword="says_who_paired_it",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M151", phase=11,
        description="say nothing on the finding when the tier was off or the "
                    "model could not answer",
        path=APP / "comparison.py",
        anchor="        elif model_reason:",
        replacement="        elif False:",
        target="tests/test_model_matching.py",
        keyword="turned_off or unavailable_model_says_so or declined_pairing",
        tags=("honesty",),
    ),
    Mutation(
        id="M152", phase=11,
        description="IGNORE match_enabled, so the off switch does nothing",
        path=APP / "comparison.py",
        anchor="            if not settings.match_enabled:",
        replacement="            if False:",
        target="tests/test_model_matching.py",
        keyword="turned_off",
    ),
    Mutation(
        id="M155", phase=11,
        description="LET AN OUT-OF-SCOPE CALLER REJECT A PAIRING, and learn "
                    "the finding exists by the answer",
        # THE DENY IS LAYERED: the finding, the requirement and the fact are
        # each scoped, so neutralising one alone changes no answer - which is
        # the point of writing it three times. This mutates the deny itself,
        # where an empty grant set stops meaning nothing and starts meaning
        # everything (the deliverables.py defect, in this file).
        path=APP / "comparison.py",
        anchor='    if not allowed_document_ids:\n        return " WHERE 1 = 0", []',
        replacement='    if not allowed_document_ids:\n        return " WHERE 1 = 1", []',
        target="tests/test_model_matching.py",
        keyword="out_of_scope_caller",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M156", phase=11,
        description="record a rejection against a finding with no pairing, "
                    "which matches no pair and is never applied",
        path=APP / "comparison.py",
        anchor='    if not finding.get("requirement_id") or not finding.get("fact_id"):',
        replacement="    if False:",
        target="tests/test_model_matching.py",
        keyword="no_pairing_is_refused",
    ),
    Mutation(
        id="M157", phase=11,
        description="stop the rejection reaching the rejection writer, so the "
                    "correction loop is broken end to end",
        path=APP / "comparison.py",
        anchor="    return reject_pair(dict(requirement), dict(fact),",
        replacement="    return dict(finding) or reject_pair(dict(requirement), dict(fact),",
        target="tests/test_model_matching.py",
        keyword="stops_it_being_proposed_again",
    ),
    # ---- from GATE_FALLOUT ------------------------------------------------
    #: The three defects the model tier's failed gate exposed, plus the default
    #: it was turned off by.
    Mutation(
        id="M165", phase=12,
        description="PAIR AN APPLICABILITY TRIGGER, so its threshold is "
                    "compared as though it were a limit",
        path=APP / "comparison.py",
        anchor='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT})',
        replacement='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT,\n    requirements_3b.APPLICABILITY_TRIGGER})',
        target="tests/test_trigger_and_relative.py",
        keyword="outside_the_matcher",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M168", phase=12,
        description="COMPARE A RELATIVE LIMIT, producing arithmetic against a "
                    "number that is a margin and not a value",
        path=APP / "comparison.py",
        anchor="    if requirement.get(\"requirement_type\") == requirements_3b.RELATIVE_LIMIT \\\n            and fact is not None and not fact.get(\"is_blank\"):",
        replacement="    if False:",
        target="tests/test_trigger_and_relative.py",
        keyword="compare_refuses_a_relative_limit",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M169", phase=12,
        description="drop relative limits from the matcher, leaving the "
                    "refusal branch dead and every one of them missing "
                    "information",
        path=APP / "comparison.py",
        anchor='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT})',
        replacement='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW})',
        target="tests/test_trigger_and_relative.py",
        keyword="relative_limit_is_matchable",
    ),
    # ---- from RANGES_AND_COMPOUNDS ----------------------------------------
    #: Two numbers in one cell, and two fields in one label.
    Mutation(
        id="M191", phase=14,
        description="COMPARE A RANGE AT ITS MEAN, inventing a number the "
                    "document does not state",
        path=APP / "comparison.py",
        anchor='        chosen = spread[1] if side == "max" else spread[0]',
        replacement="        chosen = (spread[0] + spread[1]) / 2",
        target="tests/test_ranges_and_compounds.py",
        keyword="mean_of_a_range or upper_limit or lower_limit",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M192", phase=14,
        description="swap the ends, so an upper limit is judged against the "
                    "bottom of the band",
        path=APP / "comparison.py",
        anchor='    if operator in ("<=", "<"):\n        return "max"',
        replacement='    if operator in ("<=", "<"):\n        return "min"',
        target="tests/test_ranges_and_compounds.py",
        keyword="upper_limit_is_compared",
        tags=("critical",),
    ),
    Mutation(
        id="M193", phase=14,
        description="give an exact-equality rule an end of the range to "
                    "compare, answering a question nobody can answer",
        path=APP / "comparison.py",
        anchor='    if operator in (">=", ">"):\n        return "min"\n    return None',
        replacement='    if operator in (">=", ">"):\n        return "min"\n    return "max"',
        target="tests/test_ranges_and_compounds.py",
        keyword="exact_equality_rule",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M194", phase=14,
        description="let the matcher skip a range fact, leaving every range "
                    "unpaired and the comparison code dead",
        path=APP / "comparison.py",
        anchor='    return (fact.get("raw_value") not in (None, "")\n            or fact_range(fact) is not None)',
        replacement='    return fact.get("raw_value") not in (None, "")',
        target="tests/test_ranges_and_compounds.py",
        keyword="range_fact_can_be_matched",
        tags=("critical",),
    ),
    # ---- from EQUIPMENT_TAG -----------------------------------------------
    #: Which equipment a fact describes.
    Mutation(
        id="M204", phase=16,
        description="PUT THE TAG IN EVERY FACT KEY, retiring every rejection "
                    "ever recorded against a single-tag datasheet",
        path=APP / "comparison.py",
        anchor=TAG_SCOPED,
        replacement="    return True",
        target="tests/test_equipment_tag.py",
        keyword="single_tag_document_keeps_todays_key or survives_re_extraction",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M205", phase=16,
        description="leave the tag out of the key on a MULTI-tag sheet, so "
                    "rejecting one valve's field suppresses every valve's",
        path=APP / "comparison.py",
        anchor=TAG_IN_KEY,
        replacement="    if False:\n        parts.append(None)",
        target="tests/test_equipment_tag.py",
        keyword="rejecting_one_tag_does_not_suppress",
        tags=("critical",),
    ),
    Mutation(
        id="M206", phase=16,
        description="stamp a finding with a tag when there is no fact, "
                    "claiming the sheet said something it did not",
        path=APP / "comparison.py",
        anchor='        "equipment_tag": (fact or {}).get("equipment_tag"),',
        replacement='        "equipment_tag": (fact or {}).get("equipment_tag") or "unknown",',
        target="tests/test_equipment_tag.py",
        keyword="no_fact_names_no_equipment",
        tags=("honesty",),
    ),
    # ---- from REVIEW_GOVERNANCE -------------------------------------------
    #: A crashed run, and the engineer's final code (master plan section 15).
    Mutation(
        id="M211", phase=18,
        description="LET AN ENGINEER OVERRIDE THE RECOMMENDATION WITH NO "
                    "REASON, which is the whole of section 15's governance",
        path=APP / "comparison.py",
        anchor='    if recommended and code != recommended and not (override_reason or "").strip():',
        replacement="    if False:",
        target="tests/test_review_code.py",
        keyword="overriding_the_recommendation_requires_a_reason",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M212", phase=18,
        description="OVERWRITE THE RECOMMENDATION WITH THE DECISION, so no "
                    "reader can ever see what the machine itself said",
        path=APP / "comparison.py",
        anchor='            "UPDATE review_runs SET engineer_final_code = ?,"',
        replacement='            "UPDATE review_runs SET refusal_reason = NULL,"\n'
                    '            " engineer_final_code = ?,"',
        target="tests/test_review_code.py",
        keyword="recommendation_survives_the_decision",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M213", phase=18,
        description="accept any string at all as a review code",
        path=APP / "comparison.py",
        anchor="    if code not in DEFAULT_CODES:",
        replacement="    if False:",
        target="tests/test_review_code.py",
        keyword="not_a_review_code_is_refused",
    ),
    Mutation(
        id="M214", phase=18,
        description="RE-RUN A DECIDED RUN, leaving the engineer's code "
                    "attached to findings it was never made about",
        path=APP / "comparison.py",
        anchor='    if replace and run.get("engineer_final_code"):',
        replacement="    if False:",
        target="tests/test_review_code.py",
        keyword="re_running_a_decided_run_is_refused",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M215", phase=18,
        description="block EVERY re-run, not only a decided one, so no fix "
                    "can ever reach an existing run again",
        path=APP / "comparison.py",
        anchor='    if replace and run.get("engineer_final_code"):',
        replacement="    if replace:",
        target="tests/test_review_code.py",
        keyword="without_a_decision_still_re_runs or never_blocked_by_another_runs_decision",
    ),
    # ---- from CONDITION_AND_QUOTES ----------------------------------------
    #: B24 (the condition safety gate) and B23 (evidence quote validation), plus a
    #: re-anchoring of B20's dimension guard, so all three safety gates that came out
    #: of the Phase 0.5 slice are proven by this harness rather than by an ad-hoc
    #: script in one session's scratchpad.
    Mutation(
        id="M267", phase=29,
        description="remove the B24 condition gate, so a conditional "
                    "requirement reaches a verdict with its condition "
                    "unevaluated - the Phase 0.5 defect exactly",
        path=APP / "comparison.py",
        anchor="    condition = conditions.evaluate(requirement, submittal_facts)",
        replacement="    condition = None  # MUTANT: B24 gate removed",
        target="tests/test_condition_gate.py",
        tags=("honesty", "critical"),
    ),
    # ---- from B18_UNMEASURED_FACTOR ---------------------------------------
    #: B18: completeness dropped an UNMEASURED extraction factor and reported the
    #: other half alone - 1.0 and "sufficient" with the datasheet never measured.
    Mutation(
        id="M312", phase=35,
        description="comparison: drop the unmeasured extraction and score the "
                    "run on references alone - 1.0 and sufficient again",
        path=APP / "comparison.py",
        anchor=_B18_GUARD,
        replacement="    if False:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="unmeasured_extraction",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M314", phase=35,
        description="comparison: hide a measured 0 behind None because the "
                    "other factor is unknown",
        path=APP / "comparison.py",
        anchor=_B18_GUARD,
        replacement="    if extraction is None:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="measured_zero_stays",
        tags=("honesty",),
    ),
    # ---- from B9_NOT_IN_DOCUMENT_SCOPE ------------------------------------
    #: B9/B22: NOT_IN_DOCUMENT_SCOPE, rule R1 - an unmatched `statement` is not
    #: the contractor's omission, and must never approve a submittal either.
    Mutation(
        id="M320", phase=37,
        description="PUT B9 BACK: an unmatched statement is the contractor's "
                    "MISSING_INFORMATION again",
        path=APP / "comparison.py",
        anchor="        if requirement.get(\"requirement_type\") == requirements_3b.STATEMENT:",
        replacement="        if False:",
        target="tests/test_comparison.py",
        keyword="not_in_document_scope_not_missing",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M321", phase=37,
        description="an out-of-scope-only run falls through to APPROVED",
        path=APP / "comparison.py",
        anchor="    if out_of_scope:\n        return {\n            # NOT AN APPROVAL.",
        replacement="    if False:\n        return {\n            # NOT AN APPROVAL.",
        target="tests/test_comparison.py",
        keyword="never_approve",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M322", phase=37,
        description="count out-of-scope as the contractor's missing fields",
        path=APP / "comparison.py",
        anchor="    missing = [s for s in statuses if s == MISSING_INFORMATION]\n"
               "    # B9: counted APART",
        replacement="    missing = [s for s in statuses if s in (MISSING_INFORMATION, "
                    "NOT_IN_DOCUMENT_SCOPE)]\n    # B9: counted APART",
        target="tests/test_comparison.py",
        keyword="never_counted_as_the_contractors_omission",
        tags=("honesty",),
    ),
    Mutation(
        id="M325", phase=37,
        description="a generic manual flag instead of saying WHY: the reader "
                    "cannot tell other documents are needed",
        path=APP / "comparison.py",
        anchor='            "reason": (f"Manual review: {len(out_of_scope)} requirement"',
        replacement='            "reason": ("Manual review required"',
        target="tests/test_comparison.py",
        keyword="never_approve",
        tags=("honesty",),
    ),
    # ---- from B40_FACT_GUARD ----------------------------------------------
    #: B40 -> #179: `extract_facts(replace=True)` used to DELETE unconfirmed facts
    #: that findings cite by `fact_id` (B40 guarded it: count, record, refuse).
    #: Since #179 it SUPERSEDES them instead - the rows stay, marked
    #: `superseded_at`, and every reader of current facts leaves them out.
    #: M334-M336 keep their ids, re-anchored on the supersession; M440-M444 cover
    #: the readers and the record. Phase 56.
    Mutation(
        id="M444", phase=56,
        description="the tag-scoping query counts superseded rows' tags, so a "
                    "rejection is keyed on a tag no current fact carries (#179)",
        path=APP / "comparison.py",
        anchor='            " AND superseded_at IS NULL",           # current facts only (#179)',
        replacement='            "",',
        target=_B40_TEST, keyword="equipment_tag_scoping_ignores_superseded",
    ),
    # ---- from B163_EVIDENCE_TYPE_GATE -------------------------------------
    Mutation(
        id="M374", phase=48,
        description="drop the evidence-type gate: a numeric_limit clause "
                    "that names its own evidence (a certificate, a drawing) "
                    "reaches the arithmetic again and can be paired to an "
                    "unrelated datasheet field and read COMPLIANT/"
                    "NON_COMPLIANT for a document that was never reviewed",
        path=APP / "comparison.py",
        anchor="    required_evidence = requirement.get(\"required_evidence_type\")\n"
               "    if required_evidence and required_evidence != requirements_3b.DATA_SHEET_EVIDENCE:",
        replacement="    required_evidence = requirement.get(\"required_evidence_type\")\n"
                    "    if False:",
        target="tests/test_comparison.py",
        keyword="required_evidence_type_of_a_certificate_is_not_in_document_scope",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M375", phase=48,
        description="a requirement naming other evidence with NO paired "
                    "fact falls back to MISSING_INFORMATION - the wrong-"
                    "document case is misread as the contractor's omission",
        path=APP / "comparison.py",
        anchor="    required_evidence = requirement.get(\"required_evidence_type\")\n"
               "    if required_evidence and required_evidence != requirements_3b.DATA_SHEET_EVIDENCE:",
        replacement="    required_evidence = requirement.get(\"required_evidence_type\")\n"
                    "    if False:",
        target="tests/test_comparison.py",
        keyword="required_evidence_type_of_a_certificate_with_no_fact_is_not_missing_information",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M376", phase=48,
        description="run_comparison stops filtering out excluded standards, "
                    "so a requirement from a standard ruled inapplicable is "
                    "evaluated and can be reported COMPLIANT/NON_COMPLIANT "
                    "against a submittal it does not govern",
        path=APP / "comparison.py",
        anchor="    applicable = submittal_review.list_applicable_standards(\n"
               "        review_run_id, allowed_document_ids=allowed_document_ids,\n"
               "        include_excluded=False)",
        replacement="    applicable = submittal_review.list_applicable_standards(\n"
                    "        review_run_id, allowed_document_ids=allowed_document_ids,\n"
                    "        include_excluded=True)",
        target="tests/test_comparison.py",
        keyword="an_excluded_standards_requirements_produce_no_findings_at_all",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M377", phase=48,
        description="drop the duplicate-finding gate in create_finding, so a "
                    "second call for the same (review_run_id, requirement_id, "
                    "fact_id) silently writes a second unconfirmed row instead "
                    "of being refused (issue #164 criterion 3)",
        path=APP / "comparison.py",
        anchor="    if duplicate is not None:\n"
               "        raise ComparisonError(",
        replacement="    if False:\n"
                    "        raise ComparisonError(",
        target="tests/test_issue_164_verification_gates.py",
        keyword="test_criterion_3_a_duplicate_finding_for_the_same_pair_in_the_same_run_is_blocked",
        tags=("honesty", "critical"),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M451", phase=57,
        description="the review stops asking which pages were read, so 'no value "
                    "found' is the contractor's omission again (B3)",
        path=APP / "comparison.py",
        anchor="        if fact is None and verdict.get(\"status\") == MISSING_INFORMATION:\n"
               "            verdict = qualify_by_pages(verdict, pages_read)\n",
        replacement="",
        target=_B3_TEST, keyword="not_called_the_contractors_omission or decides_the_code",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M452", phase=57,
        description="an unread page no longer blocks the omission claim (B3)",
        path=APP / "comparison.py",
        anchor="    if unread:\n        return {**verdict, \"status\": NEEDS_ENGINEER_REVIEW,",
        replacement="    if False:\n        return {**verdict, \"status\": NEEDS_ENGINEER_REVIEW,",
        target=_B3_TEST, keyword="not_called_the_contractors_omission",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M453", phase=57,
        description="with no page accounted for at all, claim every page was "
                    "read (B3)",
        path=APP / "comparison.py",
        anchor="    if not total:\n        return {**verdict, \"status\": NEEDS_ENGINEER_REVIEW,",
        replacement="    if False:\n        return {**verdict, \"status\": NEEDS_ENGINEER_REVIEW,",
        target=_B3_TEST, keyword="no_page_accounted_for",
        tags=("honesty",),
    ),
    Mutation(
        id="M457", phase=57,
        description="the run forgets which pages it searched (B3)",
        path=APP / "comparison.py",
        anchor='                "page_coverage": page_coverage,\n',
        replacement="",
        target=_B3_TEST, keyword="keeps_the_page_coverage",
        tags=("honesty",),
    ),
    # #193 plan B4 (5.3): field-name pairing.
    Mutation(
        id='M590', phase=63,
        description='B4 5.3: a model-named pairing carries a COMPLIANT/NON_COMPLIANT verdict',
        path=APP / 'comparison.py',
        # Re-anchored (B4 quality): every status is now held.
        anchor='                       "status": NEEDS_ENGINEER_REVIEW,\n                       "rationale": (\n                           f"{FIELD_NAME_PAIR_PREFIX}',
        replacement='                       "status": status,\n                       "rationale": (\n                           f"{FIELD_NAME_PAIR_PREFIX}',
        target='tests/test_field_naming.py',
        keyword='never_carries_a_verdict',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M599', phase=63,
        description='B4 5.3: field-name equality pairing never pairs (requirement name ignored)',
        path=APP / 'comparison.py',
        anchor='    field = (names.get("requirements") or {}).get(str(requirement.get("id")))\n',
        replacement='    field = None\n',
        target='tests/test_field_naming.py',
        keyword='equal_field_names_pair',
        tags=('matching',),
    ),
    Mutation(
        id='M655', phase=64,
        description='B4 item 2: a blank field never pairs by field name',
        path=APP / 'comparison.py',
        anchor='            if (fact_has_number(f) or f.get("is_blank"))\n',
        replacement='            if fact_has_number(f)\n',
        target='tests/test_b4_quality.py', keyword='blank_field_pairs',
        tags=('matching',),
    ),
    Mutation(
        id='M656', phase=64,
        description='B4 item 2: among all-blank candidates the named field is not preferred',
        path=APP / 'comparison.py',
        anchor='            ordered = sorted(allowed, key=lambda f: (field not in own_names(f),\n',
        replacement='            ordered = sorted(allowed, key=lambda f: (False,\n',
        target='tests/test_b4_quality.py', keyword='all_blank_cites',
        tags=('matching',),
    ),
    Mutation(
        id='M657', phase=64,
        description='B4 item 2: a model-named blank pairing carries MISSING_INFORMATION unheld',
        path=APP / 'comparison.py',
        anchor=('            verdict = {**verdict,\n'
                '                       "status": NEEDS_ENGINEER_REVIEW,\n'
                '                       "rationale": (\n'
                '                           f"{FIELD_NAME_PAIR_PREFIX}'),
        replacement=('            verdict = {**verdict,\n'
                     '                       "status": (NEEDS_ENGINEER_REVIEW if status in '
                     '(COMPLIANT, NON_COMPLIANT) else status),\n'
                     '                       "rationale": (\n'
                     '                           f"{FIELD_NAME_PAIR_PREFIX}'),
        target='tests/test_b4_quality.py', keyword='blank_field_pairing_is_held',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M659', phase=64,
        description='B4 item 2: the unit guard overwrites a blank field\'s own answer',
        path=APP / 'comparison.py',
        anchor='        if (fact is not None and not fact.get("is_blank")\n',
        replacement='        if (fact is not None\n',
        target='tests/test_b4_quality.py', keyword='blank_field_pairing_is_held',
    ),
)
