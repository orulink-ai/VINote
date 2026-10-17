from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.models.transcript import NoSpeechDetectedError
from app.services.vilab_cloud_service import VILabCloudService


@pytest.fixture
def isolated_preferences(monkeypatch):
    # Transport tests must not read the developer's configured database.
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app.services import vilab_cloud_service

    @contextmanager
    def session():
        yield SimpleNamespace(get=lambda model, user_id: None)

    monkeypatch.setattr(vilab_cloud_service, "session_scope", session)


@pytest.mark.parametrize("message,exception", [
    ("Aliyun ASR returned an empty transcript.", NoSpeechDetectedError),
    ("Volcengine ASR returned an empty transcript.", NoSpeechDetectedError),
    ("Volcengine ASR disconnected before its final result", HTTPException),
    ("ASR upstream unavailable", HTTPException),
])
def test_only_explicit_empty_recognition_is_distinguished(message, exception, isolated_preferences):
    response = httpx.Response(502, json={"error": {"message": message}})
    with patch.object(settings, "cloud_auth_url", ""), patch.object(
        settings, "vilab_server_url", "http://localhost"
    ), patch("app.services.vilab_cloud_service.httpx.request", return_value=response):
        with pytest.raises(exception):
            VILabCloudService().request(None, "POST", "/v1/asr/transcriptions")


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_successful_explicit_empty_recognition_preserves_interval(text):
    from app.services.transcription_service import ChunkSpec, TranscriptionService
    from app.transcribers.vilab_transcriber import VILabTranscriber
    from pathlib import Path

    adapter = VILabTranscriber("http://localhost", "unused")
    chunk = ChunkSpec(61, 61, Path("tail.wav"), 2995, 3037, 3000, 3037)
    with patch.object(adapter, "transcribe", side_effect=lambda **kwargs: adapter._result({"text": text}, "tail.wav")):
        result = TranscriptionService._transcribe_chunk(adapter, "tail.wav", chunk)
    assert result.full_text == ""
    assert result.metadata["unrecognized_segments"][0] == {
        "start": 3000, "end": 3037, "reason": "upstream_no_speech",
    }
    with pytest.raises(NoSpeechDetectedError):
        adapter._result({"text": text}, "tail.wav")


@pytest.mark.parametrize("payload", [{}, {"text": None}, {"text": "", "segments": [{"text": "发言"}]}])
def test_incomplete_success_response_does_not_become_empty_recognition(payload):
    from app.transcribers.vilab_transcriber import VILabTranscriber

    with pytest.raises(RuntimeError) as error:
        VILabTranscriber("http://localhost", "unused")._result(payload, "unused.wav")
    assert not isinstance(error.value, NoSpeechDetectedError)
