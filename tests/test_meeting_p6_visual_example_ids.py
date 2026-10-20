"""P6 envelope examples only: ID hints never change schema or admission rules."""
import copy
import json
import re
from contextlib import nullcontext

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_final_review import review_protocol
from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_review import build_meeting_review_prompts
from app.llm.meeting_visual_projection6 import core_review6
from app.llm.meeting_visual_review import visual_review_instructions


def example(rules):
    lines = rules.splitlines()
    index = next(i for i, line in enumerate(lines) if 'FINAL CLAIM LEDGER PROTOCOL ' in line)
    return json.loads(lines[index + 1].removesuffix('.'))


def visual_row(value, kind):
    return value['visual']['scenes'][0] if kind == 'comic' else value['visual']['diagram']['nodes'][0]


@pytest.mark.parametrize('kind,identifier', [('comic', 'VS1'), ('infographic', 'VN1')])
def test_new_p6_envelope_example_has_isolated_visual_ids_only(kind, identifier):
    six = example(review_protocol(kind, protocol=6))
    four = example(review_protocol(kind, protocol=4))
    assert six['protocol'] == 6 and six['visual']['protocol'] == 3
    assert visual_row(six, kind)['id'] == identifier
    assert six['blocks'] == [{'id': b['id'], 'parts': [b['markdown']]} for b in four['blocks']]
    assert six['claims'] == four['claims']
    assert visual_row(six, kind)['label_ref'] == {'block_id': 'B1', 'part_index': 0, 'claim_ids': ['C1']}
    if kind == 'infographic':
        # This file has a cards example, not an edge example. Never manufacture
        # an edge merely to introduce VE1 or alter the example's presentation.
        assert six['visual']['diagram']['kind'] == 'cards'
        assert six['visual']['diagram']['edges'] == []


@pytest.mark.parametrize('kind,identifier', [('comic', 'S1'), ('infographic', 'N1')])
@pytest.mark.parametrize('version', [4, 5])
def test_historical_examples_keep_their_exact_schema_and_visual_id(kind, identifier, version):
    value = example(review_protocol(kind, protocol=version))
    assert value['protocol'] == version
    assert visual_row(value, kind)['id'] == identifier
    if version == 4:
        assert set(value['blocks'][0]) == {'id', 'markdown'}
        assert set(value['visual']) == {'scenes', 'diagram'}
        assert set(visual_row(value, kind)) == ({'id', 'frame_id', 'block_ids', 'grounded_label'}
            if kind == 'comic' else {'id', 'block_ids', 'grounded_label'})
    else:
        assert value['visual']['protocol'] == 2
        assert value['blocks'][0]['parts'] == [{'id': 'P1', 'text': example(review_protocol(kind, protocol=4))['blocks'][0]['markdown']}]
        assert visual_row(value, kind)['label_ref'] == {'part_id': 'P1', 'claim_ids': ['C1']}


@pytest.mark.parametrize('kind', ['comic', 'infographic'])
def test_new_example_can_coexist_with_new_claim_n1_but_global_collisions_still_fail(kind):
    value = example(review_protocol(kind, protocol=6))
    new = copy.deepcopy(value['claims'][0]); new['id'] = 'N1'
    value['claims'].append(new)
    assert core_review6(value)['claims'][-1]['id'] == 'N1'
    new['id'] = visual_row(value, kind)['id']
    before = copy.deepcopy(value)
    with pytest.raises(FinalLedgerError) as error:
        core_review6(value)
    assert error.value.code == 'invalid_visual_reference_ids'
    assert value == before


@pytest.mark.parametrize('kind,identifier', [('comic', 'VS1'), ('infographic', 'VN1')])
def test_actual_structured_review_builder_uses_prefixed_envelope_example(kind, identifier):
    with presentation_scope('concise', kind) as state:
        prompts = build_meeting_review_prompts(source='Synthetic unchanged original material.',
            draft='Synthetic fallible draft.', extras=None, output_language='en')
    assert state.expected_review_protocol == 6
    value = example(prompts['system_prompt'])
    assert visual_row(value, kind)['id'] == identifier
    assert 'Synthetic unchanged original material.' in prompts['user_prompt']


@pytest.mark.parametrize('kind', ['comic', 'infographic'])
def test_complete_p6_prompt_examples_and_endpoint_refs_are_consistently_prefixed(kind):
    with presentation_scope('concise', kind):
        rules = build_meeting_review_prompts(source='Synthetic original material.',
            draft='Synthetic draft.', extras=None, output_language='en')['system_prompt']
    # Inspect visual contexts; shared claim examples may legitimately use N1.
    layout = rules.split('FINAL/6 STRING PARTS AND VISUAL-REF/3.', 1)[1]
    assert not re.search(r'"(?:id|from|to)"\s*:\s*"(?:N[12]|E1|S1)"', layout)
    assert visual_row(example(rules), kind)['id'] == ('VS1' if kind == 'comic' else 'VN1')
    if kind == 'comic':
        assert re.findall(r'"id"\s*:\s*"VS1"', rules) == ['"id":"VS1"'] * 2
    else:
        assert len(re.findall(r'"id"\s*:\s*"VN1"', rules)) == 2
        assert len(re.findall(r'"id"\s*:\s*"VE1"', rules)) == 1
        assert '"from":"VN1","to":"VN2"' in rules
    # The change is an example convention, not a schema requirement or repair.
    assert 'All block/claim/scene/node/edge IDs retain their global uniqueness' in rules


@pytest.mark.parametrize('kind', ['comic', 'infographic'])
def test_p6_wrapper_preserves_pure_constants_and_historical_visual_rules(kind):
    from app.llm.meeting_visual_projection6 import PARTS_RULE6, COMIC_RULE6, INFO_RULE6
    from app.llm.meeting_visual_projection import PARTS_RULE, COMIC_RULE, INFO_RULE
    original = COMIC_RULE6 if kind == 'comic' else INFO_RULE6
    transformed = original
    for old, new in [('S1', 'VS1'), ('N1', 'VN1'), ('N2', 'VN2'), ('E1', 'VE1')]:
        transformed = transformed.replace('"' + old + '"', '"' + new + '"')
    assert visual_review_instructions(kind, protocol=6) == '\n' + PARTS_RULE6 + '\n' + transformed
    assert visual_review_instructions(kind, protocol=5) == '\n' + PARTS_RULE + '\n' + (COMIC_RULE if kind == 'comic' else INFO_RULE)
    for version in (3, 4):
        historical = visual_review_instructions(kind, protocol=version)
        assert ('"id":"S1"' if kind == 'comic' else '"id":"N1"') in historical
        assert not re.search(r'"(?:id|from|to)":"V[NSE]\d+"', historical)


@pytest.mark.parametrize('kind', ['comic', 'infographic'])
def test_real_vilab_two_stage_adapter_second_system_contains_only_prefixed_visual_examples(
        tmp_path, monkeypatch, kind):
    from app.llm.vilab_llm import VILabLLM
    from app.models.transcript import TranscriptSegment
    source = 'Synthetic interlock remains closed until the violet check passes.'
    proof = [dict(kind='asr_span', source_ref='[ASR:0001]', quote=source)]
    draft = dict(protocol=3, topics=[dict(id='T1', title='Synthetic condition')], claims=[
        dict(id='C1', topic_id='T1', field='condition', text=source, material=True, evidence=proof)])
    if kind == 'comic':
        # No fabricated source frame is needed: this test captures the real
        # second request before finalization and then expects the real guard
        # to reject the absent comic layout, with no third model call.
        visual = dict(protocol=3, scenes=[], diagram=None)
    else:
        visual = dict(protocol=3, scenes=[], diagram=dict(kind='cards', nodes=[
            dict(id='VN1', label_ref=dict(block_id='B1', part_index=0, claim_ids=['C1']))], edges=[]))
    final = dict(protocol=6, blocks=[dict(id='B1', parts=[source])], claims=[
        dict(id='C1', field='condition', text=source, material=True, disposition='included', block_ids=['B1'], evidence=proof)], visual=visual)
    replies = [json.dumps(draft), json.dumps(final)]
    calls = []
    def request(self, owner, method, path, **kwargs):
        assert (owner, method, path) == ('synthetic-owner', 'POST', '/openai/v1/chat/completions')
        calls.append(copy.deepcopy(kwargs['json']))
        assert len(calls) <= 2
        return dict(choices=[dict(message=dict(content=replies[len(calls)-1]))])
    monkeypatch.setattr('app.services.vilab_cloud_service.VILabCloudService.request', request)
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    with presentation_scope('concise', kind) as state:
        llm = VILabLLM('synthetic-owner', 'synthetic-frozen-model')
        if kind == 'comic':
            with pytest.raises(FinalLedgerError):
                llm.summarize('Synthetic', [TranscriptSegment(0, 1, source)], style='meeting')
        else:
            assert llm.summarize('Synthetic', [TranscriptSegment(0, 1, source)], style='meeting') == source
        assert state.expected_review_protocol == 6 and state.raw_review == replies[1]
    assert len(calls) == 2
    second = calls[1]['messages'][0]['content']
    layout = second.split('FINAL/6 STRING PARTS AND VISUAL-REF/3.', 1)[1]
    assert not re.search(r'"(?:id|from|to)"\s*:\s*"(?:N[12]|E1|S1)"', layout)
    assert visual_row(example(second), kind)['id'] == ('VS1' if kind == 'comic' else 'VN1')
    assert ('"from":"VN1","to":"VN2"' in second) == (kind == 'infographic')
