"""Offline authorization and checkpoint isolation, using the real operation service."""
import json
import hashlib
import socket
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.test_new_generation_operation import case, accept
from app.db_models import SourceRequestDB
from app.config import settings
from app.services.asr_execution_binding import current_execution, require_task_execution
from app.services.asr_checkpoint_lock import checkpoint_lock
from app.services.adaptive_asr_policy import RecordedAudioPolicy
from app.services.asr_stream_service import ASRServiceError
from app.services.vilab_cloud_service import VILabCloudService
from app.transcribers.vilab_transcriber import VILabTranscriber
from tests.test_adaptive_asr_policy import write_wav

_REAL_STATUS = VILabCloudService.status


@pytest.fixture
def tmp_path(tmp_path_factory):
    # Keep nested checkpoint paths below legacy Windows MAX_PATH. The default
    # per-test descriptive directory consumes most of that limit on this host.
    return tmp_path_factory.mktemp('asr')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Offline tests must not connect to any provider')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def run(c, function):
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    results, errors = [], []
    def dispatch(*args):
        try:
            results.append(function(*args))
        except BaseException as error:
            errors.append(error)
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    assert current_execution() is None
    if errors:
        raise errors[0]
    assert len(results) == 1, c.artifacts.get_status(receipt.task_id)
    return results[0], child


def identity(path, owner='alice', origin='https://original.invalid', model='original-asr'):
    result = hashlib.sha256(json.dumps([origin, owner, model], ensure_ascii=False).encode())
    result.update(path.read_bytes())
    return result.hexdigest()


@pytest.fixture
def audio_case(case, monkeypatch):
    c = case
    monkeypatch.setattr(settings, 'data_dir', c.tmp_path / 'data')
    settings.data_dir.mkdir()
    c.wav = write_wav(c.tmp_path / 'normalized.wav', seconds=3)
    c.donor = settings.data_dir / 'asr-stream-checkpoints' / identity(c.wav)
    c.donor.mkdir(parents=True)
    c.parts = [{'start': 0, 'end': 1, 'text': 'saved', 'language': 'zh', 'segments': []}]
    c.old = {'completed': c.parts, 'inflight': {'start_frame': 16000, 'end_frame': 48000},
             'plan': {'never': 'import this plan'}}
    c.artifacts.write_json(c.donor / 'recognition.json', c.old)
    c.adapter = VILabTranscriber('https://original.invalid', '', 'original-asr', cloud_user_id='alice')
    c.token = Mock(return_value='offline-test-token')
    c.policy = Mock(return_value=RecordedAudioPolicy(64000))
    c.recognize = Mock(return_value={'text': 'new', 'language': 'zh'})
    monkeypatch.setattr(VILabTranscriber, '_recognition_bearer', c.token)
    monkeypatch.setattr(VILabTranscriber, '_recorded_audio_policy', c.policy)
    monkeypatch.setattr('app.services.asr_stream_service.recognize_pcm', c.recognize)
    return c


@pytest.mark.parametrize('change', ['missing_db', 'reserved', 'task', 'fingerprint', 'child_model',
                                  'operation', 'revision', 'parent', 'source_version', 'child_llm'])
def test_first_claim_requires_accepted_matching_db_record(case, change):
    c = case
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    with c.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', str(c.confirmation.operation_id)))
        if change == 'missing_db':
            db.delete(row)
        elif change == 'reserved':
            row.state = 'reserved'
        elif change == 'task':
            row.task_id = c.parent
        elif change == 'fingerprint':
            row.fingerprint = '0' * 64
    if change in {'child_model', 'child_llm'}:
        from app.services.task_model_source import SNAPSHOT_FILE
        key = 'asr_model' if change == 'child_model' else 'llm_model'
        c.artifacts.write_json(child / SNAPSHOT_FILE, {**c.snapshot, key: 'forged'})
    elif change in {'operation', 'revision', 'parent', 'source_version'}:
        link = json.loads((child / 'new_generation.json').read_text())
        key = {'operation': 'operation_id', 'revision': 'context_revision',
               'parent': 'parent_task_id', 'source_version': 'source_version'}[change]
        link[key] = (c.parent if change == 'operation' else receipt.task_id) if change in {'operation', 'parent'} else 'a' * 64
        c.artifacts.write_json(child / 'new_generation.json', link)
    dispatch = Mock()
    c.service.run_once(receipt.task_id, 'alice', dispatch)
    assert not dispatch.called
    assert (child / 'new_generation_started').exists()


def test_seed_is_durable_before_plan_and_reports_initial_confirmed_progress(audio_case):
    c = audio_case
    old_bytes = (c.donor / 'recognition.json').read_bytes()
    progress = []
    c.adapter.progress_callback = lambda *args: progress.append(args)
    def policy(_bearer):
        binding = current_execution()
        path = next(binding.chunks.glob('vilab_stream/recognition.json'))
        seed = json.loads(path.read_text())
        assert seed['completed'] == c.parts
        assert 'plan' not in seed and 'inflight' not in seed
        assert progress == [(1, 3, 1)]
        # Donor mutex stays held beyond the seed read, through new submissions.
        with pytest.raises(ValueError):
            with checkpoint_lock(c.donor):
                pytest.fail('donor lock was released too soon')
        return RecordedAudioPolicy(64000)
    c.policy.side_effect = policy
    result, child = run(c, lambda *_: c.adapter._transcribe_stream(str(c.wav)))
    assert result.full_text == 'saved\nnew'
    calls = c.recognize.call_args_list
    assert [(x.kwargs['start'], x.kwargs['end']) for x in calls] == [(1, 3)]
    saved = json.loads(next(child.glob('transcription_chunks/vilab_stream/recognition.json')).read_text())
    assert saved['seed']['confirmed_end_frame'] == 16000
    assert saved['plan']['intervals'][0][0] == 16000
    assert saved['execution']['operation_id'] == str(c.confirmation.operation_id)
    assert 'inflight' not in saved
    assert (c.donor / 'recognition.json').read_bytes() == old_bytes
    with pytest.raises(ASRServiceError):
        c.adapter._transcribe_stream(str(c.wav))  # Old operation remains unknown.
    assert c.recognize.call_count == 1


def test_full_confirmed_seed_needs_no_catalog_token_or_asr(audio_case):
    c = audio_case
    c.parts[0]['end'] = 3
    c.artifacts.write_json(c.donor / 'recognition.json', {'completed': c.parts})
    result, _ = run(c, lambda *_: c.adapter._transcribe_stream(str(c.wav)))
    assert result.full_text == 'saved'
    c.token.assert_not_called(); c.policy.assert_not_called(); c.recognize.assert_not_called()


@pytest.mark.parametrize('donor_state', ['busy', 'corrupt'])
def test_complete_child_cache_ignores_later_unavailable_donor(audio_case, monkeypatch, donor_state):
    c = audio_case
    def process(*_):
        first = c.adapter._transcribe_stream(str(c.wav))
        child = current_execution().chunks / 'vilab_stream' / 'recognition.json'
        before = child.read_bytes()
        c.token.reset_mock(); c.policy.reset_mock(); c.recognize.reset_mock()
        read_donor = Mock(side_effect=AssertionError('complete child must not read donor'))
        monkeypatch.setattr('app.transcribers.vilab_transcriber._read_donor', read_donor)
        if donor_state == 'busy':
            with checkpoint_lock(c.donor):
                result = c.adapter._transcribe_stream(str(c.wav))
        else:
            (c.donor / 'recognition.json').write_bytes(b'{corrupt')
            result = c.adapter._transcribe_stream(str(c.wav))
        assert result.full_text == first.full_text == 'saved\nnew'
        assert child.read_bytes() == before
        read_donor.assert_not_called()
        c.token.assert_not_called(); c.policy.assert_not_called(); c.recognize.assert_not_called()
    run(c, process)


@pytest.mark.parametrize('mismatch', ['stamp', 'normalized_identity'])
def test_complete_child_cache_still_rejects_execution_or_wav_mismatch(audio_case, mismatch):
    c = audio_case
    other = write_wav(c.tmp_path / 'different-complete.wav', seconds=2)
    def process(*_):
        c.adapter._transcribe_stream(str(c.wav))
        child = current_execution().chunks / 'vilab_stream' / 'recognition.json'
        if mismatch == 'stamp':
            saved = json.loads(child.read_text())
            saved['execution']['operation_id'] = c.parent
            c.artifacts.write_json(child, saved)
        before = child.read_bytes()
        c.token.reset_mock(); c.policy.reset_mock(); c.recognize.reset_mock()
        with checkpoint_lock(c.donor), pytest.raises(ValueError):
            c.adapter._transcribe_stream(str(other if mismatch == 'normalized_identity' else c.wav))
        assert child.read_bytes() == before
        c.token.assert_not_called(); c.policy.assert_not_called(); c.recognize.assert_not_called()
    run(c, process)


@pytest.mark.parametrize('damage', ['sentinel', 'busy', 'json', 'gap', 'overlap', 'fractional',
                                  'bool', 'nan', 'inflight_overlap', 'oversized', 'uncommitted'])
def test_unsafe_donor_blocks_instead_of_restarting_at_zero(audio_case, damage):
    c = audio_case
    if damage == 'sentinel':
        (c.donor / 'recognition.lock').write_bytes(b'preserve')
    elif damage == 'json':
        (c.donor / 'recognition.json').write_text('{')
    elif damage == 'gap':
        c.old['completed'][0]['start'] = 0.1
    elif damage == 'overlap':
        c.old['completed'].append({**c.parts[0], 'start': 0.5, 'end': 1.5})
    elif damage == 'fractional':
        c.old['completed'][0]['end'] = 1 + 0.5 / 16000
    elif damage == 'bool':
        c.old['completed'][0]['start'] = False
    elif damage == 'nan':
        c.old['completed'][0]['end'] = float('nan')
    elif damage == 'inflight_overlap':
        c.old['inflight']['start_frame'] = 100
    elif damage == 'oversized':
        with (c.donor / 'recognition.json').open('wb') as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    elif damage == 'uncommitted':
        (c.donor / 'recognition.tmp').write_bytes(b'uncertain')
    if damage in {'gap', 'overlap', 'fractional', 'bool', 'nan', 'inflight_overlap'}:
        c.artifacts.write_json(c.donor / 'recognition.json', c.old)
    original = (c.donor / 'recognition.json').read_bytes()
    def blocked(*_):
        if damage == 'busy':
            with checkpoint_lock(c.donor), pytest.raises(ValueError):
                c.adapter._transcribe_stream(str(c.wav))
        else:
            with pytest.raises(ValueError):
                c.adapter._transcribe_stream(str(c.wav))
    run(c, blocked)
    c.recognize.assert_not_called(); c.token.assert_not_called(); c.policy.assert_not_called()
    assert (c.donor / 'recognition.json').read_bytes() == original
    if damage == 'sentinel':
        assert (c.donor / 'recognition.lock').read_bytes() == b'preserve'


def test_same_operation_unknown_is_not_reseeded_or_replayed(audio_case):
    c = audio_case
    c.recognize.side_effect = ASRServiceError('unknown_result')
    seen = []
    def process(*_):
        with pytest.raises(ASRServiceError):
            c.adapter._transcribe_stream(str(c.wav))
        path = next(current_execution().chunks.glob('vilab_stream/recognition.json'))
        before = path.read_bytes()
        with pytest.raises(ASRServiceError):
            c.adapter._transcribe_stream(str(c.wav))
        assert path.read_bytes() == before
        seen.append(before)
    _, child = run(c, process)
    c.service.run_once(child.name, 'alice', Mock(side_effect=AssertionError('no new claim')))
    assert c.recognize.call_count == 1 and len(seen) == 1
    saved = json.loads(seen[0])
    assert saved['completed'] == c.parts and saved['inflight']['start_frame'] == 16000


def test_unknown_cannot_escape_namespace_by_changing_normalized_wav(audio_case):
    c = audio_case
    other = write_wav(c.tmp_path / 'other.wav', seconds=2)
    c.recognize.side_effect = ASRServiceError('unknown_result')
    def process(*_):
        with pytest.raises(ASRServiceError):
            c.adapter._transcribe_stream(str(c.wav))
        path = current_execution().chunks / 'vilab_stream' / 'recognition.json'
        before = path.read_bytes()
        with pytest.raises(ValueError):
            c.adapter._transcribe_stream(str(other))
        assert path.read_bytes() == before
        assert len(list(current_execution().chunks.glob('vilab_stream/recognition.json'))) == 1
    run(c, process)
    assert c.recognize.call_count == 1


def test_donor_safety_failure_reports_preserved_original_without_internal_terms(audio_case):
    c = audio_case
    (c.donor / 'recognition.lock').write_bytes(b'keep')
    receipt, _ = accept(c)
    c.service.run_once(receipt.task_id, 'alice', lambda *_: c.adapter._transcribe_stream(str(c.wav)))
    status = c.artifacts.get_status(receipt.task_id)
    assert status['status'] == 'failed' and status['retryable'] is False
    assert '原文件与记录已保留' in status['message']
    assert not any(word in status['message'] for word in ('donor', 'namespace', 'seed', 'lock', 'recognition'))
    c.recognize.assert_not_called()


def test_seed_flush_failure_prevents_plan_and_audio(audio_case, monkeypatch):
    c = audio_case
    def process(*_):
        with monkeypatch.context() as local:
            local.setattr('app.transcribers.vilab_transcriber.os.fsync', Mock(side_effect=OSError('disk full')))
            with pytest.raises(OSError):
                c.adapter._transcribe_stream(str(c.wav))
    run(c, process)
    c.policy.assert_not_called(); c.recognize.assert_not_called()


@pytest.mark.parametrize('change', ['owner', 'origin', 'model'])
def test_bound_adapter_cannot_use_other_identity(audio_case, change):
    c = audio_case
    def process(*_):
        setattr(c.adapter, {'owner': 'cloud_user_id', 'origin': 'base_url', 'model': 'model'}[change], 'other')
        with pytest.raises(ValueError):
            c.adapter._transcribe_stream(str(c.wav))
    run(c, process)
    c.recognize.assert_not_called()


def test_copy_context_worker_has_binding_and_lease_revokes_after_dispatch(audio_case):
    c = audio_case
    copies = []
    def process(task, request, owner):
        binding = current_execution()
        copies.append(copy_context())
        with ThreadPoolExecutor(max_workers=1) as pool:
            def recognize():
                assert current_execution() is binding
                return c.adapter._transcribe_stream(str(c.wav))
            result = pool.submit(copy_context().run, recognize).result(timeout=10)
        assert result.full_text.startswith('saved')
        with pytest.raises(ValueError):
            require_task_execution('bob', task, binding.folder, c.original)
        with pytest.raises(ValueError):
            require_task_execution(owner, c.parent, binding.folder, c.original)
        with pytest.raises(ValueError):
            binding.validate(chunks=c.tmp_path / 'foreign')
        raise RuntimeError('dispatch failed after confirmed results')
    with pytest.raises(RuntimeError):
        run(c, process)
    assert current_execution() is None
    with pytest.raises(ValueError):
        copies[0].run(current_execution)


def test_disk_json_without_runtime_binding_cannot_enter_transcription_cache(audio_case):
    from app.services.transcription_service import TranscriptionService
    c = audio_case
    receipt, _ = accept(c)
    child = c.artifacts.find_task_dir(receipt.task_id)
    read_cache = Mock()
    with pytest.raises(ValueError):
        TranscriptionService().transcribe(audio_path=str(c.original), user_id='alice',
            load_cached=read_cache, save_transcript=Mock(), chunk_cache_dir=child / 'transcription_chunks')
    read_cache.assert_not_called()


def test_changed_normalized_wav_does_not_borrow_same_raw_source_prefix(audio_case):
    c = audio_case
    other = write_wav(c.tmp_path / 'different.wav', seconds=2)
    result, _ = run(c, lambda *_: c.adapter._transcribe_stream(str(other)))
    assert result.full_text == 'new'
    assert c.recognize.call_args_list[0].kwargs['start'] == 0
    assert c.artifacts._sha256(c.original) == c.confirmation.source_version


def test_binding_authorization_is_read_only_and_first_claim_only(audio_case, monkeypatch):
    c = audio_case
    receipt, _ = accept(c)
    getter = Mock(wraps=c.receipts.get)
    monkeypatch.setattr(c.receipts, 'get', getter)
    monkeypatch.setattr(c.receipts, 'reserve', Mock(side_effect=AssertionError('must not reserve')))
    captured = []
    c.service.run_once(receipt.task_id, 'alice', lambda *_: captured.append(current_execution()))
    c.service.run_once(receipt.task_id, 'alice', lambda *_: pytest.fail('claimed twice'))
    assert getter.call_count == 1 and len(captured) == 1
    assert captured[0].operation == str(c.confirmation.operation_id)
    assert current_execution() is None


def test_only_another_accepted_operation_can_get_another_namespace(audio_case):
    import uuid
    c = audio_case
    c.recognize.side_effect = ASRServiceError('unknown_result')
    def process(*_):
        with pytest.raises(ASRServiceError):
            c.adapter._transcribe_stream(str(c.wav))
    _, first = run(c, process)
    old = next(first.glob('transcription_chunks/vilab_stream/recognition.json')).read_bytes()
    c.confirmation = c.confirmation.model_copy(update={'operation_id': uuid.uuid4()})
    c.recognize.side_effect = None
    result, second = run(c, lambda *_: c.adapter._transcribe_stream(str(c.wav)))
    assert first != second and result.full_text == 'saved\nnew'
    assert next(first.glob('transcription_chunks/vilab_stream/recognition.json')).read_bytes() == old
    assert c.recognize.call_count == 2


@pytest.mark.parametrize('change', ['owner', 'task', 'folder', 'source', 'snapshot', 'reference'])
def test_binding_revalidates_pipeline_context_before_cache(audio_case, change):
    c = audio_case
    def process(task, req, owner):
        binding = current_execution()
        if change == 'snapshot':
            from app.services.task_model_source import SNAPSHOT_FILE
            c.artifacts.write_json(binding.folder / SNAPSHOT_FILE, {**c.snapshot, 'llm_model': 'changed'})
        elif change == 'reference':
            ref = json.loads((binding.folder / 'source_reference.json').read_text())
            ref['source_version'] = 'b' * 64
            c.artifacts.write_json(binding.folder / 'source_reference.json', ref)
        with pytest.raises(ValueError):
            require_task_execution('bob' if change == 'owner' else owner,
                c.parent if change == 'task' else task,
                c.folder if change == 'folder' else binding.folder,
                c.wav if change == 'source' else c.original)
    run(c, process)
    c.recognize.assert_not_called()


def test_existing_child_record_cannot_change_execution_stamp(audio_case):
    c = audio_case
    def process(*_):
        c.adapter._transcribe_stream(str(c.wav))
        path = next(current_execution().chunks.glob('vilab_stream/recognition.json'))
        data = json.loads(path.read_text())
        data['execution']['operation_id'] = c.parent
        c.artifacts.write_json(path, data)
        before = path.read_bytes()
        with pytest.raises(ValueError):
            c.adapter._transcribe_stream(str(c.wav))
        assert path.read_bytes() == before
    run(c, process)
    assert c.recognize.call_count == 1


def test_actual_diarization_copy_context_branch_keeps_execution_binding(audio_case, monkeypatch):
    """Exercise the real parallel branch; speaker inference alone is substituted.

    Separate from the full NoteService integration below (ASR/LLM stubs only).
    Audio preprocessing, worker submission and VILab normalization remain real.
    """
    import threading
    from app.services.speaker_diarization_service import SpeakerDiarizationService, SpeakerTurn
    c = audio_case
    monkeypatch.setattr(SpeakerDiarizationService, 'require_ready', classmethod(lambda cls: None))
    models = [c.tmp_path / 'seg.onnx', c.tmp_path / 'embed.onnx']
    for model in models:
        model.write_bytes(b'offline model identity')
    monkeypatch.setattr(SpeakerDiarizationService, 'model_paths', staticmethod(lambda: tuple(models)))
    monkeypatch.setattr('app.services.speaker_worker.run_speaker_worker',
                        lambda *args, **kwargs: ([SpeakerTurn(0, 3, 'speaker_1')], {}))
    threads = []
    parent_thread = threading.get_ident()
    def process(*_):
        binding = current_execution()
        def recognize(path, **kwargs):
            assert current_execution() is binding
            threads.append(threading.get_ident())
            return c.adapter.transcribe(path)
        return SpeakerDiarizationService().transcribe(audio_path=str(c.wav), transcribe=recognize)
    result, child = run(c, process)
    assert threads and all(thread != parent_thread for thread in threads)
    assert result.metadata['analysis_parallel'] is True
    assert list(child.glob('transcription_chunks/vilab_stream/recognition.json'))


def test_real_note_pipeline_uses_seed_and_submits_only_remaining_audio(audio_case, monkeypatch):
    """Real run_once -> NoteService -> TranscriptionService -> ffmpeg -> planner.

    Only external ASR, authentication/catalog readiness and chat responses are
    replaced. No _run_pipeline, transcription orchestration or artifact stubs.
    """
    import subprocess
    from app.services.note_service import NoteService
    from app.services.task_generation_context import frozen_generation_context
    from app.services.task_new_generation import NewGenerationConfirmation
    c = audio_case
    # Replace the parent media with real WAV, rebuild the server-hashed context.
    c.original.write_bytes(c.wav.read_bytes())
    c.artifacts.record_source_media(c.folder, c.original, media_kind='audio')
    context = frozen_generation_context('alice', c.parent)
    c.confirmation = NewGenerationConfirmation(operation_id=c.confirmation.operation_id, confirmed=True,
        context_revision=context['context_revision'], source_version=context['source']['version'])
    normalized = c.tmp_path / 'ffmpeg-donor.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-y', '-loglevel', 'error', '-i', str(c.original),
                    '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(normalized)], check=True)
    donor = settings.data_dir / 'asr-stream-checkpoints' / identity(normalized)
    donor.mkdir(parents=True, exist_ok=True)
    c.artifacts.write_json(donor / 'recognition.json', c.old)
    before = (donor / 'recognition.json').read_bytes()
    monkeypatch.setattr(VILabCloudService, 'status', _REAL_STATUS)
    monkeypatch.setattr(settings, 'meeting_review_model', '')
    chats = []
    def response(_self, owner, method, endpoint, **kwargs):
        assert owner == 'alice' and method == 'POST' and endpoint == '/openai/v1/chat/completions'
        assert kwargs['json']['model'] == 'original-llm'
        chats.append(kwargs['json'])
        return {'choices': [{'message': {'content': '# 离线纪要\n\n已核验的正文。'}}]}
    monkeypatch.setattr(VILabCloudService, 'request', response)
    outputs = []
    def pipeline(task, req, owner):
        service = NoteService(artifact_service=c.artifacts)
        options = req.model_dump(exclude={'workflow'})
        outputs.append(service.generate_from_file(task_id=task, user_id=owner, **options))
    _, child = run(c, pipeline)
    assert len(outputs) == 1 and chats
    assert c.artifacts.get_status(child.name)['status'] == 'success'
    assert (child / 'transcript.json').is_file() and (child / 'note.md').is_file() and (child / 'result.json').is_file()
    assert not (child / 'media').exists()
    assert outputs[0].transcript.full_text == 'saved\nnew'
    assert [call.kwargs['start'] for call in c.recognize.call_args_list] == [1]
    assert all(call.args[2] == 'original-asr' for call in c.recognize.call_args_list)
    assert (donor / 'recognition.json').read_bytes() == before
