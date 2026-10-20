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
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', lambda self, owner: {
        'mode': 'cloud', 'server_url': settings.vilab_server_url, 'asr_model': 'old-asr',
        'llm_model': 'chosen-catalog-id'})
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


def test_formats_are_frozen_per_child_and_replay_cannot_change_them(case):
    from app.services.meeting_summary_regeneration import SummaryConfirmation
    c = case
    body = SummaryConfirmation(**{**c.body.model_dump(), 'content_depth': 'brief', 'presentation': 'html'})
    receipt, _ = accept(c, body)
    child = c.artifacts.find_task_dir(receipt.task_id)
    metadata = json.loads((child / 'summary_presentation.json').read_text())
    assert metadata['content_depth'] == 'brief' and metadata['presentation'] == 'html'
    assert metadata['transcript_version'] == c.context['transcript_version']
    assert metadata['canonical_task_id'] == c.parent and metadata['model_name'] == body.model_name
    with pytest.raises(HTTPException):
        accept(c, body.model_copy(update={'presentation': 'text'}))
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_args.kwargs['content_depth'] == 'brief'
    assert c.note.generate_from_transcript.call_args.kwargs['presentation'] == 'html'
    assert not c.note.generate_from_file.called


@pytest.mark.parametrize('presentation', ['illustrated', 'comic'])
def test_unavailable_presentation_fails_before_catalog_or_reservation(case, monkeypatch, presentation):
    from app.services.meeting_summary_regeneration import SummaryConfirmation
    c = case
    body = SummaryConfirmation(**{**c.body.model_dump(), 'presentation': presentation})
    monkeypatch.setattr(VILabCloudService, 'models', Mock(side_effect=AssertionError('no catalog')))
    with pytest.raises(HTTPException) as error:
        accept(c, body)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException): c.receipts.get('alice', str(body.operation_id))


def test_infographic_is_an_explicit_same_model_format_without_imagegen(case):
    c = case
    body = c.body.model_copy(update={'presentation': 'infographic'})
    receipt, _ = accept(c, body)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    options = c.note.generate_from_transcript.call_args.kwargs
    assert options['presentation'] == 'infographic'
    frozen = json.loads((c.artifacts.find_task_dir(receipt.task_id) / SNAPSHOT_FILE).read_text())
    assert frozen['llm_model'] == body.model_name
    assert not c.note.generate_from_file.called


def test_two_versions_of_same_format_are_distinct_operations(case):
    c = case
    first, _ = accept(c)
    second, _ = accept(c, c.body.model_copy(update={'operation_id': uuid4()}))
    assert first.task_id != second.task_id


@pytest.mark.parametrize('actual_pipeline', [False, True])
def test_selected_parent_visual_donor_is_not_replaced_by_canonical_cache(case, actual_pipeline):
    from PIL import Image
    from app.services.video_evidence_service import VideoEvidenceService, VideoEvidence, VideoFrameEvidence
    c = case
    parent_receipt, _ = accept(c)
    selected = c.artifacts.find_task_dir(parent_receipt.task_id)
    c.artifacts.update_status(selected, 'success', 'synthetic selected parent')
    frame_dir = selected / 'video_evidence'; frame_dir.mkdir()
    frame = frame_dir / 'frame.jpg'; Image.new('RGB', (10, 10)).save(frame)
    evidence = VideoEvidence(10, [VideoFrameEvidence(0, frame, ['timeline'], [0, 9], 'synthetic', 'recognized')], 10, True)
    video = VideoEvidenceService()
    video._save(selected, evidence, video._identity(c.original, selected.resolve(), 'alice'))
    c.artifacts.write_json(c.folder / 'video_evidence.json', {'version': 'historical stale canonical'})
    before = {p: p.read_bytes() for root in (selected, c.folder) for p in root.rglob('*') if p.is_file()}
    context = c.service.context('alice', parent_receipt.task_id)
    body = c.body.model_copy(update={'operation_id': uuid4(), 'context_revision': context['context_revision']})
    runner = c.note
    if actual_pipeline:
        from app.services.note_service import NoteService
        runner = object.__new__(NoteService)
        runner.artifact_service = c.artifacts
        llm = SimpleNamespace(summarize=Mock(return_value='# Automatic synthetic report\n\nA supported synthetic proposal.'))
        runner.llm_service = SimpleNamespace(create_summarizer=Mock(return_value=llm))
        runner.transcription_service = SimpleNamespace(transcribe=Mock(side_effect=AssertionError('NEVER ASR')))
        body = body.model_copy(update={'content_depth': 'detailed', 'presentation': 'text'})
    receipt = c.service.accept('alice', parent_receipt.task_id, body, BackgroundTasks(), runner)
    c.service.run_once(receipt.task_id, 'alice', runner)
    if actual_pipeline:
        assert llm.summarize.call_count == 1
        assert llm.summarize.call_args.kwargs['video_evidence'].frames[0].image_path == frame
        assert not runner.transcription_service.transcribe.called
        assert c.artifacts.get_status(receipt.task_id)['status'] == 'success'
    else:
        assert c.note.generate_from_transcript.call_count == 1
        assert c.note.generate_from_transcript.call_args.kwargs['video_evidence'].frames[0].image_path == frame
    assert not c.note.generate_from_file.called
    assert all(p.read_bytes() == value for p, value in before.items())


def test_preparation_rejection_has_safe_enum_reason_without_private_values(case):
    c = case
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    c.artifacts.write_json(child / 'request.json', {'request': {'extras': 'PRIVATE MUST NOT APPEAR'}})
    c.service.run_once(receipt.task_id, 'alice', c.note)
    status = c.artifacts.get_status(receipt.task_id)
    assert status['error_code'] == 'summary_preflight_request_changed'
    assert status['retryable'] is False and not c.note.generate_from_transcript.called
    assert 'PRIVATE' not in json.dumps(status)


def test_preparation_reason_serializer_accepts_only_exact_allowlisted_enums(case):
    c = case
    c.artifacts.update_status(c.folder, 'failed', 'synthetic', error_code='summary_preflight_request_changed')
    assert c.artifacts.get_status(c.parent)['error_code'] == 'summary_preflight_request_changed'
    other = c.artifacts.create_task_dir(str(uuid4()))
    c.artifacts.update_status(other, 'failed', 'synthetic', error_code='summary_preflight_PRIVATE_VALUE')
    assert 'error_code' not in json.loads((other / 'status.json').read_text())


def test_second_version_uses_original_evidence_never_previous_summary_and_freezes_explicit_llm(case, monkeypatch):
    from app.services.note_service import NoteService
    from app.llm.openai_llm import _BasePromptLLM
    c = case
    first, _ = accept(c)
    parent = c.artifacts.find_task_dir(first.task_id)
    c.artifacts.update_status(parent, 'success', 'synthetic first version')
    sentinel = 'PREVIOUS_MINUTES_MUST_NEVER_ENTER_MODEL_INPUT'
    for filename in ('note.md', 'result.json', 'meeting_working_draft.json', 'meeting_fact_review.json'):
        c.artifacts.write_text(parent / filename, sentinel)
    c.artifacts.write_json(parent / 'speaker_evidence.json', {'timeline': 'recording_offset_seconds', 'duration': 10,
        'turns': [{'start': 0, 'end': 10, 'speaker_id': 'speaker_0'}]})
    monkeypatch.setattr(VILabCloudService, 'models', lambda self, owner: [
        {'id': model, 'modelType': 'llm', 'runtimeStatus': 'available'} for model in ('chosen-catalog-id', 'second-explicit-llm')])
    class CaptureLLM(_BasePromptLLM):
        def __init__(self): self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            if len(self.calls) == 1:
                return json.dumps({'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic source'}],
                    'claims': [{'id': 'C1', 'topic_id': 'T1', 'field': 'relation', 'text': c.transcript['full_text'], 'anchor': c.transcript['full_text'],
                         'material': True, 'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': c.transcript['full_text']}]}]})
            return json.dumps({'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': '# Synthetic source'}, {'id': 'B2', 'markdown': c.transcript['full_text']}],
                'claims': [{'id': 'C1', 'field': 'relation', 'text': c.transcript['full_text'], 'material': True,
                    'disposition': 'included', 'block_ids': ['B2'],
                    'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': c.transcript['full_text']}]}]})
    llm = CaptureLLM()
    runner = object.__new__(NoteService)
    runner.artifact_service = c.artifacts
    runner.llm_service = SimpleNamespace(create_summarizer=Mock(return_value=llm))
    runner.transcription_service = SimpleNamespace(transcribe=Mock(side_effect=AssertionError('NEVER ASR')))
    before = {p: p.read_bytes() for p in parent.rglob('*') if p.is_file()}
    context = c.service.context('alice', first.task_id)
    body = c.body.model_copy(update={'operation_id': uuid4(), 'context_revision': context['context_revision'],
        'model_name': 'second-explicit-llm', 'content_depth': 'detailed', 'presentation': 'text'})
    second = c.service.accept('alice', first.task_id, body, BackgroundTasks(), runner)
    c.service.run_once(second.task_id, 'alice', runner)
    assert c.artifacts.get_status(second.task_id)['status'] == 'success'
    assert len(llm.calls) == 2
    assert all(sentinel not in json.dumps(call) for call in llm.calls)
    assert all(c.transcript['full_text'] in call['user_prompt'] for call in llm.calls)
    assert all('speaker_0' in call['user_prompt'] for call in llm.calls)
    snapshot = json.loads((c.artifacts.find_task_dir(second.task_id) / SNAPSHOT_FILE).read_text())
    assert snapshot['llm_model'] == 'second-explicit-llm' and snapshot['needs_stt'] is False
    assert not runner.transcription_service.transcribe.called
    assert before == {p: p.read_bytes() for p in parent.rglob('*') if p.is_file()}


def test_summary_snapshot_preserves_connection_auth_mode_without_tokens(monkeypatch):
    import app.services.meeting_summary_regeneration as module
    connection = {'configured': True, 'mode': 'cloud', 'server_url': 'https://connection.invalid',
        'connection_id': 'immutable-account-connection', 'connection_auth_mode': 'account',
        'asr_model': 'asr-unchanged', 'llm_model': 'global-default'}
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', lambda self, owner: connection)
    monkeypatch.setattr(module, 'validate_source', lambda source, owner: source)
    frozen = module._snapshot('alice', 'this-version-llm')
    assert frozen['connection_auth_mode'] == 'account' and frozen['connection_id'] == connection['connection_id']
    assert frozen['llm_model'] == 'this-version-llm' and frozen['asr_model'] == 'asr-unchanged'
    assert 'configured' not in frozen and 'token' not in frozen


@pytest.mark.parametrize('changed', ['connection', 'mode', 'asr'])
def test_accepted_summary_uses_db_bound_snapshot_after_global_changes(case, monkeypatch, changed):
    c = case
    receipt, _ = accept(c)
    accepted = json.loads((c.artifacts.find_task_dir(receipt.task_id) / SNAPSHOT_FILE).read_text())
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', Mock(side_effect=AssertionError('NEVER current selection after accept')))
    def changed_status(self, owner):
        frozen = _task_source.get()
        if frozen and frozen[0] == owner: return dict(frozen[1])
        return {'mode': 'local'} if changed == 'mode' else {'mode': 'cloud', 'server_url': 'https://other.invalid', 'asr_model': 'new-asr'}
    monkeypatch.setattr(VILabCloudService, 'status', changed_status)
    seen = []
    c.note.generate_from_transcript.side_effect = lambda **kwargs: seen.append(dict(_task_source.get()[1]))
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert len(seen) == 1
    assert {key: value for key, value in seen[0].items() if key != 'configured'} == accepted
    assert not c.note.generate_from_file.called


@pytest.mark.parametrize('tamper', [
    {'asr_model': 'tampered-snapshot-field'}, {'llm_model': 'another-model'},
    {'server_url': 'https://different.invalid'}, {'connection_id': 'different-connection'},
    {'connection_id': 'different-connection', 'connection_auth_mode': 'account'}, {'needs_stt': True},
])
def test_tampering_frozen_snapshot_cannot_be_authorized_by_current_global_selection(case, monkeypatch, tamper):
    c = case
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    frozen = json.loads((child / SNAPSHOT_FILE).read_text())
    c.artifacts.write_json(child / SNAPSHOT_FILE, {**frozen, **tamper})
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', lambda self, owner: {**frozen, **tamper})
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert not c.note.generate_from_transcript.called
    assert c.artifacts.get_status(receipt.task_id)['retryable'] is False


def test_legacy_receipt_without_accepted_snapshot_binding_never_gains_execution(case):
    c = case
    receipt, _ = accept(c)
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
        payload = json.loads(row.receipt_json)
        payload.pop('summary_snapshot_sha256')
        row.receipt_json = json.dumps(payload)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert not c.note.generate_from_transcript.called
    assert c.artifacts.get_status(receipt.task_id)['retryable'] is False


def test_illustrated_reuses_verified_visuals_and_never_mutates_donor(case):
    from PIL import Image
    from app.services.video_evidence_service import VideoEvidenceService, VideoEvidence, VideoFrameEvidence
    from app.services.meeting_summary_regeneration import SummaryConfirmation
    c = case
    frame_folder = c.folder / 'video_evidence'
    frame_folder.mkdir()
    image = frame_folder / 'frame.jpg'
    Image.new('RGB', (10, 10)).save(image)
    visual = VideoEvidence(10, [VideoFrameEvidence(0, image, ['timeline'], [0, 9], 'synthetic screen', 'recognized')], 10, True)
    service = VideoEvidenceService()
    service._save(c.folder, visual, service._identity(c.original, c.folder.resolve(), 'alice'))
    before = {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    context = c.service.context('alice', c.parent)
    assert context['presentation_options']['illustrated']['available'] is True
    assert context['visual_evidence_version']
    body = SummaryConfirmation(**{**c.body.model_dump(), 'context_revision': context['context_revision'],
                                 'content_depth': 'brief', 'presentation': 'illustrated'})
    receipt, _ = accept(c, body)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    call = c.note.generate_from_transcript.call_args.kwargs
    assert call['video_evidence'].frames[0].image_path == image
    call['video_evidence'].align([])  # Must not rewrite donor's manifest.
    from app.services.summary_presentation_artifact import render_presentation
    figures = [{'frame_ref': '[FRAME:0001]', 'after_passage': 'Automatic synthetic facts.', 'caption': 'Synthetic screen'}]
    render_context = SimpleNamespace(task_dir=c.artifacts.find_task_dir(receipt.task_id),
        task_id=receipt.task_id, presentation='illustrated', video_evidence=call['video_evidence'], presentation_figures=figures)
    with pytest.raises(ValueError): render_presentation(c.artifacts, render_context, '# No model selection')
    output = render_presentation(c.artifacts, render_context, '# Topic\n\nAutomatic synthetic facts.\n\n[FRAME:0001]\n\nNext paragraph.')
    assert 'FRAME:' not in output and output.index('summary-source-0.jpg') < output.index('Next paragraph.')
    assert f'/api/task/{receipt.task_id}/artifacts/screenshots/summary-source-0.jpg' in output
    assert (c.artifacts.find_task_dir(receipt.task_id) / 'screenshots/summary-source-0.jpg').read_bytes() == image.read_bytes()
    assert before == {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    image.write_bytes(b'changed')
    with pytest.raises(HTTPException): c.service.context('alice', c.parent)


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
