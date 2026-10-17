"""#821 (S5, Q40): the weekly log check, as one read-only command.

`docs/security/logging.md` asks s2 to post a weekly check on #692 covering
Claude spend against the caps, unusual calls, and failed logins. This prints
that check, ready to paste. It reads; it never writes:

  * the Claude spend ledger (`claude_spend.jsonl`) through `claude_spend`'s
    own reader, so a torn line counts the way the caps count it;
  * the database opened `mode=ro` by URI - it cannot write the live DB and
    cannot create a missing one (a wrong path is refused, not reported empty).

Counts, steps, models, outcomes and account names only. No prompt, no
document id, no document text is printed (CLAUDE.md rule 1).

"Unusual" means something a person should look at, each counted:
  * a model the price table does not know (charged at the dearest price);
  * a step first seen in this window (new since the last check);
  * a refused call (document not approved), an unreadable ledger line, a
    reservation never settled, or a call settled at an estimate;
  * a step or the total at 80 % of its cap or more.

Usage:
  python scripts/weekly_log_check.py [--days 7] [--ledger PATH] [--db PATH]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import claude_spend
from app.config import settings

#: Share of a cap at which the check flags it.
NEAR_CAP = 0.8


def _when(entry: dict) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(entry.get("at")))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _known_model(model: str | None) -> bool:
    """The price table's own matching rule (`claude_spend.price_for`): an
    exact key, a key plus a suffix, or a key plus a date."""
    name = (model or "").lower()
    return any(name == key or name.startswith(key + "-")
               or re.fullmatch(rf"{re.escape(key)}-\d{{8}}", name)
               for key in claude_spend.PRICES)


def spend_section(since: datetime) -> list[str]:
    calls = claude_spend.entries()
    caps = claude_spend.Caps.from_settings()
    week = [e for e in calls if (_when(e) or since) >= since]
    before = {e.get("step") for e in calls if (_when(e) or since) < since}
    total = sum(float(e.get("cost_usd") or 0) for e in calls)
    per_step: Counter = Counter()
    for e in calls:
        per_step[e.get("step")] += float(e.get("cost_usd") or 0)

    lines = ["## Claude spend",
             f"- All time: USD {total:.4f} of the USD {caps.total:.2f} total cap"
             f" ({len(calls)} calls in the ledger).",
             f"- This window: USD {sum(float(e.get('cost_usd') or 0) for e in week):.4f}"
             f" over {len(week)} calls."]
    if not calls:
        lines.append("- The ledger has no calls (file missing or empty).")
        return lines
    lines += ["", "| Step | Calls this window | USD this window | USD all time | Step cap |",
              "|---|---|---|---|---|"]
    week_calls = Counter(e.get("step") for e in week)
    week_usd: Counter = Counter()
    for e in week:
        week_usd[e.get("step")] += float(e.get("cost_usd") or 0)
    for step in sorted(per_step, key=str):
        lines.append(f"| {step} | {week_calls.get(step, 0)} | {week_usd.get(step, 0.0):.4f}"
                     f" | {per_step[step]:.4f} | {caps.per_step:.2f} |")

    unusual = []
    unknown = Counter(e.get("model") for e in week
                      if e.get("model") and not _known_model(e.get("model")))
    for model, n in sorted(unknown.items()):
        unusual.append(f"model not in the price table: {model} ({n} calls)")
    for step in sorted({e.get("step") for e in week} - before, key=str):
        unusual.append(f"step first seen this window: {step} ({week_calls[step]} calls)")
    refused = Counter(e.get("refused") for e in week if e.get("refused"))
    for code, n in sorted(refused.items()):
        unusual.append(f"refused, document not approved ({code}): {n}")
    flags = (("corrupt", "unreadable ledger lines (each counts at the total cap)"),
             ("reserved", "reservations never settled (charged at their worst case)"),
             ("estimated", "calls settled at an estimate, usage not reported"))
    for key, words in flags:
        n = sum(1 for e in week if e.get(key))
        if n:
            unusual.append(f"{words}: {n}")
    for step, usd in sorted(per_step.items(), key=lambda kv: str(kv[0])):
        if usd >= NEAR_CAP * caps.per_step:
            unusual.append(f"step at {usd / caps.per_step:.0%} of its cap: {step}")
    if total >= NEAR_CAP * caps.total:
        unusual.append(f"total at {total / caps.total:.0%} of its cap")

    lines += ["", "## Unusual calls"]
    lines += [f"- {u}" for u in unusual] or ["- none found in this window"]
    return lines


def login_section(db_path: Path, since: datetime) -> list[str]:
    lines = ["## Failed logins"]
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        return [*lines, f"- could not check: the database did not open ({type(exc).__name__})"]
    try:
        rows = conn.execute(
            "SELECT outcome, actor_username FROM audit_events"
            " WHERE action = 'login_failed' AND at >= ?", (since.isoformat(timespec="seconds"),)).fetchall()
    except sqlite3.DatabaseError as exc:
        return [*lines, f"- could not check: audit_events did not read ({type(exc).__name__})"]
    finally:
        conn.close()
    if not rows:
        return [*lines, "- none in this window (audit_events, action login_failed)"]
    by_outcome = Counter(outcome for outcome, _ in rows)
    by_user = Counter(user or "(no name)" for _, user in rows)
    lines.append(f"- {len(rows)} in this window: "
                 + ", ".join(f"{k} {v}" for k, v in sorted(by_outcome.items())))
    lines += [f"- {user}: {n}" for user, n in by_user.most_common()]
    return lines


def report(*, days: int, now: datetime | None = None, db_path: Path) -> str:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    head = [f"# Weekly log check, {since.date()} to {now.date()} ({days} days)",
            "Boundary: this machine's Claude spend ledger and its database's audit_events."
            " Counts only; no prompt or document text.", ""]
    return "\n".join(head + spend_section(since) + [""] + login_section(db_path, since)) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--ledger", type=Path, help="default: settings.claude_spend_log")
    parser.add_argument("--db", type=Path, help="default: settings.db_path")
    args = parser.parse_args(argv)
    if args.ledger:
        settings.claude_spend_log = args.ledger
    sys.stdout.write(report(days=args.days, db_path=args.db or Path(settings.db_path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
