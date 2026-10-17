"""#521: the dependency audit runs on every pull request and nightly, and
GATES on the packages the app runs on. These tests read the workflow file,
so weakening the gate fails them."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "dependency-audit.yml"


@pytest.fixture(scope="module")
def flow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _runs(job: dict) -> list[str]:
    return [s.get("run", "") for s in job["steps"]]


def test_it_runs_on_every_pull_request_and_on_a_schedule(flow):
    # PyYAML reads the bare key `on` as True
    triggers = flow.get("on", flow.get(True))
    assert "pull_request" in triggers and triggers["schedule"]
    assert flow["permissions"] == {"contents": "read"}


def test_the_python_requirements_are_audited_with_a_pinned_tool(flow):
    runs = _runs(flow["jobs"]["python"])
    assert any("pip-audit==" in r for r in runs), "the tool is pinned"
    audit = [r for r in runs if "pip_audit" in r]
    assert audit and "-r backend/requirements.txt" in audit[0]
    assert "|| " not in audit[0] and "continue-on-error" not in str(flow["jobs"]["python"])


def test_the_frontend_production_packages_are_a_gate(flow):
    job = flow["jobs"]["frontend"]
    gate = [s for s in job["steps"] if "--omit=dev" in s.get("run", "")]
    assert len(gate) == 1
    assert "--audit-level=high" in gate[0]["run"] and "||" not in gate[0]["run"]
    assert not gate[0].get("continue-on-error")
    assert gate[0]["working-directory"] == "frontend"


def test_every_ignored_advisory_names_its_tracking_issue(flow):
    """An ignore is the documented way through an advisory with no fix yet;
    one without an issue number is an advisory silently switched off."""
    ignores = re.findall(r"--ignore-vuln\s+(\S+)", " ".join(_runs(flow["jobs"]["python"])))
    text = WORKFLOW.read_text(encoding="utf-8")
    for vuln in ignores:
        assert re.search(rf"# ignore {re.escape(vuln)}: .*#\d+", text), f"{vuln} has no tracking issue"


def test_an_ignore_without_an_issue_is_refused(tmp_path, monkeypatch):
    import sys
    module = sys.modules[__name__]
    bare = WORKFLOW.read_text(encoding="utf-8").replace(
        "--progress-spinner off", "--progress-spinner off --ignore-vuln GHSA-xxxx-yyyy-zzzz")
    fake = tmp_path / "dependency-audit.yml"
    fake.write_text(bare, encoding="utf-8")
    monkeypatch.setattr(module, "WORKFLOW", fake)
    with pytest.raises(AssertionError, match="no tracking issue"):
        test_every_ignored_advisory_names_its_tracking_issue(yaml.safe_load(bare))
