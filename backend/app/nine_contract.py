"""PROPOSAL (outside the repo): the shared shapes of the nine-role review (owner order, STATE sections 59 and 60).

In the repo this becomes `backend/app/nine_contract.py`, written once by the lead before the builders start and read-only for them.
Rules of the shapes:
  * ids, page numbers, clause numbers, counts and checksums everywhere; the only document text is a QUOTE, and a quote is used only
    after code found it in the stored page text (`*_verified` is written by code, never by a model);
  * nothing here is a verdict CLASS or WORD: those are written only by `agent_review_wording.final_cap` (the one exit);
  * the role record (`RoleRecord`, `ReadEntry`, `CallEntry`) is built by code from the request that was actually sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

# ---------------------------------------------------------------- names

ROLE_NAMES: dict[int, str] = {
    1: "Reader",
    2: "Project context",
    3: "Librarian",
    4: "Reviewer",
    5: "Checklist",
    6: "Second reviewer",
    7: "Code",
    8: "Decision rule",
    9: "Writer",
}
#: the step name of each role that can spend money, for `claude_spend` (one cap line per role and run); roles 7 and 8 are code
STEP_OF_ROLE: dict[int, str] = {
    1: "nine_reader",
    2: "nine_context",
    3: "nine_librarian",
    4: "nine_reviewer",
    5: "agent_review",  # the checklist is today's batch path: its step name does not change
    6: "nine_second",
    9: "nine_writer",
}

Engine = Literal["claude", "local", "code"]
RoleState = Literal["ran", "ran_partly", "not_run"]
DocumentKind = Literal["paper", "rule_book", "project_document", "earlier_revision", "review_record"]
FactSource = Literal["stored", "ai_text", "ai_picture"]
FactState = Literal["agreed", "conflict", "ai_only", "stored_only", "needs_engineer", "stale"]
AiVerdict = Literal["met", "not_met", "not_stated", "not_applicable", "cannot_tell"]
FindingOrigin = Literal["reviewer", "checklist", "calculator"]
ChapterWhy = Literal[
    "cited by the paper",
    "named by the project context",
    "holds a rule chosen for this paper",
    "its title names the equipment",
    "chosen by the librarian",
]
NotReadWhy = Literal[
    "over the reading budget",
    "not on the list shown before the start",
    "not approved for Claude",
    "too long for the local model",
    "no stored text",
    "budget reached",
    "run stopped",
]


# ---------------------------------------------------------------- role 1: the fact sheet


@dataclass(frozen=True)
class Fact:
    fact_id: str  # "f:<page>:<n>", stable inside one run
    page: int
    field_label: str  # as printed on the paper
    field_role: str | None  # the field registry's name, set by code (`datasheet_roles`); None when code found none
    value: str | None  # as printed; None = the field is printed and empty
    unit: str | None
    quote: str  # the page words the value was read from
    quote_verified: bool  # code found the quote in the stored page text
    tag: str | None  # equipment tag or column the value belongs to
    cell_ref: str | None  # table cell, when the stored table rows give one
    source: FactSource
    state: FactState
    page_text_sha: str | None  # sha256 of the page text the value was read from
    model: str | None


@dataclass(frozen=True)
class PageRead:
    page: int
    text_read: bool
    picture_read: bool
    not_read_why: str | None  # e.g. "no stored text and pictures are not read on the local model"


@dataclass(frozen=True)
class FactSheet:
    run_id: str
    paper_id: str
    pages_total: int
    pages: tuple[PageRead, ...]
    facts: tuple[Fact, ...]
    conflicts: int  # facts with state "conflict" (never used for a decision)
    engine: Engine
    models: tuple[str, ...]


# ---------------------------------------------------------------- role 2: the context note


@dataclass(frozen=True)
class SourceQuote:
    document_id: str
    page: int
    quote: str
    verified: bool  # code found it on that page of that document


@dataclass(frozen=True)
class StandardNamed:
    name: str  # as the project document writes it
    book_id: str | None  # the held rule book, when the library holds it
    held: bool
    source: SourceQuote


@dataclass(frozen=True)
class Override:
    """A project rule that replaces or tightens a general one. Used only when `source.verified`."""

    subject: str  # the field or topic, in the model's words (shown as such)
    general_ref: str | None  # "<book> <clause>" when the project document names it
    project_rule: SourceQuote
    order_of_precedence: str | None


@dataclass(frozen=True)
class EarlierComment:
    point_id: str
    field: str | None
    status_word: str  # the stored word of that earlier point, unchanged
    engineer_decision: str | None  # keep / edit / remove, when recorded
    still_open: bool | None  # set by code from the new fact sheet; None = cannot tell


@dataclass(frozen=True)
class EarlierRevision:
    document_id: str
    revision: str | None
    run_id: str | None
    comments: tuple[EarlierComment, ...]


@dataclass(frozen=True)
class NotAvailable:
    what: Literal["contract", "project specification", "related papers", "earlier revision", "earlier comments"]
    why: str  # "none held for this project", "held, not on the list shown", "goes to Claude only when you choose Claude", ...


@dataclass(frozen=True)
class ContextNote:
    run_id: str
    project: str | None  # the classification's project value; None = the paper names no project
    documents_read: tuple[str, ...]  # ids
    standards: tuple[StandardNamed, ...]
    overrides: tuple[Override, ...]
    related_papers: tuple[str, ...]  # ids
    earlier: EarlierRevision | None
    not_available: tuple[NotAvailable, ...]  # ALWAYS filled for what was not there: said plainly on the sheet


# ---------------------------------------------------------------- role 3: the reading list


@dataclass(frozen=True)
class ChapterPart:
    part_no: int
    part_of: int
    page_from: int
    page_to: int
    chars: int
    text_sha256: str


@dataclass(frozen=True)
class Chapter:
    book_id: str
    chapter_id: str  # the heading's own number or letter; "pages 13-24" when the book has no headings code can find
    title_line: int  # line index of the heading in the stored text (the title is read from the book at display time)
    depth: int
    page_from: int
    page_to: int
    chars: int
    parts: tuple[ChapterPart, ...]  # one part when the chapter fits one call
    cut_by: Literal["heading", "page window"]


@dataclass(frozen=True)
class ReadingItem:
    chapter: Chapter
    why: tuple[ChapterWhy, ...]
    rank: int
    chosen: bool
    not_read_why: NotReadWhy | None  # set when chosen is False, or when a chosen chapter could not be read


@dataclass(frozen=True)
class BookChoice:
    book_id: str
    why: tuple[str, ...]  # "cited by the paper", "governs the equipment type", "named by the project context", ...
    on_shown_list: bool
    items: tuple[ReadingItem, ...]


@dataclass(frozen=True)
class ReadingList:
    run_id: str
    books: tuple[BookChoice, ...]
    books_wanted_not_listed: int  # counted, never named to a reader who may not read them
    tokens_planned: int
    tokens_limit: int


# ---------------------------------------------------------------- roles 4 and 5: findings


class RawFinding(TypedDict, total=False):
    """What the reviewer model returns for ONE issue (the answer shape of today's first reader, plus the clause it read)."""

    issue: str  # at most 25 words, the model's words
    field_label: str
    paper_page: int
    paper_quote: str
    clause: str
    clause_quote: str
    paper_figure: str
    clause_figure: str
    condition_quote: str
    condition_page: int
    verdict: str  # met | not_met | not_stated | not_applicable | cannot_tell
    reasoning: str
    comment: str
    fact_ids: list[str]


@dataclass(frozen=True)
class Finding:
    """One issue after code joined the raw findings of every call. Becomes ONE row of `agent_review_line` through the one exit."""

    finding_id: str  # "F-<12 hex>" of (book, clause, field key, tag)
    item_id: str  # "R-<rule id>" when code matched it to a stored rule, else the finding id
    origin: FindingOrigin
    book_id: str | None
    clause: str | None
    clause_page: int | None  # the page code located the clause quote on (the book's own pages)
    field_label: str | None
    field_roles: tuple[str, ...]
    tag: str | None
    paper_page: int | None
    paper_quote: str | None
    clause_quote: str | None
    ai_verdict: AiVerdict
    matched_rule_id: str | None
    rule_tier: str | None  # the matched rule's CURRENT tier; None = no approved rule behind it (an opinion at most)
    members: tuple[str, ...]  # call ids of the raw findings joined into this one
    contradiction: bool  # raw findings of one issue disagreed: the line is a Query that says so
    read_refs: tuple[tuple[str, str, int], ...]  # (book id, chapter id, part no) the reviewer was given when it wrote this


@dataclass(frozen=True)
class RequiredItem:
    item_id: str  # the plan's own item id ("R-...", "S-...") or "Q-<field role>" for a carried field
    source: Literal["rule chosen for this paper", "approved checklist", "field this kind of sheet must carry"]
    mentioned_by: str | None  # finding id that covers it; None = the checklist role asks it


# ---------------------------------------------------------------- role 6: challenges


@dataclass(frozen=True)
class Challenge:
    finding_id: str
    model: str
    different_family: bool  # by `agent_run_second.models_differ`
    independent: bool  # the request held no first-reader verdict, quote or reasoning
    verdict: AiVerdict
    paper_page: int | None
    paper_quote: str | None
    clause_quote: str | None
    paper_quote_verified: bool
    clause_quote_verified: bool
    same_evidence: bool  # by `agent_review_two_reader.same_evidence`
    agrees: bool  # by `agent_review_two_reader.agrees`, re-derived at the exit, never trusted from here


# ---------------------------------------------------------------- section 60: the record


@dataclass(frozen=True)
class ReadEntry:
    """One document block of one request, written by code from the block list the request was built from."""

    role_no: int
    call_id: str
    document_id: str
    document_kind: DocumentKind
    pages: tuple[int, ...]
    chapter_id: str | None
    part_no: int | None
    part_of: int | None
    chars: int
    text_sha256: str
    pictures: int


@dataclass(frozen=True)
class CallEntry:
    role_no: int
    call_id: str
    step: str
    engine: Engine
    model: str
    request_sha256: str  # the same digest the spend ledger keeps for a Claude call
    state: Literal["sent", "answered", "failed", "refused", "reused"]
    error_code: str | None
    usd: float | None  # None on the local model and for a refused call; never 0 for "unknown"
    sent_at: str


@dataclass(frozen=True)
class RoleRecord:
    role_no: int
    role: str
    state: RoleState
    why: str | None  # required unless state is "ran"
    engine: Engine | None
    models: tuple[str, ...]
    calls: int
    usd: float | None
    produced: dict[str, int | str | list] = field(default_factory=dict)  # counts and ids only
    reads: tuple[ReadEntry, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class ReviewRecord:
    run_id: str
    paper_id: str
    engine_choice: Literal["automatic", "claude", "local"]
    roles: tuple[RoleRecord, ...]  # always nine, in order
    calls: tuple[CallEntry, ...]
    shown_document_ids: tuple[str, ...] | None  # the list stored at the start; None = no list was stored

    def not_run(self) -> tuple[RoleRecord, ...]:
        return tuple(r for r in self.roles if r.state == "not_run")

    def roles_line(self) -> str:
        """The first-sheet line. Words only from the record: a role that did not run is named with its reason."""
        ran = [f"{r.role_no} {r.role}" + (" (partly)" if r.state == "ran_partly" else "") for r in self.roles if r.state != "not_run"]
        out = f"Roles run: {len(ran)} of {len(self.roles)}" + (": " + ", ".join(ran) if ran else "")
        missing = [f"{r.role_no} {r.role}: {r.why}" for r in self.not_run()]
        return out + ("; not run: " + "; ".join(missing) if missing else "; not run: none")
