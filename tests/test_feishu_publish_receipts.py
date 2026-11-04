"""Offline receipts: no real provider calls or user credentials."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import BackgroundTasks, HTTPException, Response

from app.services import feishu_service as module
from app.services import feishu_receipt_service as receipts
from test_feishu_delivery import service  # noqa: F401


def test_desktop_http_rejection_commits_before_response_without_provider_write(service, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import feishu
    from app.services import feishu_cli
    from app.services import feishu_auto_runtime
    from app.models.feishu_destination import FeishuPublishRejectionDB
    from app.db_models import FeishuDeliveryDB
    from sqlalchemy import select

    monkeypatch.setattr(feishu, 'service', service)
    monkeypatch.setattr(feishu, 'proxy', lambda *args: (False, None))
    monkeypatch.setattr(service, 'for_owner', lambda owner: service)
    monkeypatch.setattr(feishu_cli, 'enabled', lambda: True)
    monkeypatch.setattr(feishu_auto_runtime, 'guard_manual_publish', lambda *args: None)
    monkeypatch.setattr(service, '_guard_graphic_delivery', lambda *args: (_ for _ in ()).throw(
        module.FeishuError('来源无法核验', 409, code='meeting_context_unverified')))
    writes = []
    monkeypatch.setattr(service, 'process', lambda *args: writes.append(args))
    application = FastAPI()
    application.include_router(feishu.router, prefix='/api')
    application.dependency_overrides[feishu.principal] = lambda: ('a', 'a')
    payload = {'note_key': 'isolated-note', 'title': 'title', 'content': 'body', 'operation_id': 'desktop-test-op'}
    with TestClient(application) as client:
        response = client.post('/api/feishu/deliveries', json=payload, headers={'X-VINote-Client': 'desktop'})
        assert response.status_code == 409
        assert response.json()['detail'] == {'code': 'PUBLISH_DEFINITELY_REJECTED', 'protocol': 1,
                                             'operation_id': 'desktop-test-op', 'message': '来源无法核验'}
        with module.session_scope() as db:
            assert db.get(FeishuPublishRejectionDB, ('a', 'desktop-test-op')) is not None
            assert db.scalars(select(FeishuDeliveryDB)).all() == []
        replay = client.post('/api/feishu/deliveries', json=payload)
        assert replay.status_code == 409 and replay.json()['detail']['code'] == 'OPERATION_REJECTED'
    assert not writes


def test_graphic_rejection_is_committed_and_blocks_late_replay(service, monkeypatch):
    from app.models.feishu_destination import FeishuPublishRejectionDB
    from app.db_models import FeishuDeliveryDB
    from sqlalchemy import select
    monkeypatch.setattr(service, '_guard_graphic_delivery', lambda *args: (_ for _ in ()).throw(
        module.FeishuError('来源无法核验', 409, code='meeting_context_unverified')))
    with pytest.raises(module.FeishuError) as rejected:
        service.enqueue('a', 'note', 'title', 'body', operation_id='rejected-op')
    assert rejected.value.code == 'meeting_context_unverified'
    assert rejected.value.uncertain is False
    assert rejected.value.detail['code'] == 'PUBLISH_DEFINITELY_REJECTED'
    assert rejected.value.detail['operation_id'] == 'rejected-op'
    with module.session_scope() as db:
        assert db.get(FeishuPublishRejectionDB, ('a', 'rejected-op')) is not None
        assert db.scalars(select(FeishuDeliveryDB)).all() == []
    monkeypatch.setattr(service, '_guard_graphic_delivery', lambda *args: None)
    with pytest.raises(HTTPException):
        service.enqueue('a', 'note', 'title', 'body', operation_id='rejected-op')
    with pytest.raises(HTTPException):
        service.enqueue('a', 'note', 'title', 'changed', operation_id='rejected-op')
    assert service.enqueue('a', 'note', 'title', 'body', operation_id='new-op')['id']


def test_concurrent_acceptance_and_rejection_never_both_win(service, monkeypatch):
    from threading import Barrier
    from contextlib import nullcontext
    gate = Barrier(2)
    monkeypatch.setattr(module, '_lock', lambda owner: nullcontext())  # independent processes rely on DB lock
    def submit(_):
        gate.wait()
        try:
            return service.enqueue('a', 'note', 'title', 'body', operation_id='racing-op')
        except HTTPException as exc:
            return exc
    calls = iter([True, False])
    def guard(*args):
        if next(calls):
            raise module.FeishuError('来源无法核验', 409, code='meeting_context_unverified')
    monkeypatch.setattr(service, '_guard_graphic_delivery', guard)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, [True, False]))
    assert all(isinstance(value, HTTPException) for value in outcomes) or all(isinstance(value, dict) for value in outcomes)
    with module.session_scope() as db:
        from app.models.feishu_destination import FeishuPublishRejectionDB, FeishuPublishReceiptDB
        assert db.get(FeishuPublishRejectionDB, ('a', 'racing-op')) is not None
        assert db.get(FeishuPublishReceiptDB, ('a', 'racing-op')) is None


def test_accepted_operation_is_not_rejected_after_guard_changes(service, monkeypatch):
    result = service.enqueue('a', 'note', 'title', 'body', operation_id='accepted-op')
    monkeypatch.setattr(service, '_guard_graphic_delivery', lambda *args: (_ for _ in ()).throw(
        module.FeishuError('unverified', 409, code='meeting_context_unverified')))
    assert service.enqueue('a', 'note', 'title', 'body', operation_id='accepted-op')['id'] == result['id']


def test_rejection_commit_failure_never_returns_proof(service, monkeypatch):
    from contextlib import contextmanager
    real_sessions = module.session_scope
    @contextmanager
    def failing_sessions():
        with real_sessions() as db:
            yield db
            if db.get(module.FeishuPublishRejectionDB, ('a', 'failed-commit')) is not None:
                raise RuntimeError('commit failed')
    monkeypatch.setattr(module, 'session_scope', failing_sessions)
    monkeypatch.setattr(service, '_guard_graphic_delivery', lambda *args: (_ for _ in ()).throw(
        module.FeishuError('unverified', 409, code='meeting_context_unverified')))
    with pytest.raises(RuntimeError, match='commit failed'):
        service.enqueue('a', 'note', 'title', 'body', operation_id='failed-commit')


def test_original_operation_is_queryable_after_newer_publication_and_source_change(service, monkeypatch):
    old = service.enqueue('a', 'note', 'title', 'one', operation_id='original')
    service.enqueue('a', 'note', 'title', 'two', operation_id='new')
    monkeypatch.setattr(service, 'resolve_content', lambda *args: (_ for _ in ()).throw(AssertionError('must read original first')))
    same = service.enqueue('a', 'note', 'title', 'one', operation_id='original')
    assert same['id'] == old['id'] and same['_dispatch_required'] is False
    assert service.delivery_by_operation('a', 'original')['id'] == old['id']
    assert service.delivery_by_id('a', old['id'])['id'] == old['id']
    with pytest.raises(HTTPException) as changed:
        service.enqueue('a', 'note', 'title', 'changed', operation_id='original')
    assert changed.value.status_code == 409


def test_owner_and_not_found_do_not_disclose_or_dispatch(service):
    job = service.enqueue('a', 'note', 'title', 'body', operation_id='op')
    for lookup, args in [(service.delivery_by_id, ('b', job['id'])), (service.delivery_by_operation, ('b', 'op')), (service.delivery_by_operation, ('a', 'missing'))]:
        with pytest.raises(HTTPException) as missing:
            lookup(*args)
        assert missing.value.status_code == 404
    assert service.delivery_by_id('a', job['id'])['status'] == 'queued'


@pytest.mark.parametrize('changes', [
    {'notify_self': False}, {'groups': []},
    {'destination_config': {'kind': 'folder', 'folder_token': 'other'}},
    {'version_id': 'another-version', 'revision_id': '2'},
])
def test_operation_cannot_change_destination_recipients_or_version(service, changes):
    original = service.enqueue('a', 'note', 'title', 'body', operation_id='op')
    with pytest.raises(HTTPException) as rejected:
        service.enqueue('a', 'note', 'title', 'body', operation_id='op', **changes)
    assert rejected.value.status_code == 409
    assert service.delivery_by_operation('a', 'op')['id'] == original['id']


def test_publish_replay_never_schedules_worker_and_get_is_read_only(service, monkeypatch):
    from app.routers import feishu
    monkeypatch.setattr(feishu, 'service', service)
    monkeypatch.setattr(feishu, 'proxy', lambda *args: (False, None))
    monkeypatch.setattr(service, 'for_owner', lambda owner: service)
    payload = feishu.Publish(note_key='note', title='title', content='body', operation_id='op')
    first, second = BackgroundTasks(), BackgroundTasks()
    job = feishu.publish(payload, first, ('a', None))
    again = feishu.publish(payload, second, ('a', None))
    assert again['id'] == job['id'] and len(first.tasks) == 1 and not second.tasks
    response = Response()
    assert feishu.delivery_by_operation('op', response, ('a', None))['id'] == job['id']
    assert response.headers['cache-control'] == 'no-store'
    assert feishu.delivery_by_id(job['id'], Response(), ('a', None))['id'] == job['id']


def test_concurrent_same_request_converges(service):
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: service.enqueue('a', 'note', 'title', 'body', operation_id='op'), range(2)))
    assert outcomes[0]['id'] == outcomes[1]['id']
    assert sum(bool(row['_dispatch_required']) for row in outcomes) == 1


def test_concurrent_different_inputs_cannot_rebind_operation(service):
    def submit(text):
        try:
            return service.enqueue('a', 'note', 'title', text, operation_id='op')
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ['one', 'two']))
    assert sum(isinstance(row, dict) for row in outcomes) == 1
    assert 409 in outcomes


def test_batch_crash_marker_blocks_retry_route_before_scheduling(service, monkeypatch):
    from app.routers import feishu
    monkeypatch.setattr(feishu, 'service', service)
    monkeypatch.setattr(feishu, 'proxy', lambda *args: (False, None))
    monkeypatch.setattr(feishu, 'session_scope', module.session_scope)
    job = service.enqueue('a', 'note', 'title', 'body')
    with module.session_scope() as db:
        receipts.begin_batch(db, 'a', job['id'], 0, {'index': 0, 'children': []})
    with module.session_scope() as db:
        assert receipts.has_unknown_batch(db, job['id'])
    assert service.delivery_by_id('a', job['id'])['phase'] == 'unknown'
    pending = BackgroundTasks()
    with pytest.raises(HTTPException) as refused:
        feishu.retry(job['id'], pending, None, ('a', None))
    assert refused.value.status_code == 409 and not pending.tasks


def test_receipt_capability_is_explicit_and_proxy_cannot_advertise_local_support(service, monkeypatch):
    from app.routers import feishu
    assert service.status('a')['publish_receipt_protocol'] == 1
    monkeypatch.setattr(feishu, 'proxy', lambda *args: (True, {'connected': True}))
    response = Response()
    assert 'publish_receipt_protocol' not in feishu.status(('a', 'local-user'), response)
    assert response.headers['cache-control'] == 'no-store'


def test_confirmed_batch_survives_progress_checkpoint_loss(service):
    job = service.enqueue('a', 'note', 'title', 'body')
    body = {'index': 0, 'children': []}
    with module.session_scope() as db:
        assert receipts.begin_batch(db, 'a', job['id'], 0, body)
        receipts.finish_batch(db, 'a', job['id'], 0, 'confirmed')
    with module.session_scope() as db:
        assert not receipts.begin_batch(db, 'a', job['id'], 0, body)
        assert not receipts.has_unknown_batch(db, job['id'])


def test_only_definite_batch_failure_can_retry(service):
    job = service.enqueue('a', 'note', 'title', 'body')
    body = {'index': 0, 'children': []}
    with module.session_scope() as db:
        receipts.begin_batch(db, 'a', job['id'], 0, body)
        receipts.finish_batch(db, 'a', job['id'], 0, 'failed')
    with module.session_scope() as db:
        assert receipts.begin_batch(db, 'a', job['id'], 0, body)


def test_legacy_interrupted_writing_is_unknown_and_does_not_write(service, monkeypatch):
    job = service.enqueue('a', 'note', 'title', 'body')
    service.checkpoint('a', job['id'], document_id='doc', status='processing', phase='writing', lease_until='1')
    writes = []
    monkeypatch.setattr(service, 'write_document', lambda *args: writes.append(args))
    assert service.delivery_by_id('a', job['id'])['phase'] == 'unknown'
    service.process('a', job['id'])
    assert not writes and service.delivery_by_id('a', job['id'])['phase'] == 'unknown'
