#!/usr/bin/env bash
# One-click start for the RAG Intelligence System on macOS and Linux (#498).
#
# The twin of scripts/start-system.bat, with the same four lessons that file
# records as FOUND when it was first run for real (2026-09-19):
#   1. the project venv's own interpreter, by path - never the system Python;
#   2. "started" is said only once it is true;
#   3. Vite runs with --strictPort, so a server already on 5173 is reused and
#      said, never silently displaced to 5174;
#   4. the wait loop needs no interactive console.
# There are no separate windows here: each component logs to
# backend/data/logs/<name>.log, and stopping is `kill` of the printed pids.
# NOT YET RUN ON A MAC (written on the Windows PC; `bash -n` checked).

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
BACKEND="http://127.0.0.1:8000/api/health"
FRONTEND="http://127.0.0.1:5173/"
LOGS="$ROOT/backend/data/logs"
mkdir -p "$LOGS"

echo "=== RAG Intelligence System ==="

answers() { curl -sf -o /dev/null "$1"; }

wait_for() {  # wait_for URL SECONDS - poll until the URL answers 2xx, or give up
    local left="$2"
    while ! answers "$1"; do
        left=$((left - 1))
        [ "$left" -le 0 ] && return 1
        sleep 1
    done
    return 0
}

# FOUND 1: the venv's own interpreter, by path, and refuse loudly without it.
if [ ! -x "$PY" ]; then
    echo "ERROR: the project venv is missing: $PY"
    echo "       Create it with Python 3.12 (python3.12 -m venv .venv) and install backend/requirements.txt."
    exit 1
fi

# ------------------------------------------------------------------ Ollama
if answers http://127.0.0.1:11434/api/tags; then
    echo "Ollama: running"
else
    echo "Ollama is not responding - starting it..."
    nohup ollama serve >"$LOGS/ollama.log" 2>&1 &
    echo "  pid $!"
    wait_for http://127.0.0.1:11434/api/tags 15 || {
        echo "WARNING: Ollama did not answer. Quoted answers work without it;"
        echo "         Explain and the answer model will not."
    }
fi

# ----------------------------------------------------------------- backend
# Already running is not an error - a second one would only fail on the port.
if answers "$BACKEND"; then
    echo "Backend: already running"
else
    echo "Starting backend..."
    (cd "$ROOT/backend" && nohup "$PY" run.py >"$LOGS/backend.log" 2>&1 &
     echo "  pid $!")
    # The backend loads its models before it answers; ~20 s on the PC.
    if ! wait_for "$BACKEND" 90; then
        echo
        echo "ERROR: the backend did not become healthy within 90 seconds."
        echo "       See $LOGS/backend.log. The browser was NOT opened."
        exit 1
    fi
fi
echo "Backend: healthy"

# ---------------------------------------------------------------- frontend
# FOUND 3: something on 5173 is REUSED and SAID, never silently displaced.
if answers "$FRONTEND"; then
    echo "Frontend: something is already serving on 5173 - using it."
    echo "          If it is not this system, stop it and run this again."
else
    echo "Starting frontend..."
    (cd "$ROOT/frontend" && nohup npm run dev -- --port 5173 --strictPort >"$LOGS/frontend.log" 2>&1 &
     echo "  pid $!")
    if ! wait_for "$FRONTEND" 60; then
        echo
        echo "ERROR: the frontend did not answer on 5173 within 60 seconds."
        echo "       See $LOGS/frontend.log. The browser was NOT opened."
        exit 1
    fi
fi

# FOUND 2: "started" is only said once it is true.
if command -v open >/dev/null 2>&1; then open http://localhost:5173
elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:5173 >/dev/null 2>&1
fi
echo
echo "All started. Logs: $LOGS. Stop with: kill <the pids printed above>."
exit 0
