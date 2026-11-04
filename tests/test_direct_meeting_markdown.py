"""One complete-source request writes readable minutes; no claim-ledger gate."""
import json
import time

import pytest

from app.llm.openai_llm import _BasePromptLLM
from app.llm.meeting_presentation import presentation_scope
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from app.services.cloud_chat_stream import collect_chat_stream
from app.services.summary_failure import SummaryResultUnconfirmed
from app.services.vilab_cloud_service import VILabCloudService, _task_source


BODY = '# Release planning\n\n## Decision\n\nWait for the pressure test.'
SEGMENTS = [TranscriptSegment(0, 10, 'Opening: release is proposed.', speaker_id='1'),
            TranscriptSegment(7000, 7010, 'Closing: wait for the pressure test.', speaker_id='2')]
SNAPSHOT = {'mode': 'cloud', 'server_url': 'https://frozen.invalid', 'llm_model': 'selected', 'owner': 'owner'}


class Direct(_BasePromptLLM):
    def __init__(self, result=BODY):
        self.calls = []
        self.result = result

    def _complete(self, **prompts):
        self.calls.append(prompts)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def _review_meeting_note(self, **kwargs):
        pytest.fail('Default text minutes must not launch a second review')


@pytest.mark.parametrize('depth', ['concise', 'detailed'])
@pytest.mark.parametrize('presentation', [None, 'text'])
def test_complete_meeting_is_sent_once_for_readable_markdown(depth, presentation):
    llm = Direct()
    with presentation_scope(depth, presentation) as state:
        result = llm.summarize('source filename', SEGMENTS, style='meeting', extras='Explicit context')
    assert result == BODY and len(llm.calls) == 1
    prompt = llm.calls[0]
    assert all(prompt['user_prompt'].count(s.text) == 1 for s in SEGMENTS)
    assert 'Explicit context' in prompt['user_prompt']
    assert 'one # meeting title' in prompt['system_prompt']
    assert '## headings' in prompt['system_prompt']
    assert 'Return exactly one JSON' not in prompt['system_prompt']
    assert 'CLAIM LEDGER' not in prompt['system_prompt']
    assert state.raw_review is None and state.review_attempts_started == 0


@pytest.mark.parametrize('result', ['', ' \n ', RuntimeError('provider unavailable')])
def test_empty_or_failed_direct_result_never_retries_or_saves_partial_output(result):
    llm = Direct(result)
    with presentation_scope('concise', 'text'), pytest.raises(RuntimeError):
        llm.summarize('source', SEGMENTS, style='meeting')
    assert len(llm.calls) == 1


class Stream:
    def __init__(self, *, finish='stop', done=True, content=BODY):
        self.finish, self.done, self.content = finish, done, content

    def iter_lines(self):
        yield 'data: ' + json.dumps({'choices': [{'delta': {'content': self.content}, 'finish_reason': self.finish}]})
        yield ''
        if self.done:
            yield 'data: [DONE]'


@pytest.mark.parametrize('finish,done', [('stop', True), ('length', True), ('stop', False)])
def test_vilab_direct_payload_omits_json_mode_but_preserves_sse_completion_guard(monkeypatch, finish, done):
    calls = []
    def request(self, owner, method, path, **kwargs):
        assert owner == 'owner' and method == 'POST' and path == '/openai/v1/chat/completions'
        calls.append(kwargs['json'])
        return collect_chat_stream(Stream(finish=finish, done=done), started=time.monotonic())
    monkeypatch.setattr(VILabCloudService, 'request', request)
    with VILabCloudService().task_snapshot('owner', snapshot=SNAPSHOT), presentation_scope('detailed', 'text'):
        llm = VILabLLM('owner', 'selected')
        if finish == 'stop' and done:
            assert llm.summarize('source', SEGMENTS, style='meeting') == BODY
        else:
            with pytest.raises(SummaryResultUnconfirmed):
                llm.summarize('source', SEGMENTS, style='meeting')
    assert len(calls) == 1
    assert calls[0]['stream'] is True and 'response_format' not in calls[0]
    assert calls[0]['model'] == 'selected'
    assert all(s.text in calls[0]['messages'][1]['content'] for s in SEGMENTS)


def test_direct_markdown_still_rejects_changed_frozen_owner_model_binding(monkeypatch):
    monkeypatch.setattr(VILabCloudService, 'request', lambda *a, **k: pytest.fail('changed source must not dispatch'))
    with VILabCloudService().task_snapshot('owner', snapshot=SNAPSHOT), presentation_scope('detailed', 'text'):
        llm = VILabLLM('owner', 'selected')
        token = _task_source.set(('owner', {**SNAPSHOT, 'llm_model': 'different'}))
        try:
            with pytest.raises(RuntimeError, match='binding changed'):
                llm.summarize('source', SEGMENTS, style='meeting')
        finally:
            _task_source.reset(token)


def test_direct_scope_is_reset_after_provider_failure():
    from app.llm.meeting_presentation import direct_markdown_active
    llm = Direct(RuntimeError('offline'))
    with presentation_scope('concise', 'text'), pytest.raises(RuntimeError):
        llm.summarize('source', SEGMENTS, style='meeting')
    assert direct_markdown_active() is False


@pytest.mark.parametrize('presentation', ['html', 'illustrated', 'comic', 'infographic'])
def test_nontext_presentations_retain_the_structured_path(presentation):
    from app.llm.meeting_final_claim_ledger import FinalLedgerError
    llm = Direct('{malformed legacy draft')
    with presentation_scope('detailed', presentation), pytest.raises(FinalLedgerError):
        llm.summarize('source', SEGMENTS, style='meeting')
    assert len(llm.calls) == 1
    assert 'JSON' in llm.calls[0]['system_prompt']
