"""Application settings, loaded from environment variables / backend/.env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Export .env into os.environ so the LangChain integrations can read provider keys.
# Real environment variables (e.g. set on Render) take precedence.
load_dotenv(BACKEND_DIR / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM -------------------------------------------------------------
    # One of: openai | anthropic | groq
    llm_provider: str = "groq"
    # Cheap fast model: intent classification.
    llm_fast_model: str = "openai/gpt-oss-20b"
    # Strong model: SQL generation, repair, optimization, debugging, explanation.
    llm_strong_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.0
    llm_timeout_seconds: int = 60
    # Provider keys are read by the LangChain integrations directly from the
    # environment (OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY).

    # --- Database --------------------------------------------------------
    database_path: Path = BACKEND_DIR / "app" / "db" / "app.db"
    max_result_rows: int = 100
    query_timeout_seconds: float = 5.0

    # --- Agent -----------------------------------------------------------
    max_retries: int = 3
    history_turns: int = 6           # chat turns sent to the model
    schema_full_threshold: int = 25  # above this many tables, retrieve only relevant ones

    # --- Conversation memory --------------------------------------------
    # Empty = in-memory (lost on restart). Set a path to persist with SqliteSaver.
    checkpoint_db: str = ""

    # --- API -------------------------------------------------------------
    # Comma-separated list of allowed frontend origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
