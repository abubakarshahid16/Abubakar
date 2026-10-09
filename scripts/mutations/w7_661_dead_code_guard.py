"""#661 "new dead code fails the build": each entry deletes one part;
backend/tests/test_w7_661_dead_code_guard.py must notice."""
from __future__ import annotations

from ._base import APP, REPO, Mutation

_T = "tests/test_w7_661_dead_code_guard.py"
_TAG = ("w7_661", "dead_code")
WF = REPO / ".github" / "workflows" / "tests.yml"
WL = REPO / "scripts" / "vulture_whitelist.py"


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4631, "CI no longer runs the dead-code check", WF,
       "        run: python -m vulture backend/app scripts/vulture_whitelist.py --min-confidence 80\n",
       "        run: echo skipped\n", "ci_job_runs_vulture"),
    _m(4632, "CI runs it at a confidence that finds nothing", WF, "vulture_whitelist.py --min-confidence 80\n",
       "vulture_whitelist.py --min-confidence 100\n", "ci_job_runs_vulture"),
    _m(4633, "vulture is not pinned in the lint job", WF,
       "pytest-split==0.11.0 vulture==2.16\n", "pytest-split==0.11.0 vulture\n", "ci_job_runs_vulture"),
    _m(4634, "a cache-key argument is no longer whitelisted", WL,
       "mtime_ns   # lru_cache KEY: the file's mtime makes a changed file miss the cache (datasheet_inputs)\n", "",
       "whitelisted_name or no_dead_code"),
    _m(4635, "a whitelisted name loses its reason", WL,
       "rect_num   # parameter the PDF library calls `rectfn` with; it must be accepted, not used (reports)\n",
       "rect_num\n", "whitelisted_name"),
    _m(4636, "a test hook is no longer marked", APP / "acronyms.py",
       "# TEST HOOK (#661): called by the tests to start from a clean state; the app does not call it.\ndef reset_cache(",
       "def reset_cache(", "marked_as_such"),
)
