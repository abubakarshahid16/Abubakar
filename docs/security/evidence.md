# S11. Forensics and evidence preservation (Q48)

- **Delete nothing** during an incident.
- Copy these into `D:\project\incidents\<date>\`:
  - `backend/data/claude_spend.jsonl`;
  - the backend logs;
  - a copy of the database: all three files (`.sqlite`, `-wal`, `-shm`), or `live_guard.diagnostic_copy()`; never only the `.sqlite`;
  - the output of `git log` and the list of PRs.
- Record a **SHA-256 hash** of each copy (`certutil -hashfile <file> SHA256` on Windows), who took it and when (UTC).
- Hand them to KJO IT security if they ask.
