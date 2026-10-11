# S7. Revoke an AI agent fast: the kill switch (Q42)

**Target: 5 minutes.** Do the steps in this order:

1. **Close every agent session:** s1, s2, cloud and the planner.
2. **Revoke the cloud GitHub token:** GitHub → Settings → Developer settings → Fine-grained tokens → Revoke.
3. **Remove or rotate the Claude API key** in `backend/.env`, and set `REASONING_PROVIDER=ollama`.
4. **Stop the backend:** press `Ctrl+C` in the `python run.py` window.
5. **Post on #692** what was done and when (times in UTC).

**Done when:** these steps are committed and have been tested once in the drill (S10).
