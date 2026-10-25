# S10. Drill pack: the first 30-minute tabletop (Q42, Q46, Q47)

Everything needed to run the first drill in one sitting, so the result is a record on #692 and not a plan. It exercises the kill switch ([kill-switch.md](kill-switch.md)), the incident plan ([incident-response.md](incident-response.md)), the severity table ([severity-and-roles.md](severity-and-roles.md)) and the evidence steps ([evidence.md](evidence.md)). It is a talk-through with a clock. **Nobody touches a real key, token, session or database.**

## Before it starts (5 minutes, the owner)

- Pick a time-keeper (anyone who is not the incident lead). They hold the clock and write the times.
- Invite: the owner (incident lead), the planner, s2 (the PC agent that runs the backend), KJO IT security (Q47: functions outside the project team). Legal and communications join through KJO IT for the yearly drill only.
- Everyone has the five files above open. Nobody reads a secret aloud; the "key" in this drill is a made-up string.

## The scenario

> A comment on a public GitHub issue contains what looks like the project's Claude API key. Nobody knows who posted it or how long it has been visible.

## Timeline (30 minutes)

| Min | Step | Who | Proof to write down |
|---|---|---|---|
| 0 | Time-keeper starts the clock and reads the scenario. | time-keeper | Start time (UTC). |
| 0-3 | **Detect and classify.** Which severity (S1-S4)? Who is told, and within what time? | incident lead | Severity chosen, who was told, the deadline from the table. |
| 3-8 | **Contain: walk the kill switch**, step by step, saying aloud what each person would do and where: close sessions; revoke the cloud token; rotate the Claude key and set `REASONING_PROVIDER=ollama`; stop the backend; post on #692. | planner, s2 | Time for each of the five steps. Target for all five: **5 minutes**. |
| 8-14 | **Preserve evidence before changing anything:** which files are copied (spend ledger, backend logs, database copy, git log and PR list), into which folder, who records the SHA-256 and the time. | s2 | The list, and who does what. |
| 14-20 | **Fix and recover:** remove the comment, issue a new key, check the spend ledger for calls the project did not make, restart, run the usual check. | s2, owner | The order of the steps and what "recovered" means. |
| 20-25 | **Report:** what goes to KJO IT security and when (S1 or S2: within the hours in the table); who writes the 5-working-day report. | incident lead | The wording of the first message, in plain words. |
| 25-30 | **What was slow or unclear?** Every gap becomes a fix to the kill switch or the incident plan. | everyone | The list of fixes, each with an owner. |

## Pass marks (Q42, Q46, Q47)

- Q42: the five kill-switch steps were walked in order and the total time is written down, with the 5-minute target met or the gap named.
- Q46: the drill happened; the report below is on #692 within one working day.
- Q47: the attendee list names at least one person from each function: owner, planner, the agent that runs the backend, KJO IT security. A function that did not attend is written as "not present", not left out.

## Report to post on #692 (copy, fill, post)

```
Drill report | date (UTC) | scenario: leaked-key comment
Attendees (name, function): ...
Not present: ...
Severity chosen: S? Reported to: ... within: ...
Kill switch: step 1 ... min, step 2 ... min, step 3 ... min, step 4 ... min, step 5 ... min. Total ... min (target 5).
Evidence plan: files ..., folder ..., hashes by ...
Gaps found: ...
Fixes (what, who, by when): ...
Next drill: within 6 months of this date.
```

The report holds names of roles and counts of minutes only. It never contains a key, a token, a password or any document text.
