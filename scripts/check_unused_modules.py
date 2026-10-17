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


def module_name(path: Path, app: Path) -> str:
    """`ai/json_reply.py` -> "ai.json_reply" (sub-packages of the app, #455)."""
    return ".".join(path.relative_to(app).with_suffix("").parts)


def _modules() -> dict[str, Path]:
    return {module_name(p, APP): p for p in APP.rglob("*.py")
            if p.stem != "__init__" and "__pycache__" not in p.parts}


def imports_of(path: Path, known: set[str]) -> set[str]:
    """The app modules this file imports, anywhere in it. A module in a
    sub-package is named with dots ("ai.json_reply"); every dotted prefix an
    import names is counted, so `from .ai import json_reply` and
    `from .ai.json_reply import x` both reach "ai.json_reply"."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = (list(path.parent.relative_to(APP).parts)
               if path.is_relative_to(APP) else [])
    named: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level >= 1:
                up = node.level - 1
                base = (package[:len(package) - up] if up else package) + (mod.split(".") if mod else [])
            elif mod == "app" or mod.startswith("app."):
                base = mod.split(".")[1:]
            else:
                continue
            named.append(base)
            named.extend(base + a.name.split(".") for a in node.names)
        elif isinstance(node, ast.Import):
            named.extend(a.name.split(".")[1:] for a in node.names if a.name.startswith("app."))
    out = {".".join(parts[:i]) for parts in named for i in range(1, len(parts) + 1)}
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
            print(f"  backend/app/{name.replace('.', '/')}.py")
        print("Move a tool to scripts/, or delete it with its tests and mutation entries.")
        return 1
    print(f"OK: all {len(_modules())} modules in backend/app are reached from the app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
