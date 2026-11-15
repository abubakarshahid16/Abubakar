"""Role 9, the Writer (nine-role design A role 9): the AI wording of the comments of the ONE sheet, and nothing else.

The sheet is `crs_one`'s, one comment per field is `crs_comments`', the completeness check is `crs_completeness`'; this module only asks
for a wording of each comment and decides which wordings are kept. Every wording is asked through the one call seam (`nine_call.ask`, role 9:
a fixed template and ONE derived block of declared cell kinds whose sources are the paper and the books of the clauses) and is kept only
when `crs_wording.lock` finds no number, unit, clause, page, standard or status changed (`nine_sheet.apply_wordings`); a refused wording
leaves the code's words and is counted. The kept wordings are stored (`nine_sheet.store_wordings`) and are what the CRS comment shows, the code's
words stay beside them. The contractor file is never reworded. On the local model, or with no stored engine decision, the code's words stand.

No verdict, class or word of a decision is made here. No document text is logged.
"""

from __future__ import annotations

from . import nine_call, nine_sheet
from .db import connect

WRITER_SYSTEM = nine_call.template(
    "nine_writer_system",
    "You write the comments of a review sheet for an engineer, in an engineer's plain voice. You use only the facts in the rows you are given.",
)
WRITER_QUESTION = nine_call.template(
    "nine_writer_question",
    "For each of the {count} rows write one short comment for the contractor from the row's own facts only: the field, its status, the pages and "
    'the clauses. Add no number, unit, clause or standard that is not in the row and never change a status. Answer with JSON only: {{"1": "comment", ...}}.',
    count="int",
)
_STATUS_ENUM = {"not_met": "not_met", "met": "met"}
STATUS_VOCAB = nine_call.vocabulary("nine_writer_status", ("met", "not_met", "unknown"))
CODE_WORDS_LOCAL = "comments worded by code: no AI wording on the local model"
CODE_WORDS_NO_DECISION = (
    "comments worded by code: no engine decision is stored for this run"
)


def code_words(c: dict) -> str:
    """The code's own words of a comment: the strongest point's action line (what a wording must keep every fact of)."""
    from . import crs_one

    return crs_one.comment_full_texts(c)["action"]


def items_of(
    grouped: list[dict],
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """Rows for the derived block, one per comment, with DECLARED cell kinds (id, source, enum, code): the comment number, its field (a
    `source` cell: it must occur in the paper or a book the block names), its status as an enum word, its first page. And the books the rows
    came from (the paper is added by the caller)."""
    rows, books = [], []
    for c in grouped:
        page = str(c["pages"][0]) if c["pages"] else "0"
        rows.append(
            (
                str(c["number"]),
                (c["name"] or "").replace("\n", " ")[:60],
                _STATUS_ENUM.get(c["tile"], "unknown"),
                page,
            )
        )
        books += [
            str(b["id"])
            for p in c["members_points"]
            for b in p.get("books") or []
            if b.get("id")
        ]
    return tuple(rows), tuple(dict.fromkeys(books))


def lock_rows(grouped: list[dict]) -> list[dict]:
    """The rows `nine_sheet.apply_wordings` locks each wording against: the code's words, the clauses and the pages of the comment."""
    return [
        {
            "key": c["key"], "comment": code_words(c),
            "standard_reference": "; ".join(f"{k['book'] or ''} cl. {k['clause']}" for k in c["clauses"] if k.get("clause")),
            "page_section": ", ".join(str(x) for x in c["pages"]), "must_have": [c["name"] or "", *c["tags"]], "row_kind": "non_compliant" if c["tile"] == "not_met" else "other",
        }
        for c in grouped
    ]  # fmt: skip


def comments_of(submittal: str) -> list[dict]:
    from . import access, crs_comments
    from . import review_points_service as svc

    _listing, raw, _facts = svc.export_listing(submittal, access.unrestricted_scope())
    by_id = {p["id"]: p for p in raw}
    grouped = crs_comments.group(raw)
    for c in grouped:
        c["members_points"] = [by_id[i] for i in c["member_ids"]]
    return grouped


def ask_wordings(
    run_id: str, submittal: str, grouped: list[dict], *, ask=nine_call.ask, **seam
) -> tuple[dict, dict, str | None]:
    """(kept wordings by comment key, refused counts by reason, the error code when the call did not answer). ONE call; nothing is stored."""
    items, books = items_of(grouped)
    if not items:
        return {}, {}, None
    block = nine_call.Block(
        "review_record",
        name="comments",
        sources=(submittal, *books),
        kinds=("number", "source", f"vocab:{STATUS_VOCAB}", "number"),
        items=items,
    )
    got = ask(
        run_id,
        9,
        [block],
        (WRITER_QUESTION, {"count": len(items)}),
        system=(WRITER_SYSTEM, {}),
        **seam,
    )
    asked = {str(c["number"]): c["key"] for c in grouped}
    said = (
        {
            asked[k]: str(v)
            for k, v in (got.data or {}).items()
            if k in asked and isinstance(v, str)
        }
        if got.ok
        else {}
    )
    kept, dropped = nine_sheet.apply_wordings(lock_rows(grouped), said)
    return kept, dropped, (None if got.ok else got.error_code)


def write(
    run_id: str, submittal: str, engine: str, *, ask=nine_call.ask, **seam
) -> tuple[dict, str | None]:
    """The writer's part of role 9: (counts for the record, why it only ran partly or None). Claude asks and locks and stores; anything else
    leaves the code's words."""
    if engine != "claude":
        return {}, CODE_WORDS_LOCAL if engine == "local" else CODE_WORDS_NO_DECISION
    grouped = comments_of(submittal)
    kept, dropped, error = ask_wordings(run_id, submittal, grouped, ask=ask, **seam)
    nine_sheet.store_wordings(connect(), run_id, kept)
    produced = {
        "comments": len(grouped), "ai_wordings_kept": len(kept), "dropped": sum(dropped.values()),
        **{f"dropped.{k}": n for k, n in dropped.items()},
    }  # fmt: skip
    if error:
        return (
            produced,
            f"the writer's call did not answer ({error}): comments worded by code",
        )
    if dropped:
        return (
            produced,
            f"{sum(dropped.values())} comments kept in code words: the writer changed a fact",
        )
    return produced, None
