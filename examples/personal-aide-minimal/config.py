"""Environment-driven configuration for personal-aide-minimal.

Single-user demo — `USER_ID` and `DOMAIN_ID` are constants. A real assistant
resolves identity per request (see agno-plus guidance G-0001).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    uploads_dir: Path

    llm_backend: str
    llm_model: str
    embed_model: str
    openai_api_key: str
    ollama_url: str
    vision_model: str

    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str


def _settings() -> Settings:
    backend = os.getenv("LLM_BACKEND", "openai")
    uploads = Path(os.getenv("UPLOADS_DIR", "./uploads"))
    uploads.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://aide:aide@localhost:5432/aide"),
        uploads_dir=uploads,
        llm_backend=backend,
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        embed_model=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        vision_model=os.getenv("VISION_MODEL", "gpt-4o" if backend == "openai" else "llava"),
        langfuse_host=os.getenv("LANGFUSE_HOST", ""),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    )


settings = _settings()

USER_ID = "local_user"
DOMAIN_ID = "personal"
