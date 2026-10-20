import json
import threading
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.services.asr_stream_service import ASRServiceError, recognize_pcm
from tests.test_asr_stream import wav

SESSION = '56bb63c8-e013-4444-92cc-7d4f211a5e78'
PROOF = {'protocol': 1, 'outcome': 'provider_terminal_empty', 'provider': 'aliyun',
         'terminalConfirmed': True, 'inputComplete': True,
         'contentComplete': False, 'silenceConfirmed': False}


def request(tmp_path, event):
    path = tmp_path / 'audio.wav'
    wav(path, .01)
    sent = threading.Event()

    class Socket:
        started = False

        def send(self, data):
            if isinstance(data, bytes):
                sent.set()

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({'type': 'session.started', 'sessionId': SESSION})
            assert sent.wait(1)
            return json.dumps({'type': 'error', 'code': 'empty_result_unverified',
                               'stage': 'asr', 'sessionId': SESSION, **event})

    @contextmanager
    def connection(*args, **kwargs):
        yield Socket()

    with patch('app.services.asr_stream_service.open_recognition', connection):
        return recognize_pcm('https://example.test', 'private', 'selected', path)


def test_typed_normal_empty_terminal_finishes_without_claiming_silence(tmp_path):
    result = request(tmp_path, {'terminalEvidence': PROOF})
    assert result['text'] == '' and result['segments'] == []
    assert result['recognition_outcome'] == 'provider_terminal_empty'
    assert result['terminal_evidence']['silenceConfirmed'] is False


@pytest.mark.parametrize('changes', [None, {'inputComplete': False},
    {'terminalConfirmed': False}, {'protocol': True}, {'protocol': 2},
    {'outcome': 'silence'}, {'contentComplete': True}, {'silenceConfirmed': True}])
def test_unknown_or_invalid_evidence_never_skips_or_retries(tmp_path, changes):
    proof = None if changes is None else {**PROOF, **changes}
    with pytest.raises(ASRServiceError) as caught:
        request(tmp_path, {'terminalEvidence': proof})
    assert caught.value.code == 'empty_result_unverified'
    assert caught.value.retry_reason is None


def test_different_session_cannot_confirm_current_audio(tmp_path):
    with pytest.raises(ASRServiceError):
        request(tmp_path, {'sessionId': '16bb63c8-e013-4444-92cc-7d4f211a5e78',
                           'terminalEvidence': PROOF})
