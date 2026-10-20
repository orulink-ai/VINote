"""Synthetic policy/HTTP/SQLite contracts only; never send real Feishu requests."""
import json
import sys
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers import feishu
from app.services import feishu_service as module
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from test_feishu_contacts import contact_service, selection  # noqa: F401
from test_feishu_delivery import service  # noqa: F401


def enable(client, monkeypatch, **changes):
    chosen = selection(client, monkeypatch)
    body = dict(notify_self=False, groups=[], auto_publish=True,
                contacts=[chosen], automatic_delivery_consent=True)
    body.update(changes)
    return client.save_preferences('a', body)


def policy_id(result):
    return result['automatic_delivery']['policy_id']


def submit(client, policy, **changes):
    body = dict(operation_id=str(uuid.uuid4()), note_key='synthetic-new-meeting',
                policy_id=policy, title='Synthetic meeting', content='Synthetic complete minutes')
    body.update(changes)
    return client.enqueue_automatic('a', **body)


def test_legacy_request_cannot_enable_automatic_delivery(contact_service):
    with pytest.raises(HTTPException) as caught:
        contact_service.save_preferences('a', dict(notify_self=True, groups=[], auto_publish=True))
    assert caught.value.status_code == 409


def test_new_search_proof_is_persisted_but_only_minimal_contacts_are_exposed(contact_service, monkeypatch):
    result = enable(contact_service, monkeypatch)
    assert result['contacts'] == [{'open_id': 'ou_b', 'name': '同名联系人'}]
    assert result['automatic_delivery_protocol'] == 1
    assert str(uuid.UUID(policy_id(result))) == policy_id(result)
    assert result['automatic_delivery']['enabled'] is True
    assert result['capabilities']['background_delivery'] is False
    assert 'selection_token' not in json.dumps(result)
    with module.session_scope() as db:
        prefs = json.loads(db.get(module.FeishuConnectionDB, 'a').preferences)
    assert prefs['auto_policy']['binding']['owner'] == 'a'
    assert prefs['auto_policy']['fingerprint']


@pytest.mark.parametrize('damage', ['bare_new_id', 'name', 'expired', 'owner'])
def test_contacts_cannot_be_forged_or_imported_without_current_proof(contact_service, monkeypatch, damage):
    chosen = selection(contact_service, monkeypatch)
    if damage == 'bare_new_id': chosen = {'open_id': 'ou_new'}
    elif damage == 'name': chosen['name'] = 'client supplied name'
    elif damage == 'expired':
        decoded = module._cipher().decrypt(chosen['selection_token'].encode())
        chosen['selection_token'] = module._cipher().encrypt_at_time(decoded, int(time.time()) - 901).decode()
    else:
        decoded = json.loads(module._cipher().decrypt(chosen['selection_token'].encode()))
        decoded['owner'] = 'another-owner'
        chosen['selection_token'] = module._cipher().encrypt(json.dumps(decoded).encode()).decode()
    with pytest.raises(HTTPException) as caught:
        contact_service.save_preferences('a', dict(notify_self=False, groups=[], auto_publish=True,
            contacts=[chosen], automatic_delivery_consent=True))
    assert caught.value.code == ('contact_selection_expired' if damage == 'expired' else 'invalid_recipient')


def test_saved_contact_can_be_retained_by_id_but_target_change_requires_new_consent(contact_service, monkeypatch):
    original = enable(contact_service, monkeypatch)
    same = contact_service.save_preferences('a', dict(notify_self=False, groups=[], auto_publish=True,
                                                    contacts=[{'open_id': 'ou_b'}]))
    assert policy_id(same) == policy_id(original)
    with pytest.raises(HTTPException) as caught:
        contact_service.save_preferences('a', dict(notify_self=True, groups=[], auto_publish=True,
                                                  contacts=[{'open_id': 'ou_b'}]))
    assert caught.value.status_code == 409


def test_automatic_enqueue_uses_frozen_policy_and_same_operation_never_rewrites(contact_service, monkeypatch):
    chosen = policy_id(enable(contact_service, monkeypatch))
    operation = str(uuid.uuid4())
    first = submit(contact_service, chosen, operation_id=operation)
    monkeypatch.setattr(contact_service, 'check_destination', Mock(side_effect=AssertionError('duplicate must not preflight')))
    second = submit(contact_service, chosen, operation_id=operation)
    assert first['id'] == second['id'] and second['_dispatch_required'] is False
    with pytest.raises(HTTPException) as caught:
        submit(contact_service, chosen, operation_id=operation, content='Changed body')
    assert caught.value.status_code == 409
    with module.session_scope() as db:
        job = db.get(module.FeishuDeliveryDB, first['id'])
        recipients = json.loads(job.recipients)
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, first['id']).snapshot)
    assert set(recipients) == {'ou_b'}
    assert snapshot['automatic_policy_id'] == chosen
    assert snapshot['recipient_access_policy'] == 'grant_view_and_notify'
    assert snapshot['content_source']['kind'] == 'local_snapshot'
    assert snapshot['app_id'] == 'app-test'


def test_revocation_during_preflight_blocks_enqueue_inside_write_lock(contact_service, monkeypatch):
    chosen = policy_id(enable(contact_service, monkeypatch))
    def revoke(owner, target):
        with module.session_scope() as db:
            row = db.get(module.FeishuConnectionDB, owner)
            prefs = json.loads(row.preferences)
            prefs['auto_policy']['enabled'] = False
            row.preferences = json.dumps(prefs)
        return {**target, 'can_attempt_create': True}
    monkeypatch.setattr(contact_service, 'check_destination', revoke)
    with pytest.raises(HTTPException) as caught:
        submit(contact_service, chosen)
    assert caught.value.status_code == 409
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 0


@pytest.mark.parametrize('change', ['disable', 'connection', 'app', 'tenant'])
def test_automatic_snapshot_stops_after_policy_or_binding_revocation(contact_service, monkeypatch, change):
    chosen = policy_id(enable(contact_service, monkeypatch))
    job = submit(contact_service, chosen)
    with module.session_scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job['id']).snapshot)
    if change in ('disable', 'connection'):
        with module.session_scope() as db:
            row = db.get(module.FeishuConnectionDB, 'a')
            prefs = json.loads(row.preferences)
            if change == 'disable': prefs['auto_policy']['enabled'] = False
            else: prefs['connection_id'] = str(uuid.uuid4())
            row.preferences = json.dumps(prefs)
    else:
        monkeypatch.setattr(module.settings, 'feishu_app_id' if change == 'app' else 'feishu_tenant_key', 'changed')
    with pytest.raises(HTTPException):
        contact_service.assert_delivery_connection('a', snapshot)


@pytest.fixture
def http_client(contact_service, monkeypatch):
    runtime = SimpleNamespace(background_ready=lambda: False, wake=Mock(), decorate_status=Mock(side_effect=lambda identity, result: result),
                              bind_device_policy=Mock(), guard_manual_publish=Mock())
    monkeypatch.setitem(sys.modules, 'app.services.feishu_auto_runtime', runtime)
    monkeypatch.setattr(feishu, 'service', contact_service)
    monkeypatch.setattr(feishu, 'session_scope', module.session_scope)
    monkeypatch.setattr(contact_service, 'for_owner', lambda owner: contact_service)
    monkeypatch.setattr(feishu, 'proxy', lambda *args, **kwargs: (False, None))
    app = FastAPI()
    app.include_router(feishu.router, prefix='/api')
    app.dependency_overrides[feishu.principal] = lambda: ('a', 'local-a')
    with TestClient(app) as client:
        yield client, runtime


def test_automatic_http_strict_body_wakes_worker_never_background_process(contact_service, http_client, monkeypatch):
    client, runtime = http_client
    chosen = policy_id(enable(contact_service, monkeypatch))
    process = Mock(side_effect=AssertionError('route cannot process directly'))
    monkeypatch.setattr(contact_service, 'process', process)
    body = dict(operation_id=str(uuid.uuid4()), policy_id=chosen, note_key='synthetic-http', title='Title', content='Body')
    for extra in ('targets', 'model', 'desired_destination', 'automatic', 'contacts'):
        assert client.post('/api/feishu/automatic-deliveries', json={**body, extra: []}).status_code == 422
    response = client.post('/api/feishu/automatic-deliveries', json=body)
    assert response.status_code == 200 and '_dispatch_required' not in response.json()
    assert client.get('/api/feishu/deliveries/by-operation/' + body['operation_id']).json()['id'] == response.json()['id']
    runtime.wake.assert_called_once()
    process.assert_not_called()


def test_local_disable_stops_queue_before_failed_remote_preferences(http_client, monkeypatch):
    client, runtime = http_client
    def fail(*args, **kwargs):
        runtime.bind_device_policy.assert_called_once_with('local-a', None)
        raise HTTPException(502, 'synthetic offline')
    monkeypatch.setattr(feishu, 'proxy', fail)
    assert client.put('/api/feishu/preferences', json={'auto_publish': False}).status_code == 502


def test_generic_automatic_entry_never_bypasses_the_saved_policy(contact_service, monkeypatch):
    enable(contact_service, monkeypatch)
    with pytest.raises(module.FeishuError) as caught:
        contact_service.enqueue('a', 'new-note', 'title', 'body', automatic=True)
    assert caught.value.code == 'automatic_policy_required'


def test_automatic_first_completion_does_not_republish_edits_or_old_unknown_operations(contact_service, monkeypatch):
    chosen = policy_id(enable(contact_service, monkeypatch))
    first = submit(contact_service, chosen)
    second = submit(contact_service, chosen, content='Later edited body')
    assert second['id'] == first['id'] and second['_dispatch_required'] is False
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 1
        assert db.get(module.FeishuDeliveryDB, first['id']).content == 'Synthetic complete minutes'


def test_reenabled_or_changed_policy_rotates_id_without_rebinding_old_jobs(contact_service, monkeypatch):
    first = enable(contact_service, monkeypatch)
    job = submit(contact_service, policy_id(first))
    contact_service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[]))
    second = contact_service.save_preferences('a', dict(auto_publish=True, notify_self=False, groups=[],
        contacts=[{'open_id': 'ou_b'}], automatic_delivery_consent=True))
    assert policy_id(second) != policy_id(first)
    with module.session_scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job['id']).snapshot)
    with pytest.raises(module.FeishuError):
        contact_service.assert_delivery_connection('a', snapshot)


def test_saved_contact_is_reusable_after_search_token_expires_but_reconnection_invalidates_it(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    contact_service.save_preferences('a', dict(auto_publish=True, notify_self=False, groups=[],
        contacts=[chosen], automatic_delivery_consent=True))
    validate = Mock(side_effect=AssertionError('retained IDs must use saved verified claims, not expired search tokens'))
    monkeypatch.setattr(contact_service, 'validate_contacts', validate)
    contact_service.save_preferences('a', dict(auto_publish=True, notify_self=False, groups=[], contacts=[{'open_id': 'ou_b'}]))
    contact_service.store_connection('a', {'access_token': 'token', 'expires_in': 7200, 'scope': 'contact:user:search'},
                                     {'open_id': 'ou_a', 'tenant_key': 'company'})
    assert contact_service.status('a')['automatic_delivery']['enabled'] is False
    with pytest.raises(module.FeishuError) as caught:
        contact_service.save_preferences('a', dict(auto_publish=True, notify_self=False, groups=[],
            contacts=[{'open_id': 'ou_b'}], automatic_delivery_consent=True))
    assert caught.value.code == 'invalid_recipient'


def test_successful_automatic_worker_uses_view_acl_and_receipts_before_notifying(contact_service, monkeypatch):
    from test_feishu_recipient_access import worker
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)), note_key='note')
    events, _ = worker(contact_service, monkeypatch)
    contact_service.process('a', job['id'])
    assert events == ['create', 'write', 'GET', 'POST', 'GET', 'send']
    assert contact_service.delivery_by_id('a', job['id'])['status'] == 'completed'
    assert module.auto_policy.active_delivery.get() is None


def test_revocation_after_create_prevents_permission_body_and_notification(contact_service, monkeypatch):
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)))
    events = []
    def create(*args):
        events.append('create')
        contact_service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[]))
        return 'doc1', 'https://company.feishu.cn/docx/doc1'
    monkeypatch.setattr(contact_service, 'create_at_destination', create)
    monkeypatch.setattr(contact_service, 'ensure_permission', Mock(side_effect=AssertionError('revoked before permission write')))
    monkeypatch.setattr(contact_service, 'write_document', Mock(side_effect=AssertionError('revoked before body write')))
    monkeypatch.setattr(contact_service, 'send_message', Mock(side_effect=AssertionError('revoked before notification')))
    contact_service.process('a', job['id'])
    result = contact_service.delivery_by_id('a', job['id'])
    assert events == ['create'] and result['error_code'] == 'automatic_policy_changed'
    assert result['document_url'].endswith('/doc1')
    assert module.auto_policy.active_delivery.get() is None


def test_native_body_rechecks_policy_before_each_actual_batch_post(contact_service, monkeypatch):
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)))
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, job['id'])
        row.document_id = 'doc1'
        db.flush()
        db.expunge(row)
    plan = {'batches': [{'offset': index, 'client_token': str(uuid.uuid4()),
        'body': {'children_id': [name], 'descendants': [{'block_id': name}]}} for index, name in enumerate(('a', 'b'))]}
    posts = []
    def request(method, path, **kwargs):
        posts.append((method, path))
        assert len(posts) == 1
        contact_service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[]))
        return {'block_id_relations': [{'temporary_block_id': 'a', 'block_id': 'real-a'}]}
    monkeypatch.setattr(contact_service, 'request', request)
    with pytest.raises(module.FeishuError) as caught:
        contact_service.write_native_body('a', row, plan)
    assert caught.value.code == 'automatic_policy_changed'
    assert len(posts) == 1
    with module.session_scope() as db:
        from app.models.feishu_destination import FeishuWriteBatchDB
        assert db.get(FeishuWriteBatchDB, (job['id'], '0')).state == 'confirmed'
        assert db.get(FeishuWriteBatchDB, (job['id'], '1')).state == 'failed'


def test_unknown_automatic_grant_is_not_replayed_even_by_direct_worker_entry(contact_service, monkeypatch):
    from test_feishu_recipient_access import worker
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)), note_key='note')
    events, _ = worker(contact_service, monkeypatch, outcome='timeout_absent')
    contact_service.process('a', job['id'])
    before = list(events)
    assert contact_service.delivery_by_id('a', job['id'])['phase'] == 'permission_unknown'
    contact_service.process('a', job['id'])
    assert events == before and 'send' not in events


def test_manual_publish_guard_runs_before_any_manual_post(http_client, monkeypatch):
    client, runtime = http_client
    runtime.guard_manual_publish.side_effect = HTTPException(409, 'synthetic automatic result unknown')
    calls = []
    monkeypatch.setattr(feishu, 'proxy', lambda *args: calls.append(args) or (False, None))
    response = client.post('/api/feishu/deliveries', json={'note_key': 'n', 'title': 't', 'content': 'c'})
    assert response.status_code == 409 and not calls


def test_old_device_request_cannot_enable_a_policy_from_another_device(http_client, contact_service, monkeypatch):
    client, runtime = http_client
    enable(contact_service, monkeypatch)
    runtime.decorate_status.side_effect = lambda identity, result: {**result, 'auto_publish': False}
    response = client.put('/api/feishu/preferences', json={'notify_self': False, 'auto_publish': True,
        'groups': [], 'contacts': [{'open_id': 'ou_b'}]})
    assert response.status_code == 409
    runtime.bind_device_policy.assert_not_called()


def test_http_transport_checks_live_policy_after_preflight_and_before_target_write(contact_service, monkeypatch):
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)))
    with module.session_scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job['id']).snapshot)
    contact_service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[]))
    outbound = Mock(side_effect=AssertionError('revocation must prevent HTTP dispatch'))
    monkeypatch.setattr(module.httpx, 'request', outbound)
    token = module.auto_policy.active_delivery.set(('a', snapshot))
    try:
        with pytest.raises(module.FeishuError) as caught:
            # Exercise the real transport, not a replaced request method.
            module.FeishuService.request(contact_service, 'POST', 'docx/v1/documents', token='test', body={})
        assert caught.value.code == 'automatic_policy_changed'
    finally:
        module.auto_policy.active_delivery.reset(token)
    outbound.assert_not_called()


def test_another_thread_can_disable_policy_while_worker_waits_on_network(contact_service, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)))
    entered, release = threading.Event(), threading.Event()
    writes = Mock(side_effect=AssertionError('revoked before subsequent write'))
    def create(*args):
        entered.set()
        assert release.wait(4)
        return 'doc1', 'https://company.feishu.cn/docx/doc1'
    monkeypatch.setattr(contact_service, 'create_at_destination', create)
    monkeypatch.setattr(contact_service, 'ensure_permission', writes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        run = pool.submit(contact_service.process, 'a', job['id'])
        assert entered.wait(3)
        disable = pool.submit(contact_service.save_preferences, 'a', dict(auto_publish=False, notify_self=False, groups=[]))
        try:
            assert disable.result(timeout=2)['automatic_delivery']['enabled'] is False
        finally:
            release.set()
        run.result(timeout=3)
    writes.assert_not_called()


@pytest.mark.parametrize('outcome,status,phase', [
    ('queued', 'queued', 'pending_create'),
    ('processing', 'processing', 'writing'),
    ('unknown_create', 'failed', 'unknown'),
    ('unknown_write', 'failed', 'unknown'),
    ('unknown_message', 'failed', 'unknown'),
    ('unknown_permission', 'failed', 'permission_unknown'),
    ('definite_failure', 'failed', 'failed'),
    ('inconsistent_phase', 'completed', 'unknown'),
    ('inconsistent_status', 'failed', 'completed'),
])
def test_manual_new_operation_cannot_duplicate_incomplete_automatic_delivery(contact_service, monkeypatch, outcome, status, phase):
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)))
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, job['id'])
        row.status = status
        row.document_id = '__creating__' if outcome == 'unknown_create' else 'doc1' if outcome.startswith('unknown') else ''
        meta = db.get(FeishuDeliveryDestinationDB, job['id'])
        meta.phase, meta.error_code = phase, outcome
    monkeypatch.setattr(contact_service, 'check_destination', Mock(side_effect=AssertionError('must block before preflight')))
    with pytest.raises(module.FeishuError) as caught:
        contact_service.enqueue('a', 'synthetic-new-meeting', 'Edited title', 'Edited body',
            operation_id=str(uuid.uuid4()), source_mode='local_snapshot')
    assert caught.value.status_code == 409 and caught.value.code == 'automatic_delivery_pending'
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 1


def test_manual_write_transaction_rechecks_automatic_job_created_during_preflight(contact_service, monkeypatch):
    chosen = policy_id(enable(contact_service, monkeypatch))
    check = contact_service.check_destination
    entered = False
    def competing_auto(owner, target):
        nonlocal entered
        if not entered:
            entered = True
            submit(contact_service, chosen, note_key='race-note')
        return check(owner, target)
    monkeypatch.setattr(contact_service, 'check_destination', competing_auto)
    with pytest.raises(module.FeishuError) as caught:
        contact_service.enqueue('a', 'race-note', 'Manual title', 'Manual body',
            operation_id=str(uuid.uuid4()), source_mode='local_snapshot',
            destination_config={'kind': 'personal'}, notify_self=True)
    assert caught.value.code == 'automatic_delivery_pending'
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 1


def test_completed_automatic_delivery_allows_explicit_new_manual_revision(contact_service, monkeypatch):
    from test_feishu_recipient_access import worker
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)), note_key='note')
    worker(contact_service, monkeypatch)
    contact_service.process('a', job['id'])
    assert contact_service.delivery_by_id('a', job['id'])['phase'] == 'completed'
    new = contact_service.enqueue('a', 'note', 'Revised title', 'Explicitly revised body',
        operation_id=str(uuid.uuid4()), source_mode='local_snapshot', notify_self=True)
    assert new['id'] != job['id'] and new['_dispatch_required'] is True
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 2


def test_same_original_manual_operation_returns_receipt_before_pending_guard(contact_service, monkeypatch):
    enable(contact_service, monkeypatch)
    operation = str(uuid.uuid4())
    original = contact_service.enqueue('a', 'manual-note', 'Title', 'Body', operation_id=operation,
        source_mode='local_snapshot', notify_self=True)
    guard = Mock(side_effect=AssertionError('idempotent lookup must precede new-write guards'))
    monkeypatch.setattr(contact_service, '_assert_no_pending_automatic', guard)
    replay = contact_service.enqueue('a', 'manual-note', 'Title', 'Body', operation_id=operation,
        source_mode='local_snapshot', notify_self=True)
    assert replay['id'] == original['id'] and replay['_dispatch_required'] is False
    guard.assert_not_called()


def test_incomplete_auto_blocks_direct_http_new_manual_but_keeps_original_definite_retry(contact_service, http_client, monkeypatch):
    client, _ = http_client
    job = submit(contact_service, policy_id(enable(contact_service, monkeypatch)))
    process = Mock()
    monkeypatch.setattr(contact_service, 'process', process)
    response = client.post('/api/feishu/deliveries', json=dict(note_key='synthetic-new-meeting', title='Title',
        content='Changed body', operation_id=str(uuid.uuid4()), source_mode='local_snapshot'))
    assert response.status_code == 409
    with module.session_scope() as db:
        db.get(module.FeishuDeliveryDB, job['id']).status = 'failed'
        db.get(FeishuDeliveryDestinationDB, job['id']).phase = 'failed'
    assert client.post('/api/feishu/deliveries/' + job['id'] + '/retry').status_code == 200
    process.assert_called_once_with('a', job['id'], None)


def test_disabled_empty_contact_preferences_remain_compatible_without_consent(contact_service):
    result = contact_service.save_preferences('a', dict(auto_publish=False, notify_self=True, groups=[], contacts=[]))
    assert result['automatic_delivery']['enabled'] is False and result['contacts'] == []


def test_policy_receipt_and_pending_note_are_isolated_by_owner(contact_service, monkeypatch):
    chosen = policy_id(enable(contact_service, monkeypatch))
    operation = str(uuid.uuid4())
    automatic = submit(contact_service, chosen, operation_id=operation)
    contact_service.store_connection('b', {'access_token': 'other-token', 'refresh_token': 'other-refresh',
        'expires_in': 7200}, {'open_id': 'ou_other', 'name': 'Other owner', 'tenant_key': 'company'})
    with pytest.raises(module.FeishuError) as caught:
        contact_service.enqueue_automatic('b', operation_id=operation, policy_id=chosen,
            note_key='synthetic-new-meeting', title='Synthetic meeting', content='Synthetic complete minutes')
    assert caught.value.code == 'automatic_policy_changed'
    manual = contact_service.enqueue('b', 'synthetic-new-meeting', 'Other owner title', 'Other owner body',
        operation_id=operation, source_mode='local_snapshot', notify_self=True)
    assert manual['id'] != automatic['id'] and manual['_dispatch_required'] is True
    with module.session_scope() as db:
        assert db.get(module.FeishuDeliveryDB, manual['id']).owner == 'b'


def test_local_successful_preferences_bind_only_after_remote_acceptance(http_client, monkeypatch):
    client, runtime = http_client
    remote_status = {'automatic_delivery_protocol': 1}
    accepted = {'automatic_delivery_protocol': 1, 'auto_publish': True,
                'automatic_delivery': {'enabled': True, 'policy_id': str(uuid.uuid4())}}
    calls = []

    def proxy(identity, method, path, body=None):
        runtime.bind_device_policy.assert_not_called()
        calls.append((method, path))
        return True, remote_status if method == 'GET' else accepted

    monkeypatch.setattr(feishu, 'proxy', proxy)
    response = client.put('/api/feishu/preferences', json={'auto_publish': True,
        'notify_self': True, 'automatic_delivery_consent': True})
    assert response.status_code == 200 and calls == [('GET', '/status'), ('PUT', '/preferences')]
    runtime.bind_device_policy.assert_called_once_with('local-a', accepted)


def test_legacy_remote_cannot_silently_ignore_new_automatic_policy(http_client, monkeypatch):
    client, runtime = http_client
    calls = []

    def proxy(identity, method, path, body=None):
        calls.append((method, path))
        return True, {'connected': True}

    monkeypatch.setattr(feishu, 'proxy', proxy)
    assert client.put('/api/feishu/preferences', json={'auto_publish': True,
        'automatic_delivery_consent': True}).status_code == 409
    assert calls == [('GET', '/status')]
    runtime.bind_device_policy.assert_not_called()


def test_sqlite_final_check_serializes_writers_without_process_local_lock(contact_service, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext
    import threading
    chosen = policy_id(enable(contact_service, monkeypatch))
    automatic_locked, release, manual_enqueue = (threading.Event() for _ in range(3))
    check_policy, enqueue = contact_service._automatic_policy, contact_service._enqueue
    checks = 0

    def policy_check(*args):
        nonlocal checks
        result = check_policy(*args)
        checks += 1
        if checks == 2:  # Inside the automatic write transaction, before its INSERT.
            automatic_locked.set()
            assert release.wait(4)
        return result

    def entered_enqueue(*args, **kwargs):
        if not args[4]:
            manual_enqueue.set()
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(module, '_lock', lambda owner: nullcontext())
    monkeypatch.setattr(contact_service, '_automatic_policy', policy_check)
    monkeypatch.setattr(contact_service, '_enqueue', entered_enqueue)
    with ThreadPoolExecutor(max_workers=2) as pool:
        automatic = pool.submit(submit, contact_service, chosen)
        assert automatic_locked.wait(3)
        manual = pool.submit(contact_service.enqueue, 'a', 'synthetic-new-meeting', 'Revision', 'Revised body',
            operation_id=str(uuid.uuid4()), source_mode='local_snapshot', notify_self=True)
        try:
            assert manual_enqueue.wait(3)
            # SQLite must hold this new writer until the automatic job commits.
            assert not manual.done()
        finally:
            release.set()
        assert automatic.result(timeout=4)['_dispatch_required'] is True
        with pytest.raises(module.FeishuError) as caught:
            manual.result(timeout=4)
        assert caught.value.code == 'automatic_delivery_pending'
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 1


@pytest.mark.parametrize('consent', [False, True])
def test_stale_preferences_write_cannot_restore_committed_revocation(contact_service, monkeypatch, consent):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext
    import threading
    from sqlalchemy import event

    chosen = policy_id(enable(contact_service, monkeypatch))
    with module.session_scope() as db:
        engine = db.get_bind()
    waiting, release = threading.Event(), threading.Event()
    stale_threads, paused = [], []

    def pause_stale_update(conn, cursor, statement, parameters, context, executemany):
        if (threading.current_thread() in stale_threads and not paused
                and statement.lstrip().upper().startswith('UPDATE FEISHU_CONNECTIONS')):
            paused.append(True)
            waiting.set()
            assert release.wait(8)

    def stale_save():
        stale_threads.append(threading.current_thread())
        return contact_service.save_preferences('a', dict(auto_publish=True,
            notify_self=False, groups=[], contacts=[{'open_id': 'ou_b'}],
            destination_config={'kind': 'personal'}, automatic_delivery_consent=consent))

    # Different processes do not share the Python identity mutex. These separate
    # SQLite sessions pause after validation but before the final SQL write.
    monkeypatch.setattr(module, '_lock', lambda owner: nullcontext())
    event.listen(engine, 'before_cursor_execute', pause_stale_update)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            stale = pool.submit(stale_save)
            assert waiting.wait(3)
            try:
                disabled = pool.submit(contact_service.save_preferences, 'a', dict(auto_publish=False,
                    notify_self=False, groups=[], contacts=[{'open_id': 'ou_b'}]))
                assert disabled.result(timeout=3)['automatic_delivery']['enabled'] is False
            finally:
                release.set()
            with pytest.raises(module.FeishuError) as caught:
                stale.result(timeout=3)
            assert caught.value.status_code == 409 and caught.value.code == 'automatic_policy_changed'
        assert contact_service.status('a')['automatic_delivery']['enabled'] is False
        with pytest.raises(module.FeishuError):
            submit(contact_service, chosen)
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', pause_stale_update)
