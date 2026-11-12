"""What the AI reviewer does with each kind of paper: ONE data file, read here and nowhere else (order 13, K1b).

`reference/kind_review_table.json` holds, per kind: which review runs (`rule`, `rule_and_general`, `general`, `completeness`,
`none`), the label kinds whose rules are asked, the checklist skill (by the ending of its name; an EMPTY slot says so), whether
the kind has a main equipment type, the page strategy for a long paper (window size and overlap; the split is deterministic,
see `windows`) and the discipline words of the CRS. The gate, the item builder, the equipment rule and the CRS read it through
the functions below: no kind list lives in code any more (rule 13: by kind, never by one paper).

No model, no network, no I/O but the one file read.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TABLE_PATH = Path(__file__).parent / "reference" / "kind_review_table.json"
REVIEWS = ("rule", "rule_and_general", "general", "completeness", "none")
ROW_KEYS = (
    "review", "rules_of_kind", "ask_rules", "checklist_skill_ending", "checklist_slot", "no_main_equipment",
    "window_tokens", "overlap_pages", "crs_discipline", "label", "scored", "contractor_copy_ai_verdict",
)  # fmt: skip
UNKNOWN = "unknown"


class TableError(ValueError):
    """The data file is malformed: nothing is asked of any paper until it is fixed."""


def _check(data: dict) -> dict:
    kinds = data.get("kinds")
    if not isinstance(kinds, dict) or UNKNOWN not in kinds:
        raise TableError("the table needs a `kinds` object with a row for unknown")
    for name, row in kinds.items():
        missing = [k for k in ROW_KEYS if k not in row]
        if missing:
            raise TableError(f"kind {name}: missing {missing}")
        if row["review"] not in REVIEWS:
            raise TableError(
                f"kind {name}: review {row['review']!r} is not one of {REVIEWS}"
            )
        if not isinstance(row["scored"], bool):
            raise TableError(f"kind {name}: scored must be true or false")
        if not isinstance(row["contractor_copy_ai_verdict"], bool):
            raise TableError(
                f"kind {name}: contractor_copy_ai_verdict must be true or false"
            )
        if row["ask_rules"] != bool(row["rules_of_kind"]):
            raise TableError(f"kind {name}: ask_rules and rules_of_kind disagree")
        if (
            row["review"] in ("rule", "rule_and_general", "general")
            and row["window_tokens"] < 1000
        ):
            raise TableError(
                f"kind {name}: a reviewed kind needs window_tokens of at least 1000"
            )
        if row["review"] == "none" and (
            row["ask_rules"] or row["checklist_skill_ending"]
        ):
            raise TableError(f"kind {name}: review none asks nothing")
    return data


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict:  # noqa: ARG001 - the argument is the cache key (re-read when the file changes)
    return _check(json.loads(TABLE_PATH.read_text(encoding="utf-8")))


def table() -> dict:
    """The whole file, re-read when it changes on disk. Raises `TableError` when the file is missing or malformed."""
    try:
        return _load(TABLE_PATH.stat().st_mtime)
    except (OSError, ValueError) as exc:  # a json error is a ValueError
        if isinstance(exc, TableError):
            raise
        raise TableError(
            f"the kind table could not be read ({type(exc).__name__})"
        ) from exc


def problem() -> str | None:
    """Why the table cannot be used (plain words, no paper text), or None. A bad table never stops the app: every accessor below
    then answers as if no kind may be reviewed, and a review is refused with this reason."""
    try:
        table()
    except TableError as exc:
        return str(exc)
    return None


#: What a kind with no row, or any kind when the table is bad, gets: nothing is asked, nothing is sent.
NO_REVIEW = {
    "review": "none", "rules_of_kind": [], "ask_rules": False, "checklist_skill_ending": None,
    "checklist_slot": "none: the kind has no row in the table (or the table is unusable)", "no_main_equipment": False,
    "window_tokens": 0, "overlap_pages": 0, "crs_discipline": "", "label": "Unknown", "scored": False,
    "contractor_copy_ai_verdict": False,
}  # fmt: skip


def _kinds() -> dict:
    try:
        return table()["kinds"]
    except TableError:
        return {}


def norm(kind: str | None) -> str:
    k = str(kind or "").strip().lower().replace(" ", "_")
    return k if k else UNKNOWN


def row(kind: str | None) -> dict:
    """The row of a kind. A kind with no row is treated as `unknown` (asks nothing); `has_row` tells them apart."""
    return _kinds().get(norm(kind)) or _kinds().get(UNKNOWN) or NO_REVIEW


def has_row(kind: str | None) -> bool:
    return norm(kind) in _kinds()


def kinds() -> tuple[str, ...]:
    return tuple(_kinds())


def kinds_with(review: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(k for k, r in _kinds().items() if r["review"] in review)


def rule_review_kinds() -> tuple[str, ...]:
    """Kinds whose first review is the rule review alone."""
    return kinds_with(("rule",))


def general_kinds() -> tuple[str, ...]:
    """Kinds that get the GENERAL review (alone or after the rule review)."""
    return kinds_with(("general", "rule_and_general"))


def asks_rules(kind: str | None) -> bool:
    return bool(row(kind)["ask_rules"])


def no_main_equipment_kinds() -> tuple[str, ...]:
    return tuple(k for k, r in _kinds().items() if r["no_main_equipment"])


def checklist_ending(kind: str | None) -> str | None:
    return row(kind)["checklist_skill_ending"]


def checklist_slot(kind: str | None) -> str:
    return str(row(kind)["checklist_slot"])


def discipline(kind: str | None) -> str:
    return str(row(kind)["crs_discipline"] or "")


def contractor_copy_ai_verdict(kind: str | None) -> bool:
    """Do guarded "AI verdict: not met" rows go on the CONTRACTOR copy of this kind? False for every kind (owner, 12 Nov 2026):
    a person sets a kind to true after the scorer shows two-reader verdicts right 95 of 100 on that kind's key."""
    return bool(row(kind)["contractor_copy_ai_verdict"])


def scored_kinds() -> tuple[str, ...]:
    """The kinds whose `scored` field is true (the ONE home of "scored against an answer key")."""
    return tuple(k for k in kinds() if row(k)["scored"])


def scored(kind: str | None) -> bool:
    """True only for a kind whose review was scored against an answer key. A kind not scored does not go live (owner, 12 Nov)."""
    return bool(row(kind)["scored"])


def window_settings(kind: str | None) -> tuple[int, int]:
    r = row(kind)
    return int(r["window_tokens"]), int(r["overlap_pages"])


def page_rule() -> str:
    return str((_kinds() and table())["page_strategy_rule"]) if not problem() else ""


def windows(pages: dict[int, str], kind: str | None) -> list[list[int]]:
    """The deterministic page split of a paper of this kind (the rule is `page_rule()`): the window size and the overlap come
    from the kind's row; the walk is `agent_general_review.window_pages`, the one implementation."""
    from . import agent_general_review as core

    limit, overlap = window_settings(kind)
    if limit <= 0:
        return []
    return core.window_pages(pages, limit, overlap)


CONTRACTOR_COPY_PLAIN = "The contractor file holds only what code proved, or your own words. It never carries an AI wording."
CONTRACTOR_COPY_WITH_VERDICTS = (
    'The contractor file holds what code proved, your own words, and the AI\'s "not met" verdicts that two readers agreed on and code '
    "checked, which this kind of paper allows."
)


def contractor_copy_words(kind: str | None) -> str:
    """What the AI review's contractor copy holds for this kind, in plain words, from `contractor_copy_ai_verdict` (the review page says
    this; it never claims a fixed thing)."""
    return (
        CONTRACTOR_COPY_WITH_VERDICTS
        if contractor_copy_ai_verdict(kind)
        else CONTRACTOR_COPY_PLAIN
    )
