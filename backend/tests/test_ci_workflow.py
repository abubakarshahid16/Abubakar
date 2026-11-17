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
    assert set(agg["needs"]) == {"mode", "backend-shard", "backend-checks", "app-starts",
                                 "fast-backend", "fast-frontend"}
    # Without always() a failed shard SKIPS the aggregate, and a skipped
    # required check does not report failure.
    assert agg.get("if") == "always()"
    script = "\n".join(_runs(agg))
    assert 'test "${{ needs.mode.result }}" = "success"' in script
    assert 'test "${{ needs.backend-shard.result }}" = "success"' in script
    assert 'test "${{ needs.backend-checks.result }}" = "success"' in script
    assert 'test "${{ needs.app-starts.result }}" = "success"' in script


def test_the_app_start_check_runs_the_real_server(jobs):
    """Order 129: #1151 stopped the app from starting and no check caught it."""
    runs = "\n".join(_runs(jobs["app-starts"]))
    assert "python scripts/check_app_starts.py" in runs


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


def _bash():
    import shutil
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    return bash


def _aggregate(jobs, *, mode="success", full="true", shard="success", checks="success",
               starts="success", fast="skipped", fast_fe="skipped"):
    """Run the aggregate's real check script with the given job results."""
    import subprocess
    step = next(s for s in jobs["backend"]["steps"] if s.get("name") == "Every shard and the checks job passed")
    script = (
        step["run"]
        .replace("${{ needs.mode.result }}", mode)
        .replace("${{ needs.backend-shard.result }}", shard)
        .replace("${{ needs.backend-checks.result }}", checks)
        .replace("${{ needs.app-starts.result }}", starts)
        .replace("${{ needs.fast-backend.result }}", fast)
        .replace("${{ needs.fast-frontend.result }}", fast_fe)
    )
    return subprocess.run([_bash(), "-e", "-c", script], capture_output=True, env={"FULL": full}).returncode


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped"])
def test_the_aggregate_fails_on_a_failed_cancelled_or_skipped_shard(jobs, bad):
    assert _aggregate(jobs) == 0
    assert _aggregate(jobs, shard=bad) != 0
    assert _aggregate(jobs, checks=bad) != 0
    assert _aggregate(jobs, starts=bad) != 0


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped"])
def test_the_aggregate_in_fast_mode_needs_both_fast_jobs_and_the_checks(jobs, bad):
    ok = dict(full="false", shard="skipped", starts="skipped", fast="success", fast_fe="success")
    assert _aggregate(jobs, **ok) == 0
    assert _aggregate(jobs, **{**ok, "fast": bad}) != 0
    assert _aggregate(jobs, **{**ok, "fast_fe": bad}) != 0
    assert _aggregate(jobs, **{**ok, "checks": bad}) != 0


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped"])
def test_the_aggregate_fails_when_mode_failed_whatever_else_says(jobs, bad):
    """A failed `mode` leaves every other job skipped; the aggregate must not be green."""
    assert _aggregate(jobs, mode=bad, full="") != 0
    assert _aggregate(jobs, mode=bad, full="true") != 0
    assert _aggregate(jobs, mode=bad, full="false", shard="skipped", starts="skipped",
                      fast="success", fast_fe="success") != 0
    # an empty or unknown mode output is neither fast nor full
    assert _aggregate(jobs, full="") != 0


def test_full_mode_does_not_accept_a_skipped_shard_as_fast_mode_would(jobs):
    # shards skipped is right in fast mode, wrong in full mode
    assert _aggregate(jobs, full="true", shard="skipped") != 0
    assert _aggregate(jobs, full="false", shard="skipped", starts="skipped",
                      fast="success", fast_fe="success") == 0


# ---- the `mode` job: which checks run when ---------------------------------

def _decide(jobs, event, labels):
    """Run the `mode` job's real step; return the `full` output it writes."""
    import json
    import subprocess
    import tempfile
    step = next(s for s in jobs["mode"]["steps"] if s.get("id") == "decide")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out"
        out.touch()
        subprocess.run([_bash(), "-e", "-c", step["run"]], check=True, capture_output=True,
                       env={"EVENT": event, "LABELS": json.dumps(labels), "GITHUB_OUTPUT": str(out)})
        return out.read_text().strip()


@pytest.mark.parametrize("event, labels, full", [
    ("push", [], "true"),                                  # push to main
    ("schedule", [], "true"),                              # nightly
    ("workflow_dispatch", [], "true"),                     # by hand
    ("pull_request", [], "false"),                         # routine PR
    ("pull_request", ["backend"], "false"),                # only a topic label
    ("pull_request", ["full-checks"], "true"),
    ("pull_request", ["live-update"], "true"),
    ("pull_request", ["backend", "live-update"], "true"),
    ("pull_request", ["not-live-update-yet"], "false"),    # a look-alike label is not the label
])
def test_mode_decides_fast_or_full(jobs, event, labels, full):
    assert _decide(jobs, event, labels) == f"full={full}"


def test_the_pull_request_trigger_sees_a_label_being_added():
    on = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))[True]
    assert {"labeled", "unlabeled", "synchronize", "opened"} <= set(on["pull_request"]["types"])


def test_every_full_job_waits_for_mode_and_every_fast_job_runs_only_in_fast_mode(jobs):
    for name in ("backend-shard", "app-starts", "frontend", "accessibility"):
        assert jobs[name]["needs"] == "mode"
        assert jobs[name]["if"] == "needs.mode.outputs.full == 'true'", name
    for name in ("fast-backend", "fast-frontend"):
        assert jobs[name]["needs"] == "mode"
        assert jobs[name]["if"] == "needs.mode.outputs.full == 'false'", name
    # the lint job runs in both modes; only its models and benchmarks are full-only
    checks = jobs["backend-checks"]
    assert "if" not in checks
    full_only = {s["name"] for s in checks["steps"] if s.get("if") == "needs.mode.outputs.full == 'true'"}
    assert {"Cache models", "Stage models", "Run the benchmarks"} <= full_only


def test_the_fast_backend_job_runs_the_changed_tests_and_the_whole_suite_when_told(jobs):
    run = next(s["run"] for s in jobs["fast-backend"]["steps"] if s.get("name") == "Run the tests the change can break")
    assert "scripts/test_changed.py --base" in run
    assert "run the whole suite" in run and "-m pytest -q -n auto" in run


def test_the_audit_runs_only_in_full_mode(jobs):
    for s in jobs["backend"]["steps"][1:]:
        assert s.get("if") == "needs.mode.outputs.full == 'true'" or "durations" in s.get("name", "").lower() \
            or s.get("if", "").startswith("github.event_name"), s


def test_the_nightly_job_proves_every_slow_test_ran(jobs):
    runs = "\n".join(_runs(jobs["backend-slow"]))
    assert "--collect-only -q -m slow -p ci_test_ids" in runs
    assert "ci_test_ids.py compare --full ../slow-full.txt ../slow-ran.txt" in runs


DURATIONS_RUNS = "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"


def test_shards_split_by_measured_duration(jobs):
    shard = jobs["backend-shard"]
    restore = next(s for s in shard["steps"] if str(s.get("uses", "")).startswith("actions/cache/restore"))
    assert restore["with"]["path"] == "backend/.test_durations"
    assert restore["with"]["restore-keys"] == "test-durations-"
    names = [s.get("name") for s in shard["steps"]]
    assert names.index(restore["name"]) < names.index("Run this shard of the suite")
    run = next(s for s in shard["steps"] if s.get("name") == "Run this shard of the suite")
    assert "--splitting-algorithm duration_based_chunks" in run["run"]


def test_durations_are_stored_only_on_the_nightly_and_on_demand_runs(jobs):
    run = next(s for s in jobs["backend-shard"]["steps"] if s.get("name") == "Run this shard of the suite")
    assert run["env"]["STORE_DURATIONS"] == f"${{{{ ({DURATIONS_RUNS}) && '--store-durations' || '' }}}}"
    assert "$STORE_DURATIONS" in run["run"]


def test_a_green_nightly_run_refreshes_the_durations_for_the_next_runs(jobs):
    steps = jobs["backend"]["steps"]
    merge = next(s for s in steps if "merge-durations" in s.get("run", ""))
    save = next(s for s in steps if str(s.get("uses", "")).startswith("actions/cache/save"))
    assert merge.get("if") == DURATIONS_RUNS and save.get("if") == DURATIONS_RUNS
    assert save["with"]["path"] == "backend/.test_durations"
    assert save["with"]["key"].startswith("test-durations-")
    audit = next(i for i, s in enumerate(steps) if "ci_test_ids.py compare" in s.get("run", ""))
    assert audit < steps.index(merge), "durations refresh only after the audit passed"
    upload = next(s for s in steps if s.get("with", {}).get("name") == "test-durations")
    # .test_durations is a dot-file: without this the artifact is silently empty.
    assert upload["with"]["include-hidden-files"] is True
    assert upload["with"]["if-no-files-found"] == "error"


def test_the_committed_durations_file_is_real_and_well_formed():
    # The fallback the shards split by when no nightly refresh is cached yet.
    import json
    path = ROOT / "backend" / ".test_durations"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and len(data) > 1000, "durations for the real suite, not a stub"
    assert all(k.startswith("tests/") and "::" in k for k in data)
    assert all(isinstance(v, (int, float)) and v >= 0 for v in data.values())
