"""Blank fields no clause asks about: ONE CRS row, in full sentences (#882, PF2,
owner orders 180 / 180.1, items 3, 4 and 8).

A datasheet field the contractor left blank (`___`) that no clause of a held
standard names is a datasheet-checklist finding with no `standard_clause`. One
row each buried the sheet in rows saying nothing the next said not. They are
ONE row: "These fields are left blank; contractor to complete: A (p.1), B
(p.2)." A blank field that a real clause requires keeps its own row, with that
clause, as before.

The wording is a full sentence built from what is known, never a bare label. The field is named as the reader quoted it on the page (the longest of
its spellings, so a trailing fragment never stands for it) and two findings of
the same field are one entry. Nothing here names a datasheet, a field or a
layout (rule 13): it reads the finding's own fields only.
"""

from __future__ import annotations

#: The datasheet checklist's rule for a mandatory field the sheet left blank
#: (`datasheet_checks`, "DS-M2").
BLANK_RULE = "DS-M2"
#: What the permanent number of the one row is keyed on: the kind of row, not
#: which fields a run happens to find blank.
ROW_KEY = "blank fields"
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


def _same_field(label: str) -> str:
    """The field a spelling names: the row label before a " - <column>" tail,
    folded."""
    return label.partition(" - ")[0].strip().lower()


def entries(group: list[dict]) -> list[tuple[str, list[int]]]:
    """[(the field as quoted, its pages)], in first-page order. Findings of one
    field (same label before any column tail) are one entry, labelled by the
    longest spelling; a finding with no label is not an entry."""
    fields: dict[str, dict] = {}
    for g in group:
        label = _spelling(g)
        if not label:
            continue
        entry = fields.setdefault(_same_field(label), {"label": label, "pages": set()})
        if len(label) > len(entry["label"]):
            entry["label"] = label
        if isinstance(g.get("contractor_page"), int):
            entry["pages"].add(g["contractor_page"])
    ordered = sorted(
        fields.values(),
        key=lambda e: (min(e["pages"]) if e["pages"] else 10**9, e["label"].lower()),
    )
    return [(e["label"], sorted(e["pages"])) for e in ordered]


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
    """The row's comment: one plain sentence naming every field and its pages."""
    named = entries(group)
    if not named:
        return "Contractor to complete the fields left blank on the datasheet."
    return HEADLINE + "; ".join(f"{label}{_where(p)}" for label, p in named) + "."


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
