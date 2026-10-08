"""The Linux CI workflow (`.github/workflows/tests.yml`) after the speed-up (#584).

The backend suite runs in three parallel shards, and `backend (pytest)` - the
check `main` requires - is an aggregate job. These tests pin the properties that
keep that safe: the required check still fails when any shard fails, every
shard runs a distinct third of the suite, the caches really skip the installs,
and the `slow` tests run nightly instead of being dropped. They read the
workflow file, so weakening any of it fails them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _runs(job: dict) -> list[str]:
    return [s.get("run", "") for s in job["steps"]]


def _step(job: dict, uses_prefix: str, path: str) -> dict:
    return next(s for s in job["steps"]
                if str(s.get("uses", "")).startswith(uses_prefix) and s.get("with", {}).get("path") == path)


def test_the_required_check_is_an_aggregate_that_needs_every_shard(jobs):
    carriers = [j for j in jobs.values() if j["name"] == "backend (pytest)"]
    assert len(carriers) == 1, "exactly one job carries the required name"
    agg = carriers[0]
    assert set(agg["needs"]) == {"backend-shard", "backend-checks"}
    # Without always() a failed shard SKIPS the aggregate, and a skipped
    # required check does not report failure.
    assert agg.get("if") == "always()"
    script = "\n".join(_runs(agg))
    assert 'test "${{ needs.backend-shard.result }}" = "success"' in script
    assert 'test "${{ needs.backend-checks.result }}" = "success"' in script


def test_every_shard_runs_its_own_third_of_the_suite(jobs):
    shard = jobs["backend-shard"]
    assert shard["strategy"]["matrix"]["group"] == [1, 2, 3]
    assert shard["strategy"]["fail-fast"] is False
    run = next(r for r in _runs(shard) if "python -m pytest" in r)
    assert "-n auto" in run
    assert "--splits 3 --group ${{ matrix.group }}" in run


def test_benchmarks_lint_and_anchors_still_gate_the_required_check(jobs):
    runs = "\n".join(_runs(jobs["backend-checks"]))
    assert "python -m pytest -q -m benchmark" in runs
    assert "ruff check" in runs
    assert "check_mutation_anchors.py" in runs


def test_the_python_environment_is_cached_on_the_requirements(jobs):
    for name in ("backend-shard", "backend-checks"):
        job = jobs[name]
        cache = _step(job, "actions/cache", "~/venv")
        assert "hashFiles('backend/requirements.txt')" in cache["with"]["key"]
        install = next(s for s in job["steps"] if s.get("name") == "Install dependencies")
        assert install.get("if") == "steps.venv.outputs.cache-hit != 'true'"


def test_node_modules_is_cached_on_the_lock_file(jobs):
    job = jobs["frontend"]
    cache = _step(job, "actions/cache", "frontend/node_modules")
    assert "hashFiles('frontend/package-lock.json')" in cache["with"]["key"]
    install = next(s for s in job["steps"] if s.get("run") == "npm ci")
    assert install.get("if") == "steps.nm.outputs.cache-hit != 'true'"


def test_the_model_cache_is_kept(jobs):
    cache = _step(jobs["backend-shard"], "actions/cache", "backend/models")
    assert cache["with"]["key"] == "models-${{ hashFiles('scripts/fetch_models.py') }}"


def test_slow_tests_run_nightly_and_on_demand_only(jobs):
    slow = jobs["backend-slow"]
    assert slow.get("if") == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    assert any("-m slow" in r for r in _runs(slow))


def test_each_shard_records_and_uploads_the_tests_it_ran(jobs):
    shard = jobs["backend-shard"]
    run_step = next(s for s in shard["steps"] if "python -m pytest -q -n auto" in s.get("run", ""))
    assert "-p ci_test_ids" in run_step["run"]
    assert run_step["env"]["CI_TEST_IDS_OUT"].endswith("shard-${{ matrix.group }}.txt")
    upload = next(s for s in shard["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert upload.get("if") == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    collect = next(s for s in shard["steps"] if "--collect-only" in s.get("run", ""))
    assert collect["env"]["CI_COLLECT_OUT"].endswith("test-ids/full.txt")


def test_the_required_check_proves_every_test_ran_exactly_once(jobs):
    agg = jobs["backend"]
    audit = next(s for s in agg["steps"] if "ci_test_ids.py compare" in s.get("run", ""))
    for f in ("test-ids/full.txt", "test-ids/shard-1.txt", "test-ids/shard-2.txt", "test-ids/shard-3.txt"):
        assert f in audit["run"]


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped"])
def test_the_aggregate_fails_on_a_failed_cancelled_or_skipped_shard(jobs, bad):
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    step = next(s for s in jobs["backend"]["steps"] if s.get("name") == "Every shard and the checks job passed")

    def run(shard, checks):
        script = (step["run"].replace("${{ needs.backend-shard.result }}", shard)
                  .replace("${{ needs.backend-checks.result }}", checks))
        return subprocess.run([bash, "-e", "-c", script], capture_output=True).returncode

    assert run("success", "success") == 0
    assert run(bad, "success") != 0
    assert run("success", bad) != 0


def test_the_nightly_job_proves_every_slow_test_ran(jobs):
    runs = "\n".join(_runs(jobs["backend-slow"]))
    assert "--collect-only -q -m slow -p ci_test_ids" in runs
    assert "ci_test_ids.py compare --full ../slow-full.txt ../slow-ran.txt" in runs
