import socket
import time

import httpx
import pytest

from app.services import document_source_service as documents
from app.services import bilibili_source_service as source

def dns(monkeypatch, addresses):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses])

def test_fake_dns_can_be_replaced_only_with_verified_public_answers(monkeypatch):
    dns(monkeypatch, ['198.18.0.19', '2001:2::21'])
    called = []
    original, target = documents._public_target('https://api.bilibili.com/x', fake_dns_resolver=lambda host: called.append(host) or ['8.8.8.8'])
    assert called == ['api.bilibili.com']
    assert target.host == '8.8.8.8' and original.host == 'api.bilibili.com'

@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['198.18.0.19', '10.0.0.1'], ['198.18.0.19', '8.8.8.8']])
def test_non_fake_or_mixed_dns_never_uses_fallback(monkeypatch, addresses):
    dns(monkeypatch, addresses)
    with pytest.raises(ValueError):
        documents._public_target('https://api.bilibili.com/x', fake_dns_resolver=lambda host: pytest.fail('fallback forbidden'))

def test_fake_dns_stays_blocked_for_generic_documents(monkeypatch):
    dns(monkeypatch, ['198.18.0.19'])
    with pytest.raises(ValueError): documents._public_target('https://example.com/')

@pytest.mark.parametrize('answer', [['127.0.0.1'], ['8.8.8.8', '10.0.0.1'], []])
def test_fallback_cannot_approve_private_or_empty_answers(monkeypatch, answer):
    dns(monkeypatch, ['198.18.0.19'])
    with pytest.raises(ValueError): documents._public_target('https://api.bilibili.com/x', fake_dns_resolver=lambda host: answer)

def test_doh_is_fixed_tls_bounded_and_does_not_receive_source_query(monkeypatch):
    client = httpx.Client
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'Status': 0, 'Question': {'name': 'api.bilibili.com.', 'type': 1}, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]})
    def factory(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        assert kwargs.get('verify', True) is True
        return client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(source.httpx, 'Client', factory)
    assert source._resolve_public_dns('api.bilibili.com', time.monotonic()+30) == ['8.8.8.8']
    assert calls[0].url.host == '223.5.5.5'
    assert dict(calls[0].url.params) == {'name': 'api.bilibili.com', 'type': 'A'}

@pytest.mark.parametrize('body', [ {'Status': 0, 'Question': {'name': 'other.example', 'type': 1}, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]}, {'Status': 2}, {'Status': 0, 'Question': {'name': 'api.bilibili.com', 'type': 1}, 'Answer': [{'type': 1, 'data': '127.0.0.1'}]} ])
def test_doh_invalid_response_is_not_accepted(monkeypatch, body):
    client = httpx.Client
    monkeypatch.setattr(source.httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), **kw))
    with pytest.raises(ValueError): source._resolve_public_dns('api.bilibili.com', time.monotonic()+30)


def test_doh_malformed_question_is_a_safe_error(monkeypatch):
    client = httpx.Client
    body = {'Status': 0, 'Question': {'name': [], 'type': 1}}
    monkeypatch.setattr(source.httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), **kw))
    with pytest.raises(ValueError): source._resolve_public_dns('api.bilibili.com', time.monotonic()+30)
