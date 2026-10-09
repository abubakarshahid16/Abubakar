"""#678 "three honest groups instead of one 'not compared'": each entry deletes
one part; backend/tests/test_w3_678_three_way_split.py (or the screen's vitest
file) must notice."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w3_678_three_way_split.py"
_TAG = ("w3_678", "three_way_split")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


S = "requirement_split.py"
MUTATIONS: tuple[Mutation, ...] = (
    _m(4418, "the share is taken over requirements that do not apply too", S,
       '        "repeats_ignored": seen_rows - len(placed),\n        "unchecked_share": (n_not / applies) if applies else None,',
       '        "repeats_ignored": seen_rows - len(placed),\n        "unchecked_share": (n_not / (applies + n_na)) if applies else None,',
       "share"),
    _m(4419, "a repeated requirement is counted once per stored row", S,
       '    words = " ".join(table_gate.tokens(requirement.get("requirement_text")))\n',
       '    words = ""\n', "repeat"),
    _m(4420, "a requirement in two groups is counted in the weaker one", S,
       "_ORDER.index(group) < _ORDER.index(current[0])", "_ORDER.index(group) > _ORDER.index(current[0])",
       "strongest"),
    _m(4421, "the same text in two standards is one requirement", S,
       "    return f\"{requirement.get('standard_document_id') or ''}\\x00{words}\"",
       "    return f\"{words}\"", "two_standards"),
    _m(4422, "a missing reason is guessed", S,
       '    return REASON_TEXT.get(code or "", NO_REASON)', '    return REASON_TEXT.get(code or "", "no matching field")',
       "no_reason"),
    _m(4423, "a reason written in words is ignored", S,
       "    if detail and detail.strip():\n", "    if False:\n", "reasons"),
    _m(4424, "an old run's counts get no 'no reason recorded'", S,
       '"applies_not_checked_reasons": [{"reason": NO_REASON, "count": n_not}] if n_not else [],',
       '"applies_not_checked_reasons": [],', "old_run"),
    _m(4425, "a skipped cell does not know another row matched", "table_gate.py",
       '    if other_row_matched:\n        return "other_row_matched"\n', "", "reason_code"),
    _m(4426, "a skipped cell with a row label is not told apart", "table_gate.py",
       '    if _row_key(requirement):\n        return "row_label_not_on_sheet"\n', "", "reason_code"),
    _m(4427, "a skipped cell with nothing to match is called a column miss", "table_gate.py",
       '    return "no_label"\n', '    return "column_not_on_sheet"\n', "reason_code"),
    _m(4428, "a requirement for other equipment loses its reason", "subject_scope.py",
       "\"detail\": f\"about {label}, this submittal is {', '.join(sorted(equipment))}\"})",
       '"detail": ""})', "why_a_requirement_does_not_apply"),
    _m(4429, "the approval rule counts requirements that do not apply", "comparison.py",
       '    share = absence.unchecked_share(counts.get("not_compared", 0), counts.get("checked", 0))\n',
       '    share = absence.unchecked_share(counts.get("not_compared", 0) + counts.get("not_applied", 0), counts.get("checked", 0))\n',
       "approval_rule"),
    _m(4430, "a sheet is called incomplete because requirements do not apply", "absence.py",
       '    if sentence and counts.get("not_compared", 0):\n',
       '    if sentence and (counts.get("not_compared", 0) or counts.get("not_applied", 0)):\n', "incomplete"),
    _m(4431, "reason lines are counted as parts that could not be checked", "absence.py",
       '    parts = [p for p in parts if not p.get("detail")]\n', "    parts = list(parts)\n", "incomplete"),
    _m(4432, "the sheet lists every reason, not the top three", "absence.py",
       "        top = reasons[:3]\n", "        top = reasons\n", "top_three"),
    _m(4433, "the run does not store the split", "comparison.py",
       "                       unchecked_counts=unchecked_counts,\n                       requirement_split=split)",
       "                       unchecked_counts=unchecked_counts)", "stores"),
    _m(4434, "unreadable text is not counted as applies-but-not-checked", "comparison.py",
       '                held_items.append({"requirement": dict(r), "code": "text_quality"})\n', "",
       "unreadable_text"),
    _m(4435, "an old run shows no split", "main.py",
       '                              or requirement_split_mod.from_counts(outcome.get("unchecked_counts"))),',
       '                              or None),', "old_run"),
    Mutation(id="M4436", phase=4436, runner="vitest", description="the screen takes the share over all requirements",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="const applies = split.checked + split.applies_not_checked;",
             replacement="const applies = split.total;",
             target="src/views/ReviewRunsView.test.tsx", keyword="three groups", tags=_TAG),
    Mutation(id="M4437", phase=4437, runner="vitest", description="the screen shows 0% when no requirement applies",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="{split.unchecked_share !== null &&", replacement="{true &&",
             target="src/views/ReviewRunsView.test.tsx", keyword="three groups", tags=_TAG),
)
