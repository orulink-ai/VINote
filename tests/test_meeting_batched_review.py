import json
import pytest

from app.llm.meeting_batched_review import merge_batches
from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment
from tests.test_meeting_empty_review_retry import DRAFT, VALID, SOURCE


def test_batch_merge_validates_and_namespaces_report_blocks():
    draft = json.loads(DRAFT)
    second = dict(draft['claims'][0], id='C2')
    draft['claims'].append(second)
    response = json.loads(VALID)
    other = json.loads(VALID)
    other['claims'][0]['id'] = 'C2'
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]):
        result = merge_batches(draft, [(draft['claims'][:1], response), (draft['claims'][1:], other)], depth='detailed')
    assert len(result['blocks']) == 2
    assert result['blocks'][0]['id'] != result['blocks'][1]['id']
    assert {x['id'] for x in result['claims']} == {'C1', 'C2'}


def test_batch_merge_rejects_other_batch_original_id():
    draft = json.loads(DRAFT)
    draft['claims'].append(dict(draft['claims'][0], id='C2'))
    response = json.loads(VALID)
    response['claims'].append(dict(response['claims'][0], id='C2'))
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), pytest.raises(FinalLedgerError):
        merge_batches(draft, [(draft['claims'][:1], response)], depth='detailed')
