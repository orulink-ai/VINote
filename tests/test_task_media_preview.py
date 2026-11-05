from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import note
from app.services.task_artifact_service import TaskArtifactService


def test_owned_task_preview_does_not_depend_on_a_surviving_note(tmp_path, monkeypatch):
    artifacts = TaskArtifactService(tmp_path / 'output')
    folder = artifacts.create_task_dir('recording')
    (folder / 'status.json').write_text('{"status":"failed"}')
    (folder / 'recording_owner').write_text('owner')
    (folder / 'media').mkdir()
    original = folder / 'media/source_audio.wav'
    original.write_bytes(b'original recording')
    artifacts.record_source_media(folder, original, media_kind='audio')
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    monkeypatch.setattr('app.services.note_repository.NoteRepository.can_access_task', lambda *args: False)
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id='owner')
    with TestClient(app) as client:
        url = '/api/task/recording/media?playback=true'
        response = client.get(url, headers={'Range': 'bytes=0-7'})
        assert response.status_code == 206
        assert response.content == b'original'
        assert response.headers['cache-control'] == 'private, no-store'
        app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id='other')
        assert client.get(url).status_code == 404
        app.dependency_overrides[note.get_optional_current_user] = lambda: None
        assert client.get(url).status_code == 404
