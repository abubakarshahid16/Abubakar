"""Order 139 part 2 (spec a, c, d): ONE COMMENT PER DATASHEET FIELD, one
grouping for the screen and the file. `crs_mapping.py` is in the danger zone
(rule 6). PR #1179."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_mapping.py"
_T = "tests/test_139_crs_one_per_field.py"
_TAGS = ("honesty", "critical")
_FIELD_BRANCH = '    if label:\n        return ("field", bucket, label)\n'


def _m(
    n: str, description: str, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1179-{n}",
        phase=1179,
        description=description,
        path=_M,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a field's blanks are one row per clause again (the field branch never taken)",
        _FIELD_BRANCH,
        '    if False:\n        return ("field", bucket, label)\n',
        "one_row_per_datasheet_field",
    ),
    _m(
        "02",
        "the bucket is left out of the field key: a blank and a not-found of one field "
        "share one number and one screen row",
        '    return comment_key("field group", bucket, label)\n',
        '    return comment_key("field group", label)\n',
        "blank_and_not_found_stay_separate_rows",
    ),
    _m(
        "03",
        "findings with no field label are grouped as one field",
        _FIELD_BRANCH,
        '    if label or bucket in FIELD_GROUPED_BUCKETS:\n        return ("field", bucket, label)\n',
        "rows_without_a_field_label_keep_one_per_requirement",
    ),
    _m(
        "04",
        "breaches are merged per field, hiding each clause's own limit and deviation",
        "FIELD_GROUPED_BUCKETS = (BUCKET_BLANK, BUCKET_NOT_FOUND, BUCKET_QUESTION)\n",
        "FIELD_GROUPED_BUCKETS = (BUCKET_BLANK, BUCKET_NOT_FOUND, BUCKET_QUESTION, BUCKET_BREACH)\n",
        "breaches_stay_one_row_per_problem",
    ),
    _m(
        "05",
        "a field row does not list the clauses behind it",
        '        return "\\n".join([group_action(group), said, *clause_lines])\n',
        '        return "\\n".join([group_action(group), said])\n',
        "grouped_comment_lists_supporting_clauses",
    ),
    _m(
        "06",
        "the clause list is not capped",
        '    lines = [f"Supporting clauses ({n}):", *(e[2] for e in entries[:MAX_CLAUSE_LINES])]\n',
        '    lines = [f"Supporting clauses ({n}):", *(e[2] for e in entries)]\n',
        "long_clause_list_says_how_many_more",
    ),
    _m(
        "10",
        "a field row is keyed on its leading clause, so a re-run adding a clause "
        "renumbers it",
        '    if key[0] == "field":\n        return field_comment_key(key[1], key[2])\n'
        "    return _subject_key(f)\n",
        "    return _subject_key(f)\n",
        "field_row_number_key_survives_a_new_clause",
    ),
    _m(
        "11",
        "different engineer wordings of one field merge into one row",
        "            if len(wordings[base[id(f)]]) > 1\n",
        "            if False\n",
        "different_engineer_wordings_split_same_wording_stays_one",
    ),
    _m(
        "12",
        "a field row carries only its leader's per-clause key",
        '                "member_keys": sorted({finding_member_key(g) for g in group}),\n',
        '                "member_keys": [finding_member_key(f)],\n',
        "a_field_row_carries_every_member_key",
    ),
    _m(
        "14",
        "a clause list over the cap does not say how many more there are",
        "    if n > MAX_CLAUSE_LINES:\n",
        "    if False:\n",
        "long_clause_list_says_how_many_more",
    ),
    _m(
        "15",
        "the leader of a field row depends on the order the findings arrive in",
        '        _clause_key(f.get("standard_clause")),\n'
        '        _fold(f.get("requirement_source_text")),\n'
        '        str(f.get("id") or ""),\n'
        "    )\n",
        "    )\n",
        "leader_is_the_same_whatever_the_input_order",
    ),
    _m(
        "16",
        "a rejected finding's old per-clause number is not withdrawn",
        "    return {finding_comment_key(f) for f in rejected} | {\n"
        "        finding_member_key(f) for f in rejected\n"
        "    }\n",
        "    return {finding_comment_key(f) for f in rejected} | set()\n",
        "rejected_comment_keys_include_member_keys",
    ),
    _m(
        "17",
        "a field row of one clause loses today's sentence",
        "    if not _is_field_row(group) or point_count(group) < 2:\n",
        "    if not _is_field_row(group) or point_count(group) < 1:\n",
        "single_clause_row_text_is_unchanged",
    ),
    _m(
        "18",
        "rule 4: two questions of one clause on one field print only the first one's words",
        "    if not _is_field_row(group) or point_count(group) < 2:\n",
        "    if not _is_field_row(group) or clause_count(group) < 2:\n",
        "one_row_never_hides_a_second_question",
    ),
    _m(
        "19",
        "rule 4: a clause line says only its first requirement or reason",
        '        words = " ".join(dict.fromkeys(_point_words(m, question) for m in members))\n',
        "        words = _point_words(g, question)\n",
        "one_row_never_hides_a_second_question",
    ),
    Mutation(
        id="M1179-20",
        phase=1179,
        description="a CLOSED old per-clause number counts as still on the sheet and confirms the field row",
        path=APP / "main.py",
        anchor='            and records[k].get("status") == crs_numbers_mod.OPEN\n',
        replacement='            and records[k].get("status") != crs_numbers_mod.WITHDRAWN\n',
        target="tests/test_139_crs_numbers_merge.py",
        keyword="closed_old_number",
        tags=_TAGS,
    ),
)
