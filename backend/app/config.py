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

    ollama_url: str = "http://127.0.0.1:11434"
    answer_model: str = "qwen3.5:4b"

    # Measured on the target CPU - see docs/benchmarks.md
    num_thread: int = 12
    num_batch: int = 2048
    num_ctx: int = 1536
    max_output_tokens: int = 100
    temperature: float = 0.1

    upload_chunk_bytes: int = 1024 * 1024
    max_upload_mb: int = 2048
    page_batch_size: int = 32
    extract_processes: int = 2
    embed_batch_size: int = 32

    # Chunking. e5-small has a hard 512-token limit; stay below it so the
    # model never silently truncates a chunk.
    chunk_target_tokens: int = 300
    chunk_overlap_tokens: int = 60
    chunk_max_tokens: int = 480
    running_line_threshold: float = 0.03   # fraction of pages; a running head repeats per chapter, not book-wide
    running_line_scan_lines: int = 3

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
