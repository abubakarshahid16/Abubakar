"""`docs/system-map.md` lists every app module once, one module per job (#725 F8a, #736).

Fails (exit 1) when:
  * a module in `backend/app` is not in the map, or is listed twice;
  * the map lists a module that does not exist;
  * two modules share a job and the job is not under "Known duplicates"
    with exactly those modules (a duplicate is a recorded debt, never silent).
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "backend" / "app"
MAP = REPO / "docs" / "system-map.md"
_ROW = re.compile(r"^\| `(?P<module>\w+)` \| (?P<job>.+?) \|\s*$")
_DUP = re.compile(r"^\| (?P<job>[^`|][^|]*?) \| (?P<modules>`.+`) \|\s*$")


def problems(text: str | None = None) -> list[str]:
    text = MAP.read_text(encoding="utf-8") if text is None else text
    modules = {p.stem for p in APP.glob("*.py") if p.stem != "__init__"}
    listed: dict[str, str] = {}
    duplicates: dict[str, set[str]] = {}
    out: list[str] = []
    for line in text.splitlines():
        row = _ROW.match(line)
        if row:
            name = row["module"]
            if name in listed:
                out.append(f"{name} is listed twice")
            listed[name] = row["job"].strip()
            continue
        dup = _DUP.match(line)
        if dup and dup["job"].strip() not in ("Job",):
            duplicates[dup["job"].strip()] = set(re.findall(r"`(\w+)`", dup["modules"]))
    for name in sorted(modules - set(listed)):
        out.append(f"backend/app/{name}.py is not in docs/system-map.md")
    for name in sorted(set(listed) - modules):
        out.append(f"docs/system-map.md lists {name}, which is not in backend/app")
    by_job: dict[str, set[str]] = defaultdict(set)
    for name, job in listed.items():
        by_job[job].add(name)
    for job, names in sorted(by_job.items()):
        if len(names) > 1 and duplicates.get(job) != names:
            out.append(f"job {job!r} is done by {', '.join(sorted(names))} and is not a recorded duplicate")
    return out


def main() -> int:
    found = problems()
    if found:
        print("\n".join(found))
        return 1
    print("OK: docs/system-map.md lists every backend/app module once, one module per job")
    return 0


if __name__ == "__main__":
    sys.exit(main())
