"""HTTP save through the real CLI service; only CLI execution is simulated.

No orchestration, source/grouping, policy, permission, body or notification
method is replaced. All state is in temporary SQLite/artifacts. No real I/O.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.db_models import FeishuConnectionDB, FeishuDeliveryDB
from app.models.auth import AuthenticatedUser
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuWriteBatchDB
from app.models.feishu_meeting_wiki import FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB
from app.routers import feishu, feishu_auto_local, note_library
from app.services import (feishu_service, feishu_cli_service, feishu_cli as cli,
                          feishu_auto_policy,
                          feishu_auto_runtime as runtime, feishu_auto_outbox as outbox,
                          feishu_meeting_wiki as wiki, feishu_object_hotwords as hotwords,
                          note_repository)
from app.services.cloud_account_service import _cipher
from app.services.feishu_cli_service import FeishuCLIService
from app.services.feishu_service import FeishuError
from app.services.task_artifact_service import TaskArtifactService


OWNER, CONTACT = 'alice', 'ou_synthetic_contact'
ROOT = dict(kind='wiki', space_id='synthetic_space', node_token='synthetic_root')


@pytest.fixture
def chain(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Real subprocess/network/provider execution is forbidden')

    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    for name, value in dict(desktop_runtime=True, feishu_transport='cli',
                            content_cloud_runtime=False, workspace_cloud_runtime=False,
                            feishu_service_url='', model_profile_encryption_key='synthetic-chain-key',
                            output_dir=tmp_path / 'output').items():
        monkeypatch.setattr(settings, name, value)
    engine = create_engine('sqlite:///' + (tmp_path / 'chain.db').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    for module in (feishu_service, feishu_cli_service, runtime, outbox, wiki, note_repository, feishu):
        monkeypatch.setattr(module, 'session_scope', scope)
    monkeypatch.setattr(runtime, 'background_ready', lambda: True)
    monkeypatch.setattr(runtime, 'wake', lambda: None)  # Test explicitly advances bounded dispatcher passes.
    monkeypatch.setattr(cli, 'executable', lambda: 'synthetic-lark-cli')
    instance = FeishuCLIService(OWNER)
    monkeypatch.setattr(feishu, 'service', instance)
    monkeypatch.setattr(hotwords, 'service', hotwords.FeishuObjectHotwordsService(
        binding_provider=lambda owner: instance.contact_binding(owner),
        cli_enabled=cli.enabled, session_factory=scope))
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    scopes = 'contact:user:search docx:document wiki:wiki drive:drive im:message'
    identity = dict(appId='cli_synthetic', brand='feishu', identities={'user': dict(
        openId='ou_sender', tokenStatus='valid', expiresAt=expiry, scope=scopes)})
    with scope() as db:
        db.add(FeishuConnectionDB(owner=OWNER, open_id='ou_sender', expired=False,
            tokens=_cipher().encrypt(json.dumps(dict(transport='cli', app_id='cli_synthetic',
                tenant_key='synthetic_tenant', scope=scopes,
                expires_at=datetime.fromisoformat(expiry).timestamp())).encode()).decode(),
            preferences=json.dumps(dict(connection_id='synthetic_connection'))))
    c = SimpleNamespace(service=instance, scope=scope, artifacts=TaskArtifactService(),
        events=[], calls=[], mode='success', can_edit=True, permissions_read=set(), readable=set(),
        nodes={ROOT['node_token']: dict(node_token=ROOT['node_token'], space_id=ROOT['space_id'],
            node_type='origin', obj_type='docx', obj_token='root_doc', parent_node_token='', title='Synthetic root')})

    def api(method, path, body, params):
        if method == 'GET' and path == 'authen/v1/user_info':
            return dict(open_id='ou_sender', tenant_key='synthetic_tenant', name='Synthetic sender')
        if method == 'GET' and path == 'search/v1/user':
            return dict(users=[dict(open_id=CONTACT, name='Synthetic contact')], has_more=False)
        if method == 'GET' and path == 'wiki/v2/spaces/get_node':
            return dict(node=deepcopy(c.nodes[params['token']]))
        if method == 'GET' and path == f"wiki/v2/spaces/{ROOT['space_id']}":
            return dict(space={'name': 'Synthetic space'})
        if method == 'GET' and path.endswith('/members/auth'):
            c.events.append(('check_edit', params['action'], c.can_edit))
            return dict(auth_result=c.can_edit)
        if method == 'POST' and path == f"wiki/v2/spaces/{ROOT['space_id']}/nodes":
            parent = body['parent_node_token']
            kind = 'create_parent' if parent == ROOT['node_token'] else 'create_child'
            assert c.can_edit and parent in c.nodes
            with scope() as db:
                container = db.scalar(select(FeishuMeetingWikiContainerDB))
                assert container is not None
                if kind == 'create_parent':
                    assert container.state == 'creating'
                else:
                    assert container.state == 'confirmed' and parent == container.node_token
                assert db.scalar(select(FeishuMeetingWikiChildDB)) is not None
            index = 1 + sum(e[0] == kind for e in c.events)
            node = dict(node_token=f'{kind}_{index}', space_id=ROOT['space_id'], node_type='origin',
                obj_type='docx', obj_token=f'{kind}_doc_{index}', parent_node_token=parent, title=body['title'])
            c.nodes[node['node_token']] = node
            c.events.append((kind, node['obj_token'], parent, body['title']))
            return dict(node=deepcopy(node))
        if '/permissions/' in path and path.endswith('/public'):
            document = path.split('/')[3]
            # Wiki inherits its container's scope; do not fabricate a private
            # policy or silently bypass production's destination restriction.
            assert method == 'GET'
            if document.startswith('create_child_doc_'):
                c.permissions_read.add(document)
                c.events.append(('permission_read', document))
            return dict(permission_public=dict(external_access_entity='closed', link_share_entity='closed'))
        if method == 'POST' and path.startswith('docx/v1/documents/') and path.endswith('/children'):
            document = path.split('/')[3]
            assert document in c.permissions_read
            c.events.append(('body', document, deepcopy(body)))
            return dict(children=[{'block_id': f'block_{i}'} for i, _ in enumerate(body['children'])])
        if '/permissions/' in path and path.endswith('/members'):
            document = path.split('/')[3]
            if method == 'POST':
                assert params['need_notification'] == 'false'
                assert body == dict(member_type='openid', member_id=CONTACT, perm='view')
                assert any(e[0] == 'body' and e[1] == document for e in c.events)
                c.readable.add((document, CONTACT))
                c.events.append(('grant_view', document, CONTACT))
                return {}
            assert method == 'GET'
            c.events.append(('verify_reading', document))
            return dict(items=[dict(member_type='openid', member_id=target, perm='view')
                for doc, target in c.readable if doc == document])
        if method == 'POST' and path == 'im/v1/messages':
            assert body['receive_id'] == CONTACT and params['receive_id_type'] == 'open_id'
            post = json.loads(body['content'])['zh_cn']
            url = post['content'][1][0]['href']
            node = c.nodes[url.rsplit('/', 1)[-1]]
            assert (node['obj_token'], CONTACT) in c.readable
            c.events.append(('notify', node['obj_token'], body['uuid']))
            if c.mode == 'definite_notify_failure':
                raise FeishuError('Synthetic notification refused', 403, code='permission_denied')
            if c.mode == 'unknown_notify':
                raise FeishuError('Synthetic ambiguous notification', 502, uncertain=True)
            return dict(message_id='om_' + str(len(c.events)))
        raise AssertionError(f'Unexpected fake CLI API: {method} {path}')

    def run(owner, args, *, body=None, credential_identity=None, **kwargs):
        assert owner == OWNER
        if args == ['auth', 'status', '--json']:
            return deepcopy(identity)
        assert args[:1] == ['api'] and args[2].startswith('/open-apis/')
        assert args[args.index('--as') + 1] == 'user'
        assert credential_identity == dict(app_id='cli_synthetic', open_id='ou_sender')
        method, path = args[1], args[2][len('/open-apis/'):]
        if method != 'GET':
            execution = feishu_auto_policy.active_delivery.get()
            assert execution is not None and execution[0] == OWNER
            with scope() as db:
                account = db.get(FeishuConnectionDB, OWNER)
                prefs = json.loads(account.preferences)
                assert execution[1]['automatic_policy_id'] == prefs['auto_policy']['id']
                assert execution[1]['connection_id'] == prefs['connection_id']
                assert execution[1]['open_id'] == account.open_id
        params = json.loads(args[args.index('--params') + 1]) if '--params' in args else {}
        c.calls.append((method, path, deepcopy(body), deepcopy(params)))
        return dict(ok=True, identity='user', data=api(method, path, body, params))

    monkeypatch.setattr(cli, 'run', run)
    monkeypatch.setattr(note_library, '_artifact_service', c.artifacts)
    app = FastAPI()
    for router in (feishu.router, note_library.router, feishu_auto_local.router):
        app.include_router(router, prefix='/api')
    # Only the authenticated test account is injected; Feishu identity, grants,
    # selection proofs, saved policy and every mutation guard run unchanged.
    app.dependency_overrides[feishu.principal] = lambda: (OWNER, OWNER)
    app.dependency_overrides[note_library.get_current_user] = lambda: AuthenticatedUser(user_id=OWNER)
    c.canonical = str(uuid4())
    original = c.artifacts.create_task_dir(c.canonical)
    for name, value in {'.task_id': c.canonical, 'recording_owner': OWNER,
        'request.json': json.dumps(dict(request=dict(workflow='meeting'))),
        'source_media.json': json.dumps(dict(sha256=hashlib.sha256(b'synthetic original').hexdigest()))}.items():
        (original / name).write_text(value, encoding='utf-8')
    with TestClient(app) as client:
        c.client = client
        chosen = client.get('/api/feishu/contacts', params={'query': 'Synthetic'}).json()['items'][0]
        response = client.put('/api/feishu/preferences', json=dict(notify_self=False, groups=[],
            auto_publish=True, automatic_delivery_consent=True, group_meeting_versions=True,
            contacts=[{key: chosen[key] for key in ('open_id', 'selection_token')}],
            destination_config=ROOT, permission_policy='inherit'))
        assert response.status_code == 200, response.text
        assert response.json()['device_auto_enabled'] is True
        assert c.events and all(event[0] == 'check_edit' for event in c.events)
        c.events.clear()
        yield c
    engine.dispose()


def save(c, *, form='text', depth='brief'):
    task = str(uuid4())
    folder = c.artifacts.create_task_dir(task)
    for name, value in {'.task_id': task, 'recording_owner': OWNER, 'generation_client': 'desktop',
        'request.json': json.dumps(dict(request=dict(workflow='meeting'))),
        'status.json': json.dumps(dict(status='success')),
        'source_reference.json': json.dumps(dict(version=1, owner=OWNER, parent_task_id=c.canonical,
            source_version=hashlib.sha256(b'synthetic original').hexdigest())),
        'summary_presentation.json': json.dumps(dict(protocol=1, task_id=task,
            presentation=form, content_depth=depth))}.items():
        (folder / name).write_text(value, encoding='utf-8')
    body = '# Synthetic minutes\nKeep the supported condition before acting.'
    response = c.client.post('/api/notes', json=dict(title='Synthetic saved meeting', content=body,
        source_type='meeting_recording', status='done', task_id=task))
    assert response.status_code == 201, response.text
    note = response.json()['id']
    local = c.client.get('/api/feishu/automatic-deliveries/local/' + note).json()
    assert local['status'] == 'queued'
    return note, local['operation_id'], body


@pytest.mark.parametrize('mode', ['success', 'definite_notify_failure', 'unknown_notify'])
def test_actual_saved_minutes_outbox_wiki_body_and_notification_chain(chain, mode):
    c = chain
    note, operation, body = save(c)
    assert c.events == []  # Saving commits an intent, never remote work.
    c.mode = mode
    runtime.run_once()
    current = c.client.get('/api/feishu/automatic-deliveries/local/' + note).json()
    assert current['status'] == 'accepted' and current['operation_id'] == operation
    job_id = current['job_id']
    result = c.client.get('/api/feishu/deliveries/by-id/' + job_id).json()
    expected = {'success': 'completed', 'definite_notify_failure': 'partial_success', 'unknown_notify': 'unknown'}
    assert result['phase'] == expected[mode], json.dumps(
        dict(result=result, events=c.events, recent_calls=c.calls[-8:]), ensure_ascii=False)
    kinds = [e[0] for e in c.events]
    assert kinds.count('create_parent') == kinds.count('create_child') == kinds.count('body') == kinds.count('notify') == 1
    assert kinds.index('create_parent') < kinds.index('create_child') < kinds.index('permission_read') < kinds.index('body')
    assert kinds.index('body') < kinds.index('grant_view') < kinds.index('notify')
    assert 'verify_reading' in kinds[kinds.index('grant_view') + 1:kinds.index('notify')]
    written = next(e[2]['children'] for e in c.events if e[0] == 'body')
    assert [block['block_type'] for block in written] == [3, 2]
    assert written[0]['heading1']['elements'] == [{'text_run': {'content': 'Synthetic minutes'}}]
    assert written[1]['text']['elements'] == [
        {'text_run': {'content': 'Keep the supported condition before acting.'}}]
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, job_id)
        assert job.owner == OWNER and job.content == body and job.written_blocks != '0'
        container = db.scalar(select(FeishuMeetingWikiContainerDB))
        child = db.get(FeishuMeetingWikiChildDB, job_id)
        assert container.state == 'confirmed' and child.scope_key == container.scope_key
        assert child.title == '文字·摘要｜V1' and child.summary_format == 'text:brief'
        assert json.loads(child.snapshot)['canonical_task_id'] == c.canonical
        assert db.scalar(select(FeishuWriteBatchDB)).state == 'confirmed'
        frozen_snapshot = db.get(FeishuDeliveryDestinationDB, job_id).snapshot
    mutations = [call for call in c.calls if call[0] != 'GET']
    runtime.run_once()
    runtime.run_once()
    assert [call for call in c.calls if call[0] != 'GET'] == mutations
    if mode == 'definite_notify_failure':
        c.mode = 'success'
        retried = c.client.post(f'/api/feishu/deliveries/{job_id}/retry', json={'recipients': [CONTACT]})
        assert retried.status_code == 200, retried.text
        assert c.client.get('/api/feishu/deliveries/by-id/' + job_id).json()['phase'] == 'completed'
        assert [e[0] for e in c.events].count('notify') == 2
    elif mode == 'unknown_notify':
        retried = c.client.post(f'/api/feishu/deliveries/{job_id}/retry', json={'recipients': [CONTACT]})
        assert retried.status_code == 409
        assert [call for call in c.calls if call[0] != 'GET'] == mutations
    assert [e[0] for e in c.events].count('create_parent') == 1
    assert [e[0] for e in c.events].count('create_child') == 1
    assert [e[0] for e in c.events].count('body') == 1
    with c.scope() as db:
        assert db.get(FeishuDeliveryDestinationDB, job_id).snapshot == frozen_snapshot
        assert db.query(FeishuAutoOutboxDB).count() == 1
    if mode == 'success':
        for form, expected_title in [('text', '文字·摘要｜V2'), ('html', 'HTML·摘要｜V1')]:
            other, _, _ = save(c, form=form)
            runtime.run_once()
            receipt = c.client.get('/api/feishu/automatic-deliveries/local/' + other).json()
            with c.scope() as db:
                child = db.get(FeishuMeetingWikiChildDB, receipt['job_id'])
                assert child.scope_key == container.scope_key and child.title == expected_title
        assert [e[0] for e in c.events].count('create_parent') == 1
        assert [e[0] for e in c.events].count('create_child') == 3


@pytest.mark.parametrize('revocation', ['edit_permission', 'connection'])
def test_saved_wiki_intent_cannot_bypass_revoked_authority(chain, revocation):
    c = chain
    note, operation, _ = save(c)
    if revocation == 'edit_permission':
        c.can_edit = False
    else:
        with c.scope() as db:
            account = db.get(FeishuConnectionDB, OWNER)
            prefs = json.loads(account.preferences)
            prefs['connection_id'] = 'different_connection'
            account.preferences = json.dumps(prefs)
    runtime.run_once()
    local = c.client.get('/api/feishu/automatic-deliveries/local/' + note).json()
    assert local['operation_id'] == operation and local['status'] == 'failed' and not local['job_id']
    assert not any(e[0] in {'create_parent', 'create_child', 'body', 'grant_view', 'notify'} for e in c.events)
    with c.scope() as db:
        assert db.query(FeishuDeliveryDB).count() == 0
        assert db.query(FeishuMeetingWikiContainerDB).count() == 0
