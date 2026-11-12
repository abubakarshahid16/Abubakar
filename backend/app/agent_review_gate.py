"""The ONE switch of the AI reviewer in the app (#1690, owner order 11 Nov 2026, step F).

`enabled()` reads `settings.agent_review_enabled` (env name AGENT_REVIEW_ENABLED, default OFF). It is the only place the
feature asks. Off means: no table is created, every `/api/reviews/agent-*` and `/agent/*` route answers 404 "feature_off",
no `agent_review` job is claimed, no Claude call is made, and the classic review runs exactly as before.

The Claude lane is NOT opened by this switch: `REASONING_PROVIDER`, both `STANDARDS_READER_*` flags and a key still decide
(`claude_lane_open`), and the owner-approved document list and the USD caps in `claude_spend` still apply on every call.
"""

from __future__ import annotations

from . import kind_review_table
from .config import settings

#: The job stage of an AI review (the classic review is `review_jobs.STAGE`, "review_run").
STAGE = "agent_review"
FEATURE_OFF = "feature_off"


#: The paper kinds the AI reviewer accepts. OWNER, 11 Nov 2026 (STATE 16.3 point 4): "In the live app, switch on the AI reviewer
#: for datasheets only. Keep procedure and contract review off until a re-run shows most opinion lines are right." (The
#: experiment's procedure and contract runs: most "AI thinks: not met" lines were wrong, because the paper was silent.) One
#: switch stays one switch; inside it a paper of any other kind, or of an unknown kind, is refused before any job exists.
#: Widening this tuple is an owner decision.
#: GENERAL REVIEW kinds, behind the SAME switch. OWNER, 11 Nov 2026 (STATE 16.4, word for word): "Do not switch them off. Review
#: them in GENERAL REVIEW mode when we hold no rule book for the paper: ... Never ask equipment rules of a paper they do not
#: belong to. Silence is a "Query", never "not met". No "Pass" or "Fail" in this mode. All lines internal only." ... "Switch it
#: on in the app only if that score is clearly better than tonight's." (Scored 11 Nov: wrong lines 26 to 2 on a procedure, 18 to 1
#: on a contract; planted errors caught 0 to 5 of 10 on each.) A paper of any other kind stays refused (409).
#: The kinds SCORED against an answer key (owner, 12 Nov 2026, #1584 comment 6820183348: "No new kind goes live until scored
#: against a key") are read from the `scored` field of the one table (`kind_review_table.scored`); adding a kind there is an
#: owner decision after a score against a key. `SCORED_KINDS` below is served from that table, never a tuple here.
#: (`AGENT_REVIEW_KINDS` and `AGENT_GENERAL_REVIEW_KINDS` are read from the one table, `reference/kind_review_table.json`.)
def __getattr__(name: str):
    """`AGENT_REVIEW_KINDS` / `AGENT_GENERAL_REVIEW_KINDS`: read from the one table (`kind_review_table`) each time they are asked,
    never frozen at import (a bad table must not stop the app: it answers empty, and a review is refused with the reason)."""
    if name == "AGENT_REVIEW_KINDS":
        return kind_review_table.rule_review_kinds()
    if name == "AGENT_GENERAL_REVIEW_KINDS":
        return kind_review_table.general_kinds()
    if name == "SCORED_KINDS":
        return kind_review_table.scored_kinds()
    raise AttributeError(name)


UNSCORED_WORDS = (
    "This kind of paper has not been scored against an answer key yet: treat every line as a draft"
)
KIND_NOT_ENABLED = "kind_not_enabled"
KIND_NOT_ENABLED_MESSAGE = (
    "AI review is on for datasheets (rule review) and for procedures and contracts "
    "(general review, no rule book) only (owner, 11 Nov 2026)"
)


def refusal_reason() -> str:
    """The message of a refused kind: the owner's sentence, and the table's own problem when the table cannot be used."""
    bad = kind_review_table.problem()
    return (
        f"{KIND_NOT_ENABLED_MESSAGE} (the kind table cannot be used: {bad})"
        if bad
        else KIND_NOT_ENABLED_MESSAGE
    )


class FeatureOff(RuntimeError):
    """AGENT_REVIEW_ENABLED is off: nothing was created, read or written."""


def enabled() -> bool:
    """True when the AI reviewer is switched on (`settings.agent_review_enabled`, default False)."""
    return bool(settings.agent_review_enabled)


def two_reader_enabled() -> bool:
    """True when the class "AI verdict, two readers agree" is switched on (`settings.agent_review_two_reader_verdict_enabled`,
    default False). Needs the AI reviewer itself on."""
    return bool(settings.agent_review_two_reader_verdict_enabled) and enabled()


def two_reader_absence_enabled() -> bool:
    """True when the absence word of the class is on: its own switch AND the first one (`two_reader_enabled`)."""
    return (
        bool(settings.agent_review_two_reader_absence_enabled) and two_reader_enabled()
    )


def two_reader_other_paper_enabled() -> bool:
    """True when the class "Not checked on this paper" is on: its own switch AND the first one."""
    return (
        bool(settings.agent_review_two_reader_other_paper_enabled)
        and two_reader_enabled()
    )


def require_on() -> None:
    if not enabled():
        raise FeatureOff("AGENT_REVIEW_ENABLED is off")


def kind_enabled(kind: str | None) -> bool:
    """May the AI reviewer take a paper of this decided kind? An unknown kind (None, "unknown") never."""
    return kind_review_table.norm(kind) in kind_review_table.rule_review_kinds()


def general_kind_enabled(kind: str | None) -> bool:
    """Does this decided kind get the GENERAL review (no rule book, no Pass or Fail)? An unknown kind never."""
    return kind_review_table.norm(kind) in kind_review_table.general_kinds()


def rules_kind_enabled(kind: str | None) -> bool:
    """May the rule path ask the held rules of this kind? A kind whose table row is `rule` always; a `rule_and_general` kind only
    with `agent_review_general_rules_enabled` on. An unknown kind, or a kind that asks no rules, never."""
    if not kind_review_table.asks_rules(kind):
        return False
    review = kind_review_table.row(kind)["review"]
    return review == "rule" or (
        review == "rule_and_general"
        and bool(settings.agent_review_general_rules_enabled)
    )


def kind_scored(kind: str | None) -> bool:
    """Has this kind been scored against an answer key? An unknown kind never."""
    return kind_review_table.scored(kind)


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
        and reasoning_provider.claude_unavailable_for_task(
            settings.agent_review_engine
        )[0]
        is None
    )
