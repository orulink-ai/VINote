"""Real slotted NoteService context -> review state -> private visual artifact.

Only model responses, image-capability probing and the DB session destination
are substituted. Context assignment, claim checks, rendering, screenshot copy,
artifact authorization, persistence and authenticated reads use production code.
"""
import copy
import hashlib
import json
import time
from unittest.mock import Mock

import pytest

from tests.test_summary_visual_artifact import case
from app.db_models import SourceRequestDB
from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.openai_llm import _BasePromptLLM
from app.models.audio import AudioDownloadResult
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.meeting_summary_regeneration import _digest, _submission
from app.services.note_service import NoteService, PipelineContext
from app.services.source_request_service import _fingerprint
from app.services.summary_visual_artifact import SIDECAR, read_summary_visual
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
from app.services.vilab_cloud_service import VILabCloudService


SOURCE = 'Keep the turquoise valve closed until the second bell.'


def pipeline(c, monkeypatch, presentation, depth, *, invalid_quote=False):
    # Reuse the isolated accepted-receipt fixture, never the runtime account DB.
    body = c.body.model_copy(update={'presentation': presentation, 'content_depth': depth})
    c.write('new_generation.json', {'contract': 'meeting-summary-only-v1', 'parent_task_id': c.parent,
                                   **body.model_dump(mode='json')})
    metadata = json.loads((c.folder / 'summary_presentation.json').read_bytes())
    c.write('summary_presentation.json', {**metadata, 'presentation': presentation, 'content_depth': depth})
    with c.sessions() as db:
        db.get(SourceRequestDB, (c.owner, str(body.operation_id))).fingerprint = _fingerprint(_submission(c.parent, body))
    c.artifacts.update_status(c.folder, 'preparing', 'Synthetic offline task')
    monkeypatch.setattr('app.services.summary_visual_artifact.session_scope', c.sessions)

    donor = c.tmp_path / 'donor'
    donor.mkdir()
    frame = donor / 'original.jpg'
    original_bytes = c.screenshot.read_bytes()
    frame.write_bytes(original_bytes)
    evidence = VideoEvidence(10, [VideoFrameEvidence(1.25, frame, ['timeline'], [1.25])], 10, True)
    evidence._summary_frame_hashes = {frame: hashlib.sha256(original_bytes).hexdigest()}
    proof = [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE},
             {'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
              'observation': 'The displayed requirement keeps the turquoise valve closed.'}]
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic valve condition'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': SOURCE,
         'material': True, 'evidence': copy.deepcopy(proof)}]}
    review = {'protocol': 4, 'blocks': [{'id': 'H1', 'markdown': '# Synthetic valve condition'},
                                      {'id': 'B1', 'markdown': SOURCE}], 'claims': [
        {'id': 'C1', 'field': 'condition', 'text': SOURCE, 'material': True,
         'disposition': 'included', 'block_ids': ['B1'], 'evidence': copy.deepcopy(proof)}]}
    if presentation == 'comic':
        review['visual'] = {'scenes': [{'id': 'S1', 'block_ids': ['B1'], 'frame_id': '[FRAME:0001]',
                                      'grounded_label': SOURCE}], 'diagram': None}
    else:
        review['visual'] = {'scenes': [], 'diagram': {'kind': 'cards', 'edges': [],
            'nodes': [{'id': 'N1', 'block_ids': ['B1'], 'grounded_label': SOURCE}]}}
    if invalid_quote:
        review['claims'][0]['evidence'][0]['quote'] = 'This clause was never supplied.'
    raw3, raw4 = json.dumps(draft, indent=2), json.dumps(review, indent=2)

    class Automatic(_BasePromptLLM):
        def __init__(self):
            self.user_id, self.model, self.calls = c.owner, body.model_name, []

        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert len(self.calls) <= 2, 'No repair or replay call'
            assert SOURCE in prompts['user_prompt']
            return raw3 if len(self.calls) == 1 else raw4

    automatic = Automatic()
    factory = Mock(return_value=automatic)
    catalog = Mock(return_value=[{'id': body.model_name, 'modelType': 'llm',
                                  'capabilities': {'vision': True}}])
    monkeypatch.setattr(VILabCloudService, 'models', catalog)
    monkeypatch.setattr('app.services.video_model_capability.verify_image_input', Mock(return_value=True))
    monkeypatch.setattr('app.services.windows_ocr.recognize_batch', Mock(side_effect=AssertionError('No native OCR')))
    runner = object.__new__(NoteService)
    runner.artifact_service = c.artifacts
    runner.llm_service = Mock(create_summarizer=factory)
    runner.transcription_service = Mock(transcribe=Mock(side_effect=AssertionError('No ASR')))
    transcript = TranscriptResult('en', SOURCE, [TranscriptSegment(0, 10, SOURCE)])
    context = PipelineContext(task_id=c.task, task_dir=c.folder,
        audio_meta=AudioDownloadResult(str(donor / 'retained.webm'), 'Synthetic meeting', 10, c.task, 'local'),
        style='meeting', summary_mode='default', extras=None, output_language='en',
        model_profile_id=None, stt_profile_id=None, model_name=body.model_name,
        api_key=None, base_url=None, user_id=c.owner, source_video_url=None,
        task_start_time=time.time(), step_timings={}, video_evidence=evidence,
        content_depth=depth, presentation=presentation)
    assert type(context) is PipelineContext and not hasattr(context, '__dict__')
    assert getattr(context, 'presentation_visual', None) is None
    return runner, context, transcript, automatic, review, raw3, raw4, frame, original_bytes


@pytest.mark.parametrize('presentation', ['comic', 'infographic'])
@pytest.mark.parametrize('depth', ['brief', 'detailed'])
def test_real_slotted_context_hands_review_state_to_render_and_private_artifact(case, monkeypatch, presentation, depth):
    c = case
    runner, context, transcript, automatic, review, raw3, raw4, frame, original = pipeline(
        c, monkeypatch, presentation, depth)

    # This exact production call raised AttributeError before the missing slot
    # was added; a SimpleNamespace context would have silently hidden the bug.
    markdown = runner._summarize_audio(context, transcript)
    assert context.presentation_visual == {'review': review,
        'claim_sources': {'C1': ['[ASR:0001]', '[FRAME:0001]']}}
    assert context.presentation_figures is None
    assert len(automatic.calls) == 2 and 'summarize' in context.step_timings
    from app.llm.meeting_presentation import depth_instructions, final_depth_selection
    assert final_depth_selection(depth) in automatic.calls[1]['system_prompt']
    assert depth_instructions(depth).replace('The report field contains Markdown facts only;',
        'Report blocks[].markdown contain Markdown facts only;') in automatic.calls[1]['system_prompt']
    assert final_depth_selection(depth) not in automatic.calls[0]['system_prompt']
    runner.llm_service.create_summarizer.assert_called_once_with(user_id=c.owner,
        model_profile_id=None, model_name=context.model_name, api_key=None, base_url=None)
    runner.transcription_service.transcribe.assert_not_called()
    assert json.loads((c.folder / 'meeting_working_draft.json').read_bytes())['text'] == raw3
    review_path = c.folder / 'meeting_fact_review.json'
    review_bytes = review_path.read_bytes()
    assert json.loads(review_bytes)['raw_response'] == raw4

    # No render/save/read helper is mocked, including DB-bound authorization.
    rendered = runner._enrich_markdown_with_media(context, transcript, markdown)
    assert rendered == markdown
    path = c.folder / SIDECAR
    payload = json.loads(path.read_bytes())
    wire = payload['visual']
    assert wire['presentation'] == presentation and wire['task_id'] == context.task_id
    assert wire['blocks'][1]['claim_ids'] == ['C1']
    assert payload['review_sha256'] == hashlib.sha256(review_bytes).hexdigest()
    assert payload['receipt']['snapshot_sha256'] == _digest(c.snapshot)
    assert wire['body_sha256'] == hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    assert wire['scenes'] == review['visual']['scenes'] and wire['diagram'] == review['visual']['diagram']
    assert bool(wire['frames']) == (presentation == 'comic')
    if presentation == 'comic':
        assert (c.folder / 'screenshots/summary-source-0.jpg').read_bytes() == original
        assert wire['frames'][0]['id'] == '[FRAME:0001]'
    else:
        assert payload['screenshots'] == {}
    assert frame.read_bytes() == original and review_path.read_bytes() == review_bytes
    assert read_summary_visual(c.artifacts, c.owner, c.task, sessions=c.sessions) is None

    result = runner._build_result(context, transcript, rendered)
    c.artifacts.save_markdown(c.folder, rendered)
    c.artifacts.save_result(c.folder, result)
    c.artifacts.update_status(c.folder, 'success', 'Synthetic offline completion')
    before = {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    assert read_summary_visual(c.artifacts, c.owner, c.task, sessions=c.sessions) == wire
    assert read_summary_visual(c.artifacts, 'different-owner', c.task, sessions=c.sessions) is None
    assert before == {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}


@pytest.mark.parametrize('presentation', ['comic', 'infographic'])
def test_real_context_keeps_failed_raw_review_without_publishing_visual(case, monkeypatch, presentation):
    c = case
    runner, context, transcript, automatic, _, _, raw4, frame, original = pipeline(
        c, monkeypatch, presentation, 'detailed', invalid_quote=True)
    with pytest.raises(FinalLedgerError) as error:
        runner._summarize_audio(context, transcript)
    assert error.value.code == 'invalid_final_evidence'
    assert len(automatic.calls) == 2 and context.presentation_visual is None
    assert json.loads((c.folder / 'meeting_fact_review.json').read_bytes())['raw_response'] == raw4
    assert not (c.folder / SIDECAR).exists() and frame.read_bytes() == original
    runner.transcription_service.transcribe.assert_not_called()
