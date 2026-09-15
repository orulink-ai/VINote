import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.services.vilab_cloud_service import VILabCloudService
from app.transcribers.vilab_transcriber import VILabTranscriber
from app.llm.vilab_llm import VILabLLM


def test_generation_requires_resolved_models(monkeypatch):
    service = VILabCloudService()
    monkeypatch.setattr(service, "status", lambda uid: {
        "configured": True, "mode": "cloud", "llm_model": "old", "asr_model": "asr",
    })
    monkeypatch.setattr(service, "defaults", lambda uid: {"llm_model": "new", "asr_model": "asr"})
    service.validate_ready("user")
    monkeypatch.setattr(service, "defaults", lambda uid: {"llm_model": "", "asr_model": "asr"})
    with pytest.raises(ValueError, match="当前模型未配置"):
        service.validate_ready("user")


def test_stt_native_contract_and_whole_file_timing(monkeypatch, tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    def post(url, **kwargs):
        assert url == "http://vilab.test/v1/asr/transcriptions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert kwargs["data"]["model"] == "asr-model"
        assert kwargs["files"]["file"][1].read() == b"audio"
        return httpx.Response(200, json={"text": "会议内容", "language": "zh"})
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.transcribers.vilab_transcriber.subprocess.check_output", lambda *a, **k: "12.5")
    result = VILabTranscriber("http://vilab.test", "test-key", "asr-model")._transcribe_normalized(str(path))
    assert result.full_text == "会议内容"
    assert result.segments[0].end == 12.5
    assert result.metadata["timestamp_granularity"] == "file"


def test_stt_error_does_not_echo_upstream_secret(monkeypatch, tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    monkeypatch.setattr("app.transcribers.vilab_transcriber.subprocess.check_output", lambda *a, **k: "12.5")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(401, text="secret-value"))
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        VILabTranscriber("http://vilab.test", "secret-value")._transcribe_normalized(str(path))
    assert "secret-value" not in str(error.value)


def test_llm_uses_vilab_chat_gateway_for_summarization(monkeypatch):
    def request(self, user_id, method, path, **kwargs):
        assert user_id == "user-1"
        assert path == "/openai/v1/chat/completions"
        assert kwargs["json"]["model"] == "server-llm"
        assert kwargs["json"]["messages"][0]["content"].startswith("summarize")
        assert kwargs["json"]["messages"][1] == {"role": "user", "content": "notes"}
        return {"choices": [{"message": {"content": "# Summary"}}]}
    monkeypatch.setattr(VILabCloudService, "request", request)
    assert VILabLLM("user-1", "server-llm")._complete(system_prompt="summarize", user_prompt="notes") == "# Summary"


def test_cloud_auth_stays_on_backend(monkeypatch):
    monkeypatch.setattr(settings, "cloud_auth_url", "")
    monkeypatch.setattr(settings, "vilab_server_url", "http://vilab.test")
    monkeypatch.setattr(settings, "vilab_api_key", "deployment-key")
    def request(method, url, **kwargs):
        assert url == "http://vilab.test/v1/models"
        assert kwargs["headers"] == {"Authorization": "Bearer deployment-key"}
        return httpx.Response(401, text="deployment-key")
    monkeypatch.setattr(httpx, "request", request)
    with pytest.raises(HTTPException) as error:
        VILabCloudService().models("user-1")
    assert error.value.status_code == 502
    assert "deployment-key" not in error.value.detail


def test_local_mode_does_not_call_cloud(monkeypatch):
    from app.services import vilab_cloud_service as module
    row = SimpleNamespace(mode="cloud", asr_model="asr", llm_model="llm")
    @contextmanager
    def session():
        yield SimpleNamespace(get=lambda model, uid: row)
    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(httpx, "request", lambda *a, **k: pytest.fail("local switch must not call cloud"))
    status = VILabCloudService().select("user-1", "local", "", "")
    assert status["mode"] == "local"
    assert row.asr_model == "asr"


def test_cloud_model_selection_rejects_wrong_type(monkeypatch):
    service = VILabCloudService()
    monkeypatch.setattr(service, "models", lambda uid: [{"id": "asr-only", "modelType": "asr"}])
    with pytest.raises(HTTPException) as error:
        service.select("user-1", "cloud", "", "asr-only")
    assert error.value.status_code == 400


def test_global_cloud_mode_overrides_stale_local_profile_ids(monkeypatch):
    from app.services.llm_service import LLMService
    from app.services.stt_profile_service import STTProfileService
    monkeypatch.setattr(VILabCloudService, "status", lambda self, uid: {
        "mode": "cloud", "asr_model": "cloud-asr", "llm_model": "cloud-llm",
    })
    llm = LLMService().create_summarizer(user_id="user-1", model_profile_id="old-local-profile",
        model_name="old-model", api_key="old-key", base_url="http://old.test")
    assert isinstance(llm, VILabLLM)
    assert llm.model == "cloud-llm"
    stt = STTProfileService().resolve_config(user_id="user-1", stt_profile_id="old-stt")
    assert stt.provider == "vliab-server"
    assert stt.model_name == "cloud-asr"
    assert stt.cloud_user_id == "user-1"


def test_cloud_mode_without_selection_does_not_fallback(monkeypatch):
    from app.services.llm_service import LLMService
    from app.services.stt_profile_service import STTProfileService
    monkeypatch.setattr(VILabCloudService, "status", lambda self, uid: {
        "mode": "cloud", "asr_model": "", "llm_model": "",
    })
    with pytest.raises(ValueError, match="云端模式"):
        LLMService().create_summarizer(user_id="user-1", model_profile_id="local-profile",
            model_name=None, api_key=None, base_url=None)
    with pytest.raises(HTTPException, match="云端模式"):
        STTProfileService().resolve_config(user_id="user-1", stt_profile_id="local-stt")


def test_running_task_keeps_mode_until_next_task(monkeypatch):
    from app.services import vilab_cloud_service as module
    row = SimpleNamespace(mode="cloud", asr_model="asr", llm_model="llm")
    @contextmanager
    def session():
        yield SimpleNamespace(get=lambda model, uid: row)
    monkeypatch.setattr(module, "session_scope", session)
    service = VILabCloudService()
    monkeypatch.setattr(service, "request", lambda *a, **k: {"llm_model": "server-current", "asr_model": "server-asr"})
    monkeypatch.setattr(service, "models", lambda uid: [
        {"id": "llm", "modelType": "llm", "runtimeStatus": "available"},
        {"id": "asr", "modelType": "asr", "runtimeStatus": "available"},
    ])
    with service.task_snapshot("user-1"):
        row.mode = "local"
        assert service.status("user-1")["mode"] == "cloud"
        row.llm_model = "changed-after-start"
        assert service.status("user-1")["llm_model"] == "llm"
    assert service.status("user-1")["mode"] == "local"


def test_model_preferences_are_resolved_per_user(monkeypatch):
    service = VILabCloudService()
    monkeypatch.setattr(service, "status", lambda uid: {
        "asr_model": "", "llm_model": "chosen" if uid == "user-a" else "",
    })
    monkeypatch.setattr(service, "request", lambda *a, **k: {
        "asr_model": "default-asr", "llm_model": "default-llm",
    })
    monkeypatch.setattr(service, "models", lambda uid: [
        {"id": "chosen", "modelType": "llm", "runtimeStatus": "available"},
    ])
    assert service.defaults("user-a") == {"asr_model": "default-asr", "llm_model": "chosen"}
    assert service.defaults("user-b")["llm_model"] == "default-llm"


@pytest.mark.parametrize("runtime_status", ["unavailable", "loading", ""])
def test_unavailable_selection_fails_before_generation(monkeypatch, runtime_status):
    service = VILabCloudService()
    monkeypatch.setattr(service, "status", lambda uid: {"llm_model": "chosen"})
    monkeypatch.setattr(service, "request", lambda *a, **k: {"llm_model": "default"})
    monkeypatch.setattr(service, "models", lambda uid: [
        {"id": "chosen", "modelType": "llm", "runtimeStatus": runtime_status},
    ])
    with pytest.raises(HTTPException, match="不可用"):
        service.defaults("user-a")
    with pytest.raises(HTTPException, match="不可用"):
        service.select("user-a", "cloud", "", "chosen")
