# ADR-0014: Separate reminder and escalation notifications

Due-date reminders and escalation-level changes are separate notification
events with distinct subjects, triggers, and audit rows. Both remain fail
closed when SMTP is disabled.
