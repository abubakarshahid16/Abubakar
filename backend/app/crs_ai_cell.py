"""The internal CRS copy's "AI Review Comments" cell is never blank (order 233).

`crs_wording.word_run` rewords only the machine's own rows and keeps a rewrite
only if the code lock accepts it. Every other row used to print an empty cell,
which reads as "the AI looked and had nothing to say". Each one now says what
happened, in plain words:

- an AI/web check item the engineer confirmed: the comment IS the AI's draft,
  so the cell says so;
- a machine row whose rewrite was refused, not tried, or never run: the plain
  template stays, and the cell says why.

INTERNAL COPY ONLY, and only a note: the note rides in its own row key
(`ai_cell_note`), never in `ai_review_comment`, because an empty
`ai_review_comment` is what the issue-copy and carry-forward rules test.
Nothing here reads or writes document text.
"""

from __future__ import annotations

from . import crs_mapping, crs_wording

AI_DRAFT_NOTE = "Written by the AI (see the comment)"
KEPT = "Plain wording kept: "

#: Why a rewrite was refused, in words an engineer reads. Keys are the stable
#: reason strings of `crs_wording`; an unknown reason gets the generic line.
REFUSED_IN_WORDS = {
    crs_wording.NO_COMMENT: "the AI gave no comment",
    crs_wording.TOO_LONG: "the AI's wording was too long",
    crs_wording.MALFORMED: "the AI's answer could not be read",
    crs_wording.TRUNCATED: "the AI's answer was cut off",
    crs_wording.UNKNOWN: "no readable answer came back",
    crs_wording.NUMBER_CHANGED: "the AI's wording changed a number",
    crs_wording.UNIT_CHANGED: "the AI's wording changed a unit",
    crs_wording.CLAUSE_DROPPED: "the AI's wording dropped the clause",
    crs_wording.STANDARD_CHANGED: "the AI's wording changed the standard",
    crs_wording.CLAIM_ADDED: "the AI's wording added a claim the check did not make",
    crs_wording.STATUS_REVERSED: "the AI's wording changed the result",
}
_GENERIC = "the AI's wording did not pass the check"

_AI_KINDS = (
    crs_mapping.ROW_KIND_AI_ENGINEERING_CHECK,
    crs_mapping.ROW_KIND_WEB_STANDARD_CHECK,
)


def _is_machine_row(row: dict) -> bool:
    """A row `word_run` would have offered to the model, as it still stands:
    not since confirmed or edited by an engineer (then the words are theirs)."""
    return (
        row.get("row_kind") in crs_wording.WORDED_KINDS
        and bool(row.get("crs_row_key"))
        and bool(str(row.get("comment") or "").strip())
        and not str(row.get("comment_by") or "").startswith(("Edited", "Engineer"))
        and not row.get("engineer_confirmed")
        and row.get("edited") is not True
        and row.get("engineer_worded") is not True
    )


def _why_kept(row: dict, summary: dict | None) -> str:
    """The plain reason this machine row has no AI wording."""
    if summary is None:
        return "the AI wording step did not run for this review"
    if not summary.get("enabled"):
        return "the AI wording step is switched off"
    reason = (summary.get("refused_rows") or {}).get(row.get("crs_row_key"))
    if reason:
        return REFUSED_IN_WORDS.get(reason, _GENERIC)
    if summary.get("stopped"):
        return "the AI wording step stopped before this row"
    if summary.get("not_tried"):
        return f"only the first {crs_wording.MAX_ROWS} rows are worded"
    return "the AI offered no wording for this row"


def apply(rows: list[dict], review_run_id: str) -> None:
    """The internal copy's AI cell, for every row. First the wording the lock
    accepted (an unconfirmed machine row only; an engineer's confirmed words
    are theirs, an AI/web item keeps its own draft). Then, on every row the
    cell would still leave blank, `ai_cell_note` says why."""
    worded = crs_wording.stored(review_run_id)
    for row in rows:
        text = worded.get(row.get("crs_row_key") or "")
        if (
            text
            and not row.get("engineer_confirmed")
            and not str(row.get("ai_review_comment") or "").strip()
        ):
            row["ai_review_comment"] = text
    _notes(rows, review_run_id)


def _notes(rows: list[dict], review_run_id: str) -> None:
    summary = crs_wording.summary_of(review_run_id)
    for row in rows:
        if str(row.get("ai_review_comment") or "").strip():
            continue
        if (
            row.get("row_kind") in _AI_KINDS
            and row.get("engineer_confirmed")
            and row.get("engineer_worded") is not True
            and row.get("edited") is not True
            and str(row.get("comment") or "").strip()
            and row.get("comment") not in crs_mapping.WAITING_COMMENTS
        ):
            row["ai_cell_note"] = AI_DRAFT_NOTE
        elif _is_machine_row(row):
            row["ai_cell_note"] = KEPT + _why_kept(row, summary)
