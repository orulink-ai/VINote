from unittest.mock import patch

import pytest


@pytest.mark.parametrize("code,count", [("asr_timeout", 3), ("asr_stream_failed", 3),
    ("rate_limited", 3), ("asr_failed", 1), ("unknown_result", 1),
    ("auth_failed", 1), ("quota_exceeded", 1), ("asr_protocol_error", 1)])
def test_safe_service_classification_bounds_same_model_retries(code, count):
    from app.services.asr_stream_service import ASRServiceError
    adapter = VILabTranscriber("https://example.test", "test", "selected")
    failure = ASRServiceError(code, session_id="56bb63c8-e013-4444-92cc-7d4f211a5e78")
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ) as sleep, patch.object(adapter, "_transcribe_normalized", side_effect=failure) as request:
        with pytest.raises(ASRServiceError):
            adapter.transcribe("sample.wav")
    assert request.call_count == count
    assert sleep.call_count == count - 1
    assert adapter.model == "selected"
    assert all(call == request.call_args_list[0] for call in request.call_args_list)
    assert len(failure.asr_metadata["asr_attempts"]) == count
    assert failure.asr_metadata["asr_attempts"][-1]["diagnostic"]["code"] == code
from fastapi import HTTPException

from app.models.transcript import TranscriptResult
from app.transcribers.vilab_transcriber import VILabTranscriber

ALIYUN = "asr:6:aliyun:22:paraformer-realtime-v2"
VOLCENGINE = "asr:14:volcengine-asr:8:bigmodel"


@pytest.mark.parametrize("primary", [ALIYUN, VOLCENGINE])
@pytest.mark.parametrize("failure", [
    HTTPException(502, f"云端模型请求失败（HTTP {code}）") for code in (429, 502, 503, 504)
] + [RuntimeError("VILab STT connection failed or timed out")])
def test_transient_error_retries_selected_model_and_records_it(primary, failure):
    adapter = VILabTranscriber("https://example.test", "", primary, cloud_user_id="owner")
    expected = TranscriptResult(None, "真实发言", [])
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ), patch.object(adapter, "_transcribe_normalized", side_effect=[failure, expected]) as request:
        result = adapter.transcribe("sample.wav")
    assert request.call_count == 2
    assert request.call_args_list[0] == request.call_args_list[1]
    assert result.metadata["model"] == primary
    assert result.metadata["requested_model"] == primary
    assert result.metadata["asr_attempts"][0]["status"] == "failed"
    assert result.metadata["asr_attempts"][1]["status"] == "success"
    assert adapter.model == primary
    assert adapter.max_request_duration_seconds is None


@pytest.mark.parametrize("failure", [
    HTTPException(401, "expired"), HTTPException(403, "denied"),
    HTTPException(502, "云端服务未接受当前身份，请检查账号登录及服务端可信身份来源配置"),
    HTTPException(503, "云端账号认证服务暂时不可用（HTTP 503），请稍后重试"),
    RuntimeError("malformed response HTTP 502"), RuntimeError("unknown"),
])
def test_auth_and_unknown_errors_never_retry(failure):
    adapter = VILabTranscriber("https://example.test", "", ALIYUN, cloud_user_id="owner")
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ) as sleep, patch.object(adapter, "_transcribe_normalized", side_effect=failure) as request:
        with pytest.raises(type(failure)):
            adapter.transcribe("sample.wav")
    assert request.call_count == 1
    sleep.assert_not_called()


def test_repeated_gateway_failure_stays_on_selected_model():
    adapter = VILabTranscriber("https://example.test", "", ALIYUN, cloud_user_id="owner")
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ), patch.object(adapter, "_transcribe_normalized", side_effect=RuntimeError("VILab STT returned HTTP 502")) as request:
        with pytest.raises(RuntimeError):
            adapter.transcribe("sample.wav")
    assert request.call_count == 3
    assert all(not call.kwargs for call in request.call_args_list)


@pytest.mark.parametrize("model", [ALIYUN, VOLCENGINE, "asr:new-provider:arbitrary-model"])
def test_model_name_does_not_impose_short_duration_limit(model):
    adapter = VILabTranscriber("https://example.test", "", model)
    assert adapter.max_request_duration_seconds is None


def test_actual_connect_error_retries_same_model_and_wav_bytes(tmp_path):
    import httpx
    import wave
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    adapter = VILabTranscriber("https://example.test", "test", VOLCENGINE)
    uploads = []
    def recognize(origin, bearer, model, wav_path, **kwargs):
        uploads.append((model, __import__('pathlib').Path(wav_path).read_bytes()))
        if len(uploads) == 1:
            raise httpx.ConnectError("connection failed")
        return {"text": "真实发言"}
    def normalize(command, **kwargs):
        from pathlib import Path
        Path(command[-1]).write_bytes(path.read_bytes())
    with patch("app.config.settings.data_dir", str(tmp_path)), patch(
        "app.transcribers.vilab_transcriber.subprocess.run", side_effect=normalize
    ), patch("app.transcribers.vilab_transcriber.time.sleep"), patch(
        "app.services.asr_stream_service.recognize_pcm", side_effect=recognize
    ):
        result = adapter.transcribe(str(path))
    assert uploads == [(VOLCENGINE, path.read_bytes())] * 2
    assert result.metadata["model"] == VOLCENGINE


@pytest.mark.parametrize("status,message", [
    (502, "Aliyun ASR returned an empty transcript."),
    (502, "Volcengine ASR returned an empty transcript."),
    (503, "Account authentication is temporarily unavailable"),
])
def test_direct_no_speech_or_auth_service_outage_never_switches(tmp_path, status, message):
    import httpx
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    adapter = VILabTranscriber("https://example.test", "", ALIYUN)
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.subprocess.check_output", return_value="12"
    ), patch("app.transcribers.vilab_transcriber.tempfile.TemporaryDirectory") as folder, patch(
        "app.transcribers.vilab_transcriber.httpx.post", return_value=httpx.Response(status, json={"error": {"message": message}})
    ) as post, patch("app.transcribers.vilab_transcriber.httpx.get") as catalog:
        folder.return_value.__enter__.return_value = str(tmp_path)
        with pytest.raises((RuntimeError, HTTPException)):
            adapter._transcribe_http(str(path))
    assert post.call_count == 1
    catalog.assert_not_called()


def test_transient_gateway_failure_retries_same_normalized_audio():
    adapter = VILabTranscriber("http://localhost", "test")
    expected = TranscriptResult(None, "测试", [])
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ), patch.object(adapter, "_transcribe_normalized", side_effect=[
        HTTPException(502, "云端模型请求失败（HTTP 502）"), expected
    ]) as request:
        assert adapter.transcribe("sample.wav") is expected
        assert request.call_count == 2
        assert request.call_args_list[0] == request.call_args_list[1]


@pytest.mark.parametrize("detail,count", [
    ("云端模型请求失败（HTTP 503）", 3),
    ("无法连接云端模型服务，请稍后重试", 3),
    ("VILab STT connection failed or timed out", 3),
    ("云端服务未接受当前身份", 1),
])
def test_retries_are_bounded_and_do_not_hide_authentication_failure(detail, count):
    adapter = VILabTranscriber("http://localhost", "test")
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ), patch.object(adapter, "_transcribe_normalized", side_effect=HTTPException(502, detail)) as request:
        with pytest.raises(HTTPException):
            adapter.transcribe("sample.wav")
        assert request.call_count == count


@pytest.mark.parametrize("duration,deadline", [(5, 90), (55, 142.5), (60, 150)])
def test_streaming_read_deadline_has_headroom_without_ten_minute_stall(tmp_path, duration, deadline):
    normalized = tmp_path / "audio.wav"
    normalized.write_bytes(b"bounded-test")
    adapter = VILabTranscriber("https://example.test", "", cloud_user_id="owner")
    expected = TranscriptResult(None, "测试", [])
    with patch("app.transcribers.vilab_transcriber.subprocess.check_output", return_value=str(duration)), patch(
        "app.services.vilab_cloud_service.VILabCloudService.request", return_value={}
    ) as request, patch.object(adapter, "_result", return_value=expected):
        assert adapter._transcribe_http(str(normalized)) is expected
    timeout = request.call_args.kwargs["timeout"]
    assert timeout.read == deadline
    assert timeout.connect == 10
    assert timeout.read > duration


@pytest.fixture(autouse=True)
def declared_recording_budget(monkeypatch):
    # Transport regressions use an explicit service contract; never query a real catalog.
    from app.services.adaptive_asr_policy import RecordedAudioPolicy
    monkeypatch.setattr(VILabTranscriber, "_recorded_audio_policy",
                        lambda self, bearer: RecordedAudioPolicy(2097152))
