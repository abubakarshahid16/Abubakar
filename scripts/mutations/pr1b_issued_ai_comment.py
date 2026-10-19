"""Release 1b (cloud's danger-zone review of #1178): an issued AI/web comment
stays on a later run's contractor copy, and an issued number with no stored
wording is counted and named, never dropped unseen. `crs_mapping.py`,
`crs_export.py` and `crs_issue.py` are in the danger zone (rule 6). Ids
M1b1-01.. (the integrator renames them to the PR number, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "crs_mapping.py"
_E = APP / "crs_export.py"
_I = APP / "crs_issue.py"
_MAIN = APP / "main.py"
_T = "tests/test_1b_issued_ai_comment.py"
_TAGS = ("honesty", "critical")


def _m(n: str, desc: str, path, anchor: str, repl: str, kw: str) -> Mutation:
    return Mutation(
        id=f"M1b1-{n}",
        phase=1001,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the issue copy drops every row holding a draft again, even one whose "
        "number is issued (the comment vanishes from the contractor copy)",
        _E,
        "        findings = [f for f in findings\n"
        '                    if f.get("engineer_confirmed") is True\n',
        "        findings = [f for f in findings\n"
        '                    if not str(f.get("ai_review_comment") or "").strip()\n'
        '                    and f.get("engineer_confirmed") is True\n',
        "issued_ai_comment_stays_on_a_later_runs_contractor_copy",
    ),
    _m(
        "02",
        "a waiting sentence beside a draft counts as issuable text on the "
        "issue copy (the export counts and drops by the old test)",
        _E,
        "        withheld_no_text = sum(1 for f in findings if _no_issuable_text(f))\n"
        "        findings = [f for f in findings if not _no_issuable_text(f)]\n",
        "        withheld_no_text = sum(1 for f in findings if _no_text(f))\n"
        "        findings = [f for f in findings if not _no_text(f)]\n",
        "waiting_sentence_is_counted_not_issued",
    ),
    _m(
        "03",
        "the issue gate skips a confirmed row that holds a draft (the old "
        "blind spot: nothing counts the missing comment)",
        _I,
        "        and row_has_no_issuable_text(row)\n    )",
        '        and not str(row.get("ai_review_comment") or "").strip()\n'
        "        and row_has_no_issuable_text(row)\n    )",
        "issued_number_with_no_stored_wording_is_counted_and_blocks",
    ),
    _m(
        "04",
        "a draft re-raised under an issued number keeps its waiting sentence "
        "(the stored words are not carried)",
        _M,
        '    if not str(row.get("ai_review_comment") or "").strip():\n        return\n'
        '    words = str(snapshot.get("comment") or "").strip()\n',
        '    return\n    words = str(snapshot.get("comment") or "").strip()\n',
        "issued_ai_comment_stays_on_a_later_runs_contractor_copy",
    ),
    _m(
        "05",
        "a waiting sentence stored by the old overwrite is carried as the "
        "engineer's words",
        _M,
        '    if words in WAITING_COMMENTS:\n        words = ""\n',
        "",
        "waiting_sentence_stored_by_the_old_overwrite_is_never_issued",
    ),
    _m(
        "06",
        "a waiting sentence beside a draft is issuable text to the gate and the export",
        _M,
        "    return row_has_no_text(row) or (\n"
        '        str(row.get("comment") or "").strip() in WAITING_COMMENTS\n    )\n',
        "    return row_has_no_text(row)\n",
        "confirmed_row_with_a_draft_and_a_waiting_sentence",
    ),
    _m(
        "07",
        "the blocker no longer names the comment numbers",
        _I,
        '    named = ", ".join(refs)\n',
        "    named = str(len(refs))\n",
        "blocker_names_every_comment",
    ),
    _m(
        "08",
        "the gate names a numbered row by its position instead of its number",
        _I,
        '        str(row.get("crs_ref") or f"on row {n}")\n',
        '        f"on row {n}"\n',
        "carried_forward_comment_saved_empty_is_named_by_the_gate",
    ),
    _m(
        "09",
        "a numbered row with no text says the old 'An engineer must write it' "
        "sentence again, naming no comment",
        _E,
        "    if crs_ref:\n        return EMPTY_ISSUED_COMMENT_TEXT.format(ref=crs_ref)\n",
        "    if False and crs_ref:\n        return EMPTY_ISSUED_COMMENT_TEXT.format(ref=crs_ref)\n",
        "carried_forward_comment_saved_empty_is_named_by_the_gate",
    ),
    _m(
        "10",
        "the composition no longer carries an issued number's words onto a "
        "re-raised draft",
        _MAIN,
        "            crs_mapping_mod.carry_issued_wording(row, record)\n",
        "",
        "internal_copy_does_not_say_not_issued_beside_an_issued_number",
    ),
    _m(
        "11",
        "the issued byline is not carried with the issued words",
        _M,
        '    if words and by:\n        row["comment_by"] = by\n',
        "",
        "issued_ai_comment_stays_on_a_later_runs_contractor_copy",
    ),
)
