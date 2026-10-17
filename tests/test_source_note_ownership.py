from unittest.mock import patch
import json

import pytest
from fastapi import HTTPException

from app.config import settings
from app.models.transcript import TranscriptResult
from app.services.note_service import NoteService
from app.services.task_artifact_service import TaskArtifactService


@pytest.mark.parametrize("source", ["url", "transcript"])
def test_failed_generation_keeps_the_authenticated_owner_marker(tmp_path, source, monkeypatch):
    service = NoteService.__new__(NoteService)
    service.artifact_service = TaskArtifactService(tmp_path)
    monkeypatch.setattr(settings, "vilab_server_url", "https://models.invalid")
    # Mock the catalog dependency, not the durable capture/validation boundary.
    with patch("app.services.vilab_cloud_service.VILabCloudService.status", return_value={
        "mode": "cloud", "server_url": "https://models.invalid", "asr_model": "frozen-asr", "llm_model": "frozen-llm",
    }), patch("app.services.vilab_cloud_service.VILabCloudService.defaults") as defaults, patch(
        "app.services.vilab_cloud_service.VILabCloudService.validate_ready", side_effect=RuntimeError("service unavailable")
    ) as ready:
        with pytest.raises(RuntimeError, match="^service unavailable$"):
            if source == "url":
                service.generate("https://www.bilibili.com/video/example", "source-test", user_id="owner")
            else:
                service.generate_from_transcript(TranscriptResult(full_text="sample", segments=[], language="zh"), "source-test", user_id="owner")
        defaults.assert_not_called()
        ready.assert_called_once_with("owner", needs_stt=source == "url")
    task = service.artifact_service.find_task_dir("source-test")
    assert (task / "recording_owner").read_text() == "owner"
    assert service.artifact_service.get_status("source-test")["status"] == "failed"
    assert json.loads((task / "model_source_snapshot.json").read_text())["owner"] == "owner"


@pytest.mark.parametrize("source", ["url", "transcript"])
def test_capture_auth_failure_still_binds_owner_before_preflight(tmp_path, source):
    service = NoteService.__new__(NoteService)
    service.artifact_service = TaskArtifactService(tmp_path)
    denied = HTTPException(401, "synthetic authentication rejected")
    with patch("app.services.task_model_source.capture_source", side_effect=denied) as capture, patch(
        "app.services.vilab_cloud_service.VILabCloudService.validate_ready"
    ) as ready:
        with pytest.raises(HTTPException) as caught:
            if source == "url":
                service.generate("https://example.invalid/source", "failed-capture", user_id="owner")
            else:
                service.generate_from_transcript(TranscriptResult(full_text="sample", segments=[], language="zh"), "failed-capture", user_id="owner")
        assert caught.value is denied
        capture.assert_called_once()
        ready.assert_not_called()
    task = service.artifact_service.find_task_dir("failed-capture")
    assert (task / "recording_owner").read_text() == "owner"
    assert service.artifact_service.get_status("failed-capture")["status"] == "failed"
    assert not (task / "model_source_snapshot.json").exists()


@pytest.mark.parametrize("marker", ["different", "same", "symlink", "dangling-symlink", "directory"])
def test_existing_owner_is_never_overwritten_or_followed(tmp_path, marker):
    service = NoteService.__new__(NoteService)
    service.artifact_service = TaskArtifactService(tmp_path / "output")
    task = service.artifact_service.create_task_dir("existing")
    owner = task / "recording_owner"
    target = tmp_path / "outside"
    target.write_text("owner")
    if marker in {"symlink", "dangling-symlink"}:
        try:
            owner.symlink_to(target if marker == "symlink" else tmp_path / "missing")
        except OSError as error:
            pytest.skip(f"symlink capability unavailable: {error.errno}")
    elif marker == "directory":
        owner.mkdir()
    else:
        owner.write_text("other" if marker == "different" else "owner")
    before = owner.stat().st_mtime_ns if marker == "same" else None
    with patch("app.services.task_model_source.capture_source", side_effect=HTTPException(401, "synthetic denied")) as capture:
        with pytest.raises(HTTPException) as caught:
            service.generate("https://example.invalid/source", "existing", user_id="owner")
        assert caught.value.status_code == (401 if marker == "same" else 404)
        assert capture.call_count == (1 if marker == "same" else 0)
    if marker == "same":
        assert owner.stat().st_mtime_ns == before
    elif marker == "different":
        assert owner.read_text() == "other"
    assert target.read_text() == "owner"


def test_symlink_task_folder_is_rejected_before_capture(tmp_path):
    service = NoteService.__new__(NoteService)
    output = tmp_path / "output"
    output.mkdir()
    service.artifact_service = TaskArtifactService(output)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (output / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink capability unavailable: {error.errno}")
    with patch("app.services.task_model_source.capture_source") as capture:
        with pytest.raises(HTTPException) as caught:
            service.generate("https://example.invalid/source", "linked", user_id="owner")
        assert caught.value.status_code == 404
        capture.assert_not_called()
    assert list(outside.iterdir()) == []


def test_exclusive_create_race_never_overwrites_another_owner(tmp_path):
    service = NoteService.__new__(NoteService)
    service.artifact_service = TaskArtifactService(tmp_path)
    marker = tmp_path / "racing" / "recording_owner"

    def competing_create(path, flags, mode):
        assert path == marker
        marker.write_text("other")
        raise FileExistsError()

    with patch("app.services.task_model_source.os.open", side_effect=competing_create), patch(
        "app.services.task_model_source.capture_source"
    ) as capture:
        with pytest.raises(HTTPException) as caught:
            service.generate("https://example.invalid/source", "racing", user_id="owner")
        assert caught.value.status_code == 404
        capture.assert_not_called()
    assert marker.read_text() == "other"


def test_missing_authenticated_owner_is_not_invented_on_capture_failure(tmp_path):
    service = NoteService.__new__(NoteService)
    service.artifact_service = TaskArtifactService(tmp_path)
    with patch("app.services.task_model_source.capture_source", side_effect=HTTPException(401, "synthetic denied")):
        with pytest.raises(HTTPException) as caught:
            service.generate("https://example.invalid/source", "anonymous")
        assert caught.value.status_code == 401
    assert not (tmp_path / "anonymous" / "recording_owner").exists()
