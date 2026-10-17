"""Offline deadline regressions with the real sender thread and event barriers."""
import json
import socket
import shutil
import threading
import wave
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services import asr_stream_service as service
from app.transcribers.vilab_transcriber import VILabTranscriber


class Clock:
    def __init__(self):
        self.value = 0.0
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            return self.value

    def set(self, value):
        with self.lock:
            self.value = value

    def advance(self, seconds):
        with self.lock:
            self.value += seconds


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No cloud or other network calls are permitted")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 160)  # One 10ms LAST packet, no pacing sleep.
    clock = Clock()
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=clock.now))
    return path, clock


def observe_budget(monkeypatch):
    confirmed = threading.Event()
    instances = []
    actual = service._StreamDeadline

    class Observed(actual):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

        def confirm_last(self):
            super().confirm_last()
            confirmed.set()

    monkeypatch.setattr(service, "_StreamDeadline", Observed)
    return instances, confirmed


def connection_for(monkeypatch, ws):
    @contextmanager
    def connection(*_args, **_kwargs):
        try:
            yield ws
        finally:
            ws.closed = True
    monkeypatch.setattr(service, "open_recognition", connection)


def test_confirmed_last_gets_independent_finish_budget_beyond_old_deadline(scenario, monkeypatch):
    path, clock = scenario
    instances, confirmed = observe_budget(monkeypatch)

    class Socket:
        started = False
        frames = []
        closed = False

        def send(self, data):
            if isinstance(data, bytes):
                self.frames.append(data)
                clock.set(89)  # Still inside the original 90.015s upload budget.

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert confirmed.wait(1)
            clock.set(120)  # Beyond old whole-operation deadline, within finish.
            return json.dumps({"type": "asr.final", "text": "synthetic final"})

    ws = Socket()
    connection_for(monkeypatch, ws)
    result = service.recognize_pcm("https://example.test", "offline", "frozen", path)
    assert result["text"] == "synthetic final"
    assert instances[0].completed_at == 89
    assert instances[0].upload_deadline < clock.now()
    assert len(ws.frames) == 1 and ws.frames[0][6] & 2
    assert ws.closed


@pytest.mark.parametrize("partials", [False, True])
def test_no_final_is_bounded_and_partial_cannot_extend_finish(scenario, monkeypatch, partials):
    path, clock = scenario
    instances, confirmed = observe_budget(monkeypatch)

    class Socket:
        started = False
        frames = 0
        closed = False

        def send(self, data):
            if isinstance(data, bytes):
                self.frames += 1
                clock.set(80)

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert confirmed.wait(1)
            clock.advance(timeout)
            if partials:
                return json.dumps({"type": "asr.partial", "audioMs": 10})
            raise TimeoutError

    ws = Socket()
    connection_for(monkeypatch, ws)
    with pytest.raises(service.ASRServiceError) as caught:
        service.recognize_pcm("https://example.test", "offline", "frozen", path, progress=lambda *_: None)
    assert caught.value.code == "unknown_result"
    assert caught.value.sent_all
    assert VILabTranscriber._retry_reason(caught.value) is None
    assert clock.now() == pytest.approx(80 + 90.015)
    assert instances[0].completed_at == 80
    assert ws.frames == 1 and ws.closed


@pytest.mark.parametrize("late_success", [False, True])
def test_unconfirmed_or_late_last_cannot_rebase_upload_deadline(scenario, monkeypatch, late_success):
    path, clock = scenario
    instances, confirmed = observe_budget(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    send_done = threading.Event()

    class Socket:
        started = False
        closed = False
        frames = 0

        def send(self, data):
            if isinstance(data, bytes):
                self.frames += 1
                entered.set()
                assert release.wait(1)
                send_done.set()
                if not late_success:
                    raise OSError("synthetic unconfirmed send")

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert entered.wait(1)
            clock.set(91)  # LAST is still blocked as upload budget expires.
            release.set()
            if late_success:
                assert confirmed.wait(1)
            else:
                assert send_done.wait(1)
            return json.dumps({"type": "asr.partial", "audioMs": 10})

    ws = Socket()
    connection_for(monkeypatch, ws)
    with pytest.raises(service.ASRServiceError) as caught:
        service.recognize_pcm("https://example.test", "offline", "frozen", path)
    assert caught.value.code == "unknown_result"
    assert VILabTranscriber._retry_reason(caught.value) is None
    assert instances[0].completed_at is None
    assert ws.frames == 1 and ws.closed


def test_finish_transition_is_once_only_and_expiry_cannot_be_revived(scenario):
    _path, clock = scenario
    deadline = service._StreamDeadline(.01)
    clock.set(10)
    deadline.confirm_last()
    clock.set(20)
    deadline.confirm_last()
    assert deadline.completed_at == 10
    assert deadline.remaining() == pytest.approx(80.015)
    clock.set(101)
    assert deadline.remaining() == 0
    deadline.confirm_last()
    assert deadline.completed_at == 10 and deadline.remaining() == 0


@pytest.mark.parametrize("fault", ["send", "disconnect", "recv_oserror", "deadline", "service_error"])
def test_real_transcriber_never_replays_after_nonlast_audio_attempt(scenario, monkeypatch, fault):
    from websockets.exceptions import ConnectionClosedOK
    from app.config import settings

    path, clock = scenario
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 6400)  # Two packets; fault before LAST.
    sent = threading.Event()
    opens = []
    sleep_calls = []
    frames = []
    models = []

    class Socket:
        started = False
        closed = False

        def send(self, data):
            if isinstance(data, bytes):
                frames.append(data)
                sent.set()
                if fault == "send":
                    raise OSError("synthetic unconfirmed binary send")
            else:
                models.append(json.loads(data)["model"])

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert sent.wait(1)
            if fault == "deadline":
                clock.set(100)
                raise TimeoutError
            if fault == "service_error":
                return json.dumps({"type": "error", "code": "asr_timeout", "stage": "asr",
                                   "message": "SECRET provider text"})
            if fault == "recv_oserror":
                raise OSError("SECRET transport details")
            raise ConnectionClosedOK(None, None)

    @contextmanager
    def connection(*_args, **_kwargs):
        ws = Socket()
        opens.append(ws)
        try:
            yield ws
        finally:
            ws.closed = True

    monkeypatch.setattr(service, "open_recognition", connection)
    monkeypatch.setattr(settings, "data_dir", str(path.parent / "cache"))
    monkeypatch.setattr("app.transcribers.vilab_transcriber.subprocess.run",
                        lambda args, **_kwargs: shutil.copyfile(path, args[-1]))
    monkeypatch.setattr("app.transcribers.vilab_transcriber.time.sleep", sleep_calls.append)
    adapter = VILabTranscriber("https://example.test", "offline", "frozen")
    with pytest.raises(service.ASRServiceError) as caught:
        adapter.transcribe(str(path))
    error = caught.value
    assert error.code == ("asr_timeout" if fault == "service_error" else "unknown_result")
    assert error.retry_reason is None and VILabTranscriber._retry_reason(error) is None
    assert error.sent_all is False
    assert {"code", "session_id", "stage", "sent_all"} <= set(error.diagnostic)
    assert error.diagnostic["local_send_attempt_packets"] == 1
    assert error.diagnostic["local_send_attempt_bytes"] == 6400
    expected_event = {"send": {"audio_send_failed", "connection_closed"},
                      "disconnect": {"connection_closed"}, "recv_oserror": {"connection_closed"},
                      "deadline": {"client_deadline"}, "service_error": {"service_error"}}
    # This older send fixture also closes recv concurrently; either observation
    # may win. The dedicated diagnostic fixture isolates a sender-only failure.
    assert error.diagnostic["transport_event"] in expected_event[fault]
    assert len(opens) == 1 and opens[0].closed
    assert len(frames) == 1 and not frames[0][6] & 2
    assert models == ["frozen"] and not sleep_calls
    assert len(error.asr_metadata["asr_attempts"]) == 1
    assert "SECRET" not in repr(vars(error))


@pytest.mark.parametrize("fault", ["connect", "service_error"])
def test_real_transcriber_keeps_bounded_retry_before_any_audio(scenario, monkeypatch, fault):
    import httpx
    from app.config import settings

    path, _clock = scenario
    calls = []
    sleeps = []

    class Socket:
        def send(self, data):
            assert isinstance(data, str), "must not attempt audio before session.started"

        def recv(self, timeout):
            return json.dumps({"type": "error", "code": "asr_timeout", "stage": "asr"})

    @contextmanager
    def connection(*_args, **_kwargs):
        calls.append(1)
        if fault == "connect":
            raise httpx.ConnectError("synthetic pre-audio connection failure")
        yield Socket()

    monkeypatch.setattr(service, "open_recognition", connection)
    monkeypatch.setattr(settings, "data_dir", str(path.parent / "cache"))
    monkeypatch.setattr("app.transcribers.vilab_transcriber.subprocess.run",
                        lambda args, **_kwargs: shutil.copyfile(path, args[-1]))
    monkeypatch.setattr("app.transcribers.vilab_transcriber.time.sleep", sleeps.append)
    adapter = VILabTranscriber("https://example.test", "offline", "frozen")
    with pytest.raises(Exception) as caught:
        adapter.transcribe(str(path))
    assert len(calls) == 3 and len(sleeps) == 2
    assert adapter.model == "frozen"
    if fault == "service_error":
        assert len(caught.value.asr_metadata["asr_attempts"]) == 3
    else:
        assert VILabTranscriber._retry_reason(caught.value) == "network"


def test_explicit_duration_limit_still_has_its_existing_continuation_semantics(scenario, monkeypatch):
    path, _clock = scenario
    attempted = threading.Event()

    class Socket:
        started = False
        closed = False

        def send(self, data):
            if isinstance(data, bytes):
                attempted.set()

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert attempted.wait(1)
            return json.dumps({"type": "error", "code": "audio_duration_exceeded",
                               "maxAudioDurationSeconds": .005})

    connection_for(monkeypatch, Socket())
    with pytest.raises(service.ASRSessionLimit) as caught:
        service.recognize_pcm("https://example.test", "offline", "frozen", path)
    assert caught.value.seconds == .005


def test_last_completion_at_upload_deadline_does_not_extend_it(scenario):
    _path, clock = scenario
    deadline = service._StreamDeadline(.01)
    clock.set(deadline.upload_deadline)
    deadline.confirm_last()
    assert deadline.completed_at is None and deadline.remaining() == 0


def test_failure_before_first_send_stops_late_reader_before_it_can_attempt_audio(scenario, monkeypatch):
    """An in-flight file read cannot turn a retryable pre-audio close into replay."""
    import httpx

    path, _clock = scenario
    read_entered = threading.Event()
    release_read = threading.Event()
    events = []
    real_open = wave.open

    class Stop(threading.Event):
        def set(self):
            super().set()
            release_read.set()

    def event():
        result = Stop() if not events else threading.Event()
        events.append(result)
        return result

    class Reader:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.raw.close()

        def __getattr__(self, name):
            return getattr(self.raw, name)

        def readframes(self, samples):
            read_entered.set()
            assert release_read.wait(1)
            return self.raw.readframes(samples)

    class Socket:
        started = False
        closed = False
        binary_calls = 0

        def send(self, data):
            if isinstance(data, bytes):
                self.binary_calls += 1

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert read_entered.wait(1)
            raise OSError("synthetic pre-audio disconnect")

    monkeypatch.setattr(service, "threading", SimpleNamespace(
        Event=event, Lock=threading.Lock, Thread=threading.Thread))
    monkeypatch.setattr(service, "wave", SimpleNamespace(open=lambda *args: Reader(real_open(*args))))
    ws = Socket()
    connection_for(monkeypatch, ws)
    with pytest.raises(httpx.RemoteProtocolError) as caught:
        service.recognize_pcm("https://example.test", "offline", "frozen", path)
    assert VILabTranscriber._retry_reason(caught.value) == "network"
    assert ws.binary_calls == 0 and ws.closed
    assert read_entered.is_set() and release_read.is_set()


@pytest.fixture(autouse=True)
def declared_recording_budget(monkeypatch):
    # Transport regressions use an explicit service contract; never query a real catalog.
    from app.services.adaptive_asr_policy import RecordedAudioPolicy
    monkeypatch.setattr(VILabTranscriber, "_recorded_audio_policy",
                        lambda self, bearer: RecordedAudioPolicy(2097152))
