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
]

#: The word shown on a line.
VerdictWord = Literal[
    "Pass",
    "Fail",
    "AI thinks: met",
    "AI thinks: not met",
    "Query",
    "Not applicable",
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
]

#: The only class allowed to carry "Pass" or "Fail".
PROVEN_CLASS = "Proven by code"
PROVEN_WORDS = ("Pass", "Fail")

Count = Annotated[int, Field(ge=0)]


class AgentRunRequest(BaseModel):
    """POST /api/reviews/agent-run body."""

    submittal_document_id: str


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
    rule_tier: RuleTier

    @model_validator(mode="after")
    def _nothing_unproven_is_pass_or_fail(self) -> AgentLine:
        if self.word in PROVEN_WORDS and self.verdict_class != PROVEN_CLASS:
            raise ValueError(
                f'the word "{self.word}" needs class "{PROVEN_CLASS}", '
                f'not "{self.verdict_class}"'
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


class AgentRulesUsed(BaseModel):
    """GET /api/reviews/runs/{id}/rules-used (view only)."""

    paper_kind: str
    equipment_type: str | None = None
    asked: list[AgentAskedRule] = []
    left_out: list[AgentLeftOutRule] = []
    #: left-out rules counted per reason.
    left_out_counts: dict[LeftOutReason, Count] = {}
    missing_books: list[AgentMissingBook] = []
    #: null unless a person changed the rule set (then their name).
    rule_set_changed_by: str | None = None
