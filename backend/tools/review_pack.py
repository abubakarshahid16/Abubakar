"""PF6 (#886): the engineer review pack - the form a KJO engineer marks each
sampled finding right, wrong or unsure on, and lists what the review missed.

TWO SECTIONS, NEVER MIXED. MAIN is a sample of findings from unfamiliar
non-PSV documents (and the M-03 / 0810 runs); SECONDARY is the 94 PSV rows of
#829. #886's pass mark needs both counted apart, so every row here carries its
section and the two are never pooled into one count.

THE ENGINEER'S MARK IS THE ONLY GROUND TRUTH THIS WRITES. The pack ships with
no mark filled in (never a default, never a guess at what the engineer would
say); `read_pack` refuses a row with no mark rather than count it as anything.

THE FILLED SHEET IS KEPT, ONLY ITS COUNTS ARE POSTED. `score_pack` returns ids
and counts only - which finding ids were marked wrong, how many right, how
many unsure - never the finding's text, quote or document name, so the
tracking comment on #829 / #692 never carries client text. The missed-defect
list the engineer adds is itself free text and stays in the local file;
`score_pack` reports only how many entries it holds.

Format `review-pack/1`. Pure: no database, no network, no model.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable

PACK_FORMAT = "review-pack/1"
MAIN, SECONDARY = "main", "secondary"
SECTIONS = (MAIN, SECONDARY)

RIGHT, WRONG, UNSURE = "right", "wrong", "unsure"
MARKS = (RIGHT, WRONG, UNSURE)

#: The sheet's own column headers, in order. `Mark` and `Note` are the
#: engineer's; everything before them is read-only context from our own run.
COLUMNS = ("Item No", "Section", "Document", "Page", "Standard", "Clause",
          "Field", "Our verdict", "Evidence quote", "Mark", "Note")
#: Printed in the Mark column's data-validation list, and nowhere else: a
#: typo in a filled sheet must be visible as "not one of these", not silently
#: read as blank.
MARK_CHOICES = f'"{",".join(MARKS)}"'

MISSED_DEFECTS_SHEET = "Missed defects (engineer adds)"
MISSED_DEFECTS_COLUMNS = ("Standard", "Clause", "What the review missed")


class PackError(ValueError):
    """A pack or a filled sheet that cannot be built or read, with why."""


def sample_rows(findings: list[dict], *, size: int, seed: int) -> list[dict]:
    """`size` findings out of `findings`, chosen the same way every time for
    the same `seed` - so a second run of the same PF1 sample is reproducible,
    never a fresh random draw that cannot be checked. All of them when there
    are `size` or fewer."""
    if size < 0:
        raise PackError("size must be 0 or more")
    if len(findings) <= size:
        return list(findings)
    return random.Random(seed).sample(findings, size)


def _row(n: int, section: str, f: dict) -> dict:
    return {
        "item_no": n, "section": section,
        "id": f.get("id") or f"{section}-{n}",
        "document": f.get("document") or f.get("submittal_document") or "",
        "page": f.get("submittal_page"),
        "standard": f.get("standard") or "",
        "clause": f.get("clause") or "",
        "field": f.get("field") or "",
        "our_verdict": f.get("compliance_status") or "",
        "evidence_quote": f.get("requirement_text") or "",
        "mark": None, "note": "",
    }


def build_pack(main_findings: Iterable[dict], secondary_findings: Iterable[dict], *,
               main_sample_size: int, secondary_sample_size: int | None = None,
               seed: int = 0) -> dict:
    """The pack's rows, MAIN sampled from `main_findings`, SECONDARY from
    `secondary_findings` (sampled too when `secondary_sample_size` is given,
    else every row - #886 names the SECONDARY set as "the 94 PSV rows", a
    fixed set, not something to sub-sample by default).

    Returns `{"format": PACK_FORMAT, "counts": {...}, "rows": [...]}`. Every
    row's `mark` and `note` start empty - the engineer's, never guessed.
    """
    main = sample_rows(list(main_findings), size=main_sample_size, seed=seed)
    secondary = (sample_rows(list(secondary_findings), size=secondary_sample_size, seed=seed)
                if secondary_sample_size is not None else list(secondary_findings))
    rows = [_row(n, MAIN, f) for n, f in enumerate(main, start=1)]
    rows += [_row(n, SECONDARY, f) for n, f in enumerate(secondary, start=len(rows) + 1)]
    return {"format": PACK_FORMAT,
           "counts": {"main_available": len(list(main_findings)) if hasattr(main_findings, "__len__") else None,
                      "main_sampled": len(main), "secondary_sampled": len(secondary)},
           "rows": rows}


# ------------------------------------------------------------- the workbook

def render_pack(pack: dict) -> bytes:
    """The pack as an .xlsx: one sheet of rows (read-only context plus the
    engineer's blank Mark/Note), one sheet for missed defects, started empty.
    """
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Review pack"
    ws.append(list(COLUMNS))
    for row in pack["rows"]:
        ws.append([row["item_no"], row["section"], row["document"], row["page"],
                   row["standard"], row["clause"], row["field"], row["our_verdict"],
                   row["evidence_quote"], row["mark"] or "", row["note"]])
    mark_col = COLUMNS.index("Mark") + 1
    if pack["rows"]:
        dv = DataValidation(type="list", formula1=MARK_CHOICES, allow_blank=True,
                            showErrorMessage=True, error="Mark must be right, wrong or unsure.")
        ws.add_data_validation(dv)
        dv.add(f"{ws.cell(row=2, column=mark_col).coordinate}:"
               f"{ws.cell(row=len(pack['rows']) + 1, column=mark_col).coordinate}")

    missed = wb.create_sheet(MISSED_DEFECTS_SHEET)
    missed.append(list(MISSED_DEFECTS_COLUMNS))

    import io
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_pack(path: str | Path) -> dict:
    """The filled sheet back, as rows plus the missed-defects list. A row
    whose Mark is not one of `MARKS` is returned with `mark=None` and
    `mark_error` set - never guessed, never silently counted."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    if "Review pack" not in wb.sheetnames:
        raise PackError("not a review pack: no 'Review pack' sheet")
    ws = wb["Review pack"]
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(c or "").strip() for c in next(rows_iter)]
    if tuple(header) != COLUMNS:
        raise PackError(f"the sheet's columns do not match: expected {COLUMNS}, got {tuple(header)}")
    idx = {name: i for i, name in enumerate(header)}
    rows = []
    for values in rows_iter:
        if values is None or all(v is None for v in values):
            continue
        mark_raw = str(values[idx["Mark"]] or "").strip().lower()
        rows.append({
            "item_no": values[idx["Item No"]], "section": values[idx["Section"]],
            "id": None,  # the filled sheet carries no id column (never printed to the engineer)
            "mark": mark_raw if mark_raw in MARKS else None,
            "mark_error": None if (not mark_raw or mark_raw in MARKS) else mark_raw,
            "note": str(values[idx["Note"]] or ""),
        })
    missed = []
    if MISSED_DEFECTS_SHEET in wb.sheetnames:
        ms = wb[MISSED_DEFECTS_SHEET]
        mrows = ms.iter_rows(values_only=True)
        next(mrows, None)  # header
        missed = [r for r in mrows if r and any(c is not None for c in r)]
    return {"format": PACK_FORMAT, "rows": rows, "missed_defects": len(missed)}


def score_pack(filled: dict) -> dict:
    """Counts only - ids, never text - per #886's pass mark: every sampled
    row marked, split MAIN / SECONDARY, plus how many missed defects the
    engineer listed. A row with no mark, or an unreadable one, is reported
    apart, never folded into 'wrong' or dropped."""
    out = {}
    for section in SECTIONS:
        rows = [r for r in filled["rows"] if r["section"] == section]
        counts = {m: sum(1 for r in rows if r["mark"] == m) for m in MARKS}
        unmarked = [r["item_no"] for r in rows if r["mark"] is None and not r.get("mark_error")]
        bad_mark = [r["item_no"] for r in rows if r.get("mark_error")]
        out[section] = {"rows": len(rows), **counts,
                        "marked": sum(counts.values()),
                        "unmarked_item_nos": sorted(unmarked),
                        "unreadable_mark_item_nos": sorted(bad_mark)}
    out["missed_defects"] = filled.get("missed_defects", 0)
    return out
