"""The ONE switch of the AI reviewer in the app (#1690, owner order 11 Nov 2026, step F).

`enabled()` reads `settings.agent_review_enabled` (env name AGENT_REVIEW_ENABLED, default OFF). It is the only place the
feature asks. Off means: no table is created, every `/api/reviews/agent-*` and `/agent/*` route answers 404 "feature_off",
no `agent_review` job is claimed, no Claude call is made, and the classic review runs exactly as before.

The Claude lane is NOT opened by this switch: `REASONING_PROVIDER`, both `STANDARDS_READER_*` flags and a key still decide
(`claude_lane_open`), and the owner-approved document list and the USD caps in `claude_spend` still apply on every call.
"""

from __future__ import annotations

from .config import settings

#: The job stage of an AI review (the classic review is `review_jobs.STAGE`, "review_run").
STAGE = "agent_review"
FEATURE_OFF = "feature_off"


#: The paper kinds the AI reviewer accepts. OWNER, 11 Nov 2026 (STATE 16.3 point 4): "In the live app, switch on the AI reviewer
#: for datasheets only. Keep procedure and contract review off until a re-run shows most opinion lines are right." (The
#: experiment's procedure and contract runs: most "AI thinks: not met" lines were wrong, because the paper was silent.) One
#: switch stays one switch; inside it a paper of any other kind, or of an unknown kind, is refused before any job exists.
#: Widening this tuple is an owner decision.
AGENT_REVIEW_KINDS = ("datasheet",)
KIND_NOT_ENABLED = "kind_not_enabled"
KIND_NOT_ENABLED_MESSAGE = "AI review is on for datasheets only (owner, 11 Nov 2026)"


class FeatureOff(RuntimeError):
    """AGENT_REVIEW_ENABLED is off: nothing was created, read or written."""


def enabled() -> bool:
    """True when the AI reviewer is switched on (`settings.agent_review_enabled`, default False)."""
    return bool(settings.agent_review_enabled)


def require_on() -> None:
    if not enabled():
        raise FeatureOff("AGENT_REVIEW_ENABLED is off")


def kind_enabled(kind: str | None) -> bool:
    """May the AI reviewer take a paper of this decided kind? An unknown kind (None, "unknown") never."""
    return str(kind or "").strip().lower().replace(" ", "_") in AGENT_REVIEW_KINDS


def claude_lane_open() -> bool:
    """Whether the Claude lane itself is open: the provider switch, both egress flags and a key. Says nothing about the
    approved-document list or the budget, which are checked again on every call."""
    from . import agent_claude, reasoning_provider

    return bool(agent_claude.gate_open() and reasoning_provider.claude_lane_open())
