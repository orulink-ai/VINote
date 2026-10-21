"""Actual VILab adapter, with its sole outbound request replaced by a fixture."""
import base64
import copy
import hashlib
import json
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from test_meeting_final_review import case, response, SOURCE
from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.source_references import capture_working_draft
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from app.services.summary_visual_generation import render_review_visual


def five(c, kind):
    value=response(c,kind)
    value['protocol']=5
    value['blocks']=[dict(id='B1',parts=[dict(id='P1',text=SOURCE)])]
    ref=dict(part_id='P1',claim_ids=['C1'])
    value['visual']=(dict(protocol=2,scenes=[dict(id='S1',frame_id='[FRAME:0001]',label_ref=ref)],diagram=None)
        if kind=='comic' else dict(protocol=2,scenes=[],diagram=dict(kind='cards',
            nodes=[dict(id='N1',label_ref=ref)],edges=[])))
    return value


def six(c, kind):
    value=response(c,kind)
    value['protocol']=6
    value['blocks']=[dict(id='B1',parts=[SOURCE])]
    ref=dict(block_id='B1',part_index=0,claim_ids=['C1'])
    value['visual']=(dict(protocol=3,scenes=[dict(id='S1',frame_id='[FRAME:0001]',label_ref=ref)],diagram=None)
        if kind=='comic' else dict(protocol=3,scenes=[],diagram=dict(kind='cards',
            nodes=[dict(id='N1',label_ref=ref)],edges=[])))
    return value


def seven(c, kind):
    value=six(c,kind);value['protocol']=7
    value['title_ref']=dict(block_id='B1',part_index=0)
    for claim in value['claims']:
        claim.pop('text');claim.pop('block_ids')
        claim['part_ref']=dict(block_id='B1',part_index=0)
    return value


@pytest.mark.parametrize('kind',['comic','infographic'])
@pytest.mark.parametrize('depth',['brief','concise','detailed'])
def test_actual_adapter_two_whole_source_calls_raw7_and_frozen_image_input(case,monkeypatch,kind,depth):
    c=case; value=seven(c,kind)
    raw3=json.dumps(c.material); raw6=json.dumps(value,ensure_ascii=False,indent=2)
    calls=[]; captured=[]; saved=[]
    monkeypatch.setattr('app.services.tracing_service.observation',lambda *a,**k:nullcontext(None))
    monkeypatch.setattr(httpx.Client,'request',lambda *a,**k:pytest.fail('no network'))
    monkeypatch.setattr('app.services.summary_visual_generation.save_summary_visual',lambda *a:saved.append(a[-1]))
    def request(self,owner,method,path,**kw):
        assert owner=='fixture-owner' and method=='POST' and path=='/openai/v1/chat/completions'
        calls.append(copy.deepcopy(kw['json']))
        assert len(calls)<=2
        return dict(choices=[dict(message=dict(content=raw3 if len(calls)==1 else raw6))])
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request',request)
    llm=VILabLLM('fixture-owner','frozen-fixture-model')
    llm.configure_video_capabilities({'max_images':64},image_input_verified=True,webp_input_verified=True)
    with presentation_scope(depth,kind) as state,capture_working_draft(captured.append):
        body=llm.summarize('Synthetic fixture',[TranscriptSegment(0,10,SOURCE)],style='meeting',video_evidence=c.evidence)
        context=SimpleNamespace(task_id=str(uuid4()),task_dir=c.tmp_path/'child',user_id='fixture-owner',
            presentation=kind,video_evidence=c.evidence,presentation_visual=state.visual_review)
        context.task_dir.mkdir()
        assert render_review_visual(None,context,body)==SOURCE
    assert len(calls)==2 and captured==[raw3] and state.raw_review==raw6
    assert saved[0]['visual_protocol']==1 and saved[0]['body_sha256']==hashlib.sha256(SOURCE.encode()).hexdigest()
    assert state.expected_review_protocol==7
    assert 'PROTOCOL 3' in calls[0]['messages'][0]['content']
    rules=calls[1]['messages'][0]['content']
    assert 'PROTOCOL 7' in rules and 'SINGLE-COPY PARTS AND VISUAL-REF/3' in rules
    assert 'All labels must be short unchanged contiguous substrings' not in rules
    assert 'Markdown belongs only inside blocks[].markdown' not in rules
    material=[]
    for call in calls:
        assert call['model']=='frozen-fixture-model' and call['stream'] is True
        content=call['messages'][1]['content']
        assert SOURCE in ''.join(row.get('text','') for row in content)
        images=[row for row in content if row['type']=='image_url']
        assert len(images)==1
        digest=hashlib.sha256(base64.b64decode(images[0]['image_url']['url'].split(',',1)[1])).hexdigest()
        assert digest==c.evidence.input_receipt()['images'][0]['wire_sha256']
        material.append(images)
    assert material[0]==material[1]
    assert c.evidence.input_receipt()['requests_prepared']==2
    assert hashlib.sha256(c.path.read_bytes()).hexdigest()==c.evidence._summary_frame_hashes[c.path]


@pytest.mark.parametrize('kind',['comic','infographic'])
@pytest.mark.parametrize('old_protocol',[4,5,6])
def test_new_actual_graphic_call_rejects_explicit_legacy_without_retry_or_partial_graphic(case,monkeypatch,kind,old_protocol):
    c=case; calls=[]
    monkeypatch.setattr('app.services.tracing_service.observation',lambda *a,**k:nullcontext(None))
    def request(*a,**k):
        calls.append(k)
        raw=json.dumps(c.material if len(calls)==1 else (response(c,kind) if old_protocol==4 else (five(c,kind) if old_protocol==5 else six(c,kind))))
        return dict(choices=[dict(message=dict(content=raw))])
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request',request)
    llm=VILabLLM('fixture','fixture')
    llm.configure_video_capabilities({'max_images':64},image_input_verified=True)
    with presentation_scope('concise',kind) as state:
        with pytest.raises(FinalLedgerError) as e:
            llm.summarize('Synthetic',[TranscriptSegment(0,10,SOURCE)],style='meeting',video_evidence=c.evidence)
    assert e.value.code=='invalid_protocol' and len(calls)==2
    assert json.loads(state.raw_review)['protocol']==old_protocol and state.visual_review is None
