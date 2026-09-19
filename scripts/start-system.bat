@echo off
REM One-click start for the RAG Intelligence System. Phase 10 pre-build.
REM DRAFT - written on the Cowork VM, must be verified once on Windows.
REM What it does: checks Ollama, starts the backend, starts the frontend,
REM opens the browser. Each in its own window so logs stay visible.

echo === RAG Intelligence System ===

REM 1. Ollama must be up (the model host). If not running, start it.
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo Ollama is not responding - starting it...
    start "Ollama" ollama serve
    timeout /t 5 /nobreak >nul
) else (
    echo Ollama: running
)

REM 2. Backend (needs Python 3.12 exactly - run.py refuses others).
echo Starting backend...
start "RAG Backend" cmd /k "cd /d D:\project\Rag_chatbot\backend && python run.py"
timeout /t 6 /nobreak >nul

REM 3. Frontend.
echo Starting frontend...
start "RAG Frontend" cmd /k "cd /d D:\project\Rag_chatbot\frontend && npm run dev"
timeout /t 6 /nobreak >nul

REM 4. Open the app.
start http://localhost:5173

echo All started. Close the two console windows to stop the system.
