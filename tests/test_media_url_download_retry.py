"""Explicit download recovery never captures new models or repeats a worker."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import uuid
import pytest
from fastapi import BackgroundTasks, HTTPException
from app.models.note import NoteRequest
from app.services.task_artifact_service import TaskArtifactService
from test_media_url_submission import isolated_router, URL

@pytest.fixture
def retry_case(tmp_path, monkeypatch):
    note = isolated_router(); artifacts = TaskArtifactService(tmp_path / 'output')
    task = str(uuid.uuid4()); folder = artifacts.create_task_dir(task)
    (folder / 'recording_owner').write_text('owner')
    req = NoteRequest(video_url=URL)
    artifacts.write_json(folder / 'request.json', {'kind': 'media_url', 'request': req.model_dump(exclude={'api_key', 'base_url', 'model_name'}), 'trace': None})
    artifacts.update_status(folder, 'failed', 'download failed', failed_stage='downloading', retryable=True)
    note._note_service = SimpleNamespace(artifact_service=artifacts, generate=Mock())
    note.ensure_source = Mock(return_value={'frozen': True})
    monkeypatch.setattr(note, 'desktop_trace', lambda *_: nullcontext())
    return SimpleNamespace(note=note, artifacts=artifacts, task=task, folder=folder, req=req, owner=SimpleNamespace(user_id='owner'))

def test_download_retry_uses_original_url_once_and_clears_active(retry_case):
    c=retry_case; original=(c.folder/'request.json').read_bytes(); tasks=BackgroundTasks()
    result=c.note.retry_media_task(c.task,tasks,c.owner,model_confirmation=None)
    assert result['task_id']==c.task and len(tasks.tasks)==1
    assert c.note.ensure_source.call_args.kwargs.get('allow_capture',False) is False
    repeated=BackgroundTasks(); c.note.retry_media_task(c.task,repeated,c.owner,model_confirmation=None)
    assert not repeated.tasks
    work=tasks.tasks[0]; work.func(*work.args,**work.kwargs); work.func(*work.args,**work.kwargs)
    assert c.note._note_service.generate.call_count==1
    assert c.note._note_service.generate.call_args.kwargs['video_url']==URL
    assert c.task not in c.note._ACTIVE_FILE_TASKS
    assert (c.folder/'request.json').read_bytes()==original

@pytest.mark.parametrize('status,stage,retryable',[('downloading','downloading',True),('failed','summarizing',True),('failed','downloading',False),('failed','downloading',None),('failed','transcribing',True)])
def test_url_retry_rejects_active_unknown_or_non_download_outcomes(retry_case,status,stage,retryable):
    c=retry_case; c.artifacts.update_status(c.folder,status,'fixture',failed_stage=stage,retryable=retryable)
    current=c.artifacts.get_status(c.task); current['retryable']=retryable
    c.artifacts.write_json(c.folder/'status.json',current)
    with pytest.raises(HTTPException) as error: c.note.retry_media_task(c.task,BackgroundTasks(),c.owner,model_confirmation=None)
    assert error.value.status_code==409
    c.note._note_service.generate.assert_not_called()

def test_retry_keeps_ownership_independent_operation_and_frozen_models(retry_case):
    c=retry_case
    with pytest.raises(HTTPException) as error: c.note.retry_media_task(c.task,BackgroundTasks(),SimpleNamespace(user_id='other'),model_confirmation=None)
    assert error.value.status_code==404
    (c.folder/'new_generation.json').write_text('{}')
    with pytest.raises(HTTPException) as error: c.note.retry_media_task(c.task,BackgroundTasks(),c.owner,model_confirmation=None)
    assert error.value.status_code==409
    c.note.ensure_source.assert_not_called()

def test_failed_download_worker_releases_active_and_does_not_capture(retry_case):
    c=retry_case; tasks=BackgroundTasks(); c.note.retry_media_task(c.task,tasks,c.owner,model_confirmation=None)
    c.note._note_service.generate.side_effect=RuntimeError('synthetic download failure')
    work=tasks.tasks[0]; work.func(*work.args,**work.kwargs)
    assert c.task not in c.note._ACTIVE_FILE_TASKS
    assert all(not call.kwargs.get('allow_capture',False) for call in c.note.ensure_source.call_args_list)

def test_unavailable_frozen_source_never_queues_or_captures(retry_case):
    c=retry_case; tasks=BackgroundTasks()
    c.note.ensure_source.side_effect=HTTPException(409,'frozen source unavailable')
    with pytest.raises(HTTPException): c.note.retry_media_task(c.task,tasks,c.owner,model_confirmation=None)
    assert not tasks.tasks and c.task not in c.note._ACTIVE_FILE_TASKS
    assert c.artifacts.get_status(c.task)['status']=='failed'

@pytest.mark.parametrize('confirmation', [{}, {'source': 'local'}])
def test_url_retry_rejects_model_confirmation_without_mutation(retry_case, confirmation):
    c = retry_case
    tasks = BackgroundTasks()
    original = (c.folder / 'request.json').read_bytes()
    with pytest.raises(HTTPException) as error:
        c.note.retry_media_task(c.task, tasks, c.owner, model_confirmation=confirmation)
    assert error.value.status_code == 409
    c.note.ensure_source.assert_not_called()
    assert not tasks.tasks
    assert c.task not in c.note._ACTIVE_FILE_TASKS
    assert c.task not in c.note._URL_DOWNLOAD_RETRIES
    assert c.artifacts.get_status(c.task)['status'] == 'failed'
    assert (c.folder / 'request.json').read_bytes() == original
