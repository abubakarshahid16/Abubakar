"""#820 (S4): no Claude Code session in this repository may read or edit
`backend/.env`, where the keys live (CLAUDE.md rule 2).

`.claude/settings.json` is committed, so every checkout and worktree carries
it. The `/` form anchors at the session's working directory (the repo
root); the `**/` form also matches when a session starts in a subfolder.
Removing a rule, or the file, turns this red.
"""
from __future__ import annotations

import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"
REQUIRED = ("Read(/backend/.env)", "Edit(/backend/.env)",
            "Read(**/backend/.env)", "Edit(**/backend/.env)")


def test_the_env_file_is_denied_to_every_agent_session():
    deny = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    missing = [rule for rule in REQUIRED if rule not in deny]
    assert not missing, f".claude/settings.json no longer denies: {missing}"


def test_the_settings_file_grants_nothing():
    """A committed project file only narrows: it must never allow a tool
    for every session (that is each person's own local choice)."""
    permissions = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    assert not permissions.get("allow"), "a committed allow rule widens every session"
    assert "defaultMode" not in permissions
