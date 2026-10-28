"""PR #803 (R30, #763): the reasoning behind every CRS row, internal copy
only. Danger zone: `crs_mapping` (the text) and `crs_export` (what leaves the
building - the issue copy must never carry the internal reasoning)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_r30_crs_reasoning.py"
_M = APP / "crs_mapping.py"
_E = APP / "crs_export.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M803-01", phase=803, description="the issue copy carries the internal reasoning",
             path=_E, anchor='''            "reasoning": (str(finding.get("reasoning") or "")
                          if copy == COPY_INTERNAL else ""),''',
             replacement='''            "reasoning": str(finding.get("reasoning") or ""),''',
             target=_T, keyword="issue_copy_never_carries_it", tags=("crs", "honesty")),
    Mutation(id="M803-02", phase=803, description="the issue copy gets the reasoning column",
             # Re-anchored 2026-10-17 (#947 wiring, PR #985): the trust column joined the list.
             path=_E, anchor="+ ([AI_COLUMN, REASONING_COLUMN, TRUST_COLUMN, SUGGEST_COLUMN]\n                      if copy == COPY_INTERNAL else []),",
             replacement="+ ([AI_COLUMN, REASONING_COLUMN, TRUST_COLUMN, SUGGEST_COLUMN]\n                      if copy == COPY_INTERNAL else [REASONING_COLUMN]),",
             target=_T, keyword="issue_copy_never_carries_it", tags=("crs", "honesty")),
    Mutation(id="M803-03", phase=803, description="the workbook drops the reasoning cell",
             # Re-anchored 2026-10-17 (#947 wiring, PR #985): the trust cell follows the reasoning cell.
             path=_E, anchor='values.extend([entry["ai_review_comment"], entry["reasoning"],\n                           entry.get("rule_trust", ""), entry["ai_suggests"]])',
             replacement='values.extend([entry["ai_review_comment"],\n                           entry.get("rule_trust", ""), entry["ai_suggests"]])',
             target=_T, keyword="internal_copy_prints_it", tags=("crs",)),
    Mutation(id="M803-04", phase=803, description="a value not read is printed as if read",
             path=_M, anchor='(f" = {value}" if value else " (no value read)")',
             replacement='f" = {value}"',
             target=_T, keyword="value_not_read_says_so", tags=("crs", "honesty")),
    Mutation(id="M803-05", phase=803, description="the code's own why is left out",
             path=_M, anchor='        bits.extend(method_notes.why_bits(f.get("ai_rationale")))\n',
             replacement="        pass\n",
             target=_T, keyword="calculation_row_carries", tags=("crs",)),
    Mutation(id="M803-06", phase=803, description="machine rows carry no reasoning",
             path=_M, anchor='                "reasoning": reasoning_text(group),\n',
             replacement='                "reasoning": "",\n',
             target=_T, keyword="every_machine_row", tags=("crs",)),
    Mutation(id="M803-07", phase=803, description="the result is printed as the raw status code",
             path=_M, anchor='bits.append(f"Result: {_RESULT_WORDS.get(status, status)}")',
             replacement='bits.append(f"Result: {status}")',
             target=_T, keyword="value_page_clause_result", tags=("crs",)),
)
