"""Final acceptance races over fixture-owned SQLite; no CLI or remote writes."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.meeting_participants import MeetingParticipantConfirmationDB as Confirmation
from app.services import feishu_service as module, meeting_participants, feishu_object_hotwords
from test_feishu_delivery import service  # noqa: F401
from test_feishu_contacts import contact_service, selection  # noqa: F401
from test_feishu_auto_policy import enable, policy_id, submit


@pytest.fixture
def attendance(contact_service, monkeypatch):
    instance = contact_service
    monkeypatch.setattr(module.settings, 'feishu_app_id', 'cli_review_test')
    policy = policy_id(enable(instance, monkeypatch, notify_participants=True))
    binding = instance.contact_binding('a')
    key = ('a', str(uuid4()), feishu_object_hotwords.binding_hash(binding))
    people = [{'open_id': 'ou_removed', 'name': 'Synthetic attendee'}]
    with module.session_scope() as db:
        db.add(Confirmation(owner=key[0], task_id=key[1], binding_hash=key[2],
            note_key='synthetic-new-meeting', evidence_revision='e' * 64,
            revision=1, participants_json=json.dumps(people), confirmed_at=time.time()))
    monkeypatch.setattr(meeting_participants, 'session_scope', module.session_scope)

    def context(*args, **kwargs):
        return ({'canonical_task_id': key[1], 'evidence_revision': 'e' * 64,
                 'contacts': [], 'candidates': [], 'unresolved': []}, key[1], binding, True)

    monkeypatch.setattr(meeting_participants, '_context', context)
    selection(instance, monkeypatch, open_id='ou_removed', name='Synthetic attendee')
    return SimpleNamespace(service=instance, policy=policy, key=key, people=people)


@pytest.mark.parametrize('change', ['clear', 'replace', 'revision', 'evidence', 'delete'])
def test_committed_confirmation_change_after_real_resolution_blocks_new_acceptance(attendance, monkeypatch, change):
    c = attendance
    original = c.service._enqueue

    def changed(*args, **kwargs):
        assert kwargs['attendance']['confirmation_revision'] == 1

        def concurrent_confirmation():
            with module.session_scope() as db:
                row = db.get(Confirmation, c.key)
                if change == 'delete':
                    db.delete(row)
                else:
                    row.revision += 1
                    if change == 'clear':
                        row.participants_json = '[]'
                    elif change == 'replace':
                        row.participants_json = json.dumps([
                            {'open_id': 'ou_replacement', 'name': 'Other synthetic attendee'}])
                    elif change == 'evidence':
                        row.evidence_revision = 'f' * 64

        # Deterministic interleaving: the other transaction commits before accept.
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(concurrent_confirmation).result(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(c.service, '_enqueue', changed)
    with pytest.raises(module.FeishuError) as caught:
        submit(c.service, c.policy)
    assert caught.value.code == 'attendance_confirmation_required'
    assert caught.value.uncertain is False
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 0
        assert db.query(FeishuDeliveryDestinationDB).count() == 0


@pytest.mark.parametrize('cleared', [False, True])
def test_current_confirmed_or_cleared_attendance_accepts_once_without_persisting_proofs(attendance, cleared):
    c = attendance
    if cleared:
        with module.session_scope() as db:
            db.get(Confirmation, c.key).participants_json = '[]'
    accepted = submit(c.service, c.policy)
    assert accepted['_dispatch_required'] is True
    assert set(accepted['recipients']) == ({'ou_b'} if cleared else {'ou_b', 'ou_removed'})
    with module.session_scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, accepted['id']).snapshot)
    assert 'selection_token' not in json.dumps(snapshot)
    assert '_confirmation_binding_hash' not in snapshot['meeting_attendance']


def test_confirmation_lock_is_held_until_delivery_accept_commit(attendance):
    c = attendance
    attempted = Event()
    statements, pending = [], []

    def clear():
        with module.session_scope() as db:
            attempted.set()
            db.execute(text('BEGIN IMMEDIATE'))
            row = db.get(Confirmation, c.key)
            row.revision += 1
            row.participants_json = '[]'

    with ThreadPoolExecutor(max_workers=1) as executor:
        def during_accept(execution):
            statement = execution.statement
            if (getattr(statement, '_for_update_arg', None) is not None
                    and any(item.get('entity') is Confirmation
                            for item in getattr(statement, 'column_descriptions', []))):
                assert execution.session.in_transaction()
                statements.append(str(statement.compile(dialect=postgresql.dialect())))
                pending.append(executor.submit(clear))
                assert attempted.wait(5)

        event.listen(Session, 'do_orm_execute', during_accept)
        try:
            accepted = submit(c.service, c.policy)
        finally:
            event.remove(Session, 'do_orm_execute', during_accept)
        assert len(pending) == 1 and 'FOR UPDATE' in statements[0]
        pending[0].result(timeout=5)
    # The clear waited for the acceptance transaction, so this frozen receipt
    # correctly keeps the earlier list; it must not be silently retargeted.
    assert set(accepted['recipients']) == {'ou_b', 'ou_removed'}
    with module.session_scope() as db:
        assert db.get(Confirmation, c.key).revision == 2
        assert db.get(Confirmation, c.key).participants_json == '[]'
        assert set(json.loads(db.get(module.FeishuDeliveryDB, accepted['id']).recipients)) == {'ou_b', 'ou_removed'}


@pytest.mark.parametrize('unknown', [False, True])
def test_changed_confirmation_does_not_retarget_or_replay_existing_operation(attendance, monkeypatch, unknown):
    c = attendance
    operation = str(uuid4())
    first = submit(c.service, c.policy, operation_id=operation)
    with module.session_scope() as db:
        row = db.get(Confirmation, c.key)
        row.revision += 1
        row.participants_json = '[]'
        delivery = db.get(module.FeishuDeliveryDB, first['id'])
        metadata = db.get(FeishuDeliveryDestinationDB, first['id'])
        if unknown:
            delivery.status = 'failed'
            metadata.phase = 'unknown'
        frozen = (delivery.recipients, metadata.snapshot, metadata.phase)
    monkeypatch.setattr(meeting_participants, 'resolve_saved_meeting',
                        lambda *a, **kw: pytest.fail('Existing operation is receipt-only'))
    second = submit(c.service, c.policy, operation_id=operation)
    assert second['id'] == first['id'] and second['_dispatch_required'] is False
    with module.session_scope() as db:
        delivery = db.get(module.FeishuDeliveryDB, first['id'])
        metadata = db.get(FeishuDeliveryDestinationDB, first['id'])
        assert (delivery.recipients, metadata.snapshot, metadata.phase) == frozen


@pytest.mark.parametrize('damage', ['missing_binding', 'wrong_binding', 'wrong_canonical', 'wrong_revision'])
def test_acceptance_requires_the_resolvers_exact_confirmation_scope(attendance, monkeypatch, damage):
    c = attendance
    original = c.service._enqueue

    def tampered(*args, **kwargs):
        view = kwargs['attendance']
        if damage == 'missing_binding':
            view.pop('_confirmation_binding_hash', None)
        elif damage == 'wrong_binding':
            view['_confirmation_binding_hash'] = '0' * 64
        elif damage == 'wrong_canonical':
            view['canonical_task_id'] = str(uuid4())
        else:
            view['confirmation_revision'] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(c.service, '_enqueue', tampered)
    with pytest.raises(module.FeishuError) as caught:
        submit(c.service, c.policy)
    assert caught.value.code == 'attendance_confirmation_required'
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 0


def test_final_acceptance_race_leaves_original_outbox_waiting_without_auto_resubmit(attendance, monkeypatch):
    from app.db_models import NoteDB
    from app.models.feishu_auto_delivery import FeishuAutoOutboxDB, FeishuDevicePolicyDB
    from app.services import feishu_auto_runtime as runtime, feishu_auto_outbox as outbox, feishu_cli
    c = attendance
    monkeypatch.setattr(runtime, 'session_scope', module.session_scope)
    monkeypatch.setattr(outbox, 'integration_origin', lambda: 'cli://device')
    monkeypatch.setattr(outbox, 'cloud_owner', lambda db, owner: owner)
    monkeypatch.setattr(feishu_cli, 'enabled', lambda: True)
    monkeypatch.setattr(module.FeishuService, 'for_owner', lambda self, owner: c.service)
    monkeypatch.setattr(runtime, 'wake', lambda: pytest.fail('Waiting intent must not dispatch'))
    operation = str(uuid4())
    payload = dict(operation_id=operation, policy_id=c.policy, note_key='synthetic-new-meeting',
                   title='Synthetic meeting', content='Synthetic complete minutes')
    with module.session_scope() as db:
        db.add(NoteDB(id=payload['note_key'], created_by='a', title=payload['title'],
                      content=payload['content'], scope='personal', status='done'))
        db.add(FeishuDevicePolicyDB(user_id='a', policy_id=c.policy, enabled=True,
                                   integration_origin='cli://device', cloud_owner='a'))
        db.add(FeishuAutoOutboxDB(id=operation, user_id='a', note_id=payload['note_key'],
            policy_id=c.policy, integration_origin='cli://device', cloud_owner='a',
            payload=json.dumps(payload), status='queued'))
    original = c.service._enqueue
    attempts = []

    def changed(*args, **kwargs):
        attempts.append(kwargs['attendance']['confirmation_revision'])
        with module.session_scope() as db:
            row = db.get(Confirmation, c.key)
            row.revision += 1
            row.participants_json = '[]'
        return original(*args, **kwargs)

    monkeypatch.setattr(c.service, '_enqueue', changed)
    runtime.attempt_device(operation)
    runtime.attempt_device(operation)
    assert attempts == [1]
    with module.session_scope() as db:
        row = db.get(FeishuAutoOutboxDB, operation)
        assert row.status == 'waiting_participants' and row.job_id == ''
        assert row.id == operation and json.loads(row.payload) == payload
        assert db.query(module.FeishuDeliveryDB).count() == 0
