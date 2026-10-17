import importlib.util
import json
from pathlib import Path
import queue
import sys
from types import SimpleNamespace
import multiprocessing
import os
import time

import pytest


from app.services import speaker_worker as worker


def payload(duration=1):
    return {'protocol': 1, 'duration': duration, 'turns': [
        {'start': 0, 'end': duration, 'speaker_id': 'speaker_1'}], 'clustering': {}}


@pytest.mark.parametrize('change', [
    {'protocol': 2}, {'duration': 2}, {'turns': []}, {'clustering': []},
    {'turns': [{'start': 0, 'end': float('nan'), 'speaker_id': 'speaker_1'}]},
    {'turns': [{'start': 0, 'end': 2, 'speaker_id': 'speaker_1'}]},
    {'turns': [{'start': 0, 'end': 1, 'speaker_id': 'account_or_text'}]},
    {'turns': [{'start': 0, 'end': 1, 'speaker_id': 'speaker_1', 'text': 'forbidden'}]},
    {'turns': [{'start': 0, 'end': 0.8, 'speaker_id': 'speaker_1'},
               {'start': 0.5, 'end': 1, 'speaker_id': 'speaker_2'}]},
])
def test_parent_rejects_wrong_or_malformed_evidence(change):
    value = payload()
    value.update(change)
    with pytest.raises(ValueError):
        worker.validate_result(value, 1)


def inputs(tmp_path):
    pcm = tmp_path / 'audio.f32'
    pcm.write_bytes(b'\0' * 64000)
    seg = tmp_path / 'seg.onnx'
    emb = tmp_path / 'emb.onnx'
    seg.touch()
    emb.touch()
    return pcm, seg, emb


def install_process(monkeypatch, tmp_path, mode):
    state = {'alive': False, 'polls': 0, 'terminated': False, 'closed': False}
    class Events:
        def get(self, timeout):
            if mode == 'timeout':
                import time
                time.sleep(timeout)
                raise queue.Empty
            return ('detection', 0.5)
        def cancel_join_thread(self): pass
        def close(self): state['queue_closed'] = True
    class Process:
        pid = 1
        exitcode = 1 if mode == 'death' else 0
        def __init__(self, target, args, daemon):
            request = args[0]
            assert set(request) == {'folder', 'segmentation', 'embedding', 'speaker_count', 'threshold'}
            assert daemon is True
        def start(self):
            state['alive'] = True
            if mode not in {'timeout', 'death'}:
                (tmp_path / 'speaker-result.json').write_text(json.dumps(payload()))
        def is_alive(self):
            state['polls'] += 1
            if mode != 'timeout' and state['polls'] >= 2:
                state['alive'] = False
            return state['alive']
        def join(self, timeout): pass
        def terminate(self):
            state['alive'] = False
            state['terminated'] = True
        def kill(self): self.terminate()
        def close(self): state['closed'] = True
    def context(method):
        assert method == 'spawn'
        return SimpleNamespace(Queue=lambda maxsize: Events(), Process=Process)
    monkeypatch.setattr(worker.multiprocessing, 'get_context', context)
    monkeypatch.setattr(worker, '_windows_job', lambda pid: None)
    return state


@pytest.mark.parametrize('mode', ['success', 'death', 'timeout'])
def test_worker_success_death_timeout_cleanup(tmp_path, monkeypatch, mode):
    args = inputs(tmp_path)
    state = install_process(monkeypatch, tmp_path, mode)
    if mode == 'success':
        turns, _ = worker.run_speaker_worker(*args, None, 0.8)
        assert turns[0].end == 1
    else:
        with pytest.raises(TimeoutError if mode == 'timeout' else RuntimeError):
            worker.run_speaker_worker(*args, None, 0.8, timeout_seconds=0.01)
    assert state['closed'] and state['queue_closed']
    assert not (tmp_path / 'speaker-result.json').exists()
    if mode == 'timeout': assert state['terminated']


def test_callback_failure_cleans_up_worker(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    state = install_process(monkeypatch, tmp_path, 'timeout')
    # Deliver progress while worker is still alive.
    class Events:
        def get(self, timeout): return ('detection', 0.5)
        def close(self): pass
        def cancel_join_thread(self): pass
    old = worker.multiprocessing.get_context('spawn')
    monkeypatch.setattr(worker.multiprocessing, 'get_context', lambda _: SimpleNamespace(Queue=lambda maxsize: Events(), Process=old.Process))
    def cancel(*args): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        worker.run_speaker_worker(*args, None, 0.8, progress=cancel)
    assert state['terminated'] and state['closed']


def test_fresh_speaker_evidence_survives_asr_failure(tmp_path, monkeypatch):
    import numpy as np
    from app.services.speaker_diarization_service import SpeakerDiarizationService, SpeakerTurn
    import app.services.speaker_diarization_service as service
    audio = tmp_path / 'original.wav'
    audio.write_bytes(b'protected original')
    monkeypatch.setattr(SpeakerDiarizationService, 'require_ready', lambda _: None)
    monkeypatch.setattr(SpeakerDiarizationService, 'model_paths', lambda _: (tmp_path/'seg', tmp_path/'emb'))
    monkeypatch.setattr(SpeakerDiarizationService, '_source_signature', lambda *args: {'source': 'fixed'})
    def prepare(source, destination):
        np.zeros(16000, dtype='float32').tofile(destination)
        return {}
    monkeypatch.setattr(service, 'prepare_meeting_audio', prepare)
    calls = []
    def infer(*args, **kwargs):
        calls.append(1)
        return [SpeakerTurn(0, 1, 'speaker_1')], {}
    monkeypatch.setattr(worker, 'run_speaker_worker', infer)
    def fail(*args, **kwargs): raise RuntimeError('asr failure')
    evidence = tmp_path/'evidence'
    for _ in range(2):
        with pytest.raises(RuntimeError, match='asr failure'):
            SpeakerDiarizationService().transcribe(audio_path=str(audio), transcribe=fail, evidence_dir=evidence)
    assert len(calls) == 1
    assert json.loads((evidence/'speaker_evidence.json').read_text())['signature'] == {'source': 'fixed'}
    assert audio.read_bytes() == b'protected original'


def test_source_changed_during_worker_is_not_saved(tmp_path, monkeypatch):
    import numpy as np
    from app.services.speaker_diarization_service import SpeakerDiarizationService, SpeakerTurn
    import app.services.speaker_diarization_service as service
    audio = tmp_path/'original.wav'
    audio.touch()
    monkeypatch.setattr(SpeakerDiarizationService, 'require_ready', lambda _: None)
    monkeypatch.setattr(SpeakerDiarizationService, 'model_paths', lambda _: (tmp_path/'seg', tmp_path/'emb'))
    signatures = iter([{'source': 1}, {'source': 2}])
    monkeypatch.setattr(SpeakerDiarizationService, '_source_signature', lambda *args: next(signatures))
    def prepare(source, destination):
        np.zeros(16000, dtype='float32').tofile(destination)
        return {}
    monkeypatch.setattr(service, 'prepare_meeting_audio', prepare)
    monkeypatch.setattr(worker, 'run_speaker_worker', lambda *args, **kwargs: ([SpeakerTurn(0,1,'speaker_1')],{}))
    def fail(*args, **kwargs): raise RuntimeError('asr failure')
    evidence = tmp_path/'evidence'
    with pytest.raises(ValueError, match='发生变化'):
        SpeakerDiarizationService().transcribe(audio_path=str(audio), transcribe=fail, evidence_dir=evidence)
    assert not (evidence/'speaker_evidence.json').exists()


@pytest.mark.parametrize('mode', ['timeout', 'death'])
def test_real_spawned_process_is_reaped_without_loading_models(tmp_path, monkeypatch, mode):
    args = inputs(tmp_path)
    context = multiprocessing.get_context('spawn')
    children = []
    def process_factory(**kwargs):
        process = context.Process(target=time.sleep if mode == 'timeout' else os._exit,
                                  args=(30,) if mode == 'timeout' else (1,), daemon=True)
        children.append(process)
        return process
    monkeypatch.setattr(worker.multiprocessing, 'get_context', lambda _: SimpleNamespace(
        Queue=context.Queue, Process=process_factory))
    with pytest.raises(TimeoutError if mode == 'timeout' else RuntimeError):
        worker.run_speaker_worker(*args, None, 0.8, timeout_seconds=0.2 if mode == 'timeout' else 10)
    assert not multiprocessing.active_children()
    assert children[0]._closed
    assert not (tmp_path/'speaker-result.json').exists()
