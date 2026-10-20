"""Exercise real HTTPX proxy selection, TLS setup and HTTP parsing without sockets."""
import json
import socket
import ssl
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import httpx._utils
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpcore._backends.sync import SyncBackend

from app.services import cloud_account_service as account
from app.services import vilab_cloud_service as cloud
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_failure import failure_details

TARGET = 'https://target.invalid'
SECRET = 'SYNTHETIC_PRIVATE_CREDENTIAL'
PARTIAL = 'SYNTHETIC_UNCONFIRMED_PARTIAL'
PAYLOAD = {'model': 'explicit-frozen-model', 'messages': [
    {'role': 'user', 'content': 'complete synthetic source in one request'}]}


def sse(*, complete=True):
    data = 'data: ' + json.dumps({'choices': [{'index': 0,
        'delta': {'content': PARTIAL}, 'finish_reason': 'stop' if complete else None}]})
    return (': heartbeat\n\n' + data + '\n\n' +
            ('data: [DONE]\n\n' if complete else '')).encode()


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(registry_reads=[], connections=[], tls=[], writes=[],
                            status=200, body=b'{"ok":true}', truncated=False,
                            reject_tls=False, read_timeout=False, content_type='application/json')

    def forbidden(*args, **kwargs):
        pytest.fail('Real network access is forbidden')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(urllib.request, 'getproxies_environment', lambda: {})

    def registry():
        state.registry_reads.append(True)
        return {'https': 'http://proxy-user:' + SECRET + '@127.0.0.1:7890'}

    monkeypatch.setattr(urllib.request, 'getproxies_registry', registry, raising=False)
    # Model Windows getproxies' environment-or-registry behavior on every OS.
    monkeypatch.setattr(httpx._utils, 'getproxies', lambda:
                        urllib.request.getproxies_environment() or
                        urllib.request.getproxies_registry())

    class Stream:
        def __init__(self):
            length = len(state.body) + (100 if state.truncated else 0)
            self.response = (f'HTTP/1.1 {state.status} Test\r\n'
                f'Content-Length: {length}\r\nContent-Type: {state.content_type}\r\n'
                'Location: https://other.invalid/redirect\r\nConnection: close\r\n\r\n'
                ).encode() + state.body

        def start_tls(self, ssl_context, server_hostname, **kwargs):
            state.tls.append((server_hostname, ssl_context.check_hostname,
                              ssl_context.verify_mode))
            if state.reject_tls:
                import httpcore
                raise httpcore.ConnectError(SECRET)
            return self

        def write(self, buffer, **kwargs):
            state.writes.append(bytes(buffer))

        def read(self, max_bytes, **kwargs):
            if not self.response and state.read_timeout:
                import httpcore
                raise httpcore.ReadTimeout(SECRET)
            data, self.response = self.response[:max_bytes], self.response[max_bytes:]
            return data

        def close(self):
            pass

        def get_extra_info(self, name):
            return None

    def connect_tcp(self, host, port, **kwargs):
        state.connections.append((host, port))
        assert (host, port) == ('target.invalid', 443), 'System proxy trap reached'
        return Stream()

    monkeypatch.setattr(SyncBackend, 'connect_tcp', connect_tcp)
    monkeypatch.setattr(cloud, 'settings', SimpleNamespace(vilab_server_url=TARGET,
        content_cloud_runtime=False, cloud_auth_url='', vilab_api_key=SECRET))
    monkeypatch.setattr(cloud.VILabCloudService, 'status',
                        lambda self, owner: {'server_url': TARGET})
    monkeypatch.setattr(account, 'settings', SimpleNamespace(cloud_auth_url=TARGET,
                                                          cloud_auth_public_key=SECRET))
    return state


def invoke(kind, wire, monkeypatch):
    if kind != 'refresh':
        return cloud.VILabCloudService().request('synthetic-owner', 'POST',
            '/openai/v1/chat/completions', json={**PAYLOAD, 'stream': kind == 'stream'})
    cipher = Fernet(Fernet.generate_key())
    row = SimpleNamespace(issuer=TARGET, session_encrypted=cipher.encrypt(json.dumps({
        'access_token': 'expired', 'refresh_token': SECRET, 'expires_at': 0
    }).encode()).decode())

    @contextmanager
    def session():
        yield SimpleNamespace(scalar=lambda query: row)

    monkeypatch.setattr(account, 'session_scope', session)
    monkeypatch.setattr(account, '_cipher', lambda: cipher)
    return account.CloudAccountService().access_token('synthetic-owner')


def assert_direct_once(wire):
    assert wire.registry_reads == []
    assert wire.connections == [('target.invalid', 443)]
    assert wire.tls == [('target.invalid', True, ssl.CERT_REQUIRED)]
    sent = b''.join(wire.writes)
    assert sent.count(b'POST ') == 1
    assert b'CONNECT ' not in sent and b'proxy-authorization' not in sent.lower()
    return sent


def assert_summary_not_replayable(error, tmp_path, *, terminal_context=None):
    expected = {'error_code': 'summary_result_unconfirmed', 'retryable': False}
    if terminal_context is not None:
        expected['summary_failure_context'] = terminal_context
    assert failure_details(error) == expected
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('summary-failure')
    artifacts.update_status(folder, 'summarizing', processed_seconds=100,
                            total_seconds=100, stage='summarizing')
    artifacts.update_status(folder, 'failed', str(error), **failure_details(error))
    # A generic outer worker handler cannot replace the typed safety decision.
    artifacts.update_status(folder, 'failed', 'outer failure', retryable=True)
    saved = artifacts.get_status('summary-failure')
    assert saved['error_code'] == 'summary_result_unconfirmed'
    assert saved['retryable'] is False and saved['failed_stage'] == 'summarizing'
    assert saved['processed_seconds'] == saved['total_seconds'] == 100
    assert 'asr_failure_context' not in saved
    if terminal_context is not None:
        assert saved['summary_failure_context'] == terminal_context
    else:
        assert 'summary_failure_context' not in saved
    assert SECRET not in json.dumps(saved) and PARTIAL not in json.dumps(saved)


def test_proxy_trap_detects_real_httpx_default_registry_inheritance(wire):
    with pytest.raises(AssertionError, match='System proxy trap reached'):
        httpx.get(TARGET)
    assert wire.registry_reads == [True]
    assert wire.connections == [('127.0.0.1', 7890)]
    assert wire.writes == []


@pytest.mark.parametrize('kind', ['request', 'stream', 'refresh'])
def test_three_product_entries_ignore_registry_preserve_tls_and_target_credentials(
        kind, wire, monkeypatch):
    if kind == 'stream':
        wire.body, wire.content_type = sse(), 'text/event-stream'
    elif kind == 'refresh':
        wire.body = b'{"access_token":"renewed","refresh_token":"rotated","expires_in":3600}'
    result = invoke(kind, wire, monkeypatch)
    sent = assert_direct_once(wire)
    assert SECRET.encode() in sent
    if kind == 'refresh':
        assert result == 'renewed'
        assert b'/auth/v1/token?grant_type=refresh_token' in sent
    else:
        body = json.loads(sent.split(b'\r\n\r\n', 1)[1])
        assert body == {**PAYLOAD, 'stream': kind == 'stream'}
        assert b'Authorization: Bearer ' + SECRET.encode() in sent
        assert result == ({'ok': True} if kind == 'request' else {
            'model': None, 'usage': {}, 'choices': [
                {'message': {'content': PARTIAL}, 'finish_reason': 'stop'}]})


@pytest.mark.parametrize('kind', ['request', 'stream'])
def test_524_after_post_is_not_replayed_or_exposed_as_success(kind, wire, monkeypatch, caplog,
                                                           tmp_path):
    wire.status, wire.body = 524, json.dumps({'error': {'message': SECRET}}).encode()
    with pytest.raises(HTTPException) as caught:
        invoke(kind, wire, monkeypatch)
    assert_direct_once(wire)
    assert caught.value.cloud_failure_context['http_status'] == 524
    assert SECRET not in caught.value.detail + caplog.text
    assert_summary_not_replayable(caught.value, tmp_path)


@pytest.mark.parametrize('truncated', [False, True])
def test_partial_sse_eof_or_disconnect_never_replays_or_returns_partial(
        truncated, wire, monkeypatch, caplog, tmp_path):
    wire.body, wire.content_type = sse(complete=False), 'text/event-stream'
    wire.truncated = truncated
    with pytest.raises(HTTPException) as caught:
        invoke('stream', wire, monkeypatch)
    assert_direct_once(wire)
    assert caught.value.status_code == 502
    assert PARTIAL not in caught.value.detail + caplog.text
    terminal_context = None if truncated else {
        'diagnostic_protocol': 'sse_terminal/1', 'done_seen': False, 'finish': 'missing',
        'category': 'missing_done_and_non_stop_finish',
    }
    assert_summary_not_replayable(caught.value, tmp_path, terminal_context=terminal_context)


@pytest.mark.parametrize('kind', ['request', 'stream'])
def test_read_timeout_after_post_is_typed_and_never_replayed(kind, wire, monkeypatch,
                                                           tmp_path, caplog):
    wire.body = sse(complete=False) if kind == 'stream' else b'{"unfinished":'
    wire.truncated = wire.read_timeout = True
    with pytest.raises(HTTPException) as caught:
        invoke(kind, wire, monkeypatch)
    assert_direct_once(wire)
    assert_summary_not_replayable(caught.value, tmp_path)
    assert SECRET not in caught.value.detail + caplog.text


def test_overall_deadline_during_sse_keeps_single_post_and_blocks_retry(
        wire, monkeypatch, tmp_path):
    from app.services import cloud_chat_stream
    original = cloud_chat_stream.collect_chat_stream
    monkeypatch.setattr(cloud_chat_stream, 'collect_chat_stream',
                        lambda response, *, started: original(response, started=started, max_seconds=-1))
    wire.body, wire.content_type = sse(), 'text/event-stream'
    with pytest.raises(HTTPException) as caught:
        invoke('stream', wire, monkeypatch)
    assert caught.value.status_code == 504
    assert_direct_once(wire)
    assert_summary_not_replayable(caught.value, tmp_path)


@pytest.mark.parametrize('kind', ['request', 'stream', 'refresh'])
def test_tls_failure_does_not_send_credentials_or_fallback(kind, wire, monkeypatch):
    wire.reject_tls = True
    with pytest.raises(HTTPException):
        invoke(kind, wire, monkeypatch)
    assert wire.connections == [('target.invalid', 443)]
    assert wire.registry_reads == [] and wire.writes == []
    assert wire.tls == [('target.invalid', True, ssl.CERT_REQUIRED)]


@pytest.mark.parametrize('kind', ['request', 'stream', 'refresh'])
def test_redirect_does_not_forward_credentials_or_replay(kind, wire, monkeypatch):
    wire.status, wire.body = 302, b'{}'
    with pytest.raises(HTTPException):
        invoke(kind, wire, monkeypatch)
    assert_direct_once(wire)
