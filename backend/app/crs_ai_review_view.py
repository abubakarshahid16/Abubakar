"""AI engineering review pass, part 3: what the INTERNAL CRS shows of the accepted proposals. Lane 6.

INTERNAL COPY ONLY (the callers are `crs_ai_cell.apply`, `run_record.crs_meta` and `crs_export._later_sheets`, which are
internal-only paths). The issue copy never shows an AI removal, an AI reason or the understanding note.

  * remove: the row leaves the main sheet and is listed, with its own words, the AI's reason and who may restore it, on the
    sheet "AI review". An engineer's restore (`ai_review_pass.restore`, append-only, undoable) puts it back at once.
  * add: a new row, kind chosen by CODE (`ai_review_proposals.ADDED_KIND`), never confirmed, its reason in the AI Review
    Comments cell and the AI marked as its author.
  * reword: the new wording prints in the AI Review Comments cell beside the template, with the AI's reason; the template
    stays the comment. An engineer's confirmed words are never touched.
  * understanding: a short block at the top of the sheet "AI review".
A removal never applies to a row an engineer confirmed (it is theirs), and a stored removal of a row that is no longer in the
run is shown on the sheet as not applied. Each removal's state is the one `apply` found against the run's rows (removed, kept
because confirmed, no longer in the run, restored); the CRS top note counts only those really removed. Nothing here reads document text or calls a model.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager

from openpyxl.styles import Alignment, Font

from . import ai_review_pass

SHEET = "AI review"
AUTHOR = "AI engineering review - engineer to confirm"
HEADER_NOTE = (
    "Proposed by the AI and accepted only after code verified every value, page and clause on the document. "
    "Nothing here is a verdict; an engineer decides. A removed row can be restored by an engineer: "
    "POST /api/reviews/runs/{run}/ai-review/{proposal id}/restore (logged with who and when)."
)
STATE_REMOVED = "removed from the CRS"
STATE_RESTORED = "restored by an engineer"
STATE_KEPT = "kept on the CRS: an engineer confirmed this row"
STATE_ABSENT = "not applied: the row is no longer in this run"
STATE_FLAGGED = "flagged: the row stays on the CRS for the engineer to decide"
STATE_UNCHECKED = "removal proposed; not checked against this run's rows"
_SKIP = contextvars.ContextVar("crs_ai_review_view_skip", default=False)
#: Decision paths (open-items gate, finding decision) read the rows WITH the removed rows still in them: a removal is a
#: display change on the internal CRS, never a way to take an item out of the engineer's workflow.
_KEEP = contextvars.ContextVar("crs_ai_review_view_keep_removed", default=False)
#: (review_run_id, {proposal_id: state}) from the last `apply` in this context, so the sheet states what happened to
#: each removal against the rows it was applied to.
_APPLIED: contextvars.ContextVar[tuple[str, dict[str, str]] | None] = (
    contextvars.ContextVar("crs_ai_review_view_applied", default=None)
)


def with_removed(fn, *args):
    """Call `fn` (the CRS content builder) with removed rows still present: the gate and the decide route use it."""
    token = _KEEP.set(True)
    try:
        return fn(*args)
    finally:
        _KEEP.reset(token)


def top_note(meta: dict, copy: str) -> str:
    """Row 1 of the CRS: the run status note, then (internal copy only) the AI review's removal count."""
    note = (meta.get("ai_review") or {}).get("note") if copy == "internal" else ""
    from . import crs_export_quality

    said = crs_export_quality.with_rules_note(
        meta
    )  # the run status, then the rules note when its switch is on
    return "\n".join(p for p in (said, note) if p)


@contextmanager
def unapplied():
    """The pass itself reads the DRAFT rows, not rows it already changed."""
    token = _SKIP.set(True)
    try:
        yield
    finally:
        _SKIP.reset(token)


def _reason(proposal: dict) -> str:
    return f"AI review: {str(proposal.get('reason') or '').strip()}"


def _added_row(rows: list[dict], proposal: dict, review_run_id: str) -> dict:
    kind = proposal["row_kind"] or "needs_engineer_review"
    same = next(
        (
            r
            for r in rows
            if r.get("row_kind") == kind and r.get("priority") is not None
        ),
        None,
    )
    where = f"p.{proposal.get('page')} - {proposal.get('field') or ''}"
    standard = " ".join(
        p
        for p in (
            str(proposal.get("standard") or ""),
            f"cl. {proposal['clause']}" if proposal.get("clause") else "",
        )
        if p
    )
    return {
        "finding_id": "",
        "finding_ids": [],
        "document_name": next(
            (r.get("document_name") for r in rows if r.get("document_name")), ""
        ),
        "page_section": where,
        "comment": proposal["final_text"],
        "ai_comment": proposal["final_text"],
        "edited": False,
        "comment_by": AUTHOR,
        "standard_reference": standard,
        "row_kind": kind,
        "engineer_confirmed": False,
        "crs_row_key": f"ai-review:{review_run_id}:{proposal['proposal_id']}",
        "ai_review_comment": _reason(proposal),
        "ai_review_added": True,
        "priority": same["priority"] if same else 3,
    }


def apply(rows: list[dict], review_run_id: str) -> None:
    """Change `rows` in place: drop the removed rows, add the added ones, print the rewordings. Internal copy only."""
    if _SKIP.get():
        return
    accepted = ai_review_pass.accepted(review_run_id)
    if not accepted:
        return
    restored = ai_review_pass.restored_ids(review_run_id)
    by_key = {r.get("crs_row_key"): r for r in rows if r.get("crs_row_key")}
    gone, added, states = set(), [], {}
    for item in accepted:
        row = by_key.get(item.get("row_key"))
        if item["type"] == "remove":
            states[item["proposal_id"]] = (
                STATE_RESTORED
                if item["proposal_id"] in restored
                else STATE_ABSENT
                if row is None
                else STATE_KEPT
                if row.get("engineer_confirmed")
                else STATE_REMOVED
            )
        if (
            item["type"] == "remove"
            and row is not None
            and item["proposal_id"] not in restored
            and not row.get("engineer_confirmed")
        ):
            gone.add(item["row_key"])
        elif (
            item["type"] == "reword"
            and row is not None
            and not row.get("engineer_confirmed")
        ):
            row["ai_review_comment"] = f"{item['final_text']}\n{_reason(item)}"
        elif item["type"] == "flag":
            states[item["proposal_id"]] = STATE_ABSENT if row is None else STATE_FLAGGED
            if (
                row is not None
            ):  # the row (a Fail too) stays; the code-built flag prints in the AI cell
                said = str(row.get("ai_review_comment") or "").strip()
                row["ai_review_comment"] = "\n".join(
                    p for p in (said, item["final_text"]) if p
                )
        elif item["type"] == "add":
            added.append(item)
    _APPLIED.set((review_run_id, states))
    if not _KEEP.get():
        rows[:] = [r for r in rows if r.get("crs_row_key") not in gone]
    rows.extend(_added_row(rows, item, review_run_id) for item in added)


def _evidence(proposal: dict) -> str:
    """The verified evidence of a removal as the sheet prints it: page and quote, one line each (code checked every quote
    stands on its page); a rulebook scope removal prints the clause the rulebook puts outside this equipment."""
    lines = [
        f'p.{e.get("page")}: "{e.get("quote")}"'
        for e in proposal.get("evidence") or []
        if isinstance(e, dict)
    ]
    if proposal.get("basis") == "out_of_scope":
        lines.append(
            f"rulebook: {proposal.get('standard') or ''} cl. {proposal.get('clause') or ''} is outside this equipment".strip()
        )
    return "\n".join(lines)


def for_run(review_run_id: str) -> dict | None:
    """What the sheet "AI review" prints, or None when the pass left nothing to show. Internal copy only."""
    accepted = ai_review_pass.accepted(review_run_id)
    summary = ai_review_pass.summary_of(review_run_id) or {}
    understanding = next(
        (a["understanding"] for a in accepted if a["type"] == "understanding"), None
    )
    if not accepted and not understanding:
        return None
    restored = ai_review_pass.restored_ids(review_run_id)
    applied = _APPLIED.get()
    states = applied[1] if applied and applied[0] == review_run_id else {}
    removed = [
        {
            "proposal_id": a["proposal_id"],
            "words": a.get("row_words", ""),
            "where": a.get("row_where", ""),
            "standard": a.get("row_standard", ""),
            "reason": a.get("reason", ""),
            "basis": a.get("basis") or "",
            "evidence": _evidence(a),
            "state": STATE_RESTORED
            if a["proposal_id"] in restored
            else states.get(a["proposal_id"], STATE_UNCHECKED),
        }
        for a in accepted
        if a["type"] == "remove"
    ]
    flagged = [
        {
            "proposal_id": a["proposal_id"],
            "where": a.get("row_where", ""),
            "standard": a.get("row_standard", ""),
            "words": a.get("row_words", ""),
            "flag": a.get("final_text", ""),
            "state": states.get(a["proposal_id"], STATE_UNCHECKED),
        }
        for a in accepted
        if a["type"] == "flag"
    ]
    gone = sum(1 for r in removed if r["state"] == STATE_REMOVED)
    shown = sum(1 for f in flagged if f["state"] == STATE_FLAGGED)
    parts = [
        f"{n} comment{'s' if n != 1 else ''} {what} by AI review"
        for n, what in ((gone, "removed"), (shown, "flagged"))
        if n
    ]
    return {
        "understanding": understanding,
        "removed": removed,
        "flagged": flagged,
        "note": (", ".join(parts) + ", see internal sheet") if parts else "",
        "engine": summary.get("engine"),
        "model": summary.get("model"),
        "local_instead": summary.get("local_instead"),
        "counts": {
            t: sum(1 for a in accepted if a["type"] == t)
            for t in ("remove", "add", "reword", "flag")
        },
    }


def write_sheet(wb, data: dict, write) -> None:
    """Draw the sheet. `write` is `crs_export._write`, which stores every string as text."""
    sheet = wb.create_sheet(SHEET)
    wrap = Alignment(wrap_text=True, vertical="top")
    write(sheet, 1, 1, HEADER_NOTE).alignment = wrap
    how = " ".join(
        p
        for p in (
            f"Engine: {data.get('engine') or ''}",
            data.get("model") or "",
            data.get("local_instead") or "",
        )
        if p
    )
    write(sheet, 2, 1, how).alignment = wrap
    r = 4
    note = data.get("understanding")
    if note:
        write(sheet, r, 1, "Document understanding").font = Font(bold=True)
        for key, value in note.items():
            r += 1
            write(sheet, r, 1, key.replace("_", " ").capitalize())
            write(
                sheet, r, 2, ", ".join(value) if isinstance(value, list) else str(value)
            ).alignment = wrap
        r += 2
    if data["removed"]:
        for col, head in enumerate(
            (
                "Proposal id",
                "State",
                "Where",
                "Standard",
                "Row's own words",
                "AI's reason",
                "Basis",
                "Verified evidence (page, quote)",
            ),
            1,
        ):
            write(sheet, r, col, head).font = Font(bold=True)
        for item in data["removed"]:
            r += 1
            for col, key in enumerate(
                (
                    "proposal_id",
                    "state",
                    "where",
                    "standard",
                    "words",
                    "reason",
                    "basis",
                    "evidence",
                ),
                1,
            ):
                write(sheet, r, col, item[key]).alignment = wrap
    if data.get("flagged"):
        r += 2
        write(
            sheet, r, 1, "Flagged by AI review (the row stays on the CRS)"
        ).font = Font(bold=True)
        for col, head in enumerate(
            (
                "Proposal id",
                "State",
                "Where",
                "Standard",
                "Row's own words",
                "Flag (built by code from the page quote)",
            ),
            1,
        ):
            r_head = r + 1
            write(sheet, r_head, col, head).font = Font(bold=True)
        r += 1
        for item in data["flagged"]:
            r += 1
            for col, key in enumerate(
                ("proposal_id", "state", "where", "standard", "words", "flag"), 1
            ):
                write(sheet, r, col, item[key]).alignment = wrap
    for col, width in zip("ABCDEFGH", (22, 24, 22, 26, 70, 60, 16, 70), strict=True):
        sheet.column_dimensions[col].width = width
