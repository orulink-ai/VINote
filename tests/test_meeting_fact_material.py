"""Executable material/audit contracts with synthetic facts, never answer keys."""
import json
import pytest
from app.llm.meeting_presentation import presentation_scope


def material():
    return {'topics': [{'id': 'T001', 'title': 'Synthetic proposal'}], 'facts': [
        {'id': 'F001', 'topic_id': 'T001', 'subject': 'sample panel', 'relation': 'proposed power',
         'object': '3 watts', 'qualifiers': ['only while open'], 'status': 'proposal',
         'source_refs': ['[ASR:0001]'], 'material': True}],
        'coverage': [{'source_ref': '[ASR:0001]', 'fact_ids': ['F001'], 'reason': ''}]}


def review():
    passage = 'The panel proposal uses 3 watts only while open.'
    return {'markdown': '# Panel proposal\n\n' + passage,
        'audit': [{'fact_id': 'F001', 'disposition': 'included', 'passage': passage, 'reason': ''}],
        'topic_audit': [{'topic_id': 'T001', 'passage': passage, 'reason': ''}], 'figures': []}


def test_coverage_and_exact_relationship_passages_are_required():
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    source = '[ASR:0001] sample panel: proposed 3 watts only while open'
    with presentation_scope('detailed', 'text'):
        draft = prepare_fact_material(json.dumps(material()), source)
        assert finalize_fact_review(json.dumps(review()), draft, source) == review()['markdown']
        missing = material(); missing['coverage'] = []
        with pytest.raises(ValueError): prepare_fact_material(json.dumps(missing), source)
        missing = review(); missing['audit'] = []
        with pytest.raises(ValueError): finalize_fact_review(json.dumps(missing), draft, source)
        bad = review(); bad['audit'][0]['passage'] = 'not in returned report'
        with pytest.raises(ValueError): finalize_fact_review(json.dumps(bad), draft, source)


@pytest.mark.parametrize('proof_kind', ['fact', 'topic'])
@pytest.mark.parametrize(('body', 'topic'), [
    ('First condition.\n\nNext stage.', 'First condition. Next stage.'),
    ('First\tcondition.\r\nNext stage.', ' First condition.  Next stage. '),
    ('满足条件后发出通知。\n\n下阶段再次检查。', '满足条件后发出通知。下阶段再次检查。'),
    ('重新\n检查后，再执行。', '重新检查后，再执行。'),
    ('First\u00a0condition.', 'First condition.'),
])
def test_proof_quote_allows_layout_whitespace_without_changing_body(body, topic, proof_kind):
    from app.llm.meeting_fact_material import finalize_fact_review
    candidate = review()
    candidate['markdown'] = body
    candidate['audit'][0]['passage'] = body
    candidate['topic_audit'][0]['passage'] = body
    candidate['audit' if proof_kind == 'fact' else 'topic_audit'][0]['passage'] = topic
    raw = json.dumps(candidate)
    with presentation_scope('detailed', 'text') as state:
        assert finalize_fact_review(raw, json.dumps(material()), '[ASR:0001] source') == body
        assert state.raw_review == raw


@pytest.mark.parametrize('proof_kind', ['fact', 'topic'])
@pytest.mark.parametrize(('body', 'topic'), [
    ('Sample AB stays separate.', 'Sample A B stays separate.'),
    ('The value is 17.25 units.', 'The value is 17. 25 units.'),
    ('The value is 17.25 units.', 'The value is 17.35 units.'),
    ('A sends to B.', 'B sends to A.'),
    ('Only after approval, send.', 'Send.'),
    ('本阶段检查。后续执行。', '后续执行。本阶段检查。'),
    ('Check now. Unrelated insertion. Then send.', 'Check now. Then send.'),
    ('本阶段检查；后续执行。', '本阶段检查，后续执行。'),
    ('The report includes a proposal.', 'The report includes a proposal. Access has been granted.'),
])
def test_proof_quote_does_not_normalize_changed_words_numbers_relations_or_gaps(body, topic, proof_kind):
    from app.llm.meeting_fact_material import finalize_fact_review
    candidate = review()
    candidate['markdown'] = body
    candidate['audit'][0]['passage'] = body
    candidate['topic_audit'][0]['passage'] = body
    candidate['audit' if proof_kind == 'fact' else 'topic_audit'][0].update(passage=topic, reason='A reason cannot rescue a nonmatching quote')
    with presentation_scope('detailed', 'text'), pytest.raises(ValueError):
        finalize_fact_review(json.dumps(candidate), json.dumps(material()), '[ASR:0001] source')


@pytest.mark.parametrize('reason', ['', '  \n', None, 7])
def test_topic_reason_requires_a_nonempty_string(reason):
    from app.llm.meeting_fact_material import finalize_fact_review
    candidate = review()
    candidate['audit'][0].update(disposition='rejected', passage='', reason='Source does not establish the candidate')
    candidate['topic_audit'][0].update(passage='', reason=reason)
    with presentation_scope('detailed', 'text'), pytest.raises(ValueError):
        finalize_fact_review(json.dumps(candidate), json.dumps(material()), '[ASR:0001] source')


def test_topic_reason_is_only_an_alternative_when_no_fact_is_included():
    from app.llm.meeting_fact_material import finalize_fact_review
    candidate = review()
    candidate['topic_audit'][0].update(passage='', reason='All working candidates were unsupported')
    with presentation_scope('detailed', 'text'):
        with pytest.raises(ValueError):
            finalize_fact_review(json.dumps(candidate), json.dumps(material()), '[ASR:0001] source')
        candidate['audit'][0].update(disposition='rejected', passage='', reason='Source does not establish the candidate')
        assert finalize_fact_review(json.dumps(candidate), json.dumps(material()), '[ASR:0001] source') == candidate['markdown']


def test_fact_proof_layout_tolerance_preserves_raw_review_and_does_not_rewrite_markdown():
    from app.llm.meeting_fact_material import finalize_fact_review
    candidate = review()
    candidate['markdown'] = 'First condition.\n\nNext stage.'
    candidate['audit'][0]['passage'] = 'First condition. Next stage.'
    candidate['topic_audit'][0]['passage'] = candidate['markdown']
    raw = json.dumps(candidate)
    with presentation_scope('detailed', 'text') as state:
        assert finalize_fact_review(raw, json.dumps(material()), '[ASR:0001] source') == candidate['markdown']
        assert state.raw_review == raw


@pytest.mark.parametrize('anchor_kind', ['layout-only-difference', 'duplicate-exact-anchor'])
def test_topic_layout_normalization_never_applies_to_figure_anchors(tmp_path, anchor_kind):
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    from app.llm.video_material import bind_video_material
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    evidence = VideoEvidence(10, [VideoFrameEvidence(0, tmp_path / 'unused.jpg',
        ['timeline'], [0], 'synthetic proposal', 'recognized')], 10, True)
    facts, candidate = material(), review()
    facts['facts'][0]['source_refs'].append('[FRAME:0001]')
    facts['coverage'].append({'source_ref': '[FRAME:0001]', 'fact_ids': ['F001'], 'reason': ''})
    paragraph = '满足条件后再检查。\n\n下一阶段通知。'
    candidate['markdown'] = paragraph if anchor_kind == 'layout-only-difference' else paragraph + '\n\n' + paragraph
    candidate['audit'][0]['passage'] = paragraph
    candidate['topic_audit'][0]['passage'] = paragraph.replace('\n\n', '')
    candidate['figures'] = [{'frame_ref': '[FRAME:0001]', 'fact_ids': ['F001'],
        'after_passage': paragraph.replace('\n\n', '') if anchor_kind == 'layout-only-difference' else paragraph,
        'caption': 'Synthetic proposal'}]
    with bind_video_material(evidence, {'vision': False}), presentation_scope('detailed', 'illustrated') as state:
        draft = prepare_fact_material(json.dumps(facts), '[ASR:0001] source')
        with pytest.raises(ValueError):
            finalize_fact_review(json.dumps(candidate), draft, '[ASR:0001] source')
        assert state.figures == []


def test_detailed_cannot_silently_omit_material_fact_and_brief_requires_reason():
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    source = '[ASR:0001] synthetic source'
    draft = prepare_fact_material(json.dumps(material()), source)
    candidate = review(); candidate['audit'][0].update(disposition='omitted_for_depth', passage='', reason='secondary detail')
    with presentation_scope('detailed', 'text'), pytest.raises(ValueError):
        finalize_fact_review(json.dumps(candidate), draft, source)
    with presentation_scope('brief', 'text'):
        assert finalize_fact_review(json.dumps(candidate), draft, source)


def test_unknown_frame_or_unbound_fact_is_not_an_illustration():
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    source = '[ASR:0001] synthetic source'
    draft = prepare_fact_material(json.dumps(material()), source)
    candidate = review(); candidate['figures'] = [{'frame_ref': '[FRAME:9999]', 'fact_ids': ['F001'],
        'after_passage': review()['audit'][0]['passage'], 'caption': 'Synthetic panel'}]
    with presentation_scope('detailed', 'illustrated'), pytest.raises(ValueError):
        finalize_fact_review(json.dumps(candidate), draft, source)


def test_irrelevant_sources_empty_facts_single_topic_and_extension_fields_are_legal():
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    source = '[ASR:0001] synthetic silence label'
    empty = {'topics': [], 'facts': [], 'coverage': [{'source_ref': '[ASR:0001]', 'fact_ids': [], 'reason': 'No substantive proposition'}], 'extension': {'future': True}}
    draft = prepare_fact_material(json.dumps(empty), source)
    with presentation_scope('brief', 'text'):
        assert finalize_fact_review(json.dumps({'markdown': '# 无实质议题', 'audit': [], 'topic_audit': [], 'figures': []}), draft, source)
    extended = material(); extended['facts'][0]['extension'] = 'allowed'
    assert prepare_fact_material(json.dumps(extended), source)
    extended['facts'][0]['source_refs'] = ['[ASR:9999]']
    with pytest.raises(ValueError): prepare_fact_material(json.dumps(extended), source)


def test_raw_review_is_retained_even_if_envelope_is_invalid():
    from app.llm.meeting_fact_material import finalize_fact_review
    with presentation_scope('brief', 'text') as state:
        with pytest.raises(ValueError): finalize_fact_review('not JSON', json.dumps(material()), '[ASR:0001] source')
        assert state.raw_review == 'not JSON'


def test_coverage_is_navigation_not_a_mirrored_evidence_graph():
    from app.llm.meeting_fact_material import prepare_fact_material
    source = '[ASR:0001] supported proposal\n[ASR:0002] related discussion'
    value = material()
    value['coverage'].append({'source_ref': '[ASR:0002]', 'fact_ids': ['F001'], 'reason': ''})
    normalized = json.loads(prepare_fact_material(json.dumps(value), source))
    assert normalized['facts'][0]['source_refs'] == ['[ASR:0001]']  # Never invent a support edge.
    assert normalized['coverage'] == value['coverage']
    value['coverage'][1]['fact_ids'] = ['invented-fact']
    with pytest.raises(ValueError): prepare_fact_material(json.dumps(value), source)
    value['coverage'][1] = {'source_ref': '[ASR:9999]', 'fact_ids': [], 'reason': 'unknown'}
    with pytest.raises(ValueError): prepare_fact_material(json.dumps(value), source)


def test_materiality_and_review_prompts_distinguish_relevance_from_output_depth():
    from app.llm.meeting_draft import build_meeting_draft_prompts
    from app.llm.meeting_review import build_meeting_review_prompts
    with presentation_scope('detailed', 'text'):
        draft = build_meeting_draft_prompts(title='Synthetic', source='FULL ORIGINAL INPUT', extras=None, output_language='en')
        checked = build_meeting_review_prompts(source='FULL ORIGINAL INPUT', draft='fallible working facts', extras=None, output_language='en')
    assert 'materiality is not certainty' in draft['system_prompt']
    assert 'capture controls, interface chrome' in draft['system_prompt']
    assert 'even when the draft marked material=true' in checked['system_prompt']
    assert 'non_meeting, incidental or garbled' in checked['system_prompt']
    assert 'Merged duplicates are included' in checked['system_prompt']
    assert 'not an unrelated neighboring paragraph' in checked['system_prompt']
    assert 'FULL ORIGINAL INPUT' in draft['user_prompt'] and 'FULL ORIGINAL INPUT' in checked['user_prompt']


def test_source_sweep_prioritizes_request_body_and_checks_uncertainty_at_the_base_relation():
    from app.llm.meeting_draft import build_meeting_draft_prompts
    from app.llm.meeting_review import build_meeting_review_prompts
    with presentation_scope('detailed', 'text'):
        draft = build_meeting_draft_prompts(title='Synthetic', source='COMPLETE SOURCE', extras=None, output_language='en')
        checked = build_meeting_review_prompts(source='COMPLETE SOURCE', draft='working candidates', extras=None, output_language='en')
    for prompts in (draft, checked):
        rules = prompts['system_prompt']
        assert 'Read the substantive body before its title, identifier or surrounding controls' in rules
        assert 'trigger, requested behavior, expected outcome and constraints' in rules
        assert 'uncertainty starts at the base event or object' in rules
        assert 'a request stays a request' in rules
        assert 'independent screen content does not need a spoken repetition' in rules
        assert 'COMPLETE SOURCE' in prompts['user_prompt']


def test_both_calls_preserve_relational_dimensions_numeric_bindings_and_independent_deadlines():
    from app.llm.meeting_draft import build_meeting_draft_prompts
    from app.llm.meeting_review import build_meeting_review_prompts
    source = 'Synthetic source: if the amber indicator remains lit, check again at the next stage. The unclear item must be ready before dawn. Variant Q shows 17.25 units; variant R shows 23 units. A sends to B; C reports back to A.'
    with presentation_scope('detailed', 'text'):
        calls = [build_meeting_draft_prompts(title='Synthetic', source=source, extras=None, output_language='en'),
                 build_meeting_review_prompts(source=source, draft='fallible candidates', extras=None, output_language='en')]
    for call in calls:
        assert source in call['user_prompt']
        rules = call['system_prompt']
        assert 'trigger -> action -> outcome' in rules
        assert 'source endpoint -> relation -> target endpoint' in rules
        assert 'with its object, unit, configuration, state and time role' in rules
        assert 'recheck exact characters, decimal/grouping signs and operators' in rules
        assert 'independently intelligible deadline' in rules
        assert 'compare the final sentence against both the original source and the working candidate' in rules


@pytest.mark.parametrize('category', ['non_meeting', 'incidental', 'garbled'])
def test_review_can_reject_fallible_material_flag_with_source_reason(category):
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    source = '[ASR:0001] supported synthetic proposal\n[ASR:0002] incidental or unclear fragment'
    value = material()
    value['facts'].append({**value['facts'][0], 'id': 'F002', 'subject': 'capture context',
        'relation': 'candidate fragment', 'object': 'uncertain incidental value', 'source_refs': ['[ASR:0002]'], 'material': True})
    value['coverage'].append({'source_ref': '[ASR:0002]', 'fact_ids': ['F002'], 'reason': ''})
    candidate = review()
    candidate['audit'].append({'fact_id': 'F002', 'disposition': 'rejected', 'passage': '',
        'reason': f'{category}: original source does not establish a substantive meeting proposition; the candidate was misclassified.'})
    with presentation_scope('detailed', 'text'):
        assert finalize_fact_review(json.dumps(candidate), prepare_fact_material(json.dumps(value), source), source) == review()['markdown']
        candidate['audit'][1]['reason'] = ''
        with pytest.raises(ValueError): finalize_fact_review(json.dumps(candidate), json.dumps(value), source)


def test_merged_duplicate_material_facts_share_an_included_final_passage():
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    value = material()
    value['facts'].append({**value['facts'][0], 'id': 'F002'})
    value['coverage'][0]['fact_ids'].append('F002')
    candidate = review()
    candidate['audit'].append({**candidate['audit'][0], 'fact_id': 'F002'})
    source = '[ASR:0001] synthetic proposal'
    with presentation_scope('detailed', 'text'):
        assert finalize_fact_review(json.dumps(candidate), prepare_fact_material(json.dumps(value), source), source) == review()['markdown']
        candidate['audit'][1].update(disposition='omitted_for_depth', passage='', reason='duplicate merged')
        with pytest.raises(ValueError): finalize_fact_review(json.dumps(candidate), json.dumps(value), source)


def test_incidental_frame_can_have_empty_coverage_without_manufacturing_a_business_fact(tmp_path):
    from app.llm.meeting_fact_material import prepare_fact_material
    from app.llm.video_material import bind_video_material
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    evidence = VideoEvidence(10, [
        VideoFrameEvidence(0, tmp_path / 'unused-1.jpg', ['timeline'], [0], 'synthetic relevant label', 'recognized'),
        VideoFrameEvidence(9, tmp_path / 'unused-2.jpg', ['timeline'], [9], 'incidental capture toolbar', 'recognized'),
    ], 10, True)
    value = material()
    value['facts'][0]['source_refs'].append('[FRAME:0001]')
    value['coverage'].extend([
        {'source_ref': '[FRAME:0001]', 'fact_ids': ['F001'], 'reason': ''},
        {'source_ref': '[FRAME:0002]', 'fact_ids': [], 'reason': 'Incidental capture chrome, not substantively discussed'},
    ])
    with bind_video_material(evidence, {'vision': False}):
        normalized = json.loads(prepare_fact_material(json.dumps(value), '[ASR:0001] synthetic proposal'))
    assert len(normalized['facts']) == 1
    assert normalized['coverage'][-1]['fact_ids'] == []


def test_automatic_two_call_pipeline_preserves_full_source_and_selects_a_real_frame(tmp_path):
    from PIL import Image
    from app.llm.openai_llm import _BasePromptLLM
    from app.models.transcript import TranscriptSegment
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    frame = tmp_path / 'source.jpg'
    Image.new('RGB', (10, 10)).save(frame)
    evidence = VideoEvidence(10, [VideoFrameEvidence(0, frame, ['timeline'], [0, 9], 'panel proposal: 3 watts only while open', 'recognized')], 10, True)
    passage = review()['audit'][0]['passage']
    facts = {'protocol': 2, 'topics': material()['topics'], 'facts': [{'id': 'F001', 'topic_id': 'T001', 'entity': None,
        'claims': [{'id': 'C1', 'field': 'quantity', 'text': passage, 'anchor': '3 watts', 'material': True,
            'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': passage},
                         {'kind': 'ocr_span', 'source_ref': '[FRAME:0001]', 'quote': evidence.frames[0].ocr_text}]}]}]}
    checked = {'protocol': 2, 'blocks': [{'id': 'B1', 'markdown': passage}],
        'audit': [{'claim_id': 'C1', 'disposition': 'included', 'block_ids': ['B1']}],
        'figures': [{'frame_ref': '[FRAME:0001]', 'claim_ids': ['C1'], 'after_block_id': 'B1', 'caption': 'Panel power proposal'}]}
    facts = {'protocol': 3, 'topics': facts['topics'], 'claims': [{**claim, 'topic_id': fact['topic_id']} for fact in facts['facts'] for claim in fact['claims']]}
    checked = {'protocol': 4, 'blocks': checked['blocks'], 'figures': checked['figures'], 'claims': [
        {key: value for key, value in claim.items() if key not in {'topic_id', 'anchor'}}
        | {'disposition': 'included', 'block_ids': ['B1']} for claim in facts['claims']]}
    class AutomaticLLM(_BasePromptLLM):
        def __init__(self): self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            return json.dumps(facts if len(self.calls) == 1 else checked)
    llm = AutomaticLLM()
    with presentation_scope('detailed', 'illustrated') as state:
        result = llm.summarize('Synthetic meeting', [TranscriptSegment(0, 10, 'The panel proposal uses 3 watts only while open.')],
            style='meeting', video_evidence=evidence)
    assert len(llm.calls) == 2 and len(state.figures) == 1
    assert '[FRAME:0001]' in result and passage in result
    assert all('3 watts only while open' in call['user_prompt'] for call in llm.calls)
    assert state.raw_review == json.dumps(checked)
