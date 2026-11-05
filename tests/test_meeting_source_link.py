"""Synthetic real-file/DB grouping tests. No media/model/cloud operations."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db_models import NoteDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB  # register tables before fixture create_all
from app.models.feishu_destination import FeishuDeliveryDestinationDB  # register tables before fixture create_all
from app.models.feishu_native_images import FeishuNativeImagePlanDB  # register tables before fixture create_all
from app.models.meeting_source_link import ConfirmMeetingSourceLink, MeetingSourceLinkDB
from app.services.meeting_source_link import MeetingSourceLinkService
from app.services.task_artifact_service import TaskArtifactService
from app.services import meeting_deletion


@pytest.fixture
def case(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('No network'))
    engine = create_engine('sqlite:///' + str(tmp_path / 'links.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    from app import db as database
    monkeypatch.setattr(database, 'session_scope', sessions)

    artifacts = TaskArtifactService(tmp_path / 'output')
    service = MeetingSourceLinkService(sessions, artifacts)
    note_id = str(uuid4())
    with sessions() as db:
        db.add(NoteDB(id=note_id, created_by='alice', title='Unrelated old title', content='Keep this exact old text',
                      source_type='meeting_video', task_id=None, status='done', scope='personal'))

    def target(owner='alice', workflow='meeting', kind='video'):
        task = str(uuid4())
        folder = artifacts.create_task_dir(task)
        artifacts.write_text(folder / '.task_id', task)
        artifacts.write_text(folder / 'recording_owner', owner)
        artifacts.write_json(folder / 'request.json', {'request': {'workflow': workflow, 'title': 'Not a timestamp'}})
        media = folder / 'media'; media.mkdir()
        source = media / ('source_video.webm' if kind == 'video' else 'source_audio.wav')
        source.write_bytes(b'synthetic original recording')
        artifacts.record_source_media(folder, source, media_kind=kind)
        sha = artifacts._sha256(source)
        return SimpleNamespace(task=task, folder=folder, source=source, sha=sha)

    original = target()
    body = ConfirmMeetingSourceLink(confirmed=True, canonical_task_id=original.task, source_version=original.sha)
    yield SimpleNamespace(**locals())
    engine.dispose()


def test_explicit_link_only_persists_display_relation_and_is_idempotent(case):
    c = case
    before = {p: p.read_bytes() for p in c.artifacts.output_dir.rglob('*') if p.is_file()}
    result = c.service.confirm('alice', c.note_id, c.body)
    assert result['meeting_source'] == {'owner_id': 'alice', 'canonical_task_id': c.original.task,
                                        'recording_started_at': None}
    assert result['revision'] == 1
    assert c.service.confirm('alice', c.note_id, c.body) == result
    with c.sessions() as db:
        note = db.get(NoteDB, c.note_id)
        assert note.task_id is None and note.content == 'Keep this exact old text'
        assert note.title == 'Unrelated old title'
        assert len(db.scalars(select(MeetingSourceLinkDB)).all()) == 1
    assert before == {p: p.read_bytes() for p in c.artifacts.output_dir.rglob('*') if p.is_file()}


def test_meeting_delete_removes_linked_notes_and_recovers_cleanup(case, monkeypatch):
    c = case
    from app import db as database
    monkeypatch.setattr(database, 'session_scope', c.sessions)
    c.service.confirm('alice', c.note_id, c.body)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    original_rmtree = meeting_deletion.shutil.rmtree
    monkeypatch.setattr(meeting_deletion.shutil, 'rmtree', lambda path: (_ for _ in ()).throw(OSError('busy')))
    with pytest.raises(HTTPException) as failed:
        meeting_deletion.delete_meeting('alice', c.original.task)
    assert failed.value.status_code == 409
    assert not isinstance(failed.value.detail, dict) or failed.value.detail.get('code') != 'deletion_not_started'
    with c.sessions() as db:
        assert db.get(NoteDB, c.note_id) is None
        assert meeting_deletion.deleted_task(db, c.original.task)
    from app.services import local_file_service
    monkeypatch.setattr(local_file_service, 'session_scope', c.sessions)
    pending = local_file_service.LocalFileService().list('alice')['items']
    assert any(item['task_id'] == c.original.task and item.get('deletion_pending') for item in pending)
    monkeypatch.setattr(meeting_deletion.shutil, 'rmtree', original_rmtree)
    result = meeting_deletion.delete_meeting('alice', c.original.task)
    assert result == {'deleted': True, 'note_ids': [c.note_id], 'task_ids': [c.original.task]}
    assert not c.original.folder.exists()
    assert meeting_deletion.delete_meeting('alice', c.original.task) == result


def test_meeting_delete_rejects_another_owners_note(case, monkeypatch):
    c = case
    from app import db as database
    monkeypatch.setattr(database, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    with c.sessions() as db:
        db.add(NoteDB(id=str(uuid4()), created_by='bob', title='other', content='keep',
                      source_type='meeting_video', task_id=c.original.task, scope='personal'))
    with pytest.raises(HTTPException) as denied:
        meeting_deletion.delete_meeting('alice', c.original.task)
    assert denied.value.status_code == 409
    assert c.original.source.exists()


def test_meeting_delete_includes_child_and_retained_copy(case, monkeypatch):
    c = case
    from app.services import local_file_service
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(local_file_service, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    child_id = str(uuid4())
    child = c.artifacts.create_task_dir(child_id)
    c.artifacts.write_text(child / '.task_id', child_id)
    c.artifacts.write_text(child / 'recording_owner', 'alice')
    c.artifacts.write_json(child / 'status.json', {'status': 'failed'})
    c.artifacts.write_json(child / 'source_reference.json', {'version': 1, 'owner': 'alice',
        'parent_task_id': c.original.task, 'source_version': c.original.sha})
    child_note = str(uuid4())
    with c.sessions() as db:
        db.add(NoteDB(id=child_note, created_by='alice', title='child', content='child',
                      source_type='meeting_video', task_id=child_id, scope='personal'))
    files = local_file_service.LocalFileService()
    file_id, name, path = files.new_target('alice', 'recording.wav')
    path.write_bytes(b'original copy')
    files.register('alice', file_id, name, path, 'meeting')
    files.attach_task('alice', file_id, c.original.task)
    projected = next(item for item in files.list('alice')['items'] if item['id'] == file_id)
    assert projected['canonical_task_id'] == c.original.task
    result = meeting_deletion.delete_meeting('alice', c.original.task)
    assert set(result['task_ids']) == {c.original.task, child_id}
    assert result['note_ids'] == [child_note]
    assert not path.exists() and not child.exists() and not c.original.folder.exists()
    with c.sessions() as db:
        assert db.get(NoteDB, child_note) is None
    from app.services import note_repository
    from app.models.note_library import NoteCreateRequest
    monkeypatch.setattr(note_repository, 'session_scope', c.sessions)
    with pytest.raises(ValueError, match='会议已删除'):
        note_repository.NoteRepository().create_note('alice', NoteCreateRequest(
            title='stale', task_id=child_id, source_type='meeting_video'))


def test_meeting_delete_rejects_running_task(case, monkeypatch):
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'processing'})
    with pytest.raises(HTTPException) as denied:
        meeting_deletion.delete_meeting('alice', c.original.task)
    assert denied.value.status_code == 409 and c.original.source.exists()


@pytest.mark.parametrize('state', ['queued', 'waiting_participants', 'failed', 'cancelled', 'unknown', 'accepted'])
@pytest.mark.parametrize('prefix', ['', 'publish:', 'desktop-', 'publish:desktop-'])
def test_delete_scrubs_related_feishu_bodies_and_keeps_receipt_state(case, monkeypatch, state, prefix):
    from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
    from app.db_models import FeishuDeliveryDB
    from app.models.feishu_destination import FeishuDeliveryDestinationDB
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    c.service.confirm('alice', c.note_id, c.body)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    op, job, unrelated = str(uuid4()), str(uuid4()), str(uuid4())
    with c.sessions() as db:
        db.add(FeishuAutoOutboxDB(id=op, user_id='alice', note_id=c.note_id, policy_id='policy',
            integration_origin='cli://device', cloud_owner='alice', payload='{"content":"secret minutes"}',
            status=state, job_id=job if state == 'accepted' else '', lease_until=0))
        db.add(FeishuDeliveryDB(id=job, owner='alice', note_key=prefix + c.note_id, revision='rev',
            title='private title', content='secret minutes', status='completed', lease_until='0'))
        db.add(FeishuDeliveryDB(id=unrelated, owner='bob', note_key=prefix + c.note_id, revision='rev',
            title='other title', content='other body', status='completed', lease_until='0'))
        db.add(FeishuDeliveryDestinationDB(delivery_id=job, snapshot='{"format_segments":["secret minutes"]}'))
        db.add(FeishuNativeImagePlanDB(owner='alice', job_id=job, fingerprint='fingerprint',
            manifest='{"events":[{"body":"secret minutes"}]}'))
    meeting_deletion.delete_meeting('alice', c.original.task)
    with c.sessions() as db:
        row, delivery = db.get(FeishuAutoOutboxDB, op), db.get(FeishuDeliveryDB, job)
        assert row.payload == '{}'
        assert row.status == ('cancelled' if state in {'queued', 'waiting_participants'} else state)
        assert delivery.content == '' and delivery.title == ''
        assert 'secret minutes' not in db.get(FeishuDeliveryDestinationDB, job).snapshot
        assert 'secret minutes' not in db.get(FeishuNativeImagePlanDB, job).manifest
        assert db.get(FeishuDeliveryDB, unrelated).content == 'other body'


@pytest.mark.parametrize('state', ['submitting', 'delivery_queued', 'delivery_processing'])
@pytest.mark.parametrize('prefix', ['', 'publish:desktop-'])
def test_delete_refuses_while_feishu_delivery_is_active(case, monkeypatch, state, prefix):
    from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
    from app.db_models import FeishuDeliveryDB
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    c.service.confirm('alice', c.note_id, c.body)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    with c.sessions() as db:
        db.add(FeishuAutoOutboxDB(id=str(uuid4()), user_id='alice', note_id=c.note_id,
            policy_id='policy', integration_origin='cli://device', cloud_owner='alice', payload='{"content":"keep"}',
            status='submitting' if state == 'submitting' else 'accepted', lease_until=0))
        if state != 'submitting':
            db.add(FeishuDeliveryDB(id=str(uuid4()), owner='alice', note_key=prefix + c.note_id, revision='rev',
                title='private', content='keep', status=state.removeprefix('delivery_'), lease_until='0'))
    with pytest.raises(HTTPException) as denied:
        meeting_deletion.delete_meeting('alice', c.original.task)
    assert denied.value.status_code == 409
    assert denied.value.detail['code'] == 'deletion_not_started'
    with c.sessions() as db:
        assert db.get(NoteDB, c.note_id) is not None
    assert c.original.source.exists()


def test_deleted_meeting_cannot_replay_feishu_delivery(case, monkeypatch):
    from app.db_models import FeishuDeliveryDB
    from app.services import feishu_service
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(feishu_service, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    c.service.confirm('alice', c.note_id, c.body)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    job = str(uuid4())
    with c.sessions() as db:
        db.add(FeishuDeliveryDB(id=job, owner='alice', note_key='publish:desktop-' + c.note_id, revision='rev',
            title='private', content='private body', status='failed', lease_until='0'))
    meeting_deletion.delete_meeting('alice', c.original.task)
    with pytest.raises(feishu_service.FeishuError) as denied:
        feishu_service.FeishuService().process('alice', job)
    assert denied.value.code == 'meeting_deleted'
    with pytest.raises(feishu_service.FeishuError) as enqueue_denied:
        feishu_service.FeishuService()._enqueue_locked(
            'alice', 'publish:desktop-' + c.note_id, 'stale', 'stale body', False, False, {}, 'private',
            False, [], [], None, None, 'content-hash', 'revision', {})
    assert enqueue_denied.value.code == 'meeting_deleted'
    with c.sessions() as db:
        assert db.get(FeishuDeliveryDB, job).content == ''


def test_delete_refuses_during_real_feishu_job_claim(case, monkeypatch):
    import threading
    from app.db_models import FeishuDeliveryDB
    from app.services import feishu_service
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(feishu_service, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    c.service.confirm('alice', c.note_id, c.body)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    job = str(uuid4())
    with c.sessions() as db:
        db.add(FeishuDeliveryDB(id=job, owner='alice', note_key=c.note_id, revision='rev',
            title='private', content='private body', status='failed', lease_until='0'))
    started, finish = threading.Event(), threading.Event()
    def stop_before_network(*args):
        started.set()
        finish.wait(5)
        raise feishu_service.FeishuError('synthetic test stop', 409)
    monkeypatch.setattr(feishu_service.FeishuService, 'assert_delivery_connection', stop_before_network)
    worker = threading.Thread(target=lambda: feishu_service.FeishuService().process('alice', job))
    worker.start()
    try:
        assert started.wait(5)
        with pytest.raises(HTTPException) as denied:
            meeting_deletion.delete_meeting('alice', c.original.task)
        assert denied.value.detail['code'] == 'deletion_not_started'
        assert c.original.source.exists()
    finally:
        finish.set()
        worker.join(5)
    assert not worker.is_alive()


def test_delete_blocks_active_unmapped_workspace_delivery_for_same_owner(case, monkeypatch):
    from app.db_models import FeishuDeliveryDB
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    c.service.confirm('alice', c.note_id, c.body)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    with c.sessions() as db:
        db.add(FeishuDeliveryDB(id=str(uuid4()), owner='alice', note_key='publish:arbitrary-workspace-key',
            revision='rev', title='possibly related', content='preserve', status='processing', lease_until='0'))
    with pytest.raises(HTTPException) as denied:
        meeting_deletion.delete_meeting('alice', c.original.task)
    assert denied.value.detail['code'] == 'deletion_not_started'
    assert c.original.source.exists()


def test_meeting_delete_http_replays_authoritative_ids(case, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import files as file_api
    from app.models.auth import AuthenticatedUser
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    monkeypatch.setattr(meeting_deletion.settings, 'workspace_cloud_runtime', False)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    app = FastAPI()
    app.include_router(file_api.router, prefix='/api')
    app.dependency_overrides[file_api.get_current_user] = lambda: AuthenticatedUser(user_id='alice')
    with TestClient(app) as client:
        url = '/api/files/task:' + c.original.task + '/meeting'
        first, replay = client.delete(url), client.delete(url)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json() == {'deleted': True, 'note_ids': [], 'task_ids': [c.original.task]}


@pytest.mark.parametrize('missing', ['source', 'deleted_marker', 'text_without_manifest'])
def test_meeting_delete_accepts_proven_missing_original(case, monkeypatch, missing):
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    with c.sessions() as db:
        note = db.get(NoteDB, c.note_id)
        note.task_id = c.original.task
    if missing == 'deleted_marker':
        (c.original.folder / 'recording_deleted').write_text('deleted', encoding='utf-8')
    c.original.source.unlink()
    if missing == 'text_without_manifest':
        (c.original.folder / 'source_media.json').unlink()
        c.artifacts.write_json(c.original.folder / 'transcript.json', {'full_text': 'meeting'})
    result = meeting_deletion.delete_meeting('alice', c.original.task)
    assert result['note_ids'] == [c.note_id]
    assert not c.original.folder.exists()


def test_missing_manifest_direct_owned_note_projects_deletable_identity(case, monkeypatch):
    from datetime import datetime, timezone
    from app.models.note_library import NoteRecordResponse
    from app.routers import note_library
    from app.services import note_original_projection
    c = case
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    (c.original.folder / 'source_media.json').unlink()
    with c.sessions() as db:
        db.get(NoteDB, c.note_id).task_id = c.original.task
    monkeypatch.setattr(note_library, '_artifact_service', c.artifacts)
    monkeypatch.setattr(note_library.settings, 'desktop_runtime', True)
    monkeypatch.setattr(note_original_projection, 'original_source', lambda *args: None)
    monkeypatch.setattr(MeetingSourceLinkService, 'project', lambda *args: None)
    now = datetime.now(timezone.utc)
    note = NoteRecordResponse(id=c.note_id, title='meeting', content='', task_id=c.original.task,
        source_type='meeting_video', status='done', scope='personal', created_at=now, updated_at=now)
    result = note_library._with_meeting_display_source(note, 'alice')
    assert result.meeting_source.canonical_task_id == c.original.task


def test_text_note_with_explicit_meeting_workflow_can_be_deleted(case, monkeypatch):
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    (c.original.folder / 'source_media.json').unlink()
    with c.sessions() as db:
        note = db.get(NoteDB, c.note_id)
        note.task_id, note.source_type = c.original.task, 'transcript'
    assert meeting_deletion.delete_meeting('alice', c.original.task)['note_ids'] == [c.note_id]


@pytest.mark.parametrize('damage', ['unproven_workflow', 'changed_original'])
def test_meeting_delete_rejects_unproven_or_changed_source(case, monkeypatch, damage):
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'success'})
    if damage == 'unproven_workflow':
        (c.original.folder / 'request.json').unlink()
        (c.original.folder / 'source_media.json').unlink()
        with c.sessions() as db:
            note = db.get(NoteDB, c.note_id)
            note.task_id, note.source_type = c.original.task, 'transcript'
    else:
        c.original.source.write_bytes(b'x' * c.original.source.stat().st_size)
    with pytest.raises(HTTPException) as denied:
        meeting_deletion.delete_meeting('alice', c.original.task)
    assert denied.value.status_code == 409 and c.original.folder.exists()


def test_missing_metadata_linked_meeting_file_projects_and_deletes(case, monkeypatch):
    from app.services import local_file_service
    c = case
    monkeypatch.setattr(meeting_deletion, 'session_scope', c.sessions)
    monkeypatch.setattr(local_file_service, 'session_scope', c.sessions)
    monkeypatch.setattr(meeting_deletion.settings, 'output_dir', c.artifacts.output_dir)
    monkeypatch.setattr(meeting_deletion.settings, 'data_dir', c.tmp_path)
    c.artifacts.write_json(c.original.folder / 'status.json', {'status': 'failed'})
    (c.original.folder / 'request.json').unlink()
    (c.original.folder / 'source_media.json').unlink()
    files = local_file_service.LocalFileService()
    identifier, name, path = files.new_target('alice', 'meeting.txt')
    path.write_bytes(b'meeting text')
    files.register('alice', identifier, name, path, 'meeting')
    files.attach_task('alice', identifier, c.original.task)
    item = next(item for item in files.list('alice')['items'] if item['id'] == identifier)
    assert item['canonical_task_id'] == c.original.task
    assert meeting_deletion.delete_meeting('alice', c.original.task)['task_ids'] == [c.original.task]
    assert not path.exists()


def assert_rejected(c, owner='alice', note_id=None, body=None, status=409):
    with pytest.raises(HTTPException) as error:
        c.service.confirm(owner, note_id or c.note_id, body or c.body)
    assert error.value.status_code == status
    with c.sessions() as db:
        assert db.scalars(select(MeetingSourceLinkDB)).all() == []


@pytest.mark.parametrize('owner,note_scope,note_status,source_type', [
    ('bob', 'personal', 'done', 'meeting_video'),
    ('alice', 'team', 'done', 'meeting_video'),
    ('alice', 'personal', 'trash', 'meeting_video'),
    ('alice', 'personal', 'done', 'document'),
])
def test_note_owner_personal_meeting_and_live_status_required(case, owner, note_scope, note_status, source_type):
    c = case
    with c.sessions() as db:
        note = db.get(NoteDB, c.note_id)
        note.scope, note.status, note.source_type = note_scope, note_status, source_type
    assert_rejected(c, owner=owner, status=409 if source_type == 'document' else 404)


@pytest.mark.parametrize('mutation', ['owner', 'workflow', 'reference', 'mapping', 'deleted', 'manifest_sha', 'source_changed', 'no_source'])
def test_target_requires_owner_workflow_canonical_and_original_identity(case, mutation):
    c = case; t = c.original
    if mutation == 'owner': (t.folder / 'recording_owner').write_text('bob')
    if mutation == 'workflow': c.artifacts.write_json(t.folder / 'request.json', {'request': {'workflow': 'note_organization'}})
    if mutation == 'reference': c.artifacts.write_json(t.folder / 'source_reference.json', {'parent_task_id': str(uuid4())})
    if mutation == 'mapping': (t.folder / '.task_id').write_text(str(uuid4()))
    if mutation == 'deleted': (t.folder / 'recording_deleted').write_text('deleted')
    if mutation == 'manifest_sha':
        manifest = json.loads((t.folder / 'source_media.json').read_text()); manifest['sha256'] = '0' * 64
        c.artifacts.write_json(t.folder / 'source_media.json', manifest)
    if mutation == 'source_changed': t.source.write_bytes(b'X' * t.source.stat().st_size)
    if mutation == 'no_source': t.source.unlink()
    assert_rejected(c)


def test_request_hash_and_expected_revision_are_compared_before_create(case):
    c = case
    assert_rejected(c, body=c.body.model_copy(update={'source_version': 'a' * 64}))
    assert_rejected(c, body=c.body.model_copy(update={'expected_revision': 3}))
    assert c.service.get('alice', c.note_id)['meeting_source'] is None


@pytest.mark.parametrize('one_hop', [False, True])
def test_proven_other_canonical_cannot_be_overridden_even_if_its_media_is_missing(case, one_hop):
    c = case; other = c.target()
    task = other.task
    if one_hop:
        task = str(uuid4()); child = c.artifacts.create_task_dir(task)
        c.artifacts.write_text(child / '.task_id', task)
        c.artifacts.write_text(child / 'recording_owner', 'alice')
        c.artifacts.write_json(child / 'source_reference.json', {
            'version': 1, 'owner': 'alice', 'parent_task_id': other.task, 'source_version': other.sha})
    with c.sessions() as db: db.get(NoteDB, c.note_id).task_id = task
    other.source.unlink()
    assert c.service.get('alice', c.note_id)['meeting_source']['canonical_task_id'] == other.task
    assert_rejected(c)


def test_same_proven_target_is_noop_not_a_second_manual_authority(case):
    c = case
    with c.sessions() as db: db.get(NoteDB, c.note_id).task_id = c.original.task
    result = c.service.confirm('alice', c.note_id, c.body)
    assert result['association_kind'] == 'artifact' and result['revision'] == 0
    with c.sessions() as db: assert db.scalars(select(MeetingSourceLinkDB)).all() == []


def test_manual_relation_cannot_be_rebound_and_old_row_is_retained(case):
    c = case; saved = c.service.confirm('alice', c.note_id, c.body)
    other = c.target()
    with pytest.raises(HTTPException):
        c.service.confirm('alice', c.note_id, c.body.model_copy(update={
            'canonical_task_id': other.task, 'source_version': other.sha, 'expected_revision': 1}))
    assert c.service.get('alice', c.note_id) == saved
    with pytest.raises(HTTPException):
        c.service.confirm('alice', c.note_id, c.body.model_copy(update={'expected_revision': 2}))
    assert c.service.project('bob', c.note_id) is None


def test_link_does_not_follow_changed_note_task_and_keeps_original_provenance(case):
    c = case; c.service.confirm('alice', c.note_id, c.body)
    with c.sessions() as db: db.get(NoteDB, c.note_id).task_id = str(uuid4())
    assert c.service.project('alice', c.note_id) is None
    with c.sessions() as db: assert db.get(MeetingSourceLinkDB, ('alice', c.note_id)).original_note_task_id is None


def test_saved_display_relation_survives_missing_media_without_adding_access(case):
    c = case; saved = c.service.confirm('alice', c.note_id, c.body)
    c.original.source.unlink()
    assert c.service.get('alice', c.note_id) == saved
    assert c.service.targets('alice') == {'targets': []}
    with c.sessions() as db: assert db.get(NoteDB, c.note_id).task_id is None
    assert c.artifacts.resolve_source_media(c.original.folder) is None


def test_changed_target_owner_invalidates_projection_but_keeps_record(case):
    c = case; c.service.confirm('alice', c.note_id, c.body)
    (c.original.folder / 'recording_owner').write_text('bob')
    assert c.service.project('alice', c.note_id) is None
    with c.sessions() as db: assert db.get(MeetingSourceLinkDB, ('alice', c.note_id)) is not None


def test_targets_are_owner_canonical_only_and_never_infer_dates(case):
    c = case; c.target(owner='bob'); c.target(workflow='note_organization')
    first = c.service.targets('alice')['targets']
    assert len(first) == 1 and first[0]['canonical_task_id'] == c.original.task
    assert first[0]['recording_started_at'] is None and first[0]['display_name'] == '录制时间未记录'
    assert not any(key in first[0] for key in ('path', 'content_url', 'can_play', 'can_generate'))
    assert len(c.service.targets('bob')['targets']) == 1


def test_capture_time_uses_explicit_metadata_helper_not_title_or_mtime(case):
    c = case
    request = {'request': {'workflow': 'meeting', 'title': '2099-12-31 fake title',
        'extras': '录制开始时间：2026-10-20T01:02:03.000Z。录制结束时间：2026-10-20T01:03:04.000Z。'},
        'trace': {'source': 'desktop_recording', 'session_id': 'rec-123-abc', 'input': {
            'source': 'desktop_recording', 'workflow': 'meeting', 'recording_id': 'rec-123-abc',
            'filename': 'meeting-recording-2026-10-20-01-02-03.webm'}}}
    c.artifacts.write_json(c.original.folder / 'request.json', request)
    assert c.service.targets('alice')['targets'][0]['recording_started_at'] == '2026-10-20T01:02:03+00:00'
    assert c.service.targets('alice')['targets'][0]['display_name'] == '2026-10-20 01:02 UTC'
    result = c.service.confirm('alice', c.note_id, c.body)
    assert result['meeting_source']['recording_started_at'] == '2026-10-20T01:02:03+00:00'


@pytest.mark.parametrize('which', ['source', 'media_dir', 'owner', 'manifest'])
def test_real_symlinks_under_target_are_rejected(case, which):
    c = case; t = c.original
    target = {'source': t.source, 'media_dir': t.folder / 'media',
              'owner': t.folder / 'recording_owner', 'manifest': t.folder / 'source_media.json'}[which]
    moved = c.tmp_path / ('moved-' + target.name)
    target.rename(moved)
    # No skip: Windows developer-mode/admin symlink support is required for
    # this security regression to actually execute.
    target.symlink_to(moved, target_is_directory=which == 'media_dir')
    assert_rejected(c)


def test_two_workers_conflicting_initial_cas_only_one_succeeds(case):
    from concurrent.futures import ThreadPoolExecutor
    c = case; other = c.target()
    bodies = [c.body, c.body.model_copy(update={'canonical_task_id': other.task, 'source_version': other.sha})]
    def submit(body):
        try:
            c.service.confirm('alice', c.note_id, body)
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, bodies)) == [200, 409]
    with c.sessions() as db: assert len(db.scalars(select(MeetingSourceLinkDB)).all()) == 1


def test_metadata_change_after_hash_is_rejected_before_insert(case, monkeypatch):
    c = case; target = c.service._target
    def racing(owner, task, **kwargs):
        result = target(owner, task, **kwargs)
        if kwargs.get('verify_hash'):
            (c.original.folder / 'recording_owner').write_text('bob')
        return result
    monkeypatch.setattr(c.service, '_target', racing)
    assert_rejected(c)


def test_note_owner_change_after_hash_is_rechecked_in_write_transaction(case, monkeypatch):
    c = case; target = c.service._target
    def racing(owner, task, **kwargs):
        result = target(owner, task, **kwargs)
        if kwargs.get('verify_hash'):
            with c.sessions() as db: db.get(NoteDB, c.note_id).created_by = 'bob'
        return result
    monkeypatch.setattr(c.service, '_target', racing)
    assert_rejected(c, status=404)


def test_new_proven_note_relation_after_hash_is_rechecked_before_create(case, monkeypatch):
    c = case; other = c.target(); target = c.service._target
    def racing(owner, task, **kwargs):
        result = target(owner, task, **kwargs)
        if kwargs.get('verify_hash'):
            with c.sessions() as db: db.get(NoteDB, c.note_id).task_id = other.task
        return result
    monkeypatch.setattr(c.service, '_target', racing)
    assert_rejected(c)


def test_source_hardlink_does_not_become_a_target(case):
    import os
    c = case
    os.link(c.original.source, c.tmp_path / 'external-hardlink.webm')
    assert_rejected(c)


def test_manual_link_never_changes_artifact_only_projection(case, monkeypatch):
    from app.routers import note_library
    from app.services.note_repository import NoteRepository
    c = case
    monkeypatch.setattr(note_library, '_artifact_service', c.artifacts)
    c.service.confirm('alice', c.note_id, c.body)
    with c.sessions() as db: note = NoteRepository._to_response(db.get(NoteDB, c.note_id))
    assert note.task_id is None
    assert note_library._with_meeting_source(note, 'alice').meeting_source is None


def test_manual_display_wrapper_projects_without_expanding_artifact_authority(case, monkeypatch):
    from app.config import settings
    from app.routers import note_library
    from app.services import meeting_source_link
    from app.services.note_repository import NoteRepository
    c = case
    monkeypatch.setattr(settings, 'desktop_runtime', True)
    monkeypatch.setattr(note_library, '_artifact_service', c.artifacts)
    monkeypatch.setattr(meeting_source_link, 'MeetingSourceLinkService', lambda: c.service)
    c.service.confirm('alice', c.note_id, c.body)
    with c.sessions() as db: note = NoteRepository._to_response(db.get(NoteDB, c.note_id))
    display = note_library._with_meeting_display_source(note, 'alice')
    assert display.meeting_source.canonical_task_id == c.original.task
    assert display.meeting_source.owner_id == 'alice'
    assert display.task_id is None and display.content == note.content
    assert note_library._with_meeting_source(note, 'alice').meeting_source is None
    assert note_library._with_media_kind(note, 'alice').media_kind is None
    assert note_library._with_meeting_display_source(note, 'bob').meeting_source is None
    monkeypatch.setattr(settings, 'desktop_runtime', False)
    assert note_library._with_meeting_display_source(note, 'alice').meeting_source is None


def test_router_confirmation_authentication_schema_and_cloud_boundary(case, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.models.auth import AuthenticatedUser
    from app.routers import meeting_source_link as routes
    from app.services.auth_service import get_current_user
    c = case
    monkeypatch.setattr(settings, 'desktop_runtime', True)
    monkeypatch.setattr(settings, 'workspace_cloud_runtime', False)
    monkeypatch.setattr(settings, 'content_cloud_runtime', False)
    monkeypatch.setattr(routes, 'MeetingSourceLinkService', lambda: c.service)
    app = FastAPI(); app.include_router(routes.router, prefix='/api')
    with TestClient(app) as client:
        assert client.get('/api/meeting-source-links/targets').status_code == 401
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id='alice', email='alice@example.invalid')
        endpoint = '/api/meeting-source-links/' + c.note_id
        assert client.get(endpoint).json()['meeting_source'] is None
        assert client.get('/api/meeting-source-links/targets').status_code == 200
        for changed in ({'confirmed': False}, {'confirmed': 1}, {'confirmed': 'true'},
                        {'canonical_task_id': '../task'}, {'source_version': 'A' * 64}, {'expected_revision': True},
                        {'task_id': str(uuid4())}):
            assert client.put(endpoint, json={**c.body.model_dump(), **changed}).status_code == 422
        result = client.put(endpoint, json=c.body.model_dump())
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert client.get(endpoint, headers={'Authorization': 'Bearer synthetic'}).status_code == 403
        monkeypatch.setattr(settings, 'content_cloud_runtime', True)
        assert client.get('/api/meeting-source-links/targets').status_code == 403
        monkeypatch.setattr(settings, 'content_cloud_runtime', False)
        monkeypatch.setattr(settings, 'desktop_runtime', False)
        assert client.get('/api/meeting-source-links/targets').status_code == 403
