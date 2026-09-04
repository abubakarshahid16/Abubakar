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
    needs_ocr_pages: int = Field(description="detected only; OCR is not implemented")
    equation_pages: int = Field(description="maths did not survive extraction")
    error: DocumentError | None = None
    uploaded_at: str
    indexed_at: str | None = None


class UploadAccepted(BaseModel):
    document: Document
    job_id: str = Field(description="empty when the upload was a duplicate")
    duplicate_of: str | None = None


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


class Health(BaseModel):
    ok: bool
    embed_model_present: bool
    answer_model: str
    ingestion: WorkerStatus


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


class Exclusion(BaseModel):
    scope: Literal["page", "chunk"]
    page_start: int | None
    page_end: int | None
    chunk_id: str | None
    rule: str
    reason: str | None
    text_length: int
    text_sample: str


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


class KeywordIndexResult(BaseModel):
    document_id: str
    indexed: int
    seconds: float
    chunks_per_sec: float | None


class DeleteResult(BaseModel):
    deleted: str
    filename: str
    rows_removed: dict[str, int]
    files_removed: int


#: Reusable error documentation for the OpenAPI schema.
ERRORS_404 = {404: {"model": ErrorEnvelope, "description": "Unknown document id"}}
ERRORS_422 = {
    422: {
        "model": ErrorEnvelope,
        "description": "Invalid or unknown query parameter",
    }
}
ERRORS_400 = {400: {"model": ApiError, "description": "Rejected request"}}
