"""Content-free diagnostics; no cloud, sockets or real recordings."""
import json
import socket
import threading
import wave
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from app.services import asr_stream_service as service
from app.services.task_failure import failure_details, safe_asr_failure_context
from app.transcribers.vilab_transcriber import VILabTranscriber

SECRET = 'SYNTHETIC_AUTH_REASON_TRANSCRIPT_DO_NOT_RETAIN'

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def test_default_constructor_keeps_original_diagnostic_dict():
    assert service.ASRServiceError('asr_timeout').diagnostic == {
        'code': 'asr_timeout', 'session_id': None, 'stage': None, 'sent_all': False}
    assert failure_details(service.ASRServiceError('service_unavailable')) == {
        'error_code': 'service_unavailable', 'retryable': True}


@pytest.mark.parametrize('fault,origin', [
    ('deadline', 'client_deadline'), ('send', 'audio_send_failed'),
    ('close', 'connection_closed'), ('oserror', 'connection_closed'),
    ('ended', 'session_ended'), ('cancelled', 'session_ended'),
])
def test_real_sender_records_local_observations_not_ack(tmp_path, monkeypatch, caplog, fault, origin):
    path = tmp_path / 'synthetic.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 160)
    clock = [0.0]
    monkeypatch.setattr(service, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    confirmed = threading.Event()
    actual = service._StreamDeadline
    class Deadline(actual):
        def confirm_last(self):
            super().confirm_last()
            confirmed.set()
    monkeypatch.setattr(service, '_StreamDeadline', Deadline)
    attempted = threading.Event()
    calls = []
    class Socket:
        started = False
        def send(self, value):
            if isinstance(value, bytes):
                calls.append(value)
                clock[0] = 2
                attempted.set()
                if fault == 'send':
                    raise OSError(SECRET)
        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({'type': 'session.started'})
            assert attempted.wait(1)
            if fault == 'send':
                clock[0] = 3
                raise TimeoutError
            assert confirmed.wait(1)
            clock[0] = 100 if fault == 'deadline' else 3
            if fault == 'deadline':
                raise TimeoutError
            if fault == 'close':
                raise ConnectionClosedError(Close(1011, SECRET), None)
            if fault == 'oserror':
                raise OSError(SECRET)
            return json.dumps({'type': 'session.cancelled' if fault == 'cancelled' else 'session.completed', 'reason': SECRET})
    @contextmanager
    def connection(*args):
        yield Socket()
    monkeypatch.setattr(service, 'open_recognition', connection)
    with pytest.raises(service.ASRServiceError) as caught:
        service.recognize_pcm('https://example.invalid', SECRET, 'frozen', path)
    error = caught.value
    d = error.diagnostic
    assert d['transport_event'] == origin
    assert d['local_send_attempt_bytes'] == 320 and d['local_send_attempt_packets'] == 1
    assert d['local_send_bytes'] == (0 if fault == 'send' else 320)
    assert d['local_send_packets'] == (0 if fault == 'send' else 1)
    assert d['elapsed_ms'] == (100000 if fault == 'deadline' else 3000)
    if fault == 'send':
        assert 'last_send_age_ms' not in d
    else:
        assert d['last_send_age_ms'] == (98000 if fault == 'deadline' else 1000)
    assert d.get('ws_close_code') == (1011 if fault == 'close' else None)
    assert error.code == 'unknown_result' and error.retry_reason is None
    assert VILabTranscriber._retry_reason(error) is None
    assert len(calls) == 1
    details = failure_details(error)
    assert details['asr_failure_context']['diagnostic'] == {k: v for k, v in d.items() if v is not None}
    assert SECRET not in json.dumps(details) + caplog.text + repr(vars(error))
    assert not any(key.startswith(('ack_', 'server_ack_', 'provider_ack_')) for key in d)


def test_explicit_projection_rejects_text_invalid_numbers_and_arbitrary_keys():
    raw = {'code': 'unknown_result', 'transport_event': 'connection_closed', 'ws_close_code': 1011,
           'local_send_bytes': 6400, 'local_send_packets': 1, 'local_send_attempt_bytes': 12800,
           'local_send_attempt_packets': 2, 'elapsed_ms': 3000, 'last_send_age_ms': 150,
           'last_send_attempt_age_ms': 100, 'reason': SECRET, 'close_reason': SECRET,
           'exception': SECRET, 'server_ack_bytes': 999, 'url': SECRET}
    context = safe_asr_failure_context({'schema_version': 1, 'diagnostic': raw,
        'asr_attempts': [{'attempt': 1, 'status': 'failed', 'diagnostic': raw}]})
    projected = context['diagnostic']
    assert projected['transport_event'] == 'connection_closed'
    assert projected['ws_close_code'] == 1011 and projected['local_send_bytes'] == 6400
    assert 'server_ack_bytes' not in projected and SECRET not in json.dumps(context)
    assert context['asr_attempts'][0]['diagnostic'] == projected
    for key in ['local_send_bytes', 'local_send_packets', 'elapsed_ms', 'last_send_age_ms']:
        for invalid in [True, -1, 1.5, float('nan'), float('inf'), 2**80, '3', {}]:
            raw[key] = invalid
            assert key not in safe_asr_failure_context({'schema_version': 1, 'diagnostic': raw})['diagnostic']


@pytest.mark.parametrize('code', [True, 999, 1004, 1005, 1006, 1015, 2000, 5000, '1011', 1011.0, None])
def test_invalid_or_non_wire_close_codes_are_omitted(code):
    context = safe_asr_failure_context({'schema_version': 1, 'diagnostic': {
        'code': 'unknown_result', 'transport_event': 'connection_closed', 'ws_close_code': code}})
    assert 'ws_close_code' not in context['diagnostic']


@pytest.mark.parametrize('fault,kind', [('deadline', httpx.ReadTimeout), ('close', httpx.RemoteProtocolError)])
def test_pre_audio_transport_keeps_exception_class_and_projects_no_fake_code(tmp_path, monkeypatch, fault, kind):
    path = tmp_path / 'synthetic.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 160)
    clock = [0.0]
    monkeypatch.setattr(service, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    class Socket:
        def send(self, data):
            assert isinstance(data, str)  # Control start, never PCM.
        def recv(self, timeout):
            if fault == 'deadline':
                clock[0] = 100
                raise TimeoutError
            raise ConnectionClosedError(Close(1008, SECRET), None)
    @contextmanager
    def connection(*args):
        yield Socket()
    monkeypatch.setattr(service, 'open_recognition', connection)
    with pytest.raises(kind) as caught:
        service.recognize_pcm('https://example.invalid', SECRET, 'frozen', path)
    assert VILabTranscriber._retry_reason(caught.value) == 'network'
    details = failure_details(caught.value)
    assert 'error_code' not in details and 'retryable' not in details
    d = details['asr_failure_context']['diagnostic']
    assert d['transport_event'] == ('client_deadline' if fault == 'deadline' else 'connection_closed')
    assert d['local_send_attempt_bytes'] == d['local_send_packets'] == 0
    assert 'last_send_age_ms' not in d and 'code' not in d
    assert SECRET not in json.dumps(details)


def test_transport_context_roundtrips_private_artifact_without_changing_unknown_retry(tmp_path):
    from app.services.task_artifact_service import TaskArtifactService
    raw = {'transport_event': 'connection_closed', 'ws_close_code': 1011,
           'local_send_bytes': 6400, 'local_send_attempt_bytes': 12800,
           'local_send_packets': 1, 'local_send_attempt_packets': 2,
           'elapsed_ms': 3000, 'last_send_age_ms': 400, 'reason': SECRET}
    error = service.ASRServiceError('unknown_result', transport=raw)
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('offline-transport')
    artifacts.update_status(folder, 'failed', **failure_details(error))
    saved = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    assert saved['retryable'] is False
    d = saved['asr_failure_context']['diagnostic']
    assert d['ws_close_code'] == 1011 and d['local_send_attempt_bytes'] == 12800
    assert 'reason' not in d and SECRET not in json.dumps(saved)
    # Projection must copy rather than retaining the constructor caller's dict.
    raw['local_send_bytes'] = 999
    assert error.diagnostic['local_send_bytes'] == 6400


@pytest.mark.parametrize('code', [1000, 1011, 3000, 4999])
def test_safe_wire_close_codes_remain_exact(code):
    error = service.ASRServiceError('unknown_result', transport={'ws_close_code': code})
    assert failure_details(error)['asr_failure_context']['diagnostic']['ws_close_code'] == code


def test_diagnostics_saturate_without_changing_the_clock_or_deadlines(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(service, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    progress = service._LocalTransportProgress()
    progress.attempt(2**80)
    progress.sent(2**80)
    clock[0] = 10**12
    d = progress.snapshot('client_deadline')
    assert d['elapsed_ms'] == d['last_send_age_ms'] == 604800000
    assert d['local_send_bytes'] == d['local_send_attempt_bytes'] == 2**40
    assert all(type(value) is int for key, value in d.items() if key != 'transport_event')
    assert clock[0] == 10**12
