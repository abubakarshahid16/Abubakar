# S1. Cloud and SaaS responsibility matrix (Q31)

Who is responsible for what when the system uses an outside service.

| Area | Us (owner and agents) | Anthropic (Claude API) | GitHub | KJO IT |
|---|---|---|---|---|
| What data is sent | Decide and limit it (S3). Only through `reader_transport.py`, under the USD caps in `claude_spend` | Processes the request. No training on API data under its commercial terms (**owner to confirm the current terms**) | Stores code, issues and PRs. **No document text** is ever posted there | Owns the policy |
| Accounts and keys | Create, rotate and revoke them. Keys live only in `backend/.env` | Secures the API | Secures the platform. We set tokens and branch rules (S4) | Approves cloud use |
| Logs | Keep our logs (S5): `claude_spend.jsonl`, `audit_events`, git history | Keeps its own logs | Keeps the audit log of repo actions | Receives incident reports (S8, S9) |
| Outage | Fall back to the local model (`REASONING_PROVIDER=ollama`). A review never fails because the Claude lane is down | Keeps the service up | Keeps the service up | n/a |

**Done when:** this file is committed, and the owner has confirmed the Anthropic and GitHub terms with a comment on #806.
