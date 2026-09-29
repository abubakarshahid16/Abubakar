"""Audit 2026-09-30: CRS and comparison-engine defects (M1430-M1449).

Each entry deletes one fix; the named tests in
`backend/tests/test_audit_crs_fixes.py` must fail.
"""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_audit_crs_fixes.py"
_CMP = APP / "comparison.py"
_FL = APP / "field_links.py"
_P = 1430

MUTATIONS: tuple[Mutation, ...] = (
    # 1. equipment-specific exceptions reach production
    Mutation(id="M1430", phase=_P, description="run_comparison passes no equipment subject",
             path=_CMP,
             anchor="    if subject is None:\n        subject = equipment_subject(stored)\n",
             replacement="",
             target=_T, keyword="psv_sheet_gets_the_psv_exception", tags=("honesty", "critical")),
    Mutation(id="M1431", phase=_P, description="a generic subject borrows a narrower exception",
             path=_CMP, anchor="            if a and b and b <= a:\n",
             replacement="            if a and b and (b <= a or a <= b):\n",
             target=_T, keyword="generic_subject_never_borrows", tags=("honesty",)),
    # 2. categorical clauses
    Mutation(id="M1432", phase=_P, description="'Class 150 or Class 300' is read as the first class only",
             path=_FL, anchor="        ok = got in rule[\"value\"]\n",
             replacement="        ok = got == rule[\"value\"][0]\n",
             target=_T, keyword="alternatives_ceilings_and_prohibitions", tags=("honesty",)),
    Mutation(id="M1433", phase=_P, description="'shall not exceed Class 600' is read as must-equal",
             path=_FL, anchor="            return \"<=\", number, shown\n",
             replacement="            return \"==\", number, shown\n",
             target=_T, keyword="alternatives_ceilings_and_prohibitions", tags=("honesty",)),
    Mutation(id="M1434", phase=_P, description="'Class 150 shall not be used' is read as must-equal 150",
             path=_FL, anchor="            return \"!=\", number, shown\n",
             replacement="            return \"==\", number, shown\n",
             target=_T, keyword="alternatives_ceilings_and_prohibitions", tags=("honesty",)),
    Mutation(id="M1435", phase=_P, description="'not required' is read as a requirement",
             path=_FL, anchor="    if _NOT_REQUIRED.search(sentence):\n        return None\n",
             replacement="",
             target=_T, keyword="not_required_is_no_requirement", tags=("honesty", "critical")),
    Mutation(id="M1436", phase=_P, description="an unrecognised negation on a flange clause is ignored",
             path=_FL,
             anchor="        if _NEGATION.search(sentence):\n            return None\n        return (\">=\"",
             replacement="        return (\">=\"",
             target=_T, keyword="unrecognised_negation", tags=("honesty",)),
    # 3. common-section fields
    Mutation(id="M1437", phase=_P, description="untagged fields count as missing for every tag",
             path=APP / "datasheet_checks.py",
             anchor="            if not found and (shared_section or (tag is not None and common.get(role))):\n",
             replacement="            if False:\n",
             target=_T, keyword="untagged_fields_count", tags=("honesty",)),
    Mutation(id="M1438", phase=_P, description="one tag's value is lent to every other tag",
             path=APP / "datasheet_checks.py",
             anchor="    common = by_tag.get(None, {})\n",
             replacement=("    common = {k: v for roles_ in by_tag.values()"
                          " for k, v in roles_.items()}\n"),
             target=_T, keyword="never_lent_to_another_tag", tags=("honesty", "critical")),
    # 4. "Label : value" one per line
    Mutation(id="M1439", phase=_P, description="a 'Label : value' line is paired with the next line",
             path=APP / "datasheets.py", anchor="            own = _self_contained_pair(line)\n",
             replacement="            own = None\n",
             target=_T, keyword="one_field_per_line", tags=("critical",)),
    # 5. export safety and a truthful rationale
    Mutation(id="M1440", phase=_P, description="a string beginning '=' is written as a formula",
             path=APP / "crs_export.py", anchor="        cell.data_type = \"s\"\n",
             replacement="        pass\n",
             target=_T, keyword="formula_text", tags=("security", "critical")),
    Mutation(id="M1441", phase=_P, description="a control character fails the whole export",
             path=APP / "crs_export.py",
             anchor="    return ILLEGAL_CHARACTERS_RE.sub(\" \", value)\n",
             replacement="    return value\n",
             target=_T, keyword="control_character", tags=("critical",)),
    Mutation(id="M1442", phase=_P, description="an unreadable value is blamed on two identical units",
             path=_CMP,
             anchor="    if verdict is None and (claims.parse_value(str(observed.raw_value or \"\")) is None\n",
             replacement="    if False and (claims.parse_value(str(observed.raw_value or \"\")) is None\n",
             target=_T, keyword="unreadable_value", tags=("honesty",)),
    # low-trust values
    Mutation(id="M1443", phase=_P, description="a breach on an untrusted value is stated as a breach",
             path=_CMP, anchor="    reason = low_trust_reason(fact)\n",
             replacement="    reason = None\n",
             target=_T, keyword="untrusted_value or low_confidence_fact", tags=("honesty", "critical")),
    # 7. (numbered here for id order) a withdrawn number never confirms a draft
    Mutation(id="M1444", phase=_P, description="a withdrawn number marks a re-raised draft as confirmed",
             path=APP / "main.py",
             anchor="        if key in numbered and numbered[key].get(\"status\") == crs_numbers_mod.WITHDRAWN:\n",
             replacement="        if False:\n",
             target=_T, keyword="raised_again_by_a_new_run", tags=("honesty", "critical")),
    # 6. re-runs keep engineer decisions
    Mutation(id="M1445", phase=_P, description="a re-run deletes a rejected or accepted finding",
             path=APP / "review.py",
             anchor=("UNDECIDED_SQL = (\"(confirmed_by IS NULL AND approved_by IS NULL\"\n"
                     "                 \" AND COALESCE(approval_status, 'pending') = 'pending'\"\n"
                     "                 \" AND disposition IS NULL AND engineer_comment IS NULL)\")\n"),
             replacement="UNDECIDED_SQL = \"(confirmed_by IS NULL)\"\n",
             target=_T, keyword="rejection_survives or acceptance_survives", tags=("honesty", "critical")),
    Mutation(id="M1446", phase=_P, description="a re-run proposes a rejected pair again as a draft",
             path=_CMP,
             anchor=("            if (requirement.get(\"id\"), (fact or {}).get(\"id\")) in rejected_pairs:\n"
                     "                continue\n"),
             replacement="",
             target=_T, keyword="rejection_survives", tags=("honesty",)),
    # 7. a rejected comment is never issued
    Mutation(id="M1447", phase=_P, description="a confirmed-then-rejected number is not withdrawn",
             path=APP / "main.py", anchor="        if meta.get(\"rejected_row_keys\"):\n",
             replacement="        if False:\n",
             target=_T, keyword="confirmed_then_rejected", tags=("honesty", "critical")),
    Mutation(id="M1448", phase=_P, description="confirming a withdrawn comment again does not re-open it",
             path=APP / "crs_numbers.py",
             anchor="                (OPEN, user_id, _now(), scope_key, key, WITHDRAWN)).rowcount\n",
             replacement="                (WITHDRAWN, user_id, _now(), scope_key, key, WITHDRAWN)).rowcount\n",
             target=_T, keyword="confirmed_then_rejected", tags=("honesty",)),
    Mutation(id="M1449", phase=_P, description="a confirmed comment is signed with the raw user id",
             path=APP / "main.py",
             anchor="    confirmers = {f[\"confirmed_by\"] for f in findings if f.get(\"confirmed_by\")}\n",
             replacement=("    confirmers = {f[\"confirmed_by\"] for f in findings if f.get(\"confirmed_by\")"
                          " and f.get(\"origin\")}\n"),
             target=_T, keyword="signed_with_the_engineers_name", tags=("honesty",)),
)
