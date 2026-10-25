"""#806 S2: the AI register (`docs/security/ai-register.md`) must match the
AI switches in `backend/app/config.py`, by name and by default, and every
control file of the security pack must exist.

An AI switch is a setting whose name names an AI step (`AI_WORDS`) and that
is either a `*_enabled` flag or a `*_provider` / `*_reader` / `*_engine`
selector (which engine answers: local model or Claude API). A new
switch, a removed one or a changed default fails this check until the
register says so - "every AI service is added to the register before use".

Run: python scripts/check_ai_register.py   (exit 1 with the differences)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "security"
REGISTER = DOCS / "ai-register.md"
#: S1-S12, one file each, plus the index.
CONTROL_FILES = ("README.md", "responsibilities.md", "ai-register.md", "data-classification.md",
                 "least-privilege.md", "logging.md", "approvals.md", "kill-switch.md",
                 "incident-response.md", "severity-and-roles.md", "exercises.md", "evidence.md",
                 "threat-levels.md")
CONTROL_FILES += ("drill-pack.md",)
AI_WORDS = re.compile(r"(^|_)(ai|reasoning|judge|match|model|reader|wording|vision|llm)(_|$)")
_ROW = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]*)`\s*\|")
SWITCH_HEADING = "## AI switches"


def is_switch(name: str, kind: type) -> bool:
    """A setting is an AI switch when its name names an AI step and it turns
    the step on or off, or chooses the engine that answers it."""
    if not AI_WORDS.search(name):
        return False
    return (kind is bool and name.endswith("_enabled")) or (
        kind is str and name.endswith(("_provider", "_reader", "_engine")))


def config_switches() -> dict[str, str]:
    """{name: default as text} for every AI switch in the code."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings
    return {name: str(field.default) for name, field in Settings.model_fields.items()
            if is_switch(name, field.annotation)}


def register_switches(text: str) -> dict[str, str]:
    """{name: default} from the register's switch table (rows under the
    switch heading whose first two cells are code-quoted)."""
    _, _, section = text.partition(SWITCH_HEADING)
    out = {}
    for line in section.splitlines():
        if line.startswith("## "):
            break
        match = _ROW.match(line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


def problems() -> list[str]:
    found = [f"missing control file: docs/security/{name}"
             for name in CONTROL_FILES if not (DOCS / name).is_file()]
    if not REGISTER.is_file():
        return found
    listed = register_switches(REGISTER.read_text(encoding="utf-8"))
    actual = config_switches()
    for name in sorted(set(actual) - set(listed)):
        found.append(f"AI switch not in the register: {name} (default {actual[name]})")
    for name in sorted(set(listed) - set(actual)):
        found.append(f"register lists a switch config.py does not have: {name}")
    for name in sorted(set(actual) & set(listed)):
        if actual[name] != listed[name]:
            found.append(f"default differs for {name}: config.py {actual[name]}, register {listed[name]}")
    return found


def main() -> int:
    found = problems()
    for line in found:
        print(f"FAIL: {line}")
    if not found:
        print(f"OK: docs/security has all {len(CONTROL_FILES)} files and the AI register "
              f"matches the {len(config_switches())} AI switches in config.py")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
