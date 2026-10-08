"""Dependabot configuration (`.github/dependabot.yml`).

React refuses to run when `react` and `react-dom` are on different versions
("Incompatible React versions"). PR #383 bumped `react` and `@types/react` but
left `react-dom` behind, and every frontend test file failed. A Dependabot group
makes the four React packages move in one PR. These tests read the config file,
so deleting the group or dropping a package from it fails them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[2] / ".github" / "dependabot.yml"
REACT_PACKAGES = {"react", "react-dom", "@types/react", "@types/react-dom"}


@pytest.fixture(scope="module")
def npm() -> dict:
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    entries = [u for u in doc["updates"] if u["package-ecosystem"] == "npm"]
    assert len(entries) == 1, "one npm entry, for /frontend"
    return entries[0]


def test_react_packages_update_in_one_group(npm):
    groups = npm.get("groups") or {}
    assert groups, "the npm entry has no Dependabot groups"
    together = [g for g in groups.values() if REACT_PACKAGES <= set(g.get("patterns", []))]
    assert together, f"no single group lists all of {sorted(REACT_PACKAGES)}"


def test_the_react_group_holds_only_react_packages(npm):
    # A wider pattern (e.g. "*") would sweep unrelated packages into the React PR.
    react_groups = [g for g in (npm.get("groups") or {}).values() if "react" in g.get("patterns", [])]
    assert len(react_groups) == 1, "exactly one npm group names react"
    assert set(react_groups[0]["patterns"]) == REACT_PACKAGES
