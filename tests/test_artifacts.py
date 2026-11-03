import pytest

from src.artifacts import (
    ArtifactError,
    ArtifactWriter,
    list_artifacts,
    new_query_id,
    read_json_artifact,
)


def test_writer_round_trip(tmp_path):
    query_id = new_query_id()
    writer = ArtifactWriter(tmp_path, query_id)

    path = writer.write_json("00_request.json", {"query": "test"})
    writer.write_text("03_prompt.txt", "prompt text")

    assert path.exists()
    assert read_json_artifact(tmp_path, query_id, "00_request.json") == {"query": "test"}
    assert list_artifacts(tmp_path, query_id) == ["00_request.json", "03_prompt.txt"]


def test_rejects_invalid_query_id(tmp_path):
    with pytest.raises(ArtifactError):
        ArtifactWriter(tmp_path, "../escape")


def test_rejects_artifact_name_traversal(tmp_path):
    writer = ArtifactWriter(tmp_path, new_query_id())

    with pytest.raises(ArtifactError):
        writer.write_text("../outside.txt", "nope")
