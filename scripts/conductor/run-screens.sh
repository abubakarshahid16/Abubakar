#!/bin/bash
# Conductor "screens" run: this workspace's screens on its own port, talking
# to the LIVE app's server on 8000 (override with VITE_API_TARGET). Several
# workspaces can preview at once; each gets its own CONDUCTOR_PORT.
set -euo pipefail
cd "${CONDUCTOR_WORKSPACE_PATH:-$(pwd)}/frontend"
PORT="${CONDUCTOR_PORT:-5180}"
export VITE_API_TARGET="${VITE_API_TARGET:-http://127.0.0.1:8000}"
echo "== preview: http://127.0.0.1:${PORT}  (server: ${VITE_API_TARGET})"
exec npx vite --port "$PORT" --strictPort
