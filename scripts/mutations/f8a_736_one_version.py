"""#725 F8a (#736): unused-module and system-map checks. Ids M6801-M6806."""
from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_f8a_736_one_version.py"
_U = REPO / "scripts" / "check_unused_modules.py"
_M = REPO / "scripts" / "check_system_map.py"
_TAG = ("f8a", "one_version")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6801, "lazy imports inside functions are not followed", _U,
       "    for node in ast.walk(tree):\n", "    for node in tree.body:\n", "lazy_and_relative"),
    _m(6802, "a module nothing imports is not reported", _U,
       "    return sorted(set(_modules()) - reachable())", "    return []", "nothing_imports"),
    _m(6803, "relative imports of a name are dropped", _U,
       "                    out.update(a.name for a in node.names)\n", "                    pass\n",
       "lazy_and_relative or reached_from_the_app"),
    _m(6804, "a module missing from the map passes", _M,
       "    for name in sorted(modules - set(listed)):\n", "    for name in []:\n", "missing_from_the_map"),
    _m(6805, "a second module for one job passes unrecorded", _M,
       "        if len(names) > 1 and duplicates.get(job) != names:\n", "        if False:\n",
       "unrecorded_second_module"),
    _m(6806, "a module listed twice passes", _M,
       "            if name in listed:\n", "            if False:\n", "listed_twice"),
)
