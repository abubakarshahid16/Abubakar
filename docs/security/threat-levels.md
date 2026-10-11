# S12. Threat levels (Q50)

| Level | Trigger | Actions |
|---|---|---|
| Normal | The default | All rules as written |
| Elevated | A KJO IT warning, or an S3 incident | The Claude lane is paused (`REASONING_PROVIDER=ollama`); agents work on synthetic data only; the weekly log check (S5) becomes daily |
| High | An S2 incident, or a targeted threat to KJO | All external AI is off; the cloud token is revoked; the PC agents stop |
| Critical | An S1 incident | The kill switch (S7); wait for KJO IT before restarting |

**Who sets the level:** the owner, or KJO IT security.
