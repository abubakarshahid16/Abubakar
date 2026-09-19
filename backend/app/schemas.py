"""Typed response models.

Every 200 was documented as `string` and every error as "Undocumented", which
means the frontend types were guesses. The UI is generated against this
contract, so an untyped contract is a UI that cannot be trusted to match the
API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocStatus = Literal[
    "queued",
    "extracting",
    "chunking",
    "indexing_keyword",
    "partially_searchable",
    "ready",
    "no_searchable_content",
    #: A workbook: stored and previewable, deliberately never indexed. See
    #: `states.STORED_NOT_INDEXED` for why this is its own state rather than a
    #: document that failed to extract.
    "stored_not_indexed",
    "failed",
]

ChunkKind = Literal["prose", "table", "toc", "frontmatter", "index", "references"]

#: What part a document plays in a submittal review.
#:
#: THIS IS THE ENFORCEMENT POINT for the five legal roles. The column is plain
#: TEXT with no CHECK constraint, deliberately - this schema carries exactly
#: one CHECK (roles.kind), and SQLite cannot ALTER-ADD a CHECK, so a second one
#: would force a table rebuild at the next column migration. Validating here
#: instead means a bad value is refused at the API boundary with a message
#: naming the field, rather than raising sqlite3.IntegrityError from inside a
#: write. A value that never crosses this boundary is not validated by it, so
#: any writer that bypasses the API must state its own vocabulary check.
#:
#: NOT ACCESS CONTROL (CLAUDE.md rule 5). A role says what a document is for;
#: the grant tables say who may read it.
DocumentRole = Literal[
    "CONTRACTOR_SUBMITTAL",
    "COMPANY_STANDARD",
    "CONTRACT_DOCUMENT",
    "SUPPORTING_DOCUMENT",
    "CRS_TEMPLATE",
]

#: Where a DOCUMENT stands in the review workflow.
#:
#: MASTER-PLAN SECTION 6 METADATA MAPPING, RESOLVED: "review status" is
#: **derived, never stored**. There is no `review_status` column and there must
#: not be one. The authority is `review_runs.status` for the latest run over
#: that submittal, and a document with no run is `not_reviewed`. A column here
#: would be a second home for a claim `review_runs` already owns, which is
#: CLAUDE.md rule 8 - "fix a claim in every home it lives in" - broken at
#: design time rather than discovered later.
#:
#: `not_reviewed` is a real answer and NOT null: the question "has this been
#: reviewed" has a definite answer for every document, and it is "no".
#: The remaining values mirror `review_runs.status` exactly, so the two cannot
#: drift into two vocabularies.
#: Named apart from the guided-review finding status on purpose - that one is
#: where a single FINDING stands (`open`, `resolved`...). Two different
#: questions about two different things; one name for both is how a finding's
#: state ends up rendered on a document card. `contracts/types.ts` carries the
#: same distinction.
DocumentReviewStatus = Literal[
    "not_reviewed",
    "pending",
    "running",
    "completed",
    "failed",
]

#: Whether a submittal meets one requirement. A SECOND vocabulary beside the
#: guided-review `status`/`disposition`, never a replacement for them.
#:
#: The six are not collapsible to a boolean, and that is the point:
#:   * MISSING_INFORMATION is NOT NON_COMPLIANT - "the submittal does not say"
#:     is not "the submittal is wrong", and the honesty invariant that "not
#:     mentioned is never compliant" has an equal and opposite half.
#:   * CONDITIONAL carries a verdict that holds only if something else is true.
#:   * NOT_APPLICABLE means the requirement does not govern this submittal.
#:   * NEEDS_ENGINEER_REVIEW is the machine declining to answer, which is a
#:     result and must be storable as one rather than rounded to a guess.
#: NULL (no value at all) is distinct from every one of these: it means no
#: verdict was ever recorded, which is what every pre-existing finding row is.
ComplianceStatus = Literal[
    "COMPLIANT",
    "NON_COMPLIANT",
    "MISSING_INFORMATION",
    "CONDITIONAL",
    "NOT_APPLICABLE",
    "NEEDS_ENGINEER_REVIEW",
]


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
    disciplines: list[str] = Field(
        description="The disciplines this document is granted to - its category "
        "as the access model defines it. Empty means no discipline holds it and "
        "only an administrator can read it. Read from the grant tables, never "
        "inferred from the filename or the content."
    )
    # ----------------------------------------- AI submittal review, phase 2
    # The Documents page columns. Every one is null on every document
    # classified before this workflow existed, and null renders as nothing.
    document_role: DocumentRole | None = None
    document_number: str | None = None
    title: str | None = Field(
        None, description="the human title. Null means none recorded; the UI "
                          "falls back to the filename rather than inventing one")
    revision: str | None = None
    equipment_type: str | None = None
    project: str | None = None
    superseded_by: str | None = Field(
        None, description="the document id that replaced this one. Null means "
                          "this document is current")
    #: DERIVED from the latest review_runs row, never stored. `not_reviewed` is
    #: a real answer, not a null - see `ReviewStatus`.
    review_status: DocumentReviewStatus = "not_reviewed"


class StandardClause(BaseModel):
    """One clause of a standard, resolving to the chunk it was read from."""

    clause: str
    parent_clause: str | None = Field(
        None, description="null for a top-level clause - a real answer, not a "
                          "missing one: it is the root of the hierarchy")
    depth: int
    title: str | None = None
    page: int
    chunk_id: str = Field(
        description="the chunk this clause was read from, so it resolves to a "
                    "passage a reader can open")


class StandardRequirement(BaseModel):
    """One atomic requirement, with its resolving citation.

    Phase 3A carries no requirement_type, operator, value, unit, condition or
    exceptions. Those are 3B, and half a numeric limit is worse than none: a
    row carrying `value: 90` with no operator reads as a limit and is not one.
    """

    id: str
    standard_document_id: str
    clause: str | None = Field(
        None, description="NULL when the parser could not identify one. Never "
                          "guessed and never inherited from the preceding "
                          "clause - an inherited number is a citation that "
                          "resolves to the wrong place")
    page: int | None
    chunk_id: str | None
    requirement_text: str
    source_text: str | None = Field(
        None, description="the verbatim span. Separate from requirement_text "
                          "because 3B will normalise one and must not lose the "
                          "other")
    category: str | None = None
    extraction_method: str | None = Field(
        None, description="'extracted' until a human confirms it: a guess "
                          "stays labelled a guess")
    confidence: float | None = Field(
        None, description="A HEURISTIC, not a probability. Its only job is to "
                          "decide whether a row is presented as a requirement "
                          "or as one awaiting verification")
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    needs_verification: bool = Field(
        description="true while a human has not confirmed a row this extractor "
                    "is unsure of")
    # ------------------------------------------------------------ phase 3B
    requirement_type: RequirementType | None = None
    field: str | None = Field(
        None, description="what is being limited. From a table this is the "
                          "column header the document wrote; from a sentence "
                          "it is null rather than guessed")
    operator: str | None = None
    value: float | None = Field(
        None, description="the NORMALISED number, or null. NULL WHEN THE UNIT "
                          "IS UNKNOWN - never 0, which would read as a limit "
                          "of zero, a real and very different requirement")
    unit: str | None = Field(
        None, description="the canonical unit, or null when the spelling is "
                          "not in claims.py's table")
    raw_value: str | None = Field(
        None, description="exactly as the document wrote it. Preserved so an "
                          "un-normalisable value is still quotable")
    raw_unit: str | None = None
    condition: str | None = Field(
        None, description="the circumstance the requirement holds under. A "
                          "wrong condition NARROWS a requirement and silently "
                          "excuses a real deviation, so it is parsed "
                          "conservatively and is null when unclear")
    exceptions: list[dict] = Field(
        default_factory=list,
        description="carve-outs with their own limits. An exception that is "
                    "dropped turns a compliant PSV into a false finding")
    discipline: str | None = None
    table_row: int | None = None
    citation_resolves: bool = Field(
        description="false when the cited chunk is gone - re-extract. Shown "
                    "rather than the row being silently dropped")
    created_at: str
    updated_at: str


#: What kind of thing a requirement states. Phase 3B.
#:
#: NOTHING IS INVENTED FOR TEXT THE PARSER DID NOT UNDERSTAND. An obligation
#: with no recognisable limit is a `statement`, which is a true description of
#: it - not a `numeric_limit` carrying a null value, a shape that reads as a
#: limit nobody bothered to record.
RequirementType = Literal["numeric_limit", "statement", "table_value"]

#: An engineer's decision on an extracted requirement.
RequirementDecision = Literal["confirm", "edit", "reject"]


class TableParseResult(BaseModel):
    """One table chunk, parsed or explicitly not."""

    chunk_id: str
    document_id: str
    page: int
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    parsed: bool
    unparsed_reason: str | None = Field(
        None, description="why this table could not be read. A table that "
                          "could not be parsed is a FACT to report, never an "
                          "absence to skip over")


class TableReport(BaseModel):
    document_id: str
    tables: list[TableParseResult] = Field(default_factory=list)
    tables_total: int
    tables_parsed: int
    tables_unparsed: int
    parsed_fraction: float | None = Field(
        None, description="NONE when the standard has no tables at all, which "
                          "is not 0% and must not render as a failure. A rate "
                          "is never published without its denominator")


class RequirementDecisionRequest(BaseModel):
    decision: RequirementDecision
    edits: dict | None = Field(
        None, description="field -> new value, for `edit`. A correction sets "
                          "extraction_method to 'human': after it the row is a "
                          "person's statement, not a machine's guess")


class ExtractionJob(BaseModel):
    """A queued or finished background extraction.

    Typed rather than a bare dict because `test_every_endpoint_declares_a_
    typed_success_response` forbids an untyped success body - and it is right
    to: an `additionalProperties: true` response is a contract that promises
    nothing, and the client generator has nothing to generate.
    """

    document_id: str | None = None
    job_id: str | None = None
    state: str = Field(
        description="'none' when no extraction has ever been queued for this "
                    "standard - a real answer, not a missing one")
    error_code: str | None = None
    started_at: str | None = None
    updated_at: str | None = None


class RequirementDecisionResult(BaseModel):
    """What an engineer's decision did.

    `deleted` is true only for a reject, where the row is gone and the audit
    row is what survives.
    """

    id: str
    decision: RequirementDecision
    deleted: bool = False
    extraction_method: str | None = Field(
        None, description="'human' after any confirm or edit: the row is a "
                          "person's statement, not a machine's guess")
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    requirement_text: str | None = None
    clause: str | None = None
    field: str | None = None
    operator: str | None = None
    value: float | None = None
    unit: str | None = None


class RequirementConflict(BaseModel):
    """Two standards limiting the same field differently.

    SURFACED, NEVER RESOLVED. Picking one silently would hide exactly the thing
    an engineer needs to decide, and seniority between two company standards is
    not something this system can know.
    """

    field: str
    requirements: list[dict]


class StandardSummary(BaseModel):
    """One row of the Standards Library list."""

    id: str
    filename: str
    status: DocStatus
    page_count: int | None
    uploaded_at: str
    title: str | None = None
    document_number: str | None = None
    revision: str | None = None
    effective_date: str | None = None
    #: WHAT THE STANDARD'S OWN COVER PAGE SAYS. Evidence, never rewritten.
    discipline: str | None = None
    #: The editorial answer to "are these two the same discipline", derived
    #: from `discipline` and stored beside it. A screen shows this one and
    #: keeps the raw spelling in a tooltip when the two differ - an unmapped
    #: value is simply equal to the raw one, so there is nothing to show.
    discipline_canonical: str | None = None
    superseded_by: str | None = None
    superseded: bool = Field(
        description="excluded from SELECTION for new reviews, and still fully "
                    "readable and citable. Two different questions")
    requirement_count: int = Field(
        description="0 is a real answer meaning NONE EXTRACTED. It never means "
                    "'none required' and never renders as readiness")
    awaiting_verification: int


class StandardExtraction(BaseModel):
    """What one extraction run did. Counts, with their boundary stated."""

    document_id: str
    chunks_read: int
    requirements: int
    awaiting_verification: int


class SupersedeRequest(BaseModel):
    superseded_by: str | None = Field(
        None, description="the document id that replaces this one, or null to "
                          "clear the mark")


class WorkbookSheet(BaseModel):
    """One sheet of a read-only workbook preview."""

    name: str
    rows: list[list[str]] = Field(
        default_factory=list,
        description="POPULATED ROWS ONLY, row-major. Ragged rows are normal - "
                    "a sheet is not a rectangle. An empty cell is an empty "
                    "string and renders as nothing, never as 0")
    truncated: bool = Field(
        False,
        description="the preview stopped short of the sheet's full extent. "
                    "Stated rather than applied silently: a preview that "
                    "quietly stops at row 500 lies about what the file holds")


class WorkbookPreview(BaseModel):
    sheets: list[WorkbookSheet] = Field(default_factory=list)
    truncated: bool = False


class DocumentPage(BaseModel):
    """A bounded document listing; authorization and filtering happen before paging."""
    items: list[Document]
    total_matching: int
    limit: int
    offset: int


class UploadAccepted(BaseModel):
    document: Document | None = Field(
        None,
        description="ABSENT when the bytes duplicate a document this caller "
                    "may not read (#79). Not an error and not an empty "
                    "record: the response says nothing about a document "
                    "outside the caller's scope, the same answer every read "
                    "path gives. Present in every other case.",
    )
    job_id: str = Field(description="empty when the upload was a duplicate")
    duplicate_of: str | None = Field(
        None,
        description="The document these bytes already match, and null when "
                    "the caller may not read it - the id is derived from the "
                    "content hash, so stating it would confirm the content "
                    "as well as the existence.",
    )
    awaiting_grant: bool = Field(
        False,
        description="The upload was accepted and there is nothing for this "
                    "caller to see until an administrator grants it. About "
                    "the CALLER's request, never about the corpus: it does "
                    "not distinguish a duplicate from anything else, so it "
                    "is not an existence oracle.",
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
    # --------------------------------------------- AI submittal review, phase 1
    # Every one of these is null on every document classified before this
    # workflow existed, and null renders as nothing - never as a default role,
    # never as 0, never as "unknown" dressed up as a value.
    document_role: DocumentRole | None = None
    document_number: str | None = None
    title: str | None = Field(
        None, description="the human title, which is NOT the filename. Null "
                          "means none recorded and the UI falls back to the "
                          "filename rather than inventing one")
    revision: str | None = None
    effective_date: str | None = None
    project: str | None = None
    contractor_vendor: str | None = None
    equipment_type: str | None = None
    equipment_tags: list[str] = Field(
        default_factory=list,
        description="flat tag list; stored as a JSON array in one TEXT column "
                    "because nothing joins on it. An empty list means none "
                    "recorded")
    service: str | None = None
    transmittal_number: str | None = None
    superseded_by: str | None = Field(
        None, description="the document id that replaced this one, or null. "
                          "Not a foreign key: deleting the superseding "
                          "document must not erase the fact of supersession")


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
    # ----------------------------------------- AI submittal review, phase 2
    # THE ENFORCEMENT POINT for the role vocabulary on the way IN. The column
    # is plain TEXT with no CHECK (see `DocumentRole`), so this annotation is
    # the only thing standing between a typo and a document that no filter
    # will ever match. `DocumentRole` and not `str`: widening this field is
    # mutation M12, and the test that catches it is
    # test_an_invalid_role_is_rejected.
    #
    # Every field is optional and None means "clear it". That is deliberate
    # and is why the route sends the whole record: a PUT replaces the
    # classification, the same way `subject_ids` already replaces the subject
    # set, so an administrator removing a value can actually remove it.
    document_role: DocumentRole | None = None
    document_number: str | None = None
    title: str | None = None
    revision: str | None = None
    effective_date: str | None = None
    project: str | None = None
    contractor_vendor: str | None = None
    equipment_type: str | None = None
    equipment_tags: list[str] = Field(default_factory=list)
    service: str | None = None
    transmittal_number: str | None = None
    superseded_by: str | None = None


class PairChoice(BaseModel):
    """The model's answer when asked which candidate a clause governs.

    THE MODEL CHOOSES; IT NEVER NAMES. `choice` is an INDEX into a list Python
    built, so the model cannot invent a field that was not offered - the worst
    failure available to it is picking the wrong number, which the validation
    chain then checks against the list it was given.

    `extra="forbid"` because a model asked for JSON will happily return extra
    keys, and a response carrying a `field_name` or a `value` it was never
    shown is a response that did not follow the contract. Refusing it is
    `model_malformed`, and the requirement falls back to MISSING_INFORMATION.
    """

    model_config = ConfigDict(extra="forbid")

    #: The candidate index, or None for "none of these". Null is offered
    #: explicitly in the prompt so declining is a sanctioned answer rather than
    #: something the model has to invent a way to say.
    choice: int | None = None
    #: One short sentence. Bounded because it is stored on the finding and
    #: shown to an engineer, and an unbounded field lets a model write an essay
    #: into a column meant for a reason.
    reason: str = Field(default="", max_length=200)


class BulkRoleUpdate(BaseModel):
    """Set ONE role on MANY documents.

    ONE ROLE, NOT A MAP. A per-document role would let a single request mix
    standards and submittals, and the confirmation the UI can show for that is
    "40 documents updated" - which tells a reviewer nothing about what they
    just asserted. One role per request means the sentence on screen is
    "40 documents set to COMPANY_STANDARD", and that is a claim somebody can
    actually check.

    THE VOCABULARY IS ENFORCED HERE, same as `ClassificationUpdate`, and for
    the same reason: the column is plain TEXT with no CHECK, so this annotation
    is what stands between a typo and documents no filter will ever match.
    `document_role` is NOT optional on this model - an omitted role on a bulk
    write would mean "clear the role on all forty", which no caller should be
    able to ask for by leaving a field out.
    """

    document_ids: list[str] = Field(
        min_length=1,
        description="the documents to set the role on. An empty list is "
                    "refused rather than treated as a no-op: it almost always "
                    "means the UI lost its selection, and answering 200/'0 "
                    "updated' to that looks like success",
    )
    document_role: DocumentRole


class BulkRoleFailure(BaseModel):
    """One document the bulk write did NOT touch, and why."""

    document_id: str
    reason: Literal["not_found"] = Field(
        description="`not_found` covers both an id that does not exist and one "
                    "outside the caller's scope - deliberately the SAME answer, "
                    "because a distinct 'forbidden' here would turn this "
                    "endpoint into an existence oracle for documents the caller "
                    "may not read, which is the leak every single-document read "
                    "path already refuses"
    )


class BulkRoleResult(BaseModel):
    """What the bulk write actually did.

    IT REPORTS FAILURES BY ID, NOT AS A COUNT. A bulk endpoint that returns
    "37 updated" for a request naming 40 documents has told the caller that
    something went wrong and made it impossible to find out what - and the UI's
    only honest options are then to say nothing or to re-fetch everything and
    diff. Every id that did not get the role is named here, so the screen can
    say which ones and the person can act on it.
    """

    document_role: DocumentRole
    requested: int = Field(description="ids in the request, after duplicates "
                                       "were collapsed")
    updated: list[str] = Field(
        description="documents whose role this request CHANGED")
    unchanged: list[str] = Field(
        description="documents that already held this exact role. Not a "
                    "failure and not an update - re-applying the same value is "
                    "a no-op, and counting it as a change would inflate every "
                    "confirmation message"
    )
    failed: list[BulkRoleFailure] = Field(
        description="documents that were NOT written, each with a reason. "
                    "Empty on a fully successful request")


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
    "metadata",
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


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=12, max_length=1024)


class PasswordResetResult(BaseModel):
    reset: Literal[True] = True


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


class TokenRevocationResult(BaseModel):
    user_id: str
    revoked: bool


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
    recommendation_refusal: str | None = Field(
        None, description="reason the advisory recommendation was not produced")
    public_market_findings: list[MarketFinding]
    not_implemented_sections: list[str]
    #: THE FILTER THAT WAS APPLIED. Echoed so a reader can judge an
    #: absence and a report can print the same line: "no gap" and "no
    #: gap among the documents you filtered to" are different findings.
    applied_scope: AppliedScope | None = None


class AnalysisRequest(BaseModel):
    question: str
    limit: int = 8
    comparison_type: Literal[
        "baseline_vs_submittal", "requirements_vs_submittal",
        "revision_delta", "discipline_coordination"
    ] | None = Field(None, description="named engineering comparison workflow")
    document_id: str | None = Field(
        None, description="engineering submittal document used for automatic baseline selection")
    baseline_document_id: str | None = Field(
        None, description="optional manual authoritative-document override; takes precedence")
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


# ------------------------------------------- live public-market intelligence
#
# These describe the two routes the market panel is built against. They are
# declared for the reason tests/test_no_internal_leaks.py exists: an untyped
# 200 documents itself as `string`, so every frontend type written against it
# is a guess. Wiring these routes without response models left that test red,
# which is the codebase correctly refusing an undeclared body.
#
# A response_model also FILTERS. `market_providers.search_all` returns an
# `audit` list for the persistence call site, and `to_api` strips it - but a
# declared model means that even if `to_api` were bypassed, the audit rows
# could not reach a browser. Two independent guards on the same leak, which is
# the right number for the one field here that must never be served.


class MarketOutboundPayload(BaseModel):
    """THE OBJECT THAT WOULD LEAVE, for one tier.

    A CLOSED shape, and the closure is the point: everything here is sent, so a
    field added to this model is a field added to what leaves this machine.
    There is deliberately nothing that could carry a passage - no `context`,
    no `evidence`, no `surrounding_text`. See
    tests/test_market_no_document_leak.py, which asserts the field NAMES as
    well as the values.
    """

    phrase: str = Field(description="the scrubbed phrase, and the ONLY free "
                                    "text that leaves this machine")
    tier: str
    provider_label: str
    country: str | None
    freshness_days: int | None


class MarketPreviewPayload(BaseModel):
    """One tier's payload, named so the reader knows which tier it belongs to."""

    tier: str
    provider_label: str
    payload: MarketOutboundPayload


class MarketPreview(BaseModel):
    """What WOULD be sent, per tier. This route performs NO egress.

    `payloads` IS A LIST, one entry per CONFIGURED tier, in attempt order. A
    single payload could not be honest: a search builds one per tier, so
    showing one meant the user approved an object that was never sent while up
    to three others were - the defect this shape was rewritten to close.

    `phrase` null means nothing safe survived and NO SEARCH IS POSSIBLE. Not
    "send the raw text instead": a caller that falls back to the typed string
    has broken the only guarantee that matters.
    """

    phrase: str | None
    payloads: list[MarketPreviewPayload]
    tiers_configured: list[str] = Field(
        description="tiers this build could attempt, in order. Empty is real")
    tiers_unconfigured: list[str] = Field(
        description="tiers that cannot run here. Reported SEPARATELY from "
                    "attempted, because nothing is ever sent to them")
    tier_labels: dict[str, str] = Field(
        description="tier id -> label. Sent so a caller never needs its own "
                    "copy of this mapping, which would drift")


class MarketRow(BaseModel):
    """One public finding, or one labelled sample.

    `published` is nullable and a null must render as NOTHING - not a dash, not
    "N/A", and never today's date, which would date an undated page.
    `retrieved` is when this machine fetched it and is always present.
    """

    text: str
    provider_label: str = Field(
        description="which tier produced this row, in its own words - or "
                    "'sample - illustrative only' for a fixture, which no "
                    "tier produced")
    publisher: str
    published: str | None
    retrieved: str = Field(description="ISO-8601 UTC")
    url: str
    verification: str
    is_sample: bool


class MarketSearchRequest(BaseModel):
    phrase: str
    country: str | None = None
    freshness_days: int | None = None


class MarketSearchResult(BaseModel):
    """The outcome of a search. FOUR states, and they mean different things.

      * `enabled` false with a `phrase`: the feature is off and `rows` are the
        labelled samples.
      * `enabled` true with `phrase` null: nothing safe survived the scrub, so
        no search was attempted. NOT a failure - the same state the preview
        reports, so both screens can use one form of words.
      * `failure` non-null: tiers were attempted and EVERY ONE failed. `rows`
        is empty and samples are never substituted - a fixture served after a
        failed live search is the one behaviour that turns this feature into a
        liability.
      * otherwise `rows` are real, and an empty `rows` is a real answer.

    `tiers_attempted` against `tiers_answered` is what makes a dropped tier
    visible. Unconfigured tiers are in neither: nothing was sent to them.
    """

    enabled: bool
    phrase: str | None
    rows: list[MarketRow]
    tiers_attempted: list[str] = Field(
        description="tiers actually CONTACTED. Never includes an unconfigured "
                    "tier, so 'tried and did not answer' stays true")
    tiers_answered: list[str]
    tiers_unconfigured: list[str]
    tier_labels: dict[str, str]
    failure: str | None = Field(
        None, description="set ONLY when every attempted tier failed")


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
    total_matching: int = 0
    limit: int = 20
    offset: int = 0


# ------------------------------------------------------- engineering reviews

class ReviewTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=4000)
    discipline: str | None = Field(default=None, max_length=100)
    deliverable_type: str | None = Field(default=None, max_length=100)
    governing_sources: list[str] = Field(default_factory=list, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=30)
    severity_levels: list[str] = Field(default_factory=list, max_length=10)
    approval_terms: list[str] = Field(default_factory=list, max_length=30)
    required_sections: list[str] = Field(default_factory=list, max_length=50)
    active: bool = True


class ReviewTemplate(BaseModel):
    id: str
    name: str
    version: str
    description: str
    discipline: str | None
    deliverable_type: str | None
    governing_sources: list[str]
    categories: list[str]
    severity_levels: list[str]
    approval_terms: list[str]
    required_sections: list[str]
    active: bool
    created_by: str | None
    created_at: str
    updated_at: str


class ReviewTemplateList(BaseModel):
    templates: list[ReviewTemplate]


class ReviewBaselineRuleCreate(BaseModel):
    submittal_doc_type: str | None = None
    submittal_discipline: str | None = None
    baseline_doc_type: str
    baseline_discipline: str | None = None
    priority: int = 0
    active: bool = True


class ReviewBaselineRule(BaseModel):
    id: str
    submittal_doc_type: str | None
    submittal_discipline: str | None
    baseline_doc_type: str
    baseline_discipline: str | None
    priority: int
    active: bool
    created_at: str


class ReviewBaselineRuleList(BaseModel):
    rules: list[ReviewBaselineRule]


class ReviewBaselineSelection(BaseModel):
    document_id: str
    rule_id: str | None
    automatic: bool


class ExpectedDeliverable(BaseModel):
    id: str
    wbs_code: str
    deliverable_type: str
    title: str
    required: bool
    deliverable_id: str | None
    status: str | None
    state: Literal["registered", "missing"]
    origin: Literal["manual", "inferred"]


class ExpectedDeliverableList(BaseModel):
    deliverables: list[ExpectedDeliverable]


RiskType = Literal["schedule", "review", "dependency", "compliance"]


class RiskCreate(BaseModel):
    risk_type: RiskType
    title: str
    description: str
    severity: str = "medium"
    status: str = "open"
    deliverable_id: str | None = None
    document_id: str | None = None
    owner_user_id: str | None = None
    due_date: str | None = None
    source_finding_id: str | None = None


class Risk(BaseModel):
    id: str
    risk_type: RiskType
    title: str
    description: str
    severity: str
    status: str
    deliverable_id: str | None
    document_id: str | None
    owner_user_id: str | None
    due_date: str | None
    source_finding_id: str | None
    created_at: str
    updated_at: str


class RiskList(BaseModel):
    risks: list[Risk]


class StructuredSearchResult(BaseModel):
    id: str
    kind: Literal["deliverable", "finding", "risk", "stakeholder"]
    label: str
    wbs_code: str | None
    document_id: str | None


class StructuredSearchList(BaseModel):
    results: list[StructuredSearchResult]


class ReviewTraceability(BaseModel):
    finding: ReviewFinding
    document: dict
    baseline: dict | None
    citations: list[str]
    events: list[ReviewFindingEvent]
    deliverables: list[Deliverable]
    owner: dict | None
    action: str


class ReviewReportRequest(BaseModel):
    document_id: str

ReviewCategory = Literal[
    "missing_information", "inconsistency", "requirement_deviation",
    "document_control", "technical_query", "positive_observation",
]
ReviewSeverity = Literal["critical", "major", "minor", "observation"]
ReviewStatus = Literal["open", "in_progress", "awaiting_response", "resolved", "deferred"]
ApprovalStatus = Literal["pending", "accepted", "rejected", "not_required"]
ReviewDisposition = Literal["accepted", "partially_accepted", "rejected", "not_applicable"]


class ReviewFindingCreate(BaseModel):
    document_id: str
    baseline_document_id: str | None = None
    template_id: str | None = None
    discipline: str | None = Field(default=None, max_length=100)
    confidence: Literal["low", "medium"] | None = None
    category: ReviewCategory
    severity: ReviewSeverity
    requirement: str = Field(min_length=1, max_length=4000)
    finding: str = Field(min_length=1, max_length=8000)
    required_action: str = Field(min_length=1, max_length=8000)
    governing_sources: list[str] = Field(default_factory=list, max_length=100)
    unresolved_evidence: list[str] = Field(default_factory=list, max_length=50)
    response_text: str | None = Field(default=None, max_length=8000)
    disposition: ReviewDisposition | None = None
    citation_ids: list[str] = Field(default_factory=list, max_length=50)
    owner_user_id: str | None = None
    due_date: str | None = None
    status: ReviewStatus = "open"
    approval_status: ApprovalStatus = "pending"
    escalation_level: int = Field(default=0, ge=0, le=5)


class ReviewFindingUpdate(BaseModel):
    owner_user_id: str | None = None
    due_date: str | None = None
    severity: ReviewSeverity | None = None
    required_action: str | None = Field(default=None, min_length=1, max_length=8000)
    status: ReviewStatus | None = None
    approval_status: ApprovalStatus | None = None
    escalation_level: int | None = Field(default=None, ge=0, le=5)
    response_text: str | None = Field(default=None, max_length=8000)
    disposition: ReviewDisposition | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    #: CONFIRM THE PAIRING. A flag, not a name: `confirmed_by` is the CALLER,
    #: taken from the authenticated scope and never from this body, because a
    #: confirmation that can name someone else is not a confirmation. There is
    #: no way to un-confirm through this route - a wrong pairing is REJECTED,
    #: which is a different act with a different record.
    confirmed: bool | None = None


class ReviewFinding(BaseModel):
    id: str
    document_id: str
    baseline_document_id: str | None
    template_id: str | None
    discipline: str | None
    confidence: Literal["low", "medium"] | None
    category: ReviewCategory
    severity: ReviewSeverity
    requirement: str
    finding: str
    required_action: str
    governing_sources: list[str]
    unresolved_evidence: list[str]
    response_text: str | None
    disposition: ReviewDisposition | None
    citation_ids: list[str]
    owner_user_id: str | None
    due_date: str | None
    status: ReviewStatus
    approval_status: ApprovalStatus
    approved_by: str | None
    approved_at: str | None
    escalation_level: int
    created_by: str | None
    created_at: str
    updated_at: str
    # ------------------------------------- AI submittal review, phases 5A/5B
    #
    # THE COMPLIANCE SHAPE, ADDED AND NOTHING REMOVED. This model was the
    # phase-1 approval-workflow view of a finding, and the columns phase 5B
    # writes were invisible through it: a run produced 1,580 findings, the API
    # returned them, and a caller could not tell which run they belonged to,
    # what the engine decided, or which submitted value was matched.
    #
    # Every one is OPTIONAL and defaults to None, because a finding raised by
    # hand through `POST /api/reviews/findings` has none of them and is still
    # a finding.
    review_run_id: str | None = None
    compliance_status: ComplianceStatus | None = None
    #: WHICH REQUIREMENT AND WHICH SUBMITTED VALUE. A finding says a
    #: contractor's number does or does not meet a clause; if the pairing was
    #: wrong the finding is wrong, so the reader gets the pairing.
    requirement_id: str | None = None
    fact_id: str | None = None
    #: The field name found inside the requirement's subject, and the rule that
    #: found it. `containment` is the only method today; it is recorded so a
    #: second one cannot be added without the finding saying which ran.
    matched_phrase: str | None = None
    match_method: str | None = None
    #: Why the engine decided what it did, kept SEPARATE from `finding` so a
    #: reader can see the reasoning without it being presented as the
    #: contractor-facing text.
    ai_rationale: str | None = None
    #: WHICH EQUIPMENT THE FINDING IS ABOUT, verbatim from the datasheet's
    #: own tag row. None where the sheet does not say - a datasheet covering
    #: four valves has pages that name none, and a null is the true answer.
    equipment_tag: str | None = None
    #: THE CITATIONS, WHICH ARE THE FINDING'S EVIDENCE. §12 refuses a finding
    #: unless both resolve, so a response that withheld them left the screen
    #: showing a verdict with no way to check it - the Review page rendered an
    #: empty Standard / clause column until these were added.
    standard_document_id: str | None = None
    standard_clause: str | None = None
    standard_page: int | None = None
    requirement_source_text: str | None = None
    contractor_page: int | None = None
    contractor_section: str | None = None
    contractor_evidence_text: str | None = None
    #: WHO STOOD BEHIND THE PAIRING. A model-paired finding is a guess until an
    #: engineer says otherwise, and a confirmed finding is never deleted by a
    #: re-run. Both are visible here so a reader can tell a confirmed pairing
    #: from an unexamined one.
    confirmed_by: str | None = None
    confirmed_at: str | None = None


class PairRejectionCreate(BaseModel):
    """An engineer says a finding's requirement is not about that field."""

    model_config = ConfigDict(extra="forbid")
    finding_id: str
    reason: str = Field(default="", max_length=500)


class PairRejection(BaseModel):
    """What was recorded. The KEYS, not the row ids, decide whether it applies."""

    requirement_key: str
    fact_key: str
    requirement_id: str | None = None
    fact_id: str | None = None
    rejected_by: str | None = None
    rejected_at: str
    reason: str | None = None


class ReviewRunStandard(BaseModel):
    """One standard on a run's list, with the reason it is there.

    THE REASON IS VERBATIM. `applicability.select` writes a sentence saying
    what put the standard on the list - a citation in the submittal, or dense
    retrieval that "is NOT a citation and not evidence of applicability on its
    own" - and the screen shows that sentence rather than a word of its own.
    """

    standard_document_id: str
    filename: str | None = None
    selection_method: str | None = None
    selection_reason: str | None = None
    confidence: float | None = None
    included: bool = True
    exclusion_reason: str | None = None


class ReviewRunStandardList(BaseModel):
    standards: list[ReviewRunStandard]


class ReviewRunSummary(BaseModel):
    """A review run as the runs list shows it.

    EVERY COUNT CARRIES ITS DENOMINATOR (CLAUDE.md rule 4). `by_status` is a
    map of status to count and `findings_total` is what they are out of, so no
    screen has to invent the total by summing and no reader sees a bare number.
    """

    review_run_id: str
    submittal_document_id: str
    submittal_filename: str | None = None
    #: Every distinct equipment tag the run's findings name, in order. Empty
    #: when the datasheet states none - which renders as nothing, never as a
    #: guess at what the equipment might be.
    equipment_tags: list[str] = []
    status: str
    created_at: str | None = None
    completed_at: str | None = None
    standards_in_scope: int = 0
    findings_total: int = 0
    by_status: dict[str, int] = {}
    recommended_code: str | None = None
    #: The recommendation's own words. Never re-worded by a screen.
    recommended_reason: str | None = None
    #: Why a failed run failed, verbatim. None on a run that did not fail.
    failure_reason: str | None = None
    #: THE ENGINEER'S DECISION, BESIDE THE MACHINE'S AND NEVER INSTEAD OF IT.
    #: Section 15: the AI recommends and the engineer decides; both are stored
    #: so a reader can see what was recommended and what was signed.
    engineer_final_code: str | None = None
    override_reason: str | None = None
    #: The user id, because that is what the foreign key holds.
    decided_by: str | None = None
    #: And the name that id belongs to, resolved in the run's own join. A
    #: screen shows this and keeps the id for the tooltip: an engineer knows
    #: their name, not their primary key. Null when the user row is gone.
    decided_by_name: str | None = None
    decided_at: str | None = None
    completeness: dict | None = None


class ReviewCodeDecision(BaseModel):
    """The engineer's final code for a run.

    `override_reason` is REQUIRED when the code differs from the AI's
    recommendation and optional when it agrees - section 15's "the engineer's
    final action is governance". The rule is enforced server-side in
    `comparison.record_engineer_code`, not here, because a client that
    omitted the field would otherwise decide whether the rule applied.
    """

    model_config = ConfigDict(extra="forbid")
    code: str
    override_reason: str | None = Field(default=None, max_length=2000)


class ReviewDashboard(BaseModel):
    """The four cards of master plan section 20, and the recent runs.

    EVERY FIGURE CARRIES ITS POPULATION. `submittals_awaiting_review` is out
    of `submittals_total`; `standards_referenced_missing` is out of
    `standards_referenced_total`. A card showing one number without the other
    is the bare-count defect CLAUDE.md rule 4 forbids.
    """

    submittals_total: int = 0
    submittals_awaiting_review: int = 0
    standards_available: int = 0
    standards_referenced_total: int = 0
    standards_referenced_missing: int = 0
    reviews_running: int = 0
    reviews_awaiting_decision: int = 0
    reviews_total: int = 0
    needs_attention: int = 0
    #: Why each run counts as needing attention, so the tile is auditable
    #: rather than a number a reader has to trust.
    needs_attention_reasons: dict[str, int] = {}
    recent: list[ReviewRunSummary] = []


class ReviewRunList(BaseModel):
    runs: list[ReviewRunSummary]


class ReviewRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submittal_document_id: str


class ReviewFindingList(BaseModel):
    findings: list[ReviewFinding]


class ReviewFindingEvent(BaseModel):
    id: str
    finding_id: str
    event_type: str
    changes: dict
    actor_user_id: str | None
    created_at: str


class ReviewFindingEventList(BaseModel):
    events: list[ReviewFindingEvent]


DeliverableStatus = Literal["planned", "in_progress", "submitted", "under_review", "approved", "rejected", "superseded"]


class DeliverableCreate(BaseModel):
    wbs_code: str = Field(min_length=1, max_length=100)
    parent_id: str | None = None
    title: str = Field(min_length=1, max_length=500)
    deliverable_type: str = Field(min_length=1, max_length=100)
    revision: str = Field(default="0", max_length=50)
    status: DeliverableStatus = "planned"
    document_id: str | None = None
    owner_user_id: str | None = None
    planned_date: str | None = None
    due_date: str | None = None
    submitted_at: str | None = None
    approved_at: str | None = None


class DeliverableUpdate(BaseModel):
    wbs_code: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    deliverable_type: str | None = Field(default=None, min_length=1, max_length=100)
    revision: str | None = Field(default=None, max_length=50)
    status: DeliverableStatus | None = None
    document_id: str | None = None
    owner_user_id: str | None = None
    planned_date: str | None = None
    due_date: str | None = None
    submitted_at: str | None = None
    approved_at: str | None = None


class Deliverable(BaseModel):
    id: str
    wbs_code: str
    parent_id: str | None
    title: str
    deliverable_type: str
    revision: str
    status: DeliverableStatus
    document_id: str | None
    owner_user_id: str | None
    planned_date: str | None
    due_date: str | None
    submitted_at: str | None
    approved_at: str | None
    created_by: str | None
    created_at: str
    updated_at: str


class DeliverableList(BaseModel):
    deliverables: list[Deliverable]


class DeliverableEvent(BaseModel):
    id: str
    deliverable_id: str
    event_type: str
    changes: dict
    actor_user_id: str | None
    created_at: str


class DeliverableEventList(BaseModel):
    events: list[DeliverableEvent]


StakeholderRole = Literal["owner", "reviewer", "approver", "informed"]


class DeliverableStakeholder(BaseModel):
    deliverable_id: str
    user_id: str
    role: StakeholderRole
    email: str
    display_name: str | None


class DeliverableStakeholderAssignment(BaseModel):
    user_id: str
    role: StakeholderRole


class DeliverableStakeholderUpdate(BaseModel):
    assignments: list[DeliverableStakeholderAssignment] = Field(max_length=100)


class DeliverableStakeholderList(BaseModel):
    stakeholders: list[DeliverableStakeholder]


class DeliverableAlert(BaseModel):
    deliverable_id: str
    wbs_code: str
    title: str
    due_date: str
    days_overdue: int
    escalation_level: int
    severity: Literal["minor", "major", "critical"]


class DeliverableAlertList(BaseModel):
    alerts: list[DeliverableAlert]


class WbsWorkspace(BaseModel):
    node: Deliverable
    children: list[Deliverable]
    documents: list[dict]
    reviews: list[ReviewFinding]
    escalations: list[DeliverableAlert]


class ReminderEvent(BaseModel):
    id: str
    deliverable_id: str
    level: int
    due_date: str
    recipient_role: str
    status: Literal["pending", "acknowledged"]
    acknowledged_at: str | None
    created_at: str


class ReminderEventList(BaseModel):
    reminders: list[ReminderEvent]


class NotificationSendResponse(BaseModel):
    sent: bool


class ManagementSummary(BaseModel):
    deliverables_total: int
    deliverables_by_status: dict[str, int]
    review_findings_total: int
    findings_by_severity: dict[str, int]
    findings_by_status: dict[str, int]
    escalated_findings: int
    overdue_alerts: int
    alerts: list[DeliverableAlert]


class SummarySchedule(BaseModel):
    schedule: Literal["disabled", "daily", "weekly"]
    weekday_utc: int = Field(default=0, ge=0, le=6)
    hour_utc: int = Field(default=8, ge=0, le=23)


class EscalationRule(BaseModel):
    level: int = Field(ge=1, le=5)
    trigger_days: int = Field(ge=0, le=3650)
    recipient_role: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=300)
    enabled: bool = True


class EscalationRuleList(BaseModel):
    rules: list[EscalationRule]


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
    corpus_wide: bool = Field(
        description="True when `corpus` and `exclusions` count the WHOLE "
                    "corpus rather than only documents this caller may read. "
                    "Required, not optional: a count with no stated boundary "
                    "reads as total, and the screen must be able to say which "
                    "kind of number it is showing."
    )
    corpus: CorpusMetrics
    exclusions: list[ExclusionSummary]
    jobs: JobMetrics
    throughput: dict[str, StageThroughput | None] = Field(
        description="null for a stage that has never run measurably"
    )
    retrieval: RetrievalLatency | None = Field(
        None, description="null until a question has actually been asked"
    )
    system: SystemMetrics | None = Field(
        None,
        description="The machine's own CPU, memory and disk. ABSENT, not "
                    "zeroed, for any caller without the admin capability "
                    "(#77) - host specifications are not a document, so "
                    "document scoping could never have removed them. A "
                    "blanked block would state measurements that are false; "
                    "an absent one states nothing.",
    )
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


# ------------------------------------------------------------------ admin
#
# The admin screen's response shapes, matching `docs/design-admin-screen.md`.
# Every warning is a Literal ENUM and never a sentence: the UI switches on the
# value and owns the wording. A message built here would be a string the
# frontend had to parse for meaning, and `facet` being a string on one side of
# this boundary and a list on the other is what the contract was written after.


class AdminUser(BaseModel):
    """One row of the users table on the admin screen.

    `last_login_at` is None for a user who has never signed in, and the UI
    renders that as NOTHING - not a dash, not a zero, not "never". The null
    reaches the client intact so the decision stays on the screen where the
    reader is.
    """

    user_id: str = Field(examples=["usr_a1b2c3d4"])
    email: str
    disciplines: list[str]
    is_admin: bool = Field(description="the admin capability, orthogonal to discipline")
    active: bool
    created_at: str | None = Field(None, examples=["2026-09-05T18:12:04Z"])
    last_login_at: str | None = Field(None, description="null when never signed in")
    warning: Literal["no_discipline"] | None = None


class AdminUserList(BaseModel):
    """Note what is NOT here: there is no `setup_token` field on this model,
    so the token cannot be returned by this route even by accident."""

    users: list[AdminUser]


class AdminUserCreated(BaseModel):
    """The ONLY response that ever carries a setup token.

    `shown_once` is part of the contract rather than documentation of it: the
    client is told, in the payload, that this value is not retrievable again -
    the storage keeps only its SHA-256 - so a UI cannot decide to fetch it
    later instead of showing it now.
    """

    user_id: str
    email: str
    setup_token: str = Field(description="shown once; never returned again")
    setup_token_expires_at: str
    shown_once: Literal[True] = True


class AdminUserDeactivated(BaseModel):
    """Deactivated, never deleted - conversations and reports reference a user
    and a hard delete would orphan the evidence a report depends on."""

    user_id: str
    active: Literal[False] = False


class AdminDiscipline(BaseModel):
    name: str
    user_count: int
    document_count: int
    warning: Literal["no_documents"] | None = Field(
        None, description="everyone in this discipline sees an empty corpus")


class AdminDisciplineList(BaseModel):
    disciplines: list[AdminDiscipline]


class AdminGrantDocument(BaseModel):
    document_id: str
    filename: str
    disciplines: list[str]
    warning: Literal["no_discipline_can_see_this"] | None = Field(
        None, description="invisible in every search; looks like a broken upload")


class AdminGrantList(BaseModel):
    documents: list[AdminGrantDocument]


class AdminGrantResult(BaseModel):
    """`granted` states the RESULTING state, not what this call changed.

    That is what makes PUT and DELETE idempotent from the client's side too: a
    revoke of something already revoked returns exactly what a revoke of a live
    grant returns, so a retried click has nothing to reconcile.
    """

    document_id: str
    discipline: str
    granted: bool


# ------------------------------------------- the read-only database explorer
#
# A WINDOW, NOT A WORKBENCH. There is no write model anywhere in this block,
# and that is the design rather than an omission: nothing here accepts a value
# to store, so no client - and no future screen built against these types -
# can discover an edit path that does not exist.


class AdminDbTable(BaseModel):
    name: str
    row_count: int


class AdminDbTableList(BaseModel):
    tables: list[AdminDbTable]


class AdminDbColumn(BaseModel):
    name: str
    type: str | None = None
    notnull: bool = False
    pk: bool = False
    #: True when this column's NAME says it holds credential material. The
    #: column is still listed - hiding it would misreport the table's shape -
    #: and its values arrive masked.
    sensitive: bool = False


class AdminDbTableInfo(BaseModel):
    name: str
    columns: list[AdminDbColumn]
    row_count: int


class AdminDbRows(BaseModel):
    """A page of rows, with the denominator that makes the page honest.

    `total` is the whole table; `limit`/`offset` say which slice this is. A
    screen showing rows with no total would imply completeness it does not
    have (CLAUDE.md rule 4).
    """

    name: str
    columns: list[str]
    #: Values as stored, EXCEPT credential-shaped columns, which arrive as the
    #: mask string. The masking happens in `admin_explorer.read_rows`, before
    #: the value reaches this model or the wire.
    rows: list[list]
    offset: int
    limit: int
    total: int
    masked_columns: list[str] = []


ERRORS_409 = {409: {"model": ErrorEnvelope, "description": "Conflicts with existing state"}}
