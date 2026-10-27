"""Order 242.2 (PR 1342): a scope reading must be a real sentence, and a Part the
datasheet does not settle is one engineer question."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_242_scope_questions.py"
_Q = APP / "scope_quote.py"
_N = APP / "crs_no_field.py"
_T2 = "tests/test_245_no_field_answers.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1342-01",
        phase=1342,
        description="a garbled scope reading holds its Part again",
        path=APP / "ai_applicability.py",
        anchor="    if scope_quote.problems(\n",
        replacement="    if False and scope_quote.problems(\n",
        target=_T,
        keyword="garbled_scope_reading",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-02",
        phase=1342,
        description="every held requirement becomes its own question",
        path=APP / "ai_applicability.py",
        anchor='            questions.setdefault(key, question)["requirements"] += 1\n',
        replacement='            questions[(key, id(r))] = {**question, "requirements": 1}\n',
        target=_T,
        keyword="one_question_with_its_count",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-03",
        phase=1342,
        description="a quote that is cut off with an ellipsis still passes",
        path=_Q,
        anchor='    if not quote.endswith(_STOPS) or "..." in quote or "\u2026" in quote:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="fragment_is_not_a_scope_sentence",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-04",
        phase=1342,
        description="a run of codes passes as a sentence",
        path=_Q,
        anchor="    if _code_share(quote) > MAX_CODE_TOKEN_SHARE:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="fragment_is_not_a_scope_sentence",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-05",
        phase=1342,
        description="the question line is no longer printed",
        path=APP / "absence.py",
        anchor='    lines += scope_question_lines((split.get("division_scope") or {}).get("questions"))\n',
        replacement="",
        target=_T,
        keyword="one_line_in_the_review_notes",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-06",
        phase=1342,
        description="a requirement that names a datasheet field the sheet lacks loses its contractor row",
        path=_N,
        anchor="    return not_found_bucket if names_a_field(finding, _field_label) else None\n",
        replacement="    return None\n",
        target=_T2,
        keyword="names_a_field_the_sheet_lacks",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1342-07",
        phase=1342,
        description="a blank the sheet marks loses its contractor row",
        path=_N,
        anchor="    if has_field(finding):\n        return blank_bucket\n",
        replacement="    if False:\n        return blank_bucket\n",
        target=_T2,
        keyword="blank_the_sheet_marks",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1342-08",
        phase=1342,
        description="a datasheet check, AI item or chat comment is counted as no-field",
        path=_N,
        anchor='        and finding.get("origin") not in OTHER_ORIGINS\n',
        replacement="",
        target=_T2,
        keyword="other_kinds_of_finding",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-09",
        phase=1342,
        description="a rejected finding is counted in the grouped note",
        path=_N,
        anchor="        if _rejected(f) or not answered_by_no_field(f, _field_label):\n",
        replacement="        if not answered_by_no_field(f, _field_label):\n",
        target=_T2,
        keyword="other_kinds_of_finding",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-10",
        phase=1342,
        description="the requirements no field answers are in no row and in no note (hidden)",
        path=APP / "crs_mapping.py",
        anchor="    notes.extend(crs_no_field.notes(findings))\n",
        replacement="",
        target=_T2,
        keyword="counted_note",
        tags=("honesty", "critical"),
    ),
)
