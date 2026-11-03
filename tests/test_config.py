from pathlib import Path

import pytest

from src.config import PROJECT_ROOT, ConfigError, load_settings


def _project_config_text() -> str:
    return (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")


def test_loads_project_config():
    settings = load_settings(env_path=None)

    assert settings.vector_store.collection == "groww_mf_faq"
    assert settings.embedding.model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.chunking.chunk_size == 220
    assert settings.paths.sources.is_absolute()
    assert settings.paths.raw_dir.is_absolute()


def test_reads_model_id_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "qwen/test-model")

    settings = load_settings(env_path=None)

    assert settings.llm.model == "qwen/test-model"


def test_requires_provider_secrets(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_settings(env_path=None, require_secrets=True)


def test_rejects_chunk_size_over_embedding_limit(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text(
        _project_config_text().replace("chunk_size: 220", "chunk_size: 400"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="chunk_size"):
        load_settings(config, env_path=None)


def test_rejects_invalid_collection_name(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text(
        _project_config_text().replace(
            "collection: groww_mf_faq", 'collection: "bad name!"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="collection"):
        load_settings(config, env_path=None)


def test_resolves_relative_paths_against_config_dir(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text(_project_config_text(), encoding="utf-8")

    settings = load_settings(config, env_path=None)

    assert settings.paths.raw_dir == (tmp_path / "data/raw").resolve()
    assert settings.paths.chunks_file == (tmp_path / "data/chunks/chunks.jsonl").resolve()
    assert settings.paths.raw_dir.is_dir()
    assert settings.paths.embeddings_dir.is_dir()
    assert settings.paths.artifacts_dir.is_dir()
    assert settings.vector_store.persist_path.is_dir()
