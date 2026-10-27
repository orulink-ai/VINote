"""Raw5 -> actual bound-v1 storage/readback using temporary accepted receipts."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from test_summary_visual_artifact import case  # isolated temporary DB/owner/receipt fixture
from test_meeting_visual_projection import example, TEXT
from app.llm.meeting_final_review import finalize_final_review
from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_visual_review import capture_review_visual
from app.llm.source_references import bind_source_references
from app.llm.video_material import bind_video_material
from app.models.transcript import TranscriptSegment
from app.services.summary_visual_artifact import save_summary_visual, read_summary_visual
from app.services.summary_visual_generation import render_review_visual
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence


def stored(c, monkeypatch):
    value=example('comic')
    draft=dict(protocol=3,topics=[dict(id='T1',title='Gate')],claims=[
        {**copy.deepcopy(value['claims'][0]),'topic_id':'T1'}])
    for key in ('disposition','block_ids'): draft['claims'][0].pop(key)
    raw=json.dumps(value,ensure_ascii=False,indent=2)
    video=VideoEvidence(10,[VideoFrameEvidence(1.25,c.screenshot,['timeline'],[1.25])],10,True)
    video._summary_frame_hashes={c.screenshot:hashlib.sha256(c.screenshot.read_bytes()).hexdigest()}
    with presentation_scope('brief','comic') as state, bind_source_references([TranscriptSegment(0,1,TEXT)]), bind_video_material(video,{'vision':True}):
        body=finalize_final_review(raw,json.dumps(draft))
    c.write('meeting_fact_review.json',dict(protocol=1,raw_response=raw))
    c.write('result.json',dict(markdown=body))
    monkeypatch.setattr('app.services.summary_visual_generation.save_summary_visual',
        lambda *a:save_summary_visual(*a,sessions=c.sessions))
    context=SimpleNamespace(task_id=c.task,task_dir=c.folder,user_id=c.owner,
        presentation='comic',video_evidence=video,presentation_visual=state.visual_review)
    assert render_review_visual(c.artifacts,context,body)==body==TEXT
    return value,raw,body,context


def read(c):
    return read_summary_visual(c.artifacts,c.owner,c.task,sessions=c.sessions)


def test_raw5_exact_save_read_reconstructs_same_bound_v1_without_connections(case,monkeypatch):
    c=case; value,raw,body,context=stored(c,monkeypatch)
    before={p.name:p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    from app.services.vilab_cloud_service import VILabCloudService
    monkeypatch.setattr(VILabCloudService,'connection_snapshot',lambda *a,**k:pytest.fail('no connection'))
    monkeypatch.setattr('app.services.windows_ocr.recognize_batch',lambda *a,**k:pytest.fail('no OCR'))
    wire=read(c)
    assert wire['visual_protocol']==1 and wire['body_sha256']==hashlib.sha256(body.encode()).hexdigest()
    assert wire['scenes']==[dict(id='S1',frame_id='[FRAME:0001]',block_ids=['B1'],grounded_label=TEXT)]
    assert wire['frames']==[dict(id='[FRAME:0001]',screenshot_index=0,timestamp_seconds=1.25,grounded_label=TEXT)]
    assert json.loads((c.folder/'meeting_fact_review.json').read_bytes())['raw_response']==raw
    assert render_review_visual(c.artifacts,context,body)==body
    assert {p.name:p.read_bytes() for p in c.folder.iterdir() if p.is_file()}==before


@pytest.mark.parametrize('change',['raw_whitespace','part','quote_ref','claim_disposition','claim_block','claim_frame',
    'body','body_and_hash','sidecar_label','sidecar_frame_label','sidecar_index','sidecar_block','sidecar_edge',
    'owner','origin','model','fingerprint','receipt','screenshot','fenced'])
def test_readback_rejects_mutations_never_reprojects_or_repairs_on_disk(case,monkeypatch,change):
    c=case; value,raw,body,_=stored(c,monkeypatch)
    side=json.loads((c.folder/'summary_visual.json').read_bytes())
    if change in {'part','quote_ref','claim_disposition','claim_block','claim_frame'}:
        if change=='part': value['blocks'][0]['parts'][0]['text']='Changed body.'
        if change=='quote_ref': value['visual']['scenes'][0]['label_ref']['part_id']='C1'
        if change=='claim_disposition': value['claims'][0].update(disposition='omitted_for_depth',block_ids=[])
        if change=='claim_block': value['claims'][0]['block_ids']=['B999']
        if change=='claim_frame': value['claims'][0]['evidence']=[value['claims'][0]['evidence'][0]]
        c.write('meeting_fact_review.json',dict(protocol=1,raw_response=json.dumps(value)))
    elif change in {'raw_whitespace','fenced'}:
        c.write('meeting_fact_review.json',dict(protocol=1,raw_response=raw+'\n' if change=='raw_whitespace' else '```json\n'+raw+'\n```'))
    elif change=='body': c.write('result.json',dict(markdown=body+' '))
    elif change=='body_and_hash':
        changed=body+' Additional unrelated statement.'
        c.write('result.json',dict(markdown=changed))
        side['visual']['body_sha256']=hashlib.sha256(changed.encode()).hexdigest()
        c.write('summary_visual.json',side)
    elif change.startswith('sidecar_'):
        wire=side['visual']
        if change=='sidecar_label': wire['scenes'][0]['grounded_label']='beta'
        if change=='sidecar_frame_label': wire['frames'][0]['grounded_label']='beta'
        if change=='sidecar_index': wire['frames'][0]['screenshot_index']=1
        if change=='sidecar_block': wire['blocks'][0]['claim_ids']=[]
        if change=='sidecar_edge': wire['diagram']={}
        c.write('summary_visual.json',side)
    elif change=='owner': (c.folder/'recording_owner').write_text('other')
    elif change in {'origin','model'}:
        c.write('model_source_snapshot.json',{**c.snapshot,**({'server_url':'https://other.invalid'} if change=='origin' else {'llm_model':'other'})})
    elif change=='fingerprint':
        from app.db_models import SourceRequestDB
        with c.sessions() as db: db.get(SourceRequestDB,(c.owner,str(c.body.operation_id))).fingerprint='0'*64
    elif change=='receipt': side['receipt']['snapshot_sha256']='0'*64; c.write('summary_visual.json',side)
    elif change=='screenshot': c.screenshot.write_bytes(b'changed')
    before={p.name:p.read_bytes() for p in c.folder.iterdir() if p.is_file()}
    assert read(c) is None
    assert {p.name:p.read_bytes() for p in c.folder.iterdir() if p.is_file()}==before


def test_save_rebuilds_raw5_instead_of_trusting_inmemory_projection(case,monkeypatch):
    c=case; _,_,body,context=stored(c,monkeypatch)
    (c.folder/'summary_visual.json').unlink()
    bad=copy.deepcopy(context.presentation_visual)
    bad['review']['blocks'][0]['parts'][0]['text']='Other text.'
    context.presentation_visual=bad
    with pytest.raises(ValueError): render_review_visual(c.artifacts,context,body)
    assert not (c.folder/'summary_visual.json').exists()
