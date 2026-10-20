import json
import os
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.routers import note
from app.services.task_artifact_service import TaskArtifactService
from app.services.meeting_draft_artifact import save_working_draft


@pytest.fixture
def case(tmp_path, monkeypatch):
    artifacts = TaskArtifactService(tmp_path / 'output')
    folder = artifacts.create_task_dir('private-task')
    artifacts.update_status(folder, 'summarizing', 'working draft only')
    (folder / 'media').mkdir()
    (folder / 'media/video.webm').write_bytes(b'original media')
    save_working_draft(artifacts, folder, 'Private working source')
    monkeypatch.setattr(note, '_require_recording_access', lambda task, user: None)
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    with TestClient(app) as client:
        yield artifacts, folder, client


@pytest.mark.parametrize('asset', ['meeting_working_draft.json', 'media/%2e%2e/meeting_working_draft.json',
    'screenshots/%2e%2e/meeting_working_draft.json', 'media/%5c..%5cmeeting_working_draft.json',
    'media/video.webm:meeting_working_draft.json'])
def test_media_urls_never_expose_working_draft(case, asset):
    _, _, client = case
    response = client.get('/api/task/private-task/artifacts/' + asset)
    assert response.status_code == 404 and 'Private working source' not in response.text
    assert client.get('/api/task/private-task/artifacts/media/video.webm').content == b'original media'


def test_hardlinked_diagnostic_target_cannot_overwrite_another_file(case, tmp_path):
    artifacts, folder, _ = case
    target = folder / 'meeting_working_draft.json'
    target.unlink()
    victim = tmp_path / 'other.json'
    victim.write_text('retained original', encoding='utf-8')
    os.link(victim, target)
    with pytest.raises(ValueError, match='target'):
        save_working_draft(artifacts, folder, 'must not overwrite')
    assert victim.read_text(encoding='utf-8') == 'retained original'


def test_symlink_diagnostic_target_and_media_alias_are_rejected(case, tmp_path):
    artifacts, folder, client = case
    target = folder / 'meeting_working_draft.json'
    target.unlink()
    victim = tmp_path / 'other.json'
    victim.write_text('private other file', encoding='utf-8')
    try:
        target.symlink_to(victim)
        (folder / 'media/alias.webm').symlink_to(victim)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    with pytest.raises(ValueError):
        save_working_draft(artifacts, folder, 'must not overwrite')
    assert victim.read_text(encoding='utf-8') == 'private other file'
    assert client.get('/api/task/private-task/artifacts/media/alias.webm').status_code == 404


def test_atomic_draft_replacement_is_private_and_not_a_completed_result(case, monkeypatch):
    artifacts, folder, _ = case
    before = (folder / 'meeting_working_draft.json').read_bytes()
    from app.services import meeting_draft_artifact as module
    monkeypatch.setattr(module.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises(OSError):
        save_working_draft(artifacts, folder, 'new draft')
    assert (folder / 'meeting_working_draft.json').read_bytes() == before
    assert not list(folder.glob('.working-draft-*.tmp'))
    assert not (folder / 'result.json').exists() and not (folder / 'note.md').exists()
