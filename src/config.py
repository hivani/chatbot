"""Typed application configuration.

Loads tunables from ``config.yaml`` and secrets from ``.env``. Relative paths
are resolved against the directory containing the config file (the project
root by default).

Usage:
    from src.config import load_settings
    settings = load_settings()                 # local scripts/tests
    settings = load_settings(require_secrets=True)  # app startup
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Environment variable that holds the API key for each supported provider.
PROVIDER_KEY_ENV: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

COLLECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,61}[A-Za-z0-9]$")


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or inconsistent."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictModel):
    name: str = "Growchatbot"
    disclaimer: str = "Facts-only. No investment advice."
    max_answer_sentences: int = Field(default=3, ge=1, le=10)


class PathsConfig(StrictModel):
    sources: Path = Path("data/sources.csv")
    raw_dir: Path = Path("data/raw")
    chunks_file: Path = Path("data/chunks/chunks.jsonl")
    embeddings_dir: Path = Path("data/embeddings")
    artifacts_dir: Path = Path("artifacts")


class EmbeddingConfig(StrictModel):
    model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", min_length=1)
    max_seq_length: int = Field(default=256, gt=0)
    normalize: bool = True
    batch_size: int = Field(default=32, gt=0)


class ChunkingConfig(StrictModel):
    chunk_size: int = Field(default=220, gt=0)
    chunk_overlap: int = Field(default=40, ge=0)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "ChunkingConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class VectorStoreConfig(StrictModel):
    persist_path: Path = Path("data/chroma")
    collection: str = "groww_mf_faq"
    distance: Literal["cosine", "l2", "ip"] = "cosine"

    @field_validator("collection")
    @classmethod
    def _valid_collection_name(cls, value: str) -> str:
        if not COLLECTION_RE.fullmatch(value):
            raise ValueError(
                "collection must be 3-63 characters, start/end alphanumeric, "
                "and contain only letters, digits, '.', '_' or '-'"
            )
        return value


class RetrievalConfig(StrictModel):
    top_k: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.35, ge=0.0, le=1.0)


class LLMConfig(StrictModel):
    provider: Literal["groq", "gemini", "openai", "anthropic", "mistral"] = "groq"
    model_env: str = Field(default="GROQ_MODEL", min_length=1)
    model: str | None = None
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=300, gt=0)
    timeout_seconds: int = Field(default=20, gt=0)


class Settings(StrictModel):
    app: AppConfig
    paths: PathsConfig
    embedding: EmbeddingConfig
    chunking: ChunkingConfig
    vector_store: VectorStoreConfig
    retrieval: RetrievalConfig
    llm: LLMConfig

    @model_validator(mode="after")
    def _chunk_fits_embedding_model(self) -> "Settings":
        if self.chunking.chunk_size > self.embedding.max_seq_length:
            raise ValueError(
                f"chunking.chunk_size ({self.chunking.chunk_size}) must be <= "
                f"embedding.max_seq_length ({self.embedding.max_seq_length})"
            )
        return self


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file must contain a YAML mapping: {path}")
    return raw


def _resolve_path(path: Path, root: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = root / expanded
    return expanded.resolve()


def _resolve_paths(paths: PathsConfig, root: Path) -> PathsConfig:
    return paths.model_copy(
        update={
            "sources": _resolve_path(paths.sources, root),
            "raw_dir": _resolve_path(paths.raw_dir, root),
            "chunks_file": _resolve_path(paths.chunks_file, root),
            "embeddings_dir": _resolve_path(paths.embeddings_dir, root),
            "artifacts_dir": _resolve_path(paths.artifacts_dir, root),
        }
    )


def _ensure_directories(settings: Settings) -> None:
    for directory in (
        settings.paths.sources.parent,
        settings.paths.raw_dir,
        settings.paths.chunks_file.parent,
        settings.paths.embeddings_dir,
        settings.paths.artifacts_dir,
        settings.vector_store.persist_path,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _require_secrets(settings: Settings) -> None:
    provider = settings.llm.provider
    key_env = PROVIDER_KEY_ENV[provider]

    if not os.getenv(key_env):
        raise ConfigError(
            f"{key_env} is required for llm.provider={provider!r}. "
            f"Add it to .env or the environment."
        )
    if not settings.llm.model:
        raise ConfigError(
            f"{settings.llm.model_env} is required for llm.provider={provider!r}. "
            f"Set it in .env or the environment."
        )


def load_settings(
    config_path: str | Path = "config.yaml",
    env_path: str | Path | None = ".env",
    *,
    require_secrets: bool = False,
) -> Settings:
    """Load and validate configuration.

    Args:
        config_path: Path to the YAML config. Relative paths resolve against
            the project root.
        env_path: Path to the .env file. Relative paths resolve against the
            config file's directory. Pass ``None`` to skip loading .env.
        require_secrets: When true, fail if the active provider's API key or
            model id is missing. Use this at application startup, not in
            config-only unit tests.
    """

    config_file = Path(config_path).expanduser()
    if not config_file.is_absolute():
        config_file = PROJECT_ROOT / config_file
    config_file = config_file.resolve()

    if env_path is not None:
        env_file = Path(env_path).expanduser()
        if not env_file.is_absolute():
            env_file = config_file.parent / env_file
        if env_file.exists():
            load_dotenv(env_file, override=False)

    raw = _read_yaml(config_file)

    try:
        settings = Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {config_file}:\n{exc}") from exc

    settings = settings.model_copy(
        update={"paths": _resolve_paths(settings.paths, config_file.parent)}
    )

    # The model id lives in the environment, not in config.yaml.
    model = os.getenv(settings.llm.model_env) or settings.llm.model
    settings = settings.model_copy(
        update={"llm": settings.llm.model_copy(update={"model": model})}
    )

    if require_secrets:
        _require_secrets(settings)

    _ensure_directories(settings)
    return settings
