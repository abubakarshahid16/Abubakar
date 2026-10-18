# S8. Incident-response plan (Q44)

1. **Detect:** anyone who sees a problem tells the owner at once.
2. **Contain:** run the kill switch (S7) if an agent or a key may be misused.
3. **Preserve evidence** (S11) before changing anything.
4. **Fix:** remove the cause. Restore from the last good backup if needed ([backup.md](backup.md)).
5. **Recover:** restart the backend (`python run.py`), then run the PSV check.
6. **Learn:** within 5 working days, post a short report on #692: what happened, why, and what changes.

Severity and who to tell, and how fast: S9.
