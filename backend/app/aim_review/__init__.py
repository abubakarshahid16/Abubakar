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
    ]  # per checklist item in order: one line, or one per place where it fails (by page, <= 6): D's `aim_lines` columns + finding_no
    calls: list[dict] = field(
        default_factory=list
    )  # {step, model, usd, input_tokens, output_tokens, seconds, ok, code}
    usd: float = 0.0
    seconds: float = 0.0
    #: The reference papers of a contract review and what was done with each (`references.check`): not rule books, not in `books`.
    references: list = field(default_factory=list)
    #: {book document id: the reason the scope step chose it} for the books in `books` (empty text: no reason was recorded).
    book_why: dict = field(default_factory=dict)


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
#: Two values of the PAPER compared by code and they PASSED, with the rule's operator (or the AI's, when the AI itself did not say
#: Not met): an AI opinion that is no finding, kept in "All points", never sent. Appended to the line's other notes.
PAPER_COMPARE_PASSED = "paper_compare_passed"
#: `code_note` part of a line the editor step (S5) took off the comment sheet: "edited: repeats line 3", "edited: paper states
#: otherwise (page 2: ...)". Its label is unchanged; it stays in "All points" with its reason.
EDITED = "edited"
#: `code_note` part of a line on NO held rule that the whole-paper check (S4b, `answered.py`) found answered by the paper:
#: "answered: the paper answers it on page 7: "..."" (a quote code found on that page). It stays in "All points", never sent.
ANSWERED = "answered"
#: `code_note` part of a line whose quoted figure the contractor FILLED IN beside a who-supplies note ("380 psig (By Contractor)"):
#: judged as a stated value (owner, 18 Nov 2026 after live); the note says where the figure came from.
CONTRACTOR_FILLED = "filled in by the contractor (By Contractor)"
#: `code_note` parts of the second reader (S4c, `second_read.py`): both readers find a fault, or they differ ("readers differ:
#: first Not met, second Met"): a line the readers differ on is sent as a Question to be checked, with both readers' words.
TWO_READERS_AGREE = "two readers agree"
READERS_DIFFER = "readers differ"
#: `code_note` part of a line that sets a value of one equipment item against another item's (`items.py`): "different_items: page
#: 2 "X" / page 3 "Y"" (both names found on their pages). No finding: it stays in "All points", never sent.
DIFFERENT_ITEMS = "different_items"
NOT_SENT_NOTES = (
    NOT_JUDGED,
    PROVISIONAL,
    PAPER_COMPARE_PASSED,
    EDITED,
    DIFFERENT_ITEMS,
    ANSWERED,
)


def sendable(line: dict) -> bool:
    """Does this line go on the comment sheet? Its label is one of SENDABLE, and no part of its code note ("; "-joined) is one of
    NOT_SENT_NOTES: a Question whose only content is "not judged" (RISKS 2), a provisional figure that code compared and that
    passed, or a passed compare of two paper values. Such a line stays in "All points" and is counted there, never sent."""
    parts = {p.strip() for p in str(line.get("code_note") or "").split(";")}
    parts |= {
        p.split(":", 1)[0].strip() for p in parts
    }  # "edited: repeats line 3" -> "edited"
    return line.get("label") in SENDABLE and not parts & set(NOT_SENT_NOTES)


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
    cited_books: frozenset[str] | None = None,
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
        cited_books=cited_books,
    )


__all__ = [
    "ANSWERED",
    "CONTRACTOR_FILLED",
    "DIFFERENT_ITEMS",
    "EDITED",
    "LABELS",
    "MAX_BOOKS",
    "METHOD_VERSION",
    "NOT_JUDGED",
    "NOT_SENT_NOTES",
    "PAPER_COMPARE_PASSED",
    "PROVISIONAL",
    "PROVISIONAL_FAILS",
    "PROVISIONAL_UNCHECKED",
    "READERS_DIFFER",
    "SENDABLE",
    "TWO_READERS_AGREE",
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
