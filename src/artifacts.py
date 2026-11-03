"""Per-query artifact storage.

Every query gets a directory under ``artifacts/<query_id>/`` containing the
stage snapshots (request, guardrails, retrieval, prompt, completion, response).
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUERY_ID_RE = re.compile(r"^q_[A-Za-z0-9_]+$")
ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactError(ValueError):
    """Raised for invalid query IDs, artifact names, or missing artifacts."""


def new_query_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"q_{timestamp}_{secrets.token_hex(3)}"


def _validate_query_id(query_id: str) -> str:
    if not QUERY_ID_RE.fullmatch(query_id):
        raise ArtifactError(
            f"Invalid query_id {query_id!r}; expected q_<timestamp>_<hex>."
        )
    return query_id


def _validate_name(name: str) -> str:
    if not ARTIFACT_NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise ArtifactError(f"Invalid artifact name: {name!r}")
    return name


def _query_dir(root: Path, query_id: str) -> Path:
    return Path(root) / _validate_query_id(query_id)


def _artifact_path(root: Path, query_id: str, name: str) -> Path:
    return _query_dir(root, query_id) / _validate_name(name)


class ArtifactWriter:
    """Writes stage artifacts for one query."""

    def __init__(self, root: str | Path, query_id: str):
        self.root = Path(root)
        self.query_id = _validate_query_id(query_id)
        self.directory = self.root / self.query_id
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.directory / _validate_name(name)

    def write_json(self, name: str, payload: Any) -> Path:
        return self.write_text(
            name,
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        )

    def write_text(self, name: str, text: str) -> Path:
        path = self.path(name)
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
        return path


def read_artifact(root: str | Path, query_id: str, name: str) -> str:
    path = _artifact_path(root, query_id, name)
    if not path.exists():
        raise ArtifactError(f"Artifact not found: {path}")
    return path.read_text(encoding="utf-8")


def read_json_artifact(root: str | Path, query_id: str, name: str) -> Any:
    return json.loads(read_artifact(root, query_id, name))


def list_artifacts(root: str | Path, query_id: str) -> list[str]:
    directory = _query_dir(root, query_id)
    if not directory.exists():
        return []
    return sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
