"""Typed response models.

Every 200 was documented as `string` and every error as "Undocumented", which
means the frontend types were guesses. The UI is generated against this
contract, so an untyped contract is a UI that cannot be trusted to match the
API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocStatus = Literal[
    "queued",
    "extracting",
    "chunking",
    "indexing_keyword",
    "partially_searchable",
    "ready",
    "no_searchable_content",
    "failed",
]

ChunkKind = Literal["prose", "table", "toc", "frontmatter", "index", "references"]


class ApiError(BaseModel):
    """The only error shape the API returns. Never carries internal detail."""

    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["no document with that id"])
    document_id: str | None = None
    stage: str | None = None
    at: str | None = Field(default=None, examples=["2026-09-04T00:00:00Z"])


class ErrorEnvelope(BaseModel):
    """FastAPI wraps HTTPException detail under `detail`."""

    detail: ApiError


class DocumentError(BaseModel):
    code: str
    message: str


class Document(BaseModel):
    id: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int | None = Field(None, description="null until the manifest is read")
    pages_done: int
    chunk_count: int = Field(description="retrievable chunks - what search can see")
    chunk_count_total: int = Field(description="every chunk row, including excluded")
    embedded_count: int
    status: DocStatus
    needs_ocr_pages: int = Field(
        description="pages with no usable extractable text - candidates for "
        "recognition. Not the same as recognised_pages: some are simply blank"
    )
    recognised_pages: int = Field(
        0,
        description="pages OCR actually read text from. A COUNT, never a "
        "badge: a 546-page document with 12 recognised pages must not be "
        "presented as 'OCR'd'. State the fraction.",
    )
    equation_pages: int = Field(description="maths did not survive extraction")
    error: DocumentError | None = None
    pages_excluded: int = Field(
        0, description="pages search cannot see at all - not a quiet count"
    )
    pages_excluded_characters: int = 0
    pages_excluded_with_clause_headings: int = Field(
        0,
        description="excluded pages that carried numbered clause headings AND "
        "real prose. Should always be zero; if it is not, real content was "
        "almost certainly dropped",
    )
    uploaded_at: str
    indexed_at: str | None = None


class UploadAccepted(BaseModel):
    document: Document | None = None
    job_id: str = Field(description="empty when the upload was a duplicate")
    duplicate_of: str | None = None
    awaiting_grant: bool = Field(
        False,
        description="true when an administrator must grant the caller access",
    )


class WorkerStatus(BaseModel):
    alive: bool
    current_document: str | None
    seconds_since_heartbeat: float
    seconds_since_progress: float = Field(
        description="since a document last reached a terminal state"
    )
    documents_completed: int
    pending_count: int
    oldest_pending_age_seconds: float | None
    stalled: bool = Field(
        description="not running, or no heartbeat, or work pending with no progress"
    )
    stalled_reasons: list[str]
    last_error: ApiError | None = Field(
        None, description="response-safe only; tracebacks go to the local log"
    )


class HealthWorker(BaseModel):
    """The only worker facts an unauthenticated caller may have.

    Deliberately NOT WorkerStatus. Adding a field to WorkerStatus must never
    silently widen what /api/health exposes, and a separate model is what makes
    that impossible rather than merely discouraged.
    """

    alive: bool
    stalled: bool = Field(
        description="up but not making progress - distinct from down"
    )
    busy: bool = Field(
        description="a document is being processed. WHETHER, never WHICH: the "
        "badge needs this so a healthy long ingest does not read as a fault, "
        "and a boolean says work is under way where an id would say whose."
    )


class Health(BaseModel):
    ok: bool
    embed_model_present: bool
    answer_model_present: bool = Field(
        description="whether an answer model is configured, NOT which one. The "
        "exact name and version is fingerprinting material and lives on the "
        "scoped /api/metrics."
    )
    ingestion: HealthWorker


class Chunk(BaseModel):
    id: str
    ordinal: int
    page_start: int
    page_end: int
    section: str | None
    kind: ChunkKind
    token_count: int
    content_hash: str
    retrievable: bool
    quality_flags: str | None = Field(None, description="why the gate excluded it")
    text: str


class ChunkPage(BaseModel):
    total_matching: int
    limit: int
    offset: int
    chunks: list[Chunk]


class Page(BaseModel):
    page_no: int
    char_count: int
    needs_ocr: bool
    equation_heavy: bool
    batch_no: int
    preview: str


class PagesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    pages: list[Page]


class ExclusionSummary(BaseModel):
    scope: Literal["page", "chunk"]
    rule: str
    count: int
    characters_dropped: int
    clause_heading_pages: int = 0


class Exclusion(BaseModel):
    scope: Literal["page", "chunk"]
    page_start: int | None
    page_end: int | None
    chunk_id: str | None
    rule: str
    reason: str | None
    text_length: int
    text_sample: str
    clause_headings: int = Field(
        0, description="non-zero means this exclusion probably dropped real content"
    )


class ExclusionsResponse(BaseModel):
    total: int
    summary: list[ExclusionSummary]
    limit: int
    offset: int
    excluded: list[Exclusion]


class ExtractResult(BaseModel):
    document_id: str
    filename: str
    pages_total: int | None
    pages_extracted: int
    pages_extracted_this_run: int
    needs_ocr: int
    equation_heavy_pages: int | None = None
    seconds: float
    pages_per_sec: float | None = Field(
        None, description="null when nothing ran or the interval is unmeasurable"
    )
    resumed_from_batch: int
    error: str | None = None


class ChunkResult(BaseModel):
    document_id: str
    filename: str
    pages: int
    chunks: int
    chunks_retrievable: int | None = None
    chunks_non_retrievable: int | None = None
    chunks_by_kind: dict[str, int] | None = None
    chunks_rejected_by_quality_gate: int | None = None
    pages_excluded: int | None = None
    exclusions_recorded: int | None = None
    chunks_this_run: int
    skipped: bool
    reason: str | None = None
    chunks_per_page: float | None = None
    tables_kept_whole: int | None = None
    chunks_spanning_pages: int | None = None
    running_lines_detected: int | None = None
    running_lines_removed: int | None = None
    token_min: int | None = None
    token_median: int | None = None
    token_max: int | None = None
    token_ceiling: int | None = None
    seconds: float
    chunks_per_sec: float | None = None


class EmbedResult(BaseModel):
    document_id: str
    embedded_this_run: int
    embedded_count: int
    chunk_count: int
    status: DocStatus
    indexed_at: str | None


class KeywordHit(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    section: str | None
    page_start: int
    page_end: int
    bm25: float = Field(description="lower is a better match")
    text: str


class KeywordSearchResult(BaseModel):
    query: str
    match_expression: str = Field(description="the FTS5 expression actually run")
    total: int
    seconds: float
    hits: list[KeywordHit]


class Passage(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    section: str | None
    page_start: int
    page_end: int
    text: str
    score: float
    rrf: float
    boost: float = Field(description="added for exact identifier matches")
    rerank_score: float | None
    bm25: float | None
    cosine: float | None
    keyword_rank: int | None
    dense_rank: int | None
    identifier_hits: list[str]
    text_source: Literal["extracted", "recognised"] = Field(
        "extracted",
        description="'extracted' means the characters came out of the PDF's own "
        "text layer and CAN be called a verbatim quotation. 'recognised' means "
        "OCR read them off a page image - a guess about pixels, which must NEVER "
        "carry the verbatim label. A chunk spanning one recognised page and one "
        "extracted page is 'recognised': the reader cannot tell which sentence "
        "came from where.",
    )
    ocr_min_conf: float | None = Field(
        None,
        description="lowest OCR confidence across the chunk's recognised pages - "
        "the weakest evidence governs. null for extracted text. A number here is "
        "data, not a quality gate: nothing is hidden on the strength of it.",
    )
    ocr_alphabet_violations: int = 0
    ocr_alphabet_sample: str | None = None


# ----------------------------------------------------- classification
#
# WHAT A DOCUMENT IS. Not who may read it - `disciplines` and
# `document_role_access` decide that, and nothing here touches them.
#
# Typed because tests/test_no_internal_leaks.py requires every 2xx to declare
# a schema: an untyped 200 documents itself as `string`, and every frontend
# type written against it is then a guess.


class SubjectRow(BaseModel):
    id: str
    name: str
    kind: Literal["system", "facility", "project_wide"] = Field(
        description="'project_wide' is a KIND, not a system that happens to "
                    "be called Project-wide: 18% of the register applies to "
                    "everything, and those are the documents gap analysis "
                    "holds as baselines")


class ClassificationVocabulary(BaseModel):
    """The filter vocabulary. NOT SCOPED - the COUNTS are.

    A discipline the caller cannot read stays VISIBLE here. Discipline names
    are project structure, effectively the client's org chart, and not
    evidence that any document exists. Hiding one teaches a user the system is
    broken rather than that they need access; showing it beside a zero count
    tells them the truth.
    """

    register_revision: str | None = Field(
        None, description="null when no register has been imported. The "
                          "frontend must not compute a percentage against a "
                          "denominator it was not handed")
    types: list[str]
    disciplines: list[str]
    subjects: list[SubjectRow]
    needs_classification: int = Field(
        description="documents IN THIS CALLER'S SCOPE awaiting confirmation. "
                    "Scoped, unlike the vocabulary: a count is a statement "
                    "about documents")


class DocumentSubject(BaseModel):
    id: str
    name: str
    kind: str
    suggested_by: str
    confirmed_by: str | None


class DocumentClassification(BaseModel):
    """One document's classification. EVERY FIELD NULLABLE, and NULLs are real.

    `doc_type`/`discipline` null means nothing matched and nothing was
    guessed. `confirmed_by` null means SUGGESTED, NOT CONFIRMED - which is
    the state the needs-classification queue is built from.
    """

    document_id: str
    doc_type: str | None
    discipline: str | None
    doc_class: str | None = Field(
        None, description="P&ID, DATASHEET, SLD... A CHIP ONLY. Measured: 88% "
                          "derivable and nobody searches by it, so it is "
                          "deliberately not a filter axis")
    register_id: str | None = Field(
        None, description="the register row this document IS, or null when it "
                          "is not in the register at all")
    suggested_by: str = Field(
        description="'register' | 'pattern' | 'none' - WHICH TIER produced "
                    "the value. Kept after confirmation: an admin confirming "
                    "what the register already said is a different fact from "
                    "an admin confirming a guess")
    confirmed_by: str | None
    confirmed_at: str | None
    confirmed: bool
    subjects: list[DocumentSubject]


class ClassificationUpdate(BaseModel):
    """An administrator's decision. THE ADMIN CAPABILITY IS REQUIRED.

    A wrong classification misroutes searches for EVERYONE, not only for the
    person who set it, so it needs a role that answers for everyone.

    `subject_ids` REPLACES the set rather than merging: an administrator
    removing a subject must be able to remove it, and merging would leave a
    document permanently attached to a comparison it does not belong in.
    """

    doc_type: str | None = None
    discipline: str | None = None
    doc_class: str | None = None
    subject_ids: list[str] = Field(default_factory=list)


class CoverageByType(BaseModel):
    type: str
    in_register: int | None = Field(
        None, description="NULL when no register is loaded. A zero "
                          "denominator invites a percentage; a null cannot be "
                          "divided by")
    uploaded: int
    unconfirmed: int


class CoverageByDiscipline(BaseModel):
    discipline: str
    in_register: int | None
    uploaded: int
    unconfirmed: int


class CoverageBySubject(BaseModel):
    subject: str
    kind: str
    uploaded: int
    disciplines_spanned: int = Field(
        description="the measurement that made subject the comparison axis - "
                    "5.5 on average across the register - reported per "
                    "subject so a reader sees it on their own corpus")


class ClassificationCoverage(BaseModel):
    register_loaded: bool
    register_revision: str | None
    by_type: list[CoverageByType]
    by_discipline: list[CoverageByDiscipline]
    by_subject: list[CoverageBySubject]
    needs_classification: int
    corpus_wide: bool = Field(
        description="whether these counts are the WHOLE corpus or only what "
                    "this caller may read. The screen must say which")


class ClassificationScope(BaseModel):
    """An OPTIONAL classification filter. Absent means today's behaviour.

    IT MAY ONLY EVER NARROW. Applied by intersecting with the caller's
    `allowed_document_ids` before retrieval runs, so a filter naming a subject
    whose documents the caller may not read yields nothing rather than a leak -
    and yields it without saying whether any such document exists.
    """

    types: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    subject_ids: list[str] = Field(default_factory=list)


class AppliedScope(BaseModel):
    """The filter that WAS applied, echoed on every response.

    Echoed rather than assumed, so the frontend can print "Searched: ..." on
    an answer and a report can print the same line. A reader who cannot see
    which slice of the corpus was searched cannot judge an absence: "no
    evidence" and "no evidence in the three documents you filtered to" are
    different findings.
    """

    applied: bool
    types: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    subject_ids: list[str] = Field(default_factory=list)
    documents_in_scope: int = Field(
        description="how many documents the search could actually reach after "
                    "the filter and the caller's own grants were intersected")


class SearchResult(BaseModel):
    query: str
    mode: Literal["hybrid", "keyword_only"] = Field(
        description="keyword_only until embeddings exist; upgrades automatically"
    )
    reranked: bool
    keyword_candidates: int
    dense_candidates: int
    total: int
    seconds: float
    timings: dict[str, float]
    hits: list[Passage]
    #: THE FILTER THAT WAS APPLIED, echoed so a reader can judge an absence.
    #: "no evidence" and "no evidence in the slice you filtered to" are
    #: different findings, and a screen that cannot tell them apart will show
    #: the first when it means the second. Optional so a response predating
    #: the filter still validates.
    applied_scope: AppliedScope | None = None


AnswerType = Literal[
    "extract",
    "generated",
    "insufficient_evidence",
    "model_unavailable",
    # the input was never a document question - a greeting, thanks, chitchat
    "guidance",
]


class AnswerPassage(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_start: int
    page_end: int
    section: str | None
    text: str
    highlight: list[int] | None = Field(
        None, description="character offsets of the answering span within text"
    )
    match_span: list[int] | None = Field(
        None,
        description="offsets of the chunk that actually matched, inside the "
        "expanded passage - retrieval works small, the reader is shown big",
    )
    chunks_joined: int = Field(
        1, description="how many chunks were joined to form this passage"
    )
    kind: ChunkKind = Field(
        "prose",
        description="a table cannot be reflowed as prose - its column pairing "
        "is positional, so wrapping it destroys the only structure it has",
    )
    score: float
    identifier_hits: list[str] = []
    text_source: Literal["extracted", "recognised"] = Field(
        "extracted",
        description="'recognised' means OCR read this off a page image. It must "
        "NEVER be presented under the verbatim-quotation label; render the "
        "OCR label with the page image expanded instead.",
    )
    ocr_min_conf: float | None = None
    ocr_alphabet_violations: int = Field(
        0,
        description="characters in this passage the document's script cannot "
        "contain. PROOF of a substitution, not an opinion about one - two "
        "passages can both sit at 0.95 confidence and one of them contains a "
        "CJK ideograph. Escalates the OCR label; never hides the passage.",
    )
    ocr_alphabet_sample: str | None = None


DocumentCoverageStatus = Literal[
    "answered",
    "supporting",
    "credible_not_cited",
    "retrieved_not_credible",
    "expected_not_shortlisted",
    "expected_not_retrieved",
    "searched_no_match",
]


class DocumentCoverage(BaseModel):
    document_id: str
    filename: str
    status: DocumentCoverageStatus = Field(
        description="credible_not_cited is the one that matters to a reader: a "
        "passage from this document cleared the credibility floor and the "
        "answer used others instead"
    )
    expected: bool = Field(
        description="carries a distinguishing term from the question. Presence, "
        "NOT relevance - no completeness claim rests on this field"
    )
    distinguishing_terms: list[str] = []
    candidates: int = Field(description="reached the fused pool. 0 is a real 0")
    shortlisted: int
    best_rerank_score: float | None = Field(
        None,
        description="null unless a passage from this document was scored in the "
        "final rerank batch. NEVER 0.0 as a stand-in: 0.0 sits above the -3.0 "
        "floor and would read as credible",
    )
    reason: str | None = None


class Coverage(BaseModel):
    basis: Literal["credible_uncited", "single_document_scope", "none"] = Field(
        description="what the completeness verdict rests on. term_incidence is "
        "absent by measurement, not oversight: it made all twelve documents "
        "'expected' on the gold question this feature exists to measure"
    )
    expected_documents: int | None = Field(
        None, description="documents that produced a credible passage. Null "
        "when no completeness claim is made - never 0"
    )
    found_documents: int | None = None
    searched_documents: int
    complete: bool | None = Field(
        None,
        description="false when a credible passage went unused; otherwise NULL. "
        "Never true. A null MUST render as nothing at all - no tick, no green - "
        "because rendering it as a checkmark turns 'I did not check' into "
        "'I checked and it is fine'",
    )
    documents: list[DocumentCoverage] = []
    note: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class Me(BaseModel):
    """What a client may know about itself.

    Roles, never grants. The document ids a user may see are deliberately
    absent: the scope is derived server-side on every request, and handing the
    client the list gives it something to check its guesses against.
    """

    id: str
    email: str
    display_name: str
    roles: list[str]


class AuthStatus(BaseModel):
    """Whether signing in is required here, and who is signed in.

    `/api/health` deliberately does NOT carry this. Health is unauthenticated
    and was narrowed on purpose; adding `auth_mode` to it would re-widen the
    surface that was just reduced.

    Under `disabled` this returns `required: false, user: null` to an
    anonymous caller. That tells them authentication is off - which is not a
    leak, because under `disabled` the same caller can already read every
    document. Under `demo_required` an anonymous caller gets 401 instead, and
    that 401 is how the frontend knows to show a login screen.
    """

    required: bool = Field(
        description="whether a token is needed. False means AUTH_MODE is "
        "disabled and every request already sees everything"
    )
    user: Me | None = None


class LoginResult(BaseModel):
    token: str = Field(
        description="bearer token. The client holds this in memory only - "
        "never localStorage, where every XSS becomes credential theft rather "
        "than a session-length nuisance. A reload logs you out."
    )
    user: Me
    expires_in_seconds: int


class ProgressStep(BaseModel):
    stage: str
    at_seconds: float


class Progress(BaseModel):
    """Reported by the work itself, never inferred from a clock.

    There is deliberately NO percentage: the generation length is unknown
    until it ends, so any bar would be a guess. A stage, a count and an
    elapsed time are all true.
    """

    stage: Literal["retrieving", "reranking", "reading", "generating", "done"]
    detail: str | None = Field(
        None, description="e.g. '3 passages' - a count, never a percentage")
    seconds: float
    history: list[ProgressStep] = Field(
        description="every transition that actually happened, with when")


class EvidenceItem(BaseModel):
    """One retrieved passage, as everything downstream cites it.

    `evidence_id` is sha256 over the document, page span, section and the
    quoted text - NOT a chunk id. A chunk id changes when a document is
    re-chunked, and a citation that moves when the chunker is retuned is not a
    citation.
    """

    evidence_id: str
    document_id: str
    filename: str
    page_start: int
    page_end: int
    section: str | None
    exact_span: str = Field(description="verbatim; rendered in serif, never as prose")
    text_source: Literal["extracted", "recognised"]
    ocr_min_conf: float | None
    ocr_alphabet_violations: int
    relevance_score: float | None = Field(
        None, description="null unless scored in the final rerank batch. Never "
        "0.0 as a stand-in - 0.0 sits above the -3.0 floor and reads as credible")
    relevance_score_type: Literal["rerank"] | None = Field(
        None, description="WHICH SCALE the number is on. A rerank score and an "
        "RRF score are not comparable, so a bare number would invite exactly "
        "the comparison this system forbids. Null when nothing scored it")


class DocumentedFinding(BaseModel):
    claim: str
    citation_ids: list[str]
    source_kind: Literal["document", "user_stated"] = Field(
        description="nothing generated here is user_stated: a typed "
        "requirement is the requirement, not evidence")
    text_source: Literal["extracted", "recognised", "mixed"]


class DroppedSentence(BaseModel):
    sentence: str
    reason: str


class AnalysisSummary(BaseModel):
    question: str
    evidence_ledger: list[EvidenceItem]
    summary: str | None = Field(
        None, description="null when synthesis did not run or was refused. "
        "Null renders as nothing - never an empty prose block")
    summary_truncated: bool
    summary_cited_evidence_ids: list[str]
    documented_findings: list[DocumentedFinding]
    rejected_citations: list[int]
    evidence_removed: list[EvidenceRemoved]
    refusal: str | None
    dropped_sentences: list[DroppedSentence] = Field(
        description="sentences removed from the prose, with why. A sentence "
        "carrying a number no cited span contains is DROPPED, not flagged")
    not_implemented_sections: list[str]
    #: THE FILTER THAT WAS APPLIED. Echoed so a reader can judge an
    #: absence and a report can print the same line: "no gap" and "no
    #: gap among the documents you filtered to" are different findings.
    applied_scope: AppliedScope | None = None


class ClaimClusterOut(BaseModel):
    facet: str = Field(description="human-readable, e.g. 'thickness / um'")
    label: Literal["agreement", "addition", "possible_conflict", "unresolved"] = Field(
        description="possible_conflict, never conflict: documents carry no "
        "revision or approval status, so which supersedes cannot be known")
    rows: list[dict]
    note: str | None


class BaselineSelectionOut(BaseModel):
    kind: Literal["document", "document_section", "stated_requirement"]
    document_id: str | None
    section: str | None
    text: str | None


class GapItemOut(BaseModel):
    facet: str
    status: Literal["met", "possible_gap", "conflict",
                    "insufficient_evidence", "not_applicable"]
    baseline_citation_id: str | None
    baseline_span: str
    project_citation_ids: list[str]
    note: str | None


class GapAnalysisOut(BaseModel):
    applicability: Literal["applicable", "not_applicable",
                           "insufficient_baseline"] = Field(
        description="not_applicable when the caller named no baseline. The "
        "baseline is never chosen by the system: picking one would be an "
        "engineering judgement it has no basis for")
    baseline: BaselineSelectionOut | None
    items: list[GapItemOut]


class AnalysisGaps(BaseModel):
    question: str
    evidence_ledger: list[EvidenceItem]
    claim_clusters: list[ClaimClusterOut]
    gaps: GapAnalysisOut
    not_implemented_sections: list[str]
    #: THE FILTER THAT WAS APPLIED. Echoed so a reader can judge an
    #: absence and a report can print the same line: "no gap" and "no
    #: gap among the documents you filtered to" are different findings.
    applied_scope: AppliedScope | None = None


class ConfidenceCheckOut(BaseModel):
    label: str
    fired: bool = Field(description="true = this check lowered confidence")


class RecommendationOut(BaseModel):
    text: str
    citation_ids: list[str]
    basis: str
    confidence: Literal["low", "medium"] | None = Field(
        None, description='"high" is structurally unreachable, by the same '
        "rule that forbids coverage.complete == true")
    checks: list[ConfidenceCheckOut]


class AnalysisRecommendation(BaseModel):
    question: str
    evidence_ledger: list[EvidenceItem]
    recommendation: RecommendationOut | None = Field(
        None, description="null is not an empty recommendation")
    public_market_findings: list[MarketFinding]
    not_implemented_sections: list[str]
    #: THE FILTER THAT WAS APPLIED. Echoed so a reader can judge an
    #: absence and a report can print the same line: "no gap" and "no
    #: gap among the documents you filtered to" are different findings.
    applied_scope: AppliedScope | None = None


class AnalysisRequest(BaseModel):
    question: str
    limit: int = 8
    baseline_document_id: str | None = Field(
        None, description="the caller's choice of authoritative document. "
        "Never chosen by the system")
    #: OPTIONAL. Absent means today's behaviour, byte for byte. Present, it is
    #: intersected with the caller's own grants BEFORE retrieval, so it can
    #: only ever narrow. An object here rather than repeated query params
    #: because these are POST bodies and an object is the natural shape;
    #: `/api/search` is a GET and uses repeated params instead.
    scope: ClassificationScope | None = None


class MarketFinding(BaseModel):
    """An ILLUSTRATIVE row. There is no provider and this machine is offline."""

    claim: str
    url: str = Field(description="always sample:// - a scheme that resolves nowhere")
    publisher: str
    published_at: str | None
    retrieved_at: str
    verification: Literal["source_not_verified"] = Field(
        description="the only value a sample may carry: nothing here was read"
    )
    is_sample: Literal[True] = Field(
        description="ALWAYS true. Not optional and not defaulted - a row that "
        "could omit it could be mistaken for a real finding"
    )


class EgressState(BaseModel):
    web_search_enabled: bool
    allow_public_egress: bool


class MarketFindings(BaseModel):
    notice: str = Field(description="SAMPLE DATA - NOT LIVE, in full")
    egress: EgressState
    findings: list[MarketFinding]
    is_sample: Literal[True]


class MarketQueryRequest(BaseModel):
    query: str
    country: str | None = None
    freshness_days: int | None = None


class MarketQueryPreview(BaseModel):
    """What WOULD be sent. Nothing is sent."""

    query: str
    country: str | None
    freshness_days: int | None
    would_be_sent_to: None = None
    sent: Literal[False]
    reason: str


class ReportDocumentRow(BaseModel):
    document_id: str
    filename: str = Field(description="as it was named when the report was generated")
    sha256_prefix: str
    revision: str | None = Field(
        None, description="always null: no such column exists on documents. "
        "Rendered as 'not recorded', never invented")
    approval_status: str | None = None
    passages_cited: int
    text_source: Literal["extracted", "recognised", "mixed"] | None


class ReportRecord(BaseModel):
    """A report as a client may see it. `stored_path` is never here."""

    id: str
    question: str | None
    resolved_question: str | None
    created_at: str
    page_count: int
    size_bytes: int
    report_sha256: str = Field(
        description="hash of the PDF bytes. Proves the stored file is the one "
        "issued; NOT a reproducibility hash - a re-render on another build "
        "differs in producer string and ID array with identical content")
    owner_username: str | None = Field(
        None, description="null under auth_mode=disabled: there is no user, "
        "and a placeholder name would be a false attribution")
    documents: list[ReportDocumentRow]
    not_implemented_sections: list[str] = Field(
        description="named on page 1 of the PDF as not included")


class ReportList(BaseModel):
    reports: list[ReportRecord]
    suppressed_count: int = Field(
        description="reports hidden because a cited document left the caller's "
        "scope. THAT something is hidden, never WHAT")


class ReportVerification(BaseModel):
    report_id: str
    snapshot_intact: bool
    file_intact: bool
    evidence_drift: list[str] = Field(
        description="how the cited documents differ NOW from when the report "
        "was generated. Reported, never silently resolved")


class GenerateReport(BaseModel):
    message_id: str


class EvidenceRemoved(BaseModel):
    """A source that did not fit the model's context window.

    Reported rather than discarded quietly. `done_reason == "length"` already
    tells the reader when the OUTPUT ran out of budget; before this field,
    input truncation happened inside llama.cpp with no signal at all - the
    response reported FEWER tokens evaluated than the window holds, so it was
    indistinguishable from a small prompt.
    """

    index: int = Field(description="1-based position in the sources as retrieved")
    filename: str | None = None
    page_start: int | None = None
    action: Literal["trimmed", "dropped"]
    characters_kept: int
    characters_dropped: int


class AnswerResult(BaseModel):
    question: str
    answer_type: AnswerType = Field(
        description="extract is a verbatim quotation; generated is model prose. "
        "The UI must never present one as the other."
    )
    answer: str | None
    reason: str | None = Field(None, description="why there is no answer")
    passage: AnswerPassage | None = None
    answer_passages: list[AnswerPassage] = Field(
        [],
        description="one or two passages that together answer the question; a "
        "second appears only when the first cannot cover the question alone",
    )
    supporting: list[AnswerPassage] = []
    lexical: dict | None = Field(
        None,
        description="which distinctive terms the question carried, which the "
        "passage covered, and which appear nowhere in the corpus",
    )
    passages: list[AnswerPassage] = []
    cited: list[int] = []
    rejected_citations: list[int] = Field(
        [], description="citations the model invented; removed from the answer"
    )
    truncated: bool = Field(
        False, description="the generation stopped because it hit the output-token cap, not because the model finished. The UI MUST say so: an answer that simply stops reads as broken, and the reader cannot otherwise tell whether the model finished, ran out of budget, or crashed. Any half-written citation marker at the end has already been removed."
    )
    input_kind: str | None = Field(
        None, description="why this was answered as guidance rather than searched"
    )
    evidence_removed: list[EvidenceRemoved] = Field(
        [],
        description="sources trimmed or dropped to fit the context window. A "
        "numeric table costs about one token per character against a 1,536 "
        "token window, so three table passages do not fit and the runtime "
        "used to discard them silently",
    )
    coverage: Coverage | None = Field(
        None,
        description="which documents the question was about and which the "
        "answer used. Null for a refusal, deliberately: an incidence table "
        "under a refusal invites the reader to read it as evidence the corpus "
        "could have answered after all",
    )
    examples: list[str] = Field(
        [], description="real questions drawn from the loaded documents"
    )
    retrieval_mode: str
    reranked: bool
    candidates_considered: int
    model: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    seconds: float
    timings: dict[str, float]


MessageRole = Literal["user", "assistant"]


class Message(BaseModel):
    id: str
    conversation_id: str
    ordinal: int
    role: MessageRole
    text: str | None
    resolved_question: str | None = Field(
        None, description="user rows: what retrieval actually ran after follow-up resolution"
    )
    carried_terms: list[str] = Field(
        [], description="terms carried in from earlier questions; shown, never silent"
    )
    answer_type: AnswerType | None = None
    reason: str | None = None
    input_kind: str | None = None
    examples: list[str] = []
    explains_id: str | None = Field(
        None, description="assistant rows: the extract answer this Tier 2 answer explains"
    )
    payload: dict | None = Field(None, description="passages and citations, for replay")
    created_at: str


class Conversation(BaseModel):
    id: str
    title: str
    document_id: str | None
    message_count: int
    created_at: str
    updated_at: str


class ConversationSummary(Conversation):
    first_question: str | None = None


class ConversationList(BaseModel):
    total: int
    limit: int
    offset: int
    conversations: list[ConversationSummary]


class ConversationDetail(BaseModel):
    conversation: Conversation
    messages: list[Message]


class NewConversation(BaseModel):
    model_config = {"extra": "forbid"}
    title: str | None = None
    document_id: str | None = None


class AskRequest(BaseModel):
    model_config = {"extra": "forbid"}
    question: str = Field("", max_length=500)
    tier: Literal["extract", "generated"] = "extract"
    document_id: str | None = None
    limit: int = Field(3, ge=1, le=5)
    explain_of: str | None = Field(
        None,
        description="upgrade this assistant message to Tier 2 instead of asking anew; "
        "question is ignored and the already-resolved question is reused",
    )
    progress_id: str | None = Field(
        None, max_length=64,
        description="a client-chosen id for polling /api/progress/{id} while "
        "this runs. Optional: without one the work reports nothing and "
        "behaves exactly as before",
    )


class AskResult(AnswerResult):
    conversation: Conversation
    user_message: Message
    assistant_message: Message
    resolved_question: str
    carried_terms: list[str] = []


class CorpusMetrics(BaseModel):
    documents: int
    by_status: dict[str, int]
    pages_declared: int = Field(description="from the PDF manifest")
    pages_extracted: int = Field(description="actually extracted; differs while processing")
    chunks_total: int
    chunks_retrievable: int = Field(description="what search can see")
    chunks_excluded: int
    chunks_indexed_keyword: int
    chunks_embedded: int


class StageThroughput(BaseModel):
    unit: str
    samples: int
    median: float
    best: float
    items_total: int
    seconds_total: float


class RetrievalLatency(BaseModel):
    unit: str
    samples: int
    p50: float | None
    p95: float | None
    worst: float


class SystemMetrics(BaseModel):
    cpu_percent_since_last_call: float | None = Field(
        None,
        description="null on the very first reading, which has no prior call "
        "to measure against, and null whenever the window since the previous "
        "call was too short to be an average of anything",
    )
    cpu_window_seconds: float | None = Field(
        None,
        description="the span the percentage actually covers. NOT the refresh "
        "interval: every caller of this endpoint resets the window, so two "
        "open tabs halve it. null whenever the percentage is null.",
    )
    cpu_logical_cores: int | None
    cpu_physical_cores: int | None
    ram_total_bytes: int
    ram_used_bytes: int
    ram_free_bytes: int = Field(
        0,
        description="stated rather than derived. used/total made the reader "
        "subtract, and rounding broke it: 15.4 of 16 renders as 15/16, which "
        "implies 1 GB free while the low-memory alert correctly said 0.6.",
    )
    ram_percent: float
    process_rss_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    disk_percent: float | None
    data_dir_bytes: int


class ModelStatus(BaseModel):
    embed_model: str
    embed_model_present: bool
    reranker_model: str
    reranker_present: bool
    answer_model: str
    answer_model_reachable: bool = Field(description="is Ollama running")
    answer_model_installed: bool = False
    answer_model_loaded: bool = Field(False, description="resident, so no cold load")
    ollama_error: str | None = None


class DocumentFailure(BaseModel):
    id: str
    filename: str
    error_code: str | None
    error_message: str | None
    uploaded_at: str


class JobMetrics(BaseModel):
    by_state: dict[str, int]
    running: int
    failed_documents: int
    failures: list[DocumentFailure]


class MetricWarning(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    document_id: str | None
    message: str


class Metrics(BaseModel):
    """Every field is measured. A value that has not been measured is null,
    and the screen says so - never a zero standing in for unknown."""

    at: str
    refresh_seconds: int
    corpus: CorpusMetrics
    exclusions: list[ExclusionSummary]
    jobs: JobMetrics
    throughput: dict[str, StageThroughput | None] = Field(
        description="null for a stage that has never run measurably"
    )
    retrieval: RetrievalLatency | None = Field(
        None, description="null until a question has actually been asked"
    )
    system: SystemMetrics | None = None
    models: ModelStatus
    worker: WorkerStatus
    warnings: list[MetricWarning]


class KeywordIndexResult(BaseModel):
    document_id: str
    indexed: int
    seconds: float
    chunks_per_sec: float | None


class DeletedDocument(BaseModel):
    """What was removed when a DOCUMENT was deleted."""

    deleted: str
    filename: str
    rows_removed: dict[str, int]
    files_removed: int


class DeletedConversation(BaseModel):
    """What was removed when a CONVERSATION was deleted.

    A SEPARATE MODEL, and that is the fix. Both routes shared one
    `DeleteResult` whose `filename` field was REQUIRED, so the conversation
    route satisfied it by putting the conversation's TITLE under that key - and
    a client reading the response built a wrong model of what it had deleted.
    The mistake was invisible because a title looks exactly as plausible under
    `filename` as a filename does, and the response_model VALIDATED it, which
    made the wrong shape look deliberate.

    A conversation deletes no files, so the count is not carried at all rather
    than reported as a truthful-looking zero.
    """

    deleted: str
    title: str
    rows_removed: dict[str, int]


#: Reusable error documentation for the OpenAPI schema.
ERRORS_404 = {404: {"model": ErrorEnvelope, "description": "Unknown document id"}}
ERRORS_422 = {
    422: {
        "model": ErrorEnvelope,
        "description": "Invalid or unknown query parameter",
    }
}
ERRORS_400 = {400: {"model": ApiError, "description": "Rejected request"}}
ERRORS_401 = {401: {"model": ErrorEnvelope, "description": "Not signed in"}}
ERRORS_429 = {429: {"model": ErrorEnvelope, "description": "Too many attempts"}}
