"""Offline receipts: no real provider calls or user credentials."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import BackgroundTasks, HTTPException, Response

from app.services import feishu_service as module
from app.services import feishu_receipt_service as receipts
from test_feishu_delivery import service  # noqa: F401


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
