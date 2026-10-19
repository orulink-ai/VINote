"""Offline status/recovery contracts for ambiguous summary outcomes."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers import note
from app.services.summary_failure import (
    SUMMARY_UNCONFIRMED_CODE, SUMMARY_UNCONFIRMED_COPY, SummaryResultUnconfirmed,
)
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_failure import failure_details, recovery_status


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('No provider calls are allowed')
    # TestClient's Windows event loop needs a loopback socketpair; forbid the
    # actual HTTP transport instead (TestClient uses its in-memory transport).
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', denied)


def test_projection_requires_type_and_cannot_leak_exception_metadata():
    error = SummaryResultUnconfirmed()
    error.asr_metadata = {'secret': 'SYNTHETIC_SECRET'}
    error.cloud_failure_context = {'message': 'SYNTHETIC_SECRET'}
    error.error_code = 'untrusted-arbitrary-code'
    assert failure_details(error) == {'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': False}
    fake = HTTPException(502, 'SYNTHETIC_SECRET')
    fake.error_code = SUMMARY_UNCONFIRMED_CODE
    fake.retryable = False
    assert failure_details(fake) == {}


@pytest.mark.parametrize('retryable', [True, False, None])
def test_summary_status_is_safe_read_projection_without_mutating_input(retryable):
    raw = {'status': 'failed', 'error_code': SUMMARY_UNCONFIRMED_CODE,
           'retryable': retryable, 'failed_stage': 'summarizing', 'message': 'SYNTHETIC_SECRET'}
    before = dict(raw)
    projected = recovery_status(raw)
    assert projected['retryable'] is False
    assert projected['message'] == SUMMARY_UNCONFIRMED_COPY
    assert projected['failed_stage'] == 'summarizing' and raw == before
    assert 'asr_failure_context' not in projected and '转写' not in projected['message']


@pytest.mark.parametrize('legacy_retryable', [True, False])
def test_public_status_and_old_retry_cannot_replay_typed_summary_failure(
        legacy_retryable, tmp_path, monkeypatch):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('summary-task')
    (folder / 'recording_owner').write_text('owner', encoding='utf-8')
    artifacts.write_json(folder / 'status.json', {
        'status': 'failed', 'error_code': SUMMARY_UNCONFIRMED_CODE,
        'retryable': legacy_retryable, 'message': 'SYNTHETIC_SECRET',
        'failed_stage': 'summarizing', 'processed_seconds': 100, 'total_seconds': 100,
    })
    before = (folder / 'status.json').read_bytes()
    fake = SimpleNamespace(artifact_service=artifacts, get_status=artifacts.get_status)
    monkeypatch.setattr(note, '_note_service', fake)
    monkeypatch.setattr(note, '_ACTIVE_FILE_TASKS', set())
    run_media, run_document, model_check = Mock(), Mock(), Mock()
    monkeypatch.setattr(note, '_run_task_from_file', run_media)
    monkeypatch.setattr(note, '_run_source_job', run_document)
    monkeypatch.setattr(note, 'ensure_source', model_check)
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    user = lambda: SimpleNamespace(user_id='owner')
    app.dependency_overrides[note.get_current_user] = user
    app.dependency_overrides[note.get_optional_current_user] = user
    with TestClient(app) as client:
        status = client.get('/api/task/summary-task')
        response = client.post('/api/task/summary-task/retry')
    assert status.status_code == 200 and status.json()['retryable'] is False
    assert status.json()['error_code'] == SUMMARY_UNCONFIRMED_CODE
    assert status.json()['failed_stage'] == 'summarizing'
    assert 'SYNTHETIC_SECRET' not in json.dumps(status.json())
    assert response.status_code == 409
    assert response.json()['detail']['code'] == SUMMARY_UNCONFIRMED_CODE
    run_media.assert_not_called()
    run_document.assert_not_called()
    model_check.assert_not_called()
    assert (folder / 'status.json').read_bytes() == before


@pytest.mark.parametrize('job_kind', ['media', 'document'])
def test_legacy_summary_failure_true_without_code_never_queues_old_job(
        job_kind, tmp_path, monkeypatch):
    from fastapi import BackgroundTasks
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('legacy-summary')
    (folder / 'recording_owner').write_text('owner', encoding='utf-8')
    artifacts.write_json(folder / 'status.json', {
        'status': 'failed', 'failed_stage': 'summarizing', 'retryable': True,
        'message': 'old summary error without a typed code',
    })
    if job_kind == 'document':
        artifacts.write_json(folder / 'source_job.json', {'options': {}})
    before = (folder / 'status.json').read_bytes()
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    monkeypatch.setattr(note, '_ACTIVE_FILE_TASKS', set())
    model_check = Mock(side_effect=AssertionError('No model validation/submission'))
    monkeypatch.setattr(note, 'ensure_source', model_check)
    background = BackgroundTasks()
    with pytest.raises(HTTPException) as caught:
        note.retry_media_task('legacy-summary', background,
                              SimpleNamespace(user_id='owner'), model_confirmation=None)
    assert caught.value.status_code == 409
    assert caught.value.detail['code'] == 'summary_retry_requires_confirmation'
    assert background.tasks == []
    model_check.assert_not_called()
    assert (folder / 'status.json').read_bytes() == before


def test_safe_pre_asr_failure_still_queues_existing_recovery(tmp_path, monkeypatch):
    from fastapi import BackgroundTasks
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('safe-before-asr')
    (folder / 'recording_owner').write_text('owner', encoding='utf-8')
    artifacts.write_json(folder / 'status.json', {
        'status': 'failed', 'failed_stage': 'preparing', 'retryable': True,
        'message': 'source preparation failed before ASR',
    })
    source = folder / 'synthetic.wav'
    source.write_bytes(b'synthetic-media-not-decoded')
    monkeypatch.setattr(artifacts, 'resolve_source_media', lambda path: source)
    artifacts.write_json(folder / 'request.json', {'request': {'file_path': str(source)}})
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    monkeypatch.setattr(note, '_ACTIVE_FILE_TASKS', set())
    model_check = Mock()
    monkeypatch.setattr(note, 'ensure_source', model_check)
    background = BackgroundTasks()
    response = note.retry_media_task('safe-before-asr', background,
                                    SimpleNamespace(user_id='owner'), model_confirmation=None)
    assert response == {'task_id': 'safe-before-asr', 'status': 'uploaded'}
    assert len(background.tasks) == 1  # Queue inspection only; no task is executed.
    assert background.tasks[0].func is note._run_task_from_file
    model_check.assert_called_once()
