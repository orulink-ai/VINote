from contextlib import contextmanager
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models.local_file import LocalFileDB
from app.models.meeting_source_link import MeetingDisplayUpdate
from app.services.meeting_display_metadata import MeetingDisplayService
from app.services.task_artifact_service import TaskArtifactService

@pytest.fixture
def case(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'display.db'))
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db
    artifacts = TaskArtifactService(tmp_path / 'output')
    task = str(uuid4()); folder = artifacts.create_task_dir(task)
    artifacts.write_text(folder / '.task_id', task)
    artifacts.write_text(folder / 'recording_owner', 'alice')
    artifacts.write_json(folder / 'request.json', {'request': {'workflow': 'meeting'}})
    source = folder / 'original.wav'; source.write_bytes(b'unchanged audio')
    artifacts.record_source_media(folder, source, media_kind='audio')
    yield MeetingDisplayService(sessions, artifacts), task, folder, sessions
    engine.dispose()

def test_edit_title_and_date_never_changes_canonical_or_source(case):
    service, task, folder, _ = case
    service.links._metadata('alice', task, capture_only=True)
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    row = service.update('alice', 'task', task, MeetingDisplayUpdate(title='周会', meeting_date='2026-11-04'))
    assert row == {'source_key': 'task:' + task, 'title': '周会', 'meeting_date': '2026-11-04'}
    assert service.list('alice')['items'] == [row]
    assert service.list('bob')['items'] == []
    assert before == {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    cleared = service.update('alice', 'task', task, MeetingDisplayUpdate())
    assert cleared['meeting_date'] is None and cleared['title'] == ''

def test_owner_and_canonical_boundary(case):
    service, task, folder, _ = case
    with pytest.raises(HTTPException): service.update('bob', 'task', task, MeetingDisplayUpdate(title='wrong'))
    (folder / 'source_reference.json').write_text('{}')
    with pytest.raises(HTTPException): service.update('alice', 'task', task, MeetingDisplayUpdate(title='child'))
    assert service.list('alice')['items'] == []

def test_import_metadata_survives_task_association_without_filename_changes(case):
    service, task, folder, sessions = case
    file_id = str(uuid4())
    with sessions() as db:
        db.add(LocalFileDB(id=file_id, owner='alice', filename='device-000123.wav', purpose='meeting', category='recording', path=str(folder / 'original.wav'), size_bytes=15, task_id=''))
    service.update('alice', 'file', file_id, MeetingDisplayUpdate(title='采购讨论', meeting_date='2026-10-31'))
    with sessions() as db:
        file = db.get(LocalFileDB, file_id); file.task_id = task
    items = {row['source_key']: row for row in service.list('alice')['items']}
    assert items['task:' + task]['title'] == '采购讨论'
    with sessions() as db: assert db.get(LocalFileDB, file_id).filename == 'device-000123.wav'
    with pytest.raises(HTTPException): service.update('bob', 'file', file_id, MeetingDisplayUpdate(title='wrong'))

@pytest.mark.parametrize('value', ['2026-02-30', '20261104', '2026-11-04T00:00:00Z', 'yesterday'])
def test_invalid_display_dates_are_rejected(value):
    with pytest.raises(ValidationError): MeetingDisplayUpdate(meeting_date=value)
