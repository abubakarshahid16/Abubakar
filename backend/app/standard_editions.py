"""Editions of a standard, each kept with its date, and which edition a contract applies (#805, order 3 Nov STEP 5).

THE REGISTER. `standard_edition` holds one row per (family, edition) with the date it was issued. It is append-only:
triggers refuse UPDATE, DELETE and INSERT OR REPLACE, so an edition is never superseded in the record or removed; a
newer edition is another row. A date is required: an edition with no date is not registered (never guessed).

THE CHOICE. `pick` is a pure function: editions + one contract's cutoff rule -> the edition(s) to check against.
The cutoff rule is DATA (`reference/edition_cutoff.json`, or the file named by EDITION_CUTOFF_FILE), not code per
contract (CLAUDE.md rule 13). Two rule names, one date each: 'in_effect_on' and 'latest_at_award' both take the latest
edition issued on or before the date; a family listed in `always_latest_families` takes its newest edition whatever
the date. When the FEED names another edition and the rule says 'strictest', BOTH editions are returned and
`strictest` picks the harder requirement per comparator. A date too coarse to tell, a missing date or an edition
not on file is `needs_engineer`, never a guess (rule 4).

OFF by default (STANDARD_EDITIONS_ENABLED): the table is created only on a database COPY, by `ensure_schema`; nothing
at startup calls it, and it refuses a live-shaped file. The pure functions need no switch and touch nothing.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import live_guard
from .config import settings

POLICY_FILE = Path(__file__).parent / "reference" / "edition_cutoff.json"
RULES = ("in_effect_on", "latest_at_award")
FEED_CONFLICTS = ("strictest", "none")
PICKED, BOTH, NEEDS_ENGINEER = "picked", "strictest_of_both", "needs_engineer"


class SwitchedOff(RuntimeError):
    """STANDARD_EDITIONS_ENABLED is off, so nothing was read or written."""


class RefusedLive(RuntimeError):
    """The register goes on a database copy, never on a live-shaped file."""


class BadPolicy(ValueError):
    """A cutoff rule the owner's file gets wrong; says which entry and why."""


# ---------------------------------------------------------------------------------------------------- dates

_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def date_span(text) -> tuple[date, date] | None:
    """The first and last day an ISO date can mean: '2023-06-10' is one day, '2023-06' the month, '2023' the year.
    None when it is not a date. A coarse date is a span, so a cutoff inside it is not decided by guessing."""
    found = _DATE.match(str(text or "").strip())
    if not found:
        return None
    year, month, day = found.group(1), found.group(2), found.group(3)
    try:
        if day:
            one = date(int(year), int(month), int(day))
            return one, one
        if month:
            first = date(int(year), int(month), 1)
            nxt = date(int(year) + (int(month) == 12), int(month) % 12 + 1, 1)
            return first, date.fromordinal(nxt.toordinal() - 1)
        return date(int(year), 1, 1), date(int(year), 12, 31)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------------- policy


def load_policies(path: str | os.PathLike | None = None) -> dict[str, dict]:
    """The contracts' cutoff rules from the owner's file, each checked. A wrong entry raises `BadPolicy` naming it:
    a cutoff nobody can read must not pick an edition."""
    file = Path(path or os.environ.get("EDITION_CUTOFF_FILE") or POLICY_FILE)
    contracts = json.loads(file.read_text(encoding="utf-8")).get("contracts") or {}
    for name, rule in contracts.items():
        if rule.get("rule") not in RULES:
            raise BadPolicy(f"{name}: rule must be one of {', '.join(RULES)}")
        if (
            date_span(rule.get("date")) is None
            or date_span(rule["date"])[0] != date_span(rule["date"])[1]
        ):
            raise BadPolicy(f"{name}: date must be one full day, YYYY-MM-DD")
        if rule.get("feed_conflict", "none") not in FEED_CONFLICTS:
            raise BadPolicy(
                f"{name}: feed_conflict must be one of {', '.join(FEED_CONFLICTS)}"
            )
        if not isinstance(rule.get("always_latest_families", []), list):
            raise BadPolicy(f"{name}: always_latest_families must be a list")
    return contracts


def _in_family(family: str, listed: str) -> bool:
    """'SAES-B-014' is in 'SAES-B'; 'SAES-BX' is not."""
    f, p = family.strip().upper(), listed.strip().upper()
    return bool(p) and (f == p or f.startswith(p + "-") or f.startswith(p + " "))


def clean_edition(value) -> str | None:
    """The edition as a finding stores it: trimmed, and None when blank ("edition not recorded" prints for None)."""
    return str(value).strip() or None if value is not None else None


def ensure_finding_column(conn) -> None:
    """The edition column on `review_findings`, added where a version 2 finding is written (the finding table's own
    schema is not grown for it). A finding with no edition keeps NULL and the CRS says "edition not recorded"."""
    from .db import add_column_if_missing

    add_column_if_missing(conn, "review_findings", "standard_edition", "TEXT")


# ---------------------------------------------------------------------------------------------------- the choice


@dataclass(frozen=True)
class Pick:
    status: str  # picked | strictest_of_both | needs_engineer
    editions: tuple[
        str, ...
    ]  # what to check against; empty when status is needs_engineer
    reason: str  # one sentence a reader can follow; never document words


def _held(editions) -> tuple[list[tuple[str, tuple[date, date]]], list[str]]:
    """(edition, date span) for those with a readable date, and the names of those without."""
    dated, undated = [], []
    for item in editions:
        span = date_span(item.get("date"))
        (
            dated.append((str(item["edition"]), span))
            if span
            else undated.append(str(item["edition"]))
        )
    return dated, undated


def pick(editions, policy: dict, family: str, feed_edition: str | None = None) -> Pick:
    """The edition(s) of `family` this contract applies. `editions` are {'edition', 'date'} rows; `policy` one entry
    of `load_policies`. Pure: reads nothing, writes nothing."""
    dated, undated = _held(editions)
    if not dated:
        return Pick(
            NEEDS_ENGINEER,
            (),
            "no edition of this standard is on file with a readable date",
        )
    if any(_in_family(family, f) for f in policy.get("always_latest_families", [])):
        newest = max(dated, key=lambda d: d[1][1])
        # Two editions whose dates overlap cannot be ordered by date alone.
        if any(e != newest[0] and s[1] >= newest[1][0] for e, s in dated):
            return Pick(
                NEEDS_ENGINEER,
                (),
                "the newest edition cannot be told from the date alone",
            )
        chosen = newest[0]
        basis = "newest edition (this family always uses the latest)"
    else:
        cutoff = date_span(policy["date"])[0]
        in_time = [(e, s) for e, s in dated if s[1] <= cutoff]
        straddle = [e for e, s in dated if s[0] <= cutoff < s[1]]
        if straddle:
            return Pick(
                NEEDS_ENGINEER,
                (),
                f"edition {straddle[0]} has a date too coarse to tell if it came before the cutoff",
            )
        if not in_time:
            return Pick(
                NEEDS_ENGINEER,
                (),
                "no edition on file was issued on or before the cutoff date",
            )
        best = max(in_time, key=lambda d: d[1][1])
        if any(e != best[0] and s[1] >= best[1][0] for e, s in in_time):
            return Pick(
                NEEDS_ENGINEER,
                (),
                "two editions on file have overlapping dates; the later one cannot be told",
            )
        chosen = best[0]
        basis = f"latest edition on or before {policy['date']}"
    note = (
        f"; {len(undated)} edition(s) on file have no readable date and were not used"
        if undated
        else ""
    )
    if (
        feed_edition
        and policy.get("feed_conflict") == "strictest"
        and str(feed_edition) != chosen
    ):
        if str(feed_edition) not in {e for e, _s in dated}:
            return Pick(
                NEEDS_ENGINEER,
                (),
                "the FEED names an edition that is not on file" + note,
            )
        return Pick(
            BOTH,
            (chosen, str(feed_edition)),
            f"{basis}; the FEED names another edition, so the stricter requirement wins"
            + note,
        )
    return Pick(PICKED, (chosen,), basis + note)


def strictest(values, comparator: str):
    """The harder of several limits for one comparator: '>=' and '>' want the highest, '<=' and '<' the lowest.
    None when there is no value or the comparator is not one of those four (nothing is guessed)."""
    numbers = [
        v for v in values if isinstance(v, int | float) and not isinstance(v, bool)
    ]
    if not numbers or comparator not in (">=", ">", "<=", "<"):
        return None
    return max(numbers) if comparator in (">=", ">") else min(numbers)


# ---------------------------------------------------------------------------------------------------- the register

_TABLE = """CREATE TABLE standard_edition (
    id TEXT PRIMARY KEY, family TEXT NOT NULL CHECK (length(trim(family)) > 0),
    edition TEXT NOT NULL CHECK (length(trim(edition)) > 0), issued_on TEXT NOT NULL CHECK (length(issued_on) >= 4),
    document_id TEXT, recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE (family, edition))"""
_GUARDS = (
    *(
        f"CREATE TRIGGER standard_edition_no_{verb.lower()} BEFORE {verb} ON standard_edition"
        f" BEGIN SELECT RAISE(ABORT, 'editions: standard_edition is append-only'); END"
        for verb in ("UPDATE", "DELETE")
    ),
    "CREATE TRIGGER standard_edition_no_replace BEFORE INSERT ON standard_edition"
    " WHEN EXISTS (SELECT 1 FROM standard_edition t WHERE t.id = NEW.id)"
    " BEGIN SELECT RAISE(ABORT, 'editions: standard_edition is never replaced'); END",
)


def _require_on() -> None:
    if not settings.standard_editions_enabled:
        raise SwitchedOff(
            "STANDARD_EDITIONS_ENABLED is off; nothing was read or written"
        )


def ensure_schema(conn=None) -> None:
    """Create the register on a copy; twice does nothing. Refuses a live-shaped file. Called with no connection, the
    way the app's schema walk calls every module, it does nothing: only a script on a copy creates the table."""
    if conn is None:
        return
    _require_on()
    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path and live_guard.is_live_shaped(path):
        raise RefusedLive("this is a live-shaped database; run on a copy")
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'standard_edition'"
    ).fetchone():
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in (_TABLE, *_GUARDS):
            conn.execute(statement)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def add_edition(
    conn,
    family: str,
    edition: str,
    issued_on: str,
    actor: str,
    document_id: str | None = None,
) -> str:
    """Register one edition with its date. A date that is not YYYY, YYYY-MM or YYYY-MM-DD is refused."""
    _require_on()
    if date_span(issued_on) is None:
        raise ValueError(
            "an edition is registered with its issue date as YYYY, YYYY-MM or YYYY-MM-DD"
        )
    new = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO standard_edition (id, family, edition, issued_on, document_id, recorded_by, recorded_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                new,
                family.strip(),
                edition.strip(),
                issued_on.strip(),
                document_id,
                actor,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
    return new


def editions_of(conn, family: str) -> list[dict]:
    """Every edition on file for the family, oldest first, as `pick` reads them. No table: none."""
    try:
        rows = conn.execute(
            "SELECT edition, issued_on, document_id FROM standard_edition WHERE family = ? ORDER BY issued_on, rowid",
            (family.strip(),),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"edition": r[0], "date": r[1], "document_id": r[2]} for r in rows]
