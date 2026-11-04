"""Compact wire decisions still pass the complete existing evidence validator."""
import copy
import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment


SOURCE = 'The release remains blocked until the pressure test passes.'


def sample():
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Release'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': SOURCE,
         'material': True, 'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]',
                                       'quote': SOURCE}]}]}
    response = {'protocol': 8, 'blocks': [{'id': 'B1', 'markdown': '# Release\n\n' + SOURCE}],
                'claims': [{'id': 'C1', 'unchanged': True, 'disposition': 'included', 'block_ids': ['B1']}]}
    return draft, response


def validate(draft, response, depth='detailed'):
    from app.llm.meeting_compact_review import validate_compact_review
    with bind_source_references([TranscriptSegment(0, 10, SOURCE)]):
        return validate_compact_review(response, draft, depth=depth)


def test_explicit_unchanged_decision_reuses_exact_immutable_source_and_preserves_markdown():
    draft, response = sample()
    before = copy.deepcopy((draft, response))
    ledger = validate(draft, response)
    assert ledger.markdown == '# Release\n\n' + SOURCE
    assert ledger.claims[0]['text'] == SOURCE
    assert ledger.claims[0]['evidence'][0]['quote'] == SOURCE
    assert (draft, response) == before


@pytest.mark.parametrize('change', ['invalid_quote', 'missing_id', 'unknown_id', 'duplicate_id',
                                   'override_text', 'false_confirmation', 'missing_block', 'omitted_material'])
def test_compact_decisions_do_not_bypass_existing_guards(change):
    draft, response = sample()
    row = response['claims'][0]
    if change == 'invalid_quote':
        draft['claims'][0]['evidence'][0]['quote'] = 'Invented quote'
    elif change == 'missing_id':
        response['claims'] = []
    elif change == 'unknown_id':
        row['id'] = 'NEW'
    elif change == 'duplicate_id':
        response['claims'].append(copy.deepcopy(row))
    elif change == 'override_text':
        row['text'] = 'The release is approved.'
    elif change == 'false_confirmation':
        row['unchanged'] = False
    elif change == 'missing_block':
        row['block_ids'] = ['missing']
    elif change == 'omitted_material':
        row.update(disposition='omitted_for_depth', block_ids=[], reason='Shorter')
    with pytest.raises(FinalLedgerError):
        validate(draft, response)


def test_corrected_claim_requires_full_fresh_evidence_and_original_identity():
    draft, response = sample()
    row = {k: copy.deepcopy(v) for k, v in draft['claims'][0].items() if k != 'topic_id'}
    row.update(disposition='included', block_ids=['B1'], text='Release waits for the pressure test.')
    response['claims'] = [row]
    assert validate(draft, response).claims[0]['text'] == row['text']
    row['evidence'][0]['quote'] = 'The pressure test already passed.'
    with pytest.raises(FinalLedgerError):
        validate(draft, response)


def test_compact_confirmations_reduce_large_review_output_without_dropping_claims():
    draft, response = sample()
    draft['claims'] = [dict(copy.deepcopy(draft['claims'][0]), id=f'C{i}') for i in range(276)]
    response['claims'] = [dict(copy.deepcopy(response['claims'][0]), id=f'C{i}') for i in range(276)]
    ledger = validate(draft, response)
    assert len(ledger.claims) == 276
    expanded = {'protocol': 4, 'blocks': list(ledger.blocks), 'claims': list(ledger.claims)}
    assert len(json.dumps(response)) < len(json.dumps(expanded)) * .4


def test_vilab_whole_review_selects_compact_protocol_and_preserves_raw_response():
    from app.llm.vilab_llm import VILabLLM
    from app.llm.meeting_presentation import presentation_scope
    draft, response = sample()
    raw = json.dumps(response)
    client = VILabLLM('synthetic-owner', 'frozen-model')
    observed = []
    def complete(**prompts):
        observed.append(prompts)
        return raw
    client._complete_review = complete
    with bind_source_references([TranscriptSegment(0, 10, SOURCE)]), presentation_scope('detailed', 'text') as state:
        body = client._review_meeting_note(source=SOURCE, draft=json.dumps(draft), extras=None,
                                           output_language='en')
    assert SOURCE in observed[0]['user_prompt']
    assert 'PROTOCOL 8' in observed[0]['system_prompt']
    assert state.raw_review == raw
    assert body == response['blocks'][0]['markdown']


def test_unverified_and_visual_draft_evidence_cannot_use_confirmation_shorthand():
    for evidence in ({'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE, 'verification': 'unverified'},
                     {'kind': 'frame_observation', 'source_ref': '[FRAME:0001]', 'observation': SOURCE}):
        draft, response = sample()
        draft['claims'][0]['evidence'] = [evidence]
        with pytest.raises(FinalLedgerError):
            validate(draft, response)


def test_prompt_distinguishes_compact_wire_fields_from_expanded_evidence_requirements():
    from app.llm.meeting_compact_review import compact_review_protocol
    rules = compact_review_protocol()
    assert rules.index('COMPACT ORIGINAL CONFIRMATIONS') < rules.index('Each full row requires')
    assert 'Included requires at least one real block ID and a complete valid final evidence list.' not in rules
    assert 'Never omit the key or invent support' not in rules
    assert 'After host expansion, every included claim requires' in rules
    assert 'Compact unchanged rows omit the evidence key on the wire' in rules
    assert 'Full rows must never omit the evidence key' in rules
