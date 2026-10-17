import json
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services.vilab_cloud_service import VILabCloudService


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('status,error,category,copy', [
    (401, {'type': 'vilab_error', 'code': 'unauthorized'}, 'caller_auth', '当前身份'),
    (403, {'type': 'vilab_error', 'code': 'account_disabled'}, 'caller_disabled', '已停用'),
    (401, {'type': 'invalid_request_error', 'code': 'invalid_api_key'}, 'provider_auth', '模型服务'),
    (403, {'type': 'permission_error', 'code': 'permission_denied'}, 'provider_permission', '权限'),
    (403, {'type': 'invalid_request_error', 'code': 'insufficient_quota'}, 'provider_quota', '额度'),
    (403, {'type': 'untrusted-secret', 'code': 'secret-code'}, 'unclassified_rejection', 'HTTP 403'),
    (503, {'type': 'vilab_error', 'code': 'authentication_unavailable'}, 'caller_auth_unavailable', '认证服务'),
])
def test_chat_rejections_use_protocol_and_safe_projection(stream, status, error, category, copy, caplog):
    error = {**error, 'message': 'body-secret Bearer token-secret https://private.invalid',
             'api_key': 'body-secret', 'upstreamStatus': 'credential-secret'}
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={'error': error, 'prompt': 'content-secret'})
    service = VILabCloudService()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
            patch.object(service, 'status', return_value={'server_url': 'https://unused.test'}), \
            patch('app.services.vilab_cloud_service.settings') as settings, \
            patch('app.services.vilab_cloud_service.httpx.stream', side_effect=client.stream), \
            patch('app.services.vilab_cloud_service.httpx.request', side_effect=client.request):
        settings.vilab_server_url = 'https://unused.test'
        settings.cloud_auth_url = ''
        settings.vilab_api_key = 'header-secret'
        with pytest.raises(HTTPException) as caught:
            service.request('owner', 'POST', '/openai/v1/chat/completions',
                            json={'model': 'frozen-model', 'stream': stream})
    assert len(seen) == 1 and json.loads(seen[0].content)['model'] == 'frozen-model'
    assert copy in caught.value.detail
    diagnostic = caught.value.cloud_failure_context
    assert diagnostic['category'] == category and diagnostic['http_status'] == status
    assert set(diagnostic) <= {'category', 'http_status', 'error_type', 'error_code'}
    combined = str(caught.value.detail) + repr(diagnostic) + caplog.text
    assert all(secret not in combined for secret in ('body-secret', 'token-secret', 'header-secret',
        'content-secret', 'credential-secret', 'untrusted-secret', 'secret-code', 'private.invalid'))
    if category.startswith('provider') or category == 'unclassified_rejection':
        assert '登录' not in caught.value.detail and '当前身份' not in caught.value.detail


def test_complete_diarized_transcript_recovery_does_not_resolve_or_invoke_asr():
    from app.models.transcript import TranscriptResult, TranscriptSegment
    from app.services.transcription_service import TranscriptionService
    transcript = TranscriptResult('zh', 'synthetic saved transcript',
        [TranscriptSegment(0, 3, 'synthetic saved transcript')],
        {'speaker_diarization': True, 'analysis_parallel': True,
         'asr_evidence': {'full_text': 'synthetic saved transcript'},
         'speaker_evidence': [{'start': 0, 'end': 3}]})
    service = TranscriptionService(stt_profile_service=Mock())
    saved = Mock()
    with patch('app.services.transcription_service.create_transcriber', side_effect=AssertionError('no ASR')), \
            patch.object(service, 'get_audio_duration', side_effect=AssertionError('no audio preparation')):
        result = service.transcribe(audio_path='not-opened.wav', user_id='owner', diarize=True,
            load_cached=lambda: transcript, save_transcript=saved)
    assert result is transcript
    service.stt_profile_service.resolve_config.assert_not_called()
    saved.assert_not_called()


@pytest.mark.parametrize('raw', [b'<html>private-secret</html>', b'{"error": []}',
    b'{"error":{"type":"vilab_error","code":"unauthorized","message":"private-secret"}}'])
def test_ambiguous_or_malformed_403_is_not_called_a_login_failure(raw, caplog):
    from app.services.vilab_cloud_service import _chat_failure
    failure = _chat_failure(httpx.Response(403, content=raw))
    assert failure.cloud_failure_context['category'] == 'unclassified_rejection'
    assert 'HTTP 403' in failure.detail and '登录' not in failure.detail
    assert 'private-secret' not in failure.detail + caplog.text


def test_error_stream_inspection_is_bounded_and_does_not_echo_body(caplog):
    from app.services.vilab_cloud_service import _chat_failure
    class ErrorStream(httpx.SyncByteStream):
        reads = 0
        def __iter__(self):
            for _ in range(1000):
                self.reads += 1
                yield b'private-secret' + b'x' * (4096 - len(b'private-secret'))
    body = ErrorStream()
    response = httpx.Response(403, stream=body)
    try:
        failure = _chat_failure(response)
    finally:
        response.close()
    assert body.reads == 17  # 64 KiB plus a single bounded overflow block.
    assert failure.cloud_failure_context == {'category': 'unclassified_rejection', 'http_status': 403}
    assert 'private-secret' not in caplog.text + failure.detail


@pytest.mark.parametrize('error', [httpx.ConnectError('private-secret'), httpx.ReadTimeout('private-secret')])
def test_chat_transport_failure_before_headers_is_not_automatically_replayed(error, caplog):
    with patch('app.services.vilab_cloud_service.httpx.stream', side_effect=error) as send:
        with pytest.raises(HTTPException):
            VILabCloudService()._request_chat_stream('POST', '/openai/v1/chat/completions', {}, 30,
                {'json': {'model': 'frozen-model', 'stream': True}}, server_url='https://unused.test')
    assert send.call_count == 1
    assert 'private-secret' not in caplog.text
