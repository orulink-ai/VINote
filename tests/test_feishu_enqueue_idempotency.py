"""Receipt reuse never dispatches; new intents retain unknown-write gates."""
import json
import socket
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from app.models.feishu_destination import (
    FeishuDeliveryDestinationDB, FeishuPublishReceiptDB, FeishuWriteBatchDB,
)
from app.services import feishu_service as module, feishu_cli
from test_feishu_delivery import service  # noqa: F401


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No real network or Feishu CLI execution')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(feishu_cli, 'run', forbidden)


def frozen():
    with module.session_scope() as db:
        return {model.__tablename__: sorted([
            [getattr(row, col.name) for col in model.__table__.columns]
            for row in db.query(model).all()], key=repr)
            for model in (module.FeishuDeliveryDB, FeishuDeliveryDestinationDB,
                          FeishuPublishReceiptDB, FeishuWriteBatchDB)}


def set_state(job_id, state):
    with module.session_scope() as db:
        job = db.get(module.FeishuDeliveryDB, job_id)
        metadata = db.get(FeishuDeliveryDestinationDB, job_id)
        if state == 'missing-metadata':
            db.delete(metadata)
        elif state in ('queued', 'processing', 'failed', 'completed'):
            job.status = state
            metadata.phase = 'completed' if state == 'completed' else 'pending_create'
        else:
            job.status, metadata.phase = 'failed', 'unknown'
            if state == 'unknown-create':
                job.document_id = '__creating__'
            elif state == 'unknown-write':
                db.add(FeishuWriteBatchDB(job_id=job_id, offset='0',
                                         state='unknown', fingerprint='f' * 64))
            elif state == 'unknown-recipient':
                job.recipients = json.dumps({'ou_a': {'status': 'unknown'}})
            elif state == 'unknown-permission':
                metadata.phase = 'permission_unknown'
                job.recipients = json.dumps({'ou_a': {'status': 'pending',
                    'reading_permission': {'status': 'unknown'}}})


@pytest.mark.parametrize('operation', [None, 'original-operation'])
@pytest.mark.parametrize('state', ['missing-metadata', 'queued', 'processing', 'failed', 'completed',
    'unknown-create', 'unknown-write', 'unknown-recipient', 'unknown-permission', 'unknown-phase'])
def test_exact_request_reuses_every_original_state_without_mutating_or_dispatching(service, monkeypatch, operation, state):
    first = service.enqueue('a', 'note', 'title', 'body', operation_id=operation)
    set_state(first['id'], state)
    before = frozen()
    monkeypatch.setattr(service, '_guard_graphic_delivery',
                        lambda *a: pytest.fail('Receipt reuse must precede new-source validation'))
    again = service.enqueue('a', 'note', 'title', 'body', operation_id=operation)
    assert again['id'] == first['id'] and again['_dispatch_required'] is False
    assert frozen() == before


@pytest.mark.parametrize('operation', [None, 'original-operation'])
def test_http_duplicate_without_or_with_operation_never_schedules_another_worker(service, monkeypatch, operation):
    from app.routers import feishu
    monkeypatch.setattr(feishu, 'service', service)
    monkeypatch.setattr(feishu, 'proxy', lambda *args: (False, None))
    monkeypatch.setattr(feishu_cli, 'enabled', lambda: False)
    monkeypatch.setattr(service, 'for_owner', lambda owner: service)
    payload = feishu.Publish(note_key='note', title='title', content='body', operation_id=operation)
    pending, duplicate = BackgroundTasks(), BackgroundTasks()
    first = feishu.publish(payload, pending, ('a', None))
    set_state(first['id'], 'unknown-create')
    before = frozen()
    again = feishu.publish(payload, duplicate, ('a', None))
    assert first['id'] == again['id'] and len(pending.tasks) == 1 and duplicate.tasks == []
    assert frozen() == before


@pytest.mark.parametrize('state', ['processing', 'unknown-create', 'unknown-write',
    'unknown-recipient', 'unknown-permission', 'unknown-phase'])
def test_new_nonwiki_revision_cannot_bypass_unknown_or_inflight_original(service, monkeypatch, state):
    monkeypatch.setattr(service, 'check_destination', lambda owner, target: {**target, 'can_attempt_create': True})
    options = dict(destination_config={'kind': 'personal'}, groups=[], source_mode='local_snapshot')
    first = service.enqueue('a', 'note', 'title', 'body', operation_id=str(uuid4()), notify_self=False, **options)
    set_state(first['id'], state)
    before = frozen()
    with pytest.raises(module.FeishuError) as caught:
        service.enqueue('a', 'note', 'title', 'body', operation_id=str(uuid4()), notify_self=True, **options)
    assert caught.value.code == 'grouping_prior_delivery_requires_review'
    assert frozen() == before
