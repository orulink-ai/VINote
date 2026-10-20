"""No sockets/provider calls: exercise real websockets proxy/TLS setup offline."""
import inspect
import json
import socket
import ssl
import threading
import urllib.request
import wave
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close
from websockets.sync import client

from app.services import asr_stream_service as service
from app.services.task_failure import failure_details, safe_asr_failure_context
from app.transcribers.vilab_transcriber import VILabTranscriber

SECRET = 'SYNTHETIC_BEARER_REASON_AND_PROXY_PASSWORD_DO_NOT_LOG'
TARGET = 'wss://target.invalid/v1/asr/transcriptions'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No actual socket connection is allowed')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.fixture
def direct_transport(monkeypatch):
    state = SimpleNamespace(registry_reads=[], proxy_connections=[], connections=[], tls=[], starts=[])
    monkeypatch.setattr(urllib.request, 'proxy_bypass', lambda _: False)
    monkeypatch.setattr(urllib.request, 'getproxies_environment', lambda: {})
    def registry():
        state.registry_reads.append(True)
        return {'https': 'http://proxy-user:' + SECRET + '@127.0.0.1:7890'}
    monkeypatch.setattr(urllib.request, 'getproxies', lambda: registry())
    if hasattr(urllib.request, 'getproxies_registry'):
        monkeypatch.setattr(urllib.request, 'getproxies_registry', registry)
    def proxy_trap(*args, **kwargs):
        state.proxy_connections.append(True)
        raise AssertionError('Unexpected system proxy connection')
    monkeypatch.setattr(client, 'connect_http_proxy', proxy_trap)
    monkeypatch.setattr(client, 'connect_socks_proxy', proxy_trap)
    class Socket:
        def settimeout(self, value): pass
        def setsockopt(self, *args): pass
        def close(self): pass
    def tcp(address, **kwargs):
        state.connections.append(address)
        return Socket()
    monkeypatch.setattr(client.socket, 'create_connection', tcp)
    def tls(context, sock, *, server_hostname, **kwargs):
        state.tls.append((server_hostname, context.check_hostname, context.verify_mode))
        return sock
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', tls)
    class Connection:
        def __init__(self, sock, protocol, **kwargs):
            self.options = kwargs
        def handshake(self, additional_headers, user_agent_header, timeout):
            state.starts.append(dict(additional_headers))
        def start_keepalive(self): pass
    actual = client.connect
    def connect(*args, **kwargs):
        return actual(*args, **kwargs, create_connection=Connection)
    monkeypatch.setattr(service, 'connect', connect)
    return state


def test_real_connect_ignores_registry_proxy_and_sends_authorization_only_to_verified_target(direct_transport):
    assert inspect.signature(client.connect).parameters['proxy'].default is True
    assert 'proxy' in inspect.signature(client.connect).parameters
    connection = service.open_recognition(TARGET, SECRET)
    assert direct_transport.registry_reads == []
    assert direct_transport.proxy_connections == []
    assert direct_transport.connections == [('target.invalid', 443)]
    assert direct_transport.tls == [('target.invalid', True, ssl.CERT_REQUIRED)]
    assert direct_transport.starts == [{'Authorization': 'Bearer ' + SECRET}]
    assert connection.options['ping_timeout'] is None
    assert connection.options['ping_interval'] == 20


def test_tls_rejection_has_no_proxy_fallback_or_second_connection(direct_transport, monkeypatch):
    def reject(context, sock, **kwargs):
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        raise ssl.SSLCertVerificationError(SECRET)
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', reject)
    with pytest.raises(httpx.ConnectError) as caught:
        service.open_recognition(TARGET, SECRET)
    assert direct_transport.connections == [('target.invalid', 443)]
    assert direct_transport.starts == []
    assert direct_transport.registry_reads == direct_transport.proxy_connections == []
    diagnostic = failure_details(caught.value)['asr_failure_context']['diagnostic']
    assert diagnostic['transport_exception_class'] == 'SSLCertVerificationError'
    assert diagnostic['ws_proxy_mode'] == 'disabled'
    assert SECRET not in json.dumps(diagnostic)


@pytest.mark.parametrize('failure', [None, 'tls', 'timeout'])
def test_real_httpx_recorded_audio_catalog_ignores_proxy_discovery_and_never_falls_back(monkeypatch, failure):
    """Keep actual httpx.get/Client/transport setup; substitute only socket I/O."""
    reads, proxies, requests = [], [], []
    def discovery():
        reads.append(True)
        return {'all://': 'http://127.0.0.1:7890'}
    def proxy(*args, **kwargs):
        proxies.append(True)
        raise AssertionError('ASR catalog must not initialize an environment/system proxy')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:7890')
    monkeypatch.setattr(httpx._client, 'get_environment_proxies', discovery)
    monkeypatch.setattr(httpx.Client, '_init_proxy_transport', proxy)
    def direct(transport, request):
        requests.append(request)
        assert str(request.url) == 'https://target.invalid/v1/models'
        assert request.method == 'GET' and request.headers['authorization'] == 'Bearer ' + SECRET
        context = transport._pool._ssl_context
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        if failure == 'tls':
            raise httpx.ConnectError('synthetic TLS failure', request=request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic timeout', request=request)
        return httpx.Response(200, json={'data': [{'id': 'frozen-asr', 'modelType': 'asr',
            'capabilities': {'recordedAudio': {'protocol': 1, 'supported': True,
                'strategy': 'adaptive_pause', 'policySource': 'service_budget', 'maxSessionAudioBytes': 98304}}}]})
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', direct)
    adapter = VILabTranscriber('https://target.invalid', '', 'frozen-asr')
    if failure:
        with pytest.raises(ValueError, match='尚未提交音频'):
            adapter._recorded_audio_policy(SECRET)
    else:
        assert adapter._recorded_audio_policy(SECRET).max_session_audio_bytes == 98304
    assert len(requests) == 1 and reads == proxies == []


@pytest.mark.parametrize('failure,expected,close_code', [
    (lambda: ConnectionClosedError(Close(1011, SECRET), None), 'ConnectionClosedError', 1011),
    (lambda: ConnectionClosedOK(Close(1000, SECRET), None), 'ConnectionClosedOK', 1000),
    (lambda: ConnectionClosedError(None, None), 'ConnectionClosedError', None),
    (lambda: ConnectionResetError(SECRET), 'ConnectionResetError', None),
    (lambda: ssl.SSLEOFError(SECRET), 'SSLEOFError', None),
])
def test_closed_stream_persists_only_safe_exception_class_and_wire_code(tmp_path, monkeypatch, caplog,
                                                                      failure, expected, close_code):
    path = tmp_path / 'synthetic.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 160)
    sent = threading.Event()
    class Socket:
        started = False
        def send(self, data):
            if isinstance(data, bytes): sent.set()
        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({'type': 'session.started'})
            assert sent.wait(1)
            raise failure()
    @contextmanager
    def connection(*args): yield Socket()
    monkeypatch.setattr(service, 'open_recognition', connection)
    with pytest.raises(service.ASRServiceError) as caught:
        service.recognize_pcm('https://target.invalid', SECRET, 'frozen', path)
    error = caught.value
    details = failure_details(error)
    diagnostic = details['asr_failure_context']['diagnostic']
    assert diagnostic['transport_exception_class'] == expected
    assert diagnostic['ws_proxy_mode'] == 'disabled'
    assert diagnostic.get('ws_close_code') == close_code
    assert details['retryable'] is False and error.code == 'unknown_result'
    assert SECRET not in json.dumps(details) + caplog.text + repr(vars(error))
    assert 'target.invalid' not in json.dumps(details) + caplog.text
    assert 'reason' not in diagnostic and 'url' not in diagnostic
    from app.services.task_artifact_service import TaskArtifactService
    artifacts = TaskArtifactService(tmp_path / 'artifacts')
    folder = artifacts.create_task_dir('transport-fixture')
    artifacts.update_status(folder, 'failed', **details)
    saved = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    assert saved['asr_failure_context']['diagnostic'] == diagnostic
    assert saved['retryable'] is False and SECRET not in json.dumps(saved)


@pytest.mark.parametrize('value', [SECRET, 'OSError ' + SECRET, 'Custom' * 1000, {}, True, None])
def test_diagnostic_projection_rejects_unbounded_or_arbitrary_exception_and_route(value):
    result = safe_asr_failure_context({'schema_version': 1, 'diagnostic': {
        'code': 'unknown_result', 'transport_exception_class': value, 'ws_proxy_mode': value,
        'ws_close_code': 1006, 'reason': SECRET, 'url': SECRET}})['diagnostic']
    assert 'transport_exception_class' not in result and 'ws_proxy_mode' not in result
    assert 'ws_close_code' not in result and SECRET not in json.dumps(result)
