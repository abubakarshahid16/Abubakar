"""The general review method (order 14, piece A): any paper in, one line per checklist item out.

BASE BRANCH VERSION (integrator): the frozen interface of CONTRACT section A (constants, dataclasses, signatures) and stand-ins
that return a FIXED fake `Candidates` / `Result`, so pieces B, C, D and F can run against them. Piece A replaces the stand-ins.
The stand-ins make no model call, open no socket and write nothing.
"""

# ruff: noqa: ARG001 - the stand-ins take the frozen signatures and use none of their arguments; piece A replaces them
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

METHOD_VERSION = "aim-1"
LABELS = ("Met", "Not met", "Question", "Does not apply", "AI opinion")
#: The labels that make a comment on the sheet (the rest stay on "All points").
SENDABLE = ("Not met", "Question", "AI opinion")

#: The reasons a rule book is on the plan's list (`Candidates.books[*]["why"]`).
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
    books: list[dict]  # {"id": document id, "why": one of WHYS}
    not_held: list[dict]  # {"name": public standard name, "why": str}
    unreadable: int  # books outside `allowed`: counted, never named
    checklist_key: str | None
    checklist_saved: bool


class ChecklistStore(Protocol):
    def get(self, key: str) -> dict | None:  # the current checklist body, or None
        ...

    def put(
        self, key: str, checklist: dict, *, run_id: str, usd: float
    ) -> str:  # returns sha256
        ...


@dataclass
class Result:
    status: str  # "done" | "stopped"
    stop_reason: str  # "" or a code + plain words (never document text)
    identity: dict  # {kind, equipment_type, subject, subject_key, service}
    checklist_key: str
    checklist_sha256: str
    checklist_reused: bool
    books: list[str]  # document ids actually carried
    not_held: list[dict]
    unlisted_books: list[str]
    unlisted_count: int
    lines: list[dict]  # ONE per checklist item, in order: the `aim_lines` columns
    calls: list[dict] = field(
        default_factory=list
    )  # {step, model, usd, input_tokens, output_tokens, seconds, ok, code}
    usd: float = 0.0
    seconds: float = 0.0


# ---- stand-ins below: piece A replaces them ------------------------------------------------------------------------------

#: The fixed fake checklist key of the stand-ins (invented).
FAKE_KEY = "fake-kind/fake-type"


def candidates(
    conn,
    paper_id: str,
    allowed: frozenset[str],
    store: ChecklistStore,
    earlier_unlisted: frozenset[str] = frozenset(),
) -> Candidates:
    """STAND-IN: no book, nothing held, nothing read."""
    return Candidates(
        kind=None,
        equipment_type=None,
        kind_source="stand-in",
        books=[],
        not_held=[],
        unreadable=0,
        checklist_key=FAKE_KEY,
        checklist_saved=False,
    )


def _fake_line(n: int, label: str, shown: str) -> dict:
    return {
        "line_no": n,
        "item_id": f"C{n:02d}",
        "label": label,
        "shown_label": shown,
        "field": f"invented field {n}",
        "page": n,
        "quote": "",
        "quote_unverified": 0,
        "comment": f"invented comment {n}",
        "standard": "",
        "book_document_id": None,
        "clause": "",
        "source": "stand-in",
        "topic": "",
        "code_note": "",
        "numbers_json": None,
        "code_compare_json": None,
    }


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
    """STAND-IN: a fixed fake result of three lines (one Question, one AI opinion, one Met); no call, no write."""
    return Result(
        status="done",
        stop_reason="",
        identity={
            "kind": None,
            "equipment_type": None,
            "subject": "invented",
            "subject_key": "invented",
            "service": "",
        },
        checklist_key=FAKE_KEY,
        checklist_sha256="0" * 64,
        checklist_reused=False,
        books=[],
        not_held=[],
        unlisted_books=[],
        unlisted_count=0,
        lines=[
            _fake_line(1, "Question", "Question"),
            _fake_line(2, "AI opinion", "AI opinion"),
            _fake_line(3, "Met", "AI opinion: met"),
        ],
    )
