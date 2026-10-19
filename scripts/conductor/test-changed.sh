#!/bin/bash
# Conductor "tests" run: only the tests related to this workspace's change,
# through the project's own runner (scripts/test_changed.py: backend pytest
# files and `vitest related` for screens). GitHub CI runs the full suite.
set -euo pipefail
cd "${CONDUCTOR_WORKSPACE_PATH:-$(pwd)}"
git fetch --quiet origin main || true
if git diff --name-only origin/main...HEAD | grep -q '^frontend/'; then
  echo "== screens: type check"
  (cd frontend && node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json)
fi
echo "== related tests"
exec backend/.venv/bin/python scripts/test_changed.py --base origin/main
