import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.openai_llm import _BasePromptLLM
from app.llm.source_references import bind_source_references, capture_working_draft
from app.models.transcript import TranscriptSegment

SOURCE = 'Valve remains closed.'
DRAFT = json.dumps({'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Valve'}], 'claims': [{'id': 'C1', 'topic_id': 'T1', 'field': 'status', 'text': SOURCE, 'material': True, 'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE}]}]})


class Generator(_BasePromptLLM):
    def __init__(self, responses, eligible=True):
        self.responses = iter(responses)
        self.calls = []
        self.eligible = eligible

    def _can_retry_invalid_draft(self):
        return self.eligible

    def _complete(self, **prompts):
        self.calls.append(prompts)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def _review_meeting_note(self, **kwargs):
        return kwargs['draft']


def run(llm, saved):
    segment = TranscriptSegment(0, 1, SOURCE)
    with bind_source_references([segment]), presentation_scope('detailed', 'text'), capture_working_draft(saved.append):
        return llm._summarize_one_shot(title='meeting', segments=[segment], style='meeting', extras=None, output_language='en', direct_text=False)


def test_completed_invalid_json_retries_once_preserving_first_draft():
    saved = []
    llm = Generator(['{', DRAFT])
    assert json.loads(run(llm, saved))['protocol'] == 3
    assert saved == ['{'] and len(llm.calls) == 2
    assert 'invalid JSON' in llm.calls[1]['system_prompt']


@pytest.mark.parametrize('first,eligible', [(RuntimeError('transport'), True), ('{', False), ('{"a":1,"a":2}', True)])
def test_unknown_transport_or_other_validation_errors_do_not_retry(first, eligible):
    llm = Generator([first], eligible)
    with pytest.raises((RuntimeError, FinalLedgerError)):
        run(llm, [])
    assert len(llm.calls) == 1


def test_repeated_invalid_json_stops_after_one_retry():
    llm = Generator(['{', '{'])
    saved = []
    with pytest.raises(FinalLedgerError):
        run(llm, saved)
    assert len(llm.calls) == 2 and saved == ['{']


def test_completed_draft_with_unknown_evidence_kind_retries():
    bad = json.loads(DRAFT)
    bad['claims'][0]['evidence'][0]['kind'] = 'unknown'
    raw = json.dumps(bad)
    saved = []
    llm = Generator([raw, DRAFT])
    assert json.loads(run(llm, saved))['protocol'] == 3
    assert saved == [raw] and len(llm.calls) == 2


def test_other_structural_error_is_not_retried():
    bad = json.loads(DRAFT)
    bad['claims'][0]['topic_id'] = 'missing'
    llm = Generator([json.dumps(bad)])
    with pytest.raises(ValueError):
        run(llm, [])
    assert len(llm.calls) == 1

