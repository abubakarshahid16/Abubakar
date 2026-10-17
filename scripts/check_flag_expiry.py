"""#736 (F8): every on/off setting has a decision, and a rollout flag expires.

A flag left "for now" stays forever: the code keeps both paths, the tests keep
both paths, and nobody remembers which one the product is. `docs/flags.md`
lists every boolean setting in `backend/app/config.py` once, as one of:

  * `permanent` - a gate or an operator setting that is meant to stay a
    switch (an egress flag, a debug switch, TLS mode). It carries a reason.
  * `rollout`   - a switch that exists while a path is proven. It carries the
    date it was recorded (`since`) and a `decide by` date at most
    `MAX_DAYS` later; by then the owner makes it the default and the switch
    goes, removes the path, or extends it with a new `since` and a note.

This check fails when a boolean setting is missing from the register, the
register names one config.py does not have, a default differs, a rollout
row's window is longer than `MAX_DAYS` - or a rollout flag is past its
`decide by` date.

Run: python scripts/check_flag_expiry.py [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "flags.md"
MAX_DAYS = 14
KINDS = ("permanent", "rollout")
_ROW = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|(.*)$")


def config_flags() -> dict[str, str]:
    """{name: default as text} for every boolean setting."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings
    return {name: str(field.default) for name, field in Settings.model_fields.items()
            if field.annotation is bool}


def register_rows(text: str) -> dict[str, list[str]]:
    """{name: [default, kind, since, decide by, note]} from the table rows
    whose first cell is code-quoted."""
    out = {}
    for line in text.splitlines():
        match = _ROW.match(line)
        if match:
            cells = [c.strip().strip("`") for c in match.group(2).rstrip().rstrip("|").split("|")]
            out[match.group(1)] = (cells + [""] * 5)[:5]
    return out


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def problems(today: date, text: str | None = None, flags: dict[str, str] | None = None) -> list[str]:
    if text is None:
        if not REGISTER.is_file():
            return ["missing docs/flags.md"]
        text = REGISTER.read_text(encoding="utf-8")
    rows = register_rows(text)
    actual = config_flags() if flags is None else flags
    found = [f"flag not in docs/flags.md: {name} (default {actual[name]})"
             for name in sorted(set(actual) - set(rows))]
    found += [f"docs/flags.md lists a flag config.py does not have: {name}"
              for name in sorted(set(rows) - set(actual))]
    for name in sorted(set(actual) & set(rows)):
        default, kind, since, decide_by, note = rows[name]
        if default != actual[name]:
            found.append(f"default differs for {name}: config.py {actual[name]}, docs/flags.md {default}")
        if kind not in KINDS:
            found.append(f"{name}: kind must be one of {', '.join(KINDS)}, not {kind!r}")
        elif kind == "permanent" and not note:
            found.append(f"{name}: a permanent flag states why it stays a switch")
        elif kind == "rollout":
            start, end = _day(since), _day(decide_by)
            if start is None or end is None:
                found.append(f"{name}: a rollout flag needs `since` and `decide by` as YYYY-MM-DD")
            elif (end - start).days > MAX_DAYS:
                found.append(f"{name}: decide-by window is {(end - start).days} days; at most {MAX_DAYS}")
            elif today > end:
                found.append(f"{name}: EXPIRED on {end} - make it the default and remove the switch, "
                             f"remove the path, or extend it (new `since`, a note) with the owner")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat,
                        default=datetime.now(UTC).date())
    args = parser.parse_args(argv)
    found = problems(args.today)
    for line in found:
        print(f"FAIL: {line}")
    if not found:
        print(f"OK: every boolean setting is in docs/flags.md; no rollout flag past its date ({args.today})")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
