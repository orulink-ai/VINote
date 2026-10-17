from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.config import settings
from app.llm.openai_llm import _BasePromptLLM
from app.models.transcript import TranscriptSegment, TranscriptResult


class FullSourceLLM(_BasePromptLLM):
    def __init__(self):
        self.calls = []
        self.reject_at = None

    def _complete(self, **prompts):
        self.calls.append(prompts)
        if ((self.reject_at == 'draft' and len(self.calls) == 1)
                or (self.reject_at == 'review' and len(self.calls) == 2)):
            raise HTTPException(400, 'context_length_exceeded')
        return 'complete draft' if len(self.calls) == 1 else 'reviewed whole note'


@pytest.mark.parametrize('exceeds', ['chars', 'segments', 'speaker_evidence'])
@pytest.mark.parametrize('mode', ['default', 'oneshot'])
def test_default_full_source_and_overall_review_ignore_old_thresholds(exceeds, mode, monkeypatch):
    monkeypatch.setattr(settings, 'summary_default_max_chars', 2000 if exceeds != 'segments' else 1000000)
    monkeypatch.setattr(settings, 'summary_default_max_segments', 2 if exceeds == 'segments' else 1000000)
    segments = [TranscriptSegment(i, i + 1, f'UNIQUE_SOURCE_{i} ' + ('x' * 900 if exceeds == 'chars' else 'short'),
        speaker_evidence=([{'start': i, 'end': i + 1, 'speaker_id': f'speaker_{j}'} for j in range(30)]
                          if exceeds == 'speaker_evidence' else [])) for i in range(6)]
    llm = FullSourceLLM()
    progress = []
    with patch.object(llm, '_chunk_segments', side_effect=AssertionError('default must not chunk')):
        result = llm.summarize('Full source', segments, style='meeting', summary_mode=mode,
                              extras='COMPLETE_EXTRAS', progress_callback=progress.append)
    assert result == 'reviewed whole note' and len(llm.calls) == 2
    for call in llm.calls:
        assert 'COMPLETE_EXTRAS' in call['user_prompt']
        for segment in segments:
            assert segment.text in call['user_prompt']
        if exceeds == 'speaker_evidence':
            assert 'speaker_29' in call['user_prompt']
    assert 'complete draft' in llm.calls[1]['user_prompt']
    assert not any('chunk' in message or '分段' in message for message in progress)


@pytest.mark.parametrize('failure_at', ['draft', 'review'])
def test_context_rejection_preserves_source_and_never_splits_switches_or_retries(failure_at):
    llm = FullSourceLLM()
    source = [TranscriptSegment(0, 10, 'RETAIN_ALL_' + 'x' * 20000)]
    before = source[0].text
    failure = HTTPException(400, 'context_length_exceeded')
    with patch.object(llm, '_complete', side_effect=([failure] if failure_at == 'draft' else ['draft', failure])) as complete, \
            patch.object(llm, '_chunk_segments', side_effect=AssertionError('no fallback')):
        with pytest.raises(HTTPException) as caught:
            llm.summarize('Full', source, style='meeting', summary_mode='default')
    assert caught.value is failure
    assert complete.call_count == (1 if failure_at == 'draft' else 2)
    assert source[0].text == before


@pytest.mark.parametrize('reject_at', [None, 'draft', 'review'])
def test_transcript_pipeline_default_retains_full_source_reviews_and_never_calls_asr(tmp_path, monkeypatch, reject_at):
    from app.services.note_service import NoteService
    from app.services.task_artifact_service import TaskArtifactService
    from app.services.vilab_cloud_service import VILabCloudService
    monkeypatch.setattr(VILabCloudService, 'status', lambda *a: {'mode': 'local'})
    monkeypatch.setattr(settings, 'summary_default_max_chars', 2000)
    monkeypatch.setattr(settings, 'summary_default_max_segments', 1)
    transcript = TranscriptResult('zh', 'BEGIN ' + '全文资料' * 2000 + ' END',
        [TranscriptSegment(0, 22, 'BEGIN ' + '全文资料' * 2000 + ' END')])
    llm = FullSourceLLM()
    llm.reject_at = reject_at
    llm_service = Mock()
    llm_service.resolve_config.return_value = Mock(model_name='selected-frozen-model')
    llm_service.create_summarizer.return_value = llm
    transcription = Mock()
    transcription.transcribe.side_effect = AssertionError('ASR forbidden')
    artifacts = TaskArtifactService(tmp_path / 'output')
    service = NoteService(llm_service=llm_service, transcription_service=transcription, artifact_service=artifacts)
    # The existing model-freeze contract also needs resolved local STT identity
    # only for media; transcript input deliberately never resolves it.
    with patch('app.services.task_model_source.capture_source', return_value={
        'version': 1, 'owner': None, 'mode': 'local', 'server_url': '', 'asr_model': '', 'llm_model': '',
        'needs_stt': False, 'local_llm_fingerprint': 'a' * 64, 'local_stt_fingerprint': 'b' * 64}), \
            patch('app.services.speaker_diarization_service.SpeakerDiarizationService.transcribe',
                  side_effect=AssertionError('speaker analysis forbidden')):
        if reject_at:
            with pytest.raises(HTTPException, match='context_length_exceeded'):
                service.generate_from_transcript(transcript, 'full-summary-offline', style='meeting')
        else:
            result = service.generate_from_transcript(transcript, 'full-summary-offline', style='meeting')
            assert result.markdown == 'reviewed whole note'
    assert len(llm.calls) == (1 if reject_at == 'draft' else 2)
    assert all(transcript.full_text in call['user_prompt'] for call in llm.calls)
    transcription.transcribe.assert_not_called()
    folder = artifacts.find_task_dir('full-summary-offline')
    assert artifacts.load_transcript(folder).full_text == transcript.full_text
    if reject_at:
        assert artifacts.get_status('full-summary-offline')['status'] == 'failed'
        assert not (folder / 'result.json').exists() and not (folder / 'note.md').exists()
    else:
        assert (folder / 'result.json').is_file() and (folder / 'note.md').is_file()
