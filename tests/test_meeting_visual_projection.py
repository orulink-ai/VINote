"""Synthetic final5 reference boundaries. No execution, inference or repair."""
import copy
import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError, decode_final_review
from app.llm.meeting_final_review import validate_review_envelope
from app.llm.meeting_visual_projection import core_review5, project_review5
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment


TEXT = 'Enable beta only after the gate passes.'


def example(presentation='infographic'):
    evidence = [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': TEXT}]
    claim = dict(id='C1', field='condition', text='Claim prose is deliberately NOT the body.', material=True,
                 disposition='included', block_ids=['B1'], evidence=evidence)
    value = dict(protocol=5, blocks=[dict(id='B1', parts=[dict(id='P1', text=TEXT)])], claims=[claim],
                 visual=dict(protocol=2, scenes=[], diagram=dict(kind='cards', nodes=[
                     dict(id='N1', label_ref=dict(part_id='P1', claim_ids=['C1']))], edges=[])))
    if presentation == 'comic':
        claim['evidence'].append(dict(kind='frame_observation', source_ref='[FRAME:0001]', observation='Visible gate condition'))
        value['visual'].update(scenes=[dict(id='S1', frame_id='[FRAME:0001]',
            label_ref=dict(part_id='P1', claim_ids=['C1']))], diagram=None)
    return value


def ref(value):
    return value['visual']['diagram']['nodes'][0]['label_ref']


def test_exact_parts_once_whole_reference_not_claim_text_and_detached():
    value = example()
    value['blocks'][0]['parts'] = [dict(id='prefix', text='Context. '), dict(id='P1', text=TEXT)]
    before = copy.deepcopy(value)
    core, plan = project_review5(value, presentation='infographic')
    assert core['blocks'] == [dict(id='B1', markdown='Context. ' + TEXT)]
    assert plan['diagram']['nodes'][0] == dict(id='N1', block_ids=['B1'], grounded_label=TEXT)
    assert value == before
    core['claims'][0]['text'] = 'changed detached copy'
    assert value == before


@pytest.mark.parametrize('text', ['a'*120, '😀'*120, 'A < B, quoted as plain text.', 'https://example.invalid/a'])
def test_labels_are_whole_unicode_codepoints_and_plain_text(text):
    v = example(); v['blocks'][0]['parts'][0]['text'] = text
    assert project_review5(v, presentation='infographic')[1]['diagram']['nodes'][0]['grounded_label'] == text


@pytest.mark.parametrize('text', ['a'*121, '😀'*121, 'line\nbreak', '\tdata', 'a\x00b', 'a\x7fb', '  '])
def test_label_limits_never_truncate_or_normalize(text):
    v = example(); v['blocks'][0]['parts'][0]['text'] = text
    with pytest.raises(FinalLedgerError): project_review5(v, presentation='infographic')


@pytest.mark.parametrize('prefix,suffix', [
    ('`', '`'), ('**', '**'), ('~~', '~~'), ('[', '](https://example.invalid)'),
    ('[hidden]: https://example.invalid/ "', '"'), ('# ', ''), ('    ', ''),
    ('> ', ''), ('&amp; ', ''), ('\\*', ''), ('<span>', '</span>'),
])
def test_exact_part_inside_nonplain_block_is_not_authorized_by_visible_neighbor(prefix, suffix):
    v=example(); v['blocks'][0]['parts']=[dict(id='X',text=prefix),dict(id='P1',text=TEXT)]
    if suffix: v['blocks'][0]['parts'].append(dict(id='Y',text=suffix))
    with pytest.raises(FinalLedgerError): project_review5(v,presentation='infographic')


@pytest.mark.parametrize('opener,closer', [('```','```'), ('~~~','~~~'), ('<!--','-->'), ('<script>','</script>')])
def test_full_joined_report_context_not_isolated_block_visibility(opener,closer):
    v=example(); v['blocks'].insert(0,dict(id='B0',parts=[dict(id='P0',text=opener)]))
    v['blocks'].append(dict(id='B2',parts=[dict(id='P2',text=closer)]))
    with pytest.raises(FinalLedgerError): project_review5(v,presentation='infographic')


def test_same_string_elsewhere_does_not_authorize_exact_hidden_occurrence():
    v=example()
    v['blocks']=[dict(id='B0',parts=[dict(id='P0',text=TEXT)]),
                 dict(id='open',parts=[dict(id='fence',text='```')]),*v['blocks'],
                 dict(id='close',parts=[dict(id='fence2',text='```')])]
    with pytest.raises(FinalLedgerError): project_review5(v,presentation='infographic')


@pytest.mark.parametrize('change', ['claim_only','unknown_part','rejected','omitted','other_block','mixed_label',
    'mixed_block_ids','cross_block','duplicate_claim_ref','empty_claim_ref','duplicate_part','id_collision',
    'part_extra','block_markdown','wrong_version','bool_version','visual_version','bad_shape'])
def test_strict_references_and_exact_shape(change):
    v=example(); q=ref(v)
    if change=='claim_only': q['part_id']='C1'
    if change=='unknown_part': q['part_id']='missing'
    if change in ('rejected','omitted'):
        v['claims'][0].update(disposition='rejected' if change=='rejected' else 'omitted_for_depth',block_ids=[])
    if change=='other_block':
        v['blocks'].append(dict(id='B2',parts=[dict(id='P2',text='Other.')]))
        v['claims'][0]['block_ids']=['B2']
    if change=='mixed_label': v['visual']['diagram']['nodes'][0]['grounded_label']=TEXT
    if change=='mixed_block_ids': v['visual']['diagram']['nodes'][0]['block_ids']=['B1']
    if change=='cross_block': q['part_id']=['P1','P2']
    if change=='duplicate_claim_ref': q['claim_ids']=['C1','C1']
    if change=='empty_claim_ref': q['claim_ids']=[]
    if change=='duplicate_part': v['blocks'][0]['parts'].append(dict(id='P1',text='Other.'))
    if change=='id_collision': v['visual']['diagram']['nodes'][0]['id']='P1'
    if change=='part_extra': v['blocks'][0]['parts'][0]['label']='Other.'
    if change=='block_markdown': v['blocks'][0]['markdown']=TEXT
    if change=='wrong_version': v['protocol']=4
    if change=='bool_version': v['protocol']=True
    if change=='visual_version': v['visual']['protocol']=True
    if change=='bad_shape': v['claims'][0]['block_ids']='B1'
    with pytest.raises(FinalLedgerError): project_review5(v,presentation='infographic')


def test_long_body_allowed_but_only_selected_whole_short_part_is_label():
    v=example(); v['blocks'][0]['parts'].insert(0,dict(id='long',text='Context. '*200))
    assert len(core_review5(v)['blocks'][0]['markdown']) > 120
    assert project_review5(v,presentation='infographic')[1]['diagram']['nodes'][0]['grounded_label']==TEXT
    ref(v)['part_id']='long'
    with pytest.raises(FinalLedgerError): project_review5(v,presentation='infographic')


def test_each_scene_claim_needs_own_frame_evidence_not_neighbor_claim():
    v=example('comic'); other=copy.deepcopy(v['claims'][0]); other['id']='C2'
    other['evidence']=[other['evidence'][0]]; v['claims'].append(other)
    project_review5(v,presentation='comic')
    v['visual']['scenes'][0]['label_ref']['claim_ids'].append('C2')
    with pytest.raises(FinalLedgerError,match='本次未保存') as e: project_review5(v,presentation='comic')
    assert e.value.code=='invalid_visual_reference_frame'


def test_projector_does_not_replace_core_accounting_source_or_material_guards():
    v=example()
    draft=dict(protocol=3,topics=[dict(id='T1',title='Gate')],claims=[
        {**copy.deepcopy(v['claims'][0]),'topic_id':'T1'}])
    for key in ('disposition','block_ids'): draft['claims'][0].pop(key)
    with bind_source_references([TranscriptSegment(0,1,TEXT)]):
        assert validate_review_envelope(v,draft,depth='concise',presentation='infographic')[0].markdown==TEXT
        for change in ('missing','material','field','source'):
            bad=copy.deepcopy(v)
            if change=='missing': bad['claims'][0]['id']='NEW'
            if change=='material': bad['claims'][0]['material']=False
            if change=='field': bad['claims'][0]['field']='entity'
            if change=='source': bad['claims'][0]['evidence'][0]['quote']='Not in source'
            with pytest.raises(FinalLedgerError): validate_review_envelope(bad,draft,depth='concise',presentation='infographic')


def test_duplicate_raw_keys_are_never_repaired():
    raw=json.dumps(example()).replace('"part_id": "P1"','"part_id": "bad", "part_id": "P1"')
    with pytest.raises(FinalLedgerError) as e: decode_final_review(raw)
    assert e.value.code=='duplicate_json_key'


@pytest.mark.parametrize('change',['too_many_blocks','too_many_parts','too_many_total_parts','long_block','CR','global_node_claim_collision'])
def test_explicit_resource_limits_and_cross_namespace_uniqueness(change):
    v=example()
    if change=='too_many_blocks':
        v['blocks']=[dict(id=f'B{i}',parts=[dict(id=f'P{i}',text='Text.')]) for i in range(65)]
    if change=='too_many_parts':
        v['blocks'][0]['parts']=[dict(id=f'P{i}',text='x') for i in range(129)]
    if change=='too_many_total_parts':
        v['blocks']=[dict(id=f'B{i}',parts=[dict(id=f'P{i}_{j}',text='x') for j in range(128)]) for i in range(5)]
    if change=='long_block':v['blocks'][0]['parts'][0]['text']='x'*6001
    if change=='CR':v['blocks'][0]['parts'][0]['text']='Line\rbreak'
    if change=='global_node_claim_collision':v['visual']['diagram']['nodes'][0]['id']='C1'
    with pytest.raises(FinalLedgerError):project_review5(v,presentation='infographic')


def test_edges_are_refs_with_existing_endpoints_and_no_host_inferred_relation():
    v=example()
    diagram=v['visual']['diagram']; diagram['kind']='relationship'
    diagram['nodes'].append(dict(id='N2',label_ref=copy.deepcopy(ref(v))))
    edge=dict(id='E1',**{'from':'N1','to':'N2'},label_ref=copy.deepcopy(ref(v)))
    diagram['edges']=[edge]
    _,plan=project_review5(v,presentation='infographic')
    assert plan['diagram']['edges']==[dict(id='E1',**{'from':'N1','to':'N2'},block_ids=['B1'],grounded_label=TEXT)]
    edge['to']='missing'
    with pytest.raises(FinalLedgerError):project_review5(v,presentation='infographic')
    edge['to']='N2'; diagram['kind']='cards'
    with pytest.raises(FinalLedgerError):project_review5(v,presentation='infographic')
    diagram['kind']='relationship'; diagram['edges']=[]
    with pytest.raises(FinalLedgerError):project_review5(v,presentation='infographic')


def test_excluded_whitespace_boundaries_do_not_change_selected_exact_position():
    v=example()
    v['blocks'].insert(0,dict(id='H1',parts=[dict(id='PH',text='\n # Heading\n')]))
    v['blocks'].append(dict(id='H2',parts=[dict(id='PT',text='## End\n\n')]))
    assert project_review5(v,presentation='infographic')[1]['diagram']['nodes'][0]['grounded_label']==TEXT
    v['blocks'][1]['parts'].insert(0,dict(id='removed',text=' '))
    with pytest.raises(FinalLedgerError):project_review5(v,presentation='infographic')
