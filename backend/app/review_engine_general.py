"""The ONE Review button's resolver and pre-start answer for the GENERAL review (order 14; owner's ONE ORDER, 18 Nov 2026).

`review_engine.decide` and `review_engine.plan_for` hand over here when `aim_review_gate.general_on()`: the facts are read and
narrowed or widened by the choice there (`review_engine._narrowed`, the same consent rules as before), so this module only says what
the general review does with them. Pure resolver; the plan reads and writes nothing beyond `review_engine.plan_for`'s own reads.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from . import review_leaving
from .review_engine import (
    AI_REVIEW,
    AUTOMATIC,
    CLAUDE,
    LOCAL,
    NEEDS_YES,
    NOT_RUN,
    ON_CLAUDE,
    RULE_CHECK,
    UNKNOWN_CHOOSE,
    Facts,
    Part,
    Plan,
    unscored_choose_words,
)
from .review_engine_ran import _notes

#: Order 14 (owner, 18 Nov 2026): with the general review on, Local only is refused with this code (the sentence is
#: `aim_review_gate.LOCAL_NOT_AVAILABLE`); nothing is queued.
GENERAL_NOT_ON_LOCAL = "GENERAL_NOT_ON_LOCAL"
#: The blockers an explicit choice of Claude lifts (`decide` replaces those facts for Claude): Automatic says so.
LIFTED_BY_CLAUDE = ("NEEDS_YES", "NOT_APPROVED", "BOOKS_NOT_APPROVED", "UNSCORED")
CHOOSE_CLAUDE = ", choose Claude to send it"
GENERAL_ON_CLAUDE = "the general review reads the paper on Claude"


def narrowed(choice: str, f: Facts) -> Facts:
    """What the choice does to the facts, for both methods."""
    if choice == CLAUDE:
        # THE EXPLICIT CHOICE IS THE CONSENT (owner, 12 Nov 2026, #1584: "button is enough"): of any kind, a contract, a paper or
        # book not on the approved list, an unscored kind (a draft, internal copy only). The block list, the lane, the caps and
        # the kinds the AI review takes are not lifted by it.
        return replace(
            f,
            contract_yes=True,
            paper_approved=True,
            books_ok=True,
            scored_allowed=True,
        )
    if choice == AUTOMATIC:
        # AUTOMATIC NEVER SENDS A CONTRACT OR AN UNSCORED KIND TO CLAUDE BY ITSELF: it resolves to Local, and says why.
        return replace(
            f,
            contract_yes=False,
            scored_allowed=f.scored_allowed and f.kind is not None and f.kind_scored,
        )
    return f


def _general_blocker(f: Facts) -> tuple[str, str] | None:
    """`_ai_blocker` for the general review: every kind is taken, so KIND_UNKNOWN and KIND_NOT_OFFERED do not apply; every other
    blocker stands as written. An unknown kind is not scored: Automatic does not send it (UNSCORED), an explicit Claude does."""
    if not f.agent_enabled:
        return "AI_OFF", "the AI review is switched off on this install"
    if f.is_contract and not f.contract_yes:
        return "NEEDS_YES", NEEDS_YES
    if not (
        f.provider == "claude" or (f.provider == "per_task" and f.agent_engine_claude)
    ):
        return (
            "CLAUDE_NOT_SET",
            "Claude is not switched on for the AI review on this install",
        )
    if not f.lane_open:
        return (
            "LANE_CLOSED",
            "the connection to Claude is closed on this install (flags or key)",
        )
    if f.blocked:
        return "BLOCKED", "this file is blocked for Claude by name or checksum"
    if not f.paper_approved:
        return "NOT_APPROVED", "this paper is not approved for Claude"
    if not f.books_ok:
        return "BOOKS_NOT_APPROVED", "the rule books are not approved for Claude"
    if not f.scored_allowed:
        return "UNSCORED", UNKNOWN_CHOOSE if f.kind is None else unscored_choose_words()
    if not f.caps_ok:
        return "CAPS", "the spending cap leaves no room today"
    return None


def decide_general(choice: str, f: Facts) -> Plan:
    """The general review (order 14). Parts stay [rule_check, ai_review]; the rule check never runs; the AI review is the general
    review, on Claude or not run. A start that would run nothing is refused (never queued): Local only with
    GENERAL_NOT_ON_LOCAL, Automatic and Claude with the blocker's code. Pure: `f` is already narrowed or widened by the choice."""
    from . import aim_review_gate

    plan = Plan(choice=choice)
    plan.unscored = bool(f.kind) and not f.kind_scored
    plan.needs_yes = bool(f.is_contract and not f.contract_yes)
    off = Part(RULE_CHECK, NOT_RUN, aim_review_gate.OLD_ENGINE_OFF_WORDS)
    if choice == LOCAL:
        plan.refused = aim_review_gate.LOCAL_NOT_AVAILABLE
        plan.refused_code = GENERAL_NOT_ON_LOCAL
        plan.parts = [
            off,
            Part(AI_REVIEW, NOT_RUN, aim_review_gate.LOCAL_NOT_AVAILABLE),
        ]
        return plan
    blocker = _general_blocker(f)
    if blocker is None:
        plan.parts = [off, Part(AI_REVIEW, ON_CLAUDE, GENERAL_ON_CLAUDE)]
        return plan
    code, words = blocker
    if (
        choice == AUTOMATIC
        and code in LIFTED_BY_CLAUDE
        and "choose Claude" not in words
    ):
        words += CHOOSE_CLAUDE
    # Automatic holding a paper back is NOT "Claude cannot be used": the explicit choice of Claude lifts it (the words say so), so the two
    # never sit in one sentence (planner 19 Nov, items 6 and the HAZOP plan of the first-time user)
    lifted = choice == AUTOMATIC and code in LIFTED_BY_CLAUDE
    plan.refused = (
        f"Automatic will not send this paper to Claude on its own: {words}"
        if lifted
        else f"Claude cannot be used for this paper: {words}"
    )
    plan.refused_code = code
    plan.parts = [off, Part(AI_REVIEW, NOT_RUN, words)]
    return plan


#: The cost basis the plan says for the general review (CONTRACT section 3).
GENERAL_COST_BASIS = "at most {usd} for this review; a first review of a new type also writes its checklist"
GENERAL_LEAVES = (
    "Text of this paper and of the listed rule books leaves this computer for Claude."
)


LAST_COST_READ = "the cost of the last general review of this paper, read from the spend ledger (every step of that run)"
LAST_COST_UNREAD = (
    "the cost of the last review of this paper was not read from the spend ledger"
)


def _last_general_cost(conn, document_id: str) -> tuple[float | None, str | None]:
    """(cost, words) of the paper's last ENDED general review. The cost is the run's own stored `usd`, which the run read from the
    spend ledger's lines for that run (every step: reading, naming, checklist, judging, comments), never the earlier engine's figure,
    which covers one part only (A-H1). A run whose ledger could not be read has no cost: said so, never a partial sum or a 0. No
    general review yet: nothing is said."""
    from . import aim_review_store

    try:
        run = aim_review_store.latest_run(conn, str(document_id), ended=True)
    except sqlite3.Error:  # an unreadable store says nothing about a past cost
        return None, None
    if run is None:
        return None, None
    usd = run.get("usd")
    if isinstance(usd, bool) or not isinstance(usd, (int, float)):
        return None, LAST_COST_UNREAD
    return float(usd), LAST_COST_READ


def _unscored_note(facts) -> str:
    """The sentence under the engine line for a kind not on the automatic list. A kind that HAS a measured score on test copies is never
    called "not scored" beside that score (planner 19 Nov, item 6): it says it is measured but not yet on the automatic list."""
    from . import agent_review_gate, aim_review_measured

    got = aim_review_measured.for_run({"kind": getattr(facts, "kind", None)})
    if got and got.get("found") is not None:
        return (
            "This kind of paper is measured on test copies (the score is shown with the review) but is not on Automatic's list yet: "
            "treat every line as a draft"
        )
    return agent_review_gate.UNSCORED_WORDS


ACCOUNT_REFUSAL_HOURS = 24


def _recent_account_refusal(conn) -> str | None:
    """The plain sentence when a general review of the last day STOPPED because the Claude account cannot answer, else None. It says what
    the last review met, not that the account is still empty (credit may have been added since)."""
    from datetime import UTC, datetime, timedelta

    from . import aim_review_gate, aim_review_store

    if not aim_review_store.has_tables(conn):
        return None
    since = (datetime.now(UTC) - timedelta(hours=ACCOUNT_REFUSAL_HOURS)).isoformat(
        timespec="seconds"
    )
    row = conn.execute(
        f"SELECT stop_reason FROM {aim_review_store.RUNS} WHERE status = 'stopped' AND created_at >= ? AND ("
        + " OR ".join("stop_reason LIKE ?" for _ in aim_review_gate.ACCOUNT_WORDS)
        + ") ORDER BY created_at DESC LIMIT 1",
        (since, *[f"%{c}%" for c in aim_review_gate.ACCOUNT_WORDS]),
    ).fetchone()
    words = aim_review_gate.account_words(row["stop_reason"]) if row else None
    return f"The last review's Claude call was refused. {words}" if words else None


def general_plan(
    conn, document_id, allowed, plan, facts, reading, out: dict, project_ids=()
) -> dict:
    """The pre-start answer of the general review: the documents the review may send (the paper and the rule books chosen from the
    library's own records, `aim_review.candidates`), the upper bound of its cost, and one sentence. No write, no model, no call."""
    from . import aim_review_gate
    from .config import settings

    if plan.unscored:
        out["unscored_note"] = _unscored_note(facts)
    ctx = (conn, document_id, allowed, facts, reading)
    out["documents"] = review_leaving.documents_block(ctx, plan, tuple(project_ids))
    out["boundary"] = "documents you may read"
    leaves = plan.text_leaves
    cap = aim_review_gate.max_usd()
    last, last_note = _last_general_cost(conn, document_id)
    out["cost"] = {
        "at_most_usd": cap if leaves else None,
        "by_part_at_most_usd": {
            "rule_check": None,
            "ai_review": cap if leaves else None,
        },
        "basis": GENERAL_COST_BASIS.format(usd=f"USD {cap:.2f}") if leaves else None,
        "last_review_usd": last if leaves else None,
        "last_review_note": last_note if leaves else None,
        "exact": False,
    }
    out["notes"] = _notes(plan, settings)
    if refusal := _recent_account_refusal(
        conn
    ):  # the last Claude call was refused by the account: say it before the start
        out["notes"] = [*out["notes"], refusal]
    if plan.refused:
        out["sentence"] = (
            plan.refused if plan.refused.endswith(".") else plan.refused + "."
        )
    else:
        out["sentence"] = (
            f"The general review runs on Claude. {GENERAL_LEAVES} {aim_review_gate.AI_MARK}."
        )
    return out
