"""Blank fields no clause asks about: ONE CRS row, in full sentences (#882, PF2,
owner orders 180 / 180.1, items 3, 4 and 8).

A datasheet field the contractor left blank (`___`) that no clause of a held
standard names is a datasheet-checklist finding with no `standard_clause`. One
row each buried the sheet in rows saying nothing the next said not. They are
ONE row: "These fields are left blank; contractor to complete: A (p.1), B
(p.2)." A blank field that a real clause requires keeps its own row, with that
clause, as before.

The wording is a full sentence built from what is known, never a bare label.
A field is named as the reader quoted it on the page (the longest of its
spellings, so a fragment never stands for it); two labels that differ are two
fields and both are named. Nothing here names a datasheet, a field or a
layout (rule 13): it reads the finding's own fields only.
"""

from __future__ import annotations

#: The datasheet checklist's rule for a mandatory field the sheet left blank
#: (`datasheet_checks`, "DS-M2").
BLANK_RULE = "DS-M2"
#: What the permanent number of the one row is keyed on: the kind of row, not
#: which fields a run happens to find blank.
ROW_KEY = "blank fields"
#: At most this many fields are named in the one comment.
MAX_FIELDS = 30
HEADLINE = "These fields are left blank; contractor to complete: "


def is_unrequired_blank(f: dict) -> bool:
    """A datasheet-checklist blank that no clause of a standard stands behind."""
    return (
        f.get("origin") == "datasheet_check"
        and f.get("compliance_status") == "MISSING_INFORMATION"
        and f"{BLANK_RULE}:" in str(f.get("requirement_source_text") or "")
        and not f.get("standard_clause")
    )


def _spelling(f: dict) -> str:
    return " ".join(
        str(f.get("crs_field_label") or f.get("contractor_section") or "").split()
    )


def entries(group: list[dict]) -> list[tuple[str, list[int]]]:
    """[(the field as quoted, its pages)], in first-page order. Two spellings of
    one field are one entry when one is a fragment of the other (the shorter
    is the start of the longer on a word boundary, case-folded: the longer is
    the full label as quoted). Two labels that differ after a " - " are two
    fields and both stay; a fragment that several longer labels extend is not
    guessed into one of them. A finding with no label is not an entry (see
    `unlabelled`)."""
    spelled: dict[str, dict] = {}
    for g in group:
        label = _spelling(g)
        if not label:
            continue
        entry = spelled.setdefault(label.lower(), {"label": label, "pages": set()})
        if isinstance(g.get("contractor_page"), int):
            entry["pages"].add(g["contractor_page"])
    kept: list[dict] = []
    for key in sorted(spelled, key=len, reverse=True):
        entry = spelled[key]
        longer = [k for k in kept if k["key"].startswith(key + " ")]
        if len(longer) == 1:
            longer[0]["pages"] |= entry["pages"]
        else:
            kept.append({"key": key, **entry})
    kept.sort(key=lambda e: (min(e["pages"]) if e["pages"] else 10**9, e["key"]))
    return [(e["label"], sorted(e["pages"])) for e in kept]


def unlabelled(group: list[dict]) -> int:
    """How many findings of the row name no field the reader quoted."""
    return sum(1 for g in group if not _spelling(g))


def page_list(pages: list[int]) -> str:
    """`[1, 2, 3, 7]` -> `1-3, 7` - the shape the findings themselves use."""
    out, run = [], []
    for p in sorted(pages):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


def _where(pages: list[int]) -> str:
    return f" (p.{page_list(pages)})" if pages else ""


def comment(group: list[dict]) -> str:
    """The row's comment: one plain sentence naming every field and its pages.
    At most MAX_FIELDS are named; the rest are counted, never dropped silently."""
    named = entries(group)
    parts = [f"{label}{_where(p)}" for label, p in named[:MAX_FIELDS]]
    if len(named) > MAX_FIELDS:
        parts.append(
            f"and {len(named) - MAX_FIELDS} more of these {len(named)} (see the datasheet pages)"
        )
    if unlabelled(group):
        parts.append(
            f"{unlabelled(group)} with no readable field name (see the datasheet pages)"
        )
    if not parts:
        return "Contractor to complete the fields left blank on the datasheet."
    return HEADLINE + "; ".join(parts) + "."


def page_section(group: list[dict]) -> str:
    """The sheet's pages ("p.1-2 - Fields left blank"), never one field's."""
    pages = sorted(
        {
            g["contractor_page"]
            for g in group
            if isinstance(g.get("contractor_page"), int)
        }
    )
    return f"p.{page_list(pages)} - Fields left blank" if pages else "Fields left blank"


def is_row(group: list[dict]) -> bool:
    """Is this group the one blank-fields row?"""
    return is_unrequired_blank(group[0])


def comment_or(group: list[dict], other) -> str:
    """The blank-fields row's comment, else `other(group)`."""
    return comment(group) if is_row(group) else other(group)


def section_or(group: list[dict], other) -> str:
    """The blank-fields row's page and field, else `other(group)`."""
    return page_section(group) if is_row(group) else other(group)
