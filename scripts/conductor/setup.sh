#!/bin/bash
# Conductor setup: runs once in a new workspace (a git worktree).
# Installs the backend (Python 3.12 exactly; run.py refuses others) and the
# screens (Node, npm ci). Never copies backend/.env, never opens the live DB.
set -euo pipefail
cd "${CONDUCTOR_WORKSPACE_PATH:-$(pwd)}"

PY="$(command -v python3.12 || true)"
if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
  PY="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
fi
[ -x "$PY" ] || { echo "Python 3.12 not found (brew install python@3.12)"; exit 1; }

echo "== backend packages (Python $("$PY" --version | cut -d' ' -f2))"
[ -d backend/.venv ] || "$PY" -m venv backend/.venv
backend/.venv/bin/python -m pip install --quiet --upgrade pip
backend/.venv/bin/python -m pip install --quiet -r backend/requirements.txt

echo "== screen packages (Node $(node --version))"
(cd frontend && npm ci --no-audit --no-fund --loglevel=error)

# Same commit checks as everywhere else (secret scan before a push).
if [ -d .githooks ]; then git config core.hooksPath .githooks; fi

echo "== workspace ready: $(git rev-parse --abbrev-ref HEAD)"
