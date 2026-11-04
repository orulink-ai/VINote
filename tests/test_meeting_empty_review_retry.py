import json
import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.openai_llm import _BasePromptLLM
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment

SOURCE = 'The valve remains closed until inspection.'
DRAFT = json.dumps({'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Valve'}], 'claims': [
    {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': SOURCE, 'material': True,
     'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE}]}]})
EMPTY = json.dumps({'protocol': 4, 'claims': [], 'blocks': []})
EMPTY_CLAIMS = json.dumps({'protocol': 4, 'claims': [], 'blocks': [{'id': 'B1', 'markdown': SOURCE}]})
VALID = json.dumps({'protocol': 4, 'claims': [{'id': 'C1', 'field': 'condition', 'text': SOURCE,
    'material': True, 'disposition': 'included', 'block_ids': ['B1'],
    'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE}]}],
    'blocks': [{'id': 'B1', 'markdown': SOURCE}]})

class Reviewer(_BasePromptLLM):
    def _can_retry_empty_review(self):
        return True

    def _can_retry_invalid_draft(self):
        return True

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def _complete_review(self, **prompts):
        self.calls.append(prompts)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

def run(llm):
    return llm._review_meeting_note(source='[ASR:0001] '+SOURCE, draft=DRAFT, extras=None, output_language='en')

def test_empty_completed_review_retries_once_and_validates():
    llm = Reviewer([EMPTY, VALID])
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), presentation_scope('detailed', 'text') as state:
        assert run(llm) == SOURCE
        assert state.raw_review == VALID
        assert state.review_attempts_started == 2
        assert state.review_attempts_completed == 2
        assert state.empty_review_responses == 1
    assert len(llm.calls) == 2
    assert llm.calls[0]['user_prompt'] == llm.calls[1]['user_prompt']
    assert 'empty' in llm.calls[1]['system_prompt'].lower()

def test_empty_claims_with_blocks_retries_and_validates():
    llm = Reviewer([EMPTY_CLAIMS, VALID])
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), presentation_scope('detailed', 'text') as state:
        assert run(llm) == SOURCE
        assert state.review_attempts_completed == 2

def test_repeated_empty_fails_closed_without_more_calls():
    llm = Reviewer([EMPTY, EMPTY, EMPTY])
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), presentation_scope('detailed', 'text') as state:
        with pytest.raises(FinalLedgerError):
            run(llm)
        assert state.empty_review_responses == 2
    assert len(llm.calls) == 2


def test_retry_transport_failure_preserves_first_response():
    llm = Reviewer([EMPTY, RuntimeError('transport')])
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), presentation_scope('detailed', 'text') as state:
        with pytest.raises(RuntimeError):
            run(llm)
        assert state.raw_review == EMPTY
        assert state.review_attempts_started == 2
        assert state.review_attempts_completed == 1
        assert state.empty_review_responses == 1
    assert len(llm.calls) == 2

def test_vilab_allows_only_explicit_completed_empty_review_retry():
    from app.llm.vilab_llm import VILabLLM
    llm = VILabLLM('owner', 'model')
    assert llm._can_retry_empty_review()
    llm.configure_source_reading()
    assert llm._can_retry_empty_review()
    with pytest.raises(ValueError):
        llm._permit_completed_empty_review_retry()
    llm._source_review_started = True
    llm._source_post_count = 4
    llm._permit_completed_empty_review_retry()
    assert llm._source_review_retry_permitted

@pytest.mark.parametrize('response', [RuntimeError('transport'), '{'])
def test_ambiguous_or_other_invalid_results_never_retry(response):
    llm = Reviewer([response])
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), presentation_scope('detailed', 'text'):
        with pytest.raises((FinalLedgerError, RuntimeError)): run(llm)
    assert len(llm.calls) == 1
