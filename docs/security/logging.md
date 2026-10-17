# S5. Logging and monitoring (Q40)

**Already in place:**
- Every Claude call is recorded in `claude_spend.jsonl` (step, model, cost; never the document text).
- Application events are recorded in `audit_events`.
- Every code change is recorded in git and on GitHub.
- Server logs carry ids and counts only, never document text (CLAUDE.md, standing rule 1).

**Added by this control:**
- s2 does a **weekly log check** and posts it on #692. It covers Claude spend against the caps, unusual calls (a step or model not in the AI register, S2), and failed logins.
  `python scripts/weekly_log_check.py` prints it, ready to paste (read-only: the DB opens `mode=ro`; counts, steps, models and account names only).
- Logs are kept for **90 days** at least.

**Done when:** the first weekly check is posted on #692.
