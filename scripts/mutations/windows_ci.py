"""Mutations of the Windows CI job (.github/workflows/tests-windows.yml).
Target: backend/tests/test_windows_ci_workflow.py.
"""

from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_windows_ci_workflow.py"
_W = REPO / ".github" / "workflows" / "tests-windows.yml"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1780", phase=1780, description="the Windows job runs on Linux",
             path=_W, anchor="    runs-on: windows-latest\n",
             replacement="    runs-on: ubuntu-latest\n",
             target=_T, keyword="job_runs_on_windows", tags=("ci",)),
    Mutation(id="M1781", phase=1781, description="the suite is narrowed with a -k filter",
             path=_W, anchor="        run: python -m pytest -q -n auto --durations=10\n",
             replacement="        run: python -m pytest -q -n auto -k smoke --durations=10\n",
             target=_T, keyword="real_backend_suite", tags=("ci",)),
    Mutation(id="M1782", phase=1782, description="the suite runs from the repo root, not backend/",
             path=_W, anchor="        working-directory: backend\n        run: python -m pytest",
             replacement="        run: python -m pytest",
             target=_T, keyword="real_backend_suite", tags=("ci",)),
    Mutation(id="M1783", phase=1783, description="the models are never verified before the suite",
             path=_W, anchor="        run: python scripts/fetch_models.py --verify-only\n",
             replacement="        run: echo skipped\n",
             target=_T, keyword="models_are_staged_and_verified", tags=("ci",)),
    Mutation(id="M1784", phase=1784, description="the job takes the Linux check's name",
             path=_W, anchor="    name: backend on Windows (pytest, informational)\n",
             replacement="    name: backend (pytest)\n",
             target=_T, keyword="does_not_reuse_a_name or informational", tags=("ci",)),
    Mutation(id="M1785", phase=1785, description="it runs on every pull request again",
             path=_W, anchor="on:\n  schedule:\n",
             replacement="on:\n  pull_request:\n  schedule:\n",
             target=_T, keyword="nightly_and_on_demand_only", tags=("ci",)),
    Mutation(id="M1786", phase=1786, description="the job asks for write access",
             path=_W, anchor="permissions:\n  contents: read\n",
             replacement="permissions:\n  contents: write\n",
             target=_T, keyword="no_more_than_read_access", tags=("ci", "security")),
    Mutation(id="M1787", phase=1787, description="a different Python from the Linux job",
             path=_W, anchor='          python-version: "3.12"\n',
             replacement='          python-version: "3.11"\n',
             target=_T, keyword="same_python", tags=("ci",)),
    Mutation(id="M1788", phase=1788, description="no time limit on the job",
             path=_W, anchor="    timeout-minutes: 45\n",
             replacement="    timeout-minutes: 600\n",
             target=_T, keyword="time_limit", tags=("ci",)),
)
