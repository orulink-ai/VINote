from pathlib import Path
import hashlib
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import asr_checkpoint_lock as locking
from app.services.asr_stream_service import ASRServiceError
from app.services.cloud_account_service import CloudAccountService
from app.transcribers.vilab_transcriber import VILabTranscriber
from tests.test_adaptive_asr_policy import write_wav

CHILD = Path(__file__).with_name('lock_child.py')


def args(folder, action):
    # Windows venv python.exe may be a launcher with a separate interpreter.
    # Kill the actual interpreter, not just a launcher that leaves its child alive.
    return [getattr(sys, '_base_executable', sys.executable), '-I', '-B',
            str(CHILD), locking.__file__, str(folder), action]


def setup_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', str(tmp_path))
    # Exercise real Origin validation with a synthetic built-in account route;
    # the credential provider and recognition transport stay mocked below.
    monkeypatch.setattr(settings, 'vilab_server_url', 'https://offline.invalid')
    monkeypatch.setattr(settings, 'cloud_auth_url', 'https://identity.invalid')
    monkeypatch.setattr(settings, 'vilab_api_key', '')
    monkeypatch.setattr(settings, 'content_cloud_runtime', False)
    audio = write_wav(tmp_path / 'one.wav', seconds=1)
    adapter = VILabTranscriber('https://offline.invalid', '', 'frozen-model', cloud_user_id='owner')
    identity = hashlib.sha256(json.dumps([adapter.base_url, 'owner', adapter.model],
                                        ensure_ascii=False).encode())
    identity.update(audio.read_bytes())
    folder = tmp_path / 'asr-stream-checkpoints' / identity.hexdigest()
    folder.mkdir(parents=True)
    token = Mock(side_effect=AssertionError('No token refresh is allowed'))
    recognize = Mock(side_effect=AssertionError('No audio replay is allowed'))
    monkeypatch.setattr(CloudAccountService, 'access_token', token)
    monkeypatch.setattr('app.services.asr_stream_service.recognize_pcm', recognize)
    return adapter, audio, folder, token, recognize


def completed(folder):
    (folder / 'recognition.json').write_text(json.dumps({'completed': [
        {'start': 0, 'end': 1, 'text': 'confirmed final', 'language': None, 'segments': []}
    ]}), encoding='utf-8')


def test_actual_subprocess_kill_releases_lock_and_backing_file_stays(tmp_path):
    child = subprocess.Popen(args(tmp_path, 'hold'), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'LOCKED'
        with pytest.raises(ValueError, match='未重复提交'):
            with locking.checkpoint_lock(tmp_path):
                pytest.fail('Concurrent lock accepted')
        child.kill()
        child.wait(timeout=10)
        assert child.returncode != 0
        with locking.checkpoint_lock(tmp_path):
            assert (tmp_path / 'recognition.process.lock').exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def test_actual_second_process_is_excluded_and_normal_exit_releases(tmp_path):
    with locking.checkpoint_lock(tmp_path):
        second = subprocess.run(args(tmp_path, 'probe'), capture_output=True, text=True, timeout=10)
        assert second.returncode == 17 and second.stdout.strip() == 'BUSY'
    second = subprocess.run(args(tmp_path, 'probe'), capture_output=True, text=True, timeout=10)
    assert second.returncode == 0 and second.stdout.strip() == 'LOCKED'


def test_actual_crash_after_final_reuses_cloud_cache_without_token(tmp_path, monkeypatch):
    adapter, audio, folder, token, recognize = setup_cache(tmp_path, monkeypatch)
    child = subprocess.run(args(folder, 'crash-final'), capture_output=True, text=True, timeout=10)
    assert child.returncode == 29 and child.stdout.strip() == 'LOCKED'
    before = (folder / 'recognition.json').read_bytes()
    assert adapter._transcribe_stream(str(audio)).full_text == 'confirmed final'
    assert (folder / 'recognition.json').read_bytes() == before
    token.assert_not_called()
    recognize.assert_not_called()


def test_actual_crash_with_inflight_never_replays_or_refreshes(tmp_path, monkeypatch):
    adapter, audio, folder, token, recognize = setup_cache(tmp_path, monkeypatch)
    child = subprocess.run(args(folder, 'crash-inflight'), capture_output=True, timeout=10)
    assert child.returncode == 29
    before = (folder / 'recognition.json').read_bytes()
    for _ in range(2):
        with pytest.raises(ASRServiceError) as caught:
            adapter._transcribe_stream(str(audio))
        assert caught.value.code == 'unknown_result' and caught.value.retry_reason is None
    assert (folder / 'recognition.json').read_bytes() == before
    token.assert_not_called()
    recognize.assert_not_called()


@pytest.mark.parametrize('has_final', [False, True])
def test_legacy_sentinel_never_reclaimed_even_with_full_final(tmp_path, monkeypatch, has_final):
    adapter, audio, folder, token, recognize = setup_cache(tmp_path, monkeypatch)
    if has_final:
        completed(folder)
    sentinel = folder / 'recognition.lock'
    sentinel.write_bytes(b'legacy unknown evidence')
    for _ in range(2):
        with pytest.raises(ASRServiceError) as caught:
            adapter._transcribe_stream(str(audio))
        assert caught.value.code == 'unknown_result'
    assert sentinel.read_bytes() == b'legacy unknown evidence'
    assert (folder / 'recognition.json').exists() == has_final
    token.assert_not_called()
    recognize.assert_not_called()


def test_completed_cloud_cache_never_fetches_policy_or_token(tmp_path, monkeypatch):
    adapter, audio, folder, token, recognize = setup_cache(tmp_path, monkeypatch)
    completed(folder)
    catalog = Mock(side_effect=AssertionError('No catalog request is allowed'))
    monkeypatch.setattr(adapter, '_recorded_audio_policy', catalog)
    assert adapter._transcribe_stream(str(audio)).full_text == 'confirmed final'
    token.assert_not_called()
    catalog.assert_not_called()
    recognize.assert_not_called()


@pytest.mark.parametrize('field,value', [('model', 'other-model'),
    ('base_url', 'https://other.invalid'), ('cloud_user_id', 'other-owner')])
def test_complete_cache_not_reused_for_changed_identity(tmp_path, monkeypatch, field, value):
    adapter, audio, folder, token, recognize = setup_cache(tmp_path, monkeypatch)
    completed(folder)
    before = (folder / 'recognition.json').read_bytes()
    setattr(adapter, field, value)
    if field == 'base_url':
        # A cache miss never grants another Origin the account's credentials.
        with pytest.raises(HTTPException) as caught:
            adapter._transcribe_stream(str(audio))
        assert caught.value.status_code == 409
        token.assert_not_called()
    else:
        with pytest.raises(AssertionError, match='No token refresh'):
            adapter._transcribe_stream(str(audio))
        token.assert_called_once_with(adapter.cloud_user_id)
    assert (folder / 'recognition.json').read_bytes() == before
    recognize.assert_not_called()


def test_remaining_audio_refreshes_token_and_keeps_selected_model(tmp_path, monkeypatch):
    from app.services.adaptive_asr_policy import RecordedAudioPolicy
    adapter, audio, folder, token, recognize = setup_cache(tmp_path, monkeypatch)
    token.side_effect = ['policy-token', 'fresh-submit-token']
    recognize.side_effect = None
    recognize.return_value = {'text': 'new confirmed final'}
    catalog = Mock(return_value=RecordedAudioPolicy(32000))
    monkeypatch.setattr(adapter, '_recorded_audio_policy', catalog)
    assert adapter._transcribe_stream(str(audio)).full_text == 'new confirmed final'
    catalog.assert_called_once_with('policy-token')
    assert recognize.call_args.args[:3] == ('https://offline.invalid', 'fresh-submit-token', 'frozen-model')
    assert token.call_count == 2
    assert all(call.args == ('owner',) for call in token.call_args_list)
