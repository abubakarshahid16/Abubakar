"""ONE Review button, three choices: Automatic, Claude, Local only (owner decision, 12 Nov 2026, #1584 comment 6820183348).

THE RESOLVER IS HERE AND NOWHERE ELSE. `decide(choice, facts)` turns the choice, the paper's kind, role and approvals and the installed
switches into a PLAN: which parts run (the rule check, the AI review), on which engine, with one plain reason per decision. It is
pure (no database, no network, no model) so a brute force can walk every combination. `read_facts` reads the facts; `plan_for`
joins them; the pre-start route and the start route both call `plan_for`, so the screen shows exactly what will be enforced.

THE CHOICE ONLY NARROWS OR SELECTS (CLAUDE.md rule 1). It never opens a lane the installed switches keep closed: Claude needs
`REASONING_PROVIDER` claude, or per_task with the step's OWN engine setting (`agent_review_engine`, `REVIEW_ENGINE_SETTINGS`),
both egress flags and a key; every call still passes `claude_approved.refusal` and the USD caps in `claude_spend`.

  Local only   nothing leaves the machine, guaranteed: the run is barred (`barring`, a context variable honoured by
               `reasoning_provider._lane_unavailable`, `claude_approved.refusal` and `agent_claude.gate_open`, before any
               transport). The AI review needs Claude, so it does not run; the rule check runs on this computer.
  Automatic    the best engine the rules allow for THIS paper: Claude where the lane, the kind, the approvals and the caps allow
               it, else the local model, with the reason. A part the plan puts on the local model is barred from Claude too.
  Claude       the same checks; any that fails is a refusal with a plain reason. Never a silent fallback to local.

THE AI REVIEW HAS NO LOCAL READER ON THE JOB PATH (`agent_review_jobs` is Claude-only; `agent_local_lead` is used only by the
experiment loop). So "Local only" means: rule check on the local model, AI review not run, and the plan says so.

WHAT IS RECORDED. `review_engine_choice` holds, per run, the choice, the plan, who asked and whether the AI review follows the rule
check. The worker reads it to raise the bar and to start the follow-up job. Words only: no document text, no file name.

This module opens no socket and reads no document text.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

AUTOMATIC, CLAUDE, LOCAL = "automatic", "claude", "local"
CHOICES = (AUTOMATIC, CLAUDE, LOCAL)
RULE_CHECK, AI_REVIEW = "rule_check", "ai_review"
ON_CLAUDE, ON_LOCAL, NOT_RUN = "claude", "local", "not_run"
#: A run barred from Claude: the id of its choice, for the log. None = not barred.
_BARRED: ContextVar[bool] = ContextVar("review_engine_barred", default=False)
BARRED_CODE = "RUN_LOCAL_ONLY"
BARRED_WORDS = (
    "this part of the review was set to run on this computer only, so nothing is sent"
)

# Plain sentences. One home: the screen and the refusal read these.
AI_NEEDS_CLAUDE_LOCAL = (
    "The AI review needs Claude and will not run; the rule check runs on this computer"
)
NEEDS_YES = "needs the owner's yes for this upload"
CHECKLISTS_EMPTY = (
    ("contract checklist", "empty; an engineer must write it"),
    ("calculation checklist", "empty; an engineer must write it"),
)


# ----------------------------------------------------------------------------------------------- the bar


def claude_barred() -> bool:
    """True inside a run whose plan keeps it on this computer."""
    return _BARRED.get()


@contextmanager
def barring() -> Iterator[None]:
    token = _BARRED.set(True)
    try:
        yield
    finally:
        _BARRED.reset(token)


# ----------------------------------------------------------------------------------------------- the facts


@dataclass(frozen=True)
class Facts:
    """Everything the resolver may look at. All plain values."""

    kind: str | None = None  # "datasheet", "procedure", "contract", ... None = unknown
    kind_guess: bool = False
    agent_enabled: bool = True  # AGENT_REVIEW_ENABLED
    provider: str = "ollama"  # REASONING_PROVIDER: ollama | claude | per_task | other
    agent_engine_claude: bool = False  # AGENT_REVIEW_ENGINE says claude
    step_engine_claude: bool = False  # any normal-review step's OWN engine says claude
    lane_open: bool = False  # both egress flags and a key
    blocked: bool = False  # the paper's hash or name is on the block list
    paper_approved: bool = (
        False  # the paper may go to Claude (list, or the automatic route for its role)
    )
    is_contract: bool = False
    contract_yes: bool = False  # the owner's yes for THIS file
    scored_allowed: bool = True  # kind scored, or the setting offers unscored kinds
    kind_scored: bool = True
    caps_ok: bool = True  # the USD caps leave room
    books_ok: bool = (
        True  # the rule books may go (approved or joining by the automatic route)
    )


@dataclass
class Part:
    name: str
    engine: str  # claude | local | not_run
    why: str


@dataclass
class Plan:
    choice: str
    parts: list[Part] = field(default_factory=list)
    refused: str | None = None  # a plain sentence; set only when the start is refused
    refused_code: str | None = None
    needs_yes: bool = False
    unscored: bool = False
    wont_run: list[dict] = field(default_factory=list)

    def part(self, name: str) -> Part:
        return next(p for p in self.parts if p.name == name)

    @property
    def text_leaves(self) -> bool:
        return any(p.engine == ON_CLAUDE for p in self.parts)

    @property
    def runs(self) -> list[str]:
        return [p.name for p in self.parts if p.engine != NOT_RUN]

    def as_dict(self) -> dict:
        return {
            "choice": self.choice,
            "parts": [p.__dict__ for p in self.parts],
            "text_leaves": self.text_leaves,
            "refused": self.refused,
            "refused_code": self.refused_code,
            "needs_yes": self.needs_yes,
            "unscored": self.unscored,
            "wont_run": list(self.wont_run),
        }


# ----------------------------------------------------------------------------------------------- the resolver


def _ai_blocker(f: Facts) -> tuple[str, str] | None:
    """The first reason the AI review cannot go to Claude for this paper: (code, one plain sentence), else None."""
    if not f.agent_enabled:
        return "AI_OFF", "the AI review is switched off on this install"
    if f.kind is None:
        return (
            "KIND_UNKNOWN",
            "the kind of this paper is not known; an engineer names it first",
        )
    if f.kind not in ("datasheet", "procedure", "contract"):
        word = f.kind.replace("_", " ")
        return "KIND_NOT_OFFERED", f"the AI review does not take a {word} yet"
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
    if f.is_contract and not f.contract_yes:
        return "NEEDS_YES", NEEDS_YES
    if not f.paper_approved:
        return "NOT_APPROVED", "this paper is not approved for Claude"
    if not f.books_ok:
        return "BOOKS_NOT_APPROVED", "the rule books are not approved for Claude"
    if not f.scored_allowed:
        return "UNSCORED", gate_unscored_words()
    if not f.caps_ok:
        return "CAPS", "the spending cap leaves no room today"
    return None


def _rule_check_on_claude(f: Facts) -> tuple[bool, str]:
    """Would the rule check's own AI steps be allowed on Claude? (They follow each step's OWN engine setting.) (yes, reason when not)"""
    if not (
        f.provider == "claude" or (f.provider == "per_task" and f.step_engine_claude)
    ):
        return False, "no step of the rule check is set to Claude on this install"
    if not f.lane_open:
        return (
            False,
            "the connection to Claude is closed on this install (flags or key)",
        )
    if f.blocked:
        return False, "this file is blocked for Claude by name or checksum"
    if f.is_contract and not f.contract_yes:
        return False, NEEDS_YES
    if not f.paper_approved:
        return False, "this paper is not approved for Claude"
    if not f.scored_allowed:
        return False, gate_unscored_words()
    if not f.caps_ok:
        return False, "the spending cap leaves no room today"
    return True, "its AI steps use Claude where this install sets them to"


def gate_unscored_words() -> str:
    from . import agent_review_gate

    return agent_review_gate.UNSCORED_WORDS


def decide(choice: str, f: Facts) -> Plan:
    """THE resolver. See the module docstring. Pure."""
    choice = (choice or "").strip().lower()
    if choice not in CHOICES:
        raise ValueError(f"engine must be one of {', '.join(CHOICES)}")
    plan = Plan(choice=choice)
    plan.unscored = bool(f.kind) and not f.kind_scored
    plan.needs_yes = bool(f.is_contract and not f.contract_yes)
    if f.is_contract:
        plan.wont_run = [{"part": p, "why": w} for p, w in CHECKLISTS_EMPTY]
    blocker = _ai_blocker(f)
    rc_claude, rc_why = _rule_check_on_claude(f)

    if choice == LOCAL:
        plan.parts = [
            Part(
                RULE_CHECK,
                ON_LOCAL,
                "you chose Local only: nothing leaves this computer",
            ),
            Part(AI_REVIEW, NOT_RUN, AI_NEEDS_CLAUDE_LOCAL),
        ]
        return plan

    ai_ok = blocker is None
    if choice == CLAUDE and not ai_ok and not rc_claude:
        plan.refused = f"Claude cannot be used for this paper: {blocker[1]}"
        plan.refused_code = blocker[0]
        plan.parts = [
            Part(RULE_CHECK, NOT_RUN, "refused"),
            Part(AI_REVIEW, NOT_RUN, blocker[1]),
        ]
        return plan

    if rc_claude:
        rc = Part(RULE_CHECK, ON_CLAUDE, rc_why)
    elif choice == CLAUDE:
        # Claude was asked for and the AI review is allowed: the rule check keeps the local model, and says so.
        rc = Part(RULE_CHECK, ON_LOCAL, f"runs on this computer: {rc_why}")
    else:
        rc = Part(RULE_CHECK, ON_LOCAL, f"runs on this computer: {rc_why}")
    if ai_ok:
        ai = Part(AI_REVIEW, ON_CLAUDE, "the AI review reads the paper on Claude")
    else:
        ai = Part(AI_REVIEW, NOT_RUN, blocker[1])
    plan.parts = [rc, ai]
    return plan


# ----------------------------------------------------------------------------------------------- reading the facts


def read_facts(conn, document_id: str, allowed: frozenset[str]) -> tuple[Facts, object]:
    """The facts for one paper from the app and the installed switches. Reads only. Also returns the PaperReading."""
    from . import (
        agent_review_gate,
        agent_review_kind,
        claude_approved,
        claude_spend,
        contract_yes,
        local_engine_bar,
        reasoning_provider,
    )
    from .config import settings

    reading = agent_review_kind.decide(document_id, allowed)
    kind = reading.kind if reading.known else None
    provider = reasoning_provider._provider_setting()
    row = conn.execute(
        "SELECT d.filename, d.sha256, c.document_role FROM documents d"
        " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
        (document_id,),
    ).fetchone()
    sha = ((row["sha256"] if row else "") or "").strip().lower()
    role = row["document_role"] if row else None
    try:
        blocked_hashes = claude_approved.blocked_hashes()
        blocked = sha in blocked_hashes or claude_approved.name_is_blocked(
            row["filename"] if row else None, claude_approved.marked_name_keys()
        )
    except claude_approved.BlockListUnreadable:
        blocked = True  # fail closed
    is_contract = kind == "contract" or role == "CONTRACT_DOCUMENT"
    yes = is_contract and contract_yes.has_yes(document_id)
    approved = _paper_approved(sha, role, is_contract, yes, claude_approved, settings)
    lane_open = reasoning_provider.claude_lane_open()
    scored = agent_review_gate.kind_scored(kind)
    steps_claude = any(
        str(getattr(settings, name, "") or "").strip().lower()
        == reasoning_provider.CLAUDE
        for name in local_engine_bar.REVIEW_ENGINE_SETTINGS
    )
    try:
        room = claude_spend.spent() < claude_spend.total_cap()
    except Exception as exc:  # noqa: BLE001 - an unreadable ledger leaves no room: the safe side
        log.warning(
            "review plan: spend ledger unreadable (%s); no room is claimed",
            type(exc).__name__,
        )
        room = False
    facts = Facts(
        kind=kind,
        kind_guess=bool(reading.guess),
        agent_enabled=agent_review_gate.enabled(),
        provider=provider,
        agent_engine_claude=str(settings.agent_review_engine or "").strip().lower()
        == "claude",
        step_engine_claude=steps_claude,
        lane_open=lane_open,
        blocked=blocked,
        paper_approved=approved,
        is_contract=is_contract,
        contract_yes=yes,
        # An unknown kind is not a kind that went live: nothing new is offered for it, and what ran before runs as before (the
        # AI review refuses it on its own: KIND_UNKNOWN). A KNOWN kind not scored against a key is held unless the setting says so.
        scored_allowed=kind is None
        or scored
        or bool(settings.review_unscored_kinds_for_claude_enabled),
        kind_scored=scored,
        caps_ok=room,
        books_ok=bool(
            settings.claude_auto_approve_reviews_enabled
            or not settings.claude_approved_list_enforced
            or _any_book_approved(conn, document_id, claude_approved)
        ),
    )
    return facts, reading


def _paper_approved(sha, role, is_contract, yes, claude_approved, settings) -> bool:
    if is_contract:
        return bool(yes)
    if not settings.claude_approved_list_enforced:
        return True
    if sha and sha in claude_approved.approved_hashes():
        return True
    qualifies = role in (None, *claude_approved.REVIEW_ROLES)
    return bool(qualifies and settings.claude_auto_approve_reviews_enabled)


def _any_book_approved(conn, document_id: str, claude_approved) -> bool:
    """Without the automatic route the books must already be on the list: true when the paper's earlier run chose books and
    every one is. No earlier run: not known, so not claimed."""
    try:
        books = _earlier_books(conn, document_id)
    except sqlite3.Error:
        return False
    if not books:
        return False
    hashes = {b["sha256"] for b in books if b["sha256"]}
    return bool(hashes) and hashes <= claude_approved.approved_hashes()


def _earlier_books(conn, document_id: str) -> list[dict]:
    run = conn.execute(
        "SELECT id FROM review_runs WHERE submittal_document_id = ? AND status = 'complete'"
        " ORDER BY started_at DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    if run is None:
        return []
    return [
        {
            "id": r["standard_document_id"],
            "filename": r["filename"],
            "sha256": (r["sha256"] or "").strip().lower(),
        }
        for r in conn.execute(
            "SELECT s.standard_document_id, d.filename, d.sha256 FROM review_applicable_standards s"
            " JOIN documents d ON d.id = s.standard_document_id"
            " WHERE s.review_run_id = ? AND COALESCE(s.included, 1) = 1",
            (run["id"],),
        )
    ]


# ----------------------------------------------------------------------------------------------- the pre-start answer


def _last_cost(conn, document_id: str) -> float | None:
    """The real cost of the paper's last AI review (its stored `usd`); None when there is none or it was not measured."""
    try:
        row = conn.execute(
            "SELECT a.usd FROM agent_review_run a JOIN review_runs r ON r.id = a.run_id"
            " WHERE r.submittal_document_id = ? AND a.usd IS NOT NULL ORDER BY r.started_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return float(row["usd"]) if row and row["usd"] is not None else None


def plan_for(conn, document_id: str, allowed: frozenset[str], choice: str) -> dict:
    """The pre-start answer. No side effect: nothing is written, no call is made, no model is loaded. A dict of plain facts:
    the engine of each part, whether text leaves this computer and which documents, the estimated cost, what will not run."""
    from .config import settings

    facts, _reading = read_facts(conn, document_id, allowed)
    plan = decide(choice, facts)
    out = plan.as_dict()
    out["kind"] = facts.kind
    out["kind_guess"] = facts.kind_guess
    if plan.unscored:
        from . import agent_review_gate

        out["unscored_note"] = agent_review_gate.UNSCORED_WORDS
    leaves = plan.text_leaves
    docs: dict = {"paper": bool(leaves), "rule_books": [], "rule_books_note": None}
    if leaves:
        books = [b for b in _earlier_books(conn, document_id) if b["id"] in allowed]
        docs["rule_books"] = sorted(b["filename"] for b in books)
        docs["rule_books_note"] = (
            "named from this paper's last review, only the books you may read; the books are chosen again when the review starts"
            if books
            else "the rule books are chosen when the review starts"
        )
    out["documents"] = docs
    out["boundary"] = "documents you may read"
    cap = float(settings.claude_budget_usd_per_run)
    last = _last_cost(conn, document_id)
    out["cost"] = {
        "at_most_usd": cap if leaves else None,
        "basis": "the cap for one review (never exceeded); the real cost is usually lower"
        if leaves
        else None,
        "last_review_usd": last if leaves else None,
        "last_review_note": "the measured cost of the last AI review of this paper"
        if (leaves and last is not None)
        else None,
        "exact": False,
    }
    out["sentence"] = sentence_of(out)
    return out


def sentence_of(plan: dict) -> str:
    """The plan in plain words, for the panel and for the refusal. Never a code."""
    ai = next(p for p in plan["parts"] if p["name"] == AI_REVIEW)
    rc = next(p for p in plan["parts"] if p["name"] == RULE_CHECK)
    bits = []
    if plan["refused"]:
        return plan["refused"] + "."
    if plan["choice"] == LOCAL:
        bits.append(AI_NEEDS_CLAUDE_LOCAL + ".")
    elif ai["engine"] == ON_CLAUDE:
        bits.append("The AI review runs on Claude.")
    else:
        bits.append(f"The AI review will not run: {ai['why']}.")
    bits.append(
        "The rule check runs on Claude for its AI steps."
        if rc["engine"] == ON_CLAUDE
        else "The rule check runs on this computer."
    )
    bits.append(
        "Text of this paper leaves this computer."
        if plan["text_leaves"]
        else "No text leaves this computer."
    )
    return " ".join(bits)


# ----------------------------------------------------------------------------------------------- the stored choice

TABLE = "review_engine_choice"


def ensure_schema(conn) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            run_id        TEXT PRIMARY KEY,
            choice        TEXT NOT NULL,
            plan_json     TEXT NOT NULL,
            requested_by  TEXT,
            bar_claude    INTEGER NOT NULL DEFAULT 0,
            then_ai       INTEGER NOT NULL DEFAULT 0,
            followed_by   TEXT,
            decided_at    TEXT NOT NULL
        )"""
    )


def record(
    conn,
    run_id: str,
    plan: dict,
    requested_by: str | None,
    *,
    then_ai: bool,
    bar_claude: bool,
    now: str,
) -> None:
    ensure_schema(conn)
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {TABLE} (run_id, choice, plan_json, requested_by, bar_claude, then_ai, decided_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                plan["choice"],
                json.dumps(plan, sort_keys=True),
                requested_by,
                int(bar_claude),
                int(then_ai),
                now,
            ),
        )


def stored(conn, run_id: str | None) -> dict | None:
    """The stored choice of a run, or None. A table not made yet is None (a read creates nothing)."""
    if not run_id:
        return None
    try:
        row = conn.execute(
            f"SELECT * FROM {TABLE} WHERE run_id = ?", (run_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    got = dict(row)
    try:
        got["plan"] = json.loads(got.pop("plan_json"))
    except ValueError:
        got["plan"] = {}
    return got


def bar_for_job(conn, job_id) -> bool:
    """True when the run of this job must stay on this computer: its stored plan says so. A job with no stored choice (the old two
    buttons) is not barred here: the installed switches decide, as before."""
    try:
        row = conn.execute(
            "SELECT review_run_id FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    except sqlite3.Error:
        return False
    got = stored(conn, row["review_run_id"] if row else None)
    return bool(got and got["bar_claude"])


def honouring_choice(job):
    """The review job, with the run's bar up when its plan keeps it on this computer."""
    import functools

    from .db import connect

    @functools.wraps(job)
    def wrapper(job_id, *args, **kwargs):
        if bar_for_job(connect(), job_id):
            with barring():
                state = job(job_id, *args, **kwargs)
        else:
            state = job(job_id, *args, **kwargs)
        # Outside the bar: the AI review that follows a finished rule check is its own run with its own plan.
        from . import review_engine_start

        review_engine_start.follow_up(job_id, state)
        return state

    return wrapper
