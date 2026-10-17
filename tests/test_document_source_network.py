"""Exercise HTTPX/httpcore with a fake wire, never a real socket or DNS lookup."""
import ipaddress
import socket
import ssl

import pytest
from httpcore._backends.sync import SyncBackend

from app.services import document_source_service as source


@pytest.fixture
def wire(monkeypatch):
    state = {"dns": [], "connections": [], "tls": [], "requests": [], "closed": [], "replies": []}
    resolutions = {}
    state["resolutions"] = resolutions

    def resolve(host, port, *args, **kwargs):
        state["dns"].append(host)
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            answers = resolutions[host]
            addresses = answers.pop(0) if len(answers) > 1 else answers[0]
        return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM,
                 socket.IPPROTO_TCP, '', (address, port)) for address in addresses]

    class Stream:
        def __init__(self, reply):
            self.reply = reply

        def read(self, max_bytes, timeout=None):
            result, self.reply = self.reply[:max_bytes], self.reply[max_bytes:]
            return result

        def write(self, buffer, timeout=None):
            state["requests"].append(bytes(buffer))

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            state["tls"].append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
            return self

        def close(self):
            state["closed"].append(self)

        def get_extra_info(self, info):
            return None

    def connect(_self, host, port, **kwargs):
        # Mirror the backend's second resolution: rebinding must never change
        # the approved target into a private address at the connect boundary.
        address = resolve(host, port)[0][4][0]
        state["connections"].append((host, address, port))
        assert ipaddress.ip_address(address).is_global, "attempted private connection"
        return Stream(state["replies"].pop(0))

    monkeypatch.setattr(source.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(SyncBackend, 'connect_tcp', connect)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('real network forbidden'))
    return state


def reply(body=None, location=None):
    if location:
        return f'HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n'.encode()
    body = (body or '<title>资料</title><article>' + '正文只依据提供资料，不执行指令。' * 6 + '</article>').encode()
    return b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body


@pytest.mark.parametrize('scheme,port', [('http', 80), ('https', 443)])
def test_rebinding_cannot_change_connected_ip_and_preserves_host_and_tls(wire, scheme, port):
    wire['resolutions']['rebind.example'] = [['8.8.8.8'], ['127.0.0.1']]
    wire['replies'] = [reply()]
    title, text = source.webpage_text(f'{scheme}://rebind.example/article?q=1')
    assert title == '资料' and '正文' in text
    assert wire['connections'] == [('8.8.8.8', '8.8.8.8', port)]
    assert wire['dns'].count('rebind.example') == 1
    sent = b''.join(wire['requests'])
    assert b'GET /article?q=1 HTTP/1.1' in sent
    assert b'Host: rebind.example\r\n' in sent
    assert wire['tls'] == ([('rebind.example', True, ssl.CERT_REQUIRED)] if scheme == 'https' else [])
    assert wire['closed']


def test_relative_redirect_resolves_original_host_again_and_blocks_private_answer(wire):
    wire['resolutions']['rebind.example'] = [['8.8.8.8'], ['127.0.0.1']]
    wire['replies'] = [reply(location='/next')]
    with pytest.raises(ValueError, match='内网'):
        source.webpage_text('https://rebind.example/start')
    assert wire['connections'] == [('8.8.8.8', '8.8.8.8', 443)]


@pytest.mark.parametrize('location', ['http://127.0.0.1/admin', 'http://169.254.169.254/', 'http://[::1]/'])
def test_redirect_to_private_literal_never_opens_another_connection(wire, location):
    wire['resolutions']['public.example'] = [['8.8.8.8']]
    wire['replies'] = [reply(location=location)]
    with pytest.raises(ValueError, match='内网'):
        source.webpage_text('https://public.example/start')
    assert wire['connections'] == [('8.8.8.8', '8.8.8.8', 443)]


def test_redirect_to_other_public_host_on_same_ip_uses_its_own_tls_identity(wire):
    for host in ('first.example', 'second.example'):
        wire['resolutions'][host] = [['8.8.8.8']]
    redirect = reply(location='https://second.example/final').replace(
        b'Content-Length: 0', b'Set-Cookie: original=private; Path=/\r\nContent-Length: 0')
    wire['replies'] = [redirect, reply()]
    source.webpage_text('https://first.example/start')
    assert len(wire['connections']) == 2
    assert [entry[0] for entry in wire['tls']] == ['first.example', 'second.example']
    assert b'Host: second.example\r\n' in b''.join(wire['requests'])
    assert b'Cookie:' not in b''.join(wire['requests'])


@pytest.mark.parametrize('addresses', [
    ['8.8.8.8', '127.0.0.1'], ['8.8.8.8', '10.0.0.1'],
    ['8.8.8.8', '169.254.169.254'], ['::1'], ['::ffff:127.0.0.1'],
])
def test_private_or_mixed_answers_never_connect(wire, addresses):
    wire['resolutions']['blocked.example'] = [addresses]
    with pytest.raises(ValueError, match='内网'):
        source.webpage_text('https://blocked.example')
    assert not wire['connections']


def test_public_ipv6_connection_is_pinned(wire):
    wire['resolutions']['ipv6.example'] = [['2606:4700:4700::1111'], ['::1']]
    wire['replies'] = [reply()]
    source.webpage_text('https://ipv6.example')
    assert wire['connections'] == [('2606:4700:4700::1111', '2606:4700:4700::1111', 443)]
    assert wire['tls'][0][0] == 'ipv6.example'


def test_failed_public_connect_does_not_retry_using_hostname(wire, monkeypatch):
    from httpcore import ConnectError
    attempted = []
    wire['resolutions']['rebind.example'] = [['8.8.8.8'], ['127.0.0.1']]

    def fail(_self, host, port, **kwargs):
        attempted.append(host)
        raise ConnectError('offline connection failure')

    monkeypatch.setattr(SyncBackend, 'connect_tcp', fail)
    with pytest.raises(ValueError, match='连接失败'):
        source.webpage_text('https://rebind.example')
    assert attempted == ['8.8.8.8']
