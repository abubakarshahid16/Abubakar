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

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.lance_dir.parent):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
