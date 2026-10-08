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
def updates() -> list[dict]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["updates"]


@pytest.fixture(scope="module")
def npm(updates) -> dict:
    entries = [u for u in updates if u["package-ecosystem"] == "npm"]
    assert len(entries) == 1, "one npm entry, for /frontend"
    return entries[0]


def test_every_ecosystem_is_checked_weekly(updates):
    assert {u["package-ecosystem"] for u in updates} == {"pip", "npm", "github-actions"}
    assert all(u["schedule"]["interval"] == "weekly" for u in updates)


def test_minor_and_patch_updates_arrive_as_one_pr_per_ecosystem(updates):
    for u in updates:
        catch_all = [g for g in (u.get("groups") or {}).values()
                     if g.get("patterns") == ["*"] and set(g.get("update-types", [])) == {"minor", "patch"}]
        assert len(catch_all) == 1, f"{u['package-ecosystem']}: no single minor+patch group"


def test_the_react_group_comes_before_the_npm_catch_all(npm):
    # Dependabot puts a package in the FIRST group that matches; listed after the
    # catch-all, react minor/patch bumps would leave react-dom behind again.
    names = list(npm["groups"])
    react = next(n for n, g in npm["groups"].items() if "react" in g.get("patterns", []))
    catch_all = next(n for n, g in npm["groups"].items() if g.get("patterns") == ["*"])
    assert names.index(react) < names.index(catch_all)


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
