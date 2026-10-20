"""Actual host pipeline contracts, with synthetic responses and no provider calls."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

@pytest.mark.parametrize('presentation', ['text', 'html', 'infographic'])
def test_actual_opt_in_layout_keeps_two_full_source_calls_and_original_responses(tmp_path, monkeypatch, presentation):
    from app.llm.openai_llm import _BasePromptLLM
    from app.llm.source_references import capture_working_draft
    from app.models.transcript import TranscriptSegment
    from app.services.summary_presentation_artifact import render_presentation
    raw_source = 'Zephrel reaches 62.875 bar only after the violet gate locks.'
    draft = {'protocol': 3, 'topics': [{'id': 'T2', 'title': 'Zephrel'}], 'claims': [
        {'id': 'C8', 'topic_id': 'T2', 'field': 'condition', 'text': raw_source, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': raw_source}]}]}
    review = {'protocol': 3, 'blocks': [{'id': 'B6', 'markdown': raw_source}],
        'audit': [{'claim_id': 'C8', 'disposition': 'included', 'block_ids': ['B6']}], 'figures': []}
    if presentation == 'infographic':
        review['visual'] = {'scenes': [], 'diagram': {'kind': 'cards',
            'nodes': [{'id': 'N8', 'block_ids': ['B6'], 'grounded_label': '62.875 bar'}], 'edges': []}}
    class Automatic(_BasePromptLLM):
        def __init__(self): self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert raw_source in prompts['user_prompt']
            return json.dumps(draft if len(self.calls) == 1 else review)
    automatic, observed, saved_wire = Automatic(), [], []
    monkeypatch.setattr('app.services.summary_visual_generation.save_summary_visual',
        lambda *args: saved_wire.append(args[-1]))
    from app.llm.meeting_presentation import presentation_scope
    with presentation_scope('brief', presentation) as state, capture_working_draft(observed.append):
        body = automatic.summarize('Synthetic source', [TranscriptSegment(0, 9, raw_source)], style='meeting')
        assert state.raw_review == json.dumps(review)
        if presentation == 'infographic':
            context = SimpleNamespace(task_id=str(uuid4()), task_dir=tmp_path, user_id='fixture-owner',
                presentation=presentation, video_evidence=None, presentation_visual=state.visual_review)
            assert render_presentation(None, context, body) == raw_source
            assert saved_wire[0]['blocks'][0]['claim_ids'] == ['C8']
        else:
            assert state.visual_review is None
    assert body == raw_source and len(automatic.calls) == 2 and observed == [json.dumps(draft)]
    assert ('VISUAL LAYOUT' in automatic.calls[1]['system_prompt']) == (presentation == 'infographic')


def test_actual_graphic_without_layout_keeps_raw_review_but_cannot_claim_completion(monkeypatch):
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    from app.llm.source_references import bind_source_references
    from app.models.transcript import TranscriptSegment
    raw = 'Solven preserves 46.125 volts.'
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Solven'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'quantity', 'text': raw, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': raw}]}]}
    response = json.dumps({'protocol': 3, 'blocks': [{'id': 'B1', 'markdown': raw}],
        'audit': [{'claim_id': 'C1', 'disposition': 'included', 'block_ids': ['B1']}], 'figures': []})
    from app.llm.meeting_presentation import presentation_scope
    with presentation_scope('brief', 'infographic') as state, bind_source_references([TranscriptSegment(0, 5, raw)]):
        prepared = prepare_fact_material(json.dumps(draft), raw, require_protocol=3)
        with pytest.raises(ValueError, match='布局'):
            finalize_fact_review(response, prepared, raw)
        assert state.raw_review == response and state.visual_review is None
