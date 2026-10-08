"""The Windows CI job (`.github/workflows/tests-windows.yml`).

It exists so a person does not have to run the suite by hand on Windows. These
tests pin the properties that make it a real, safe check and not a decoration:
it runs on Windows, it runs the real suite with the models staged and verified,
it cannot be mistaken for (or clobber) a required check, and it does not fire on
every push. They read the workflow file, so deleting or weakening the job fails
them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
WINDOWS = WORKFLOWS / "tests-windows.yml"
LINUX = WORKFLOWS / "tests.yml"


@pytest.fixture(scope="module")
def win() -> dict:
    return yaml.safe_load(WINDOWS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(win) -> dict:
    jobs = win["jobs"]
    assert len(jobs) == 1, "one Windows job, so its name identifies it"
    return next(iter(jobs.values()))


def _triggers(doc: dict) -> dict:
    # PyYAML reads the bare key `on:` as the boolean True.
    return doc.get("on") or doc[True]


def _steps_text(job: dict) -> list[str]:
    return [(s.get("run") or s.get("uses") or "") for s in job["steps"]]


def test_the_job_runs_on_windows(job):
    assert str(job["runs-on"]).startswith("windows")


def test_it_runs_the_real_backend_suite_from_the_backend_folder(job):
    suite = [s for s in job["steps"] if "pytest" in (s.get("run") or "")]
    assert len(suite) == 1
    assert suite[0].get("working-directory") == "backend"
    assert "-n auto" in suite[0]["run"]
    # A `-k`, `--deselect`, `-m` or `--ignore` AFTER `pytest` would quietly shrink
    # what "passes" means. (`python -m pytest` itself has a `-m`, so look only at
    # the arguments that follow the word pytest.)
    args = suite[0]["run"].split("pytest", 1)[1].split()
    for narrowing in ("-k", "-m", "--deselect", "--ignore"):
        assert narrowing not in args
        assert not any(a.startswith(narrowing + "=") for a in args)


def test_the_models_are_staged_and_verified_before_the_suite_runs(job):
    runs = _steps_text(job)
    stage = next(i for i, r in enumerate(runs) if "fetch_models.py" in r and "--verify-only" not in r)
    verify = next(i for i, r in enumerate(runs) if "--verify-only" in r)
    suite = next(i for i, r in enumerate(runs) if "pytest" in r)
    assert stage < verify < suite, "a skipped suite reports success, so prove it is armed first"


def test_it_uses_the_same_python_as_the_linux_job(job):
    # The Linux suite runs in the `backend-shard` matrix; `backend` is now the
    # aggregate required check and has no steps of its own (#584).
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))["jobs"]["backend-shard"]
    want = next(s["with"]["python-version"] for s in linux["steps"]
                if str(s.get("uses", "")).startswith("actions/setup-python"))
    got = next(s["with"]["python-version"] for s in job["steps"]
               if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert got == want


def test_it_does_not_reuse_a_name_the_linux_workflow_uses(win, job):
    """A check that shared a name with a required one would be counted as it."""
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))
    linux_names = {linux["name"], *(j["name"] for j in linux["jobs"].values())}
    assert win["name"] not in linux_names
    assert job["name"] not in linux_names


def test_it_is_informational_and_says_so(win, job):
    assert "informational" in job["name"].lower()
    assert "NOT one of the checks" in WINDOWS.read_text(encoding="utf-8")


def test_it_runs_nightly_and_on_demand_only(win):
    # Owner decision 2026-10-08 (CI trim): nightly on main plus workflow_dispatch,
    # not on pull requests or pushes, to save Actions minutes.
    triggers = _triggers(win)
    assert "workflow_dispatch" in triggers
    assert [s.get("cron") for s in triggers.get("schedule") or []], "no nightly schedule"
    assert "pull_request" not in triggers
    assert "push" not in triggers


def test_linux_tests_run_on_pull_requests_and_pushes_to_main_only():
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))
    triggers = _triggers(linux)
    assert "pull_request" in triggers
    assert (triggers.get("push") or {}).get("branches") == ["main"], \
        "a push to a PR branch already runs through pull_request"


def test_it_asks_for_no_more_than_read_access(win):
    assert win["permissions"] == {"contents": "read"}


def test_it_has_a_time_limit(job):
    assert 10 <= job["timeout-minutes"] <= 60
