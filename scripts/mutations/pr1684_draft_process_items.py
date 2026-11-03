"""Part of #805 / PR #1684: two DRAFT relief-valve process items (fluid phase, sour service) that never
decide (switch `draft_process_items_enabled`). Ids M1684-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_D = APP / "datasheet_checks.py"
_G = APP / "checklist_scope.py"
_T = "tests/test_805_draft_process_items.py"
_TAG = ("honesty", "draft")


def _m(n: int, description: str, path, anchor: str, replacement: str, keyword: str) -> Mutation:
    return Mutation(id=f"M1684-{n:02d}", phase=1684, description=description, path=path, anchor=anchor,
                    replacement=replacement, target=_T, keyword=keyword, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(1, "a draft item is read with its switch off",
       _D, "    if not settings.draft_process_items_enabled:\n", "    if False:\n",
       "switch_off"),
    _m(2, "a draft item's stated value passes as a Pass (no hold)",
       _D, "    if not is_draft_item(item):\n        return result\n", "    return result\n",
       "stated_phase_gives_no_verdict or not_stated"),
    _m(3, "a value not stated by a draft item loses its 'Not stated.' wording",
       _D, "        out[\"detail\"] = \"Not stated. \" + detail", "        out[\"detail\"] = detail",
       "not_stated_is_the_contractors_gap"),
    _m(4, "sour service stated yes is no longer a query for materials",
       _D, "            if yes and not no:\n", "            if False:\n",
       "sour_service_yes_is_a_query"),
    _m(5, "sour service stated no is read as a query, not as no verdict",
       _D, "            elif no and not yes:\n", "            elif False:\n",
       "sour_service_no_gives_no_verdict"),
    _m(6, "a stated draft value writes a finding row",
       _D, "    results = [x for x in results if x[\"status\"] != STATED_NO_VERDICT]", "    results = [x for x in results if False]",
       "stated_value_writes_no_row"),
    _m(7, "a draft item makes its standard governed by the checklist",
       _G, "            if not str(item.get(\"status\") or \"\").lower().startswith(\"draft\")\n",
       "            if True\n",
       "does_not_make_its_standard_governed"),
)
