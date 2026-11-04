"""Original identity is owner-bound metadata, never title or URL matching."""
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.local_file import LocalFileDB
from app.models.note_library import NoteRecordResponse
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def case(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'source.db'))
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db
    artifacts = TaskArtifactService(tmp_path / 'output')
    def task(owner='alice', workflow='note_organization'):
        identifier = str(uuid4())
        folder = artifacts.create_task_dir(identifier)
        artifacts.write_text(folder / '.task_id', identifier)
        artifacts.write_text(folder / 'recording_owner', owner)
        artifacts.write_json(folder / 'request.json', {'request': {'workflow': workflow}})
        artifacts.write_json(folder / 'source_media.json', {'sha256': 'a' * 64})
        return identifier, folder
    now = datetime.now(timezone.utc)
    def note(task_id):
        return NoteRecordResponse(id=str(uuid4()), title='Same title', content='Different versions',
            task_id=task_id, status='done', created_at=now, updated_at=now)
    yield artifacts, sessions, task, note
    engine.dispose()


def project(case, note):
    from app.services.note_original_projection import original_source
    return original_source(note, 'alice', case[0], case[1])


def test_versions_share_verified_single_hop_original(case):
    artifacts, _, task, note = case
    original, _ = task()
    child, folder = task()
    artifacts.write_json(folder / 'source_reference.json', dict(version=1, owner='alice',
        parent_task_id=original, source_version='a' * 64))
    assert project(case, note(original)) == project(case, note(child)) == {
        'owner_id': 'alice', 'original_id': 'task:' + original, 'canonical_task_id': original}


@pytest.mark.parametrize('damage', ['foreign_owner', 'wrong_hash', 'reference_chain', 'unknown_workflow'])
def test_unverified_relations_never_merge(case, damage):
    artifacts, _, task, note = case
    original, root = task(owner='bob' if damage == 'foreign_owner' else 'alice',
                          workflow='unknown' if damage == 'unknown_workflow' else 'note_organization')
    child, folder = task()
    artifacts.write_json(folder / 'source_reference.json', dict(version=1, owner='alice',
        parent_task_id=original, source_version=('b' if damage == 'wrong_hash' else 'a') * 64))
    if damage == 'reference_chain':
        artifacts.write_json(root / 'source_reference.json', {})
    assert project(case, note(child)) is None


def test_owned_registered_document_has_stable_file_identity(case):
    artifacts, sessions, task, note = case
    identifier, folder = task()
    (folder / 'source_media.json').unlink()
    (folder / 'request.json').unlink()
    artifacts.write_json(folder / 'source_job.json', {'options': {}})
    file_id = str(uuid4())
    with sessions() as db:
        db.add(LocalFileDB(id=file_id, owner='alice', filename='original.pdf', category='file',
            purpose='note', path='unused-original.pdf', size_bytes=5, task_id=identifier))
    assert project(case, note(identifier)) == {
        'owner_id': 'alice', 'original_id': 'file:' + file_id, 'canonical_task_id': identifier}


def test_same_title_and_url_do_not_create_identity(case):
    _, _, _, note = case
    assert project(case, note(str(uuid4()))) is None
