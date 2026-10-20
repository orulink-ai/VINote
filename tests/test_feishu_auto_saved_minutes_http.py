"""Actual HTTP save/policy/receipt chain in SQLite; Feishu itself is stubbed.

This proves product wiring, not a real provider delivery or ASR/LLM acceptance.
"""
import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.auth import AuthenticatedUser
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
from app.routers import feishu, note_library, feishu_auto_local
from app.services import (feishu_service as module, note_repository,
                          feishu_auto_outbox as outbox, feishu_auto_runtime as runtime)
from app.services.task_artifact_service import TaskArtifactService
from test_feishu_contacts import contact_service  # noqa: F401
from test_feishu_delivery import service  # noqa: F401


@pytest.mark.parametrize('lost_response', [False, True])
def test_confirm_preferences_save_minutes_dispatch_readback_edit_reopen_and_disable(
        contact_service, monkeypatch, tmp_path, lost_response):
    instance, events, accepted = contact_service, [], []
    from app.services import feishu_cli
    monkeypatch.setattr(feishu_cli, 'enabled', lambda: True)
    monkeypatch.setattr(settings, 'feishu_service_url', '')
    monkeypatch.setattr(settings, 'output_dir', tmp_path / 'output')
    monkeypatch.setattr(note_repository, 'session_scope', module.session_scope)
    monkeypatch.setattr(outbox, 'session_scope', module.session_scope)
    monkeypatch.setattr(runtime, 'session_scope', module.session_scope)
    monkeypatch.setattr(runtime, 'background_ready', lambda: True)
    monkeypatch.setattr(module.FeishuService, 'for_owner', lambda self, owner: instance)
    monkeypatch.setattr(feishu, 'service', instance)
    artifacts = TaskArtifactService()
    monkeypatch.setattr(note_library, '_artifact_service', artifacts)
    original_enqueue = instance.enqueue_automatic

    def enqueue(owner, **body):
        accepted.append(body['operation_id'])
        result = original_enqueue(owner, **body)
        if lost_response:
            raise module.FeishuError('Synthetic response lost after committed receipt', 502, uncertain=True)
        return result

    monkeypatch.setattr(instance, 'enqueue_automatic', enqueue)
    readable = set()

    def provider(method, path, **kw):
        if (method, path) == ('GET', 'search/v1/user'):
            return {'users': [{'open_id': 'ou_contact', 'name': 'Synthetic contact'}], 'has_more': False}
        if path == 'drive/v1/permissions/doc-auto/members':
            if method == 'POST':
                assert kw['body']['perm'] == 'view'
                readable.add(kw['body']['member_id'])
                events.append('grant_view')
                return {}
            if method == 'GET':
                events.append('verify_reading')
                return {'items': [{'member_type': 'openid', 'member_id': target, 'perm': 'view'} for target in readable]}
        raise AssertionError('Unexpected provider path: ' + method + ' ' + path)

    monkeypatch.setattr(instance, 'request', provider)
    monkeypatch.setattr(instance, 'create_at_destination', lambda *a: events.append('create') or
                        ('doc-auto', 'https://company.feishu.cn/docx/doc-auto'))
    monkeypatch.setattr(instance, 'ensure_permission', lambda *a: events.append('private') or {'status': 'verified'})
    monkeypatch.setattr(instance, 'write_document', lambda *a: events.append('body'))

    def notify(owner, target, job):
        assert target == 'ou_contact' and target in readable
        events.append('notify')
        return 'om-synthetic'

    monkeypatch.setattr(instance, 'send_message', notify)
    app = FastAPI()
    app.include_router(feishu.router, prefix='/api')
    app.include_router(note_library.router, prefix='/api')
    app.include_router(feishu_auto_local.router, prefix='/api')
    app.dependency_overrides[feishu.principal] = lambda: ('a', 'a')
    app.dependency_overrides[note_library.get_current_user] = lambda: AuthenticatedUser(user_id='a')
    with TestClient(app) as client:
        contact = client.get('/api/feishu/contacts', params={'query': 'Synthetic'}).json()['items'][0]
        prefs = dict(notify_self=False, groups=[], auto_publish=True,
                     contacts=[{k: contact[k] for k in ('open_id', 'selection_token')}],
                     destination_config={'kind': 'personal'}, automatic_delivery_consent=True)
        enabled = client.put('/api/feishu/preferences', json=prefs)
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()['auto_publish'] and enabled.json()['device_auto_enabled']
        assert enabled.json()['contacts'] == [{'open_id': 'ou_contact', 'name': 'Synthetic contact'}]
        assert events == []

        task = str(uuid.uuid4())
        folder = artifacts.create_task_dir(task)
        for name, value in [('.task_id', task), ('recording_owner', 'a'), ('generation_client', 'desktop'),
                            ('request.json', json.dumps({'request': {'workflow': 'meeting'}}))]:
            (folder / name).write_text(value, encoding='utf-8')
        artifacts.update_status(folder, 'success', 'Synthetic completed pipeline fixture')
        payload = dict(title='VINote synthetic acceptance', content='Explicit synthetic saved minutes.',
                       source_type='meeting_recording', status='done', task_id=task)
        created = client.post('/api/notes', json=payload)
        assert created.status_code == 201, created.text
        note = created.json()['id']
        local = '/api/feishu/automatic-deliveries/local/' + note
        assert client.get(local).json()['status'] == 'queued'
        assert events == []  # Saving did not invoke the provider or wait for it.
        runtime.run_once()
        assert events.count('create') == events.count('notify') == 1
        assert events.index('body') < events.index('grant_view') < events.index('notify')
        if lost_response:
            assert client.get(local).json()['status'] == 'unknown'
            blocked = client.post('/api/feishu/deliveries', json={
                'operation_id': 'new-manual', 'note_key': note, 'title': payload['title'],
                'content': payload['content'], 'source_mode': 'local_snapshot'})
            assert blocked.status_code == 409
            checked = client.post(local + '/check')
            assert checked.status_code == 200 and checked.json()['status'] == 'accepted'
        current = client.get(local).json()
        assert current['status'] == 'accepted' and current['job_id']
        assert client.get('/api/feishu/deliveries/by-id/' + current['job_id']).json()['status'] == 'completed'
        runtime.run_once()
        assert accepted == [current['operation_id']]
        assert events.count('create') == events.count('notify') == 1
        assert client.post('/api/notes', json=payload).json()['id'] == note
        assert client.patch('/api/notes/' + note, json={'content': 'Later explicit edit'}).status_code == 200
        assert client.get('/api/notes/' + note).json()['content'] == 'Later explicit edit'
        runtime.run_once()
        assert events.count('notify') == 1
        assert client.put('/api/feishu/preferences', json={
            'notify_self': False, 'groups': [], 'auto_publish': False,
            'contacts': [{'open_id': 'ou_contact'}], 'destination_config': {'kind': 'personal'},
        }).json()['auto_publish'] is False
    with module.session_scope() as db:
        assert len(db.scalars(select(FeishuAutoOutboxDB)).all()) == 1
