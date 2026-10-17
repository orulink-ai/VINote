from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.note_library import NoteCreateRequest
from app.services.meeting_media_service import MeetingMediaService
from app.services.note_repository import NoteRepository
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def recording(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'test.db'))
    Base.metadata.create_all(engine)
    @contextmanager
    def scope():
        with Session(engine, expire_on_commit=False) as db:
            yield db
            db.commit()
    monkeypatch.setattr('app.services.note_repository.session_scope', scope)
    monkeypatch.setattr('app.services.meeting_media_service.session_scope', scope)
    artifacts = TaskArtifactService(output_dir=tmp_path / 'output')
    monkeypatch.setattr('app.services.meeting_media_service.TaskArtifactService', lambda: artifacts)
    folder = artifacts.create_task_dir('task-recording')
    artifacts.update_status(folder, 'success', 'ready')
    source = tmp_path / 'original.webm'
    source.write_bytes(b'original recording')
    artifacts.stage_source_media(folder, str(source), media_kind='video')
    (folder / 'recording_owner').write_text('owner', encoding='utf-8')
    (folder / 'note.md').write_text('Keep this note', encoding='utf-8')
    (folder / 'transcript.json').write_text('{}', encoding='utf-8')
    note = NoteRepository().create_note('owner', NoteCreateRequest(title='meeting', task_id='task-recording', source_type='meeting_video'))
    yield MeetingMediaService(), note, folder, source
    engine.dispose()


def test_delete_removes_recording_but_keeps_notes_and_imported_original(recording):
    service, note, folder, original = recording
    assert service.info('owner', note.id)['available']
    service.delete('owner', note.id)
    assert not list((folder / 'media').glob('*.webm'))
    assert (folder / 'note.md').read_text() == 'Keep this note'
    assert (folder / 'transcript.json').exists()
    assert original.exists()
    assert service.info('owner', note.id)['deleted']
    service.delete('owner', note.id)  # idempotent retry


def test_other_user_cannot_delete(recording):
    service, note, folder, _ = recording
    with pytest.raises(HTTPException) as error:
        service.delete('other', note.id)
    assert error.value.status_code == 404
    assert list((folder / 'media').glob('*.webm'))


def test_shared_or_unverified_task_cannot_be_deleted(recording):
    service, note, folder, _ = recording
    (folder / 'recording_owner').write_text('other', encoding='utf-8')
    with pytest.raises(HTTPException) as error:
        service.delete('owner', note.id)
    assert error.value.status_code == 403
    (folder / 'recording_owner').write_text('owner', encoding='utf-8')
    NoteRepository().create_note('owner', NoteCreateRequest(title='copy', task_id=note.task_id))
    with pytest.raises(HTTPException):
        service.delete('owner', note.id)
    assert list((folder / 'media').glob('*.webm'))
