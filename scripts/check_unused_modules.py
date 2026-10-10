"""Every module in backend/app is reached from the app (#725 F8a, #736).

Walks the import graph from the app's entry points (`app/main.py` and the
modules `run.py` starts) by AST - top-level AND lazy imports inside functions,
`from . import x`, `from .x import y`, `import app.x` - and lists every
`backend/app/*.py` module nothing reaches. A module only a test or a script
imports is not part of the app: it belongs in `scripts/` or nowhere.

    python scripts/check_unused_modules.py          # exit 1 if any is unused

Package files (`__init__.py`) are not counted. No module is exempt; there is
no allow-list to grow.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "backend" / "app"
#: What starts the app: the web server module, and what `run.py` imports.
ENTRY_POINTS = ("main",)


def _modules() -> dict[str, Path]:
    return {p.stem: p for p in APP.glob("*.py") if p.stem != "__init__"}


def imports_of(path: Path, known: set[str]) -> set[str]:
    """The app modules this file imports, anywhere in it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level >= 1 or mod == "app" or mod.startswith("app."):
                base = mod[4:] if mod.startswith("app.") else ("" if mod == "app" else mod)
                if base:
                    out.add(base.split(".")[0])
                else:
                    out.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app."):
                    out.add(a.name.split(".")[1])
    return out & known


def run_entry_points() -> set[str]:
    """`run.py` may start modules main does not import."""
    run = REPO / "backend" / "run.py"
    if not run.exists():
        return set()
    return imports_of(run, set(_modules()))


def reachable() -> set[str]:
    modules = _modules()
    known = set(modules)
    todo = [m for m in (*ENTRY_POINTS, *run_entry_points()) if m in modules]
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(imports_of(modules[name], known) - seen)
    return seen


def unused() -> list[str]:
    return sorted(set(_modules()) - reachable())


def main() -> int:
    dead = unused()
    if dead:
        print(f"{len(dead)} module(s) in backend/app are not reached from the app:")
        for name in dead:
            print(f"  backend/app/{name}.py")
        print("Move a tool to scripts/, or delete it with its tests and mutation entries.")
        return 1
    print(f"OK: all {len(_modules())} modules in backend/app are reached from the app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
