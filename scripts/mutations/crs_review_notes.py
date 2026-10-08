"""Owner order 2f + 2e: Review notes sheet, same-rule merge, scope change."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1049", phase=88, description="the contractor's copy carries the internal Review notes",
             path=APP / "crs_export.py",
             anchor="            for n in (meta.get(\"review_notes\") or [])] if copy == COPY_INTERNAL else []),\n",
             replacement="            for n in (meta.get(\"review_notes\") or [])]),\n",
             target="tests/test_crs_review_notes.py", keyword="issue_copy_has_no_review_notes",
             tags=("crs", "critical")),
    Mutation(id="M1050", phase=88, description="requires-another-document notes are one per requirement, not per standard",
             path=APP / "crs_mapping.py",
             anchor='            name = str(f.get("standard_name") or f.get("standard_document_id") or "")\n',
             replacement='            name = str(f.get("id") or id(f))\n',
             target="tests/test_crs_mapping.py", keyword="review_note_by_standard", tags=("crs",)),
    Mutation(id="M1051", phase=88, description="the same rule from two standards prints as two comments",
             path=APP / "crs_mapping.py",
             # Re-anchored 2026-09-27 (CRS quick wins): `_group_key`.
             anchor="            f.get(\"origin\") == _DATASHEET_ORIGIN)\n",
             replacement="            f.get(\"origin\") == _DATASHEET_ORIGIN, id(f))\n",
             target="tests/test_crs_mapping.py", keyword="same_rule_from_two_standards", tags=("crs",)),
    Mutation(id="M1052", phase=88, description="the run no longer says which standards left scope",
             path=APP / "main.py",
             anchor='            "removed": sorted(before[k] for k in before.keys() - now.keys())}\n',
             replacement='            "removed": []}\n',
             target="tests/test_crs_review_notes.py", keyword="came_into_or_left_scope", tags=("ui",)),
    Mutation(id="M1053", phase=88, description="a cited standard not held is no longer noted",
             path=APP / "crs_mapping.py",
             anchor="    for ref in missing_references:\n        notes.append(",
             replacement="    for ref in ():\n        notes.append(",
             target="tests/test_crs_review_notes.py", keyword="holds_no_internal_note", tags=("crs", "honesty")),
    Mutation(id="M1054", phase=88, runner="vitest",
             description="the run card stops saying which standards left scope",
             path=FRONTEND_SRC / "components/review/reviewFormat.ts",
             anchor='  const parts = [part(change.removed, "removed"), part(change.added, "added")].filter(Boolean);\n',
             replacement='  const parts = [part(change.added, "added")].filter(Boolean);\n',
             target="src/components/review/reviewFormat.test.ts", keyword="why the in-scope count moved",
             tags=("ui",)),
)
