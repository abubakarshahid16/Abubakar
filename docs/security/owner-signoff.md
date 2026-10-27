# Owner sign-off list (Stage S, #806)

Every security paper in this folder is written and on `main`. What is left is not code. It is a decision, a setting or a meeting that only the owner (or KJO) can do. This page lists each one with the issue that stays open for it, so that nobody has to read seven issues to find them.

Nothing here contains a key, a password, a name or a document's text. The owner confirms each line with a short comment on #806; the planner then ticks the row in the #806 tracker and closes the issue.

| # | Question | Owner step | What proves it | Issue |
|---|---|---|---|---|
| 1 | Q31 | Confirm the current Anthropic commercial terms (no training on API data) and the GitHub terms, with one comment on #806 | The comment | #817 |
| 2 | Q38 | Create the fine-grained GitHub token for the cloud agent: this repository only, contents and pull-request write, no admin, no merge, 30 days | A note on #806 that it is done (never the token) | #820 |
| 3 | Q38 | Turn on branch protection for `main` (needs GitHub Pro, decided "yes" on 8 Oct, waiting for payment) | A screenshot or the settings noted on #806 | #820, #488 |
| 4 | Q38 | Change the test account's password (it was shared in chat) | A note on #806 that it is done | #820 |
| 5 | Q45 | Give KJO IT security's contact route in `severity-and-roles.md` (the name goes in the file, not in a public comment) | The file changed on `main`, or the owner's note | #825 |
| 6 | Q42, Q46, Q47 | Hold the 30-minute drill with [drill-pack.md](drill-pack.md): owner, planner, s2 and KJO IT security | The drill report posted on #692 (the pack has the template) | #826, #823 |
| 7 | Q40 | Run `python scripts/weekly_log_check.py` once in the live app, or tell s2 on #1309 that it may run it on the live paths read-only once a week | The first weekly log check posted on #692 | #821 |

## What is already proven (no owner step)

| Question | Proof on `main` |
|---|---|
| Q33, Q36, Q37, Q39 | `ai-register.md`, checked against `config.py` by `backend/tests/test_806_security_docs.py` |
| Q34, Q35 | `data-classification.md`; the Claude lane refuses documents not on the approved list (`backend/tests/test_806_claude_approved.py`) |
| Q38, item 3 | `.claude/settings.json` denies Read and Edit on `backend/.env` for every session; `backend/tests/test_820_agent_deny_rules.py` fails if a rule is removed |
| Q40, the script | `scripts/weekly_log_check.py`, read-only, counts only; `backend/tests/test_821_weekly_log_check.py` |
| Q41, Q44, Q48, Q50 | `approvals.md`, `incident-response.md`, `evidence.md`, `threat-levels.md` |

## What is not proven yet

- **Q40, the first weekly log check.** No weekly log check has been posted. The comment on #821 dated 12 Oct that says it was ("first weekly log review posted by s2") links to an unrelated comment on #692, so it proves nothing. The honest state is: the script exists, nobody has run it on the live paths. Row 7 above is the step that fixes this.
- **Q42, the kill switch in the drill.** The five steps are written. A test that the code half works (no Claude call with the key removed or `REASONING_PROVIDER=ollama`) is the open PR #1334. The people steps (close sessions, revoke the token) can only be proven by the drill.
