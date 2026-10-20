"""Saved-note transactions and real disk metadata, with no provider/model calls."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.db_models import NoteDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB, FeishuDevicePolicyDB, FeishuMeetingSaveDB
from app.models.local_file import LocalFileDB  # noqa: F401
from app.models.note_library import NoteCreateRequest, NoteUpdateRequest
from app.services import feishu_auto_outbox as outbox, note_repository, local_file_service
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def saved(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'outbox.db').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(outbox, 'session_scope', scope)
    monkeypatch.setattr(note_repository, 'session_scope', scope)
    monkeypatch.setattr(local_file_service, 'session_scope', scope)
    monkeypatch.setattr(settings, 'output_dir', tmp_path / 'output')
    monkeypatch.setattr(settings, 'feishu_service_url', '')
    (tmp_path / 'output').mkdir()
    policy = str(uuid.uuid4())
    status = {'automatic_delivery_protocol': 1, 'auto_publish': True,
              'automatic_delivery': {'policy_id': policy, 'enabled': True}}
    outbox.bind_device_policy('alice', status)
    c = SimpleNamespace(sessions=sessions, scope=scope, policy=policy, status=status,
                        repository=note_repository.NoteRepository(), root=tmp_path)
    yield c
    engine.dispose()


def payload(c, *, owner='alice', status='success', workflow='meeting', content='Synthetic saved minutes'):
    task = str(uuid.uuid4())
    artifacts = TaskArtifactService()
    folder = artifacts.create_task_dir(task)
    (folder / '.task_id').write_text(task, encoding='utf-8')
    (folder / 'recording_owner').write_text(owner, encoding='utf-8')
    (folder / 'request.json').write_text(json.dumps({'request': {'workflow': workflow}}), encoding='utf-8')
    artifacts.update_status(folder, status, 'Synthetic status')
    return NoteCreateRequest(title='Synthetic meeting', content=content,
                             task_id=task, source_type='meeting_recording', status='done')


def rows(c):
    with c.sessions() as db:
        return db.scalars(select(FeishuAutoOutboxDB)).all()


def test_first_completed_saved_meeting_atomically_freezes_one_handoff(saved):
    c = saved
    request = payload(c)
    note = c.repository.create_note('alice', request, generation_client='desktop')
    assert len(rows(c)) == 1
    queued = rows(c)[0]
    assert (queued.user_id, queued.note_id, queued.policy_id, queued.status) == ('alice', note.id, c.policy, 'queued')
    frozen = json.loads(queued.payload)
    assert frozen == {'operation_id': queued.id, 'policy_id': c.policy, 'note_key': note.id,
                      'title': request.title, 'content': request.content}
    c.repository.create_note('alice', request, generation_client='desktop')
    c.repository.update_note('alice', note.id, NoteUpdateRequest(content='Explicit later edit'))
    assert len(rows(c)) == 1 and json.loads(rows(c)[0].payload) == frozen


@pytest.mark.parametrize('change', ['disabled', 'web', 'failed', 'other_owner', 'ordinary_note', 'empty', 'wrong_workflow', 'missing_metadata', 'wrong_origin'])
def test_ineligible_or_unconsented_saves_still_save_without_delivery(saved, change):
    c = saved
    request = payload(c, owner='bob' if change == 'other_owner' else 'alice',
                      status='failed' if change == 'failed' else 'success',
                      workflow='note' if change == 'wrong_workflow' else 'meeting',
                      content='' if change == 'empty' else 'Synthetic saved minutes')
    if change == 'disabled':
        outbox.bind_device_policy('alice', None)
    if change == 'ordinary_note':
        request.source_type = 'file'
    if change == 'missing_metadata':
        folder = TaskArtifactService().find_task_dir(request.task_id)
        (folder / 'recording_owner').unlink()
    if change == 'wrong_origin':
        with c.scope() as db:
            db.get(FeishuDevicePolicyDB, 'alice').integration_origin = 'https://different.example'
    note = c.repository.create_note('alice', request, generation_client='web' if change == 'web' else 'desktop')
    assert c.repository.get_note('alice', note.id) is not None
    assert rows(c) == []


def test_enabling_never_discovers_old_rows_and_completion_transition_is_once(saved):
    c = saved
    outbox.bind_device_policy('alice', None)
    old = c.repository.create_note('alice', payload(c), generation_client='desktop')
    outbox.bind_device_policy('alice', c.status)
    c.repository.get_note('alice', old.id)
    c.repository.update_note('alice', old.id, NoteUpdateRequest(content='Edited old body'))
    c.repository.update_note('alice', old.id, NoteUpdateRequest(status='processing'))
    c.repository.update_note('alice', old.id, NoteUpdateRequest(status='done'))
    assert rows(c) == []
    request = payload(c)
    request.status = 'processing'
    pending = c.repository.create_note('alice', request, generation_client='desktop')
    assert rows(c) == []
    c.repository.update_note('alice', pending.id, NoteUpdateRequest(status='done'))
    assert len(rows(c)) == 1
    c.repository.update_note('alice', pending.id, NoteUpdateRequest(status='done'))
    assert len(rows(c)) == 1


def test_permanent_delete_and_resave_deterministic_id_still_saves_without_new_delivery(saved):
    c = saved
    request = payload(c)
    note = c.repository.create_note('alice', request, generation_client='desktop')
    assert len(rows(c)) == 1
    assert c.repository.delete_note('alice', note.id)
    again = c.repository.create_note('alice', request, generation_client='desktop')
    assert again.id == note.id and len(rows(c)) == 1


def test_disabling_cancels_only_unsent_and_never_retargets_or_relabels_unknown(saved):
    c = saved
    c.repository.create_note('alice', payload(c), generation_client='desktop')
    item = rows(c)[0]
    with c.scope() as db:
        row = db.get(FeishuAutoOutboxDB, item.id)
        row.status = 'unknown'
    outbox.bind_device_policy('alice', None)
    assert rows(c)[0].status == 'unknown'
    outbox.bind_device_policy('alice', c.status)
    c.repository.create_note('alice', payload(c), generation_client='desktop')
    outbox.bind_device_policy('alice', None)
    assert {r.status for r in rows(c)} == {'cancelled', 'unknown'}


def test_outbox_and_note_rollback_together_on_transaction_failure(saved, monkeypatch):
    c = saved
    request = payload(c)
    original = outbox.capture_saved_meeting

    def fail_after_capture(db, record):
        original(db, record)
        raise RuntimeError('Synthetic transaction interruption')

    monkeypatch.setattr(outbox, 'capture_saved_meeting', fail_after_capture)
    with pytest.raises(RuntimeError, match='interruption'):
        c.repository.create_note('alice', request, generation_client='desktop')
    with c.sessions() as db:
        assert db.scalars(select(NoteDB)).all() == []
        assert db.scalars(select(FeishuMeetingSaveDB)).all() == []
    assert rows(c) == []
