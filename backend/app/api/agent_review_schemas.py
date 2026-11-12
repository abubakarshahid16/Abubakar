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
    #: Two different AI readers reached the same verdict independently, code verified both readers' quotes and no guard objects
    #: (owner order 13, behind AGENT_REVIEW_TWO_READER_VERDICT_ENABLED). Internal copy only; never a Pass or a Fail.
    "AI verdict, two readers agree",
    #: Two AI readers each found the rule cannot be checked on this paper: it needs a drawing or a calculation (owner order 13, behind
    #: AGENT_REVIEW_TWO_READER_OTHER_PAPER_ENABLED). Not a decision, not a Query, not "Not applicable"; internal only.
    "Not checked on this paper",
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
    "AI verdict: met",
    "AI verdict: not met",
    "AI verdict: not stated",
    "Needs a drawing or a calculation",
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
    "a part excluded by a value the paper states",
    "both labelling readers named other equipment",
]

#: The closed table every line must match: class -> (allowed words, allowed
#: tiers). A tier of None (a checklist item has no rule tier) is allowed for
#: every class except "AI opinion, rule not yet approved". "Pass" and "Fail"
#: appear only under "Proven by code", and that class only with them.
_APPROVED_TIERS = ("Owner", "Engineer", "AI approved")
_AI_WORDS = ("AI thinks: met", "AI thinks: not met")
LINE_TABLE: dict[str, tuple[tuple[str, ...], tuple[str | None, ...]]] = {
    "Proven by code": (("Pass", "Fail"), (*_APPROVED_TIERS, None)),
    "Not checked on this paper": (
        ("Needs a drawing or a calculation",),
        (*_APPROVED_TIERS, None),
    ),
    "AI verdict, two readers agree": (
        ("AI verdict: met", "AI verdict: not met", "AI verdict: not stated"),
        (*_APPROVED_TIERS, None),
    ),
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
    "AI verdict, two readers agree",
    "Not checked on this paper",
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
    #: Ask for fresh first-reader answers: this run ignores every stored answer and replaces it (only when the server keeps stored
    #: answers, `AGENT_REVIEW_REUSE_ANSWERS_ENABLED`; otherwise nothing is stored and the option changes nothing).
    fresh: bool = False


class AgentProjectPaper(BaseModel):
    """A project paper a general review was checked against."""

    document_id: str
    name: str


class AgentStatus(BaseModel):
    """GET /api/reviews/agent-status: whether the feature is on and whether the
    Claude lane is open. Both false means the screen shows no start button."""

    enabled: bool
    claude_lane_open: bool


class AgentTwoReaderStep(BaseModel):
    """What the optional second-reader step did in one run (owner order 13): counts only. `off` is the code that switched the
    step off for the rest of the run (a cap refusal, a failed call, an unknown first-reader model), null when it ran to the end."""

    candidates: Count = 0
    asked: Count = 0
    calls: Count = 0
    #: lines that earned the class "AI verdict, two readers agree".
    agreed: Count = 0
    #: lines where the two readers reached opposite verdicts (a Query for the engineer).
    disagreed: Count = 0
    #: lines asked where the second reader could not tell, or a quote or a guard did not hold (the line stays as it was).
    unconfirmed: Count = 0
    #: absence step only: lines not asked because the first reader was not given every page of the paper.
    skipped: Count = 0
    off: str | None = None


#: What the library holds for the paper to read (order 13, C2). "no text", "not indexed" and "still reading" stop the run before any rule is
#: chosen or any call is made; "partly readable" runs and lists the pages with no stored text.
PaperTextState = Literal[
    "readable", "partly readable", "no text", "not indexed", "still reading"
]


class AgentPaperText(BaseModel):
    state: PaperTextState
    #: null when the library holds no page count for the paper.
    pages_total: int | None = Field(default=None, ge=0)
    #: page numbers with no stored text (every page when state is "no text").
    pages_not_read: list[int] = []
    #: the one plain sentence for a state other than "readable"; null when readable.
    sentence: str | None = None


class AgentChangedSincePrevious(BaseModel):
    """Lines whose class changed since the previous finished run of the same paper (compared before the optional steps). Counts only;
    the ids are in the run's trace. `decisions`: how many of those lines are, or were, a proven Pass or Fail or an AI opinion met or not met."""

    previous_run_id: str
    lines_compared: Count
    changed: Count
    decisions: Count


class AgentPageRereadStop(BaseModel):
    """The optional second reading of pages ended early in this run (a cap or an error inside it, never the review)."""

    #: plain words for the reason, no document text.
    why: str
    #: silent lines that were not re-read because it had ended (the lines carrying the marker; counts equal lines).
    not_reread: Count


class AgentDecisions(BaseModel):
    """Decisions of one run (owner, 12 Nov 2026): lines the code proved (class "Proven by code") plus two-reader verdicts (class "AI verdict,
    two readers agree" with the word met, not met or not stated). "AI thinks" and Queries are not decisions. `not_stated`: how many of the
    two-reader figure are "not stated on the paper" (two readers each read every page and found no value)."""

    code: Count = 0
    two_reader: Count = 0
    not_stated: Count = 0
    total: Count = 0


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
    #: null when the second reading of pages is off or ran fully (shown as nothing, never 0).
    page_reread_stopped: AgentPageRereadStop | None = None
    #: answers taken from an earlier run instead of asking (USD 0 each); null when the server does not keep stored answers.
    answers_reused: Count | None = None
    #: null when there is no earlier finished run of this paper, or this run did not finish whole.
    changed_since_previous: AgentChangedSincePrevious | None = None
    #: lines the AI gave no answer for (class "Not reviewed"); also inside counts_by_class.
    not_reviewed: Count = 0
    #: "general review" for a procedure or a contract (no rule book, no Pass or Fail); "rule review" otherwise.
    mode: Mode = "rule review"
    #: the project papers a general review was checked against (empty for a rule review, or when none was named).
    project_papers_used: list[AgentProjectPaper] = []
    #: the second-reader step of this run (counts and one code, no text); null when the step was off or the run was stored before it.
    two_reader_step: AgentTwoReaderStep | None = None
    #: the same for the absence word ("AI verdict: not stated"); null when that step was off or the run was stored before it.
    two_reader_absence_step: AgentTwoReaderStep | None = None
    #: the same for the other-paper class ("Not checked on this paper"); null when that step was off.
    two_reader_other_step: AgentTwoReaderStep | None = None
    #: the one count of decisions: code Pass/Fail plus two-reader verdicts (class "AI verdict, two readers agree", word met or not met).
    decisions: AgentDecisions | None = None
    #: the paper's stored-text state; null on a run stored before it was kept (shown as nothing).
    paper_text: AgentPaperText | None = None


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
CandidatesFrom = Literal[
    "per-rule scope decisions",
    "the rules of the selected books",
    "the rules of the selected books and per-rule scope decisions",
]


class AgentOtherBooks(BaseModel):
    """AI-approved rules of the paper's kind that sit in rule books the run did NOT select (counts only)."""

    books: Count
    ai_approved_rules: Count
    #: whose books these counts cover, in words.
    boundary: str


class AgentBookRow(BaseModel):
    """One rule book that was a candidate for this review, or was only considered, with what happened to its rules."""

    rule_book: str
    #: true when the book's rules were candidates; false when the book was only considered and not included.
    in_review: bool
    #: the fixed words for what decided it (never text from the paper): named in the paper, governs this equipment type, ...
    method: str
    #: how many rules the library stores for this book (all of them, whatever their label); null when not counted.
    stored_rules: Count | None = None
    #: rules of this book asked in this review.
    asked: Count = 0
    #: rules of this book that were candidates and not asked, counted per reason.
    left_out: dict[LeftOutReason, Count] = {}


class AgentBookTable(BaseModel):
    """Which held rule books were candidates for this review and which were not (view only)."""

    books: list[AgentBookRow] = []
    #: whose books these rows cover, in words (rule 4: every count states its boundary).
    boundary: str
    #: rule books of this review the reader may not read: counted, never named (rule 5).
    hidden_books: Count = 0
    #: a sentence when no book selection was stored for this run (rules came from per-rule decisions); null otherwise.
    note: str | None = None


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
    #: the book-by-book table: which held rule books were candidates and which were not, and why; null on a run stored before it was kept.
    book_table: AgentBookTable | None = None
    #: why the run stopped early, or why no rule was asked (the same words as the summary); null when it ran to its end.
    stop_reason: str | None = None
    #: the paper's stored-text state; null on a run stored before it was kept.
    paper_text: AgentPaperText | None = None
