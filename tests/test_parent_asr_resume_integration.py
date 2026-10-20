"""Actual operation/lease/transcriber flow with synthetic audio and no network."""
import hashlib
import json
import os
import socket
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from tests.test_independent_asr_namespace import audio_case, tmp_path, identity, _EMPTY_PROOF
from tests.test_new_generation_operation import case, accept
from tests.test_adaptive_asr_policy import write_wav
from app.services.adaptive_asr_policy import RecordedAudioPolicy
from app.services.asr_execution_binding import current_execution
from app.services.asr_stream_service import ASRServiceError
from app.services.task_generation_context import frozen_generation_context
from app.services.task_new_generation import NewGenerationConfirmation


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original(sock, address)  # Windows asyncio self-pipe only.
        pytest.fail('No external network in resume tests')
    monkeypatch.setattr(socket.socket, 'connect', connect)


@pytest.fixture
def failed_parent(audio_case):
    c = audio_case
    write_wav(c.wav, seconds=21)
    c.donor = c.donor.parent / identity(c.wav)
    c.donor.mkdir()
    c.artifacts.write_json(c.donor / 'recognition.json', c.old)
    c.policy.return_value = RecordedAudioPolicy(32000)
    def recognize(*args, start, end, **kwargs):
        if c.recognize.call_count == 20:
            raise ASRServiceError('asr_provider_error')
        if c.recognize.call_count in (4, 12, 17):
            return {'text': '', 'segments': [], 'recognition_outcome': 'provider_terminal_empty',
                    'terminal_evidence': _EMPTY_PROOF}
        return {'text': 'confirmed synthetic interval', 'language': 'zh'}
    c.recognize.side_effect = recognize
    receipt, _ = accept(c)
    parent = c.artifacts.find_task_dir(receipt.task_id)
    def dispatch(*_):
        with pytest.raises(ASRServiceError):
            c.adapter._transcribe_stream(str(c.wav))
        c.artifacts.update_status(parent, 'failed', 'synthetic upstream failure',
                                  stage='asr', error_code='asr_provider_error', retryable=False)
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    path = parent / 'transcription_chunks' / 'vilab_stream' / 'recognition.json'
    record = json.loads(path.read_text())
    assert len(record['completed']) == 20
    assert sum(p.get('recognition_outcome') == 'provider_terminal_empty' for p in record['completed']) == 3
    end_frame = round(record['completed'][-1]['end'] * 16000)
    assert record['inflight']['start_frame'] == end_frame
    c.recognize.reset_mock()
    c.token.reset_mock()
    c.policy.reset_mock()
    return SimpleNamespace(c=c, parent=parent, receipt=receipt, checkpoint=path, end_frame=end_frame)


def confirmation(r):
    ctx = frozen_generation_context('alice', r.receipt.task_id, receipts=r.c.receipts)
    body = NewGenerationConfirmation(operation_id=uuid.uuid4(), confirmed=True,
        context_revision=ctx['context_revision'], source_version=ctx['source']['version'],
        canonical_task_id=ctx['canonical_task_id'])
    return ctx, body


def test_v2_context_is_owner_bound_offline_and_canonical_without_registering_child(failed_parent):
    r = failed_parent
    ctx, _ = confirmation(r)
    assert ctx['protocol'] == 2 and ctx['canonical_task_id'] == r.c.parent
    assert ctx['parent_task_id'] == r.receipt.task_id
    assert ctx['source']['file_id'] == 'task:' + r.c.parent
    assert not (r.parent / 'source_original.json').exists()
    assert 'file_path' not in json.dumps(ctx) and 'request' not in ctx
    assert 'parent_prefix' not in ctx  # Opaque revision, no new public fields.
    r.c.token.assert_not_called()
    r.c.recognize.assert_not_called()
    with pytest.raises(HTTPException) as error:
        frozen_generation_context('bob', r.receipt.task_id, receipts=r.c.receipts)
    assert error.value.status_code == 404


def test_readonly_preflight_validates_normalized_wav_and_twenty_parts_without_claim(failed_parent):
    r, c = failed_parent, failed_parent.c
    before = r.checkpoint.read_bytes()
    with c.sessions() as db:
        from sqlalchemy import select, func
        from app.db_models import SourceRequestDB
        count = db.scalar(select(func.count()).select_from(SourceRequestDB))
    report = c.service.preflight_parent('alice', r.receipt.task_id, c.wav)
    assert report['confirmed_parts'] == 20 and report['typed_empty_parts'] == 3
    assert report['confirmed_end_frame'] == r.end_frame
    assert report['remaining_frames'] == 336000 - r.end_frame
    assert report['checkpoint_sha256'] == hashlib.sha256(before).hexdigest()
    assert r.checkpoint.read_bytes() == before
    assert 'file_path' not in json.dumps(report)
    c.token.assert_not_called(); c.recognize.assert_not_called()
    with c.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceRequestDB)) == count
    write_wav(c.wav, seconds=22)
    with pytest.raises(ValueError):
        c.service.preflight_parent('alice', r.receipt.task_id, c.wav)


def test_new_lease_seeds_twenty_parts_fsynced_before_policy_and_sends_only_remaining(failed_parent, monkeypatch):
    from app.services.asr_checkpoint_lock import checkpoint_lock
    r, c = failed_parent, failed_parent.c
    _, body = confirmation(r)
    before = r.checkpoint.read_bytes()
    global_before = (c.donor / 'recognition.json').read_bytes()
    background = BackgroundTasks()
    receipt = c.service.accept('alice', r.receipt.task_id, body, background, Mock())
    child = c.artifacts.find_task_dir(receipt.task_id)
    reference = json.loads((child / 'source_reference.json').read_text())
    assert reference['parent_task_id'] == c.parent
    assert not (child / 'media').exists() and len(background.tasks) == 1
    fsynced = []
    real_fsync = os.fsync
    def fsync(fd):
        real_fsync(fd)
        fsynced.append(os.fstat(fd).st_ino)
    monkeypatch.setattr(os, 'fsync', fsync)
    def policy(_):
        checkpoint = child / 'transcription_chunks' / 'vilab_stream' / 'recognition.json'
        record = json.loads(checkpoint.read_text())
        assert checkpoint.stat().st_ino in fsynced
        assert len(record['completed']) == 20
        assert record['seed']['confirmed_end_frame'] == r.end_frame
        assert record['seed']['checkpoint_sha256'] == hashlib.sha256(before).hexdigest()
        assert record['seed']['donor_task_id'] == r.receipt.task_id
        assert record['execution']['task_id'] == receipt.task_id
        assert record['execution']['parent_task_id'] == r.receipt.task_id
        assert 'inflight' not in record and 'plan' not in record
        with pytest.raises(ValueError):
            with checkpoint_lock(r.checkpoint.parent):
                pytest.fail('Parent lock must remain held during new execution')
        return RecordedAudioPolicy(64000)
    c.policy.side_effect = policy
    c.recognize.side_effect = None
    c.recognize.return_value = {'text': 'last confirmed interval', 'language': 'zh'}
    outcomes = []
    def dispatch(*_):
        outcomes.append(c.adapter._transcribe_stream(str(c.wav)))
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    assert len(outcomes) == 1, c.artifacts.get_status(receipt.task_id)
    assert [(call.kwargs['start'], call.kwargs['end']) for call in c.recognize.call_args_list] == [(r.end_frame / 16000, 21)]
    saved = json.loads((child / 'transcription_chunks' / 'vilab_stream' / 'recognition.json').read_text())
    assert len(saved['completed']) == 21 and saved['plan']['intervals'] == [[r.end_frame, 336000]]
    assert r.checkpoint.read_bytes() == before
    assert (c.donor / 'recognition.json').read_bytes() == global_before
    assert current_execution() is None
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    c.original.unlink()
    duplicate_queue = BackgroundTasks()
    duplicate = c.service.accept('alice', r.receipt.task_id, body, duplicate_queue, dispatch)
    assert duplicate.task_id == receipt.task_id and not duplicate_queue.tasks
    assert c.recognize.call_count == 1


@pytest.mark.parametrize('damage', ['donor_tmp', 'donor_corrupt', 'donor_stamp', 'donor_empty_proof',
    'different_wav', 'child_reference', 'child_intent_canonical', 'db_fingerprint', 'db_reserved'])
def test_v2_rechecks_before_send_and_cannot_fall_back_to_global(failed_parent, damage):
    from app.db_models import SourceRequestDB
    r, c = failed_parent, failed_parent.c
    _, body = confirmation(r)
    receipt = c.service.accept('alice', r.receipt.task_id, body, BackgroundTasks(), Mock())
    child = c.artifacts.find_task_dir(receipt.task_id)
    if damage == 'donor_tmp': r.checkpoint.with_suffix('.tmp').write_text('uncommitted')
    elif damage == 'donor_corrupt': r.checkpoint.write_text('{')
    elif damage in {'donor_stamp', 'donor_empty_proof'}:
        record = json.loads(r.checkpoint.read_text())
        if damage == 'donor_stamp': record['execution']['normalized_identity'] = '0' * 64
        else: next(p for p in record['completed'] if 'terminal_evidence' in p)['terminal_evidence']['inputComplete'] = False
        c.artifacts.write_json(r.checkpoint, record)
    elif damage == 'different_wav': write_wav(c.wav, seconds=22)
    elif damage == 'child_reference':
        ref = json.loads((child / 'source_reference.json').read_text())
        c.artifacts.write_json(child / 'source_reference.json', {**ref, 'parent_task_id': r.receipt.task_id})
    elif damage == 'child_intent_canonical':
        link = json.loads((child / 'new_generation.json').read_text())
        c.artifacts.write_json(child / 'new_generation.json', {**link, 'canonical_task_id': str(uuid.uuid4())})
    else:
        with c.sessions() as db:
            row = db.get(SourceRequestDB, ('alice', str(body.operation_id)))
            if damage == 'db_fingerprint': row.fingerprint = '0' * 64
            else: row.state = 'reserved'
    before = r.checkpoint.read_bytes()
    c.service.run_once(receipt.task_id, 'alice', lambda *_: c.adapter._transcribe_stream(str(c.wav)))
    c.token.assert_not_called()
    c.recognize.assert_not_called()
    assert r.checkpoint.read_bytes() == before
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'failed'


def test_v2_http_endpoint_and_missing_confirmation_are_bounded(failed_parent, monkeypatch):
    from app.routers import note
    r, c = failed_parent, failed_parent.c
    monkeypatch.setattr(note, '_source_requests', c.receipts)
    dispatch = Mock()
    monkeypatch.setattr(note, '_run_task_from_file', dispatch)
    monkeypatch.setattr(note, '_ACTIVE_FILE_TASKS', set())
    app = FastAPI(); app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='alice')
    client = TestClient(app)
    context_url = '/api/task/' + r.receipt.task_id + '/new-generation-context'
    response = client.get(context_url)
    assert response.status_code == 200 and response.json()['canonical_task_id'] == c.parent
    ctx = response.json()
    body = {'operation_id': str(uuid.uuid4()), 'confirmed': True,
        'canonical_task_id': ctx['canonical_task_id'], 'context_revision': ctx['context_revision'],
        'source_version': ctx['source']['version']}
    url = context_url.removesuffix('-context')
    assert client.post(url, json={**body, 'confirmed': False}).status_code == 422
    assert client.post(url, json={**body, 'parent_prefix': {
        'checkpoint_sha256': '0' * 64, 'confirmed_end_frame': 1}}).status_code == 422
    assert client.post(url, json={**body, 'canonical_task_id': str(uuid.uuid4())}).status_code == 409
    result = client.post(url, json=body)
    assert result.status_code == 200 and dispatch.call_count == 1
    assert client.post(url, json=body).json()['task_id'] == result.json()['task_id']
    assert dispatch.call_count == 1
    c.recognize.assert_not_called()


def truncate_parent(r):
    record = json.loads(r.checkpoint.read_text())
    record['completed'] = record['completed'][:10]
    # Keep the accepted DB receipt, failed status and execution stamp identical.
    # The later unknown tail remains nonoverlapping and structurally valid.
    r.c.artifacts.write_json(r.checkpoint, record)


def test_get_then_shortened_confirmed_prefix_cannot_be_accepted(failed_parent):
    r, c = failed_parent, failed_parent.c
    _, body = confirmation(r)
    truncate_parent(r)
    background = BackgroundTasks()
    with pytest.raises(HTTPException) as rejected:
        c.service.accept('alice', r.receipt.task_id, body, background, Mock())
    assert rejected.value.status_code == 409
    with pytest.raises(HTTPException) as absent:
        c.receipts.get('alice', str(body.operation_id))
    assert absent.value.status_code == 404
    assert not background.tasks
    c.token.assert_not_called(); c.recognize.assert_not_called()


@pytest.mark.parametrize('when', ['before_claim', 'after_lease', 'after_lease_and_forged_link'])
def test_post_then_shortened_parent_prefix_cannot_dispatch_or_seed(failed_parent, when):
    r, c = failed_parent, failed_parent.c
    _, body = confirmation(r)
    receipt = c.service.accept('alice', r.receipt.task_id, body, BackgroundTasks(), Mock())
    if when == 'before_claim': truncate_parent(r)
    reached = []
    def dispatch(*_):
        reached.append(True)
        if when.startswith('after_lease'):
            truncate_parent(r)
        if when == 'after_lease_and_forged_link':
            path = c.artifacts.find_task_dir(receipt.task_id) / 'new_generation.json'
            link = json.loads(path.read_text())
            changed = json.loads(r.checkpoint.read_text())
            link['parent_prefix'] = {'checkpoint_sha256': hashlib.sha256(r.checkpoint.read_bytes()).hexdigest(),
                'confirmed_end_frame': round(changed['completed'][-1]['end'] * 16000)}
            c.artifacts.write_json(path, link)
        c.adapter._transcribe_stream(str(c.wav))
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    if when == 'before_claim': assert not reached
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'failed'
    c.token.assert_not_called(); c.recognize.assert_not_called()


def test_same_end_frame_with_changed_confirmed_text_changes_context_revision(failed_parent):
    from app.services.task_new_generation import _submission
    from app.services.source_request_service import _fingerprint
    r, c = failed_parent, failed_parent.c
    context, body = confirmation(r)
    record = json.loads(r.checkpoint.read_text())
    record['completed'][0]['text'] = 'different confirmed content'
    c.artifacts.write_json(r.checkpoint, record)
    changed = frozen_generation_context('alice', r.receipt.task_id, receipts=c.receipts)
    assert changed['context_revision'] != context['context_revision']
    changed_body = body.model_copy(update={'context_revision': changed['context_revision']})
    assert _fingerprint(_submission(r.receipt.task_id, body)) != _fingerprint(_submission(r.receipt.task_id, changed_body))
    with pytest.raises(HTTPException) as rejected:
        c.service.accept('alice', r.receipt.task_id, body, BackgroundTasks(), Mock())
    assert rejected.value.status_code == 409
    c.token.assert_not_called(); c.recognize.assert_not_called()


@pytest.mark.parametrize('kind', ['missing', 'revoked'])
def test_v2_pipeline_rejects_missing_or_revoked_live_lease(failed_parent, kind):
    from app.services.asr_execution_binding import _execution
    from app.services.note_service import NoteService
    r, c = failed_parent, failed_parent.c
    _, body = confirmation(r)
    receipt = c.service.accept('alice', r.receipt.task_id, body, BackgroundTasks(), Mock())
    child = c.artifacts.find_task_dir(receipt.task_id)
    pipeline = NoteService()
    pipeline.transcription_service.transcribe = Mock(side_effect=AssertionError('No ASR without a live lease'))
    rejected = []
    def dispatch(*_):
        binding = current_execution()
        token = _execution.set(None) if kind == 'missing' else None
        if kind == 'revoked': binding._live[0] = False
        try:
            context = SimpleNamespace(preloaded_transcript=None, user_id='alice', task_id=receipt.task_id,
                task_dir=child, audio_meta=SimpleNamespace(file_path=str(c.original)))
            with pytest.raises(ValueError): pipeline._transcribe_audio(context)
            rejected.append(True)
        finally:
            if token is not None: _execution.reset(token)
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    assert rejected == [True]
    pipeline.transcription_service.transcribe.assert_not_called()
    c.token.assert_not_called(); c.recognize.assert_not_called()


def test_v2_seed_fsync_failure_prevents_policy_and_audio(failed_parent, monkeypatch):
    r, c = failed_parent, failed_parent.c
    _, body = confirmation(r)
    receipt = c.service.accept('alice', r.receipt.task_id, body, BackgroundTasks(), Mock())
    child = c.artifacts.find_task_dir(receipt.task_id)
    temporary = child / 'transcription_chunks' / 'vilab_stream' / 'recognition.tmp'
    real_fsync = os.fsync
    failed = []
    def fsync(fd):
        if temporary.exists() and os.fstat(fd).st_ino == temporary.stat().st_ino:
            failed.append(True)
            raise OSError('Synthetic seed flush failure')
        return real_fsync(fd)
    monkeypatch.setattr(os, 'fsync', fsync)
    before = r.checkpoint.read_bytes()
    c.service.run_once(receipt.task_id, 'alice', lambda *_: c.adapter._transcribe_stream(str(c.wav)))
    assert failed == [True]
    c.policy.assert_not_called(); c.token.assert_not_called(); c.recognize.assert_not_called()
    assert r.checkpoint.read_bytes() == before
