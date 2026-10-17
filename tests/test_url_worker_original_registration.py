"""Exercise the actual URL worker and pipeline, never hand-write request.json."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import BackgroundTasks, HTTPException
import pytest
from starlette.requests import Request

from app.config import settings
from app.downloaders.ytdlp_downloader import YtdlpDownloader
from app.models.note import NoteRequest
from app.routers import note
from app.services import bilibili_source_service as bili
from app.services import task_model_source as models
from app.services import vilab_cloud_service as gateway
from app.services.note_service import NoteService
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_original_service import TaskOriginalService
from test_bilibili_device_download import BYTES, LLM, Transcriber

URL = "https://www.bilibili.com/video/BV18tAnzvE9J?p=1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "downloaded")
    monkeypatch.setattr(settings, "vilab_server_url", "https://model-fixture.test")
    preferences = {"mode": "cloud", "configured": True, "server_url": settings.vilab_server_url,
                   "asr_model": "chosen-asr", "llm_model": "chosen-llm"}

    def status(self, owner):
        current = gateway._task_source.get()
        if current and current[0] == owner:
            return {**current[1], "configured": True}
        return dict(preferences)

    monkeypatch.setattr(gateway.VILabCloudService, "status", status)
    catalog = Mock(return_value=[{"id": "chosen-asr", "modelType": "asr", "runtimeStatus": "available"},
                                 {"id": "chosen-llm", "modelType": "llm", "runtimeStatus": "available"}])
    monkeypatch.setattr(gateway.VILabCloudService, "models", catalog)
    forbidden = Mock(side_effect=AssertionError("no generic/network/model implementation allowed"))
    monkeypatch.setattr(gateway.VILabCloudService, "request", forbidden)
    monkeypatch.setattr("app.downloaders.ytdlp_downloader.yt_dlp.YoutubeDL", forbidden)
    monkeypatch.setattr("app.downloaders.ytdlp_downloader.subprocess.run", forbidden)
    source = bili.BilibiliSource(URL, "来源标题", "BV18tAnzvE9J_p1", 41,
                                "https://upos-fixture.bilivideo.com/audio?ephemeral-signed", 1, 123, 456)
    resolve = Mock(return_value=source)
    monkeypatch.setattr(bili, "resolve", resolve)
    events = []
    downloads = []
    artifacts = TaskArtifactService(settings.output_dir)

    def download(item, target, max_bytes=bili.MAX_AUDIO_BYTES):
        # These files must be produced by the real worker before downloading.
        folders = list(artifacts.output_dir.iterdir())
        assert len(folders) == 1
        folder = folders[0]
        assert (folder / models.SNAPSHOT_FILE).is_file()
        saved = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        assert saved["kind"] == "media_url"
        assert saved["request"]["video_url"] == URL
        events.append("download")
        target.write_bytes(BYTES)
        downloads.append(target)
        return target

    downloaded = Mock(side_effect=download)
    monkeypatch.setattr(bili, "download_audio", downloaded)
    transcriber = Transcriber()
    original_transcribe = transcriber.transcribe
    checks = []

    def transcribe(**kwargs):
        # The first ASR entry already has an owner-bound, independently listed
        # original. No saved-note fallback or manually created request is used.
        items = TaskOriginalService().list("device-user")
        assert len(items) == 1
        task_id = items[0]["task_id"]
        info, path = TaskOriginalService().get("device-user", "task:" + task_id)
        assert path.read_bytes() == BYTES and path == Path(kwargs["audio_path"])
        assert TaskOriginalService().list("foreign") == []
        checks.append(info)
        events.append("asr")
        return original_transcribe(**kwargs)

    transcriber.transcribe = transcribe
    llm = LLM()
    service = NoteService(downloader=YtdlpDownloader(), transcription_service=transcriber,
                          llm_service=llm, artifact_service=artifacts,
                          screenshot_service=SimpleNamespace(prepare_local_video=forbidden, inject_screenshots=forbidden),
                          media_service=SimpleNamespace(enrich_markdown=forbidden))
    monkeypatch.setattr(note, "_note_service", service)
    return SimpleNamespace(artifacts=artifacts, service=service, transcriber=transcriber,
        llm=llm, catalog=catalog, resolve=resolve, download=downloaded, forbidden=forbidden,
        checks=checks, events=events, downloads=downloads)


def queue(env, workflow="note_organization", **changes):
    body = NoteRequest(video_url=URL, workflow=workflow, model_name="chosen-llm", asr_model="chosen-asr",
                       api_key="fixture-private-key", base_url="https://private-fixture.test", **changes)
    background = BackgroundTasks()
    request = Request({"type": "http", "method": "POST", "path": "/api/generate", "headers": []})
    response = note.generate_note_async(body, background, request, user=SimpleNamespace(user_id="device-user"))
    assert len(background.tasks) == 1
    assert background.tasks[0].func is note._run_task
    return response, background.tasks[0]


@pytest.mark.parametrize("workflow", ["note_organization", "meeting"])
def test_new_worker_freezes_then_persists_then_registers_before_real_mock_pipeline(env, workflow):
    response, worker = queue(env, workflow)
    initial = env.artifacts.find_task_dir(response["task_id"])
    assert not (initial / "request.json").exists() and not (initial / models.SNAPSHOT_FILE).exists()
    worker.func(**worker.kwargs)
    folder = env.artifacts.find_task_dir(response["task_id"])
    assert json.loads((folder / "status.json").read_text(encoding="utf-8"))["status"] == "success"
    saved = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "media_url" and saved["request"]["workflow"] == workflow
    assert not {"api_key", "base_url", "model_name"} & set(saved["request"])
    assert "fixture-private" not in json.dumps(saved) and "private-fixture" not in json.dumps(saved)
    assert "title" not in saved["request"]  # NoteRequest has no invented title.
    index = json.loads((folder / "source_original.json").read_text(encoding="utf-8"))
    assert index["owner"] == "device-user" and index["task_id"] == response["task_id"]
    assert index["workflow"] == workflow and index["filename"] == "来源标题.m4a"
    exported, _ = TaskOriginalService().get("device-user", "task:" + response["task_id"])
    assert exported["filename"] == "来源标题.m4a"
    assert env.events == ["download", "asr"] and len(env.llm.calls) == 1
    assert env.artifacts.resolve_source_media(folder).read_bytes() == BYTES
    assert env.downloads[0].read_bytes() == BYTES
    assert env.artifacts.get_result(response["task_id"])["video_id"] == "BV18tAnzvE9J_p1"
    env.forbidden.assert_not_called()


def test_catalog_failure_sets_failed_without_request_original_or_asr(env):
    response, worker = queue(env)
    env.catalog.side_effect = HTTPException(503, "fixture unavailable")
    worker.func(**worker.kwargs)
    folder = env.artifacts.find_task_dir(response["task_id"])
    raw = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    assert raw["status"] == "failed" and raw["retryable"] is False
    assert not (folder / "request.json").exists() and not (folder / "source_original.json").exists()
    assert not env.transcriber.paths and not env.llm.calls
    env.resolve.assert_not_called()
    env.forbidden.assert_not_called()


def test_ready_failure_after_snapshot_still_precedes_typed_request(env, monkeypatch):
    response, worker = queue(env)
    monkeypatch.setattr(gateway.VILabCloudService, "validate_ready", Mock(side_effect=ValueError("not ready")))
    worker.func(**worker.kwargs)
    folder = env.artifacts.find_task_dir(response["task_id"])
    assert (folder / models.SNAPSHOT_FILE).exists()
    assert not (folder / "request.json").exists()
    assert json.loads((folder / "status.json").read_text(encoding="utf-8"))["status"] == "failed"
    env.resolve.assert_not_called()
    assert not env.transcriber.paths


def test_original_index_survives_asr_failure_without_saved_note(env):
    response, worker = queue(env)
    env.transcriber.transcribe = Mock(side_effect=RuntimeError("synthetic ASR failure"))
    worker.func(**worker.kwargs)
    folder = env.artifacts.find_task_dir(response["task_id"])
    assert (folder / "source_original.json").exists()
    assert TaskOriginalService().get("device-user", "task:" + response["task_id"])[1].read_bytes() == BYTES
    assert env.artifacts.get_result(response["task_id"]) is None
    assert json.loads((folder / "status.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert not env.llm.calls


@pytest.mark.parametrize("status", ["success", "failed", "transcribing"])
def test_historical_task_without_request_is_not_migrated_or_replayed(env, status):
    task_id = "00000000-0000-4000-8000-000000000099"
    folder = env.artifacts.create_task_dir(task_id)
    (folder / "recording_owner").write_text("device-user", encoding="utf-8")
    env.artifacts.update_status(folder, status, "historical evidence")
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    note._run_task(task_id, NoteRequest(video_url=URL), "device-user")
    assert before == {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    env.catalog.assert_not_called()
    env.resolve.assert_not_called()
    assert not env.transcriber.paths and not env.llm.calls
