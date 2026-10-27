"""Owner/job-scoped container association, offline only."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from test_feishu_meeting_wiki import setup, OWNER, ROOT  # noqa: F401
from app.models.auth import AuthenticatedUser
from app.services.feishu_service import FeishuError, FeishuService
from app.services import feishu_meeting_wiki as wiki
from app.services import feishu_meeting_wiki_recovery as recovery
from app.routers import feishu_meeting_wiki_recovery as router


@pytest.fixture
def pending(setup, monkeypatch):
    monkeypatch.setattr(recovery, 'session_scope', setup.sessions)
    job = setup.job()
    def uncertain(*args):
        raise FeishuError('synthetic timeout', 502, uncertain=True)
    setup.service.create_at_destination = uncertain
    with pytest.raises(FeishuError):
        wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    calls = []
    def request(method, path, **kwargs):
        assert method == 'GET' and path == 'wiki/v2/spaces/get_node'
        calls.append((method, path, kwargs))
        return {'node': dict(space_id=ROOT['space_id'], parent_node_token=ROOT['node_token'],
            node_token='originalParent', obj_type='docx', node_type='origin', obj_token='doc1',
            title=recovery.read_container(setup.service, OWNER, job.id)['title'], has_child=True)}
    setup.service.request = request
    setup.service.user_token = lambda owner: 'synthetic'
    setup.job_id, setup.read_calls = job.id, calls
    return setup


def payload(state, **changes):
    return dict(expected_user_id=OWNER, confirmed=True, context_revision=state['context_revision'],
                url='https://tenant.feishu.cn/wiki/originalParent?from=copy#section', **changes)


@pytest.mark.parametrize('as_token', [False, True])
def test_read_has_no_remote_calls_and_explicit_recovery_only_uses_official_get(pending, as_token):
    state = recovery.read_container(pending.service, OWNER, pending.job_id)
    assert state['state'] == 'unknown' and state['can_recover'] is True
    assert state['root_destination'] == ROOT and not pending.read_calls
    body = payload(state)
    if as_token: body['url'] = 'originalParent'
    recovered = recovery.recover_for_delivery(pending.service, OWNER, pending.job_id, **body)
    assert recovered['state'] == 'confirmed' and not recovered['can_recover']
    assert recovered['document_url'].endswith('/wiki/originalParent')
    assert len(pending.read_calls) == 1 and 'tenant.feishu.cn' not in repr(pending.read_calls)
    assert recovery.read_container(pending.service, OWNER, pending.job_id) == recovered
    with pytest.raises(FeishuError):
        recovery.recover_for_delivery(pending.service, OWNER, pending.job_id, **payload(state))
    assert len(pending.read_calls) == 1


@pytest.mark.parametrize('damage', ['other_owner', 'body_owner', 'binding', 'revision', 'unconfirmed'])
def test_stale_or_foreign_confirmation_never_reads_provider(pending, damage):
    state = recovery.read_container(pending.service, OWNER, pending.job_id)
    owner, body = OWNER, payload(state)
    if damage == 'other_owner': owner = 'other'
    if damage == 'body_owner': body['expected_user_id'] = 'other'
    if damage == 'revision': body['context_revision'] = '0' * 64
    if damage == 'unconfirmed': body['confirmed'] = False
    if damage == 'binding':
        from app.db_models import FeishuConnectionDB
        with pending.sessions() as db:
            db.get(FeishuConnectionDB, OWNER).preferences = json.dumps({'connection_id': 'changed'})
    with pytest.raises(FeishuError):
        recovery.recover_for_delivery(pending.service, owner, pending.job_id, **body)
    assert not pending.read_calls


@pytest.mark.parametrize('state,lease,expected', [('creating', 99999999999, False),
    ('creating', 0, True), ('failed', 0, False), ('confirmed', 0, False)])
def test_read_only_projects_expired_lease_and_never_changes_original_container(pending, state, lease, expected):
    from app.models.feishu_meeting_wiki import FeishuMeetingWikiContainerDB as Container
    from sqlalchemy import select
    with pending.sessions() as db:
        row = db.scalar(select(Container)); row.state, row.lease_until = state, lease
    result = recovery.read_container(pending.service, OWNER, pending.job_id)
    assert result['can_recover'] is expected
    with pending.sessions() as db:
        row = db.scalar(select(Container)); assert (row.state, row.lease_until) == (state, lease)
    if not expected:
        with pytest.raises(FeishuError):
            recovery.recover_for_delivery(pending.service, OWNER, pending.job_id, **payload(result))
        assert not pending.read_calls


@pytest.mark.parametrize('field,value', [('space_id', 'foreign'), ('parent_node_token', 'foreign'),
    ('title', 'Other meeting'), ('node_type', 'shortcut'), ('obj_type', 'sheet'), ('node_token', 'foreign')])
def test_another_meeting_or_shadow_node_is_not_associated(pending, field, value):
    original = pending.service.request
    def changed(*args, **kwargs):
        result = original(*args, **kwargs); result['node'][field] = value
        return result
    pending.service.request = changed
    state = recovery.read_container(pending.service, OWNER, pending.job_id)
    with pytest.raises(FeishuError):
        recovery.recover_for_delivery(pending.service, OWNER, pending.job_id, **payload(state))
    assert recovery.read_container(pending.service, OWNER, pending.job_id)['state'] == 'unknown'


def test_frozen_job_change_rejects_recovery_before_remote_read(pending):
    from app.db_models import FeishuDeliveryDB
    with pending.sessions() as db:
        db.get(FeishuDeliveryDB, pending.job_id).content = 'changed'
    with pytest.raises(FeishuError): recovery.read_container(pending.service, OWNER, pending.job_id)
    assert not pending.read_calls


@pytest.mark.parametrize('url', ['http://tenant.feishu.cn/wiki/a', 'https://evil.invalid/wiki/a',
    'https://tenant.feishu.cn.evil.invalid/wiki/a', 'https://user@tenant.feishu.cn/wiki/a',
    'https://tenant.feishu.cn:444/wiki/a', 'https://tenant.feishu.cn/docx/a',
    'https://tenant.feishu.cn/wiki/a%2Fb', 'https://tenant.feishu.cn/wiki/../a',
    'https://tenant.feishu.cn/wiki/a\n', 'https://tenant.feishu.cn\\evil.invalid/wiki/a'])
def test_unsafe_input_never_fetches_tenant_or_changes_receipt(pending, url):
    state = recovery.read_container(pending.service, OWNER, pending.job_id)
    body = payload(state); body['url'] = url
    with pytest.raises(FeishuError):
        recovery.recover_for_delivery(pending.service, OWNER, pending.job_id, **body)
    assert not pending.read_calls
    assert recovery.read_container(pending.service, OWNER, pending.job_id) == state


def test_router_is_desktop_cookie_only_and_rejects_extra_authority_fields(pending, monkeypatch):
    from app.config import settings
    from app.services import feishu_cli
    monkeypatch.setattr(settings, 'desktop_runtime', True)
    monkeypatch.setattr(settings, 'workspace_cloud_runtime', False)
    monkeypatch.setattr(settings, 'content_cloud_runtime', False)
    monkeypatch.setattr(feishu_cli, 'enabled', lambda: True)
    monkeypatch.setattr(FeishuService, 'for_owner', lambda self, owner: pending.service)
    app = FastAPI(); app.include_router(router.router, prefix='/api')
    app.dependency_overrides[router.get_current_user] = lambda: AuthenticatedUser(OWNER)
    client = TestClient(app)
    path = '/api/feishu/meeting-containers/by-delivery/' + pending.job_id
    response = client.get(path); assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert client.get(path, headers={'Authorization': 'Bearer synthetic'}).status_code == 403
    assert client.post(path + '/recover', json={**payload(response.json()), 'scope_key': 'forged'}).status_code == 422
    monkeypatch.setattr(settings, 'desktop_runtime', False)
    assert client.get(path).status_code == 403
    assert not pending.read_calls
