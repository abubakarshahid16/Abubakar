"""A standard the run judged not applicable is never used as support (orders 180.1 item 6).

The standards check can say, for a standard the datasheet cites, "this does not
appear to apply to this equipment" (it governs other equipment, or a service the
sheet declares absent). The same run must not then quote that standard's clauses
as the support of other rows: two rows said "ASME VIII does not appear to apply"
while four others used ASME VIII clauses. A standard so judged is HELD for the
engineer - not compared, not quoted - with the reason the check gave, and the
"cited but does not appear to apply" row stays the one place the engineer reads it.

Pure function over the selection dict; the lookup is passed in.
"""

from __future__ import annotations


def hold(selected: dict, check: dict, library: list, find) -> None:
    """Mark, in place, every selected standard the check judged not applicable."""
    for item in check.get("cited_not_applicable") or []:
        entry = find(library, item["identifier"])
        row = selected.get(entry["id"]) if entry else None
        if row is not None and not row.get("held_for_engineer"):
            row["held_for_engineer"] = (
                "held for the engineer to check: this run judged it not applicable "
                f"({item['reason']})"
            )
