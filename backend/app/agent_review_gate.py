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
#: GENERAL REVIEW kinds, behind the SAME switch. OWNER, 11 Nov 2026 (STATE 16.4, word for word): "Do not switch them off. Review
#: them in GENERAL REVIEW mode when we hold no rule book for the paper: ... Never ask equipment rules of a paper they do not
#: belong to. Silence is a "Query", never "not met". No "Pass" or "Fail" in this mode. All lines internal only." ... "Switch it
#: on in the app only if that score is clearly better than tonight's." (Scored 11 Nov: wrong lines 26 to 2 on a procedure, 18 to 1
#: on a contract; planted errors caught 0 to 5 of 10 on each.) A paper of any other kind stays refused (409).
AGENT_GENERAL_REVIEW_KINDS = ("procedure", "contract")
KIND_NOT_ENABLED = "kind_not_enabled"
KIND_NOT_ENABLED_MESSAGE = (
    "AI review is on for datasheets (rule review) and for procedures and contracts "
    "(general review, no rule book) only (owner, 11 Nov 2026)"
)


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


def general_kind_enabled(kind: str | None) -> bool:
    """Does this decided kind get the GENERAL review (no rule book, no Pass or Fail)? An unknown kind never."""
    return (
        str(kind or "").strip().lower().replace(" ", "_") in AGENT_GENERAL_REVIEW_KINDS
    )


def any_kind_enabled(kind: str | None) -> bool:
    """A kind either review accepts: a datasheet (rule review) or a procedure or contract (general review)."""
    return kind_enabled(kind) or general_kind_enabled(kind)


def claude_lane_open() -> bool:
    """Whether THIS reviewer may call Claude: the provider switch (claude, or per_task with `agent_review_engine` = claude),
    both egress flags and a key. Says nothing about the approved-document list or the budget, which are checked again on every
    call. Under per_task with the reviewer's engine on ollama this is False even when the lane itself is open."""
    from . import agent_claude, reasoning_provider

    return bool(
        agent_claude.gate_open()
        and reasoning_provider.claude_unavailable_for_task(settings.agent_review_engine)[0] is None
    )
