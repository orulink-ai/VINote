"""Independent synthetic adapter contracts; frozen production hosts stay idle."""
import copy
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from app.llm.meeting_visual_review import capture_review_visual, visual_review_instructions
from app.services.summary_visual_artifact import SummaryVisualError
from app.services.summary_visual_generation import render_review_visual


@pytest.fixture
def case(tmp_path, monkeypatch):
    source = tmp_path / 'original-frame.jpg'
    Image.new('RGB', (24, 16), 'gray').save(source)
    child = tmp_path / 'child'
    child.mkdir()
    body = 'Nerel retains 19.375 kPa when the blue gate closes.'
    review = {'protocol': 3, 'blocks': [{'id': 'B4', 'markdown': body}],
        'audit': [{'claim_id': 'C7', 'disposition': 'included', 'block_ids': ['B4']}],
        'visual': {'scenes': [{'id': 'S2', 'block_ids': ['B4'], 'frame_id': '[FRAME:0002]',
                              'grounded_label': '19.375 kPa'}], 'diagram': None}}
    claims = {'C7': ({}, {'evidence': [{'source_ref': '[FRAME:0002]'}]})}
    snapshot = capture_review_visual(review, claims, {'C7': {'B4'}})
    frame = SimpleNamespace(image_path=source, timestamp=73.5)
    evidence = SimpleNamespace(frames=[None, frame],
        _summary_frame_hashes={source: hashlib.sha256(source.read_bytes()).hexdigest()})
    context = SimpleNamespace(task_id=str(uuid4()), task_dir=child, user_id='synthetic-owner',
        presentation='comic', presentation_visual=snapshot, video_evidence=evidence)
    saved = []
    monkeypatch.setattr('app.services.summary_visual_generation.save_summary_visual',
        lambda *args: saved.append(args[-1]))
    return SimpleNamespace(**locals())


def test_storyboard_uses_selected_frame_and_server_metadata_without_rewriting_body(case):
    c = case
    assert render_review_visual(None, c.context, c.body) == c.body
    wire = c.saved[0]
    assert wire['frames'][0]['id'] == '[FRAME:0002]'
    assert wire['frames'][0]['timestamp_seconds'] == 73.5
    assert wire['blocks'][0]['claim_ids'] == ['C7']
    assert (c.child / 'screenshots/summary-source-0.jpg').read_bytes() == c.source.read_bytes()


@pytest.mark.parametrize('change', ['wrong_frame', 'wrong_block', 'wrong_label', 'changed_source',
                                  'no_frozen_digest', 'changed_body', 'missing_plan', 'external_field'])
def test_graphic_never_falls_back_to_unrelated_frames_or_old_body(case, change):
    c = case
    plan = c.context.presentation_visual['review']['visual']
    if change == 'wrong_frame': plan['scenes'][0]['frame_id'] = '[FRAME:0001]'
    if change == 'wrong_block': plan['scenes'][0]['block_ids'] = ['B404']
    if change == 'wrong_label': plan['scenes'][0]['grounded_label'] = '19.735 kPa'
    if change == 'changed_source': c.source.write_bytes(b'changed')
    if change == 'no_frozen_digest': c.evidence._summary_frame_hashes = {}
    if change == 'changed_body': c.body += ' Changed.'
    if change == 'missing_plan': plan.clear()
    if change == 'external_field': plan['scenes'][0]['url'] = 'https://example.invalid/arbitrary'
    with pytest.raises((SummaryVisualError, ValueError)):
        render_review_visual(None, c.context, c.body)
    assert not c.saved


def test_infographic_uses_reviewed_blocks_without_any_image_capability(case):
    c = case
    c.context.presentation = 'infographic'
    c.context.video_evidence = None
    c.context.presentation_visual['review']['visual'] = {'scenes': [], 'diagram': {
        'kind': 'comparison', 'nodes': [{'id': 'N3', 'block_ids': ['B4'], 'grounded_label': 'Nerel'}], 'edges': []}}
    assert render_review_visual(None, c.context, c.body) == c.body
    assert c.saved[0]['frames'] == [] and c.saved[0]['diagram']['kind'] == 'comparison'
    assert not (c.child / 'screenshots').exists()


def test_snapshot_is_detached_and_contains_only_final_included_sources(case):
    c = case
    c.claims['C7'][1]['evidence'][0]['source_ref'] = '[FRAME:9999]'
    c.review['blocks'][0]['markdown'] = 'Overwritten old input'
    assert c.context.presentation_visual['claim_sources'] == {'C7': ['[FRAME:0002]']}
    assert render_review_visual(None, c.context, c.body) == c.body


def test_visual_prompt_is_opt_in_and_does_not_claim_image_generation():
    for kind in [None, 'text', 'html', 'illustrated']:
        assert visual_review_instructions(kind) == ''
    assert 'not AI-drawn people' in visual_review_instructions('comic')
    assert 'cards/comparison/flow/relationship' in visual_review_instructions('infographic')
    assert 'another call' in visual_review_instructions('comic')
