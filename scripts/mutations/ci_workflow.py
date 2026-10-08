"""Mutations of the Linux CI workflow (.github/workflows/tests.yml) after the
speed-up (#584), and of scripts/test_changed.py.
Targets: backend/tests/test_ci_workflow.py, test_windows_ci_workflow.py,
test_test_changed_script.py.
"""

from __future__ import annotations

from ._base import REPO, Mutation

_W = REPO / ".github" / "workflows" / "tests.yml"
_T = "tests/test_ci_workflow.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2047", phase=2047, description="the required aggregate is skipped when a shard fails",
             path=_W, anchor="    needs: [backend-shard, backend-checks]\n    if: always()\n",
             replacement="    needs: [backend-shard, backend-checks]\n",
             target=_T, keyword="aggregate_that_needs_every_shard", tags=("ci",)),
    Mutation(id="M2048", phase=2048, description="every shard runs the whole suite",
             path=_W, anchor="--splits 3 --group ${{ matrix.group }} ",
             replacement="",
             target=_T, keyword="own_third", tags=("ci",)),
    Mutation(id="M2049", phase=2049, description="npm ci runs even on a node_modules cache hit",
             path=_W, anchor="        if: steps.nm.outputs.cache-hit != 'true'\n",
             replacement="",
             target=_T, keyword="node_modules_is_cached", tags=("ci",)),
    Mutation(id="M2050", phase=2050, description="the slow tests run on every pull request",
             path=_W, anchor="    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'\n",
             replacement="",
             target=_T, keyword="slow_tests_run_nightly", tags=("ci",)),
    Mutation(id="M2051", phase=2051, description="tests run on every push to every branch again",
             path=_W, anchor="  push:\n    branches: [main]\n  pull_request:\n",
             replacement='  push:\n    branches: ["**"]\n  pull_request:\n',
             target="tests/test_windows_ci_workflow.py", keyword="pushes_to_main_only", tags=("ci",)),
    Mutation(id="M2052", phase=2052, description="test_changed.py forgets tests named after a module",
             path=REPO / "scripts" / "test_changed.py",
             anchor='            hit |= {t for t in tests if t.name.startswith(f"test_{mod}")}\n',
             replacement="",
             target="tests/test_test_changed_script.py", keyword="named_after_it", tags=("ci",)),
)
