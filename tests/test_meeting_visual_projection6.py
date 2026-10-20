"""Independent protocol6 path projection: no P5 fabrication or repair."""
import copy
import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError, decode_final_review
from app.llm.meeting_final_review import validate_review_envelope
from app.llm.meeting_visual_projection6 import core_review6, project_review6
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment

TEXT = 'Use the spare sensor only after the violet check passes.'


def example(presentation='infographic'):
    claim=dict(id='C1',field='condition',text='Claim text is NOT a label source.',material=True,
        disposition='included',block_ids=['B1'],evidence=[
            dict(kind='asr_span',source_ref='[ASR:0001]',quote=TEXT)])
    ref=dict(block_id='B1',part_index=0,claim_ids=['C1'])
    value=dict(protocol=6,blocks=[dict(id='B1',parts=[TEXT])],claims=[claim],
        visual=dict(protocol=3,scenes=[],diagram=dict(kind='cards',edges=[],nodes=[dict(id='N1',label_ref=ref)])))
    if presentation=='comic':
        claim['evidence'].append(dict(kind='frame_observation',source_ref='[FRAME:0001]',observation='Visible check condition'))
        value['visual'].update(scenes=[dict(id='S1',frame_id='[FRAME:0001]',label_ref=ref)],diagram=None)
    return value


def ref(v):return v['visual']['diagram']['nodes'][0]['label_ref']


def test_whole_string_exact_concatenation_and_detached_core_without_using_p5(monkeypatch):
    monkeypatch.setattr('app.llm.meeting_visual_projection.core_review5',lambda *a,**k:pytest.fail('no raw5 projection'))
    monkeypatch.setattr('app.llm.meeting_visual_projection.project_review5',lambda *a,**k:pytest.fail('no raw5 projection'))
    v=example();v['blocks'][0]['parts']=['Context. ',TEXT];ref(v)['part_index']=1
    before=copy.deepcopy(v);core,plan=project_review6(v,presentation='infographic')
    assert core['blocks']==[dict(id='B1',markdown='Context. '+TEXT)]
    assert plan['diagram']['nodes'][0]==dict(id='N1',block_ids=['B1'],grounded_label=TEXT)
    core['claims'][0]['text']='detached';assert v==before


@pytest.mark.parametrize('index',[True,False,-1,1,1.0,0.0,'0',None,[],{},2**80])
def test_path_index_is_strict_integer_and_never_guessed_or_clamped(index):
    v=example();ref(v)['part_index']=index
    with pytest.raises(FinalLedgerError) as e:project_review6(v,presentation='infographic')
    assert e.value.code=='invalid_visual_reference_path'


@pytest.mark.parametrize('text',['x'*120,'😀'*120,'A < B.','https://example.invalid/a'])
def test_exact_120_codepoints_and_escaped_plain_text(text):
    v=example();v['blocks'][0]['parts']=[text]
    assert project_review6(v,presentation='infographic')[1]['diagram']['nodes'][0]['grounded_label']==text


@pytest.mark.parametrize('text',['x'*121,'😀'*121,'\ntext','a\tb','a\x00b','a\x7fb',' ',''])
def test_invalid_label_never_truncated_or_normalized(text):
    v=example();v['blocks'][0]['parts']=[text]
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


@pytest.mark.parametrize('prefix,suffix',[('`','`'),('**','**'),('~~','~~'),('[','](https://invalid.test)'),
    ('[hidden]: https://invalid.test/ "','"'),('# ',''),('    ',''),('> ',''),('&amp; ',''),('\\*',''),('<i>','</i>')])
def test_exact_selected_position_must_be_in_plain_block(prefix,suffix):
    v=example();v['blocks'][0]['parts']=[prefix,TEXT]+([suffix] if suffix else []);ref(v)['part_index']=1
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


@pytest.mark.parametrize('opener,closer',[('```','```'),('~~~','~~~'),('<!--','-->'),('<script>','</script>')])
def test_full_body_context_and_repeated_text_do_not_lend_visibility(opener,closer):
    v=example();v['blocks']=[dict(id='B0',parts=[TEXT]),dict(id='OPEN',parts=[opener]),
        *v['blocks'],dict(id='CLOSE',parts=[closer])]
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


def test_scope_is_explicit_not_inferred_from_multiblock_claim_or_matching_text():
    v=example();v['blocks'].append(dict(id='B2',parts=[TEXT,' Different condition.']))
    v['claims'][0]['block_ids'].append('B2');ref(v).update(block_id='B2',part_index=1)
    assert project_review6(v,presentation='infographic')[1]['diagram']['nodes'][0]['grounded_label']==' Different condition.'
    ref(v)['block_id']='unknown'
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


@pytest.mark.parametrize('change',['mixed_parts','null_part','nested_part','missing_index','old_part_id','claim_only',
    'extra_label','extra_block_ids','excluded','wrong_block','duplicate_block','duplicate_claim','duplicate_node',
    'cross_namespace_id','bool_protocol','wrong_visual_protocol','long_block','too_many_parts','too_many_total_parts','CR'])
def test_strict_schema_old_unique_rules_and_resource_limits(change):
    v=example();q=ref(v)
    if change=='mixed_parts':v['blocks'][0]['parts'].append(dict(id='P1',text=TEXT))
    if change=='null_part':v['blocks'][0]['parts']=[None]
    if change=='nested_part':v['blocks'][0]['parts']=[[TEXT]]
    if change=='missing_index':q.pop('part_index')
    if change=='old_part_id':q['part_id']='P1'
    if change=='claim_only':q['block_id']='C1'
    if change=='extra_label':v['visual']['diagram']['nodes'][0]['grounded_label']=TEXT
    if change=='extra_block_ids':v['visual']['diagram']['nodes'][0]['block_ids']=['B1']
    if change=='excluded':v['claims'][0].update(disposition='rejected',block_ids=[])
    if change=='wrong_block':
        v['blocks'].append(dict(id='B2',parts=[TEXT]));v['claims'][0]['block_ids']=['B2']
    if change=='duplicate_block':v['blocks'].append(copy.deepcopy(v['blocks'][0]))
    if change=='duplicate_claim':v['claims'].append(copy.deepcopy(v['claims'][0]))
    if change=='duplicate_node':v['visual']['diagram']['nodes'].append(copy.deepcopy(v['visual']['diagram']['nodes'][0]))
    if change=='cross_namespace_id':v['visual']['diagram']['nodes'][0]['id']='C1'
    if change=='bool_protocol':v['protocol']=True
    if change=='wrong_visual_protocol':v['visual']['protocol']=2
    if change=='long_block':v['blocks'][0]['parts']=['a'*6001]
    if change=='too_many_parts':v['blocks'][0]['parts']=['a']*129
    if change=='too_many_total_parts':v['blocks']=[dict(id=f'B{i}',parts=['a']*128) for i in range(5)]
    if change=='CR':v['blocks'][0]['parts']=['a\rb']
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


def test_each_scene_claim_must_have_its_own_exact_frame():
    v=example('comic');other=copy.deepcopy(v['claims'][0]);other['id']='C2';other['evidence']=other['evidence'][:1]
    v['claims'].append(other);v['visual']['scenes'][0]['label_ref']['claim_ids'].append('C2')
    with pytest.raises(FinalLedgerError) as e:project_review6(v,presentation='comic')
    assert e.value.code=='invalid_visual_reference_frame'


def test_empty_layout_or_missing_relation_is_not_repaired():
    v=example('comic');v['visual']['scenes']=[]
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='comic')
    v=example();v['visual']['diagram']=None
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')
    v=example();v['visual']['diagram']['kind']='flow'
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


def test_core_ledger_still_checks_original_accounting_fields_material_and_evidence():
    v=example();draft=dict(protocol=3,topics=[dict(id='T1',title='Check')],claims=[
        {**copy.deepcopy(v['claims'][0]),'topic_id':'T1'}])
    for key in ('disposition','block_ids'):draft['claims'][0].pop(key)
    with bind_source_references([TranscriptSegment(0,1,TEXT)]):
        assert validate_review_envelope(v,draft,depth='detailed',presentation='infographic')[0].markdown==TEXT
        for change in ['id','field','material','evidence']:
            bad=copy.deepcopy(v)
            if change=='id':bad['claims'][0]['id']='NEW'
            if change=='field':bad['claims'][0]['field']='entity'
            if change=='material':bad['claims'][0]['material']=False
            if change=='evidence':bad['claims'][0]['evidence'][0]['quote']='not present'
            with pytest.raises(FinalLedgerError):validate_review_envelope(bad,draft,depth='detailed',presentation='infographic')


def test_duplicate_json_keys_fail_before_path_projection():
    raw=json.dumps(example()).replace('"part_index": 0','"part_index": 1, "part_index": 0')
    with pytest.raises(FinalLedgerError) as e:decode_final_review(raw)
    assert e.value.code=='duplicate_json_key'


def test_all_blocks_may_have_index_zero_without_global_part_names():
    v=example();v['blocks'].append(dict(id='B2',parts=[TEXT]));v['claims'][0]['block_ids'].append('B2')
    v['visual']['diagram']['nodes'].append(dict(id='N2',label_ref=dict(block_id='B2',part_index=0,claim_ids=['C1'])))
    assert len(project_review6(v,presentation='infographic')[1]['diagram']['nodes'])==2


def test_historical_five_still_rejects_block_local_reuse_of_global_part_id():
    from test_meeting_visual_projection import example as five
    from app.llm.meeting_visual_projection import project_review5
    v=five();v['blocks'].append(dict(id='B2',parts=[dict(id='P1',text=TEXT)]))
    with pytest.raises(FinalLedgerError) as e:project_review5(v,presentation='infographic')
    assert e.value.code=='invalid_visual_reference_ids'


def test_relationship_edges_select_original_complete_parts_and_strict_endpoints():
    v=example();diagram=v['visual']['diagram'];diagram['kind']='relationship'
    diagram['nodes'].append(dict(id='N2',label_ref=copy.deepcopy(ref(v))))
    edge=dict(id='E1',**{'from':'N1','to':'N2'},label_ref=copy.deepcopy(ref(v)))
    diagram['edges']=[edge]
    assert project_review6(v,presentation='infographic')[1]['diagram']['edges']==[
        dict(id='E1',**{'from':'N1','to':'N2'},block_ids=['B1'],grounded_label=TEXT)]
    edge['to']='missing'
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')
    edge['to']='N2';diagram['kind']='cards'
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')


def test_whole_body_trimming_does_not_lose_exact_selected_offset():
    v=example();v['blocks'].insert(0,dict(id='H1',parts=['\n # Heading\n']))
    v['blocks'].append(dict(id='H2',parts=['## End\n\n']))
    assert project_review6(v,presentation='infographic')[1]['diagram']['nodes'][0]['grounded_label']==TEXT
    v['blocks'][1]['parts'].insert(0,' ')
    with pytest.raises(FinalLedgerError):project_review6(v,presentation='infographic')
