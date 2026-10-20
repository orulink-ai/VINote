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
from app.models.meeting_source_link import ConfirmMeetingSourceLink, MeetingSourceLinkDB
from app.services.meeting_source_link import MeetingSourceLinkService
from app.services.task_artifact_service import TaskArtifactService


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
