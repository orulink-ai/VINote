from unittest.mock import patch
import json
import httpx

import pytest

from app.services.adaptive_asr_policy import RecordedAudioPolicy
from app.services.asr_stream_service import ASRServiceError
from app.transcribers.vilab_transcriber import VILabTranscriber
from tests.test_adaptive_asr_policy import write_wav


def test_final_intervals_reused_without_second_cloud_call(tmp_path):
    path = write_wav(tmp_path / "source.wav", seconds=3)
    adapter = VILabTranscriber("https://unused.test", "unused", "unchanged")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch.object(
        adapter, "_recorded_audio_policy", return_value=RecordedAudioPolicy(32000)
    ) as policy, patch("app.services.asr_stream_service.recognize_pcm",
                      return_value={"text": "confirmed"}) as recognize:
        result = adapter._transcribe_stream(str(path))
        count = recognize.call_count
        assert count > 1
        assert adapter._transcribe_stream(str(path)).full_text == result.full_text
        assert recognize.call_count == count
        assert policy.call_count == 1
        assert all(call.args[2] == "unchanged" for call in recognize.call_args_list)
    checkpoint = json.loads(next(tmp_path.glob("asr-stream-checkpoints/*/recognition.json")).read_text())
    assert "inflight" not in checkpoint
    assert checkpoint["completed"][-1]["end"] == 3


def test_unknown_interval_never_replays_and_retains_completed_parts(tmp_path):
    path = write_wav(tmp_path / "source.wav", seconds=3)
    adapter = VILabTranscriber("https://unused.test", "unused", "unchanged")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch.object(
        adapter, "_recorded_audio_policy", return_value=RecordedAudioPolicy(32000)
    ), patch("app.services.asr_stream_service.recognize_pcm", side_effect=[
        {"text": "confirmed"}, ASRServiceError("asr_provider_error")]) as recognize:
        with pytest.raises(ASRServiceError):
            adapter._transcribe_stream(str(path))
        with pytest.raises(ASRServiceError, match="最终识别结果"):
            adapter._transcribe_stream(str(path))
        assert recognize.call_count == 2
    saved = json.loads(next(tmp_path.glob("asr-stream-checkpoints/*/recognition.json")).read_text())
    assert len(saved["completed"]) == 1
    assert saved["inflight"]["start_frame"] == round(saved["completed"][0]["end"] * 16000)


def test_bad_catalog_never_starts_recognition(tmp_path):
    path = write_wav(tmp_path / "source.wav", seconds=1)
    adapter = VILabTranscriber("https://unused.test", "unused", "unchanged")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch.object(
        adapter, "_recorded_audio_policy", side_effect=ValueError("policy unavailable")
    ), patch("app.services.asr_stream_service.recognize_pcm") as recognize:
        with pytest.raises(ValueError):
            adapter._transcribe_stream(str(path))
        recognize.assert_not_called()


def test_checkpoint_flush_failure_never_submits_audio(tmp_path):
    path = write_wav(tmp_path / "source.wav", seconds=1)
    adapter = VILabTranscriber("https://unused.test", "unused", "unchanged")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch.object(
        adapter, "_recorded_audio_policy", return_value=RecordedAudioPolicy(32000)
    ), patch("app.transcribers.vilab_transcriber.os.fsync", side_effect=OSError("disk failure")), patch(
        "app.services.asr_stream_service.recognize_pcm"
    ) as recognize:
        with pytest.raises(OSError, match="disk failure"):
            adapter._transcribe_stream(str(path))
        recognize.assert_not_called()


def test_policy_catalog_uses_exact_selected_model_not_default():
    policy = {"recordedAudio": {"protocol": 1, "supported": True,
        "strategy": "adaptive_pause", "maxSessionAudioBytes": 98304,
        "policySource": "service_budget"}}
    adapter = VILabTranscriber("https://unused.test", "unused", "selected")
    response = httpx.Response(200, request=httpx.Request("GET", "https://unused.test/v1/models"),
        json={"data": [{"id": "other", "modelType": "asr", "capabilities": {}},
                       {"id": "selected", "modelType": "asr", "capabilities": policy}]})
    with patch("app.transcribers.vilab_transcriber.httpx.get", return_value=response) as catalog:
        assert adapter._recorded_audio_policy("test-bearer").max_session_audio_bytes == 98304
    assert catalog.call_count == 1
    assert adapter.model == "selected"


def test_old_catalog_is_service_update_error_not_model_incapability():
    adapter = VILabTranscriber("https://unused.test", "unused", "selected")
    response = httpx.Response(200, request=httpx.Request("GET", "https://unused.test/v1/models"),
        json={"data": [{"id": "selected", "modelType": "asr"}]})
    with patch("app.transcribers.vilab_transcriber.httpx.get", return_value=response):
        with pytest.raises(ValueError, match="更新服务"):
            adapter._recorded_audio_policy("test-bearer")
