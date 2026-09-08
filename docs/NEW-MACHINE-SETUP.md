# Moving to another computer — step by step

Do these in order. Everything in **Part A** happens on the OLD computer before
you leave it. **Part B** is the new computer. **Part C** is starting Claude there.
Nothing in this file needs Claude — you can do it all yourself.

---

## Part A — on the OLD computer (this laptop)

### A1. Make sure the code is in GitHub

Open VS Code, open Claude Code, and paste the "Save all current work" prompt
(it is in the chat history; the short version is below). When it finishes, check:

```
git status          → must say "nothing to commit, working tree clean"
git log -1          → the newest commit is yours from today
```

Then open the repo on github.com and confirm the branch
`feat/phase-1-ui-reaches-backend` shows today's commits. **If GitHub does not
show them, nothing else in this file matters — the code is only on this laptop.**

Short version of the save prompt, if you need it again:
> Commit all uncommitted work on this branch in logical commits with honest
> messages naming the two known P0 defects from docs/code-review/README.md, push
> the branch, open a DRAFT pull request. Do not merge. Do not commit .env, data,
> models or *.sqlite*. Delete docs/review-command.md and frontend/dash-body.txt
> first, and revert the lightningcss line in frontend/package.json.

### A2. Copy the three things git must never carry

**Stop the backend first** (Ctrl+C in its terminal). Then copy these to a USB
stick or an encrypted drive — **not** to email, chat, or any cloud folder that
syncs to other people:

| Copy this | From | Why it is not in git |
|---|---|---|
| `.env` | `D:\project\Rag_chatbot\backend\.env` | secrets |
| `models\` (whole folder) | `D:\project\Rag_chatbot\backend\models\` | large binaries |
| `rag_intelligence.sqlite`, `rag_intelligence.sqlite-wal`, `rag_intelligence.sqlite-shm` | `D:\project\Rag_chatbot\backend\data\` | contains client document text — **all three files, or you lose documents** |

If you skip the database, the new machine simply starts empty and you re-upload
the PDFs. If you skip the models, the README's setup step re-downloads them.
**If you skip `.env`, the backend will not start** — there is no way to
recreate it from git.

### A3. Delete the stale lock (if it is still there)

```
del D:\project\Rag_chatbot\.git\index.lock
```

Only if no git command is running. Harmless if the file does not exist.

---

## Part B — on the NEW computer

### B1. Install the tools

| Tool | Version | Check |
|---|---|---|
| Git | any recent | `git --version` |
| Python | **3.12 exactly** — not 3.11, not 3.13 | `py -3.12 --version` |
| Node | 20 or newer | `node --version` |
| Ollama | latest | `ollama --version` |

### B2. Get the code

```
git clone https://github.com/abubakarshahid16/saudi-aramco-rag-chatbot.git Rag_chatbot
cd Rag_chatbot
git checkout feat/phase-1-ui-reaches-backend
```

### B3. Put back the three hand-carried things

From your USB stick:

```
backend\.env                         ← .env
backend\models\                      ← the models folder
backend\data\rag_intelligence.sqlite      ← all three DB files
backend\data\rag_intelligence.sqlite-wal
backend\data\rag_intelligence.sqlite-shm
```

Create `backend\data\` if it does not exist.

### B4. Backend

```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
```

If PowerShell refuses to activate:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` then retry.

### B5. Frontend

```
cd frontend
npm install
cd ..
```

**Run this on the new machine itself, in PowerShell or CMD.** Never from a
Linux shell or WSL — that installs the wrong native binaries and `npm run dev`
fails with `Cannot find module lightningcss...`. If that ever happens:
`npm install lightningcss-win32-x64-msvc@1.32.0`.

### B6. The answer model

```
ollama pull qwen3.5:4b
ollama list          → must show qwen3.5:4b
```

### B7. Start it

Terminal 1:
```
cd Rag_chatbot\backend
..\.venv\Scripts\activate
python run.py
```
Wait for `Uvicorn running on http://127.0.0.1:8000`.

Terminal 2:
```
cd Rag_chatbot\frontend
npm run dev
```
Open **http://127.0.0.1:5173** and sign in.

### B8. Check it worked

| Check | Expected |
|---|---|
| Sidebar bottom | green dot, **Connected** |
| Dashboard | your document count (19 if you copied the DB; 0 if not) |
| Chat: *What drawing size is required for design submittals?* | ANSI-D 22 × 34, doc16 p.22 (if DB copied) |

If the backend says `This project requires Python 3.12` → wrong interpreter;
delete `.venv` and redo B4 with `py -3.12`.

---

## Part C — starting Claude on the new computer

### C1. Claude Code in VS Code

Open the `Rag_chatbot` folder in VS Code and start Claude Code. It reads
`CLAUDE.md` **automatically** — you do not need to explain anything. Just say:

> Read docs/HANDOVER.md, then docs/code-review/README.md. Confirm the working
> tree matches HANDOVER §2. Then start the fix campaign at P0.

### C2. Cowork (Claude desktop app) or any other Claude chat

Link the session to the new computer and connect the `Rag_chatbot` folder.
Then attach `docs/HANDOVER.md` (or paste it) and say:

> This is the handover for my project. Read it fully, then read CLAUDE.md and
> docs/code-review/README.md in the repo. You are Cowork: frontend, tests, docs,
> reviews, and writing prompts for Claude Code in VS Code. Confirm the working
> tree matches HANDOVER §2 before doing anything. Then continue from §8.

### C3. If the two disagree with each other

`docs/HANDOVER.md` §2 describes the working tree as of 2026-09-08. If `git
status` shows something different, someone worked since. Tell Claude:

> The working tree differs from HANDOVER §2 — show me the difference and ask
> before touching anything.

### C4. Keep the handover alive

At the end of every working session, ask whichever Claude you used:

> Update docs/HANDOVER.md sections 2 and 4 to match what we did today, and
> commit it with the message "docs: handover update".

A handover file that is not updated is the next false claim.

---

## What never moves through git, ever

`.env` · the database · the models · the client's `Engineering Deliverables.pdf`
· any API key. Private repo or not. This is the industry rule and your own
pre-commit hook enforces it.
