"""New draft3 -> review4 hosts and renderers; no providers or ASR calls."""
import copy
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_final_review import finalize_final_review, review_protocol
from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_review import build_meeting_review_prompts
from app.llm.openai_llm import _BasePromptLLM
from app.llm.source_references import bind_source_references, capture_working_draft
from app.llm.video_material import bind_video_material
from app.models.transcript import TranscriptSegment
from app.services.summary_presentation_artifact import render_presentation
from app.services.summary_visual_artifact import reviewed_claim_sources, reviewed_visual_blocks
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence


SOURCE = 'Keep 34.625 kPa only while the gold interlock is closed.'
KINDS = ['text', 'html', 'illustrated', 'comic', 'infographic']


@pytest.fixture
def case(tmp_path):
    path = tmp_path / 'original.jpg'
    Image.new('RGB', (32, 24), 'white').save(path)
    evidence = VideoEvidence(10, [VideoFrameEvidence(1, path, ['timeline'], [1])], 10, True)
    evidence._summary_frame_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest()}
    frame = {'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
             'observation': 'The displayed limit is 34.625 kPa with the gold interlock closed.'}
    material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic interlock'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': SOURCE, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE}, frame]}]}
    value = {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': SOURCE}], 'claims': [
        {key: copy.deepcopy(item) for key, item in material['claims'][0].items() if key != 'topic_id'}
        | {'disposition': 'included', 'block_ids': ['B1']}]}
    return SimpleNamespace(**locals())


def response(c, presentation):
    value = copy.deepcopy(c.value)
    if presentation == 'illustrated':
        value['figures'] = [{'frame_ref': '[FRAME:0001]', 'claim_ids': ['C1'],
                             'after_block_id': 'B1', 'caption': 'Displayed pressure condition'}]
    elif presentation == 'comic':
        value['visual'] = {'scenes': [{'id': 'S1', 'block_ids': ['B1'], 'frame_id': '[FRAME:0001]',
                                      'grounded_label': SOURCE}], 'diagram': None}
    elif presentation == 'infographic':
        value['visual'] = {'scenes': [], 'diagram': {'kind': 'cards', 'edges': [],
            'nodes': [{'id': 'N1', 'block_ids': ['B1'], 'grounded_label': SOURCE}]}}
    return value


def finalize(c, value, presentation='text', depth='detailed'):
    with presentation_scope(depth, presentation) as state, \
            bind_source_references([TranscriptSegment(0, 10, SOURCE)]), bind_video_material(c.evidence, {'vision': True}):
        result = finalize_final_review(json.dumps(value), json.dumps(c.material))
        return result, state


@pytest.mark.parametrize('presentation', KINDS)
@pytest.mark.parametrize('depth', ['brief', 'concise', 'detailed'])
def test_all_new_hosts_keep_two_calls_full_source_raw4_and_real_rendering(case, monkeypatch, presentation, depth):
    c = case
    value = response(c, presentation)
    # A source omission is defined and accounted once, with no addition/audit table.
    value['claims'].append({**copy.deepcopy(value['claims'][0]), 'id': 'NEW1'})
    raw3, raw4 = json.dumps(c.material, indent=2), json.dumps(value, indent=2)
    before = copy.deepcopy(c.material)
    saved, observed = [], []
    monkeypatch.setattr('app.services.summary_visual_generation.save_summary_visual',
                        lambda *args: saved.append(args[-1]))

    class Automatic(_BasePromptLLM):
        def __init__(self):
            self.model = 'frozen-selected-model'
            self.configure_video_capabilities({'vision': True}, image_input_verified=True)
            self.calls = []

        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert SOURCE in prompts['user_prompt']
            assert self.model == 'frozen-selected-model'
            # Capture the actual production host's two prompts, beyond builder-only checks.
            for instruction in ('trace its tail continuously to its own arrowhead',
                                'decimal/grouping signs and operators',
                                'An explicitly continuing arrangement remains one event',
                                'A listing title is not the configuration of its selected offer',
                                'Evidence quotes remain unchanged'):
                assert prompts['system_prompt'].count(instruction) == 1
            self_contained = 'Never split an object and its values across independent nodes'
            assert prompts['system_prompt'].count(self_contained) == (
                1 if len(self.calls) == 2 and presentation == 'infographic' else 0)
            return raw3 if len(self.calls) == 1 else raw4

    automatic = Automatic()
    child = c.tmp_path / 'child'
    child.mkdir()
    with presentation_scope(depth, presentation) as state, capture_working_draft(observed.append):
        body = automatic.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)], style='meeting',
                                   video_evidence=c.evidence)
        from app.llm.meeting_presentation import final_depth_selection
        assert final_depth_selection(depth) in automatic.calls[1]['system_prompt']
        assert final_depth_selection(depth) not in automatic.calls[0]['system_prompt']
        assert state.raw_review == raw4
        context = SimpleNamespace(task_id=str(uuid4()), task_dir=child, user_id='fixture',
            presentation=presentation, video_evidence=c.evidence, presentation_figures=state.figures,
            presentation_visual=state.visual_review)
        rendered = render_presentation(None, context, body)
    assert len(automatic.calls) == 2 and observed == [raw3] and c.material == before
    assert 'PROTOCOL 3' in automatic.calls[0]['system_prompt']
    assert 'PROTOCOL 4' in automatic.calls[1]['system_prompt']
    assert hashlib.sha256(c.path.read_bytes()).hexdigest() == c.evidence._summary_frame_hashes[c.path]
    if presentation == 'illustrated':
        assert '![Displayed pressure condition' in rendered and '[FRAME:' not in rendered
        assert (child / 'screenshots/summary-source-0.jpg').read_bytes() == c.path.read_bytes()
    else:
        assert rendered == SOURCE
    if presentation in {'comic', 'infographic'}:
        assert state.visual_review['review'] == value and 'audit' not in state.visual_review['review']
        assert state.visual_review['claim_sources'] == reviewed_claim_sources(value)
        assert saved[0]['blocks'][0]['claim_ids'] == ['C1', 'NEW1']
        assert bool(saved[0]['frames']) == (presentation == 'comic')
    else:
        assert state.visual_review is None and not saved


@pytest.mark.parametrize('presentation', KINDS)
@pytest.mark.parametrize('error', ['unknown_field', 'missing_original', 'lower_material', 'wrong_evidence', 'duplicate_json'])
def test_failed_host_keeps_raw_without_any_partial_graphic_completion(case, presentation, error):
    c = case
    value = response(c, presentation)
    if error == 'unknown_field': value['audit'] = []
    if error == 'missing_original': value['claims'][0]['id'] = 'RENAMED'
    if error == 'lower_material': value['claims'][0].update(material=False, disposition='omitted_for_depth', block_ids=[], reason='Shorten')
    if error == 'wrong_evidence': value['claims'][0]['evidence'][0]['quote'] = 'Not supplied'
    raw = json.dumps(value)
    if error == 'duplicate_json': raw = raw.replace('"protocol": 4', '"protocol": 4, "protocol": 4')
    with presentation_scope('detailed', presentation) as state, \
            bind_source_references([TranscriptSegment(0, 10, SOURCE)]), bind_video_material(c.evidence, {'vision': True}):
        with pytest.raises(ValueError): finalize_final_review(raw, json.dumps(c.material))
        assert state.raw_review == raw and state.figures == [] and state.visual_review is None


@pytest.mark.parametrize('presentation', KINDS)
def test_only_the_declared_required_host_extension_is_allowed(case, presentation):
    value = response(case, presentation)
    if presentation in {'text', 'html'}:
        value['figures'] = []
    elif presentation == 'illustrated':
        value.pop('figures')
    else:
        value.pop('visual')
    with pytest.raises(FinalLedgerError) as error:
        finalize(case, value, presentation)
    assert error.value.code == 'invalid_host_envelope'


@pytest.mark.parametrize('change', ['empty', 'unknown_block', 'unknown_claim', 'wrong_frame', 'duplicate_frame', 'extra_field'])
def test_illustrated_never_invents_a_default_picture(case, change):
    value = response(case, 'illustrated')
    figure = value['figures'][0]
    if change == 'empty': value['figures'] = []
    if change == 'unknown_block': figure['after_block_id'] = 'B9'
    if change == 'unknown_claim': figure['claim_ids'] = ['C9']
    if change == 'wrong_frame': figure['frame_ref'] = '[FRAME:0002]'
    if change == 'duplicate_frame': value['figures'].append(copy.deepcopy(figure))
    if change == 'extra_field': figure['url'] = 'https://invalid.test/other.jpg'
    with pytest.raises(FinalLedgerError): finalize(case, value, 'illustrated')


@pytest.mark.parametrize('presentation', KINDS)
def test_actual_prompt_example_matches_host_schema_and_preserves_full_source_rules(case, presentation):
    contract = review_protocol(presentation)
    example = json.loads(next(line for line in contract.splitlines() if line.startswith('{')).rstrip('.'))
    expected = {'protocol', 'blocks', 'claims'}
    if presentation == 'illustrated': expected.add('figures')
    if presentation in {'comic', 'infographic'}: expected.add('visual')
    assert set(example) == expected and example['protocol'] == 4
    with presentation_scope('detailed', presentation):
        prompts = build_meeting_review_prompts(source=SOURCE, draft=json.dumps(case.material), extras=None, output_language='zh-CN')
    rules = prompts['system_prompt']
    assert SOURCE in prompts['user_prompt']
    for fragment in ['Only speaker labels explicitly attached', 'Check omissions as well as false claims',
                     'PRESERVE RELATIONAL DIMENSIONS', 'zero-based Python-character', 'never an ASR window',
                     'Detailed output cannot omit a material=true claim', 'complete original speech']:
        assert fragment in rules
    for fragment in ['This core ledger has no', 'protocol-3 blocks/audit', 'Keep figures=[]',
                     'coverage fact_ids', 'included audit passage']:
        assert fragment not in rules


def test_new_host_refuses_a_protocol_three_response_without_rewriting_it(case):
    value = {'protocol': 3, 'blocks': case.value['blocks'], 'claims': case.value['claims']}
    with pytest.raises(FinalLedgerError) as error:
        finalize(case, value)
    assert error.value.code == 'invalid_protocol'


def test_v4_block_and_source_projection_never_mutates_raw(case):
    value = response(case, 'comic')
    value['blocks'][0]['markdown'] = '\n ' + SOURCE + '\n'
    original = json.dumps(value, indent=2)
    assert reviewed_visual_blocks(value) == [{'id': 'B1', 'text': SOURCE, 'claim_ids': ['C1']}]
    assert reviewed_claim_sources(value) == {'C1': ['[ASR:0001]', '[FRAME:0001]']}
    assert json.dumps(value, indent=2) == original


@pytest.mark.parametrize('presentation', KINDS)
@pytest.mark.parametrize('duplicate', ['material', 'field', 'source_ref', 'quote', 'evidence'])
def test_actual_host_rejects_raw_draft_duplicate_members_before_normalization(case, presentation, duplicate):
    c = case
    raw = json.dumps(c.material)
    if duplicate == 'material':
        raw = raw.replace('"material": true', '"material": true, "material": false', 1)
    elif duplicate == 'field':
        raw = raw.replace('"field": "condition"', '"field": "condition", "field": "entity"', 1)
    elif duplicate == 'source_ref':
        raw = raw.replace('"source_ref": "[ASR:0001]"',
                          '"source_ref": "[ASR:9999]", "source_ref": "[ASR:0001]"', 1)
    elif duplicate == 'quote':
        raw = raw.replace('"quote": ' + json.dumps(SOURCE),
                          '"quote": "Invented", "quote": ' + json.dumps(SOURCE), 1)
    else:
        raw = raw.replace('"evidence": [', '"evidence": [], "evidence": [', 1)
    malicious_review = response(c, presentation)
    malicious_review['claims'][0].update(material=False, disposition='omitted_for_depth',
                                        block_ids=[], evidence=[], reason='Shorten')

    class Automatic(_BasePromptLLM):
        def __init__(self):
            self.calls = []

        def _complete(self, **prompts):
            self.calls.append(prompts)
            return raw if len(self.calls) == 1 else json.dumps(malicious_review)

    automatic, observed = Automatic(), []
    with presentation_scope('detailed', presentation) as state, capture_working_draft(observed.append):
        with pytest.raises(FinalLedgerError) as error:
            automatic.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)], style='meeting')
        assert error.value.code == 'duplicate_json_key'
        assert state.raw_review is None and state.visual_review is None and state.figures == []
    assert len(automatic.calls) == 1 and observed == [raw]
