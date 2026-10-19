"""Offline summary-only contracts; fixture text is not provider acceptance."""
import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db_models import SourceRequestDB
from app.services.source_request_service import SourceRequestService
from app.services.task_model_source import SNAPSHOT_FILE
from app.services.vilab_cloud_service import VILabCloudService, _task_source


@pytest.fixture
def case(tmp_path, monkeypatch):
    from app.services.meeting_summary_regeneration import SummaryRegenerationService, SummaryConfirmation
    monkeypatch.setattr(settings, 'output_dir', tmp_path / 'output')
    monkeypatch.setattr(settings, 'vilab_server_url', 'https://summary.invalid')
    engine = create_engine('sqlite:///' + str(tmp_path / 'receipts.db'), connect_args={'check_same_thread': False})
    SourceRequestDB.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    receipts = SourceRequestService(sessions)
    service = SummaryRegenerationService(receipts)
    artifacts = service.artifacts
    parent = str(uuid4())
    folder = artifacts.create_task_dir(parent)
    artifacts.write_text(folder / '.task_id', parent)
    artifacts.write_text(folder / 'recording_owner', 'alice')
    artifacts.write_text(folder / 'generation_client', 'desktop')
    artifacts.write_json(folder / 'request.json', {'request': {
        'workflow': 'meeting', 'title': 'Fixture meeting', 'style': 'meeting',
        'model_name': 'old-model', 'model_profile_id': 'old-profile'}})
    media = folder / 'media'
    media.mkdir()
    original = media / 'source_audio.wav'
    original.write_bytes(b'offline original identity only')
    artifacts.record_source_media(folder, original, media_kind='audio')
    artifacts.update_status(folder, 'failed', 'summary failed', retryable=False)
    snapshot = {'version': 1, 'owner': 'alice', 'mode': 'cloud',
                'server_url': settings.vilab_server_url, 'asr_model': 'old-asr',
                'llm_model': 'old-model', 'needs_stt': True}
    artifacts.write_json(folder / SNAPSHOT_FILE, snapshot)
    transcript = {'language': 'zh', 'full_text': 'Offline test transcript.',
                  'segments': [{'start': 0, 'end': 10, 'text': 'Offline test transcript.'}],
                  'metadata': {}}
    artifacts.write_json(folder / 'transcript.json', transcript)
    artifacts.write_json(folder / 'result.json', {'markdown': 'old result'})
    note = SimpleNamespace(generate_from_transcript=Mock(),
                           generate_from_file=Mock(side_effect=AssertionError('NEVER ASR')))
    monkeypatch.setattr(VILabCloudService, 'request', Mock(side_effect=AssertionError('no network')))
    def status(self, owner):
        frozen = _task_source.get()
        return dict(frozen[1]) if frozen and frozen[0] == owner else {'mode': 'cloud'}
    monkeypatch.setattr(VILabCloudService, 'status', status)
    monkeypatch.setattr(VILabCloudService, 'models', lambda self, owner: [
        {'id': 'chosen-catalog-id', 'modelType': 'llm', 'runtimeStatus': 'available'}])
    context = service.context('alice', parent)
    body = SummaryConfirmation(operation_id=uuid4(), confirmed=True,
        context_revision=context['context_revision'], source_version=context['source']['version'],
        model_name='chosen-catalog-id')
    yield SimpleNamespace(**locals())
    engine.dispose()


def accept(c, body=None):
    background = BackgroundTasks()
    receipt = c.service.accept('alice', c.parent, body or c.body, background, c.note)
    return receipt, background


@pytest.mark.parametrize('status', ['failed', 'success'])
@pytest.mark.parametrize('evidence', ['transcript.json', 'asr_evidence.json'])
def test_complete_saved_evidence_new_child_explicit_model_no_copy(case, status, evidence):
    c = case
    c.artifacts.update_status(c.folder, status, 'fixture status')
    if evidence == 'asr_evidence.json':
        (c.folder / 'transcript.json').rename(c.folder / evidence)
    c.artifacts.write_json(c.folder / 'speaker_evidence.json', {
        'timeline': 'recording_offset_seconds', 'duration': 10,
        'turns': [{'start': 0, 'end': 10, 'speaker_id': 'speaker_0'}]})
    context = c.service.context('alice', c.parent)
    body = c.body.model_copy(update={'context_revision': context['context_revision']})
    before = {p.name: p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    receipt, tasks = accept(c, body)
    assert receipt.task_id != c.parent and receipt.state == 'accepted' and len(tasks.tasks) == 1
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert c.artifacts.resolve_source_media(child) == c.original and not (child / 'media').exists()
    assert json.loads((child / 'request.json').read_text())['request']['workflow'] == 'meeting'
    assert json.loads((child / SNAPSHOT_FILE).read_text())['llm_model'] == 'chosen-catalog-id'
    assert json.loads((child / SNAPSHOT_FILE).read_text())['needs_stt'] is False
    c.service.run_once(receipt.task_id, 'alice', c.note)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    call = c.note.generate_from_transcript.call_args.kwargs
    assert c.note.generate_from_transcript.call_count == 1
    assert call['task_id'] == receipt.task_id and call['user_id'] == 'alice'
    assert call['transcript'].full_text == c.transcript['full_text']
    assert call['transcript'].metadata['speaker_evidence'][0]['speaker_id'] == 'speaker_0'
    assert before == {p.name: p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    assert not c.note.generate_from_file.called


@pytest.mark.parametrize('change', ['owner', 'missing_source', 'source', 'transcript', 'speaker',
                                    'partial', 'empty', 'missing_text', 'missing_snapshot', 'active'])
def test_invalid_or_changed_context_never_reserves(case, change):
    c = case
    if change == 'owner': (c.folder / 'recording_owner').write_text('bob')
    elif change == 'missing_source': c.original.unlink()
    elif change == 'source': c.original.write_bytes(b'changed original')
    elif change == 'missing_text': (c.folder / 'transcript.json').unlink()
    elif change == 'missing_snapshot': (c.folder / SNAPSHOT_FILE).unlink()
    elif change == 'active': c.artifacts.write_json(c.folder / 'status.json', {'status': 'transcribing'})
    elif change == 'speaker': c.artifacts.write_json(c.folder / 'speaker_evidence.json', {'turns': []})
    else:
        value = {**c.transcript, 'full_text': 'changed'}
        if change == 'partial': value['metadata'] = {'partial': True}
        if change == 'empty': value['full_text'] = ''
        c.artifacts.write_json(c.folder / 'transcript.json', value)
    with pytest.raises(HTTPException): accept(c)
    with pytest.raises(HTTPException): c.receipts.get('alice', str(c.body.operation_id))
    assert not c.note.generate_from_transcript.called


def test_duplicate_and_reserved_unknown_are_query_only(case, monkeypatch):
    c = case
    receipt, _ = accept(c)
    c.original.unlink()
    again, tasks = accept(c)
    assert again.task_id == receipt.task_id and not tasks.tasks
    changed = c.body.model_copy(update={'model_name': 'another-model'})
    with pytest.raises(HTTPException): accept(c, changed)
    assert not c.note.generate_from_transcript.called


def test_staging_failure_reserved_receipt_never_queues(case, monkeypatch):
    c = case
    monkeypatch.setattr(c.artifacts, 'save_transcript', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError): accept(c)
    assert c.receipts.get('alice', str(c.body.operation_id)).state == 'reserved'
    _, tasks = accept(c)
    assert not tasks.tasks and not c.note.generate_from_transcript.called


@pytest.mark.parametrize('change', ['model', 'origin', 'local', 'denied'])
def test_catalog_and_current_mode_fail_closed_before_reserve(case, monkeypatch, change):
    c = case
    if change == 'origin': monkeypatch.setattr(settings, 'vilab_server_url', 'https://changed.invalid')
    elif change == 'local': monkeypatch.setattr(VILabCloudService, 'status', lambda self, owner: {'mode': 'local'})
    elif change == 'denied': monkeypatch.setattr(VILabCloudService, 'models', Mock(side_effect=HTTPException(403, 'denied')))
    else: monkeypatch.setattr(VILabCloudService, 'models', lambda self, owner: [])
    with pytest.raises(HTTPException): accept(c)
    with pytest.raises(HTTPException): c.receipts.get('alice', str(c.body.operation_id))


@pytest.mark.parametrize('change', ['owner', 'source', 'transcript', 'receipt', 'snapshot', 'request'])
def test_worker_rechecks_db_and_evidence_before_dispatch(case, change):
    c = case
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    if change == 'owner': (child / 'recording_owner').write_text('bob')
    elif change == 'source': c.original.unlink()
    elif change == 'transcript': c.artifacts.write_json(c.folder / 'transcript.json', {**c.transcript, 'full_text': 'changed'})
    elif change == 'snapshot': c.artifacts.write_json(child / SNAPSHOT_FILE, {**c.snapshot, 'llm_model': 'wrong'})
    elif change == 'request': c.artifacts.write_json(child / 'request.json', {'request': {'workflow': 'note_organization'}})
    else:
        with c.sessions() as db: db.get(SourceRequestDB, ('alice', str(c.body.operation_id))).fingerprint = '0' * 64
    c.service.run_once(receipt.task_id, 'alice', c.note)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert not c.note.generate_from_transcript.called
    assert c.artifacts.get_status(receipt.task_id)['retryable'] is False


def test_http_auth_confirmation_and_receipt_isolation(case):
    from app.routers.meeting_summary_regeneration import create_summary_regeneration_router
    c = case
    def principal(): raise HTTPException(401, 'login required')
    app = FastAPI()
    app.include_router(create_summary_regeneration_router(c.service, principal, c.note), prefix='/api')
    client = TestClient(app)
    path = '/api/task/' + c.parent
    assert client.get(path + '/summary-context').status_code == 401
    app.dependency_overrides[principal] = lambda: SimpleNamespace(user_id='bob')
    assert client.get(path + '/summary-context').status_code == 404
    assert client.post(path + '/regenerate-summary', json=c.body.model_dump(mode='json')).status_code == 404
    app.dependency_overrides[principal] = lambda: SimpleNamespace(user_id='alice')
    response = client.get(path + '/summary-context')
    assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
    body = c.body.model_dump(mode='json')
    for invalid in ({**body, 'confirmed': 1}, {**body, 'confirmed': False},
                    {**body, 'file_path': '/untrusted'}, {**body, 'model_name': ''}):
        assert client.post(path + '/regenerate-summary', json=invalid).status_code == 422
    response = client.post(path + '/regenerate-summary', json=body)
    assert response.status_code == 200
    assert client.post(path + '/regenerate-summary', json=body).json()['task_id'] == response.json()['task_id']
    assert c.note.generate_from_transcript.call_count == 1
    assert c.receipts.get('alice', body['operation_id']).task_id == response.json()['task_id']
    with pytest.raises(HTTPException): c.receipts.get('bob', body['operation_id'])


def test_get_context_never_reads_cloud_catalog_or_preferences(case, monkeypatch):
    c = case
    monkeypatch.setattr(VILabCloudService, 'models', Mock(side_effect=AssertionError('GET is offline')))
    monkeypatch.setattr(VILabCloudService, 'status', Mock(side_effect=AssertionError('GET is offline')))
    assert c.service.context('alice', c.parent)['transcript_version'] == c.context['transcript_version']


def test_concurrent_confirmation_and_worker_delivery_only_one_winner(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    c = case
    barrier = Barrier(2)
    def submit(_):
        barrier.wait()
        return accept(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert len({r.task_id for r, _ in results}) == 1
    assert sum(len(b.tasks) for _, b in results) == 1
    receipt = results[0][0]
    def execute(_): c.service.run_once(receipt.task_id, 'alice', c.note)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, range(2)))
    assert c.note.generate_from_transcript.call_count == 1


def test_arbitrary_task_disk_metadata_and_reserved_receipt_do_not_authorize_worker(case):
    c = case
    receipt, _ = accept(c)
    with c.sessions() as db:
        db.get(SourceRequestDB, ('alice', str(c.body.operation_id))).state = 'reserved'
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert not c.note.generate_from_transcript.called
    forged = str(uuid4())
    folder = c.artifacts.create_task_dir(forged)
    c.artifacts.write_json(folder / 'new_generation.json', {
        'contract': 'meeting-summary-only-v1', 'parent_task_id': c.parent,
        **c.body.model_dump(mode='json')})
    c.service.run_once(forged, 'alice', c.note)
    c.service.run_once('../outside', 'alice', c.note)
    assert not c.note.generate_from_transcript.called


def test_frozen_choice_survives_changed_preferences_and_uses_no_asr(case, monkeypatch):
    c = case
    receipt, _ = accept(c)
    def summarize(**kwargs):
        owner, snapshot = _task_source.get()
        assert owner == 'alice' and snapshot['llm_model'] == c.body.model_name
        assert snapshot['needs_stt'] is False and snapshot['asr_model'] == ''
    c.note.generate_from_transcript.side_effect = summarize
    monkeypatch.setattr(VILabCloudService, 'status', Mock(side_effect=AssertionError('no new preferences')))
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1


def test_dispatch_failure_and_interruption_remain_unknown_and_query_only(case):
    c = case
    receipt, _ = accept(c)
    c.note.generate_from_transcript.side_effect = RuntimeError('provider result unknown')
    c.service.run_once(receipt.task_id, 'alice', c.note)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    status = c.artifacts.get_status(receipt.task_id)
    assert status['status'] == 'failed' and status['retryable'] is False
    assert '本次总结结果尚未确认' in status['message'] and not status.get('error_code')
    assert not accept(c)[1].tasks and c.note.generate_from_transcript.call_count == 1
    folder = c.artifacts.find_task_dir(receipt.task_id)
    c.artifacts.write_json(folder / 'status.json', {'status': 'summarizing', 'worker_id': 'gone'})
    assert c.artifacts.get_status(receipt.task_id)['error_code'] == 'unknown_result'


def test_source_reference_protects_canonical_original(case):
    from app.services.retained_task_source import assert_unreferenced
    c = case
    accept(c)
    with pytest.raises(HTTPException) as error: assert_unreferenced(c.artifacts, c.folder)
    assert error.value.status_code == 409


@pytest.mark.parametrize('evidence', ['transcript.json', 'asr_evidence.json'])
def test_large_final_transcript_not_rejected_by_metadata_size_limit(case, evidence):
    c = case
    (c.folder / 'transcript.json').unlink()
    text = 'offline fixture ' * 9000
    value = {**c.transcript, 'full_text': text,
             'segments': [{'start': 0, 'end': 10, 'text': text}]}
    c.artifacts.write_json(c.folder / evidence, value)
    assert c.service.context('alice', c.parent)['can_regenerate_summary'] is True


def test_conflicting_independent_asr_evidence_is_not_silently_substituted(case):
    c = case
    c.artifacts.write_json(c.folder / 'asr_evidence.json', {
        **c.transcript, 'full_text': 'Different source evidence.'})
    with pytest.raises(HTTPException): c.service.context('alice', c.parent)


def test_staging_marks_query_only_before_request_or_media_reference(case, monkeypatch):
    c = case
    write = c.artifacts.write_json
    def stage(path, value):
        if path.parent != c.folder and path.name in {'request.json', 'source_reference.json'}:
            assert (path.parent / 'new_generation.json').is_file()
        write(path, value)
    monkeypatch.setattr(c.artifacts, 'write_json', stage)
    accept(c)


def test_summary_child_can_regenerate_its_own_evidence_with_canonical_playback(case):
    c = case
    first, _ = accept(c)
    child = c.artifacts.find_task_dir(first.task_id)
    c.artifacts.update_status(child, 'success', 'offline fixture terminal')
    c.artifacts.write_json(child / 'transcript.json', {**c.transcript,
        'metadata': {'evidence_revision': 'child-specific'}})
    context = c.service.context('alice', first.task_id)
    assert context['parent_task_id'] == first.task_id
    assert context['canonical_task_id'] == c.parent
    assert context['source']['file_id'] == 'task:' + c.parent
    assert context['transcript_version'] != c.context['transcript_version']
    body = c.body.model_copy(update={'operation_id': uuid4(), 'context_revision': context['context_revision']})
    result = c.service.accept('alice', first.task_id, body, BackgroundTasks(), c.note)
    grandchild = c.artifacts.find_task_dir(result.task_id)
    assert json.loads((grandchild / 'source_reference.json').read_text())['parent_task_id'] == c.parent
    assert c.artifacts.resolve_source_media(grandchild) == c.original
    c.service.run_once(result.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_args.kwargs['transcript'].metadata['evidence_revision'] == 'child-specific'


@pytest.mark.parametrize('change', ['owner', 'mapping', 'chain', 'version'])
def test_child_context_rejects_unverified_reference(case, change):
    c = case
    first, _ = accept(c)
    child = c.artifacts.find_task_dir(first.task_id)
    c.artifacts.update_status(child, 'success', 'offline fixture terminal')
    if change == 'owner': (child / 'recording_owner').write_text('bob')
    elif change == 'mapping': (child / '.task_id').write_text(str(uuid4()))
    else:
        reference = json.loads((child / 'source_reference.json').read_text())
        if change == 'chain': reference['parent_task_id'] = first.task_id
        else: reference['source_version'] = '0' * 64
        c.artifacts.write_json(child / 'source_reference.json', reference)
    with pytest.raises(HTTPException): c.service.context('alice', first.task_id)


def test_pipeline_persisted_failure_stage_and_code_are_preserved(case):
    c = case
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    saved = []
    def failure(**kwargs):
        c.artifacts.update_status(child, 'failed', 'Upstream permission rejected.',
            stage='summarizing', failed_stage='summarizing', error_code='provider_permission', retryable=False)
        status = json.loads((child / 'status.json').read_text())
        c.artifacts.write_json(child / 'status.json', {**status, 'error_code': 'provider_permission'})
        saved.append((child / 'status.json').read_bytes())
        raise RuntimeError('DO NOT PUBLISH credentials or exception contents')
    c.note.generate_from_transcript.side_effect = failure
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert (child / 'status.json').read_bytes() == saved[0]


@pytest.mark.parametrize('only_asr_file', [False, True])
@pytest.mark.parametrize('granularity', ['session', 'segment'])
def test_nested_asr_fixture_uses_original_27_windows_without_another_wrapper(case, only_asr_file, granularity):
    from app.services.meeting_summary_regeneration import _evidence
    c = case
    utterances = [f'原始发言{i:02d}的完整内容。' for i in range(27)]
    full_text = ''.join(utterances)
    raw = {'language': 'zh', 'full_text': full_text,
           'segments': [{'start': i * 10, 'end': (i + 1) * 10, 'text': text,
                         'timestamp_estimated': i == 0} for i, text in enumerate(utterances)],
           'metadata': {'timestamp_granularity': granularity}}
    # Historical asr_evidence.json may itself be the estimated outer transcript.
    outer = {'language': 'zh', 'full_text': full_text,
        'segments': [{'start': i * 270 / 126, 'end': (i + 1) * 270 / 126,
                      'text': full_text[i * len(full_text) // 126:(i + 1) * len(full_text) // 126],
                      'speaker_id': 'speaker_0', 'timestamp_estimated': True} for i in range(126)],
        'metadata': {'asr_evidence': raw, 'speaker_alignment_estimated': True}}
    c.artifacts.write_json(c.folder / 'transcript.json', outer)
    c.artifacts.write_json(c.folder / 'asr_evidence.json', outer)
    c.artifacts.write_json(c.folder / 'speaker_evidence.json', {
        'timeline': 'recording_offset_seconds', 'duration': 270,
        'turns': [{'start': 0, 'end': 270, 'speaker_id': 'speaker_0'}]})
    if only_asr_file:
        (c.folder / 'transcript.json').unlink()
    before = {p.name: p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    context = c.service.context('alice', c.parent)
    body = c.body.model_copy(update={'context_revision': context['context_revision']})
    receipt, _ = accept(c, body)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    transcript = c.note.generate_from_transcript.call_args.kwargs['transcript']
    assert transcript.full_text == full_text
    assert transcript.metadata['asr_evidence'] == raw
    assert len(transcript.metadata['asr_evidence']['segments']) == 27
    assert 'asr_evidence' not in transcript.metadata['asr_evidence']['metadata']
    assert transcript.metadata['asr_evidence']['segments'][0]['timestamp_estimated'] is True
    assert transcript.metadata['asr_evidence']['segments'][1]['timestamp_estimated'] is False
    assert all(not segment.get('speaker_id') for segment in transcript.metadata['asr_evidence']['segments'])
    assert transcript.metadata['speaker_evidence'] == [{'start': 0, 'end': 270, 'speaker_id': 'speaker_0'}]
    reloaded, _ = _evidence(c.artifacts.find_task_dir(receipt.task_id))
    assert reloaded.metadata['asr_evidence'] == raw  # Reading a saved child adds no wrapper.
    assert before == {p.name: p.read_bytes() for p in c.folder.iterdir() if p.is_file()}


def test_unwrapping_applies_without_external_speaker_evidence(case):
    from app.services.meeting_summary_regeneration import _evidence
    c = case
    raw = {**c.transcript, 'metadata': {'timestamp_granularity': 'session'}}
    wrapper = {**c.transcript, 'metadata': {'asr_evidence': raw}}
    c.artifacts.write_json(c.folder / 'transcript.json', {
        **c.transcript, 'metadata': {'asr_evidence': wrapper}})
    transcript, _ = _evidence(c.folder)
    assert transcript.metadata['asr_evidence'] == raw


@pytest.mark.parametrize('bad', ['depth', 'text', 'partial'])
def test_nested_original_evidence_rejects_unbounded_inconsistent_or_partial_source(case, bad):
    c = case
    raw = {**c.transcript, 'metadata': {}}
    if bad == 'text': raw['full_text'] = 'Different original source'
    if bad == 'partial': raw['metadata'] = {'partial': True}
    wrapped = raw
    for _ in range(9 if bad == 'depth' else 1):
        wrapped = {**c.transcript, 'metadata': {'asr_evidence': wrapped}}
    c.artifacts.write_json(c.folder / 'transcript.json', wrapped)
    with pytest.raises(HTTPException) as error: c.service.context('alice', c.parent)
    assert error.value.status_code == 409


@pytest.mark.parametrize('granularity', ['segment', 'session'])
def test_regenerated_summary_preserves_explicit_uncertainty_and_independent_voice_windows(case, granularity):
    from app.services.meeting_summary_regeneration import _evidence
    from app.services.note_service import NoteService
    c = case
    raw = {**c.transcript, 'segments': [{**c.transcript['segments'][0], 'timestamp_estimated': True}],
           'metadata': {'timestamp_granularity': granularity}}
    c.artifacts.write_json(c.folder / 'transcript.json', {
        **c.transcript, 'metadata': {'asr_evidence': raw}})
    c.artifacts.write_json(c.folder / 'speaker_evidence.json', {
        'timeline': 'recording_offset_seconds', 'duration': 10,
        'turns': [{'start': 0, 'end': 10, 'speaker_id': 'speaker_0'}]})
    transcript, _ = _evidence(c.folder)
    llm = Mock(summarize=Mock(return_value='offline pipeline-boundary assertion'))
    service = SimpleNamespace(artifact_service=Mock(),
        llm_service=SimpleNamespace(create_summarizer=Mock(return_value=llm)))
    context = SimpleNamespace(task_dir=c.folder, user_id='alice', model_profile_id=None,
        model_name=None, api_key=None, base_url=None, extras=None, style='meeting',
        audio_meta=SimpleNamespace(duration=10, title='offline fixture'), video_evidence=None,
        summary_mode='default', output_language='zh-CN', step_timings={})
    NoteService._summarize_audio(service, context, transcript)
    segment = llm.summarize.call_args.kwargs['segments'][0]
    assert segment.timestamp_estimated is True
    assert segment.speaker_id is None and segment.speaker_label is None
    assert segment.speaker_evidence == [{'start': 0, 'end': 10, 'speaker_id': 'speaker_0'}]
