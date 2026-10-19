#!/bin/bash
# Conductor "screens" run: this workspace's screens on its own port. Several
# workspaces can preview at once; each gets its own CONDUCTOR_PORT.
#
# NEVER THE LIVE SERVER BY DEFAULT (#1173 review): a workspace's screens are
# unmerged code, and a click in them (a decision, a final code, an issued
# CRS) would write the owner's real reviews through the live server on 8000.
# So the server is chosen on purpose:
#   VITE_API_TARGET=http://127.0.0.1:<port>  a workspace's own backend
#   PREVIEW_AGAINST_LIVE=1                    the live app on 8000, knowingly
# With neither, the preview does not start. vite.config.ts falls back to 8000
# when VITE_API_TARGET is unset, so this script always sets it or stops.
set -euo pipefail
cd "${CONDUCTOR_WORKSPACE_PATH:-$(pwd)}/frontend"
PORT="${CONDUCTOR_PORT:-5180}"
LIVE="http://127.0.0.1:8000"
live_ok="${PREVIEW_AGAINST_LIVE:-}"
target="${VITE_API_TARGET:-}"
if [ -z "$target" ]; then
  if [ "$live_ok" != "1" ]; then
    echo "== preview not started: no server chosen." >&2
    echo "   Set VITE_API_TARGET to a workspace backend (not port 8000)," >&2
    echo "   or PREVIEW_AGAINST_LIVE=1 to click against the live app on purpose." >&2
    exit 2
  fi
  target="$LIVE"
fi
# Any address on port 8000 is the live app, whatever the host is called.
case "$target" in
  *:8000|*:8000/*)
    if [ "$live_ok" != "1" ]; then
      echo "== preview not started: ${target} is the live app's port." >&2
      echo "   Set PREVIEW_AGAINST_LIVE=1 to click against it on purpose." >&2
      exit 2
    fi
    echo "== WARNING: these unmerged screens talk to the LIVE app. Every click is real." ;;
esac
export VITE_API_TARGET="$target"
echo "== preview: http://127.0.0.1:${PORT}  (server: ${VITE_API_TARGET})"
exec npx vite --port "$PORT" --strictPort
