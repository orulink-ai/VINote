from unittest.mock import Mock, patch

import pytest
from PIL import Image

from app.llm.openai_llm import _BasePromptLLM, OpenAILLM, AnthropicLLM, AzureOpenAILLM
from app.llm.prompts import build_user_prompt
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence, VideoEvidenceError


def evidence(tmp_path, text='SCREEN_PROPOSAL_NOT_DECISION'):
    image = tmp_path / 'screen.jpg'
    Image.new('RGB', (64, 36), 'white').save(image)
    return VideoEvidence(100, [VideoFrameEvidence(99, image, ['text_or_detail_change'], [99],
                                                text, 'recognized' if text else 'unavailable')],
                         scanned_samples=100, scan_complete=True)


class RecordingLLM(_BasePromptLLM):
    def __init__(self):
        self.calls = []

    def _complete(self, **prompts):
        from app.llm.video_material import video_user_content
        self.calls.append(video_user_content(prompts['user_prompt']))
        return 'dynamic note'


def test_text_model_gets_actual_extracted_text_and_entire_source_in_draft_and_review(tmp_path):
    llm = RecordingLLM()
    material = evidence(tmp_path)
    llm.summarize('Meeting', [TranscriptSegment(0, 100, 'FULL_SPEECH_END')],
                  style='meeting', video_evidence=material)
    assert len(llm.calls) == 2
    for call in llm.calls:
        assert isinstance(call, str)
        assert 'FULL_SPEECH_END' in call and 'SCREEN_PROPOSAL_NOT_DECISION' in call
        assert 'No images were supplied' in call


@pytest.mark.parametrize('capabilities,verified', [({'vision': True}, False), ({}, True)])
def test_verified_or_explicit_vision_sends_actual_image_in_draft_and_review(tmp_path, capabilities, verified):
    llm = RecordingLLM()
    llm.configure_video_capabilities(capabilities, image_input_verified=verified)
    llm.summarize('Meeting', [TranscriptSegment(0, 100, 'FULL_SOURCE')], style='meeting',
                  video_evidence=evidence(tmp_path, text=None))
    assert len(llm.calls) == 2
    for call in llm.calls:
        assert call[0]['type'] == 'text'
        assert 'FULL_SOURCE' in call[0]['text']
        assert any(block['type'] == 'image_url' and block['image_url']['url'].startswith('data:image/jpeg;base64,')
                   for block in call)
    # No evidence or base64 leaks into the following ordinary request.
    llm.summarize('Other', [TranscriptSegment(0, 1, 'OTHER')])
    assert isinstance(llm.calls[-1], str) and 'SCREEN' not in llm.calls[-1]


def test_unknown_capability_does_not_send_images_or_call_provider_without_text(tmp_path):
    llm = RecordingLLM()
    llm.configure_video_capabilities({'thinking': {'status': 'unknown', 'default': True}})
    with pytest.raises(VideoEvidenceError):
        llm.summarize('Meeting', [], video_evidence=evidence(tmp_path, None))
    assert not llm.calls


def test_visual_review_does_not_switch_to_other_model_or_query_catalog(tmp_path):
    llm = VILabLLM('user', 'chosen-model')
    llm.configure_video_capabilities({}, image_input_verified=True)
    used = []
    def complete(self, **prompts):
        from app.llm.video_material import video_user_content
        used.append((self.model, video_user_content(prompts['user_prompt'])))
        return 'supported note'
    with patch.object(VILabLLM, '_complete', complete), \
            patch('app.llm.vilab_llm.VILabCloudService.models', side_effect=AssertionError('no switching')):
        llm.summarize('Meeting', [], style='meeting', video_evidence=evidence(tmp_path))
    assert len(used) == 2 and all(model == 'chosen-model' for model, _ in used)


def test_openai_transport_receives_images_but_tracing_receives_only_text(tmp_path):
    llm = OpenAILLM('offline-test-key', model='user-choice')
    llm.configure_video_capabilities({'vision': True})
    response = Mock()
    response.choices = [Mock(message=Mock(content='note'))]
    with patch.object(llm.client.chat.completions, 'create', return_value=response) as create, \
            patch('app.services.tracing_service.content_summary', side_effect=lambda value: value) as trace:
        llm.summarize('Meeting', [TranscriptSegment(0, 100, 'speech')], video_evidence=evidence(tmp_path))
    payload = create.call_args.kwargs
    assert payload['model'] == 'user-choice'
    assert any(block['type'] == 'image_url' for block in payload['messages'][1]['content'])
    assert all(block['image_url']['detail'] == 'high' for block in payload['messages'][1]['content']
               if block['type'] == 'image_url')
    assert 'base64' not in str(trace.call_args_list) and str(tmp_path) not in str(trace.call_args_list)


@pytest.mark.parametrize('kind', ['vilab', 'anthropic', 'azure'])
def test_other_adapters_send_actual_images_to_exact_selected_model(tmp_path, kind):
    if kind == 'vilab':
        llm = VILabLLM('user', 'selected')
        target = 'app.llm.vilab_llm.VILabCloudService.request'
        response = {'choices': [{'message': {'content': 'note'}}]}
    elif kind == 'anthropic':
        llm = AnthropicLLM('offline-key', model='selected')
        target = 'app.llm.openai_llm.post_anthropic_compatible'
        response = Mock()
        response.json.return_value = {'content': [{'type': 'text', 'text': 'note'}]}
    else:
        llm = AzureOpenAILLM('offline-key', 'https://offline.invalid', 'selected')
        target = 'app.llm.openai_llm.httpx.post'
        response = Mock()
        response.json.return_value = {'choices': [{'message': {'content': 'note'}}]}
    llm.configure_video_capabilities({'vision': {'supported': True}})
    with patch(target, return_value=response) as request:
        llm.summarize('Topic', [], video_evidence=evidence(tmp_path))
    payload = request.call_args.kwargs['json_body' if kind == 'anthropic' else 'json']
    content = payload['messages'][-1]['content']
    assert any(block['type'] == ('image' if kind == 'anthropic' else 'image_url') for block in content)
    if kind != 'anthropic':
        assert all(block['image_url']['detail'] == 'high' for block in content if block['type'] == 'image_url')
    if kind != 'azure':
        assert payload['model'] == 'selected'


def test_provider_failure_never_replays_switches_or_leaks_material_to_next_request(tmp_path):
    llm = RecordingLLM()
    llm.configure_video_capabilities({}, image_input_verified=True)
    with patch.object(llm, '_complete', side_effect=RuntimeError('context exceeded')) as complete:
        with pytest.raises(RuntimeError, match='context exceeded'):
            llm.summarize('Topic', [], style='meeting', video_evidence=evidence(tmp_path))
    complete.assert_called_once()
    llm.summarize('Next', [TranscriptSegment(0, 1, 'next')])
    assert isinstance(llm.calls[-1], str) and 'VIDEO SOURCE' not in llm.calls[-1]


def test_image_verification_does_not_transfer_to_a_changed_model(tmp_path):
    llm = RecordingLLM()
    llm.model = 'verified'
    llm.configure_video_capabilities({}, image_input_verified=True)
    llm.model = 'different'
    with pytest.raises(VideoEvidenceError):
        llm.summarize('Topic', [], video_evidence=evidence(tmp_path, None))
    assert llm.calls == []


@pytest.mark.parametrize('limit', ['image', 'total'])
def test_high_resolution_budget_fails_before_any_provider_call_without_dropping(tmp_path, limit):
    from app.services import video_evidence_service as module
    material = evidence(tmp_path)
    path = material.frames[0].image_path
    if limit == 'image':
        path.write_bytes(path.read_bytes().ljust(384 * 1024 + 1, b'\0'))
    else:
        # Each image fits; 43 x 384 KiB exceeds the 16 MiB complete payload.
        path.write_bytes(path.read_bytes().ljust(384 * 1024, b'\0'))
        material.frames = [VideoFrameEvidence(i, path, ['timeline'], [i]) for i in range(43)]
    original_count = len(material.frames)
    llm = RecordingLLM()
    llm.configure_video_capabilities({'vision': True})
    with pytest.raises(VideoEvidenceError, match='预算'):
        llm.summarize('Source', [], video_evidence=material)
    assert not llm.calls and len(material.frames) == original_count
    assert module._MAX_IMAGE_BYTES == 384 * 1024 and module._MAX_PAYLOAD_BYTES == 16 * 1024 * 1024


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
def test_visual_and_asr_uncertainty_rules_reach_draft_and_review(language):
    from app.llm.prompts import build_system_prompt
    from app.llm.meeting_review import build_meeting_review_prompts
    draft = build_system_prompt(language)
    review = build_meeting_review_prompts(source='source', draft='draft', extras=None,
                                          output_language=language)['system_prompt']
    assert ('看不清' in draft if language == 'zh-CN' else 'illegible' in draft)
    assert ('连接关系' in draft if language == 'zh-CN' else 'connections' in draft)
    assert 'corrupted ASR' in review and 'do not guess' in review


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
def test_meeting_structure_is_content_driven_and_diagnostics_stay_internal(language):
    prompt = build_user_prompt('Meeting', 'source', style='meeting', output_language=language)
    assert '3–5' not in prompt
    assert '1. 会议概览' not in prompt
    assert 'completion criterion' not in prompt
    assert ('不固定章节' in prompt if language == 'zh-CN' else 'no fixed sections' in prompt)
    assert ('识别' in prompt if language == 'zh-CN' else 'recognition' in prompt)
