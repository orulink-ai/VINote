"""Glue for validated review layouts and source-bound wire/sidecar artifacts.

No source sampling, inference, fallback images, retries or model changes.
The pipeline must supply a snapshot captured after successful fact review.
"""
import hashlib
import re

from app.services.summary_visual_artifact import (
    SummaryVisualError, build_summary_visual, reviewed_visual_blocks,
    reviewed_claim_sources, save_summary_visual,
)
from app.services.video_evidence_service import _MAX_IMAGE_BYTES


def _need(condition):
    if not condition:
        raise SummaryVisualError('图形尚未完成：本次正文、布局或真实截图无法核验')


def render_review_visual(artifacts, context, markdown):
    """Build wire from reviewed IDs; save without changing the reviewed body."""
    snapshot = getattr(context, 'presentation_visual', None)
    _need(isinstance(snapshot, dict) and set(snapshot) == {'review', 'claim_sources'})
    review, sources = snapshot['review'], snapshot['claim_sources']
    blocks = reviewed_visual_blocks(review)
    if review['protocol'] in (4, 5, 6):
        _need(sources == reviewed_claim_sources(review))
    _need('\n\n'.join(block['text'] for block in blocks).strip() == markdown)
    if review['protocol'] == 6:
        from app.llm.meeting_visual_projection6 import project_review6
        _, plan = project_review6(review, presentation=context.presentation)
    elif review['protocol'] == 5:
        from app.llm.meeting_visual_projection import project_review5
        _, plan = project_review5(review, presentation=context.presentation)
    else:
        plan = review.get('visual')
    _need(type(plan) is dict and set(plan) == {'scenes', 'diagram'})
    scenes, frames, copies = plan['scenes'], [], []
    if context.presentation == 'comic':
        _need(type(scenes) is list and 1 <= len(scenes) <= 8 and plan['diagram'] is None)
        evidence = context.video_evidence
        _need(evidence is not None and bool(evidence.frames))
        by_block = {block['id']: block['claim_ids'] for block in blocks}
        selected = {}
        for scene in scenes:
            _need(type(scene) is dict and isinstance(scene.get('frame_id'), str)
                  and re.fullmatch(r'\[FRAME:[0-9]{4,}\]', scene['frame_id'])
                  and type(scene.get('block_ids')) is list)
            ref = scene['frame_id']
            _need(all(isinstance(key, str) and key in by_block for key in scene['block_ids']))
            _need(any(ref in sources.get(claim, []) for key in scene['block_ids'] for claim in by_block[key]))
            if ref in selected:
                continue
            index = int(ref[7:-1]) - 1
            _need(0 <= index < len(evidence.frames))
            frame = evidence.frames[index]
            expected = getattr(evidence, '_summary_frame_hashes', {}).get(frame.image_path)
            _need(expected and not frame.image_path.is_symlink())
            with frame.image_path.open('rb') as stream:
                data = stream.read(_MAX_IMAGE_BYTES + 1)
            _need(0 < len(data) <= _MAX_IMAGE_BYTES and hashlib.sha256(data).hexdigest() == expected)
            selected[ref] = len(frames)
            frames.append({'id': ref, 'screenshot_index': selected[ref],
                           'timestamp_seconds': frame.timestamp,
                           'grounded_label': scene.get('grounded_label')})
            copies.append((selected[ref], data))
    else:
        _need(context.presentation == 'infographic' and scenes == [])
    wire = build_summary_visual(task_id=context.task_id, presentation=context.presentation,
        markdown=markdown, blocks=blocks, frames=frames, scenes=scenes, diagram=plan['diagram'])
    if copies:
        folder = context.task_dir / 'screenshots'
        _need(not folder.is_symlink() and not getattr(folder, 'is_junction', lambda: False)())
        folder.mkdir(exist_ok=True)
        _need(folder.resolve().parent == context.task_dir.resolve())
        for index, data in copies:
            destination = folder / f'summary-source-{index}.jpg'
            _need(not destination.is_symlink())
            try:
                with destination.open('xb') as stream:
                    stream.write(data)
            except FileExistsError:
                _need(destination.read_bytes() == data)
    save_summary_visual(artifacts, context.user_id, context.task_id, markdown, wire)
    return markdown
