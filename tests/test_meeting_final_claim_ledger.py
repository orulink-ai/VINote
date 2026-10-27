"""Protocol-4 core contracts; synthetic sources and no provider execution."""
import copy
import json

import pytest

from app.llm.meeting_final_claim_ledger import (
    FinalLedgerError, REVIEW_PROTOCOL, parse_final_ledger, validate_final_ledger,
)
from app.llm.meeting_fact_material import finalize_fact_review
from app.llm.meeting_presentation import presentation_scope
from app.llm.source_references import bind_source_references
from app.llm.video_material import bind_video_material
from app.models.transcript import TranscriptSegment
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence


RAW = 'Hold 18.625 mA while the blue latch is closed. Finish before the third bell.'


def span(quote=RAW, **kwargs):
    return {'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': quote, **kwargs}


def draft():
    return {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic interlock'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'quantity', 'text': 'Hold 18.625 mA',
         'material': True, 'evidence': [span()]},
        {'id': 'C2', 'topic_id': 'T1', 'field': 'condition', 'text': 'while the blue latch is closed',
         'material': True, 'evidence': [span()]},
    ]}


def row(key='C1', *, field='quantity', text='Hold 18.625 mA', material=True):
    return {'id': key, 'field': field, 'text': text, 'material': material,
            'disposition': 'included', 'block_ids': ['B1'], 'evidence': [span()]}


def review():
    return {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': RAW}], 'claims': [
        row(), row('C2', field='condition', text='while the blue latch is closed')]}


def run(value=None, material=None, *, raw=RAW, depth='detailed'):
    with bind_source_references([TranscriptSegment(0, 9, raw)]):
        return validate_final_ledger(review() if value is None else value,
                                     draft() if material is None else material, depth=depth)


def fails(code, value=None, material=None, **kwargs):
    with pytest.raises(FinalLedgerError) as error:
        run(value, material, **kwargs)
    assert error.value.code == code


def test_original_and_new_claims_are_defined_and_accounted_in_one_row():
    value = review()
    value['claims'].append(row('C3', field='deadline', text='Finish before the third bell'))
    before = copy.deepcopy(value)
    result = run(value)
    assert result.original_ids == frozenset({'C1', 'C2'})
    assert len(result.claims) == 3 and result.markdown == RAW
    assert all(c['evidence'][0]['verification'] == 'exact_asr_span' for c in result.claims)
    assert value == before


def test_whole_source_review_can_introduce_a_topic_absent_from_an_empty_draft():
    material = {'protocol': 3, 'topics': [], 'claims': []}
    value = {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': RAW}], 'claims': [row('NEW1')]}
    result = run(value, material)
    assert result.original_ids == frozenset() and result.claims[0]['id'] == 'NEW1'
    assert result.markdown == RAW


def test_empty_source_candidates_need_no_invented_claim_for_a_report_block():
    material = {'protocol': 3, 'topics': [], 'claims': []}
    value = {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': 'No substantive proposition.'}], 'claims': []}
    assert run(value, material).claims == ()


@pytest.mark.parametrize('change', ['missing', 'rename', 'duplicate', 'same_count_replacement'])
def test_complete_original_ids_cannot_be_replaced_by_counts_or_new_ids(change):
    value = review()
    if change == 'missing':
        value['claims'].pop()
    elif change == 'rename':
        value['claims'][1]['id'] = 'NEW2'
    elif change == 'duplicate':
        value['claims'].append(copy.deepcopy(value['claims'][0]))
    else:
        value['claims'] = [value['claims'][0], row('NEW3', field='deadline')]
    fails('invalid_claim_ids' if change == 'duplicate' else 'missing_original_claims', value)


@pytest.mark.parametrize('disposition', ['included', 'rejected', 'omitted_for_depth'])
@pytest.mark.parametrize('original_material', [True, False])
def test_original_material_flag_cannot_change_for_any_disposition(disposition, original_material):
    material = draft()
    material['claims'][0]['material'] = original_material
    value = review()
    value['claims'][0].update(material=not original_material, disposition=disposition)
    fails('changed_original_material', value, material)


@pytest.mark.parametrize('disposition', ['included', 'rejected', 'omitted_for_depth'])
def test_obsolete_material_reason_is_not_a_final_claim_field(disposition):
    value = review()
    value['claims'][0].update(material_reason='Synthetic relevance explanation', disposition=disposition)
    fails('invalid_claim_shape', value)


def test_new_nonmaterial_claim_does_not_reclassify_original_claims():
    value = review()
    value['claims'].append(row('NEW1', field='deadline', text='Finish before the third bell', material=False))
    result = run(value)
    assert [claim['material'] for claim in result.claims] == [True, True, False]


def test_original_field_cannot_be_relabelled_to_authorize_entity_rejection():
    value = review()
    value['claims'][0].update(field='entity', disposition='rejected', block_ids=[],
                              reason_code='unclear_entity', reason='Uncertain identity')
    fails('changed_original_field', value)


@pytest.mark.parametrize('new', [False, True])
def test_detailed_cannot_omit_material_original_or_new_claim(new):
    value = review()
    if new:
        value['claims'].append(row('NEW1', field='deadline'))
    target = value['claims'][-1] if new else value['claims'][0]
    target.update(disposition='omitted_for_depth', block_ids=[], evidence=[], reason='Shorten output')
    fails('material_omitted_for_depth', value)


@pytest.mark.parametrize('depth', ['brief', 'concise', 'detailed'])
def test_nonmaterial_omission_is_explicit_and_needs_no_invented_evidence(depth):
    material, value = draft(), review()
    material['claims'][0]['material'] = False
    # A draft mismatch is not published or repaired to justify an omission.
    material['claims'][0]['evidence'][0]['source_ref'] = '[ASR:9999]'
    value['claims'][0].update(material=False, disposition='omitted_for_depth', block_ids=[],
                              reason='Peripheral detail', evidence=[])
    assert run(value, material, depth=depth).claims[0]['evidence'] == []
    value['claims'][0]['reason'] = '  '
    fails('invalid_exclusion', value, material, depth=depth)


@pytest.mark.parametrize('depth', ['brief', 'concise'])
def test_shorter_depth_can_select_material_claims_without_changing_the_flag(depth):
    value = review()
    value['claims'][0].update(disposition='omitted_for_depth', block_ids=[],
                              reason='Secondary detail for this depth', evidence=[])
    assert run(value, depth=depth).claims[0]['material'] is True


@pytest.mark.parametrize('depth', [None, '', 'unknown', [], True])
def test_depth_has_no_permissive_default_or_model_override(depth):
    fails('invalid_depth', depth=depth)


@pytest.mark.parametrize('disposition', ['included', 'rejected', 'omitted_for_depth'])
@pytest.mark.parametrize('bad', ['unknown_ref', 'changed_quote', 'wrong_type', 'empty', 'mixed', 'offset'])
def test_final_evidence_is_strict_for_every_supplied_row(disposition, bad):
    material, value = draft(), review()
    target = value['claims'][0]
    if disposition != 'included':
        target.update(disposition=disposition, block_ids=[], reason='Specific source reason', reason_code='misread')
    if disposition == 'omitted_for_depth':
        material['claims'][0]['material'] = target['material'] = False
    evidence = target['evidence']
    if bad == 'unknown_ref': evidence[0]['source_ref'] = '[ASR:9999]'
    if bad == 'changed_quote': evidence[0]['quote'] = RAW.replace('18.625', '18.265')
    if bad == 'wrong_type': evidence[0]['kind'] = 'invented'
    if bad == 'empty': target['evidence'] = None
    if bad == 'mixed': evidence.append(span('Not supplied'))
    if bad == 'offset': evidence[0].update(start=False, end=len(RAW))
    fails('invalid_final_evidence', value, material)


def test_correction_uses_the_explicit_complete_replacement_not_draft_evidence():
    material, value = draft(), review()
    material['claims'][0]['evidence'][0].update(source_ref='[ASR:8888]', quote='Invented quote',
                                               verification='exact_asr_span')
    before = copy.deepcopy(material)
    assert run(value, material).claims[0]['evidence'][0]['source_ref'] == '[ASR:0001]'
    assert material == before
    value['claims'][0].pop('evidence')
    fails('invalid_claim_shape', value, material)


def test_repeated_exact_clause_requires_exclusive_character_offsets():
    raw = 'Check the seal. Check the seal.'
    value = review()
    for claim in value['claims']:
        claim['evidence'] = [span('Check the seal.', verification='exact_asr_span')]
    fails('invalid_final_evidence', value, raw=raw)
    start = raw.rfind('Check the seal.')
    for claim in value['claims']:
        claim['evidence'][0].update(start=start, end=len(raw))
    assert run(value, raw=raw).claims[0]['evidence'][0]['verification'] == 'exact_asr_span'
    value['claims'][0]['evidence'][0]['end'] -= 1
    fails('invalid_final_evidence', value, raw=raw)


@pytest.mark.parametrize('field', ['entity', 'quantity'])
def test_unclear_entity_cannot_reject_independently_supported_property(field):
    material, value = draft(), review()
    material['claims'][0]['field'] = value['claims'][0]['field'] = field
    value['claims'][0].update(disposition='rejected', block_ids=[], reason_code='unclear_entity',
                              reason='The label is not established by this source')
    if field == 'entity':
        assert run(value, material).claims[0]['disposition'] == 'rejected'
    else:
        fails('invalid_rejection', value, material)


@pytest.mark.parametrize('change', ['empty_blocks', 'duplicate_block', 'unknown_block', 'duplicate_reference',
                                   'included_no_block', 'rejected_with_block', 'missing_definition'])
def test_block_and_definition_accounting_cannot_be_inferred(change):
    value = review()
    if change == 'empty_blocks': value['blocks'] = []
    if change == 'duplicate_block': value['blocks'].append(copy.deepcopy(value['blocks'][0]))
    if change == 'unknown_block': value['claims'][0]['block_ids'] = ['UNKNOWN']
    if change == 'duplicate_reference': value['claims'][0]['block_ids'] = ['B1', 'B1']
    if change == 'included_no_block': value['claims'][0]['block_ids'] = []
    if change == 'rejected_with_block':
        value['claims'][0].update(disposition='rejected', reason='Incorrect', reason_code='misread')
    if change == 'missing_definition': value['claims'].append({'id': 'NEW1', 'block_ids': ['B1']})
    with pytest.raises(FinalLedgerError): run(value)


@pytest.mark.parametrize('extra', ['audit', 'additional_claims', 'topic_audit', 'additional_topics', 'visual', 'figures'])
def test_no_second_accounting_table_or_unwired_visual_receipt(extra):
    value = review()
    value[extra] = []
    fails('invalid_envelope', value)


@pytest.mark.parametrize('body', ['[ASR:0001] source', '[FRAME:0001]', '![image](x)',
                                '[[Screenshot:00:01]]', '<script>alert(1)</script>'])
def test_reader_body_cannot_contain_internal_evidence_or_resources(body):
    value = review()
    value['blocks'][0]['markdown'] = body
    fails('invalid_block_content', value)


@pytest.mark.parametrize('body', ['See <https://example.org/reference>.', 'Keep x < 7 and y > 2.'])
def test_normal_markdown_links_and_comparisons_are_not_html(body):
    value = review()
    value['blocks'][0]['markdown'] = body
    assert run(value).markdown == body


@pytest.mark.parametrize('raw', ['{} {}', '```json\n{}\n```', '{', 'null',
                               '{"protocol":4,"protocol":4}',
                               '{"protocol":4,"blocks":[],"claims":[],"x":NaN}'])
def test_parser_never_repairs_partial_json_or_drops_duplicate_members(raw):
    with pytest.raises(FinalLedgerError): parse_final_ledger(raw, draft(), depth='detailed')


def test_duplicate_nested_claim_member_is_not_silently_overwritten():
    raw = json.dumps(review()).replace('"material": true', '"material": false, "material": true', 1)
    with pytest.raises(FinalLedgerError) as error:
        parse_final_ledger(raw, draft(), depth='detailed')
    assert error.value.code == 'duplicate_json_key'


def test_strict_parser_preserves_raw_and_returns_the_same_validated_body():
    raw = json.dumps(review(), ensure_ascii=False)
    with bind_source_references([TranscriptSegment(0, 9, RAW)]):
        result = parse_final_ledger(raw, draft(), depth='detailed')
    assert result.markdown == RAW and raw == json.dumps(review(), ensure_ascii=False)


@pytest.fixture
def visual(tmp_path):
    from PIL import Image
    path = tmp_path / 'synthetic.jpg'
    Image.new('RGB', (32, 32), 'white').save(path)
    return VideoEvidence(9, [VideoFrameEvidence(1, path, ['timeline'], [1],
                         'Valve Q stays closed. Valve Q stays closed.', 'recognized')], 9, True)


def test_actual_ocr_repetition_uses_ocr_offsets_not_asr_offsets(visual):
    value = review()
    value['claims'][0]['evidence'] = [{'kind': 'ocr_span', 'source_ref': '[FRAME:0001]',
                                      'quote': 'Valve Q stays closed.'}]
    with bind_video_material(visual, {'vision': False}):
        fails('invalid_final_evidence', value)
        value['claims'][0]['evidence'][0].update(start=0, end=len('Valve Q stays closed.'))
        assert run(value).claims[0]['evidence'][0]['verification'] == 'exact_ocr_span'
        visual.frames[0].ocr_status = 'unavailable'
        fails('invalid_final_evidence', value)


@pytest.mark.parametrize('vision', [True, False])
def test_frame_observation_requires_actual_image_input_and_never_claims_ocr(visual, vision):
    value = review()
    value['claims'][0]['evidence'] = [{'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
                                      'observation': 'A synthetic white field', 'verification': 'exact_ocr_span'}]
    with bind_video_material(visual, {'vision': vision}):
        if vision:
            assert run(value).claims[0]['evidence'][0]['verification'] == 'model_visual_observation'
        else:
            fails('invalid_final_evidence', value)


@pytest.mark.parametrize('protocol', [1, 2, 4, True])
def test_draft_protocol_selection_is_explicit_and_not_a_legacy_upgrade(protocol):
    material = draft()
    material['protocol'] = protocol
    fails('invalid_draft_protocol', material=material)


def test_legacy_v3_host_still_rejects_protocol_four_instead_of_dispatching_it():
    with bind_source_references([TranscriptSegment(0, 9, RAW)]), presentation_scope('detailed', 'text'):
        with pytest.raises(ValueError):
            finalize_fact_review(json.dumps(review()), json.dumps(draft()), RAW)


def test_prompt_example_is_one_ledger_without_independent_addition_accounting():
    example = json.loads(next(line for line in REVIEW_PROTOCOL.splitlines() if line.startswith('{')).rstrip('.'))
    assert set(example) == {'protocol', 'blocks', 'claims'} and example['protocol'] == 4
    assert list(example) == ['protocol', 'claims', 'blocks']
    assert REVIEW_PROTOCOL.count('Complete claims before blocks; their block_ids reference the report blocks that follow.') == 1
    assert all({'id', 'disposition', 'block_ids', 'evidence'} <= set(c) for c in example['claims'])
    assert 'complete original speech' in REVIEW_PROTOCOL
    assert 'end is exclusive' in REVIEW_PROTOCOL
    assert 'material=true' in REVIEW_PROTOCOL
    assert 'No extra extraction' in REVIEW_PROTOCOL
