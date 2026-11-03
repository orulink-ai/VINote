import json
import wave

import httpx
import pytest

from app.config import settings
from app.services.adaptive_asr_policy import RecordingModelPolicy
from app.services.asr_stream_service import ASRServiceError
from app.transcribers.vilab_transcriber import VILabTranscriber

CAPABILITIES = {
    "useCases": ["meeting"], "protocols": ["asr-recording"], "audioDelivery": "public",
    "audioFormats": ["wav"], "maxAudioSeconds": 7200, "maxAudioBytes": 512 * 1024 * 1024,
    "speakerDiarization": True, "utteranceTimestamps": True,
    "recordedAudio": {"protocol": 1, "supported": True, "strategy": "single_request",
                      "policySource": "provider_model"},
}

RESULT = {
    "text": "会议内容",
    "language": "zh",
    "segments": [
        {"start": 0.0, "end": 4.0, "text": "会议内容", "speakerId": "1", "speakerLabel": "发言人 1"},
        {"start": 4.0, "end": 9.0, "text": "下一步", "speakerId": "2", "speakerLabel": "发言人 2"},
    ],
}


@pytest.fixture
def audio(tmp_path, monkeypatch):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        target.writeframes(b"\0\0" * 16000)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr("app.transcribers.vilab_transcriber.subprocess.check_output", lambda *a, **k: "9.0")
    monkeypatch.setattr("app.transcribers.vilab_transcriber.time.sleep", lambda seconds: None)
    return path


def adapter():
    return VILabTranscriber("http://vilab.test", "test-key", "asr-model", cloud_user_id="owner")


def policy():
    return RecordingModelPolicy.from_capabilities(CAPABILITIES)


def checkpoint_path(audio):
    return next((settings.data_dir / "asr-recording-checkpoints").glob("*/meeting.json"))


def test_creates_job_polls_and_persists_result(monkeypatch, audio):
    posts, polls = [], []
    statuses = ["queued", "submitting", "processing", "completed"]

    def post(url, **kwargs):
        posts.append((url, kwargs))
        job_id = kwargs["headers"]["Idempotency-Key"]
        return httpx.Response(202, json={"id": job_id, "status": "queued"})

    def get(url, **kwargs):
        polls.append(url)
        if url.endswith("/result"):
            return httpx.Response(200, json=RESULT)
        status = statuses[min(len(polls) - 1, len(statuses) - 1)]
        return httpx.Response(200, json={"id": url.rsplit("/", 1)[-1], "status": status})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    result = adapter()._transcribe_recording(str(audio), "test-key", policy())

    assert result.full_text == "会议内容"
    assert [segment.speaker_id for segment in result.segments] == ["1", "2"]
    assert len(posts) == 1
    url, kwargs = posts[0]
    assert url == "http://vilab.test/v1/asr/transcription-jobs"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["data"] == {"mode": "meeting", "model": "asr-model"}
    assert kwargs["timeout"].read == 120
    assert polls[0] == "http://vilab.test/v1/asr/transcription-jobs/" + kwargs["headers"]["Idempotency-Key"]
    saved = json.loads(checkpoint_path(audio).read_text(encoding="utf-8"))
    assert saved["version"] == 2 and saved["status"] == "completed"
    assert saved["result"]["full_text"] == "会议内容"


def test_completed_checkpoint_never_posts_again(monkeypatch, audio):
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(
        202, json={"id": kwargs["headers"]["Idempotency-Key"], "status": "completed"}))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json=RESULT))
    first = adapter()._transcribe_recording(str(audio), "test-key", policy())
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("completed work must not resubmit"))
    again = adapter()._transcribe_recording(str(audio), "test-key", policy())
    assert again.full_text == first.full_text == "会议内容"


def test_lost_create_response_reuses_same_idempotency_key(monkeypatch, audio):
    keys = []

    def lost(url, **kwargs):
        keys.append(kwargs["headers"]["Idempotency-Key"])
        raise httpx.ReadTimeout("lost")

    monkeypatch.setattr(httpx, "post", lost)
    with pytest.raises(ASRServiceError) as error:
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    assert error.value.code == "unknown_result"
    saved = json.loads(checkpoint_path(audio).read_text(encoding="utf-8"))
    assert saved["status"] == "created"

    def replay(url, **kwargs):
        keys.append(kwargs["headers"]["Idempotency-Key"])
        return httpx.Response(200, json={"id": kwargs["headers"]["Idempotency-Key"],
                                         "status": "completed", "deduplicated": True})

    monkeypatch.setattr(httpx, "post", replay)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json=RESULT))
    assert adapter()._transcribe_recording(str(audio), "test-key", policy()).full_text == "会议内容"
    assert len(keys) == 2 and keys[0] == keys[1]


def test_failed_job_is_terminal(monkeypatch, audio):
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(
        202, json={"id": kwargs["headers"]["Idempotency-Key"], "status": "queued"}))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json={
        "status": "failed", "error": {"code": "asr_provider_error", "message": "rejected"}}))
    with pytest.raises(ASRServiceError) as error:
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    assert error.value.code == "asr_provider_error"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("failed work must not resubmit"))
    with pytest.raises(ASRServiceError):
        adapter()._transcribe_recording(str(audio), "test-key", policy())


def test_empty_result_stays_no_speech_without_replay(monkeypatch, audio):
    from app.models.transcript import NoSpeechDetectedError

    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(
        202, json={"id": kwargs["headers"]["Idempotency-Key"], "status": "queued"}))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json={
        "status": "failed", "error": {"code": "empty_result_unverified", "message": "empty"}}))
    with pytest.raises(NoSpeechDetectedError):
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("empty work must not resubmit"))
    with pytest.raises(NoSpeechDetectedError):
        adapter()._transcribe_recording(str(audio), "test-key", policy())


def test_outcome_unknown_keeps_job_for_manual_recovery(monkeypatch, audio):
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(
        202, json={"id": kwargs["headers"]["Idempotency-Key"], "status": "processing"}))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json={
        "status": "outcome_unknown"}))
    with pytest.raises(ASRServiceError) as error:
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    assert error.value.code == "unknown_result"
    saved = json.loads(checkpoint_path(audio).read_text(encoding="utf-8"))
    assert saved["status"] == "outcome_unknown" and saved["job_id"]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("unknown work must not resubmit"))
    with pytest.raises(ASRServiceError):
        adapter()._transcribe_recording(str(audio), "test-key", policy())


def test_legacy_inflight_marker_without_job_id_is_unknown(monkeypatch, audio):
    def lost(url, **kwargs):
        raise httpx.ConnectError("lost")

    monkeypatch.setattr(httpx, "post", lost)
    # Create the checkpoint location, then downgrade it to the old format.
    with pytest.raises(ASRServiceError):
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    path = checkpoint_path(audio)
    path.write_text(json.dumps({"version": 1, "status": "inflight", "model": "asr-model"}), encoding="utf-8")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("legacy inflight must not resubmit"))
    with pytest.raises(ASRServiceError) as error:
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    assert error.value.code == "unknown_result"


def test_audio_delivery_unavailable_clears_marker(monkeypatch, audio):
    from fastapi import HTTPException

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(503, json={
        "error": {"code": "meeting_audio_delivery_unavailable", "message": "no public audio"}}))
    with pytest.raises(HTTPException) as error:
        adapter()._transcribe_recording(str(audio), "test-key", policy())
    assert error.value.status_code == 503
    assert not list((settings.data_dir / "asr-recording-checkpoints").glob("*/meeting.json"))

