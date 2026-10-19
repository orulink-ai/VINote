from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import note
from app.services.asr_stream_service import ASRServiceError
from app.services.task_failure import failure_details, recovery_status, UNKNOWN_MESSAGE
from app.services.task_artifact_service import TaskArtifactService
from app.transcribers.vilab_transcriber import VILabTranscriber

@pytest.mark.parametrize('code,sent_all', [('unknown_result', False), ('asr_timeout', True), ('unknown_error', False), ('asr_incomplete_result', False), ('asr_empty_result', False), ('empty_result_unverified', True)])
def test_typed_unsafe_failure_cannot_auto_retry(code, sent_all, tmp_path):
    service = VILabTranscriber('https://example.invalid', 'not-a-real-key', model='frozen-selected-model')
    error = ASRServiceError(code, sent_all=sent_all)
    with patch('app.transcribers.vilab_transcriber.subprocess.run'), patch.object(service, '_transcribe_normalized', side_effect=error) as run, patch('app.transcribers.vilab_transcriber.time.sleep') as sleep:
        with pytest.raises(ASRServiceError):
            service.transcribe(str(tmp_path / 'fake.wav'))
    assert run.call_count == 1 and service.model == 'frozen-selected-model'
    sleep.assert_not_called()
    assert failure_details(error)['retryable'] is False


def test_declared_transient_before_send_complete_still_retryable():
    error = ASRServiceError('service_unavailable', sent_all=False)
    assert failure_details(error) == {'error_code': 'service_unavailable', 'retryable': True}


def test_outer_failure_cannot_launder_typed_failure(tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('task')
    artifacts.update_status(folder, 'transcribing')
    artifacts.update_status(folder, 'failed', str(ASRServiceError('unknown_result')), **failure_details(ASRServiceError('unknown_result')))
    artifacts.update_status(folder, 'failed', 'outer generic failure', retryable=True)
    artifacts.update_status(folder, 'transcribing', speaker_analysis_ready=True)
    result = artifacts.get_status('task')
    assert result['status'] == 'failed' and result['error_code'] == 'unknown_result'
    assert result['retryable'] is False

@pytest.mark.parametrize('typed', [True, False])
def test_retry_route_unknown_result_no_dispatch_even_with_legacy_true(tmp_path, typed):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('same-task')
    (folder / 'recording_owner').write_text('owner')
    artifacts.write_json(folder / 'status.json', {'status': 'failed', 'retryable': True, 'message': UNKNOWN_MESSAGE, **({'error_code': 'unknown_result'} if typed else {})})
    app = FastAPI(); app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='owner')
    with patch.object(note, '_note_service', SimpleNamespace(artifact_service=artifacts)), patch.object(note, '_run_task_from_file') as run:
        response = TestClient(app).post('/api/task/same-task/retry')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'unknown_result'
    run.assert_not_called()
    assert artifacts.get_status('same-task')['status'] == 'failed'


def test_get_route_exposes_safe_typed_unknown_without_raw_provider_text(tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('same-task')
    (folder / 'recording_owner').write_text('owner')
    app = FastAPI(); app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id='owner')
    fake = SimpleNamespace(artifact_service=artifacts, get_status=lambda _: {'status':'failed', 'retryable':True, 'error_code':'unknown_result', 'message':'provider secret text'})
    with patch.object(note, '_note_service', fake):
        response = TestClient(app).get('/api/task/same-task')
    body = response.json()
    assert body['error_code'] == 'unknown_result' and body['retryable'] is False
    assert 'provider secret' not in body['message']


@pytest.mark.parametrize('code', ['asr_empty_result', 'empty_result_unverified'])
@pytest.mark.parametrize('sent_all', [False, True])
def test_empty_terminal_keeps_protocol_code_without_retry_or_silence_inference(code, sent_all):
    error = ASRServiceError(code, sent_all=sent_all)
    assert error.code == code
    assert error.retry_reason is None
    details = failure_details(error)
    assert details == {'error_code': code, 'retryable': False}
    result = recovery_status({'status': 'failed', 'failed_stage': 'transcribing', 'message': 'untrusted provider text', **details})
    assert result['error_code'] == code and result['retryable'] is False
    assert result['failed_stage'] == 'transcribing'
    assert '空结果' in result['message'] and '尚未确认' in result['message']
    assert '不要重复提交' in result['message']
    assert 'untrusted provider text' not in result['message']


@pytest.mark.parametrize('code', ['asr_empty_result', 'empty_result_unverified'])
def test_empty_terminal_status_and_retry_route_preserve_failure_without_dispatch(code, tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('empty-task')
    (folder / 'recording_owner').write_text('owner')
    artifacts.write_json(folder / 'status.json', {
        'status': 'failed', 'failed_stage': 'transcribing', 'error_code': code,
        'retryable': True, 'message': 'untrusted provider text',
    })
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='owner')
    app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id='owner')
    fake = SimpleNamespace(artifact_service=artifacts, get_status=artifacts.get_status)
    with patch.object(note, '_note_service', fake), patch.object(note, '_run_task_from_file') as run:
        client = TestClient(app)
        status = client.get('/api/task/empty-task').json()
        retry = client.post('/api/task/empty-task/retry')
    assert status['status'] == 'failed' and status['failed_stage'] == 'transcribing'
    assert status['error_code'] == code and status['retryable'] is False
    assert '空结果' in status['message'] and 'untrusted provider text' not in status['message']
    assert retry.status_code == 409 and retry.json()['detail']['code'] == code
    run.assert_not_called()
