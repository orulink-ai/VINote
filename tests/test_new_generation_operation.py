import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.config import settings
from app.db_models import SourceRequestDB
from app.services.source_request_service import SourceRequestService
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_generation_context import frozen_generation_context
from app.services.task_model_source import SNAPSHOT_FILE
from app.services.task_new_generation import NewGenerationService, NewGenerationConfirmation
from app.services.retained_task_source import assert_unreferenced
from app.services.task_original_service import TaskOriginalService
from app.services.vilab_cloud_service import VILabCloudService, _task_source


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'output_dir', tmp_path / 'output')
    monkeypatch.setattr(settings, 'vilab_server_url', 'https://original.invalid')
    engine = create_engine('sqlite:///' + str(tmp_path / 'receipt.db'), connect_args={'check_same_thread': False})
    SourceRequestDB.__table__.create(engine)
    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db
    receipts = SourceRequestService(sessions)
    service = NewGenerationService(receipts)
    artifacts = service.artifacts
    parent = str(uuid.uuid4()); folder = artifacts.create_task_dir(parent)
    (folder / 'recording_owner').write_text('alice')
    (folder / 'generation_client').write_text('desktop')
    artifacts.write_json(folder / 'request.json', {'request': {'workflow': 'meeting', 'title': '讨论',
        'style': 'meeting', 'diarize': False, 'model_profile_id': 'stale', 'model_name': 'wrong-default'}})
    media = folder / 'media'; media.mkdir(); original = media / 'source_video.webm'; original.write_bytes(b'original')
    artifacts.record_source_media(folder, original, media_kind='video')
    artifacts.update_status(folder, 'failed', 'unconfirmed', error_code='unknown_result', retryable=False)
    snapshot = {'version': 1, 'owner': 'alice', 'mode': 'cloud', 'server_url': settings.vilab_server_url,
                'asr_model': 'original-asr', 'llm_model': 'original-llm', 'needs_stt': True}
    artifacts.write_json(folder / SNAPSHOT_FILE, snapshot)
    from app.services import task_model_source
    monkeypatch.setattr(task_model_source, 'capture_source', Mock(side_effect=AssertionError('no defaults')))
    monkeypatch.setattr(VILabCloudService, 'status', Mock(side_effect=AssertionError('no preferences')))
    validations = []
    def validate(self, owner, *, needs_stt=True):
        captured_owner, captured = _task_source.get()
        assert owner == captured_owner == 'alice' and needs_stt
        assert captured == {**snapshot, 'configured': True}
        validations.append(captured.copy())
    monkeypatch.setattr(VILabCloudService, 'validate_ready', validate)
    # Any unexpected network access fails, even if a worker is accidentally real.
    monkeypatch.setattr(VILabCloudService, 'request', Mock(side_effect=AssertionError('no provider calls')))
    context = frozen_generation_context('alice', parent)
    confirmation = NewGenerationConfirmation(operation_id=uuid.uuid4(), confirmed=True,
        context_revision=context['context_revision'], source_version=context['source']['version'])
    dispatch = Mock()
    yield SimpleNamespace(**locals())
    engine.dispose()


def accept(c, body=None):
    background = BackgroundTasks()
    receipt = c.service.accept('alice', c.parent, body or c.confirmation, background, c.dispatch)
    return receipt, background


def test_distinct_durable_operation_inherits_models_no_copy_preserves_old(case):
    c = case
    old = {p.name: p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    receipt, background = accept(c)
    assert receipt.state == 'accepted' and receipt.task_id != c.parent
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert c.artifacts.resolve_source_media(child) == c.original
    assert not (child / 'media').exists()
    assert json.loads((child / SNAPSHOT_FILE).read_text()) == c.snapshot
    assert (child / 'generation_client').read_text() == 'desktop'
    c.service.run_once(receipt.task_id, 'alice', c.dispatch)
    assert c.dispatch.call_count == 1
    task, req, owner = c.dispatch.call_args.args
    assert task == receipt.task_id and owner == 'alice' and req.file_path == str(c.original)
    assert req.model_name is None and req.model_profile_id is None and req.api_key is None
    assert req.workflow == 'meeting' and len(c.validations) == 2
    assert old == {p.name: p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    assert len(background.tasks) == 1
    assert len(TaskOriginalService().list('alice')) == 1


def test_response_loss_restart_only_returns_original_receipt(case):
    c = case; receipt, _ = accept(c)
    c.service = NewGenerationService(SourceRequestService(c.sessions))
    c.original.unlink()  # Recovery lookup must survive later source removal.
    replay, background = accept(c)
    assert replay.task_id == receipt.task_id and replay.state == 'accepted'
    assert not background.tasks and not c.dispatch.called
    assert len(c.validations) == 1


def test_reserved_staging_failure_never_requeues_after_restart(case, monkeypatch):
    c = case
    write = c.artifacts.write_json
    def broken(path, value):
        if path.name == SNAPSHOT_FILE and path.parent != c.folder:
            raise OSError('disk full')
        write(path, value)
    monkeypatch.setattr(c.artifacts, 'write_json', broken)
    with pytest.raises(OSError): accept(c)
    receipt = c.receipts.get('alice', str(c.confirmation.operation_id))
    assert receipt.state == 'reserved'
    c.service = NewGenerationService(SourceRequestService(c.sessions))
    recovered, background = accept(c)
    assert recovered.task_id == receipt.task_id and not background.tasks


def test_operation_fingerprint_cannot_change_parent_or_context(case):
    c = case; receipt, _ = accept(c)
    changed = c.confirmation.model_copy(update={'context_revision': 'a' * 64})
    with pytest.raises(HTTPException) as error: accept(c, changed)
    assert error.value.status_code == 409
    assert c.receipts.get('alice', str(c.confirmation.operation_id)).task_id == receipt.task_id


@pytest.mark.parametrize('change', ['owner', 'origin', 'source', 'snapshot', 'active', 'raw_running', 'missing_snapshot', 'local'])
def test_stale_or_unverified_context_blocks_before_reserve(case, change):
    c = case
    if change == 'owner': (c.folder / 'recording_owner').write_text('bob')
    elif change == 'origin': c.monkeypatch.setattr(settings, 'vilab_server_url', 'https://other.invalid')
    elif change == 'source': c.original.write_bytes(b'changed!')  # same byte count
    elif change == 'snapshot': c.artifacts.write_json(c.folder / SNAPSHOT_FILE, {**c.snapshot, 'llm_model': 'other'})
    elif change == 'raw_running': c.artifacts.write_json(c.folder / 'status.json', {'status': 'transcribing', 'worker_id': 'old'})
    elif change == 'missing_snapshot': (c.folder / SNAPSHOT_FILE).unlink()
    elif change == 'local': c.artifacts.write_json(c.folder / SNAPSHOT_FILE, {**c.snapshot, 'mode': 'local'})
    background = BackgroundTasks()
    with pytest.raises(HTTPException):
        c.service.accept('alice', c.parent, c.confirmation, background, c.dispatch, active=change == 'active')
    with pytest.raises(HTTPException) as missing:
        c.receipts.get('alice', str(c.confirmation.operation_id))
    assert missing.value.status_code == 404 and not background.tasks


@pytest.mark.parametrize('status', [401, 403, 429, 503])
def test_model_permission_quota_unavailability_no_reserve_or_substitution(case, status):
    c = case
    c.monkeypatch.setattr(VILabCloudService, 'validate_ready', Mock(side_effect=HTTPException(status, 'unavailable')))
    with pytest.raises(HTTPException): accept(c)
    assert not c.dispatch.called
    with pytest.raises(HTTPException): c.receipts.get('alice', str(c.confirmation.operation_id))


@pytest.mark.parametrize('change', ['owner', 'source', 'origin', 'permission', 'cycle'])
def test_worker_revalidates_before_dispatch_and_never_reclaims(case, change):
    c = case; receipt, _ = accept(c); child = c.artifacts.find_task_dir(receipt.task_id)
    if change == 'owner': (child / 'recording_owner').write_text('bob')
    elif change == 'source': c.original.write_bytes(b'changed!')
    elif change == 'origin': c.monkeypatch.setattr(settings, 'vilab_server_url', 'https://changed.invalid')
    elif change == 'permission': c.monkeypatch.setattr(VILabCloudService, 'validate_ready', Mock(side_effect=HTTPException(403, 'denied')))
    else:
        link = json.loads((child / 'source_reference.json').read_text()); link['parent_task_id'] = receipt.task_id
        c.artifacts.write_json(child / 'source_reference.json', link)
    c.service.run_once(receipt.task_id, 'alice', c.dispatch)
    c.service.run_once(receipt.task_id, 'alice', c.dispatch)
    assert not c.dispatch.called
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'failed'
    assert c.artifacts.get_status(receipt.task_id)['retryable'] is False


def test_persisted_reference_blocks_deletion_after_restart_and_completion(case):
    c = case; receipt, _ = accept(c)
    c.artifacts.update_status(c.artifacts.find_task_dir(receipt.task_id), 'success', 'done')
    with pytest.raises(HTTPException) as error: assert_unreferenced(TaskArtifactService(), c.folder)
    assert error.value.status_code == 409 and c.original.exists()


def test_duplicate_worker_delivery_dispatches_once(case):
    c = case; receipt, _ = accept(c)
    c.service.run_once(receipt.task_id, 'alice', c.dispatch)
    NewGenerationService(SourceRequestService(c.sessions)).run_once(receipt.task_id, 'alice', c.dispatch)
    assert c.dispatch.call_count == 1


def test_concurrent_same_operation_has_exactly_one_queue_winner(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    c = case; barrier = Barrier(2)
    def confirm(_):
        service = NewGenerationService(SourceRequestService(c.sessions))
        background = BackgroundTasks()
        barrier.wait()
        result = service.accept('alice', c.parent, c.confirmation, background, c.dispatch)
        return result, len(background.tasks)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, range(2)))
    assert len({result.task_id for result, _ in results}) == 1
    assert sum(count for _, count in results) == 1
    assert not c.dispatch.called


def test_queue_failure_after_acceptance_remains_query_only(case):
    c = case
    background = Mock(add_task=Mock(side_effect=OSError('queue unavailable')))
    with pytest.raises(OSError):
        c.service.accept('alice', c.parent, c.confirmation, background, c.dispatch)
    receipt = c.receipts.get('alice', str(c.confirmation.operation_id))
    assert receipt.state == 'accepted'
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'failed'
    _, recovered_queue = accept(c)
    assert not recovered_queue.tasks and not c.dispatch.called


def test_foreign_worker_interruption_is_unknown_and_old_retry_is_blocked(case):
    from app.routers import note
    c = case; receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    c.artifacts.write_json(child / 'status.json', {'status': 'transcribing', 'worker_id': 'gone'})
    status = c.artifacts.get_status(receipt.task_id)
    assert status['retryable'] is False and status['error_code'] == 'unknown_result'
    c.monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=c.artifacts))
    with pytest.raises(HTTPException) as error:
        note.retry_media_task(receipt.task_id, BackgroundTasks(), SimpleNamespace(user_id='alice'))
    assert error.value.detail['code'] == 'independent_operation_query_only'
    assert not c.dispatch.called


def test_saved_child_deduplicates_canonical_original_in_library(case):
    from datetime import datetime
    from app.services import local_file_service
    c = case; receipt, _ = accept(c)
    saved = SimpleNamespace(task_id=receipt.task_id, id='child-note', source_type='meeting_video',
                            title='新纪要', created_at=datetime.now())
    class Database:
        calls = 0
        def scalars(self, statement):
            self.calls += 1
            return [] if self.calls == 1 else [saved]
    @contextmanager
    def sessions(): yield Database()
    c.monkeypatch.setattr(local_file_service, 'session_scope', sessions)
    items = local_file_service.LocalFileService().list('alice')['items']
    assert len(items) == 1 and items[0]['task_id'] == c.parent
    assert items[0]['note_id'] == saved.id


def test_old_operation_receipt_and_unknown_partial_not_reused(case):
    from app.models.source_request import SourceInput, SourceSubmission
    c = case
    old = c.receipts.reserve('alice', 'old-operation', SourceSubmission(source=SourceInput(kind='url', url='https://source.invalid')))
    c.receipts.accept('alice', old.operation_id, old.task_id, status='failed', source_type='video')
    before = c.receipts.get('alice', old.operation_id).model_dump()
    c.artifacts.write_json(c.folder / 'transcript.json', {'full_text': 'not-final', 'partial': True})
    c.artifacts.write_json(c.folder / 'result.json', {'markdown': 'must not copy'})
    # These artifacts are excluded from the source/model context on purpose.
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert not (child / 'transcript.json').exists() and not (child / 'result.json').exists()
    assert c.receipts.get('alice', old.operation_id).model_dump() == before


def test_real_pipeline_entry_uses_child_frozen_models_without_media_copy(case):
    from app.routers import note
    from app.services.note_service import NoteService
    import shutil
    c = case
    pipeline = NoteService()
    c.monkeypatch.setattr(note, '_note_service', pipeline)
    c.monkeypatch.setattr(pipeline.transcription_service, 'get_audio_duration', lambda _: 28.0)
    def complete(**kwargs):
        assert kwargs['audio_meta'].file_path == str(c.original)
        assert _task_source.get()[1]['asr_model'] == 'original-asr'
        assert _task_source.get()[1]['llm_model'] == 'original-llm'
        folder = kwargs['task_dir']
        assert pipeline.artifact_service.resolve_source_media(folder) == c.original
        pipeline.artifact_service.update_status(folder, 'success', 'offline fixture complete')
        return SimpleNamespace(markdown='offline test')
    c.monkeypatch.setattr(pipeline, '_run_pipeline', complete)
    c.monkeypatch.setattr(shutil, 'copy2', Mock(side_effect=AssertionError('must not copy original')))
    receipt, _ = accept(c)
    c.service.run_once(receipt.task_id, 'alice', note._run_task_from_file)
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'success'
    assert c.artifacts.get_status(c.parent)['error_code'] == 'unknown_result'


def test_http_confirmation_exact_get_recovery_auth_and_extra_fields(case):
    from app.routers import note
    c = case; c.monkeypatch.setattr(note, '_source_requests', c.receipts)
    c.monkeypatch.setattr(note, '_run_task_from_file', c.dispatch)
    c.monkeypatch.setattr(note, '_ACTIVE_FILE_TASKS', set())
    app = FastAPI(); app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='alice')
    client = TestClient(app)
    url = '/api/task/' + c.parent + '/new-generation'
    body = c.confirmation.model_dump(mode='json')
    assert client.post(url, json={**body, 'model_name': 'default'}).status_code == 422
    assert client.post(url, json={**body, 'confirmed': False}).status_code == 422
    response = client.post(url, json=body)
    assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
    assert c.dispatch.call_count == 1
    result = client.get('/api/source-requests/' + body['operation_id'])
    assert result.status_code == 200 and result.json()['task_id'] == response.json()['task_id']
    assert client.post(url, json=body).json()['task_id'] == response.json()['task_id']
    assert c.dispatch.call_count == 1
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='bob')
    assert client.post(url, json=body).status_code == 404
    assert client.get('/api/source-requests/' + body['operation_id']).status_code == 404
