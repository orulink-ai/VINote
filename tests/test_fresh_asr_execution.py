"""Explicit fresh ASR: real receipt/lease/checkpoint paths, no network."""
import json
import socket
import uuid
from contextvars import copy_context
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.config import settings
from app.models.audio import AudioDownloadResult
from app.db_models import SourceRequestDB
from app.services.asr_execution_binding import current_execution
from app.services.task_model_source import SNAPSHOT_FILE
from app.services.task_fresh_asr import FreshASRConfirmation, FreshASRService
from app.services.vilab_cloud_service import VILabCloudService, _task_source
from tests.test_new_generation_operation import case
from tests.test_independent_asr_namespace import audio_case, tmp_path
from tests.test_meeting_summary_regeneration import case as summary_case


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('Fresh ASR tests must never connect to a provider')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def fresh(case, monkeypatch):
    c = case
    c.fresh = FreshASRService(c.receipts)
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', lambda *a: {
        'mode': 'cloud', 'server_url': 'https://original.invalid'})
    monkeypatch.setattr(VILabCloudService, 'models', lambda *a: [
        {'id': 'original-asr', 'modelType': 'asr', 'runtimeStatus': 'available'},
        {'id': 'selected-llm', 'modelType': 'llm', 'runtimeStatus': 'available'}])
    def ready(self, owner, *, needs_stt=True):
        assert owner == 'alice' and needs_stt
        assert _task_source.get()[1]['llm_model'] == 'selected-llm'
    monkeypatch.setattr(VILabCloudService, 'validate_ready', ready)
    context = c.fresh.context('alice', c.parent)
    c.body = FreshASRConfirmation(operation_id=uuid.uuid4(), confirmed=True,
        asr_mode='fresh', llm_mode='select', extra_asr_consent=True,
        context_revision='a' * 64, fresh_context_revision=context['context_revision'],
        selection_revision='b' * 64, source_version=context['source']['version'],
        asr_model='original-asr', model_name='selected-llm')
    return c


def accept_fresh(c, body=None):
    bg = BackgroundTasks()
    result = c.fresh.accept('alice', c.parent, body or c.body, bg)
    return result, bg


def pipeline(function=None):
    return SimpleNamespace(_build_local_audio_meta=lambda **kw: AudioDownloadResult(
        kw['file_path'], kw['title'] or 'Synthetic', 3, kw['task_id'], 'local'),
        _run_pipeline=Mock(side_effect=function))


@pytest.mark.parametrize('status', ['success', 'failed'])
def test_terminal_original_creates_distinct_fresh_no_copies_or_old_changes(fresh, status):
    c = fresh
    c.artifacts.update_status(c.folder, status, 'terminal', retryable=False)
    context = c.fresh.context('alice', c.parent)
    c.body = c.body.model_copy(update={'fresh_context_revision': context['context_revision']})
    before = {str(p.relative_to(c.folder)): p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    receipt, bg = accept_fresh(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert receipt.state == 'accepted' and receipt.task_id != c.parent and len(bg.tasks) == 1
    assert c.artifacts.resolve_source_media(child) == c.original and not (child / 'media').exists()
    assert not (child / 'transcript.json').exists() and not (child / 'transcription_chunks').exists()
    snapshot = json.loads((child / SNAPSHOT_FILE).read_text())
    assert snapshot['asr_model'] == 'original-asr' and snapshot['llm_model'] == 'selected-llm'
    assert before == {str(p.relative_to(c.folder)): p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}


def test_same_operation_is_query_only_even_after_source_removed(fresh):
    c = fresh; receipt, _ = accept_fresh(c)
    c.original.unlink()
    again, bg = accept_fresh(c)
    assert again.task_id == receipt.task_id and not bg.tasks
    with pytest.raises(HTTPException):
        accept_fresh(c, c.body.model_copy(update={'asr_model': 'another'}))


@pytest.mark.parametrize('change', ['active', 'source', 'owner', 'summary_snapshot', 'missing_asr', 'workflow'])
def test_untrusted_or_changed_source_never_reserves(fresh, change):
    c = fresh
    if change == 'active': c.artifacts.write_json(c.folder / 'status.json', {'status': 'transcribing'})
    if change == 'source': c.original.write_bytes(b'modified')
    if change == 'owner': (c.folder / 'recording_owner').write_text('bob')
    if change in {'summary_snapshot', 'missing_asr'}:
        c.artifacts.write_json(c.folder / SNAPSHOT_FILE, {**c.snapshot,
            **({'needs_stt': False} if change == 'summary_snapshot' else {'asr_model': ''})})
    if change == 'workflow': c.artifacts.write_json(c.folder / 'request.json', {'request': {'workflow': 'note_organization'}})
    with pytest.raises(HTTPException): accept_fresh(c)
    with pytest.raises(HTTPException) as missing: c.receipts.get('alice', str(c.body.operation_id))
    assert missing.value.status_code == 404


@pytest.mark.parametrize('field,value', [('extra_asr_consent', False), ('confirmed', 1),
    ('asr_mode', 'reuse'), ('llm_mode', 'inherit'), ('asr_model', ''), ('model_name', ' padded ')])
def test_fresh_requires_explicit_consent_and_pair(fresh, field, value):
    with pytest.raises(ValueError):
        FreshASRConfirmation(**{**fresh.body.model_dump(), field: value})


@pytest.mark.parametrize('damage', ['missing_db', 'reserved', 'task', 'fingerprint', 'snapshot', 'link', 'cache'])
def test_accepted_binding_required_before_fresh_dispatch(fresh, damage):
    c = fresh; receipt, _ = accept_fresh(c); child = c.artifacts.find_task_dir(receipt.task_id)
    with c.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
        if damage == 'missing_db': db.delete(row)
        elif damage == 'reserved': row.state = 'reserved'
        elif damage == 'task': row.task_id = c.parent
        elif damage == 'fingerprint': row.fingerprint = '0' * 64
    if damage == 'snapshot': c.artifacts.write_json(child / SNAPSHOT_FILE, {**c.snapshot, 'llm_model': 'forged'})
    if damage == 'link':
        link = json.loads((child / 'new_generation.json').read_text()); link['source_version'] = '0' * 64
        c.artifacts.write_json(child / 'new_generation.json', link)
    if damage == 'cache': c.artifacts.write_json(child / 'transcript.json', {'full_text': 'old'})
    service = pipeline()
    c.fresh.run_once(receipt.task_id, 'alice', service)
    service._run_pipeline.assert_not_called()


def test_revocable_lease_and_one_claim_only(fresh):
    c = fresh; receipt, _ = accept_fresh(c); retained = []
    def generate(**kwargs):
        binding = current_execution(); assert binding.fresh is True
        binding.validate(); retained.append(copy_context())
        assert kwargs['audio_meta'].file_path == str(c.original) and kwargs['user_id'] == 'alice'
        assert kwargs['content_depth'] == c.body.content_depth and kwargs['presentation'] == c.body.presentation
        assert kwargs['preloaded_transcript'] is None
    service = pipeline(generate)
    c.fresh.run_once(receipt.task_id, 'alice', service)
    c.fresh.run_once(receipt.task_id, 'alice', service)
    assert service._run_pipeline.call_count == 1 and current_execution() is None
    with pytest.raises(ValueError): retained[0].run(current_execution)


def test_accepted_metadata_alone_cannot_mint_fresh_lease_without_claim(fresh):
    from app.services.asr_execution_binding import _claimed_execution
    c = fresh; receipt, _ = accept_fresh(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    snapshot = json.loads((child / SNAPSHOT_FILE).read_text())
    link = json.loads((child / 'new_generation.json').read_text())
    with VILabCloudService().task_snapshot('alice', snapshot=snapshot), pytest.raises((ValueError, OSError)):
        with _claimed_execution(c.receipts, c.artifacts, 'alice', receipt.task_id, child, snapshot, link, c.original):
            pytest.fail('An accepted receipt alone is not an exclusive run_once claim')
    assert current_execution() is None


def test_fresh_never_reads_or_locks_old_global_or_parent_cache(fresh, audio_case, monkeypatch):
    c = fresh; audio = audio_case
    monkeypatch.setattr(settings, 'data_dir', audio.tmp_path / 'data')
    before = (audio.donor / 'recognition.json').read_bytes()
    old_read = Mock(side_effect=AssertionError('fresh must not read donor'))
    monkeypatch.setattr('app.transcribers.vilab_transcriber._read_donor', old_read)
    from app.services.asr_checkpoint_lock import checkpoint_lock
    seen = []
    def generate(**kwargs):
        with checkpoint_lock(audio.donor):  # busy old donor cannot block explicit fresh
            seen.append(audio.adapter._transcribe_stream(str(audio.wav)))
    receipt, _ = accept_fresh(c)
    c.fresh.run_once(receipt.task_id, 'alice', pipeline(generate))
    assert seen and 'saved' not in seen[0].full_text
    intervals = [(call.kwargs['start'], call.kwargs['end']) for call in audio.recognize.call_args_list]
    assert intervals[0][0] == 0 and intervals[-1][1] == 3
    assert all(left[1] == right[0] for left, right in zip(intervals, intervals[1:]))
    old_read.assert_not_called()
    assert (audio.donor / 'recognition.json').read_bytes() == before
    child = c.artifacts.find_task_dir(receipt.task_id)
    record = json.loads((child / 'transcription_chunks/vilab_stream/recognition.json').read_text())
    assert record['execution']['asr_mode'] == 'fresh' and 'seed' not in record


@pytest.mark.parametrize('change', ['model', 'origin', 'owner', 'reference'])
def test_fresh_live_lease_revalidates_before_audio(fresh, audio_case, change):
    c = fresh; audio = audio_case
    def process(**kwargs):
        binding = current_execution()
        if change == 'reference':
            path = binding.folder / 'source_reference.json'
            ref = json.loads(path.read_text()); ref['source_version'] = 'e' * 64
            c.artifacts.write_json(path, ref)
        elif change == 'model': audio.adapter.model = 'foreign-asr'
        elif change == 'origin': audio.adapter.base_url = 'https://foreign.invalid'
        elif change == 'owner': audio.adapter.cloud_user_id = 'bob'
        with pytest.raises(ValueError): audio.adapter._transcribe_stream(str(audio.wav))
    receipt, _ = accept_fresh(c)
    service = pipeline(process); c.fresh.run_once(receipt.task_id, 'alice', service)
    assert service._run_pipeline.call_count == 1
    audio.recognize.assert_not_called()


def test_fresh_empty_checkpoint_fsync_failure_precedes_policy_or_audio(fresh, audio_case, monkeypatch):
    c = fresh; audio = audio_case
    def process(**kwargs):
        monkeypatch.setattr('app.transcribers.vilab_transcriber._save_checkpoint', Mock(side_effect=OSError('synthetic fsync')))
        with pytest.raises(OSError): audio.adapter._transcribe_stream(str(audio.wav))
    receipt, _ = accept_fresh(c)
    c.fresh.run_once(receipt.task_id, 'alice', pipeline(process))
    audio.policy.assert_not_called(); audio.token.assert_not_called(); audio.recognize.assert_not_called()


def test_fresh_unknown_keeps_original_namespace_and_never_replays(fresh, audio_case):
    from app.services.asr_stream_service import ASRServiceError
    c = fresh; audio = audio_case
    audio.recognize.side_effect = ASRServiceError('unknown_result')
    def process(**kwargs):
        with pytest.raises(ASRServiceError): audio.adapter._transcribe_stream(str(audio.wav))
        path = current_execution().chunks / 'vilab_stream/recognition.json'
        before = path.read_bytes()
        assert json.loads(before)['inflight']
        with pytest.raises(ASRServiceError): audio.adapter._transcribe_stream(str(audio.wav))
        assert path.read_bytes() == before
    receipt, _ = accept_fresh(c)
    service = pipeline(process)
    c.fresh.run_once(receipt.task_id, 'alice', service)
    c.fresh.run_once(receipt.task_id, 'alice', service)
    again, bg = accept_fresh(c)
    assert again.task_id == receipt.task_id and not bg.tasks
    assert audio.recognize.call_count == 1 and service._run_pipeline.call_count == 1


@pytest.mark.parametrize('damage', ['seed', 'normalized_identity'])
def test_fresh_own_complete_cache_must_remain_fresh_and_same_wav(fresh, audio_case, damage):
    from tests.test_adaptive_asr_policy import write_wav
    c = fresh; audio = audio_case
    def process(**kwargs):
        audio.adapter._transcribe_stream(str(audio.wav))
        path = current_execution().chunks / 'vilab_stream/recognition.json'
        if damage == 'seed':
            data = json.loads(path.read_text()); data['seed'] = {'forbidden': 'old'}
            c.artifacts.write_json(path, data)
        before = path.read_bytes(); audio.recognize.reset_mock()
        source = audio.wav if damage == 'seed' else write_wav(c.tmp_path / 'other.wav', seconds=2)
        with pytest.raises(ValueError): audio.adapter._transcribe_stream(str(source))
        assert path.read_bytes() == before
        audio.recognize.assert_not_called()
    receipt, _ = accept_fresh(c)
    service = pipeline(process); c.fresh.run_once(receipt.task_id, 'alice', service)
    assert service._run_pipeline.call_count == 1


@pytest.mark.parametrize('field,value', [('asr_model', 'unknown'), ('model_name', 'unknown'),
    ('presentation', 'comic'), ('presentation', 'infographic')])
def test_missing_catalog_selection_or_unsupported_format_never_reserves(fresh, field, value, monkeypatch):
    c = fresh
    body = c.body.model_copy(update={field: value})
    if field == 'presentation':
        from app.llm import meeting_presentation
        availability = meeting_presentation.presentation_availability
        def unavailable(**kwargs):
            return {**availability(**kwargs), value: {'available': False, 'reason': 'Synthetic unavailable capability'}}
        monkeypatch.setattr(meeting_presentation, 'presentation_availability', unavailable)
        body = body.model_copy(update={'fresh_context_revision': c.fresh.context('alice', c.parent)['context_revision']})
    with pytest.raises((ValueError, HTTPException)) as error:
        accept_fresh(c, body)
    if field == 'presentation':
        assert error.value.detail['code'] == 'fresh_presentation_unavailable'
    with pytest.raises(HTTPException): c.receipts.get('alice', str(c.body.operation_id))


@pytest.mark.parametrize('damage', [None, 'origin', 'request', 'parent_model', 'modern_shape', 'digest_mismatch', 'fingerprint', 'owner'])
def test_exact_legacy_summary_origin_proof_allows_fresh_only_with_unchanged_binding(summary_case, damage, monkeypatch):
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _digest, _submission
    from app.services.source_request_service import _fingerprint
    c = summary_case
    receipt = c.service.accept('alice', c.parent, c.body, BackgroundTasks(), c.note)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    child = c.artifacts.find_task_dir(receipt.task_id)
    c.artifacts.update_status(child, 'success', 'synthetic')
    prior, _, _, _, request = c.service._context('alice', c.parent)
    legacy = {key: prior[key] for key in ('protocol', 'parent_task_id', 'canonical_task_id', 'workflow',
        'source', 'transcript_version', 'requires_confirmation', 'can_regenerate_summary')}
    revision = _digest({'owner': 'alice', 'context': legacy, 'request': request,
        'snapshot': c.snapshot, 'source_reference': None})
    link = {'contract': 'meeting-summary-only-v1', 'parent_task_id': c.parent,
        'operation_id': receipt.operation_id, 'confirmed': True, 'canonical_task_id': None,
        'context_revision': revision, 'source_version': prior['source']['version'], 'model_name': c.body.model_name}
    if damage == 'modern_shape': link['presentation'] = None
    c.artifacts.write_json(child / 'new_generation.json', link)
    with c.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', receipt.operation_id))
        row.fingerprint = _fingerprint(_submission(c.parent, SummaryConfirmation(**{
            key: link[key] for key in SummaryConfirmation.model_fields if key in link})))
        meta = json.loads(row.receipt_json); meta.pop('summary_snapshot_sha256')
        if damage == 'digest_mismatch': meta['summary_snapshot_sha256'] = 'e' * 64
        if damage == 'fingerprint': row.fingerprint = '0' * 64
        row.receipt_json = json.dumps(meta)
        original_receipt = row.receipt_json
    snapshot = json.loads((child / SNAPSHOT_FILE).read_text())
    snapshot['asr_model'] = 'unused-display-field'
    if damage == 'origin': snapshot['server_url'] = 'https://foreign.invalid'
    c.artifacts.write_json(child / SNAPSHOT_FILE, snapshot)
    if damage == 'request': c.artifacts.write_json(c.folder / 'request.json', {'request': {**request['request'], 'title': 'different'}})
    if damage == 'parent_model': c.artifacts.write_json(c.folder / SNAPSHOT_FILE, {**c.snapshot, 'llm_model': 'other'})
    if damage == 'owner': (child / 'recording_owner').write_text('bob')
    service = FreshASRService(c.receipts)
    if damage:
        with pytest.raises(HTTPException): service.context('alice', receipt.task_id)
    else:
        context = service.context('alice', receipt.task_id)
        assert context['available'] and context['canonical_task_id'] == c.parent
        assert context['frozen_models']['asr_model'] == 'old-asr'
        monkeypatch.setattr(VILabCloudService, 'models', lambda *args: [
            {'id': 'fresh-asr', 'modelType': 'asr', 'runtimeStatus': 'available'},
            {'id': 'fresh-llm', 'modelType': 'llm', 'runtimeStatus': 'available'}])
        body = FreshASRConfirmation(operation_id=uuid.uuid4(), confirmed=True, asr_mode='fresh',
            llm_mode='select', extra_asr_consent=True, context_revision='a' * 64, selection_revision='b' * 64,
            fresh_context_revision=context['context_revision'], source_version=context['source']['version'],
            asr_model='fresh-asr', model_name='fresh-llm')
        background = BackgroundTasks()
        new = service.accept('alice', receipt.task_id, body, background)
        assert new.state == 'accepted' and new.task_id not in {receipt.task_id, c.parent}
        runner = pipeline()
        service.run_once(new.task_id, 'alice', runner)
        assert runner._run_pipeline.call_count == 1
    with c.sessions() as db:
        assert db.get(SourceRequestDB, ('alice', receipt.operation_id)).receipt_json == original_receipt


def test_audio_only_webm_does_not_advertise_visual_presentation(fresh):
    c = fresh
    c.artifacts.record_source_media(c.folder, c.original, media_kind='audio')
    context = c.fresh.context('alice', c.parent)
    assert context['presentation_options']['illustrated']['available'] is False
    body = c.body.model_copy(update={'presentation': 'illustrated', 'fresh_context_revision': context['context_revision']})
    with pytest.raises(HTTPException): accept_fresh(c, body)


def test_fresh_successful_child_can_itself_be_selected_for_another_fresh_version(fresh):
    c = fresh; first, _ = accept_fresh(c)
    c.fresh.run_once(first.task_id, 'alice', pipeline())
    child = c.artifacts.find_task_dir(first.task_id)
    c.artifacts.update_status(child, 'success', 'synthetic')
    context = c.fresh.context('alice', first.task_id)
    assert context['canonical_task_id'] == c.parent
    body = c.body.model_copy(update={'operation_id': uuid.uuid4(), 'fresh_context_revision': context['context_revision']})
    bg = BackgroundTasks()
    second = c.fresh.accept('alice', first.task_id, body, bg)
    assert second.task_id not in {first.task_id, c.parent} and len(bg.tasks) == 1
    ref = json.loads((c.artifacts.find_task_dir(second.task_id) / 'source_reference.json').read_text())
    assert ref['parent_task_id'] == c.parent


@pytest.mark.parametrize('damage', [None, 'receipt', 'snapshot', 'canonical_asr', 'modern_missing_digest'])
def test_summary_parent_requires_accepted_lineage_to_actual_asr_original(summary_case, damage):
    c = summary_case
    receipt = c.service.accept('alice', c.parent, c.body, BackgroundTasks(), c.note)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    child = c.artifacts.find_task_dir(receipt.task_id)
    c.artifacts.update_status(child, 'success', 'synthetic summary')
    if damage == 'receipt':
        with c.sessions() as db: db.delete(db.get(SourceRequestDB, ('alice', str(c.body.operation_id))))
    elif damage == 'modern_missing_digest':
        with c.sessions() as db:
            row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
            meta = json.loads(row.receipt_json); meta.pop('summary_snapshot_sha256')
            row.receipt_json = json.dumps(meta)
    elif damage == 'snapshot':
        saved = json.loads((child / SNAPSHOT_FILE).read_text()); saved['asr_model'] = 'fake-looking-asr'
        c.artifacts.write_json(child / SNAPSHOT_FILE, saved)
    elif damage == 'canonical_asr':
        c.artifacts.write_json(c.folder / SNAPSHOT_FILE, {**c.snapshot, 'needs_stt': False})
    fresh_service = FreshASRService(c.receipts)
    if damage:
        with pytest.raises((ValueError, HTTPException)): fresh_service.context('alice', receipt.task_id)
    else:
        context = fresh_service.context('alice', receipt.task_id)
        assert context['available'] and context['canonical_task_id'] == c.parent
        assert context['frozen_models']['asr_model'] == 'old-asr'
        # The summary child's retained ASR field alone did not authorize this.
        assert json.loads((child / SNAPSHOT_FILE).read_text())['needs_stt'] is False


def test_legacy_independent_success_parent_can_create_fresh_without_reading_prefix(fresh, monkeypatch):
    from tests.test_new_generation_operation import accept
    c = fresh
    # Legacy executor still inherits its original pair.
    monkeypatch.setattr(VILabCloudService, 'validate_ready', lambda *args, **kwargs: None)
    receipt, _ = accept(c)
    c.service.run_once(receipt.task_id, 'alice', Mock())
    child = c.artifacts.find_task_dir(receipt.task_id)
    c.artifacts.update_status(child, 'success', 'synthetic')
    monkeypatch.setattr('app.transcribers.vilab_transcriber._read_donor', Mock(side_effect=AssertionError('no prefix')))
    context = c.fresh.context('alice', receipt.task_id)
    body = c.body.model_copy(update={'fresh_context_revision': context['context_revision']})
    result = c.fresh.accept('alice', receipt.task_id, body, BackgroundTasks())
    assert result.state == 'accepted' and result.task_id != receipt.task_id


def test_real_fresh_note_pipeline_sends_full_audio_with_selected_llm(fresh, audio_case, monkeypatch):
    from app.services.note_service import NoteService
    from tests.test_independent_asr_namespace import _REAL_STATUS
    c = fresh; audio = audio_case
    c.original.write_bytes(audio.wav.read_bytes())
    c.artifacts.record_source_media(c.folder, c.original, media_kind='audio')
    context = c.fresh.context('alice', c.parent)
    c.body = c.body.model_copy(update={'fresh_context_revision': context['context_revision'],
        'source_version': context['source']['version'], 'content_depth': 'detailed'})
    monkeypatch.setattr(VILabCloudService, 'status', _REAL_STATUS)
    chats = []
    def chat(self, owner, method, endpoint, **kwargs):
        assert owner == 'alice' and method == 'POST' and endpoint == '/openai/v1/chat/completions'
        assert kwargs['json']['model'] == 'selected-llm'
        chats.append(kwargs['json'])
        material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic source'}],
            'claims': [{'id': 'C1', 'topic_id': 'T1', 'field': 'relation', 'text': 'new', 'anchor': 'new',
                'material': True, 'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': 'new'}]}]}
        review = {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': '# Synthetic meeting\n\nnew'}],
            'claims': [{'id': 'C1', 'field': 'relation', 'text': 'new', 'material': True,
                'disposition': 'included', 'block_ids': ['B1'],
                'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': 'new'}]}]}
        return {'choices': [{'message': {'content': json.dumps(material if len(chats) == 1 else review)}}]}
    monkeypatch.setattr(VILabCloudService, 'request', chat)
    monkeypatch.setattr(settings, 'meeting_review_model', '')
    from app.services import task_fresh_asr
    dispatch = task_fresh_asr._dispatch
    errors = []
    def observed(*args):
        try: return dispatch(*args)
        except Exception as error:
            errors.append(error)
            raise
    monkeypatch.setattr(task_fresh_asr, '_dispatch', observed)
    receipt, _ = accept_fresh(c)
    c.fresh.run_once(receipt.task_id, 'alice', NoteService(artifact_service=c.artifacts))
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'success', errors
    assert all((child / name).is_file() for name in ('transcript.json', 'note.md', 'result.json'))
    transcript = json.loads((child / 'transcript.json').read_text())
    assert 'saved' not in transcript['full_text']
    assert audio.recognize.call_args_list[0].kwargs['start'] == 0
    assert audio.recognize.call_args_list[-1].kwargs['end'] == 3
    assert chats and not (child / 'media').exists()
