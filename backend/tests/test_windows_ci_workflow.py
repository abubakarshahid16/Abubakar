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
    """The shard job: it runs the suite (order 130, three ways)."""
    return win["jobs"]["backend-windows-shard"]


@pytest.fixture(scope="module")
def agg(win) -> dict:
    """The aggregate job, which keeps the old check name."""
    return win["jobs"]["backend-windows"]


def _triggers(doc: dict) -> dict:
    # PyYAML reads the bare key `on:` as the boolean True.
    return doc.get("on") or doc[True]


def _steps_text(job: dict) -> list[str]:
    return [(s.get("run") or s.get("uses") or "") for s in job["steps"]]


def _runs_suite(run: str) -> bool:
    """The step that runs the tests: not the install line, not the collection."""
    return "python -m pytest" in run and "--collect-only" not in run


def test_the_job_runs_on_windows(job):
    assert str(job["runs-on"]).startswith("windows")


def test_it_runs_the_real_backend_suite_from_the_backend_folder(job):
    suite = [s for s in job["steps"] if _runs_suite(s.get("run") or "")]
    assert len(suite) == 1
    assert suite[0].get("working-directory") == "backend"
    assert "-n auto" in suite[0]["run"]
    assert "--splits 3 --group ${{ matrix.group }}" in suite[0]["run"]
    # A `-k`, `--deselect`, `-m` or `--ignore` AFTER `pytest` would quietly shrink
    # what "passes" means. (`python -m pytest` itself has a `-m`, so look only at
    # the arguments that follow the word pytest.)
    args = suite[0]["run"].split("pytest", 1)[1].split()
    for narrowing in ("-k", "-m", "--deselect", "--ignore"):
        assert narrowing not in args
        assert not any(a.startswith(narrowing + "=") for a in args)


def test_the_models_are_staged_and_verified_before_the_suite_runs(job):
    runs = _steps_text(job)
    stage = next(
        i
        for i, r in enumerate(runs)
        if "fetch_models.py" in r and "--verify-only" not in r
    )
    verify = next(i for i, r in enumerate(runs) if "--verify-only" in r)
    suite = next(i for i, r in enumerate(runs) if _runs_suite(r))
    assert stage < verify < suite, (
        "a skipped suite reports success, so prove it is armed first"
    )


def test_it_uses_the_same_python_as_the_linux_job(job):
    # The Linux suite runs in the `backend-shard` matrix; `backend` is now the
    # aggregate required check and has no steps of its own (#584).
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))["jobs"]["backend-shard"]
    want = next(
        s["with"]["python-version"]
        for s in linux["steps"]
        if str(s.get("uses", "")).startswith("actions/setup-python")
    )
    got = next(
        s["with"]["python-version"]
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("actions/setup-python")
    )
    assert got == want


def test_it_does_not_reuse_a_name_the_linux_workflow_uses(win, job, agg):
    """A check that shared a name with a required one would be counted as it."""
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))
    linux_names = {linux["name"], *(j["name"] for j in linux["jobs"].values())}
    assert win["name"] not in linux_names
    assert job["name"] not in linux_names
    assert agg["name"] not in linux_names


def test_it_is_informational_and_says_so(win, agg):
    # The aggregate carries the old job's name: the check a train waits for.
    assert agg["name"] == "backend on Windows (pytest, informational)"
    assert "NOT one of the checks" in WINDOWS.read_text(encoding="utf-8")


def test_it_runs_nightly_and_on_demand_only(win):
    # Owner decision 2026-10-08 (CI trim): nightly on main plus workflow_dispatch,
    # not on pull requests or pushes, to save Actions minutes.
    triggers = _triggers(win)
    assert "workflow_dispatch" in triggers
    assert [s.get("cron") for s in triggers.get("schedule") or []], (
        "no nightly schedule"
    )
    assert "pull_request" not in triggers
    assert "push" not in triggers


def test_linux_tests_run_on_pull_requests_and_pushes_to_main_only():
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))
    triggers = _triggers(linux)
    assert "pull_request" in triggers
    assert (triggers.get("push") or {}).get("branches") == ["main"], (
        "a push to a PR branch already runs through pull_request"
    )


def test_it_asks_for_no_more_than_read_access(win):
    assert win["permissions"] == {"contents": "read"}


def test_it_has_a_time_limit(job, agg):
    assert 10 <= job["timeout-minutes"] <= 60
    assert 1 <= agg["timeout-minutes"] <= 15


def test_the_suite_runs_in_three_parallel_shards(job):
    """Order 130: one Windows job took about 20 of a train's 22 minutes."""
    assert job["strategy"]["matrix"]["group"] == [1, 2, 3]
    assert job["strategy"]["fail-fast"] is False
    install = next(
        s["run"] for s in job["steps"] if s.get("name") == "Install dependencies"
    )
    assert "pytest-split==" in install


def test_the_aggregate_needs_every_shard_and_proves_each_test_ran_once(agg):
    assert agg["needs"] == ["backend-windows-shard"]
    # Without always() a failed shard SKIPS the aggregate, and a skipped
    # check does not report failure.
    assert agg.get("if") == "always()"
    runs = "\n".join(s.get("run", "") for s in agg["steps"])
    assert 'test "${{ needs.backend-windows-shard.result }}" = "success"' in runs
    assert (
        "ci_test_ids.py compare --full test-ids/full.txt test-ids/shard-1.txt "
        "test-ids/shard-2.txt test-ids/shard-3.txt"
    ) in runs


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped"])
def test_the_aggregate_fails_on_a_failed_cancelled_or_skipped_shard(agg, bad):
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    step = next(
        s for s in agg["steps"] if s.get("name") == "Every Windows shard passed"
    )

    def run(result):
        script = step["run"].replace(
            "${{ needs.backend-windows-shard.result }}", result
        )
        return subprocess.run(
            [bash, "-e", "-c", script], capture_output=True
        ).returncode

    assert run("success") == 0
    assert run(bad) != 0


def test_windows_durations_never_reach_the_linux_shards(job, agg):
    """The Linux restore takes the newest cache whose key starts with its
    prefix; a Windows key under that prefix would split Linux by Windows times."""
    linux = yaml.safe_load(LINUX.read_text(encoding="utf-8"))["jobs"]["backend-shard"]
    linux_prefix = next(
        s["with"]["restore-keys"]
        for s in linux["steps"]
        if s.get("name") == "Restore the latest test durations"
    )
    restore = next(
        s
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("actions/cache/restore")
    )
    save = next(
        s
        for s in agg["steps"]
        if str(s.get("uses", "")).startswith("actions/cache/save")
    )
    for key in (
        restore["with"]["key"],
        restore["with"]["restore-keys"],
        save["with"]["key"],
    ):
        assert not key.startswith(linux_prefix), key
