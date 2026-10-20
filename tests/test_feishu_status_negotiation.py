"""Display negotiation only; synthetic authenticated HTTP and no network."""
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import feishu
from app.services import feishu_service as module
from test_feishu_auto_policy import enable
from test_feishu_contacts import contact_service  # noqa: F401
from test_feishu_delivery import service  # noqa: F401


@pytest.fixture
def negotiated_client(contact_service, monkeypatch):
    runtime = SimpleNamespace(background_ready=lambda: True, wake=Mock(), bind_device_policy=Mock(),
        guard_manual_publish=Mock(), decorate_status=Mock(side_effect=lambda identity, result: result))
    monkeypatch.setitem(sys.modules, 'app.services.feishu_auto_runtime', runtime)
    enable(contact_service, monkeypatch)
    monkeypatch.setattr(feishu, 'service', contact_service)
    monkeypatch.setattr(contact_service, 'for_owner', lambda owner: contact_service)
    monkeypatch.setattr(module.settings, 'feishu_service_url', '')
    monkeypatch.setattr(module.settings, 'workspace_cloud_runtime', True)
    monkeypatch.setattr(feishu, 'cloud_owner', lambda subject: 'a')
    verify = Mock(return_value={'id': 'synthetic-subject', 'email_confirmed_at': 'confirmed'})
    monkeypatch.setattr(feishu, '_request', verify)
    app = FastAPI()
    app.include_router(feishu.router, prefix='/api')
    with TestClient(app) as client:
        yield client, runtime, verify


@pytest.mark.parametrize('protocol', [None, '0', 'true', '2', '1'])
def test_bearer_status_negotiates_only_automatic_display(contact_service, negotiated_client, protocol):
    client, _, verify = negotiated_client
    internal = contact_service.status('a')
    assert internal['auto_publish'] and internal['capabilities']['background_delivery']
    headers = {'Authorization': 'Bearer synthetic-owner-token'}
    if protocol is not None:
        headers['X-VINote-Automatic-Delivery'] = protocol
    response = client.get('/api/feishu/status', headers=headers)
    assert response.status_code == 200
    expected = internal if protocol == '1' else {**internal, 'auto_publish': False,
        'capabilities': {**internal['capabilities'], 'background_delivery': False}}
    # All manual capabilities, verified contacts and policy fields stay intact.
    assert response.json() == expected
    assert response.json()['contacts'] == [{'open_id': 'ou_b', 'name': '同名联系人'}]
    assert contact_service.status('a') == internal
    verify.assert_called_once_with('user', token='synthetic-owner-token')


def test_negotiation_header_does_not_authenticate(negotiated_client):
    client, _, verify = negotiated_client
    response = client.get('/api/feishu/status', headers={'X-VINote-Automatic-Delivery': '1'})
    assert response.status_code == 401
    verify.assert_not_called()


def test_cookie_status_without_header_uses_device_overlay(negotiated_client, contact_service):
    client, runtime, _ = negotiated_client
    client.app.dependency_overrides[feishu.principal] = lambda: ('a', 'local-a')
    internal = contact_service.status('a')
    overlay = {**internal, 'auto_publish': False, 'device_auto_enabled': False}
    runtime.decorate_status.return_value = overlay
    runtime.decorate_status.side_effect = None
    response = client.get('/api/feishu/status')
    assert response.status_code == 200 and response.json() == overlay
    runtime.decorate_status.assert_called_once_with(('a', 'local-a'), internal)


@pytest.mark.parametrize('method,path,body', [
    ('GET', '/api/feishu/status', None),
    ('PUT', '/api/feishu/preferences', {'auto_publish': False}),
    ('POST', '/api/feishu/deliveries', {'note_key': 'synthetic-note', 'title': 'Title', 'content': 'Body'}),
])
def test_proxy_adds_fixed_protocol_without_forwarding_source_headers(negotiated_client, monkeypatch, method, path, body):
    client, _, _ = negotiated_client
    client.app.dependency_overrides[feishu.principal] = lambda: ('a', 'local-a')
    monkeypatch.setattr(module.settings, 'feishu_service_url', 'https://synthetic-integration.example')
    monkeypatch.setattr(feishu.CloudAccountService, 'access_token', lambda self, owner: 'owned-session-token')
    outbound = Mock(return_value=SimpleNamespace(is_success=True, json=lambda: {'synthetic': 'remote-result'}))
    monkeypatch.setattr(feishu.httpx, 'request', outbound)
    response = client.request(method, path, json=body, headers={
        'Authorization': 'Bearer incoming-token', 'X-VINote-Automatic-Delivery': '0',
        'X-Arbitrary-Source': 'synthetic-private-header', 'Cookie': 'session=synthetic-cookie'})
    assert response.status_code == 200
    outbound.assert_called_once()
    args, kwargs = outbound.call_args
    assert args == (method, 'https://synthetic-integration.example' + path)
    assert kwargs['headers'] == {'Authorization': 'Bearer owned-session-token',
                                 'X-VINote-Automatic-Delivery': '1'}


def test_automatic_post_is_not_gated_by_display_header(contact_service, negotiated_client):
    client, runtime, _ = negotiated_client
    chosen = contact_service.status('a')['automatic_delivery']['policy_id']
    response = client.post('/api/feishu/automatic-deliveries',
        headers={'Authorization': 'Bearer synthetic-owner-token'}, json={
            'operation_id': str(uuid.uuid4()), 'policy_id': chosen, 'note_key': 'synthetic-new-note',
            'title': 'Title', 'content': 'Complete synthetic minutes'})
    assert response.status_code == 200 and response.json()['automatic_policy_id'] == chosen
    runtime.wake.assert_called_once()
