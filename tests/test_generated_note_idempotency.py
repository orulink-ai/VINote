from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.db import Base
from app.db_models import NoteDB, TeamDB, TeamMemberDB
from app.models.note_library import NoteCreateRequest
from app.services import note_repository as module

@pytest.fixture
def repo(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'notes.sqlite'), connect_args={'check_same_thread': False, 'timeout': 15})
    Base.metadata.create_all(engine)
    @contextmanager
    def scope():
        with Session(engine) as db, db.begin(): yield db
    monkeypatch.setattr(module, 'session_scope', scope)
    monkeypatch.setattr(module.feishu_auto_outbox, 'register_new_meeting', lambda *a: None)
    with scope() as db:
        for team in ['team-a', 'team-b']:
            db.add(TeamDB(id=team, name=team, owner_id='alice'))
            db.add(TeamMemberDB(team_id=team, user_id='alice'))
    yield module.NoteRepository(), scope
    engine.dispose()


def payload(**patch):
    return NoteCreateRequest(**{'title': '原稿', 'content': '原始正文', 'task_id': 'task-generated', 'source_type': 'webpage', **patch})


def test_generated_double_save_returns_existing_edit_without_overwrite(repo):
    service, scope = repo
    first = service.create_note('alice', payload())
    with scope() as db:
        db.get(NoteDB, first.id).content = '人工修改'
    second = service.create_note('alice', payload(title='后来标题', content='后来生成正文'))
    assert second.id == first.id and second.content == '人工修改'
    with scope() as db: assert len(db.scalars(select(NoteDB)).all()) == 1


def test_concurrent_same_generated_task_saves_one_note(repo):
    service, scope = repo
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: service.create_note('alice', payload()).id, range(2)))
    assert ids[0] == ids[1]
    with scope() as db: assert len(db.scalars(select(NoteDB)).all()) == 1


def test_identity_isolated_by_owner_and_original_workspace(repo):
    service, _ = repo
    personal = service.create_note('alice', payload())
    team_a = service.create_note('alice', payload(scope='team', team_id='team-a'))
    team_b = service.create_note('alice', payload(scope='team', team_id='team-b'))
    bob = service.create_note('bob', payload())
    assert len({personal.id, team_a.id, team_b.id, bob.id}) == 4
    assert service.create_note('alice', payload(scope='team', team_id='team-a')).id == team_a.id
    with pytest.raises(ValueError): service.create_note('bob', payload(scope='team', team_id='team-a'))


def test_manual_notes_without_task_remain_independent(repo):
    service, _ = repo
    assert service.create_note('alice', payload(task_id=None)).id != service.create_note('alice', payload(task_id=None)).id


def test_meeting_namespace_is_unchanged_and_old_generated_ids_remain(repo):
    service, scope = repo
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(['vinote-meeting', 'alice', 'meeting-task', 'personal', None])))
    assert service.create_note('alice', payload(task_id='meeting-task', source_type='meeting_recording')).id == expected
    with scope() as db:
        db.add(NoteDB(id='historical-id', created_by='alice', title='历史标题', content='历史正文', task_id='old-task', source_type='video', scope='personal', status='done'))
    assert service.create_note('alice', payload(task_id='old-task')).id == 'historical-id'


def test_exact_task_lookup_scopes_owner_and_team(repo):
    service, _ = repo
    service.create_note('alice', payload(task_id='wanted'))
    service.create_note('alice', payload(task_id='different'))
    service.create_note('bob', payload(task_id='wanted'))
    found = service.list_notes('alice', scope='personal', task_id='wanted')
    assert len(found) == 1 and found[0].task_id == 'wanted'


def test_http_exact_task_filter_reaches_repository(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import note_library
    from app.models.auth import AuthenticatedUser
    from app.services.auth_service import get_current_user
    calls = []
    monkeypatch.setattr(note_library._repository, 'list_notes', lambda user, **kwargs: calls.append((user, kwargs)) or [])
    app = FastAPI(); app.include_router(note_library.router, prefix='/api')
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser('alice')
    with TestClient(app) as client:
        assert client.get('/api/notes?scope=team&team_id=team-a&task_id=wanted').status_code == 200
    assert calls == [('alice', {'scope': 'team', 'team_id': 'team-a', 'task_id': 'wanted'})]
