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


class FeatureOff(RuntimeError):
    """AGENT_REVIEW_ENABLED is off: nothing was created, read or written."""


def enabled() -> bool:
    """True when the AI reviewer is switched on (`settings.agent_review_enabled`, default False)."""
    return bool(settings.agent_review_enabled)


def require_on() -> None:
    if not enabled():
        raise FeatureOff("AGENT_REVIEW_ENABLED is off")


def claude_lane_open() -> bool:
    """Whether the Claude lane itself is open: the provider switch, both egress flags and a key. Says nothing about the
    approved-document list or the budget, which are checked again on every call."""
    from . import agent_claude, reasoning_provider

    return bool(agent_claude.gate_open() and reasoning_provider.claude_lane_open())
