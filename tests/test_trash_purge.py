"""Real HTTP and isolated DB/files only: permanent text cleanup preserves media."""
from contextlib import contextmanager
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.db_models import NoteDB, NoteVersionDB, TeamDB, TeamMemberDB
from app.models.auth import AuthenticatedUser
from app.models.local_file import LocalFileDB
from app.routers import note_library
from app.services import note_repository, local_file_service
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def trash(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + (tmp_path / 'trash.db').as_posix(),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(note_repository, 'session_scope', scope)
    monkeypatch.setattr(local_file_service, 'session_scope', scope)
    monkeypatch.setattr(settings, 'output_dir', tmp_path / 'output')
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'data')
    artifacts = TaskArtifactService(settings.output_dir)
    monkeypatch.setattr(note_library, '_artifact_service', artifacts)
    owner = SimpleNamespace(id='alice')
    app = FastAPI()
    app.include_router(note_library.router, prefix='/api')
    app.dependency_overrides[note_library.get_current_user] = lambda: AuthenticatedUser(user_id=owner.id)
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, sessions=sessions, owner=owner, artifacts=artifacts, tmp=tmp_path)
    engine.dispose()


def note(c, *, owner='alice', scope='personal', task=None, team=None):
    identifier = str(uuid.uuid4())
    with c.sessions.begin() as db:
        db.add(NoteDB(id=identifier, created_by=owner, scope=scope, team_id=team,
            title='Synthetic saved text', content='Current synthetic body', task_id=task,
            source_type='meeting_video', status='done'))
        db.add(NoteVersionDB(id=str(uuid.uuid4()), note_id=identifier,
                             title='Old synthetic title', content='Old synthetic body'))
    return identifier


def present(c, identifier):
    with c.sessions() as db:
        return db.get(NoteDB, identifier) is not None


@pytest.mark.parametrize('suffix,kind', [('.wav', 'audio'), ('.webm', 'video')])
def test_personal_purge_removes_only_owned_body_and_versions_keeps_real_retained_bytes(trash, suffix, kind):
    c = trash
    task = str(uuid.uuid4())
    folder = c.artifacts.create_task_dir(task)
    c.artifacts.update_status(folder, 'success', 'Synthetic saved task')
    source = c.tmp / ('synthetic' + suffix)
    source.write_bytes(b'full retained synthetic recording bytes')
    retained = c.artifacts.stage_source_media(folder, str(source), media_kind=kind)
    (folder / 'recording_owner').write_text('alice', encoding='utf-8')
    (folder / 'transcript.json').write_bytes(b'{"full_text":"saved synthetic ASR"}')
    identifier, other = note(c, task=task), note(c, owner='bob')
    response = c.client.delete('/api/notes/' + identifier + '?personal_only=true')
    assert response.status_code == 204 and not response.content
    with c.sessions() as db:
        assert db.get(NoteDB, identifier) is None
        assert not db.scalars(select(NoteVersionDB).where(NoteVersionDB.note_id == identifier)).all()
        originals = db.scalars(select(LocalFileDB).where(LocalFileDB.owner == 'alice')).all()
        assert len(originals) == 1
        assert local_file_service.LocalFileService()._path(originals[0]).read_bytes() == source.read_bytes()
    assert present(c, other) and retained.read_bytes() == source.read_bytes()
    assert (folder / 'transcript.json').read_bytes() == b'{"full_text":"saved synthetic ASR"}'
    assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 404


def test_personal_purge_requires_authentication_before_any_deletion(trash):
    c = trash
    identifier = note(c)
    c.app.dependency_overrides.clear()
    assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 401
    assert present(c, identifier)


def test_foreign_owner_cannot_purge_even_if_exact_id_is_known(trash, monkeypatch):
    c = trash
    identifier = note(c, owner='bob')
    retain = []
    monkeypatch.setattr(local_file_service.LocalFileService, 'retain_note_original', lambda *args: retain.append(args))
    assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 404
    assert present(c, identifier) and not retain


def test_personal_trash_cannot_purge_accessible_team_content(trash, monkeypatch):
    c = trash
    with c.sessions.begin() as db:
        db.add(TeamDB(id='team', name='Synthetic shared team', owner_id='bob'))
        db.add(TeamMemberDB(id='member', team_id='team', user_id='alice', role='member'))
    identifier = note(c, owner='bob', scope='team', team='team')
    retain = []
    monkeypatch.setattr(local_file_service.LocalFileService, 'retain_note_original', lambda *args: retain.append(args))
    assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 404
    assert present(c, identifier) and not retain


def test_second_owner_scope_check_blocks_concurrent_move_to_team(trash, monkeypatch):
    c = trash
    with c.sessions.begin() as db:
        db.add(TeamDB(id='team', name='Synthetic shared team', owner_id='alice'))
        db.add(TeamMemberDB(id='member', team_id='team', user_id='alice', role='owner'))
    identifier = note(c)

    def move(*args):
        with c.sessions.begin() as db:
            row = db.get(NoteDB, identifier)
            row.scope, row.team_id = 'team', 'team'

    monkeypatch.setattr(local_file_service.LocalFileService, 'retain_note_original', move)
    assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 404
    assert present(c, identifier)


def test_retention_failure_keeps_body_and_versions_and_manual_retry_works(trash, monkeypatch):
    c = trash
    identifier = note(c)
    original = local_file_service.LocalFileService.retain_note_original
    with monkeypatch.context() as patch:
        def fail(*args):
            raise HTTPException(507, 'Synthetic disk unavailable; body retained')
        patch.setattr(local_file_service.LocalFileService, 'retain_note_original', fail)
        assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 507
    assert present(c, identifier)
    with c.sessions() as db:
        assert db.scalar(select(NoteVersionDB).where(NoteVersionDB.note_id == identifier)) is not None
    assert local_file_service.LocalFileService.retain_note_original is original
    assert c.client.delete('/api/notes/' + identifier + '?personal_only=true').status_code == 204
    assert not present(c, identifier)
