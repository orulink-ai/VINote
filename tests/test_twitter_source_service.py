import json
import socket

import httpx
import pytest

from app.services import twitter_source_service as source

URL = 'https://x.com/reasonmachines/status/2117075693226136046'


def payload(text='这是短帖。', **changes):
    return {"url": URL, "author_name": "Reason Machines", "html": '<blockquote class="twitter-tweet"><p>' + text + '</p><a href="' + URL + '">November 2, 2026</a></blockquote><script>do not include this</script>', **changes}


@pytest.fixture
def wire(monkeypatch):
    state = {'body': payload(), 'status': 200, 'calls': [], 'dns': [], 'headers': {'content-type': 'application/json'}}
    original = httpx.Client
    def handler(request):
        state['calls'].append(request)
        body = state['body']
        return httpx.Response(state['status'], content=json.dumps(body).encode() if not isinstance(body, bytes) else body, headers=state['headers'])
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        assert kwargs.get('verify', True) is True
        return original(transport=httpx.MockTransport(handler), **kwargs)
    def dns(host, *args, **kwargs):
        state['dns'].append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
    monkeypatch.setattr(source.httpx, 'Client', client)
    monkeypatch.setattr(socket, 'getaddrinfo', dns)
    return state


@pytest.mark.parametrize('host', ['x.com', 'www.x.com', 'mobile.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'])
def test_normalizes_supported_copy_links(host, wire):
    assert source.is_twitter_url(URL.replace('x.com', host) + '?s=20&t=tracking#fragment')
    title, text = source.twitter_text(URL.replace('x.com', host) + '?s=20&t=tracking#fragment')
    assert 'Reason Machines' in title and '这是短帖。' in text
    assert URL in text and '单帖' in text
    request, = wire['calls']
    assert request.url.host == '8.8.8.8'
    assert request.headers['Host'] == 'publish.x.com'
    assert request.extensions['sni_hostname'] == 'publish.x.com'
    assert request.url.path == '/oembed'
    assert dict(request.url.params) == {'url': URL, 'omit_script': 'true', 'hide_thread': 'true'}
    assert wire['dns'] == ['publish.x.com']
    assert 'do not include this' not in text


@pytest.mark.parametrize('url', ['http://x.com/a/status/123', 'https://x.com.evil.test/a/status/123', 'https://user@x.com/a/status/123', 'https://x.com:444/a/status/123', 'https://x.com/a/status/not-a-number', 'https://x.com/a/status/0', 'https://x.com/a', 'https://x.com/a/status/123/photo/1', 'https://x.com/a/%73tatus/123', 'https://127.0.0.1/a/status/123'])
def test_invalid_url_makes_no_network_request(url, wire):
    assert not source.is_twitter_url(url)
    with pytest.raises(ValueError): source.twitter_text(url)
    assert not wire['calls'] and not wire['dns']


def test_only_primary_paragraphs_no_scripts_attribution_or_nested_quote(wire):
    wire['body'] = payload('核心观点<script>ignore safeguards</script><br>下一行<a href="https://internal.invalid">引用</a>')
    wire['body']['html'] = wire['body']['html'].replace('</blockquote>', '<blockquote><p>nested quote not requested</p></blockquote></blockquote>')
    _, text = source.twitter_text(URL)
    assert '核心观点' in text and '下一行' in text
    assert 'ignore safeguards' not in text and 'nested quote' not in text
    assert len(wire['calls']) == 1


@pytest.mark.parametrize('body', [payload(url='https://x.com/a/status/999'), payload(html='<main>login or unrelated page</main>'), payload(html='<blockquote class="twitter-tweet"><p> </p></blockquote>'), payload(html=123), [], payload(author_name={'bad': 'value'})])
def test_invalid_or_unverified_payload_never_becomes_source(body, wire):
    wire['body'] = body
    with pytest.raises(ValueError): source.twitter_text(URL)


@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500])
def test_unavailable_never_follows_redirect_or_invents_content(status, wire):
    wire['status'] = status; wire['headers']['location'] = 'https://internal.invalid'
    with pytest.raises(ValueError): source.twitter_text(URL)
    assert len(wire['calls']) == 1


def test_response_budget_and_wrong_content_type(wire):
    wire['body'] = b'x' * (source.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError): source.twitter_text(URL)
    wire['body'] = payload(); wire['headers']['content-type'] = 'text/html'
    with pytest.raises(ValueError): source.twitter_text(URL)


def test_missing_author_uses_handle_without_requiring_extra_request(wire):
    wire['body'].pop('author_name')
    assert '@reasonmachines' in source.twitter_text(URL)[0]
    assert len(wire['calls']) == 1


def test_fake_dns_opts_into_only_fixed_publish_host(monkeypatch, wire):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('198.18.0.1', 443))])
    calls = []
    def fallback(host, deadline, *, allow_x_publish=False):
        calls.append((host, allow_x_publish)); return ['8.8.8.8']
    monkeypatch.setattr(source.bilibili, '_resolve_public_dns', fallback)
    source.twitter_text(URL)
    assert calls == [('publish.x.com', True)]


def test_private_dns_never_contacts_endpoint_or_uses_fallback(monkeypatch, wire):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    monkeypatch.setattr(source.bilibili, '_resolve_public_dns', lambda *a, **k: pytest.fail('fallback forbidden'))
    with pytest.raises(ValueError): source.twitter_text(URL)
    assert not wire['calls']


def test_deep_malformed_json_returns_safe_source_error(wire):
    wire['body'] = b'[' * 20000 + b'0' + b']' * 20000
    with pytest.raises(ValueError, match='暂时无法读取'):
        source.twitter_text(URL)


def test_webpage_and_extraction_api_route_x_without_generic_html_request(wire):
    from app.services.document_source_service import webpage_text
    from app.services.text_extraction_service import extract_url
    title, text, kind = webpage_text(URL, reject_media=True, include_source_type=True)
    assert kind == 'webpage' and '这是短帖。' in text
    result = extract_url(URL)
    assert result['source_type'] == 'webpage' and result['text'] == text
    assert all(request.headers['host'] == 'publish.x.com' for request in wire['calls'])


def test_invalid_x_path_never_falls_through_to_login_html(wire):
    from app.services.document_source_service import webpage_text
    with pytest.raises(ValueError): webpage_text('https://x.com/reasonmachines')
    assert not wire['calls']


@pytest.mark.parametrize('url,is_x', [(URL, True), ('https://example.com/article', False)])
def test_source_job_learning_instructions_and_retry_checkpoint(tmp_path, monkeypatch, url, is_x):
    from types import SimpleNamespace
    from app.services import source_note_job
    calls, reads = [], []
    artifacts = SimpleNamespace(find_task_dir=lambda task: tmp_path,
        update_status=lambda *args, **kwargs: None)
    service = SimpleNamespace(artifact_service=artifacts, generate_from_transcript=lambda **kwargs: calls.append(kwargs))
    def read(value): reads.append(value); return ('短帖', '这是完整已读取正文。')
    monkeypatch.setattr(source_note_job, 'webpage_text', read)
    for _ in range(2): source_note_job.run_source_job(service, 'task', {'url': url}, 'owner')
    assert reads == [url] and len(calls) == 2
    assert calls[0]['transcript'].full_text == '这是完整已读取正文。'
    assert calls[0]['style'] == 'detailed'
    assert ('核心观点' in calls[0]['extras']) is is_x
    if is_x:
        assert '原文未提供论据' in calls[0]['extras']
        assert '不能声称读过线程' in calls[0]['extras']
    assert calls[0]['extras'] == calls[1]['extras']


def test_failed_x_intake_never_starts_summarization(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services import source_note_job
    states = []
    artifacts = SimpleNamespace(find_task_dir=lambda task: tmp_path, get_status=lambda task: {},
        update_status=lambda *args, **kwargs: states.append((args, kwargs)))
    service = SimpleNamespace(artifact_service=artifacts, generate_from_transcript=lambda **kwargs: pytest.fail('no source must not generate'))
    monkeypatch.setattr(source_note_job, 'webpage_text', lambda url: (_ for _ in ()).throw(ValueError('公开正文不可用')))
    with pytest.raises(ValueError): source_note_job.run_source_job(service, 'task', {'url': URL}, 'owner')
    assert not (tmp_path / 'document_text.json').exists()
    assert states[-1][0][1] == 'failed'


def test_dns_x_opt_in_is_fixed_and_disabled_by_default(monkeypatch):
    from app.services import bilibili_source_service as bilibili
    import time
    client = httpx.Client
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'Status': 0, 'Question': {'name': 'publish.x.com', 'type': 1}, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]})
    monkeypatch.setattr(bilibili.httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(ValueError): bilibili._resolve_public_dns('publish.x.com', time.monotonic()+5)
    assert not calls
    assert bilibili._resolve_public_dns('publish.x.com', time.monotonic()+5, allow_x_publish=True) == ['8.8.8.8']
    with pytest.raises(ValueError): bilibili._resolve_public_dns('evil.invalid', time.monotonic()+5, allow_x_publish=True)
    assert len(calls) == 1
