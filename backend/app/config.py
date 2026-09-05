from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Bind loopback only. Never 0.0.0.0 - document content must not be reachable.
    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: Path = BACKEND_DIR / "data"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    db_path: Path = BACKEND_DIR / "data" / "nabaa.sqlite"
    lance_dir: Path = BACKEND_DIR / "data" / "vectors.lance"

    embed_model_dir: Path = BACKEND_DIR / "models" / "e5-small"

    # ------------------------------------------------------------------ OCR
    #: Weights are VENDORED and addressed by explicit path. RapidOCR resolves
    #: an unset model_path by downloading from modelscope.cn on first
    #: construction, which fails on an air-gapped machine at the first
    #: recognition rather than at install. Staged by scripts/fetch_models.py.
    #: `disabled` (default) or `demo_required`. Disabled must behave exactly as
    #: the system did before authorisation existed, so every pre-existing test
    #: passes unchanged with it off - which is what proves the enforcement is
    #: additive, and what makes the rollback a config change rather than a
    #: revert. The enforcement path runs in BOTH modes; only the contents of
    #: the scope differ.
    auth_mode: str = "disabled"

    ocr_model_dir: Path = BACKEND_DIR / "models" / "ocr"
    ocr_det_model: str = "PP-OCRv6_det_tiny.onnx"
    #: The recogniser is the open decision. PP-OCRv6 ships no English model, so
    #: this multilingual one can emit CJK into an English document - measured:
    #: 凤, 日, ≦ for "Save". `en_PP-OCRv5_rec_mobile.onnx` cannot, by
    #: construction, at 2.16 s/page against 0.90. Switch when the client
    #: confirms whether the corpus contains Arabic. See ADR-0005.
    ocr_rec_model: str = "PP-OCRv6_rec_tiny.onnx"
    ocr_cls_model: str = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"

    #: 150, measured, not assumed. 300 dpi produced WORSE text on these
    #: documents for 39% more time and 186 MB more RSS - it splits words and
    #: drops letters from proper names. See ADR-0005.
    ocr_dpi: int = 150
    #: Kept ON. Turning it off saved 1% and changed the output on 2 of 12
    #: pages; a 1% saving is not worth a behaviour change.
    ocr_use_cls: bool = True
    #: Bounded explicitly. Never -1: that takes all 12 logical cores and
    #: allocates a per-thread arena each, which is how the reranker came to
    #: reserve 829 MB for a 22 MB model.
    ocr_threads: int = 2
    ocr_rec_batch: int = 4
    ocr_max_side_len: int = 2000
    #: Memory-bound, not CPU-bound, and ONE - corrected by measuring the real
    #: stage rather than one worker in isolation. Isolated workers peaked at
    #: 524-549 MB, which suggested two would fit in the 1.15 GiB free at demo
    #: time. Running the actual stage measured the WHOLE operation, parent plus
    #: children at their simultaneous peak: 1,399 MB for two workers against
    #: 598 MB for one. Two do not fit. NOT scaled to cores - that is how the
    #: reranker came to reserve 829 MB for a 22 MB model.
    ocr_processes: int = 1
    ocr_batch_size: int = 8
    #: Characters outside this script in recognised text are a recognition
    #: failure, not a curiosity. Counted and flagged, never deleted.
    ocr_expected_script: str = "latin"

    ollama_url: str = "http://127.0.0.1:11434"
    answer_model: str = "qwen3.5:4b"
    #: Resident size of the answer model. Used to warn BEFORE someone presses
    #: Explain: with 14.7 GB of 16 GB already in use, Tier 2 will swap hard or
    #: fail, and that is a fact worth surfacing before the button is clicked
    #: rather than after a two-minute stall in front of a client.
    answer_model_ram_bytes: int = 3_400_000_000

    # Measured on the target CPU - see docs/benchmarks.md
    num_thread: int = 12
    num_batch: int = 2048
    num_ctx: int = 1536
    max_output_tokens: int = 100
    temperature: float = 0.1

    upload_chunk_bytes: int = 1024 * 1024
    #: Ceiling on a single upload, enforced DURING the stream in
    #: `upload.stream_to_temp` - the count is checked per block and the read
    #: aborts the moment it is exceeded, rather than discovering afterwards
    #: that the whole file was already on disk. This is the only unbounded
    #: untrusted input in the system.
    #:
    #: SET FROM MEASUREMENT, not from a round number. The largest document
    #: ingested is book4 at 37.6 MB / 1,400 pages (27.5 KB per page); the
    #: corpus ranges 3.6-27.5 KB per page. 512 MB is 13.6x that largest file
    #: and about 19,000 pages at the observed density - comfortably above any
    #: real specification, while bounding what a single malicious request can
    #: write to a volume with ~45 GB free. The previous value of 2048 MB was
    #: 54x the largest real document and had never been measured against
    #: anything.
    max_upload_mb: int = 512
    page_batch_size: int = 32
    extract_processes: int = 2
    embed_batch_size: int = 32

    # Chunking. e5-small has a hard 512-token limit; stay below it so the
    # model never silently truncates a chunk.
    chunk_target_tokens: int = 300
    chunk_overlap_tokens: int = 60
    chunk_max_tokens: int = 480

    # Retrieval. Defaults chosen from measurement on this CPU, not by guess:
    # reranking 30 candidates at 320 tokens costs ~1025ms, 20 at 256 costs
    # ~500ms, which is what keeps the Tier 1 answer inside its 1-2s budget.
    search_candidates: int = 30       # retrieved from each side before fusion
    #: How many candidates the cross-encoder sees. Reduced from 20 to claw
    #: back the latency that widening the rerank window cost, measured over
    #: the independent 15-question set:
    #:
    #:   candidates   retrieval  citation  tokens  refusal  false  median
    #:           20      10/10       9/9   10/10      5/5      0   2213 ms
    #:           16      10/10       9/9   10/10      5/5      0   1961 ms
    #:           12       9/10       8/9    9/10      5/5      0   1712 ms
    #:           10      10/10       9/9   10/10      5/5      0   1697 ms
    #:
    #: 16, not 10. The result is NOT monotonic - 12 degrades and 10 recovers -
    #: which means the shortlist composition is changing under the questions
    #: rather than the depth being genuinely unnecessary. One perfect run at 10
    #: sitting next to a degraded run at 12 is noise, not evidence, so 16 keeps
    #: a margin above the unstable region for the 250 ms it costs.
    rerank_candidates: int = 16
    #: MUST cover chunk_max_tokens, or the cross-encoder judges a chunk on a
    #: fragment of it and is asked to rate relevance it was never shown.
    #:
    #: At 256 this silently broke every long chunk. NORSOK's clause 11 holds
    #: Table 3 flattened to 486 tokens, and "Holiday detection NACE RP0188
    #: voltage" sits at token 350 - so the reranker scored the passage on its
    #: first 256 tokens, which are about environmental conditions and visual
    #: examination, and returned -10.95. That score was CORRECT about what it
    #: had been given and wrong about the passage. The evaluation recorded it
    #: as a retrieval failure, and it was a truncation failure.
    #:
    #: Measured cost of covering the whole chunk, 20 candidates, median of 5:
    #:   256 tokens   583 ms
    #:   320 tokens   603 ms
    #:   384 tokens   910 ms
    #:   480 tokens   796 ms
    #:   512 tokens  1182 ms
    #: +213 ms against 256, which keeps Tier 1 inside its 1-2 second target.
    rerank_max_tokens: int = 480
    rerank_batch: int = 32

    #: ONNX Runtime's CPU arena allocator reserves large per-thread blocks
    #: and never returns them. Measured on this machine (16 GB, 12 threads):
    #:
    #:                       process RSS   tier-1 query   embed
    #:   both arenas on          3,247 MB       ~1,926 ms   6.9 c/s
    #:   rerank off, embed on    2,438 MB       ~2,493 ms   6.8 c/s
    #:   both off                  503 MB       ~2,500 ms   5.7 c/s
    #:
    #: Rerank scores are BIT-IDENTICAL either way (np.array_equal, max diff
    #: 0.0) - arena configuration changes allocation, not arithmetic. So there
    #: is no accuracy trade here, but there IS a latency one: roughly 2.7 GB
    #: against roughly 575 ms.
    #:
    #: DEFAULT IS ON, deliberately. Two hypotheses for turning it off were
    #: tested and both failed:
    #:   * that it would recover the latency lost to memory pressure - it does
    #:     not, it costs latency
    #:   * that freeing memory would speed up Explain, which needs ~2.5 GB for
    #:     qwen3.5:4b - measured warm, Explain is 7.4-7.9 s with the arena on
    #:     against 8.3-10.5 s with it off. A 63 s Explain measured earlier was
    #:     Ollama's cold model load, not the arena.
    #: Left configurable because 503 MB against 3,247 MB is a real option on a
    #: machine that demos at 92% RAM - but it buys stability, not speed.
    onnx_cpu_arena_rerank: bool = True
    onnx_cpu_arena_embed: bool = True
    # Small-to-big. Retrieval runs on the small chunk; the reader is shown
    # the surrounding parent block, expanded to neighbours up to this many
    # characters. The generated budget is smaller because three sources have
    # to fit inside num_ctx alongside the prompt.
    answer_context_chars: int = 2400
    generated_context_chars: int = 1200
    running_line_threshold: float = 0.03   # fraction of pages; a running head repeats per chapter, not book-wide
    # Only the top/bottom N lines of a page are considered for running
    # header/footer removal. NORSOK stacks four lines of furniture -
    # "NORSOK standard M-501" / "Rev. 5, June 2004" / "NORSOK standard" /
    # "Page 6 of 20" - so a 3-line window caught the first three and left the
    # page number prepended to the text of nearly every chunk. The short-page
    # guard inside strip_running_lines keeps a wider window safe.
    running_line_scan_lines: int = 5

    # Content-quality gate. A chunk failing these does not read like natural
    # language and is stored but not retrievable. Tuned against known-good
    # book1 prose and known-bad book2 symbol-font tables.
    quality_min_alpha_ratio: float = 0.55
    quality_max_symbol_ratio: float = 0.20
    quality_min_wordish_ratio: float = 0.45
    quality_min_avg_word_len: float = 2.5
    quality_max_unbroken_run: int = 45
    quality_max_control_chars: int = 3      # only the top/bottom N lines of a page

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.lance_dir.parent):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
