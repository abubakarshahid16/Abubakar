"""ROUTE BY KIND, IN CODE (order 14, planner 25 Nov 2026 23:35 (b) item 3; builder H). Not an AI manager: one table,
`reference/kind_route.json`, says per review FAMILY of the one kind list (`kind_list`, builder G) what the general review does
with a paper: the rule kind labels its rules come from, the kind whose method books apply, the checklist's coverage floor, the
after-judge steps it may skip, and the reviewers that may judge it.

THE SWITCH (KIND_ROUTE_ENABLED, off). Off, every answer here is the code's own answer from before the table, read from the
same constants (`aim_review.library.KIND_LABELS`, `ROLE_KIND`, the kind table's no-main-equipment floor), every step runs and
only the general judge is named: byte for byte today's routing. On, the table answers. The table starts EQUAL to today for
every kind (`differences_from_today`, a test), so the switch changes nothing until a row is edited on purpose.

SAFE BY SHAPE. A skipped step can only be one the table lists as `skippable` (never the no-ask mark, never a code check of a
verdict). A step's own kind check still runs inside it (the contract's code checks still ask whether the paper is a contract):
the table can only narrow what runs, never widen it. A reviewer name is only a name: builder A's discipline reviewers still
choose by their own table and switch (`aim_review.disciplines`). A table that cannot be read routes as today and says so in the
log (class only). Reads one file; no model, no network, no write.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

PATH = Path(__file__).parent / "reference" / "kind_route.json"
FIELDS = (
    "rules_of_kind",
    "method_books_kind",
    "checklist_floor",
    "skip_steps",
    "reviewers",
)
GENERAL = "general"
#: The method's step names a row may skip (the table's `skippable` must be a part of these).
STEPS = (
    "reference_papers",
    "second_read",
    "whole_paper_check",
    "editor",
    "contract_code",
)


class RouteError(ValueError):
    """The table is missing or malformed."""


@dataclass(frozen=True)
class Route:
    kind: str
    family: str | None
    rules_of_kind: tuple[str, ...]
    method_books_kind: str | None
    checklist_floor: int
    skip_steps: frozenset[str]
    reviewers: tuple[str, ...]
    source: str  # "today" (switch off, or the table unreadable) | "table"

    def runs(self, step: str) -> bool:
        return step not in self.skip_steps


def enabled() -> bool:
    from .config import settings

    return bool(getattr(settings, "kind_route_enabled", False))


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict:  # noqa: ARG001 - the cache key: re-read when the file changes
    from . import kind_list

    data = json.loads(PATH.read_text(encoding="utf-8"))
    skippable, names = (
        set(data.get("skippable") or ()),
        set(data.get("reviewers") or ()),
    )
    if not skippable <= set(STEPS) or GENERAL not in names:
        raise RouteError("skippable steps or reviewer names are not the method's")
    rows = {"default": data.get("default"), **(data.get("families") or {})}
    unknown = set(data.get("families") or {}) - set(kind_list.families())
    if unknown:
        raise RouteError(f"families not on the kind list: {sorted(unknown)}")
    for name, row in rows.items():
        if not isinstance(row, dict) or any(f not in row for f in FIELDS):
            raise RouteError(f"row {name}: needs {FIELDS}")
    for name, row in [*rows.items(), *(data.get("kinds") or {}).items()]:
        if (
            not set(row.get("skip_steps") or ()) <= skippable
            or not set(row.get("reviewers") or [GENERAL]) <= names
        ):
            raise RouteError(
                f"row {name}: a step it may not skip, or a reviewer not named"
            )
        if "checklist_floor" in row and (
            not isinstance(row["checklist_floor"], int) or row["checklist_floor"] < 0
        ):
            raise RouteError(f"row {name}: the floor is a whole number")
    return data


def table() -> dict:
    try:
        return _load(PATH.stat().st_mtime)
    except (OSError, ValueError) as exc:
        if isinstance(exc, RouteError):
            raise
        raise RouteError(
            f"the route table could not be read ({type(exc).__name__})"
        ) from exc


def family_of(kind: str | None) -> str | None:
    """The review family of a METHOD kind ("test record", "other" ...), from the one kind list; None for other or unknown."""
    from . import kind_list

    return kind_list.family_of(str(kind or "").strip().lower().replace(" ", "_"))


def floor_today(kind: str | None) -> int:
    """The checklist floor before the table: FLOOR_ITEMS for a kind with no main equipment (`kind_review_table`), else 0 (the
    method's own floor, the lead, 18 Nov 2026); an unreadable kind table gives no floor, never a stop."""
    from . import kind_review_table
    from .aim_review.library import FLOOR_ITEMS

    try:
        long_kinds = kind_review_table.no_main_equipment_kinds()
    except Exception as exc:  # noqa: BLE001 - as before: no floor, logged
        log.info(
            "general review: kind table not read for the floor (%s)", type(exc).__name__
        )
        return 0
    return (
        FLOOR_ITEMS
        if str(kind or "").strip().lower().replace(" ", "_") in long_kinds
        else 0
    )


def today(kind: str | None) -> Route:
    """The route the code took before the table, from its own constants (the switch-off answer)."""
    from .aim_review import library as L

    k = str(kind or "")
    return Route(
        kind=k,
        family=family_of(k),
        rules_of_kind=tuple(L.KIND_LABELS.get(k) or ("other",)),
        method_books_kind=L.ROLE_KIND.get(k),
        checklist_floor=floor_today(k),
        skip_steps=frozenset(),
        reviewers=(GENERAL,),
        source="today",
    )


def from_table(kind: str | None) -> Route:
    """The table's route for a method kind: the kind's row over its family's row (the default row for no family)."""
    data = table()
    k = str(kind or "")
    fam = family_of(k)
    row = {
        **data["default"],
        **((data.get("families") or {}).get(fam) or {}),
        **((data.get("kinds") or {}).get(k) or {}),
    }
    return Route(
        kind=k,
        family=fam,
        rules_of_kind=tuple(row["rules_of_kind"]) or ("other",),
        method_books_kind=row["method_books_kind"],
        checklist_floor=int(row["checklist_floor"]),
        skip_steps=frozenset(row["skip_steps"]),
        reviewers=tuple(row["reviewers"]) or (GENERAL,),
        source="table",
    )


def route(kind: str | None) -> Route:
    """THE route of a method kind: the table's when the switch is on and the table reads, else today's."""
    if not enabled():
        return today(kind)
    try:
        return from_table(kind)
    except RouteError as exc:
        log.warning("kind route table not used: %s", type(exc).__name__)
        return today(kind)


def differences_from_today(kinds) -> list[str]:
    """Plain words for every kind whose table route is not today's (rule labels, books kind, floor, steps); reviewers aside:
    today names only the general judge, and the table names who MAY judge (builder A's switch decides)."""
    out = []
    for k in kinds:
        a, b = today(k), from_table(k)
        for f in (
            "rules_of_kind",
            "method_books_kind",
            "checklist_floor",
            "skip_steps",
        ):
            if getattr(a, f) != getattr(b, f):
                out.append(
                    f"{k}: {f} is {getattr(b, f)!r} in the table, {getattr(a, f)!r} today"
                )
    return out
