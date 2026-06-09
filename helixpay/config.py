"""Runtime configuration — secrets from env only (spec §1, CLAUDE.md §7).

No secret literals live in source. Model ids and the embedding dimension are pinned
here so every agent uses the same models:

    extraction  = claude-sonnet-4-6   (cheap, parallel at ingest)
    synthesis    = claude-opus-4-8     (ask() reasoning)
    embeddings   = voyage (1024-dim)

``load_config()`` raises ``MissingEnvError`` listing every missing variable; it is
called at process start, not import time, so unit tests that need no DB/keys can
import this module freely.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Pinned models (not secrets — safe to hardcode).
EXTRACTION_MODEL = "claude-sonnet-4-6"
SYNTHESIS_MODEL = "claude-opus-4-8"
EMBEDDING_MODEL = "voyage-3"
EMBEDDING_DIM = 1024

_REQUIRED_ENV = ("DATABASE_URL", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY")


class MissingEnvError(RuntimeError):
    """Raised when one or more required environment variables are unset."""


@dataclass(frozen=True)
class Config:
    database_url: str
    anthropic_api_key: str
    voyage_api_key: str
    extraction_model: str = EXTRACTION_MODEL
    synthesis_model: str = SYNTHESIS_MODEL
    embedding_model: str = EMBEDDING_MODEL
    embedding_dim: int = EMBEDDING_DIM


def load_config() -> Config:
    """Build a Config from the environment. Raises MissingEnvError if any of the
    required secrets are unset. Never logs secret values."""
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise MissingEnvError(
            "Missing required environment variable(s): " + ", ".join(missing)
        )
    return Config(
        database_url=os.environ["DATABASE_URL"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
    )


def database_url() -> str:
    """Return DATABASE_URL or raise MissingEnvError. Used by db tooling that does
    not need the LLM keys (migrations, the integration test harness)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise MissingEnvError("Missing required environment variable: DATABASE_URL")
    return url


__all__ = [
    "Config",
    "MissingEnvError",
    "load_config",
    "database_url",
    "EXTRACTION_MODEL",
    "SYNTHESIS_MODEL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
]
