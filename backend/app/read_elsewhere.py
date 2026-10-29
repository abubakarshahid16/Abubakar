"""A value that was read for other equipment tags is never "not read" for this one (order 307.1). Pure.

The checks judge every equipment tag on a sheet on its own: a tag's own value is never lent to another tag. When
the set pressure is read for PSV-1 and PSV-2 and a third valve has none, that third valve's checklist item is
MISSING_INFORMATION. Said alone on the CRS ("Not read from the datasheet - Set pressure") it tells the contractor
the sheet has no set pressure, which is false. Such a row becomes NEEDS_ENGINEER_REVIEW and says which pages the
value was read on and for which tag it was not, and it carries the first of those pages so the Page/Section cell
shows where the value is, not "Not read"."""

from __future__ import annotations

MISSING = "MISSING_INFORMATION"
REVIEW = "NEEDS_ENGINEER_REVIEW"
#: Results that carry a value the reader did read (a placeholder is MISSING and is not one).
_READ = ("COMPLIANT", "NON_COMPLIANT", REVIEW)


def soften(results: list[dict]) -> list[dict]:
    pages_by_role: dict[str, set[int]] = {}
    for r in results:
        if (
            r.get("checklist")
            and r.get("fact_id") is not None
            and r["status"] in _READ
            and r.get("role")
            and r.get("page")
        ):
            pages_by_role.setdefault(r["role"], set()).add(r["page"])
    out = []
    for r in results:
        pages = sorted(pages_by_role.get(r.get("role"), ()))
        if (
            pages
            and r.get("checklist")
            and r["status"] == MISSING
            and r.get("fact_id") is None
        ):
            where = ", ".join(str(p) for p in pages)
            tag = r.get("equipment_tag")
            r = {
                **r,
                "status": REVIEW,
                "page": pages[0],
                "read_elsewhere": True,
                "text_searched": False,
                "detail": (
                    f"A value for {r['field']} was read on page{'s' if len(pages) > 1 else ''} {where}, "
                    f"but not for {tag if tag else 'this item'}; engineer to confirm."
                ),
            }
        out.append(r)
    return out
