"""Durable dispatch/restart/CAS/readback tests; synthetic records, no cloud."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import threading
import time
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.db_models import CloudAccountDB, FeishuDeliveryDB, NoteDB
from app.models.auth import AuthenticatedUser
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB, FeishuDevicePolicyDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.routers import feishu_auto_local
from app.services import feishu_auto_runtime as runtime, feishu_auto_outbox as outbox


@pytest.fixture
def queue(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'queue.db').as_posix(),
                           connect_args={'check_same_thread': False, 'timeout': 5})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(runtime, 'session_scope', scope)
    monkeypatch.setattr(outbox, 'session_scope', scope)
    monkeypatch.setattr(settings, 'feishu_service_url', '')
    policy, note, operation, job = [str(uuid.uuid4()) for _ in range(4)]
    body = {'operation_id': operation, 'policy_id': policy, 'note_key': note,
            'title': 'Synthetic minutes', 'content': 'Synthetic frozen body'}
    with scope() as db:
        db.add(NoteDB(id=note, created_by='alice', scope='personal', title=body['title'], content=body['content']))
        db.add(FeishuDevicePolicyDB(user_id='alice', policy_id=policy, enabled=True,
                                   integration_origin='', cloud_owner='alice'))
        db.add(FeishuAutoOutboxDB(id=operation, user_id='alice', note_id=note,
                                 policy_id=policy, integration_origin='', cloud_owner='alice',
                                 payload=json.dumps(body), status='queued'))
    c = SimpleNamespace(sessions=sessions, scope=scope, operation=operation, note=note,
                        policy=policy, job=job, body=body)
    yield c
    engine.dispose()


def row(c):
    with c.sessions() as db:
        return db.get(FeishuAutoOutboxDB, c.operation)


def receipt(c):
    return {'id': c.job, 'operation_id': c.operation, 'status': 'queued'}


def test_queue_survives_caller_exit_and_is_dispatched_once(queue, monkeypatch):
    c, calls = queue, []
    monkeypatch.setattr(runtime, '_request', lambda r, **kw: calls.append((r.payload, kw)) or receipt(c))
    runtime.run_once()
    runtime.run_once()
    assert len(calls) == 1
    assert json.loads(calls[0][0]) == c.body and calls[0][1] == {'read_only': False}
    assert (row(c).status, row(c).job_id) == ('accepted', c.job)


def test_two_workers_compete_for_one_claim_without_duplicate_post(queue, monkeypatch):
    c, entered, release, calls = queue, threading.Event(), threading.Event(), []

    def provider(r, **kw):
        calls.append(r.id)
        entered.set()
        assert release.wait(4)
        return receipt(c)

    monkeypatch.setattr(runtime, '_request', provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.attempt_device, c.operation)
        assert entered.wait(3)
        pool.submit(runtime.attempt_device, c.operation).result(timeout=3)
        release.set()
        first.result(timeout=3)
    assert calls == [c.operation] and row(c).status == 'accepted'


def test_timeout_never_reposts_and_explicit_check_reads_exact_operation(queue, monkeypatch):
    c, calls = queue, []

    def provider(r, *, read_only):
        calls.append((r.id, read_only))
        if not read_only:
            raise runtime.HandoffError('Synthetic ambiguous timeout', uncertain=True)
        return receipt(c)

    monkeypatch.setattr(runtime, '_request', provider)
    runtime.run_once()
    assert row(c).status == 'unknown'
    runtime.run_once()
    assert calls == [(c.operation, False)]
    with pytest.raises(HTTPException) as blocked:
        runtime.guard_manual_publish(('cloud-owner', 'alice'), c.note)
    assert blocked.value.status_code == 409
    assert runtime.check_local('alice', c.note)['status'] == 'accepted'
    assert calls == [(c.operation, False), (c.operation, True)]


def test_expired_submitting_crash_is_readback_not_new_post_even_when_not_found(queue, monkeypatch):
    c, calls = queue, []
    with c.scope() as db:
        item = db.get(FeishuAutoOutboxDB, c.operation)
        item.status, item.lease_until = 'submitting', 1

    def not_found(r, **kw):
        calls.append(kw)
        raise runtime.HandoffError('No receipt yet', uncertain=True)

    monkeypatch.setattr(runtime, '_request', not_found)
    runtime.run_once()
    runtime.run_once()
    assert calls == [{'read_only': True}] and row(c).status == 'unknown'


@pytest.mark.parametrize('which', ['disabled', 'changed_policy', 'changed_origin', 'changed_owner', 'deleted_note', 'now_team'])
def test_dispatch_rechecks_current_binding_before_any_network_or_content_transfer(queue, monkeypatch, which):
    c = queue
    with c.scope() as db:
        policy = db.get(FeishuDevicePolicyDB, 'alice')
        if which == 'disabled':
            policy.enabled = False
        elif which == 'changed_policy':
            policy.policy_id = str(uuid.uuid4())
        elif which == 'changed_origin':
            db.get(FeishuAutoOutboxDB, c.operation).integration_origin = 'https://different.example'
        elif which == 'changed_owner':
            db.get(FeishuAutoOutboxDB, c.operation).cloud_owner = 'other-owner'
        elif which == 'now_team':
            db.get(NoteDB, c.note).scope = 'team'
        else:
            db.delete(db.get(NoteDB, c.note))
    from app.services.feishu_service import FeishuService
    monkeypatch.setattr(FeishuService, 'for_owner', lambda *args: pytest.fail('No service dispatch allowed'))
    runtime.attempt_device(c.operation)
    assert row(c).status == 'cancelled'


def test_readback_cannot_claim_rejection_or_replay_on_authorization_failure(queue, monkeypatch):
    c = queue
    with c.scope() as db:
        db.get(FeishuAutoOutboxDB, c.operation).status = 'unknown'
    monkeypatch.setattr(runtime, '_request', lambda *args, **kw: (_ for _ in ()).throw(runtime.HandoffError('Auth required')))
    assert runtime.check_local('alice', c.note)['status'] == 'unknown'


def test_mismatched_receipt_is_unknown_and_never_accepted_or_replayed(queue, monkeypatch):
    c = queue
    monkeypatch.setattr(runtime, '_request', lambda *args, **kw: {'id': c.job, 'operation_id': 'different'})
    runtime.run_once()
    assert row(c).status == 'unknown' and row(c).job_id == ''


def test_device_opt_in_is_explicit_and_remote_compatibility_cannot_enable_it(queue, monkeypatch):
    c = queue
    monkeypatch.setattr(runtime, 'background_ready', lambda: True)
    status = {'auto_publish': True, 'automatic_delivery_protocol': 1,
              'automatic_delivery': {'policy_id': c.policy, 'enabled': True},
              'capabilities': {'background_delivery': True}}
    assert runtime.decorate_status(('alice', 'alice'), status)['auto_publish']
    assert not runtime.decorate_status(('bob', 'bob'), status)['auto_publish']
    old = {'auto_publish': True, 'capabilities': {'background_delivery': True}}
    assert not runtime.decorate_status(('alice', 'alice'), old)['capabilities']['background_delivery']


def test_owner_scoped_local_status_and_check_are_http_readback_only(queue, monkeypatch):
    c = queue
    app = FastAPI()
    app.include_router(feishu_auto_local.router, prefix='/api')
    user = SimpleNamespace(id='bob')
    app.dependency_overrides[feishu_auto_local.get_current_user] = lambda: AuthenticatedUser(user_id=user.id)
    calls = []
    monkeypatch.setattr(runtime, '_request', lambda *a, **kw: calls.append(kw) or receipt(c))
    with TestClient(app) as client:
        path = '/api/feishu/automatic-deliveries/local/' + c.note
        assert client.get(path).status_code == 404
        assert client.post(path + '/check').status_code == 404
        user.id = 'alice'
        assert client.get(path).json()['status'] == 'queued'
        assert client.get(path).headers['cache-control'] == 'no-store'
        assert client.post(path + '/check').json()['status'] == 'queued'
        assert calls == []


def test_manual_post_can_cancel_only_queued_auto_intent(queue):
    c = queue
    runtime.guard_manual_publish(('alice', 'alice'), c.note)
    assert row(c).status == 'cancelled'


def test_plugin_disable_stops_only_authenticated_matching_device_policy(queue):
    c = queue
    app = FastAPI()
    app.include_router(feishu_auto_local.device_router, prefix='/api')
    user = SimpleNamespace(id='bob')
    app.dependency_overrides[feishu_auto_local.get_current_user] = lambda: AuthenticatedUser(user_id=user.id)
    with TestClient(app) as client:
        path = '/api/feishu/automatic-deliveries/device-disable'
        assert client.post(path, json={'expected_user_id': 'alice'}).status_code == 409
        assert row(c).status == 'queued'
        user.id = 'alice'
        response = client.post(path, json={'expected_user_id': 'alice'})
        assert response.status_code == 200 and response.json()['device_auto_enabled'] is False
        assert row(c).status == 'cancelled'


@pytest.mark.parametrize('status,phase', [('queued', 'pending_create'), ('processing', 'writing'),
                                        ('failed', 'unknown'), ('failed', 'permission_unknown'),
                                        ('completed', 'unknown')])
def test_accepted_handoff_does_not_authorize_new_manual_operation_before_provider_confirmation(
        queue, monkeypatch, status, phase):
    c = queue
    with c.scope() as db:
        item = db.get(FeishuAutoOutboxDB, c.operation)
        item.status, item.job_id = 'accepted', c.job
    monkeypatch.setattr(runtime, '_request', lambda r, **kw: {
        **receipt(c), 'status': status, 'phase': phase})
    with pytest.raises(HTTPException) as blocked:
        runtime.guard_manual_publish(('alice', 'alice'), c.note)
    assert blocked.value.status_code == 409


def test_confirmed_completed_original_allows_a_new_explicit_manual_publish(queue, monkeypatch):
    c = queue
    with c.scope() as db:
        item = db.get(FeishuAutoOutboxDB, c.operation)
        item.status, item.job_id = 'accepted', c.job
    monkeypatch.setattr(runtime, '_request', lambda r, **kw: {
        **receipt(c), 'status': 'completed', 'phase': 'completed'})
    runtime.guard_manual_publish(('alice', 'alice'), c.note)


def test_real_loop_stop_then_start_schedules_one_successor_after_inflight_pass(queue, monkeypatch):
    entered, release, successor = threading.Event(), threading.Event(), threading.Event()
    count = []

    def bounded_pass():
        count.append(threading.current_thread())
        if len(count) == 1:
            entered.set()
            assert release.wait(9)
        else:
            successor.set()

    monkeypatch.setattr(runtime, '_thread', None)
    monkeypatch.setattr(runtime, '_desired_running', False)
    monkeypatch.setattr(runtime, '_stop', threading.Event())
    monkeypatch.setattr(runtime, '_wake', threading.Event())
    monkeypatch.setattr(runtime, 'run_once', bounded_pass)
    try:
        runtime.start()
        assert entered.wait(2)
        old = runtime._thread
        runtime.stop()  # The real 5 second bounded join expires.
        assert old.is_alive()
        runtime.start()
        release.set()
        assert successor.wait(2)
        assert runtime.background_ready() and runtime._thread is not old
        # The successor may run before the old thread finishes its Python
        # finally bookkeeping. Its business loop has already returned.
        old.join(timeout=1)
        assert not old.is_alive()
    finally:
        release.set()
        runtime.stop()


def test_server_dispatcher_ignores_manual_legacy_unknown_and_failed_rows(queue, monkeypatch):
    from app.services.feishu_service import FeishuService
    c, dispatched = queue, []
    with c.scope() as db:
        db.get(FeishuAutoOutboxDB, c.operation).status = 'cancelled'
        for label, state, snapshot in [
            ('manual', 'queued', {'automatic': False}),
            ('legacy', 'queued', {'automatic': True}),
            ('unknown', 'failed', {'automatic': True, 'automatic_policy_id': c.policy}),
            ('new-auto', 'queued', {'automatic': True, 'automatic_policy_id': c.policy}),
        ]:
            job = FeishuDeliveryDB(id=label, owner='alice', note_key=label, revision=label,
                                  title='Synthetic', content='Synthetic', status=state)
            db.add(job)
            db.flush()
            db.add(FeishuDeliveryDestinationDB(delivery_id=label, snapshot=json.dumps(snapshot)))
    monkeypatch.setattr(FeishuService, 'for_owner', lambda self, owner: SimpleNamespace(
        process=lambda who, identifier: dispatched.append((who, identifier))))
    runtime.run_once()
    assert dispatched == [('alice', 'new-auto')]


def test_network_unknown_lookup_uses_original_origin_and_operation_never_resubmits(queue, monkeypatch):
    from app.services.cloud_account_service import CloudAccountService
    c, calls = queue, []
    monkeypatch.setattr(settings, 'feishu_service_url', 'https://integration.example')
    monkeypatch.setattr(settings, 'cloud_auth_url', 'https://identity.example')
    with c.scope() as db:
        db.add(CloudAccountDB(user_id='alice', issuer=settings.cloud_auth_url, subject='subject-a',
                              email='synthetic@example.com', session_encrypted='synthetic'))
        owner = outbox.cloud_owner(db, 'alice')  # flush explicitly; session autoflush may differ by engine.
        db.flush()
        owner = outbox.cloud_owner(db, 'alice')
        item = db.get(FeishuAutoOutboxDB, c.operation)
        item.status, item.integration_origin, item.cloud_owner = 'unknown', settings.feishu_service_url, owner
    monkeypatch.setattr(CloudAccountService, 'access_token', lambda self, user: 'synthetic-test-token')

    def request(method, url, **kw):
        calls.append((method, url, kw))
        return httpx.Response(404)

    monkeypatch.setattr(httpx, 'request', request)
    assert runtime.check_local('alice', c.note)['status'] == 'unknown'
    assert len(calls) == 1 and calls[0][0] == 'GET'
    assert calls[0][1] == settings.feishu_service_url + '/api/feishu/deliveries/by-operation/' + c.operation
    assert 'json' not in calls[0][2] and calls[0][2]['follow_redirects'] is False
