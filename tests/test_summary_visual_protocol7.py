"""Real raw7 finalize/storage/readback, isolated accepted DB and real JPEGs."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_summary_visual_artifact import case
from test_meeting_visual_projection6 import example, TEXT
from app.llm.meeting_final_review import finalize_final_review
from app.llm.meeting_presentation import presentation_scope
from app.llm.source_references import bind_source_references
from app.llm.video_material import bind_video_material
from app.models.transcript import TranscriptSegment
from app.services.summary_visual_artifact import read_summary_visual, save_summary_visual, reviewed_visual_blocks, reviewed_claim_sources
from app.services.summary_visual_generation import render_review_visual
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence


FRESH_READ = r'''
import hashlib,json,sys
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.summary_visual_artifact import read_summary_visual
from app.services.task_artifact_service import TaskArtifactService
folder,owner,task,database=Path(sys.argv[1]),sys.argv[2],sys.argv[3],sys.argv[4]
engine=create_engine(database)
@contextmanager
def sessions():
    with Session(engine) as db: yield db
before={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
wire=read_summary_visual(TaskArtifactService(folder.parent),owner,task,sessions=sessions)
assert wire is not None
raw=json.loads((folder/'meeting_fact_review.json').read_bytes())['raw_response']
print(json.dumps({'wire_sha256':hashlib.sha256(json.dumps(wire,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
 'raw_protocol':json.loads(raw)['protocol'],
 'disk_unchanged':before=={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}}))
engine.dispose()
'''


def stored(c, monkeypatch):
    value = example('comic')
    material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic condition'}], 'claims': [
        {k: copy.deepcopy(v) for k, v in value['claims'][0].items() if k not in {'disposition', 'block_ids'}}
        | {'topic_id': 'T1'}]}
    value['protocol'] = 7
    value['title_ref'] = {'block_id': 'B1', 'part_index': 0}
    for claim in value['claims']:
        claim.pop('text'); claim.pop('block_ids')
        claim['part_ref'] = {'block_id': 'B1', 'part_index': 0}
    raw = json.dumps(value, ensure_ascii=False, indent=2)
    video = VideoEvidence(10, [VideoFrameEvidence(1.25, c.screenshot, ['timeline'], [1.25])], 10, True)
    video._summary_frame_hashes = {c.screenshot: hashlib.sha256(c.screenshot.read_bytes()).hexdigest()}
    with presentation_scope('brief', 'comic') as state, bind_source_references([TranscriptSegment(0, 1, TEXT)]), bind_video_material(video, {'vision': True}):
        state.expected_review_protocol = 7
        body = finalize_final_review(raw, json.dumps(material))
    c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': raw})
    from app.llm.meeting_single_copy_projection7 import metadata_title7
    source_title = '2026-10-19 15:41 | 待生成纪要'
    c.write('audio_meta.json', {'title': source_title})
    c.write('result.json', {'markdown': body, 'title': metadata_title7(value, presentation='comic', source_title=source_title)})
    monkeypatch.setattr('app.services.summary_visual_generation.save_summary_visual',
                        lambda *a: save_summary_visual(*a, sessions=c.sessions))
    context = SimpleNamespace(task_id=c.task, task_dir=c.folder, user_id=c.owner,
        presentation='comic', video_evidence=video, presentation_visual=state.visual_review)
    assert render_review_visual(c.artifacts, context, body) == TEXT
    return value, raw, body, context


def read(c):
    return read_summary_visual(c.artifacts, c.owner, c.task, sessions=c.sessions)


def test_raw7_sidecar_real_roundtrip_and_fresh_process_no_core4_on_disk(case, monkeypatch):
    c = case; value, raw, body, context = stored(c, monkeypatch)
    before = {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    wire = read(c)
    assert wire['body_sha256'] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert wire['scenes'][0]['grounded_label'] == TEXT
    assert json.loads((c.folder / 'meeting_fact_review.json').read_bytes())['raw_response'] == raw
    assert json.loads(raw)['protocol'] == 7
    assert context.presentation_visual['review'] == value
    assert all('block_ids' not in claim and 'text' not in claim for claim in value['claims'])
    assert render_review_visual(c.artifacts, context, body) == body
    process = subprocess.run([sys.executable, '-B', '-c', FRESH_READ, str(c.folder), c.owner, c.task,
        str(c.engine.url)], capture_output=True, text=True, check=True)
    fresh = json.loads(process.stdout)
    assert fresh['wire_sha256'] == hashlib.sha256(json.dumps(wire, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert fresh['disk_unchanged'] and fresh['raw_protocol'] == 7
    assert {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()} == before
    assert {p.name for p in c.folder.iterdir() if p.is_file()} == {p.name for p in before if p.parent == c.folder}


@pytest.mark.parametrize('name', ['raw', 'fenced', 'part', 'part_boundaries', 'claim_part', 'claim_frame', 'frame',
    'body', 'body_and_hash', 'sidecar_label', 'sidecar_frame_label', 'screenshot', 'owner', 'origin', 'model',
    'receipt', 'workflow_form', 'metadata_form', 'missing_source_binding'])
def test_raw7_readback_tampering_is_read_only_and_never_repairs(case, monkeypatch, name):
    c = case; value, raw, body, _ = stored(c, monkeypatch)
    side = json.loads((c.folder / 'summary_visual.json').read_bytes())
    if name == 'raw': c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': raw + '\n'})
    if name == 'fenced': c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': '```json\n' + raw + '\n```'})
    if name in {'part', 'part_boundaries', 'claim_part', 'claim_frame', 'frame'}:
        if name == 'part': value['blocks'][0]['parts'][0] = 'Changed text.'
        if name == 'part_boundaries': value['blocks'][0]['parts'] = ['Use the spare sensor ', 'only after the violet check passes.']
        if name == 'claim_part': value['claims'][0]['part_ref']['part_index'] = False
        if name == 'claim_frame': value['claims'][0]['evidence'] = value['claims'][0]['evidence'][:1]
        if name == 'frame': value['visual']['scenes'][0]['frame_id'] = '[FRAME:0002]'
        c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': json.dumps(value)})
        side['review_sha256'] = hashlib.sha256((c.folder / 'meeting_fact_review.json').read_bytes()).hexdigest()
        c.write('summary_visual.json', side)
    if name == 'body': c.write('result.json', {'markdown': body + ' '})
    if name == 'body_and_hash':
        c.write('result.json', {'markdown': body + ' Extra.'})
        side['visual']['body_sha256'] = hashlib.sha256((body + ' Extra.').encode()).hexdigest()
        c.write('summary_visual.json', side)
    if name == 'sidecar_label': side['visual']['scenes'][0]['grounded_label'] = 'Other'; c.write('summary_visual.json', side)
    if name == 'sidecar_frame_label': side['visual']['frames'][0]['grounded_label'] = 'Other'; c.write('summary_visual.json', side)
    if name == 'screenshot': c.screenshot.write_bytes(b'changed')
    if name == 'owner': (c.folder / 'recording_owner').write_text('other')
    if name == 'origin': c.write('model_source_snapshot.json', {**c.snapshot, 'server_url': 'https://changed.invalid'})
    if name == 'model': c.write('model_source_snapshot.json', {**c.snapshot, 'llm_model': 'different'})
    if name == 'receipt': side['receipt']['snapshot_sha256'] = '0' * 64; c.write('summary_visual.json', side)
    if name == 'workflow_form':
        data = json.loads((c.folder / 'new_generation.json').read_bytes()); data['presentation'] = 'infographic'; c.write('new_generation.json', data)
    if name == 'metadata_form':
        data = json.loads((c.folder / 'summary_presentation.json').read_bytes()); data['presentation'] = 'infographic'; c.write('summary_presentation.json', data)
    if name == 'missing_source_binding': (c.folder / 'new_generation.json').unlink()
    before = {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    assert read(c) is None
    assert {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()} == before


def test_raw7_helpers_require_explicit_form_not_context_or_layout_guess(case, monkeypatch):
    value, _, _, _ = stored(case, monkeypatch)
    for helper in [reviewed_visual_blocks, reviewed_claim_sources]:
        for form in [None, 'text', 'html', 'illustrated']:
            with presentation_scope('brief', 'comic'):
                with pytest.raises(ValueError): helper(value, presentation=form)
        assert helper(value, presentation='comic')
