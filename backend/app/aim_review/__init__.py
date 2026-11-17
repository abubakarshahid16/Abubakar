"""THE GENERAL REVIEW: one method behind the ONE Review button, for every kind of paper (owner order, 18 Nov 2026).

S1 identify the paper -> the checklist of its TYPE (saved, else S2 choose books among the listed ones + S3 write the checklist
from those books' clauses only, no paper + the attack by a stronger model, then saved) -> S4 judge the paper against it in
batches of 8, by page windows for a long paper. Code verifies every quote and makes every number and unit comparison; a value the
vendor left open is a Question; an item not from a held standard is never Met or Not met.

Consent (CLAUDE.md rule 1): the books are fixed BEFORE the start. `candidates` (plan time: no model, no socket, no write) says
which books the review may use; the run takes `allowed_books` (the list shown, minus the paper) and its catalog holds only those;
a book the paper's type wants that is not on the list is never sent and is counted (`Result.unlisted_books`). Every Claude call
goes `claude_approved.carrying(ids)` -> `claude_spend.metered(step=..)` -> `reader_transport.transport()`, inside
`claude_spend.for_run(run_id)` and `claude_approved.reviewing(run_id)` (`engine.ClaudeModel`).

General only (CLAUDE.md rule 13): nothing here names an equipment type, a standard, a paper or a layout.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

METHOD_VERSION = "aim-1"
LABELS = ("Met", "Not met", "Question", "Does not apply", "AI opinion")
SENDABLE = ("Not met", "Question", "AI opinion")

#: The reasons a rule book is on the plan's list (`Candidates.books[*]["why"]`). One home: `library` reads them from here.
WHY_CITED = "cited by the paper"
WHY_GOVERNS = "governs the equipment type"
WHY_METHOD = "method book of this kind"
WHY_RULES = "rules of this kind"
WHY_LAST = "applied in the last review of this paper"
WHY_SAVED = "in the saved checklist"
WHYS = (WHY_CITED, WHY_GOVERNS, WHY_METHOD, WHY_RULES, WHY_LAST, WHY_SAVED)
#: At most this many rule books on a plan's list.
MAX_BOOKS = 20


@dataclass(frozen=True)
class Candidates:
    kind: str | None
    equipment_type: str | None
    kind_source: str  # how the app's stored reading decided it
    books: list[dict]  # {"id", "why"}
    not_held: list[dict]  # {"name": public standard name, "why"}
    unreadable: int  # books outside `allowed`: counted, never named
    checklist_key: str | None
    checklist_saved: bool


class ChecklistStore(Protocol):
    def get(self, key: str) -> dict | None: ...  # the current checklist body, or None

    def put(
        self, key: str, checklist: dict, *, run_id: str, usd: float
    ) -> str: ...  # returns sha256


@dataclass
class Result:
    status: str  # "done" | "stopped"
    stop_reason: str  # "" or a code + plain words (never document text)
    identity: dict  # {kind, equipment_type, subject, subject_key, service}
    checklist_key: str
    checklist_sha256: str
    checklist_reused: bool
    books: list[str]  # rule-book document ids actually carried
    not_held: list[dict]
    unlisted_books: list[str]
    unlisted_count: int
    lines: list[
        dict
    ]  # ONE per checklist item, in order: section D's `aim_lines` columns (D adds `shown_label`)
    calls: list[dict] = field(
        default_factory=list
    )  # {step, model, usd, input_tokens, output_tokens, seconds, ok, code}
    usd: float = 0.0
    seconds: float = 0.0


#: `code_note` of a line whose item was never answered (the run stopped, a batch failed, its book was not on the list).
NOT_JUDGED = "not_judged"
#: `code_note` of a PROVISIONAL figure (a stated figure beside a who-supplies note, "380 psig (By Contractor)"): always a Question.
#: Code compared it and it PASSED: kept in "All points", never sent (fewer false alarms).
PROVISIONAL = "provisional"
#: ... code compared it and it FAILED: a sent Question whose comment states the check in numbers.
PROVISIONAL_FAILS = "provisional_fails"
#: ... code could not compare it: a sent Question with the AI's comment as written.
PROVISIONAL_UNCHECKED = "provisional_unchecked"
#: The code notes of a line that stays in "All points" and is never a comment.
NOT_SENT_NOTES = (NOT_JUDGED, PROVISIONAL)


def sendable(line: dict) -> bool:
    """Does this line go on the comment sheet? Its label is one of SENDABLE, and its code note is not one of NOT_SENT_NOTES: a
    Question whose only content is "not judged" (RISKS 2), or a provisional figure that code compared and that passed. Such a line
    stays in "All points" and is counted there, never sent to the vendor."""
    return (
        line.get("label") in SENDABLE
        and str(line.get("code_note") or "") not in NOT_SENT_NOTES
    )


def candidates(
    conn,
    paper_id: str,
    allowed: frozenset[str],
    store: ChecklistStore | None,
    earlier_unlisted: frozenset[str] = frozenset(),
) -> Candidates:
    from .library import candidates as _candidates

    return _candidates(
        conn, paper_id, frozenset(allowed), store, frozenset(earlier_unlisted)
    )


def run(
    conn,
    *,
    run_id: str,
    paper_id: str,
    allowed_books: frozenset[str],
    store: ChecklistStore,
    max_usd: float,
    progress: Callable[[int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    model=None,
) -> Result:
    from .engine import run as _run

    return _run(
        conn,
        run_id=run_id,
        paper_id=paper_id,
        allowed_books=frozenset(allowed_books),
        store=store,
        max_usd=max_usd,
        progress=progress,
        cancelled=cancelled,
        model=model,
    )


__all__ = [
    "LABELS",
    "MAX_BOOKS",
    "METHOD_VERSION",
    "NOT_JUDGED",
    "NOT_SENT_NOTES",
    "PROVISIONAL",
    "PROVISIONAL_FAILS",
    "PROVISIONAL_UNCHECKED",
    "SENDABLE",
    "WHYS",
    "WHY_CITED",
    "WHY_GOVERNS",
    "WHY_LAST",
    "WHY_METHOD",
    "WHY_RULES",
    "WHY_SAVED",
    "Candidates",
    "ChecklistStore",
    "Result",
    "candidates",
    "run",
    "sendable",
]
