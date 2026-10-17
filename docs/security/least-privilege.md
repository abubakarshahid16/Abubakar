# S4. Least privilege for AI agents (Q38)

1. **Cloud agent:** a fine-grained GitHub token for this repository only, with contents and pull-request write, no admin and no merge, expiring after 30 days. **The owner creates it.**
2. **Branch protection on `main`:** no direct pushes; merging needs passing checks. **The owner sets it** in the repository settings.
3. **PC agents:** work only inside `D:\project\Rag_chatbot` and its worktrees. Never `backend\.env`. Never `hidden-exam`, except s2 to score.
   **Enforced for `backend/.env` (#820):** the committed `.claude/settings.json` denies the Read and Edit tools on it for every Claude Code session in this repository and its worktrees. That covers the file tools, the shell file commands Claude Code recognises (`cat`, `head`, `sed`, `tee`) and redirections. It does not stop a program that opens the file itself, such as the backend reading its own settings. `tests/test_820_agent_deny_rules.py` fails if a rule is removed.
4. **Planner:** read-only by default. Any GitHub write needs the owner's OK in chat for that change, recorded on #692.
5. **Test account:** the owner changes the test password (it was shared in chat).

**Done when:** items 1, 2 and 5 are done by the owner and confirmed on #806.
