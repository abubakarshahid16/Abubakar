@echo off
setlocal EnableDelayedExpansion
REM One-click start for the RAG Intelligence System.
REM
REM RUN FOR REAL on Windows 11, 2026-09-19. The draft this replaces was written
REM on the Cowork VM and had never been run; running it once found four things
REM reality disagreed with, each fixed below and marked FOUND:
REM
REM   1. `python run.py` used the SYSTEM Python, not the project venv. It is
REM      also 3.12, so run.py's version check passed - and the backend died on
REM      `No module named 'onnxruntime'`. Right version, wrong environment.
REM   2. It printed "All started" whether or not anything had started.
REM   3. A dev server already on 5173 made Vite silently take 5174, while the
REM      script opened 5173 - landing the user on the OLD server.
REM   4. `timeout /t` refuses to run without an interactive console, so the
REM      script could not be launched from anything but a double-click.
REM
REM Each component is started in its own window so its log stays visible.

set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "BACKEND=http://127.0.0.1:8000/api/health"
set "FRONTEND=http://127.0.0.1:5173/"

echo === RAG Intelligence System ===

REM FOUND 1: the venv's own interpreter, by path, and refuse loudly without it.
if not exist "%PY%" (
    echo ERROR: the project venv is missing: %PY%
    echo        Create it with Python 3.12 and install backend\requirements.txt.
    exit /b 1
)

REM ---------------------------------------------------------------- Ollama
curl -sf -o nul http://127.0.0.1:11434/api/tags
if errorlevel 1 (
    echo Ollama is not responding - starting it...
    start "Ollama" ollama serve
    call :wait_for http://127.0.0.1:11434/api/tags 15 || (
        echo WARNING: Ollama did not answer. Quoted answers work without it;
        echo          Explain and the answer model will not.
    )
) else (
    echo Ollama: running
)

REM --------------------------------------------------------------- backend
REM Already running is not an error - starting a second one would only fail
REM on the port and leave a dead window behind.
curl -sf -o nul %BACKEND%
if errorlevel 1 (
    echo Starting backend...
    start "RAG Backend" cmd /k "cd /d "%ROOT%\backend" && "%PY%" run.py"
    REM The backend loads its models before it answers; measured ~20s here.
    call :wait_for %BACKEND% 90 || goto backend_failed
) else (
    echo Backend: already running
)
echo Backend: healthy

REM -------------------------------------------------------------- frontend
REM FOUND 3: something on 5173 is REUSED and SAID, never silently displaced.
REM --strictPort makes Vite fail loudly rather than drift to another port the
REM browser below would not be opened on.
curl -sf -o nul %FRONTEND%
if errorlevel 1 (
    echo Starting frontend...
    start "RAG Frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev -- --port 5173 --strictPort"
    call :wait_for %FRONTEND% 60 || goto frontend_failed
) else (
    echo Frontend: something is already serving on 5173 - using it.
    echo           If it is not this system, stop it and run this again.
)

REM FOUND 2: "started" is only said once it is true.
start "" http://localhost:5173
echo.
echo All started. Close the "RAG Backend" and "RAG Frontend" windows to stop.
exit /b 0

:backend_failed
echo.
echo ERROR: the backend did not become healthy within 90 seconds.
echo        Its window shows why. The browser was NOT opened.
exit /b 1

:frontend_failed
echo.
echo ERROR: the frontend did not answer on 5173 within 60 seconds.
echo        Its window shows why. The browser was NOT opened.
exit /b 1

REM ---------------------------------------------------------------------
REM :wait_for URL SECONDS - poll until the URL answers 2xx, or give up.
REM FOUND 4: `ping` as the delay rather than `timeout /t`, which refuses to
REM run when there is no interactive console.
:wait_for
set /a "_left=%~2"
:wait_loop
curl -sf -o nul %~1 && exit /b 0
set /a "_left-=1"
if !_left! leq 0 exit /b 1
ping -n 2 127.0.0.1 >nul
goto wait_loop
