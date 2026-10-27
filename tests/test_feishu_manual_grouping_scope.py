"""Manual Wiki source grouping and legacy receipt guards with isolated fixtures."""
import copy
import hashlib
import json
import socket
import uuid
import pytest

from app.db_models import NoteDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuPublishReceiptDB, FeishuWriteBatchDB
from app.services import feishu_service as module, feishu_cli
from test_feishu_delivery import service  # noqa: F401

ROOT = dict(kind='wiki', space_id='offline-space', node_token='offline-root')


@pytest.fixture
def scenario(service, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No real CLI/network/provider execution')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(feishu_cli, 'run', forbidden)
    monkeypatch.setattr(service, 'request', forbidden)
    monkeypatch.setattr(service, 'user_token', lambda owner: 'offline-token')
    monkeypatch.setattr(service, 'check_destination', lambda owner, destination:
                        {**destination, 'can_attempt_create': True})
    service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[],
        destination_config=ROOT, permission_policy='inherit', group_meeting_versions=True))
    events = []
    monkeypatch.setattr(service, 'prepare_native_body', lambda *a: None)
    monkeypatch.setattr(service, 'create_at_destination', lambda *a:
                        events.append('create') or ('offline-doc', 'https://company.feishu.cn/wiki/offline-node'))
    monkeypatch.setattr(service, 'ensure_permission', lambda *a: dict(status='verified'))
    monkeypatch.setattr(service, 'write_document', lambda *a: events.append('write'))
    return service, events


def note(prefix=False, source_type='text', task=None):
    identifier = str(uuid.uuid4())
    with module.session_scope() as db:
        db.add(NoteDB(id=identifier, title='Writing', content='Saved paragraph.', status='done',
            source_type=source_type, task_id=task, scope='personal', created_by='a'))
    return ('publish:' if prefix else '') + identifier


def submit(service, key, operation=None, target=None):
    return service.enqueue('a', key, 'Writing', 'Saved paragraph.', operation_id=operation or str(uuid.uuid4()),
        source_mode='local_snapshot', destination_config=target or ROOT, notify_self=False, groups=[])


def frozen(job_id):
    with module.session_scope() as db:
        values = [[getattr(db.get(model, job_id), col.name) for col in model.__table__.columns]
                  for model in (module.FeishuDeliveryDB, FeishuDeliveryDestinationDB)]
        return copy.deepcopy(values + [[[r.owner, r.operation_id, r.fingerprint, r.job_id]
            for r in db.query(FeishuPublishReceiptDB).filter_by(job_id=job_id).all()]])


@pytest.mark.parametrize('prefix', [False, True])
def test_ordinary_note_first_manual_wiki_ignores_only_meeting_grouping(scenario, prefix):
    service, events = scenario
    key = note(prefix)
    operation = str(uuid.uuid4())
    accepted = submit(service, key, operation)
    assert accepted['group_meeting_versions'] is False
    assert submit(service, key, operation)['id'] == accepted['id']
    service.process('a', accepted['id'])
    assert service.delivery_by_id('a', accepted['id'])['status'] == 'completed'
    assert events == ['create', 'write']
    assert service.status('a')['group_meeting_versions'] is True
    assert submit(service, key)['id'] == accepted['id']  # Same complete grouping-aware intent.
    with module.session_scope() as db:
        account = db.get(module.FeishuConnectionDB, 'a')
        context = dict(destination=ROOT, permission_policy='inherit', notify_self=False,
            connection_id=json.loads(account.preferences)['connection_id'], groups=[],
            version_id=None, revision_id=None, group_meeting_versions=False)
        expected = hashlib.sha256((hashlib.sha256(b'Writing\nSaved paragraph.').hexdigest()
            + json.dumps(context, sort_keys=True)).encode()).hexdigest()
        assert db.get(module.FeishuDeliveryDB, accepted['id']).revision == expected


@pytest.mark.parametrize('damage', ['missing-task', 'corrupt-request', 'missing-owner', 'derived', 'wrong-owner'])
def test_missing_or_damaged_meeting_is_never_ordinary(scenario, tmp_path, monkeypatch, damage):
    from app.services.task_artifact_service import TaskArtifactService
    service, events = scenario
    monkeypatch.setattr(module.settings, 'output_dir', tmp_path / 'output')
    task = str(uuid.uuid4())
    key = note(task=task)
    if damage != 'missing-task':
        folder = TaskArtifactService().create_task_dir(task)
        (folder / 'recording_owner').write_text('a' if damage != 'wrong-owner' else 'other', encoding='utf-8')
        (folder / '.task_id').write_text(task, encoding='utf-8')
        (folder / 'request.json').write_text('{' if damage == 'corrupt-request' else json.dumps({'request': {'workflow': 'meeting'}}), encoding='utf-8')
        if damage == 'missing-owner': (folder / 'recording_owner').unlink()
        if damage == 'derived': (folder / 'source_reference.json').write_text('{}', encoding='utf-8')
    with pytest.raises(module.FeishuError) as caught:
        submit(service, key)
    assert caught.value.code == 'meeting_context_unverified'
    assert not events
    with module.session_scope() as db:
        assert db.query(module.FeishuDeliveryDB).count() == 0


def test_positive_nonmeeting_task_and_trusted_meeting_selection(scenario, tmp_path, monkeypatch):
    from app.services.task_artifact_service import TaskArtifactService
    from app.routers import note_library
    service, _ = scenario
    monkeypatch.setattr(module.settings, 'output_dir', tmp_path / 'output')
    artifacts = TaskArtifactService()
    monkeypatch.setattr(note_library, '_artifact_service', artifacts)
    keys = []
    for workflow in ('note_organization', 'meeting'):
        task = str(uuid.uuid4())
        folder = artifacts.create_task_dir(task)
        for name, value in {'.task_id': task, 'recording_owner': 'a',
            'request.json': json.dumps({'request': {'workflow': workflow}}),
            'source_media.json': json.dumps({'sha256': 'f' * 64})}.items():
            (folder / name).write_text(value, encoding='utf-8')
        keys.append(note(task=task))
    with module.session_scope() as db:
        for key, expected in zip(keys, (False, True)):
            assert service._manual_meeting_grouping(db, 'a', key, 'Writing', 'Saved paragraph.',
                ROOT, {'group_meeting_versions': True}) is expected
    # The production graphic/source guard is not weakened or replaced by this classifier.
    original_guard = service._guard_graphic_delivery
    seen = []
    monkeypatch.setattr(service, '_guard_graphic_delivery', lambda *args: seen.append(args[2]))
    accepted = submit(service, keys[0])
    assert accepted['group_meeting_versions'] is False and seen == [keys[0]]
    meeting = submit(service, keys[1])
    assert meeting['group_meeting_versions'] is True
    with module.session_scope() as db:
        ordinary_revision = db.get(module.FeishuDeliveryDB, accepted['id']).revision
        meeting_revision = db.get(module.FeishuDeliveryDB, meeting['id']).revision
        assert ordinary_revision != meeting_revision  # Same body/target; actual grouping is committed.
    assert original_guard.__name__ == '_guard_graphic_delivery'


@pytest.mark.parametrize('state', ['legacy-failed', 'legacy-completed', 'unknown-create', 'queued',
    'processing', 'unknown-message', 'unknown-batch', 'unknown-permission'])
@pytest.mark.parametrize('target_changed', [False, True])
def test_settings_and_new_operation_never_bypass_original_record(scenario, state, target_changed):
    service, events = scenario
    key, operation = note(prefix=True), str(uuid.uuid4())
    accepted = submit(service, key, operation)
    with module.session_scope() as db:
        job = db.get(module.FeishuDeliveryDB, accepted['id'])
        metadata = db.get(FeishuDeliveryDestinationDB, job.id)
        if state.startswith('legacy'):
            snapshot = json.loads(metadata.snapshot)
            snapshot.pop('meeting_grouping_protocol')
            snapshot.update(group_meeting_versions=True, app_id=service.config.feishu_app_id)
            metadata.snapshot = json.dumps(snapshot)
            # Historical Wiki revisions did not commit a grouping boolean.
            job.revision = 'legacy-revision-without-grouping'
            job.status, job.lease_until, metadata.phase = 'failed', '0', 'failed'
            metadata.error_code = 'meeting_source_unverified'
            if state == 'legacy-completed': job.status, metadata.phase = 'completed', 'completed'
        elif state == 'unknown-create': job.document_id, job.status, metadata.phase = '__creating__', 'failed', 'unknown'
        elif state == 'processing': job.status = 'processing'
        elif state == 'unknown-message':
            job.status, metadata.phase = 'completed', 'completed'
            job.recipients = json.dumps({'ou_a': {'name': 'A', 'status': 'unknown'}})
        elif state == 'unknown-batch':
            job.status, metadata.phase = 'completed', 'completed'
            db.add(FeishuWriteBatchDB(job_id=job.id, offset='0', state='unknown', fingerprint='f' * 64))
        elif state == 'unknown-permission':
            job.status, metadata.phase = 'completed', 'completed'
            job.recipients = json.dumps({'ou_a': {'name': 'A', 'status': 'pending', 'reading_permission': {'status': 'unknown'}}})
    before = frozen(accepted['id'])
    service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[],
        destination_config=ROOT, permission_policy='inherit', group_meeting_versions=False))
    assert submit(service, key, operation)['id'] == accepted['id']
    if not target_changed and not state.startswith('legacy'):
        # Exact revision lookup is query-only in every delivery state. Binding
        # a new operation to that receipt never grants another dispatch.
        duplicate_operation = str(uuid.uuid4())
        duplicate = submit(service, key, duplicate_operation)
        assert duplicate['id'] == accepted['id'] and duplicate['_dispatch_required'] is False
        after = frozen(accepted['id'])
        assert after[:2] == before[:2]
        assert all(receipt in after[2] for receipt in before[2])
        assert len(after[2]) == len(before[2]) + 1 and not events
        assert service.delivery_by_operation('a', duplicate_operation)['id'] == accepted['id']
        return
    with pytest.raises(module.FeishuError) as caught:
        submit(service, key, target={'kind': 'personal'} if target_changed else ROOT)
    assert caught.value.code == 'grouping_prior_delivery_requires_review'
    assert frozen(accepted['id']) == before and not events


def test_selection_change_between_preflight_and_commit_fails(scenario, monkeypatch):
    service, events = scenario
    original = service._enqueue
    def changed(*args, **kwargs):
        key = args[1]
        with module.session_scope() as db:
            db.get(NoteDB, key).source_type = 'meeting_recording'
        return original(*args, **kwargs)
    monkeypatch.setattr(service, '_enqueue', changed)
    with pytest.raises(module.FeishuError): submit(service, note())
    assert not events


@pytest.mark.parametrize('source_mode', [None, 'local_snapshot'])
def test_cache_only_writing_uses_explicit_snapshot_without_new_legacy_fingerprint_fields(scenario, source_mode):
    from app.services import feishu_receipt_service as receipts
    service, events = scenario
    key, operation = 'publish:text-' + str(uuid.uuid4()), str(uuid.uuid4())
    args = dict(operation_id=operation, source_mode=source_mode, destination_config=ROOT,
                notify_self=False, groups=[])
    if source_mode is None:
        with pytest.raises(module.FeishuError) as caught:
            service.enqueue('a', key, 'Writing', 'Saved paragraph.', **args)
        assert caught.value.code == 'meeting_source_unverified'
        return
    result = service.enqueue('a', key, 'Writing', 'Saved paragraph.', **args)
    expected = dict(note_key=key, title='Writing', content='Saved paragraph.', automatic=False,
        destination_config=ROOT, permission_policy=None, notify_self=False, groups=[], version_id=None,
        revision_id=None, source_mode=source_mode)
    with module.session_scope() as db:
        assert db.get(NoteDB, key.removeprefix('publish:')) is None
        record = db.get(FeishuPublishReceiptDB, ('a', operation))
        assert record.fingerprint == receipts.fingerprint(expected)
    service.save_preferences('a', dict(auto_publish=False, notify_self=False, groups=[],
        destination_config=ROOT, permission_policy='inherit', group_meeting_versions=False))
    assert service.enqueue('a', key, 'Writing', 'Saved paragraph.', **args)['id'] == result['id']
    assert not events  # Accept/query only; no implicit dispatch.


@pytest.mark.parametrize('binding', ['task-shaped', 'artifact', 'workspace', 'foreign-note', 'damaged-note'])
def test_explicit_snapshot_never_demotes_a_known_or_ambiguous_source(scenario, tmp_path, monkeypatch, binding):
    from app.services.task_artifact_service import TaskArtifactService
    service, events = scenario
    monkeypatch.setattr(module.settings, 'output_dir', tmp_path / 'sources')
    key = 'text-' + str(uuid.uuid4())
    if binding == 'task-shaped':
        key = str(uuid.uuid4())
    elif binding == 'artifact':
        folder = TaskArtifactService().create_task_dir(key)
        (folder / 'request.json').write_text('{', encoding='utf-8')
    elif binding == 'workspace':
        with module.session_scope() as db:
            db.add(module.WorkspaceNoteDB(owner='a', key=key, title='Writing', content='Saved paragraph.',
                source_type='meeting_video', source_device='desktop', metadata_json='{"task_id":"missing"}'))
    else:
        with module.session_scope() as db:
            db.add(NoteDB(id=key, created_by='other' if binding == 'foreign-note' else 'a',
                title='Writing', content='Saved paragraph.', status='done', scope='personal',
                source_type='meeting_recording', task_id=str(uuid.uuid4())))
    with pytest.raises(module.FeishuError) as caught:
        submit(service, 'publish:' + key)
    expected = 'meeting_context_unverified' if binding == 'damaged-note' else 'meeting_source_unverified'
    assert caught.value.code == expected and not events


def journal_state(job_id):
    with module.session_scope() as db:
        state = []
        for model in (module.FeishuDeliveryDB, FeishuDeliveryDestinationDB):
            row = db.get(model, job_id)
            state.append(None if row is None else [getattr(row, col.name) for col in model.__table__.columns])
        state.append([[r.owner, r.operation_id, r.fingerprint, r.job_id]
                      for r in db.query(FeishuPublishReceiptDB).filter_by(job_id=job_id).all()])
        return copy.deepcopy(state)


@pytest.mark.parametrize('old_prefix', [False, True])
@pytest.mark.parametrize('missing', [False, True])
def test_cache_aliases_and_missing_metadata_preserve_unknown_journals(scenario, old_prefix, missing):
    service, events = scenario
    canonical = 'text-' + str(uuid.uuid4())
    old_key = ('publish:' if old_prefix else '') + canonical
    operation = str(uuid.uuid4())
    old = submit(service, old_key, operation)
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, old['id'])
        row.status, row.document_id, row.lease_until = 'failed', '__creating__', '0'
        metadata = db.get(FeishuDeliveryDestinationDB, old['id'])
        if missing: db.delete(metadata)
        else: metadata.phase = 'unknown'
    before = journal_state(old['id'])
    assert submit(service, old_key, operation)['id'] == old['id']
    opposite = canonical if old_prefix else 'publish:' + canonical
    with pytest.raises(module.FeishuError): submit(service, opposite, target={'kind': 'personal'})
    assert journal_state(old['id']) == before and not events


@pytest.mark.parametrize('damage', ['invalid-json', 'nonobject', 'missing-destination',
    'missing-kind', 'unknown-kind'])
def test_malformed_legacy_metadata_is_not_an_absent_delivery(scenario, damage):
    service, events = scenario
    key = note()
    old = submit(service, key)
    with module.session_scope() as db:
        metadata = db.get(FeishuDeliveryDestinationDB, old['id'])
        metadata.snapshot = {'invalid-json': '{', 'nonobject': 'null', 'missing-destination': '{}',
            'missing-kind': '{"destination": {}}',
            'unknown-kind': '{"destination": {"kind": "unknown"}}'}[damage]
    before = journal_state(old['id'])
    with pytest.raises(module.FeishuError): submit(service, 'publish:' + key, target={'kind': 'personal'})
    assert journal_state(old['id']) == before and not events


@pytest.mark.parametrize('different', ['object', 'owner'])
def test_alias_protection_never_merges_other_objects_or_owners_by_equal_body(scenario, different):
    service, events = scenario
    key = note()
    old = submit(service, key)
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, old['id'])
        row.status, row.document_id = 'failed', '__creating__'
        db.get(FeishuDeliveryDestinationDB, row.id).phase = 'unknown'
        if different == 'owner': row.owner = 'other'
    before = journal_state(old['id'])
    new = submit(service, note() if different == 'object' else key)
    assert new['id'] != old['id']
    assert journal_state(old['id']) == before and not events
