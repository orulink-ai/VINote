"""Flat serialization contracts with independent synthetic source material."""
import copy
import json

import pytest

from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
from app.llm.meeting_presentation import presentation_scope
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment

SOURCE = 'The label is unclear. Hold 27.625 mA while the green latch is closed; finish before noon.'


def draft():
    return {'protocol': 3, 'topics': [{'id': 'T9', 'title': 'Vesper calibration'}], 'claims': [
        {'id': key, 'topic_id': 'T9', 'field': field, 'text': anchor, 'anchor': anchor, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE}]}
        for key, field, anchor in [('C1', 'quantity', '27.625 mA'), ('C2', 'condition', 'while the green latch is closed'), ('C3', 'deadline', 'before noon')]]}


def review():
    return {'protocol': 3, 'blocks': [{'id': 'B2', 'markdown': 'For the unidentified unit, hold 27.625 mA while the green latch is closed; finish before noon.'}],
            'audit': [{'claim_id': key, 'disposition': 'included', 'block_ids': ['B2']} for key in ('C1', 'C2', 'C3')], 'figures': []}


def final_review():
    return {'protocol': 4, 'blocks': review()['blocks'], 'claims': [
        {key: value for key, value in claim.items() if key not in {'topic_id', 'anchor'}}
        | {'disposition': 'included', 'block_ids': ['B2']} for claim in draft()['claims']]}


def evaluate(material, result):
    with bind_source_references([TranscriptSegment(0, 9, SOURCE)]), presentation_scope('detailed', 'text'):
        checked = prepare_fact_material(json.dumps(material), 'annotated transcript', require_protocol=3)
        return checked, finalize_fact_review(json.dumps(result), checked, 'annotated transcript')


def test_flat_claims_use_the_same_exact_evidence_and_block_accounting():
    checked, body = evaluate(draft(), review())
    value = json.loads(checked)
    assert value['protocol'] == 3 and 'facts' not in value
    assert all('topic_id' in claim and 'claims' not in claim for claim in value['claims'])
    assert value['claims'][0]['evidence'][0]['verification'] == 'exact_asr_span'
    assert body == review()['blocks'][0]['markdown']


def test_review_flat_additional_claims_can_restore_a_source_property():
    material, result = draft(), review()
    result['additional_claims'] = [material['claims'].pop()]
    assert evaluate(material, result)[1] == result['blocks'][0]['markdown']


def test_partial_entity_rejection_never_removes_independent_properties():
    material, result = draft(), review()
    entity = copy.deepcopy(material['claims'][0])
    entity.update(id='C4', field='entity', text='Uncertain label', anchor='unclear')
    material['claims'].append(entity)
    result['audit'].append({'claim_id': 'C4', 'disposition': 'rejected', 'block_ids': [], 'reason_code': 'unclear_entity',
        'reason': 'The original source explicitly calls the label unclear.', 'evidence': entity['evidence']})
    assert '27.625 mA' in evaluate(material, result)[1]
    result['audit'][0] = {**result['audit'][-1], 'claim_id': 'C1'}
    with pytest.raises(ValueError): evaluate(material, result)


@pytest.mark.parametrize('change', ['nested_facts', 'nested_claim', 'changed_span', 'unknown_source', 'missing_topic', 'repeated_id', 'unknown_block'])
def test_flat_shape_never_repairs_nesting_or_weakens_evidence(change):
    material, result = draft(), review()
    if change == 'nested_facts': material['facts'] = []
    if change == 'nested_claim': material['claims'][0] = {'id': 'F1', 'topic_id': 'T9', 'claims': material['claims'][:1]}
    if change == 'changed_span': material['claims'][0]['evidence'][0]['quote'] = SOURCE.replace('27.625', '27.265')
    if change == 'unknown_source': material['claims'][0]['evidence'][0]['source_ref'] = '[ASR:9999]'
    if change == 'missing_topic': material['claims'][0].pop('topic_id')
    if change == 'repeated_id': material['claims'][1]['id'] = 'C1'
    if change == 'unknown_block': result['audit'][0]['block_ids'] = ['B404']
    with pytest.raises(ValueError): evaluate(material, result)


def test_malformed_json_is_not_fixed_or_accepted_as_a_partial_prefix():
    for raw in [json.dumps(draft())[:-2], json.dumps(draft()) + '}', json.dumps(draft()) + '\ntrailing prose']:
        with pytest.raises(ValueError): prepare_fact_material(raw, SOURCE, require_protocol=3)


def test_current_prompt_examples_are_valid_flat_json_and_quotes_stay_in_source_language():
    from app.llm.meeting_fact_protocol import DRAFT_PROTOCOL, REVIEW_PROTOCOL
    from app.llm.meeting_draft import build_meeting_draft_prompts
    for prompt in [DRAFT_PROTOCOL, REVIEW_PROTOCOL]:
        example = next(line for line in prompt.splitlines() if line.startswith('{'))
        assert json.loads(example.rstrip('.'))['protocol'] == 3
    example = json.loads(next(line for line in DRAFT_PROTOCOL.splitlines() if line.startswith('{')).rstrip('.'))
    assert 'claims' in example and 'facts' not in example
    with presentation_scope('brief', 'text'):
        prompt = build_meeting_draft_prompts(title='Synthetic', source=SOURCE, extras=None, output_language='zh-CN')
    assert SOURCE in prompt['user_prompt']
    assert 'quotes and verbatim names exactly in their original source language' in prompt['user_prompt']


@pytest.mark.parametrize('depth', ['brief', 'detailed'])
def test_live_path_remains_two_calls_with_draft_three_and_review_four(depth):
    from app.llm.openai_llm import _BasePromptLLM
    class Automatic(_BasePromptLLM):
        def __init__(self): self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert SOURCE in prompts['user_prompt']
            return json.dumps(draft() if len(self.calls) == 1 else final_review())
    llm = Automatic()
    with presentation_scope(depth, 'text'):
        result = llm.summarize('Synthetic Vesper calibration', [TranscriptSegment(0, 9, SOURCE)], style='meeting')
    assert result == review()['blocks'][0]['markdown'] and len(llm.calls) == 2


def test_v3_anchor_is_optional_and_never_a_semantic_proof():
    material = draft()
    material['claims'][0].pop('anchor')
    material['claims'][1]['anchor'] = 'A paraphrase rather than a second quotation'
    assert evaluate(material, review())[1] == review()['blocks'][0]['markdown']


def test_v3_field_extensions_are_labels_not_a_new_semantic_gate():
    material, result = draft(), review()
    material['claims'][0]['field'] = 'responsibility'
    assert evaluate(material, result)[1] == result['blocks'][0]['markdown']
    result['audit'][0].update(disposition='rejected', block_ids=[], reason_code='unclear_entity',
        reason='Unclear identity', evidence=material['claims'][0]['evidence'])
    with pytest.raises(ValueError): evaluate(material, result)


def test_wrong_draft_quote_is_preserved_unverified_until_review_corrects_it():
    material, result = draft(), review()
    wrong = material['claims'][0]['evidence'][0]
    wrong.update(source_ref='[ASR:0002]', verification='exact_asr_span')
    with bind_source_references([TranscriptSegment(0, 9, SOURCE)]):
        checked = json.loads(prepare_fact_material(json.dumps(material), SOURCE, require_protocol=3))
    assert checked['claims'][0]['evidence'][0] == {**wrong, 'verification': 'unverified'}
    assert material['claims'][0]['evidence'][0]['verification'] == 'exact_asr_span'
    result['audit'][0]['evidence'] = draft()['claims'][0]['evidence']
    assert evaluate(material, result)[1] == result['blocks'][0]['markdown']


@pytest.mark.parametrize('disposition', ['included', 'rejected'])
@pytest.mark.parametrize('failure', ['wrong_quote', 'unknown_source', 'bad_offsets', 'ambiguous_quote'])
def test_final_corrected_evidence_still_requires_exact_actual_source(disposition, failure):
    material, result = draft(), review()
    row = result['audit'][0]
    row['evidence'] = copy.deepcopy(material['claims'][0]['evidence'])
    if failure == 'wrong_quote': row['evidence'][0]['quote'] = SOURCE.replace('27.625', '27.265')
    if failure == 'unknown_source': row['evidence'][0]['source_ref'] = '[ASR:4040]'
    if failure == 'bad_offsets': row['evidence'][0].update(start=False, end=len(SOURCE))
    if failure == 'ambiguous_quote': row['evidence'][0]['quote'] = 'a'
    if disposition == 'rejected':
        row.update(disposition='rejected', block_ids=[], reason_code='misread', reason='The candidate misreads this source.')
    with pytest.raises(ValueError): evaluate(material, result)


def test_rejected_candidate_does_not_revalidate_its_wrong_old_quote_or_reference():
    material, result = draft(), review()
    material['claims'][0]['evidence'][0].update(source_ref='[ASR:9999]', quote='Unsupported invented source text')
    result['audit'][0].update(disposition='rejected', block_ids=[], reason_code='unsupported',
        reason='The original source does not establish this candidate.', evidence=draft()['claims'][0]['evidence'])
    assert evaluate(material, result)[1] == result['blocks'][0]['markdown']
    result['audit'][0].pop('evidence')
    with pytest.raises(ValueError): evaluate(material, result)


def test_unverified_draft_cannot_be_included_without_review_evidence_correction():
    material = draft()
    material['claims'][0]['evidence'][0]['quote'] = '27.265 mA'
    with pytest.raises(ValueError): evaluate(material, review())


def test_nonmaterial_omission_does_not_authorize_or_recheck_unpublished_old_evidence():
    material, result = draft(), review()
    material['claims'][0].update(material=False)
    material['claims'][0]['evidence'][0]['source_ref'] = '[ASR:4444]'
    result['blocks'][0]['markdown'] = 'The green latch must be closed; finish before noon.'
    result['audit'][0].update(disposition='omitted_for_depth', block_ids=[], reason='Minor candidate excluded.')
    assert evaluate(material, result)[1] == result['blocks'][0]['markdown']
    material['claims'][0]['material'] = True
    with pytest.raises(ValueError): evaluate(material, result)


def test_correction_replaces_the_entire_invalid_list_including_added_claims():
    material, result = draft(), review()
    added = material['claims'].pop()
    result['additional_claims'] = [added]
    valid = copy.deepcopy(added['evidence'])
    added['evidence'].append({'kind': 'asr_span', 'source_ref': '[ASR:8888]', 'quote': 'Not present'})
    result['audit'][-1]['evidence'] = valid
    assert evaluate(material, result)[1] == result['blocks'][0]['markdown']


@pytest.mark.parametrize('evidence', [[], None, [{'kind': 'invented_type', 'source_ref': '[ASR:0001]', 'quote': SOURCE}]])
def test_draft_source_mismatch_tolerance_does_not_accept_a_missing_evidence_contract(evidence):
    material = draft()
    material['claims'][0]['evidence'] = evidence
    with pytest.raises(ValueError): evaluate(material, review())


def test_wrong_quote_reaches_second_call_with_original_response_preserved():
    from app.llm.openai_llm import _BasePromptLLM
    from app.llm.source_references import capture_working_draft
    material, result = draft(), final_review()
    material['claims'][0].pop('anchor')
    material['claims'][0]['evidence'][0]['source_ref'] = '[ASR:7777]'
    result['claims'][0]['evidence'] = draft()['claims'][0]['evidence']
    raw = json.dumps(material)
    class Automatic(_BasePromptLLM):
        def __init__(self): self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert SOURCE in prompts['user_prompt']
            if len(self.calls) == 1: return raw
            assert '[ASR:7777]' in prompts['user_prompt'] and 'unverified' in prompts['user_prompt']
            return json.dumps(result)
    llm, observed = Automatic(), []
    with presentation_scope('detailed', 'text') as state, capture_working_draft(observed.append):
        body = llm.summarize('Synthetic Vesper calibration', [TranscriptSegment(0, 9, SOURCE)], style='meeting')
        assert state.raw_review == json.dumps(result)
    assert body == result['blocks'][0]['markdown'] and len(llm.calls) == 2 and observed == [raw]


def test_review_repeated_clause_needs_exact_occurrence_without_altering_source():
    source = 'Check the seal. Check the seal.'
    quote = 'Check the seal.'
    material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic seal check'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': quote, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': quote}]}]}
    result = {'protocol': 3, 'blocks': [{'id': 'B1', 'markdown': quote}],
              'audit': [{'claim_id': 'C1', 'disposition': 'included', 'block_ids': ['B1']}], 'figures': []}
    with bind_source_references([TranscriptSegment(0, 9, source)]), presentation_scope('concise', 'text'):
        checked = prepare_fact_material(json.dumps(material), source, require_protocol=3)
        with pytest.raises(ValueError):
            finalize_fact_review(json.dumps(result), checked, source)
        start = source.rfind(quote)
        result['audit'][0]['evidence'] = [{'kind': 'asr_span', 'source_ref': '[ASR:0001]',
                                         'quote': quote, 'start': start, 'end': start + len(quote)}]
        assert finalize_fact_review(json.dumps(result), checked, source) == quote
