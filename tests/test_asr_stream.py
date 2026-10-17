import json
import wave
from unittest.mock import patch

import httpx
import pytest

from app.services.asr_stream_service import ASRSessionLimit, recognize_pcm, service_duration_limit
from app.transcribers.vilab_transcriber import VILabTranscriber


@pytest.mark.parametrize("value", [True, False, "12", "12.5", None, float("nan"),
                                  float("inf"), -float("inf"), 0, -1, {}, []])
def test_invalid_structured_limit_cannot_fall_back_to_message(value):
    assert service_duration_limit({"code": "audio_duration_exceeded",
        "maxAudioDurationSeconds": value, "message": "5 minute session limit"}) is None


@pytest.mark.parametrize("value", [True, False, "12", float("nan"), float("inf"), 0, -1])
def test_invalid_cached_limit_preserves_checkpoint_and_sends_nothing(tmp_path, value):
    path = tmp_path / "source.wav"
    wav(path, .01)
    adapter = VILabTranscriber("https://example.test", "test", "selected")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch(
        "app.services.asr_stream_service.recognize_pcm", return_value={"text": "retained"}):
        adapter._transcribe_normalized(str(path))
    checkpoint = next(tmp_path.glob("asr-stream-checkpoints/*/recognition.json"))
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    saved["session_limit"] = value
    before = json.dumps(saved)
    checkpoint.write_text(before, encoding="utf-8")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch(
        "app.services.asr_stream_service.recognize_pcm") as request:
        with pytest.raises(ValueError, match="会话记录无效"):
            adapter._transcribe_normalized(str(path))
    request.assert_not_called()
    assert checkpoint.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("code,expected", [("asr_timeout", "asr_timeout"),
    ("asr_failed", "asr_failed"), ("Bearer private-key", "unknown_error")])
def test_service_error_preserves_only_safe_classification_and_session(tmp_path, caplog, code, expected):
    from contextlib import contextmanager
    from app.services.asr_stream_service import ASRServiceError
    path = tmp_path / "source.wav"
    wav(path, .01)
    session = "56bb63c8-e013-4444-92cc-7d4f211a5e78"
    class Socket:
        index = 0
        def send(self, _data):
            pass
        def recv(self, timeout):
            self.index += 1
            if self.index == 1:
                return json.dumps({"type": "session.started", "sessionId": session})
            return json.dumps({"type": "error", "code": code, "stage": "asr",
                               "message": "private-key private transcript", "sessionId": "private-key"})
    @contextmanager
    def connection(*args, **kwargs):
        yield Socket()
    with patch("app.services.asr_stream_service.open_recognition", connection):
        with pytest.raises(ASRServiceError) as caught:
            recognize_pcm("https://example.test", "private-key", "selected", path)
    assert caught.value.code == expected
    assert caught.value.session_id == session
    assert session in caplog.text
    assert "private-key" not in caplog.text + str(caught.value) + repr(vars(caught.value))
    assert "private transcript" not in caplog.text + repr(vars(caught.value))


def test_last_packet_then_disconnect_is_unknown_without_auto_retry(tmp_path):
    from contextlib import contextmanager
    from websockets.exceptions import ConnectionClosedOK
    from app.services.asr_stream_service import ASRServiceError
    import threading
    path = tmp_path / "source.wav"
    wav(path, .01)
    sent = threading.Event()
    class Socket:
        index = 0
        def send(self, data):
            if isinstance(data, bytes):
                sent.set()
        def recv(self, timeout):
            self.index += 1
            if self.index == 1:
                return json.dumps({"type": "session.started"})
            assert sent.wait(1)
            raise ConnectionClosedOK(None, None)
    @contextmanager
    def connection(*args, **kwargs):
        yield Socket()
    with patch("app.services.asr_stream_service.open_recognition", connection):
        with pytest.raises(ASRServiceError) as caught:
            recognize_pcm("https://example.test", "test", "selected", path)
    assert caught.value.code == "unknown_result"
    assert VILabTranscriber._retry_reason(caught.value) is None


def test_diagnostic_rejects_arbitrary_session_and_stage():
    from app.services.asr_stream_service import ASRServiceError
    error = ASRServiceError("asr_failed", session_id="secret-token\nforged log", stage="private transcript")
    assert error.diagnostic == {"code": "asr_failed", "session_id": None, "stage": None, "sent_all": False}
    assert "secret" not in repr(vars(error))


def wav(path, duration):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * round(duration * 16000))


def test_only_explicit_service_limit_changes_session_layout():
    assert service_duration_limit({"code": "audio_duration_exceeded", "message": "Audio duration exceeds the 5 minute session limit."}) == 300
    assert service_duration_limit({"code": "audio_duration_exceeded", "maxAudioDurationSeconds": 37.5}) == 37.5
    assert service_duration_limit({"code": "network_error", "message": "5 minute session limit"}) is None
    assert service_duration_limit({"code": "audio_duration_exceeded", "maxAudioDurationSeconds": float("nan")}) is None


def test_delayed_send_does_not_burst_catch_up_packets(tmp_path):
    import threading
    import time
    from contextlib import contextmanager
    path = tmp_path / 'delayed.wav'
    wav(path, .6)
    frames = []
    finished = threading.Event()

    class Socket:
        started = False

        def send(self, data):
            if not isinstance(data, bytes):
                return
            if not frames:
                time.sleep(.5)  # A blocked write / scheduling pause.
            frames.append(time.monotonic())
            if data[6] & 2:
                finished.set()

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({'type': 'session.started'})
            assert finished.wait(3)
            return json.dumps({'type': 'asr.final', 'text': 'complete'})

    @contextmanager
    def connection(*args, **kwargs):
        yield Socket()

    with patch('app.services.asr_stream_service.open_recognition', connection):
        assert recognize_pcm('https://example.test', 'secret', 'chosen', path)['text'] == 'complete'
    assert len(frames) == 3
    assert all(later - earlier >= .15 for earlier, later in zip(frames, frames[1:]))


def test_service_limit_failure_does_not_blindly_replay_audio(tmp_path):
    from app.services.asr_stream_service import ASRServiceError
    path = tmp_path / "source.wav"
    wav(path, 97)
    adapter = VILabTranscriber("https://example.test", "private-key", "asr:any:new-provider")
    with patch("app.config.settings.data_dir", str(tmp_path)), patch(
        "app.services.asr_stream_service.recognize_pcm", side_effect=ASRSessionLimit(41)
    ) as call:
        with pytest.raises(ASRServiceError):
            adapter._transcribe_normalized(str(path))
        with pytest.raises(ASRServiceError):
            adapter._transcribe_normalized(str(path))
        assert call.call_count == 1
        assert call.call_args.args[2] == adapter.model


def test_separate_credentials_never_reuse_other_owner_transcripts(tmp_path):
    path = tmp_path / "source.wav"
    wav(path, 2)
    with patch("app.config.settings.data_dir", str(tmp_path)), patch("app.services.asr_stream_service.recognize_pcm", side_effect=[{"text": "owner one"}, {"text": "owner two"}]) as call:
        first = VILabTranscriber("https://example.test", "one", "asr:model")._transcribe_normalized(str(path))
        second = VILabTranscriber("https://example.test", "two", "asr:model")._transcribe_normalized(str(path))
    assert first.full_text == "owner one"
    assert second.full_text == "owner two"
    assert call.call_count == 2


def test_partial_text_is_not_a_final_transcript(tmp_path):
    from contextlib import contextmanager
    path = tmp_path / "source.wav"
    wav(path, 1)
    class Socket:
        events = iter([{"type": "asr.partial", "text": "temporary", "audioMs": 900}, {"type": "session.completed"}])
        def send(self, _data):
            pass
        def recv(self, timeout):
            return json.dumps(next(self.events))
    @contextmanager
    def connection(*args, **kwargs):
        yield Socket()
    with patch("app.services.asr_stream_service.connect", connection):
        with pytest.raises(RuntimeError, match="最终"):
            recognize_pcm("https://example.test", "secret", "asr:model", path)


def test_final_sentence_timestamps_are_retained_without_losing_text(tmp_path):
    path = tmp_path / "source.wav"
    wav(path, 2)
    payload = {"text": "first second", "segments": [
        {"start": 0, "end": .8, "text": "first"},
        {"start": 1, "end": 2, "text": "second"},
    ]}
    with patch("app.config.settings.data_dir", str(tmp_path)), patch("app.services.asr_stream_service.recognize_pcm", return_value=payload):
        result = VILabTranscriber("https://example.test", "key", "chosen")._transcribe_normalized(str(path))
    assert result.full_text == "first second"
    assert len(result.segments) == 2
    assert result.segments[1].start == 1
    assert not result.segments[1].timestamp_estimated
    assert result.metadata["timestamp_granularity"] == "segment"


def test_incomplete_provider_timestamps_cannot_truncate_the_final_text(tmp_path):
    path = tmp_path / "source.wav"
    wav(path, 2)
    payload = {"text": "first second", "segments": [{"start": 0, "end": 1, "text": "first"}]}
    with patch("app.config.settings.data_dir", str(tmp_path)), patch("app.services.asr_stream_service.recognize_pcm", return_value=payload):
        result = VILabTranscriber("https://example.test", "key", "chosen")._transcribe_normalized(str(path))
    assert result.segments[0].text == "first second"
    assert result.segments[0].timestamp_estimated


def test_final_before_last_frame_is_rejected_instead_of_waiting_for_remainder(tmp_path):
    import threading
    from contextlib import contextmanager
    path = tmp_path / "source.wav"
    wav(path, 1)
    first_frame = threading.Event()
    class Socket:
        index = 0
        def send(self, data):
            if isinstance(data, bytes):
                first_frame.set()
        def recv(self, timeout):
            self.index += 1
            if self.index == 1:
                return json.dumps({"type": "session.started"})
            assert first_frame.wait(1)
            return json.dumps({"type": "asr.final", "text": "prefix only"})
    @contextmanager
    def connection(*args, **kwargs):
        yield Socket()
    with patch("app.services.asr_stream_service.open_recognition", connection):
        with pytest.raises(RuntimeError, match="提前"):
            recognize_pcm("https://example.test", "secret", "chosen", path)


@pytest.fixture(autouse=True)
def declared_recording_budget(monkeypatch):
    # Transport regressions use an explicit service contract; never query a real catalog.
    from app.services.adaptive_asr_policy import RecordedAudioPolicy
    monkeypatch.setattr(VILabTranscriber, "_recorded_audio_policy",
                        lambda self, bearer: RecordedAudioPolicy(2097152))
