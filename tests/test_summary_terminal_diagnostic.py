"""Offline SSE terminal diagnostics, isolated task persistence and safe recovery."""
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.cloud_chat_stream import collect_chat_stream
from app.services.summary_failure import (
    SUMMARY_UNCONFIRMED_CODE, SUMMARY_UNCONFIRMED_COPY, SummaryResultUnconfirmed,
)
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_failure import failure_details, recovery_status


SECRET = 'SYNTHETIC_SECRET https://invalid.test/private?key=secret'


def context(done=False, finish='missing'):
    return {
        'diagnostic_protocol': 'sse_terminal/1', 'done_seen': done, 'finish': finish,
        'category': ('non_stop_finish' if done else 'missing_done' if finish == 'stop'
                     else 'missing_done_and_non_stop_finish'),
    }


class Stream:
    def __init__(self, finish, done):
        self.finish, self.done = finish, done

    def iter_lines(self):
        yield 'data: ' + json.dumps({'model': SECRET, 'usage': {'private': SECRET},
            'choices': [{'index': 0, 'delta': {'content': SECRET, 'reasoning_content': SECRET},
                         'finish_reason': self.finish}]})
        yield ''
        if self.done:
            yield 'data: [DONE]'
            yield ''


def failure(finish=None, done=False):
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(Stream(finish, done), started=time.monotonic())
    return caught.value


@pytest.mark.parametrize('done', [False, True])
@pytest.mark.parametrize('finish,expected', [
    ('stop', 'stop'), ('length', 'length'), ('content_filter', 'content_filter'),
    ('tool_calls', 'tool_calls'), ('function_call', 'function_call'), (None, 'missing'),
    (SECRET, 'other'), ('', 'other'), (0, 'other'), (False, 'other'),
    ([], 'other'), ({}, 'other'), ({'message': SECRET}, 'other'), (['stop'], 'other'),
    (True, 'other'), ('missing', 'other'), ('other', 'other'),
])
def test_terminal_matrix_never_accepts_non_stop_or_missing_done(done, finish, expected, caplog):
    if done and finish == 'stop':
        result = collect_chat_stream(Stream(finish, done), started=time.monotonic())
        assert result == {'model': SECRET, 'usage': {'private': SECRET}, 'choices': [
            {'message': {'content': SECRET}, 'finish_reason': 'stop'}]}
        return
    error = failure(finish, done)
    assert error.status_code == 502 and error.detail == SUMMARY_UNCONFIRMED_COPY
    assert failure_details(error) == {
        'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': False,
        'summary_failure_context': context(done, expected),
    }
    assert SECRET not in json.dumps(error.summary_failure_context) + str(error) + caplog.text
    assert not caplog.records


def test_normal_output_is_unchanged_including_usage_reasoning_and_trailing_null_finish():
    class Complete:
        def iter_lines(self):
            for event in [
                {'choices': [{'delta': {'reasoning_content': SECRET}}]},
                {'model': 'fixture-model', 'choices': [{'delta': {'content': ' 甲\n\n'}, 'finish_reason': 'stop'}]},
                {'choices': [{'delta': {'content': '乙  '}, 'finish_reason': None}]},
                {'choices': [], 'usage': {'total_tokens': 9}},
            ]:
                yield 'data: ' + json.dumps(event)
                yield ''
            yield 'data: [DONE]'
            yield ''
    assert collect_chat_stream(Complete(), started=time.monotonic()) == {
        'model': 'fixture-model', 'usage': {'total_tokens': 9},
        'choices': [{'message': {'content': ' 甲\n\n乙  '}, 'finish_reason': 'stop'}],
    }


@pytest.mark.parametrize('done', [False, True])
@pytest.mark.parametrize('finishes,effective,safe_finish', [
    (['stop', None], 'stop', 'stop'), (['length', ''], 'length', 'length'),
    (['stop', 0], 'stop', 'stop'), ([None, ''], None, 'other'),
    (['stop', 'length'], 'length', 'length'), (['length', 'stop'], 'stop', 'stop'),
])
def test_diagnostic_preserves_existing_accumulated_finish_semantics(done, finishes, effective, safe_finish):
    class MultiFinish:
        def iter_lines(self):
            for finish in finishes:
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': 'x'}, 'finish_reason': finish}]})
                yield ''
            if done:
                yield 'data: [DONE]'
                yield ''
    if done and effective == 'stop':
        result = collect_chat_stream(MultiFinish(), started=time.monotonic())
        assert result == {'model': None, 'usage': {}, 'choices': [
            {'message': {'content': 'xx'}, 'finish_reason': 'stop'}]}
    else:
        with pytest.raises(SummaryResultUnconfirmed) as caught:
            collect_chat_stream(MultiFinish(), started=time.monotonic())
        assert failure_details(caught.value)['summary_failure_context'] == context(done, safe_finish)


@pytest.mark.parametrize('reason', ['incomplete', 'timeout', 'connection', 'http524'])
def test_legacy_and_other_failure_branches_do_not_invent_terminal_diagnostics(reason):
    error = SummaryResultUnconfirmed(reason)
    error.cloud_failure_context = context()
    assert failure_details(error) == {'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': False}


def test_early_parser_failure_and_deadline_do_not_acquire_terminal_diagnostics():
    class Invalid:
        def iter_lines(self):
            yield 'data: invalid-json'
            yield ''
    for stream, started, status in [(Invalid(), time.monotonic(), 502),
                                     (Stream('stop', True), time.monotonic() - 901, 504)]:
        with pytest.raises(SummaryResultUnconfirmed) as caught:
            collect_chat_stream(stream, started=started)
        assert caught.value.status_code == status
        assert 'summary_failure_context' not in failure_details(caught.value)


@pytest.mark.parametrize('damage', [
    {'diagnostic_protocol': 'other'}, {'done_seen': 0}, {'done_seen': 'false'},
    {'finish': SECRET}, {'finish': []}, {'category': SECRET},
    {'done_seen': True, 'finish': 'stop'}, {'category': 'missing_done'},
])
def test_invalid_context_is_dropped_at_exception_projection_recovery_and_update(tmp_path, damage):
    invalid = context() | damage
    error = SummaryResultUnconfirmed(terminal_diagnostic=invalid)
    # Recheck even if an exception attribute was changed after construction.
    error.summary_failure_context = invalid
    assert failure_details(error) == {'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': False}
    raw = {'status': 'failed', 'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': True,
           'summary_failure_context': invalid}
    before = copy.deepcopy(raw)
    projected = recovery_status(raw)
    assert 'summary_failure_context' not in projected and projected['retryable'] is False
    assert raw == before
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('invalid')
    artifacts.write_json(folder / 'status.json', raw)
    artifacts.update_status(folder, 'failed', retryable=True)
    assert 'summary_failure_context' not in artifacts.get_status('invalid')
    assert artifacts.get_status('invalid')['retryable'] is False


def test_only_typed_summary_errors_project_explicit_diagnostics_and_extra_fields_are_removed():
    error = failure('length', True)
    error.summary_failure_context.update(raw=SECRET, url=SECRET, message=SECRET, id=SECRET, keys=[SECRET])
    assert failure_details(error)['summary_failure_context'] == context(True, 'length')
    fake = HTTPException(502, 'fixture')
    fake.summary_failure_context = context()
    assert failure_details(fake) == {}
    raw = {'status': 'failed', 'error_code': SUMMARY_UNCONFIRMED_CODE,
           'summary_failure_context': error.summary_failure_context}
    assert recovery_status(raw)['summary_failure_context'] == context(True, 'length')


@pytest.mark.parametrize('missing', ['diagnostic_protocol', 'done_seen', 'finish', 'category'])
def test_partial_historical_context_is_not_completed_by_inference(missing):
    partial = context()
    partial.pop(missing)
    raw = {'status': 'failed', 'error_code': SUMMARY_UNCONFIRMED_CODE,
           'summary_failure_context': partial, 'retryable': True}
    assert 'summary_failure_context' not in recovery_status(raw)


@pytest.mark.parametrize('retryable', [True, False, None])
def test_safe_recovery_is_detached_non_mutating_and_always_non_retryable(retryable):
    raw = {'status': 'failed', 'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': retryable,
           'summary_failure_context': context(True, 'length') | {'raw': SECRET}}
    before = copy.deepcopy(raw)
    saved = recovery_status(raw)
    assert saved['summary_failure_context'] == context(True, 'length')
    assert saved['retryable'] is False and raw == before
    saved['summary_failure_context']['finish'] = 'other'
    assert raw == before


@pytest.mark.parametrize('retryable', [False, True])
def test_task_updates_preserve_only_safe_same_attempt_context_and_cannot_enable_retry(tmp_path, retryable):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('one')
    artifacts.update_status(folder, 'summarizing', processed_seconds=10, total_seconds=10)
    error = failure('length', True)
    artifacts.update_status(folder, 'failed', str(error), **failure_details(error))
    disk = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    assert disk['summary_failure_context'] == context(True, 'length')
    disk['summary_failure_context']['raw'] = SECRET
    artifacts.write_json(folder / 'status.json', disk)
    artifacts.update_status(folder, 'failed', 'outer handler', retryable=retryable)
    saved = artifacts.get_status('one')
    assert saved['summary_failure_context'] == context(True, 'length')
    assert saved['retryable'] is False and saved['error_code'] == SUMMARY_UNCONFIRMED_CODE
    assert saved['failed_stage'] == 'summarizing'
    assert saved['processed_seconds'] == saved['total_seconds'] == 10
    assert 'asr_failure_context' not in saved and SECRET not in json.dumps(saved)
    before = (folder / 'status.json').read_bytes()
    artifacts.update_status(folder, 'success', 'late callback')
    assert (folder / 'status.json').read_bytes() == before
    artifacts.update_status(folder, 'uploaded', attempt=2)
    assert 'summary_failure_context' not in artifacts.get_status('one')


def test_concurrent_task_failures_are_persisted_to_their_own_status_only(tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    cases = [('length', True), ('stop', False), (None, False), ('tool_calls', True)]
    captured = Barrier(len(cases))
    def save(index):
        finish, done = cases[index]
        folder = artifacts.create_task_dir(f'task-{index}')
        artifacts.update_status(folder, 'summarizing')
        error = failure(finish, done)
        captured.wait(timeout=10)
        artifacts.update_status(folder, 'failed', str(error), **failure_details(error))
        return folder
    with ThreadPoolExecutor(max_workers=4) as pool:
        folders = list(pool.map(save, range(len(cases))))
    for index, folder in enumerate(folders):
        finish, done = cases[index]
        raw = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
        assert raw['summary_failure_context'] == context(done, finish or 'missing')
        assert raw['retryable'] is False
    other = artifacts.create_task_dir('legacy')
    artifacts.update_status(other, 'failed', error_code=SUMMARY_UNCONFIRMED_CODE, retryable=True)
    assert 'summary_failure_context' not in artifacts.get_status('legacy')
    assert artifacts.get_status('legacy')['retryable'] is False


@pytest.mark.parametrize('status,code', [('success', SUMMARY_UNCONFIRMED_CODE), ('failed', 'unknown_result'),
                                        ('failed', None), ('summarizing', SUMMARY_UNCONFIRMED_CODE)])
def test_context_does_not_authorize_a_summary_failure_for_an_unrelated_state(status, code):
    raw = {'status': status, 'retryable': True, 'summary_failure_context': context()}
    if code is not None:
        raw['error_code'] = code
    assert 'summary_failure_context' not in recovery_status(raw)


def test_non_summary_retryable_failure_and_empty_legacy_projection_remain_unchanged(tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('preparing')
    artifacts.update_status(folder, 'preparing')
    artifacts.update_status(folder, 'failed', 'fixture failure', retryable=True)
    saved = artifacts.get_status('preparing')
    assert saved['retryable'] is True and 'summary_failure_context' not in saved
    assert recovery_status({'status': 'failed', 'retryable': True}) == {'status': 'failed', 'retryable': True}


def test_private_diagnostic_is_not_added_to_public_status_and_get_does_not_rewrite_artifact(tmp_path, monkeypatch):
    from app.routers import note
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('private')
    error = failure('length', True)
    artifacts.update_status(folder, 'failed', str(error), **failure_details(error))
    before = (folder / 'status.json').read_bytes()
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(get_status=artifacts.get_status))
    monkeypatch.setattr(note, '_require_recording_access', lambda *args: None)
    result = note.get_task_status('private', SimpleNamespace(user_id='fixture'))
    assert result.error_code == SUMMARY_UNCONFIRMED_CODE and result.retryable is False
    assert result.message == SUMMARY_UNCONFIRMED_COPY
    assert 'summary_failure_context' not in result.model_dump()
    assert (folder / 'status.json').read_bytes() == before
