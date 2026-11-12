"""The AI reviewer's request and response shapes (#1690, contract only).

No route uses these yet: the routes land in the next PR. This file is read by
`scripts/gen_contract_types.py` so the screen and the server share one
definition (`contracts/generated/agent_review.ts`).

POST /api/reviews/agent-run takes `AgentRunRequest` and answers with the
existing `ReviewRunSummary` (schemas.py); no copy of it is made here.

Honesty rules held by the shapes themselves (CLAUDE.md rule 4, owner decision
2 of 11 Nov 2026): a line may carry the word "Pass" or "Fail" only when its
class is "Proven by code"; a number the server does not know is null, never 0;
counts are per class and no field is a percentage.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

#: Class of one CRS line. Only the first is proven by code.
VerdictClass = Literal[
    "Proven by code",
    "AI opinion, engineer to confirm",
    "AI opinion, rule not yet approved",
    "Query for the engineer",
    "Not applicable",
    #: The AI gave no answer for this line, even after the batch was split: the PAPER was not reviewed on it.
    #: Never a Query about the paper.
    "Not reviewed",
    #: GENERAL REVIEW (procedures and contracts, no rule book; owner 11 Nov 2026): a rule book the paper cites that we do not
    #: hold, and an AI engineering note with no rule behind it. Never a Pass, a Fail or an "AI thinks"; internal only.
    "Not checked: rule book not held",
    "AI note, no rule book",
]

#: The word shown on a line.
VerdictWord = Literal[
    "Pass",
    "Fail",
    "AI thinks: met",
    "AI thinks: not met",
    "Query",
    "Not applicable",
    "Not reviewed",
    "Not checked",
    "AI note",
]

#: Who stands behind a rule.
RuleTier = Literal["Owner", "Engineer", "AI approved", "Not AI approved"]

#: Why a rule was not asked of this paper.
LeftOutReason = Literal[
    "needs another paper",
    "needs a human",
    "quote not found",
    "not labelled yet",
    "another equipment type",
    "rule book not held",
    "the paper names no equipment",
    "the paper names equipment the equipment list does not know",
    "the paper's equipment could not be read",
    "a part the paper's equipment does not have",
]

#: The closed table every line must match: class -> (allowed words, allowed
#: tiers). A tier of None (a checklist item has no rule tier) is allowed for
#: every class except "AI opinion, rule not yet approved". "Pass" and "Fail"
#: appear only under "Proven by code", and that class only with them.
_APPROVED_TIERS = ("Owner", "Engineer", "AI approved")
_AI_WORDS = ("AI thinks: met", "AI thinks: not met")
LINE_TABLE: dict[str, tuple[tuple[str, ...], tuple[str | None, ...]]] = {
    "Proven by code": (("Pass", "Fail"), (*_APPROVED_TIERS, None)),
    "AI opinion, engineer to confirm": (_AI_WORDS, (*_APPROVED_TIERS, None)),
    "AI opinion, rule not yet approved": (_AI_WORDS, ("Not AI approved",)),
    "Query for the engineer": (("Query",), (*_APPROVED_TIERS, "Not AI approved", None)),
    "Not applicable": (
        ("Not applicable",),
        (*_APPROVED_TIERS, "Not AI approved", None),
    ),
    "Not reviewed": (
        ("Not reviewed",),
        (*_APPROVED_TIERS, "Not AI approved", None),
    ),
    # General review: no rule, so no tier (null only).
    "Not checked: rule book not held": (("Not checked",), (None,)),
    "AI note, no rule book": (("AI note",), (None,)),
}

#: The ONE place a core word is turned into the contract's word when the two differ: the core words a line the AI judged not
#: for this paper "Query for the engineer" (its class is "Not applicable"); the contract's only word for that class is its own.
WORD_FIXES: dict[tuple[str, str], str] = {
    ("Not applicable", "Query for the engineer"): "Not applicable",
    (
        "Not applicable",
        "Query",
    ): "Not applicable",  # a row stored by 71e9f625 (issue 1749)
    ("Query for the engineer", "Query for the engineer"): "Query",
}


def legal_word(verdict_class: str, word: str) -> str | None:
    """The contract's word for a (class, word) pair, or None when the contract refuses the pair. Reads `LINE_TABLE`."""
    row = LINE_TABLE.get(verdict_class)
    if row is None:
        return None
    word = WORD_FIXES.get((verdict_class, word), word)
    return word if word in row[0] else None


def legal_tier(verdict_class: str, tier: str | None) -> bool:
    row = LINE_TABLE.get(verdict_class)
    return row is not None and tier in row[1]


#: Which part of a general review a line belongs to (null on every line of a rule review).
Part = Literal[
    "not held",
    "checklist",
    "paper against itself",
    "against project papers",
    "engineering comment",
]
#: What the line's text is: a quote from the paper, or the model's own words (a quote is always shown apart, verified by code).
TextSource = Literal["quote", "the model's words"]
#: The classes of a RULE review: a line of these classes carries no part. A line of a general review is one of the four
#: classes below, with a part; "Query" and "Not reviewed" appear in both modes.
RULE_REVIEW_ONLY = (
    "Proven by code",
    "AI opinion, engineer to confirm",
    "AI opinion, rule not yet approved",
    "Not applicable",
)
GENERAL_ONLY = ("Not checked: rule book not held", "AI note, no rule book")
#: The two modes of a run.
Mode = Literal["rule review", "general review"]

#: Where a rule's text was read from: the page text, or a scanned page re-read as a picture (owner 16.3 point 2).
ReadFrom = Literal["text", "scan"]

Count = Annotated[int, Field(ge=0)]


class AgentRunRequest(BaseModel):
    """POST /api/reviews/agent-run body."""

    submittal_document_id: str
    #: General review only (a procedure or a contract): the project papers part 4 is checked against. Optional. Never chosen
    #: silently: each must be readable by the caller and is checked again when the job runs. Empty: part 4 says so on one line.
    project_document_ids: list[str] = Field(default=[], max_length=10)


class AgentProjectPaper(BaseModel):
    """A project paper a general review was checked against."""

    document_id: str
    name: str


class AgentStatus(BaseModel):
    """GET /api/reviews/agent-status: whether the feature is on and whether the
    Claude lane is open. Both false means the screen shows no start button."""

    enabled: bool
    claude_lane_open: bool


class AgentRunSummary(BaseModel):
    """GET /api/reviews/runs/{id}/agent/summary. Counts are per class, over the
    lines of this run only; there is no percentage."""

    paper_kind: str
    paper_kind_source: str
    #: null when the paper has no equipment type (shown as nothing).
    equipment_type: str | None = None
    counts_by_class: dict[VerdictClass, Count] = {}
    #: null until spend is known; never 0 for unknown.
    usd: float | None = Field(default=None, ge=0)
    models: list[str] = []
    #: null when the run was not stopped early.
    stop_reason: str | None = None
    missing_books: list[str] = []
    #: how the paper's equipment was read (the state word), null when not known.
    equipment_state: str | None = None
    #: the sentences about the paper's equipment and the rules left out for it (counts only, no document text).
    equipment_notes: list[str] = []
    #: lines the AI gave no answer for (class "Not reviewed"); also inside counts_by_class.
    not_reviewed: Count = 0
    #: "general review" for a procedure or a contract (no rule book, no Pass or Fail); "rule review" otherwise.
    mode: Mode = "rule review"
    #: the project papers a general review was checked against (empty for a rule review, or when none was named).
    project_papers_used: list[AgentProjectPaper] = []


class AgentLine(BaseModel):
    """One CRS line of the AI reviewer."""

    item_id: str
    verdict_class: VerdictClass
    word: VerdictWord
    #: null when the line has no single page.
    page: int | None = Field(default=None, ge=1)
    clause: str
    rule_book: str
    reason: str
    #: null for a checklist item, which has no rule tier.
    rule_tier: RuleTier | None
    #: general review only: which part the line belongs to; null on a rule review line.
    part: Part | None = None
    #: general review only: whether the text is a quote or the model's words; null otherwise.
    text_source: TextSource | None = None

    @model_validator(mode="after")
    def _class_word_and_tier_agree(self) -> AgentLine:
        words, tiers = LINE_TABLE[self.verdict_class]
        if self.word not in words:
            raise ValueError(
                f'class "{self.verdict_class}" cannot carry the word "{self.word}"'
            )
        if self.rule_tier not in tiers:
            raise ValueError(
                f'class "{self.verdict_class}" cannot have rule tier {self.rule_tier!r}'
            )
        if self.verdict_class in RULE_REVIEW_ONLY and (
            self.part is not None or self.text_source is not None
        ):
            raise ValueError(
                f'class "{self.verdict_class}" belongs to a rule review: it has no part'
            )
        if self.verdict_class in GENERAL_ONLY and self.part is None:
            raise ValueError(
                f'class "{self.verdict_class}" belongs to a general review: it needs its part'
            )
        return self


class AgentLineList(BaseModel):
    """GET /api/reviews/runs/{id}/agent/lines: one page of lines."""

    lines: list[AgentLine] = []
    #: cursor for the next page; null on the last page.
    next: str | None = None


class AgentGateStep(BaseModel):
    """One check a line passed through before it was shown."""

    step: str
    outcome: str
    reason: str


class AgentTrace(BaseModel):
    """GET /api/reviews/runs/{id}/agent/lines/{item_id}/trace."""

    item_id: str
    page: int | None = Field(default=None, ge=1)
    paper_quote: str
    rule_quote: str
    rule_book: str
    clause: str
    model: str
    reason: str
    gate: list[AgentGateStep] = []
    #: general review: the second quote (a second place in the paper, or a project paper); null otherwise.
    other_quote: str | None = None
    #: general review: the part of the review the line belongs to.
    part: Part | None = None


class AgentAskedRule(BaseModel):
    """A rule that was asked of this paper."""

    rule_book: str
    clause: str
    quote: str
    paper_kind: str
    #: null when the rule has no datasheet field.
    field: str | None = None
    #: null when the rule has no equipment type.
    equipment: str | None = None
    tier: RuleTier
    #: "scan" for a rule re-read from a scanned page; "text" otherwise.
    read_from: ReadFrom = "text"


class AgentLeftOutRule(BaseModel):
    """A rule that was not asked, with its one reason."""

    rule_book: str
    clause: str
    reason: LeftOutReason


class AgentMissingBook(BaseModel):
    """A rule book the paper cites that we do not hold. Listed, never counted
    against the system."""

    name: str
    why: str


class AgentBookCoverage(BaseModel):
    """How much of one rule book the stored rules cover (free coverage check). The screen computes the percentage from the
    two integers, so the denominator is always shown; a book with no row in the coverage file has every number null."""

    rule_book: str
    requirement_sentences: int | None = Field(default=None, ge=0)
    covered_sentences: int | None = Field(default=None, ge=0)
    unreadable_pages: int | None = Field(default=None, ge=0)
    weak_pages: int | None = Field(default=None, ge=0)
    below_half: bool | None = None


#: Where the candidate rules of a run came from.
CandidatesFrom = Literal["per-rule scope decisions", "the rules of the selected books"]


class AgentOtherBooks(BaseModel):
    """AI-approved rules of the paper's kind that sit in rule books the run did NOT select (counts only)."""

    books: Count
    ai_approved_rules: Count
    #: whose books these counts cover, in words.
    boundary: str


class AgentRulesUsed(BaseModel):
    """GET /api/reviews/runs/{id}/rules-used (view only)."""

    paper_kind: str
    equipment_type: str | None = None
    asked: list[AgentAskedRule] = []
    left_out: list[AgentLeftOutRule] = []
    #: left-out rules counted per reason.
    left_out_counts: dict[LeftOutReason, Count] = {}
    missing_books: list[AgentMissingBook] = []
    #: how the paper's equipment was read, and the sentences about it (same as the summary).
    equipment_state: str | None = None
    equipment_notes: list[str] = []
    #: coverage of each rule book that was asked or left out; empty when no coverage file is placed.
    books: list[AgentBookCoverage] = []
    #: null unless a person changed the rule set (then their name).
    rule_set_changed_by: str | None = None
    #: where the candidate rules came from; null on a run stored before this was kept (shown as nothing).
    candidates_from: CandidatesFrom | None = None
    #: rules that were the same rule as another candidate (not asked twice, not in either list); null when not kept.
    same_rule_repeats: Count | None = None
    #: AI-approved rules of this paper kind in rule books the run did not select; null when not kept.
    other_books: AgentOtherBooks | None = None
