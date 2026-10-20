"""Independent synthetic contracts; no real-meeting fixtures or provider calls."""
import copy
import json
from contextlib import contextmanager

import pytest

from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
from app.llm.meeting_presentation import presentation_scope
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment


RAW = 'Name possibly Talven, label unclear. Keep 43.875 kPa if the amber flag dims. Finish before the second bell.'


def span(quote=RAW, ref='[ASR:0001]'):
    return {'kind': 'asr_span', 'source_ref': ref, 'quote': quote}


def candidate():
    return {'protocol': 2, 'topics': [{'id': 'T7', 'title': 'Synthetic calibration'}], 'facts': [
        {'id': 'F8', 'topic_id': 'T7', 'entity': 'Talven', 'claims': [
            {'id': 'C1', 'field': 'entity', 'text': 'Tentative name Talven', 'anchor': 'Talven', 'material': True, 'evidence': [span()]},
            {'id': 'C2', 'field': 'quantity', 'text': 'Target pressure 43.875 kPa', 'anchor': '43.875 kPa', 'material': True, 'evidence': [span()]},
            {'id': 'C3', 'field': 'condition', 'text': 'Only if the amber flag dims', 'anchor': 'if the amber flag dims', 'material': True, 'evidence': [span()]},
            {'id': 'C4', 'field': 'deadline', 'text': 'Finish before the second bell', 'anchor': 'before the second bell', 'material': True, 'evidence': [span()]},
        ]}]}


def checked():
    return {'protocol': 2, 'blocks': [{'id': 'B9', 'markdown': 'For the unidentified item, keep 43.875 kPa if the amber flag dims; finish before the second bell.'}],
        'audit': [{'claim_id': 'C1', 'disposition': 'rejected', 'block_ids': [], 'reason_code': 'unclear_entity',
                   'reason': 'The original speaker explicitly marks the name uncertain.', 'evidence': [span()]},
                  *[{'claim_id': key, 'disposition': 'included', 'block_ids': ['B9']} for key in ('C2', 'C3', 'C4')]],
        'topic_audit': [{'topic_id': 'T7', 'block_ids': ['B9'], 'reason': ''}], 'figures': []}


@contextmanager
def inputs(raw=RAW):
    with bind_source_references([TranscriptSegment(0, 12, raw)]), presentation_scope('detailed', 'text') as state:
        yield state


def run(draft=None, review=None):
    draft = candidate() if draft is None else draft
    review = checked() if review is None else review
    return finalize_fact_review(json.dumps(review), prepare_fact_material(json.dumps(draft), '[ASR:0001] rendered'), '[ASR:0001] rendered')


def test_unknown_entity_rejection_keeps_independently_supported_quantity_condition_deadline():
    with inputs() as state:
        result = run()
        assert result == checked()['blocks'][0]['markdown']
        assert 'Talven' not in result and '43.875 kPa' in result and 'second bell' in result
        assert state.raw_review == json.dumps(checked())


@pytest.mark.parametrize('change', ['quote', 'reference', 'number_anchor', 'injected_metadata', 'invalid_offset', 'boolean_offset'])
def test_original_asr_binding_is_exact_and_never_uses_rendered_metadata(change):
    value = candidate()
    item = value['facts'][0]['claims'][1]
    if change == 'quote': item['evidence'] = [span(RAW.replace('43.875', '43.785'))]
    if change == 'reference': item['evidence'] = [span(ref='[ASR:0002]')]
    if change == 'number_anchor': item['anchor'] = '43.785 kPa'
    if change == 'injected_metadata': item.update(anchor='speaker_9', evidence=[span('speaker_9')])
    if change == 'invalid_offset': item['evidence'][0].update(start=1, end=len(RAW))
    if change == 'boolean_offset': item['evidence'][0].update(start=False, end=len(RAW))
    with inputs(), pytest.raises(ValueError):
        prepare_fact_material(json.dumps(value), '[ASR:0001] rendered speaker_9')


def test_missing_trusted_asr_binding_cannot_be_authorized_by_a_reference_in_model_text():
    with pytest.raises(ValueError):
        prepare_fact_material(json.dumps(candidate()), '[ASR:0001] ' + RAW)


def test_repeated_quote_needs_exact_offsets_not_fuzzy_matching():
    value = candidate()
    value['facts'][0]['entity'] = None
    value['facts'][0]['claims'] = [value['facts'][0]['claims'][1]]
    claim = value['facts'][0]['claims'][0]
    claim['evidence'] = [span('43.875 kPa')]
    raw = '43.875 kPa then 43.875 kPa'
    with inputs(raw):
        with pytest.raises(ValueError): prepare_fact_material(json.dumps(value), '[ASR:0001] ' + raw)
        claim['evidence'][0].update(start=0, end=len('43.875 kPa'))
        assert prepare_fact_material(json.dumps(value), '[ASR:0001] ' + raw)


@pytest.mark.parametrize('change', ['whole_fact_rejection', 'blank_rejection', 'unbound_rejection', 'entity_reason_for_number', 'missing_claim', 'unknown_block', 'duplicate_block', 'unknown_topic', 'detailed_omission'])
def test_partial_accounting_and_block_references_cannot_silently_drop_properties(change):
    value = checked()
    if change == 'whole_fact_rejection': value['audit'] = [{'fact_id': 'F8', 'disposition': 'rejected', 'reason': 'unclear entity'}]
    if change == 'blank_rejection': value['audit'][0]['reason'] = ' '
    if change == 'unbound_rejection': value['audit'][0]['evidence'] = []
    if change == 'entity_reason_for_number': value['audit'][1] = {**value['audit'][0], 'claim_id': 'C2'}
    if change == 'missing_claim': value['audit'].pop()
    if change == 'unknown_block': value['audit'][1]['block_ids'] = ['B404']
    if change == 'duplicate_block': value['blocks'].append(copy.deepcopy(value['blocks'][0]))
    if change == 'unknown_topic': value['topic_audit'][0]['topic_id'] = 'T404'
    if change == 'detailed_omission': value['audit'][1].update(disposition='omitted_for_depth', block_ids=[], reason='shorter report')
    with inputs(), pytest.raises(ValueError): run(review=value)


def test_unknown_entity_is_legal_without_an_entity_claim_and_no_fixed_fact_count():
    value, review = candidate(), checked()
    value['facts'][0]['entity'] = None
    value['facts'][0]['claims'].pop(0)
    review['audit'].pop(0)
    with inputs(): assert run(value, review) == review['blocks'][0]['markdown']
    empty = {'protocol': 2, 'topics': [], 'facts': []}
    result = {'protocol': 2, 'blocks': [{'id': 'B1', 'markdown': 'No substantive item.'}], 'audit': [], 'topic_audit': [], 'figures': []}
    with inputs(): assert run(empty, result) == 'No substantive item.'


def test_review_can_add_a_source_bound_property_missing_from_draft_without_an_extra_call():
    value, review = candidate(), checked()
    deadline = value['facts'][0]['claims'].pop()
    review['additional_facts'] = [{'id': 'F9', 'topic_id': 'T7', 'entity': None, 'claims': [deadline]}]
    with inputs(): assert run(value, review) == review['blocks'][0]['markdown']


def test_new_protocol_cannot_downgrade_to_unbound_v1():
    old = {'topics': [], 'facts': [], 'coverage': []}
    with pytest.raises(ValueError): prepare_fact_material(json.dumps(old), '', require_protocol=2)
    with inputs(), pytest.raises(ValueError): run(review={'markdown': 'Old shape', 'audit': [], 'topic_audit': [], 'figures': []})


def test_original_source_binding_is_nested_and_resets_without_leaking_between_meetings():
    from app.llm.source_references import original_asr_texts
    assert original_asr_texts() == {}
    with inputs():
        assert original_asr_texts()['[ASR:0001]'] == RAW
        with inputs('Other station Neris uses 68.125 volts.'):
            with pytest.raises(ValueError): prepare_fact_material(json.dumps(candidate()), '[ASR:0001] ' + RAW)
        assert original_asr_texts()['[ASR:0001]'] == RAW
    assert original_asr_texts() == {}


@pytest.mark.parametrize('kind', ['asr_span', 'ocr_span', 'frame_observation'])
def test_visual_observation_with_no_ocr_is_never_promoted_to_verified_text(tmp_path, kind):
    from app.llm.video_material import bind_video_material
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    from PIL import Image
    path = tmp_path / 'unreadable.jpg'
    Image.new('RGB', (24, 24)).save(path)
    evidence = VideoEvidence(12, [VideoFrameEvidence(1, path, ['timeline'], [1])], 1, True)
    value = candidate()
    value['facts'][0]['entity'] = None
    value['facts'][0]['claims'] = [value['facts'][0]['claims'][1]]
    claim = value['facts'][0]['claims'][0]
    claim['evidence'] = [{'kind': kind, 'source_ref': '[FRAME:0001]', 'quote': '43.875 kPa', 'observation': '43.875 kPa shown on the gauge'}]
    with inputs(), bind_video_material(evidence, {'vision': True}):
        if kind == 'frame_observation':
            prepared = json.loads(prepare_fact_material(json.dumps(value), 'source'))
            assert prepared['facts'][0]['claims'][0]['evidence'][0]['verification'] == 'model_visual_observation'
            claim['anchor'] = 'fabricated auxiliary text'
            claim['evidence'][0]['quote'] = claim['anchor']
            with pytest.raises(ValueError): prepare_fact_material(json.dumps(value), 'source')
        else:
            with pytest.raises(ValueError): prepare_fact_material(json.dumps(value), 'source')
    with pytest.raises(ValueError), inputs(), bind_video_material(evidence, {'vision': False}):
        prepare_fact_material(json.dumps(value), 'source')


@pytest.mark.parametrize('bad_placement', [False, 'unknown_block', 'duplicate_body', 'rejected_claim'])
def test_block_figures_translate_to_legacy_exact_anchor_only_after_validation(tmp_path, bad_placement):
    from app.llm.video_material import bind_video_material
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    from PIL import Image
    path = tmp_path / 'gauge.jpg'
    Image.new('RGB', (24, 24)).save(path)
    evidence = VideoEvidence(12, [VideoFrameEvidence(1, path, ['timeline'], [1])], 1, True)
    draft, review = candidate(), checked()
    draft['facts'][0]['claims'][1]['evidence'].append({'kind': 'frame_observation', 'source_ref': '[FRAME:0001]', 'observation': '43.875 kPa is visible'})
    review['figures'] = [{'frame_ref': '[FRAME:0001]', 'claim_ids': ['C2'], 'after_block_id': 'B9', 'caption': 'Gauge observation'}]
    if bad_placement == 'unknown_block': review['figures'][0]['after_block_id'] = 'B404'
    if bad_placement == 'duplicate_body': review['blocks'].append({'id': 'B10', 'markdown': review['blocks'][0]['markdown']})
    if bad_placement == 'rejected_claim': review['figures'][0]['claim_ids'] = ['C1']
    with bind_source_references([TranscriptSegment(0, 12, RAW)]), bind_video_material(evidence, {'vision': True}), presentation_scope('detailed', 'illustrated') as state:
        if bad_placement:
            with pytest.raises(ValueError): run(draft, review)
            assert state.figures == []
        else:
            assert run(draft, review).endswith('[FRAME:0001]')
            assert state.figures[0]['after_passage'] == review['blocks'][0]['markdown']
            assert state.figures[0]['fact_ids'] == ['F8']


def test_overlapping_occurrences_are_ambiguous_without_offsets():
    value = candidate()
    value['facts'][0].update(entity=None, claims=[value['facts'][0]['claims'][1]])
    value['facts'][0]['claims'][0].update(anchor='aa', evidence=[span('aa')])
    with inputs('aaa'), pytest.raises(ValueError): prepare_fact_material(json.dumps(value), '[ASR:0001] aaa')


def test_two_concurrent_meetings_each_use_exactly_two_calls_and_their_own_sources():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.llm.openai_llm import _BasePromptLLM
    from app.llm.source_references import original_asr_texts, capture_working_draft
    rendezvous = Barrier(2)
    def worker(number):
        raw = RAW.replace('43.875', number)
        draft = json.loads(json.dumps(candidate()).replace('43.875', number))
        review = json.loads(json.dumps(checked()).replace('43.875', number))
        draft = {'protocol': 3, 'topics': draft['topics'], 'claims': [{**claim, 'topic_id': fact['topic_id']} for fact in draft['facts'] for claim in fact['claims']]}
        review['protocol'] = 3
        class Automatic(_BasePromptLLM):
            def __init__(self): self.calls = []
            def _complete(self, **prompts):
                self.calls.append(prompts)
                assert raw in prompts['user_prompt']
                assert original_asr_texts() == {'[ASR:0001]': raw}
                if len(self.calls) == 1:
                    rendezvous.wait(timeout=5)
                    return json.dumps(draft)
                return json.dumps(review)
        llm, observed = Automatic(), []
        with presentation_scope('detailed', 'text') as state, capture_working_draft(observed.append):
            result = llm.summarize('Synthetic calibration', [TranscriptSegment(0, 12, raw)], style='meeting')
            assert state.raw_review == json.dumps(review)
        assert len(llm.calls) == 2 and observed == [json.dumps(draft)]
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(worker, ['43.875', '92.625']))
    assert '43.875' in first and '92.625' not in first
    assert '92.625' in second and '43.875' not in second
    assert original_asr_texts() == {}
