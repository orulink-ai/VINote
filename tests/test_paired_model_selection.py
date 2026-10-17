"""Explicit ASR+LLM choices freeze once; all catalogs and execution are fake."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.models.note import LocalFileRequest, NoteRequest
from app.routers import note
from app.services import task_model_source as sources
from app.services import vilab_cloud_service as gateway
from app.services.note_service import NoteService
from app.services.task_artifact_service import TaskArtifactService

PAIR = {"asr_model": "explicit-asr", "model_name": "explicit-llm"}


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr(settings, "vilab_server_url", "https://model-fixture.test")
    state = {"mode": "cloud", "server_url": settings.vilab_server_url, "configured": True,
             "asr_model": "original-asr", "llm_model": "original-llm"}
    models = [{"id": name, "modelType": kind, "runtimeStatus": "available"}
              for name, kind in [("explicit-asr", "asr"), ("explicit-llm", "llm"),
                                 ("original-asr", "asr"), ("original-llm", "llm")]]
    catalog = Mock(return_value=models)
    defaults = Mock(side_effect=AssertionError("must not substitute preferences/defaults"))
    writes = Mock(side_effect=AssertionError("must not change global selection"))
    monkeypatch.setattr(gateway.VILabCloudService, "status", lambda *a, **kw: dict(state))
    monkeypatch.setattr(gateway.VILabCloudService, "models", catalog)
    monkeypatch.setattr(gateway.VILabCloudService, "defaults", defaults)
    monkeypatch.setattr(gateway.VILabCloudService, "select", writes)
    return SimpleNamespace(state=state, models=models, catalog=catalog, defaults=defaults, writes=writes)


def test_pair_freezes_catalog_validated_choices_without_preferences_or_defaults(tmp_path, cloud):
    value = sources.ensure_source(tmp_path, "owner", PAIR, allow_capture=True)
    assert value["asr_model"] == PAIR["asr_model"] and value["llm_model"] == PAIR["model_name"]
    assert value["mode"] == "cloud" and value["owner"] == "owner"
    cloud.catalog.assert_called_once_with("owner")
    cloud.defaults.assert_not_called()
    cloud.writes.assert_not_called()
    assert cloud.state["asr_model"] == "original-asr"
    assert cloud.state["llm_model"] == "original-llm"
    assert "api_key" not in (tmp_path / sources.SNAPSHOT_FILE).read_text()


@pytest.mark.parametrize("options", [{"asr_model": "explicit-asr"}, {"asr_model": "", "model_name": "explicit-llm"},
                                    {"asr_model": "explicit-asr", "model_name": ""},
                                    {"asr_model": " explicit-asr", "model_name": "explicit-llm"}])
def test_partial_or_blank_pair_fails_before_catalog_or_snapshot(tmp_path, cloud, options):
    with pytest.raises(HTTPException) as exc:
        sources.ensure_source(tmp_path, "owner", options, allow_capture=True)
    assert exc.value.status_code == 422
    assert not (tmp_path / sources.SNAPSHOT_FILE).exists()
    cloud.catalog.assert_not_called()
    cloud.defaults.assert_not_called()


@pytest.mark.parametrize("case", ["unknown_asr", "unknown_llm", "wrong_type", "unavailable"])
def test_invalid_catalog_selection_never_writes_snapshot_or_falls_back(tmp_path, cloud, case):
    options = dict(PAIR)
    if case == "unknown_asr":
        options["asr_model"] = "missing"
    elif case == "unknown_llm":
        options["model_name"] = "missing"
    elif case == "wrong_type":
        cloud.models[0]["modelType"] = "llm"
    else:
        cloud.models[0]["runtimeStatus"] = "not_available"
    with pytest.raises(HTTPException):
        sources.ensure_source(tmp_path, "owner", options, allow_capture=True)
    assert not (tmp_path / sources.SNAPSHOT_FILE).exists()
    cloud.defaults.assert_not_called()
    cloud.writes.assert_not_called()


def test_pair_local_mode_is_not_an_implicit_switch(tmp_path, cloud):
    cloud.state["mode"] = "local"
    with pytest.raises(HTTPException) as exc:
        sources.ensure_source(tmp_path, "owner", PAIR, allow_capture=True)
    assert exc.value.status_code == 409 and not (tmp_path / sources.SNAPSHOT_FILE).exists()
    assert cloud.state["mode"] == "local"
    cloud.catalog.assert_not_called()
    cloud.writes.assert_not_called()


def test_existing_snapshot_wins_even_if_new_pair_is_invalid_or_mode_changed(tmp_path, cloud):
    first = sources.ensure_source(tmp_path, "owner", PAIR, allow_capture=True)
    raw = (tmp_path / sources.SNAPSHOT_FILE).read_bytes()
    cloud.state["mode"] = "local"
    cloud.catalog.reset_mock()
    assert sources.ensure_source(tmp_path, "owner", {"asr_model": "bad"}, allow_capture=True) == first
    assert (tmp_path / sources.SNAPSHOT_FILE).read_bytes() == raw
    cloud.catalog.assert_not_called()


def test_legacy_model_name_only_keeps_cloud_preferences(tmp_path, cloud):
    value = sources.ensure_source(tmp_path, "owner", {"model_name": "legacy-ignored-in-cloud"}, allow_capture=True)
    assert value["llm_model"] == "original-llm" and value["asr_model"] == "original-asr"
    cloud.catalog.assert_not_called()


def test_legacy_local_model_name_still_resolves_custom_configuration(tmp_path, cloud, monkeypatch):
    from app.models.model_profile import ResolvedLLMConfig
    from app.services.llm_service import LLMService
    from app.services.stt_profile_service import STTProfileService
    cloud.state["mode"] = "local"
    config = ResolvedLLMConfig(provider="openai-compatible", base_url="https://custom-fixture.test",
                               model_name="custom-model", api_key="private-fixture")
    resolve = Mock(return_value=config)
    monkeypatch.setattr(LLMService, "resolve_config", resolve)
    monkeypatch.setattr(STTProfileService, "resolve_config", lambda *a, **k: config)
    value = sources.ensure_source(tmp_path, "owner", {"model_name": "custom-model"}, allow_capture=True)
    assert value["mode"] == "local" and resolve.call_args.kwargs["model_name"] == "custom-model"
    assert "private-fixture" not in (tmp_path / sources.SNAPSHOT_FILE).read_text()
    cloud.catalog.assert_not_called()


def test_explicit_confirmation_retains_authority_over_request_options(tmp_path, cloud, monkeypatch):
    monkeypatch.setattr(gateway.VILabCloudService, "validate_ready", lambda *a, **k: None)
    confirmation = {"confirmed": True, "mode": "cloud", "server_url": settings.vilab_server_url,
                    "asr_model": "original-asr", "llm_model": "original-llm"}
    value = sources.ensure_source(tmp_path, "owner", PAIR, confirmation=confirmation)
    assert value["asr_model"] == "original-asr" and value["llm_model"] == "original-llm"


@pytest.mark.parametrize("model", [NoteRequest, LocalFileRequest])
def test_request_models_retain_pair_and_legacy_absence(model):
    source = {"video_url": "https://www.bilibili.com/video/BV13At46PEGQ"} if model is NoteRequest else {"file_path": "original.wav"}
    assert model(**source, **PAIR).model_dump()["asr_model"] == PAIR["asr_model"]
    assert model(**source).asr_model is None


@pytest.fixture
def router(tmp_path, cloud, monkeypatch):
    artifacts = TaskArtifactService(tmp_path / "output")
    service = object.__new__(NoteService)
    service.artifact_service = artifacts
    service.transcription_service = SimpleNamespace(get_audio_duration=lambda *a: 1)
    captured = []

    def pipeline(**kwargs):
        captured.append(dict(gateway._task_source.get()[1]))
        return SimpleNamespace(audio_meta=SimpleNamespace(title="fixture", duration=1, platform="local", video_id="fixture"),
                               markdown="fixture", summary_mode="default")

    service._run_pipeline = pipeline
    service._download_audio = lambda **kw: SimpleNamespace(title="fixture", duration=1, platform="bilibili")
    monkeypatch.setattr(note, "_note_service", service)
    monkeypatch.setattr(note, "normalize_audio_for_transcription", lambda path: path)
    monkeypatch.setattr(gateway.VILabCloudService, "validate_ready", lambda *a, **kw: None)
    app = FastAPI()
    app.include_router(note.router, prefix="/api")
    app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id="owner")
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b"\0" * 320)
    original = tmp_path / "original.wav"
    original.write_bytes(data.getvalue())
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, captured=captured, artifacts=artifacts,
                               content=data.getvalue(), original=original)


@pytest.mark.parametrize("entry", ["url", "url_sync", "upload", "upload_sync", "file", "file_sync"])
def test_json_and_multipart_selection_reaches_single_snapshot_decision(router, cloud, entry):
    if entry.startswith("url"):
        path = "/api/generate_sync" if entry.endswith("sync") else "/api/generate"
        response = router.client.post(path, json={"video_url": "https://www.bilibili.com/video/BV13At46PEGQ", **PAIR})
    elif entry.startswith("upload"):
        path = "/api/generate_from_upload_sync" if entry.endswith("sync") else "/api/generate_from_upload"
        response = router.client.post(path, data={"source_type": "audio", **PAIR},
                                      files={"file": ("original.wav", router.content, "audio/wav")})
    else:
        path = "/api/generate_from_file_sync" if entry.endswith("sync") else "/api/generate_from_file"
        response = router.client.post(path, json={"file_path": str(router.original), **PAIR})
    assert response.status_code == 200, response.text
    assert len(router.captured) == 1
    assert router.captured[0]["asr_model"] == PAIR["asr_model"]
    assert router.captured[0]["llm_model"] == PAIR["model_name"]
    task = router.artifacts.find_task_dir(response.json()["task_id"])
    saved = json.loads((task / sources.SNAPSHOT_FILE).read_text())
    assert saved["asr_model"] == PAIR["asr_model"] and saved["llm_model"] == PAIR["model_name"]
    cloud.catalog.assert_called_once()
    cloud.defaults.assert_not_called()
    cloud.writes.assert_not_called()


def test_unavailable_upload_pair_rejected_before_media_or_execution(router, cloud):
    cloud.models[0]["runtimeStatus"] = "not_available"
    response = router.client.post("/api/generate_from_upload", data={"source_type": "audio", **PAIR},
                                  files={"file": ("original.wav", router.content, "audio/wav")})
    assert response.status_code != 200
    assert not router.captured
    assert not list(router.artifacts.output_dir.rglob(sources.SNAPSHOT_FILE))
    assert not list(router.artifacts.output_dir.rglob("source_audio.wav"))


@pytest.mark.parametrize("entry", ["/api/generate_from_upload", "/api/generate_from_upload_sync"])
def test_local_upload_rejects_pair_with_explicit_conflict_no_model_or_asr(router, cloud, entry):
    cloud.state["mode"] = "local"
    response = router.client.post(entry, data={"source_type": "audio", **PAIR},
                                  files={"file": ("original.wav", router.content, "audio/wav")})
    assert response.status_code == 409, response.text
    assert not router.captured
    cloud.catalog.assert_not_called()
    cloud.writes.assert_not_called()


def test_no_stt_source_can_freeze_pair_without_dispatching_asr(tmp_path, cloud):
    value = sources.ensure_source(tmp_path, "owner", {**PAIR, "needs_stt": False}, allow_capture=True)
    assert value["needs_stt"] is False and value["asr_model"] == "explicit-asr"
    assert value["llm_model"] == "explicit-llm"
    cloud.catalog.assert_called_once_with("owner")
