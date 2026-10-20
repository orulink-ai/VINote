"""The same original ASR windows must be identifiable beside actual frames."""
from app.llm.openai_llm import _BasePromptLLM
from app.models.transcript import TranscriptSegment
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
from PIL import Image
import pytest


def test_source_labels_preserve_text_and_do_not_assign_nearby_speech(tmp_path):
    windows = [TranscriptSegment(0, 10, 'Candidate route price is 410.'),
               TranscriptSegment(20, 30, 'A separate return booking remains open.')]
    image = tmp_path / 'screen.jpg'
    Image.new('RGB', (80, 60), 'white').save(image)
    frames = [VideoFrameEvidence(5, image, ['timeline'], [5]),
              VideoFrameEvidence(15, image, ['timeline'], [15]),
              VideoFrameEvidence(25, image, ['timeline'], [25])]
    evidence = VideoEvidence(30, frames, scanned_samples=30, scan_complete=True).align(windows)
    text = object.__new__(_BasePromptLLM)._build_segment_text(windows)
    assert '[ASR:0001]' in text and '[ASR:0002]' in text
    assert all(window.text in text for window in windows)
    payload = evidence.user_content(text, capabilities={'vision': True})
    labels = [block['text'] for block in payload[1:] if block['type'] == 'text']
    assert '[FRAME:0001]' in labels[0] and '[ASR:0001]' in labels[0]
    assert '[ASR:0002]' not in labels[0]
    assert '[FRAME:0002]' in labels[1] and '[ASR:' not in labels[1]
    assert '[FRAME:0003]' in labels[2] and '[ASR:0002]' in labels[2]
    assert '[ASR:0001]' not in labels[2]
    assert frames[1].speech_indices == []


def test_duplicate_frame_offsets_reference_all_overlapping_windows_without_merging(tmp_path):
    windows = [TranscriptSegment(0, 10, 'Original proposal.'),
               TranscriptSegment(20, 30, 'Changed proposal.')]
    image = tmp_path / 'screen.jpg'
    Image.new('RGB', (80, 60), 'white').save(image)
    frame = VideoFrameEvidence(5, image, ['timeline'], [5, 25])
    evidence = VideoEvidence(30, [frame], scanned_samples=30, scan_complete=True).align(windows)
    payload = evidence.user_content('Complete source', capabilities={'vision': True})
    assert frame.speech_indices == [0, 1]
    assert '[ASR:0001]' in payload[1]['text'] and '[ASR:0002]' in payload[1]['text']
    assert len([block for block in payload if block['type'] == 'image_url']) == 1
    assert windows[0].text == 'Original proposal.' and windows[1].text == 'Changed proposal.'


def test_legacy_subsets_and_nested_requests_keep_original_addresses_then_reset():
    from app.llm.source_references import bind_source_references
    llm = object.__new__(_BasePromptLLM)
    segments = [TranscriptSegment(0, 10, 'First.'), TranscriptSegment(20, 30, 'Second.')]
    with bind_source_references(segments):
        assert '[ASR:0002]' in llm._build_segment_text(segments[1:])
        with bind_source_references([TranscriptSegment(0, 1, 'Other task.')]):
            with pytest.raises(ValueError, match='reference changed'):
                llm._build_segment_text([TranscriptSegment(0, 1, 'Unbound.')])
        assert '[ASR:0002]' in llm._build_segment_text(segments[1:])
    assert '[ASR:0001]' in llm._build_segment_text(segments[1:])


def test_final_reference_cleanup_keeps_real_values_and_business_identifiers():
    from app.llm.source_references import without_internal_references
    assert without_internal_references('## Plan\nShip 24 units [ASR:0001] by 09:40 [FRAME:0017].\n[SKU:0001]') == (
        '## Plan\nShip 24 units  by 09:40 .\n[SKU:0001]')


def test_reference_only_review_is_not_a_saved_summary():
    class EmptyReview(_BasePromptLLM):
        def _complete(self, **kwargs):
            return '[ASR:0001] [FRAME:9999]'
    with pytest.raises(RuntimeError, match='事实复核'):
        EmptyReview()._review_meeting_note(source='source', draft='draft', extras=None, output_language='en')


def test_working_draft_capture_is_not_final_output_and_does_not_add_calls_or_leak():
    from app.llm.source_references import capture_working_draft
    class SourceFirst(_BasePromptLLM):
        def __init__(self):
            self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            return 'Working: pack 24 units [ASR:0001]' if len(self.calls) % 2 else 'Pack 24 units.'
    llm, observed = SourceFirst(), []
    with capture_working_draft(observed.append):
        assert llm.summarize('Meeting', [TranscriptSegment(0, 1, 'Pack 24 units.')], style='meeting') == 'Pack 24 units.'
    assert observed == ['Working: pack 24 units [ASR:0001]']
    assert len(llm.calls) == 2 and all('Pack 24 units.' in call['user_prompt'] for call in llm.calls)
    assert 'Working: pack 24 units' in llm.calls[1]['user_prompt']
    llm.summarize('Other', [TranscriptSegment(0, 1, 'Other.')], style='meeting')
    assert len(observed) == 1 and len(llm.calls) == 4
