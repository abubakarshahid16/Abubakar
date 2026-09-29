"""Mutations of `backend/app/field_links.py`.

CRS quick wins (2026-09-27, audit crs.md defect 3): synonym rewriting,
nozzle-mark fields, and closed categorical comparison.
"""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1305", phase=96,
        description="the synonym table is never consulted, so a clause's "
                    "words and a datasheet's own spelling of the same "
                    "quantity never fold to the same phrase",
        path=APP / "field_links.py",
        anchor="    folded = _fold(text)\n    pattern, to_canonical, _attributes = _table()\n"
              "    if not folded or pattern is None:\n        return folded\n"
              "    return pattern.sub(lambda m: to_canonical[m.group(0)], folded)",
        replacement="    return _fold(text)",
        target="tests/test_field_links.py",
        keyword="test_synonym_is_rewritten_to_its_canonical_phrase",
        tags=("honesty",),
    ),
    Mutation(
        id="M1306", phase=96,
        description="a nozzle-mark field name is never read as the nozzle's "
                    "attribute, so 'N3 SIZE' never meets a clause about "
                    "'nozzle size'",
        path=APP / "field_links.py",
        anchor='    match = _NOZZLE_MARK.match(folded)\n    _pattern, _to, attributes = _table()\n'
              '    if match and match.group("attr") in attributes:\n'
              '        return canonical(f"nozzle {match.group(\'attr\')}"), f"N{match.group(\'mark\').upper()}"\n',
        replacement="",
        target="tests/test_field_links.py",
        keyword="test_nozzle_mark_field_reads_as_the_nozzle_attribute_with_its_item",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1307", phase=96,
        description="a flange-class requirement ('minimum ... Class 300') "
                    "is never recognised as a categorical rule",
        path=APP / "field_links.py",
        anchor='    if "flange rating" in folded or re.search(r"\\bflanges?\\b", sentence, re.IGNORECASE):\n',
        replacement='    if False:\n',
        target="tests/test_field_links.py",
        keyword="test_flange_class_requirement_is_read_as_a_minimum or test_cl150_fails_a_minimum_class_300_requirement",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1308", phase=96,
        description="a categorical comparison always reports COMPLIANT, "
                    "regardless of the datasheet's answer",
        path=APP / "field_links.py",
        # Re-anchored 2026-09-30 (audit): five operators now; ok is forced
        # after they are all computed.
        anchor='    shown = " ".join((provided or "").split())\n    required = {',
        replacement='    ok = True\n    shown = " ".join((provided or "").split())\n    required = {',
        target="tests/test_field_links.py",
        keyword="test_cl150_fails_a_minimum_class_300_requirement",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1309", phase=96,
        description="a conditional categorical clause is decided as a "
                    "verdict instead of left as an engineer's question",
        path=APP / "field_links.py",
        anchor='    if rule.get("condition"):\n        return {"status": "NEEDS_ENGINEER_REVIEW",\n',
        replacement='    if False:\n        return {"status": "NEEDS_ENGINEER_REVIEW",\n',
        target="tests/test_field_links.py",
        keyword="test_a_conditional_categorical_clause_is_a_question_never_a_verdict",
        tags=("honesty", "critical"),
    ),
)
