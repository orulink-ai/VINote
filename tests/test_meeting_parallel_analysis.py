import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.speaker_diarization_service import SpeakerDiarizationService, SpeakerTurn


def test_asr_runs_during_diarization_and_saved_speakers_survive_asr_retry(tmp_path):
    started, detecting = threading.Event(), threading.Event()
    source = tmp_path / 'original.wav'
    source.write_bytes(b'unchanged original')
    # The worker is mocked, but evidence signatures still inspect model files.
    # Keep those inputs isolated instead of depending on installed machine models.
    models = (tmp_path / 'segmentation.onnx', tmp_path / 'embedding.onnx')
    for model in models:
        model.write_bytes(b'synthetic-model-signature')
    evidence = tmp_path / 'evidence'
    attempts = 0

    def recognize(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        assert kwargs['diarization_parallel'] is True
        started.set()
        assert detecting.wait(2), 'ASR must overlap speaker processing'
        if attempts == 1:
            raise RuntimeError('ASR unavailable')
        return TranscriptResult('zh', '确认测试。', [TranscriptSegment(0, 2, '确认测试。')],
                                {'timestamp_granularity': 'chunk'})

    def detect(*args, **kwargs):
        assert started.wait(2), 'ASR must start before diarization finishes'
        detecting.set()
        return [SpeakerTurn(0, 2, 'speaker_1')], {}

    def prepare(_, output):
        np.zeros(32000, dtype='float32').tofile(output)
        return {'timeline_trimmed': False}

    with patch.object(SpeakerDiarizationService, 'require_ready'), \
            patch.object(SpeakerDiarizationService, 'model_paths', return_value=models), \
            patch('app.services.speaker_diarization_service.prepare_meeting_audio', side_effect=prepare), \
            patch('app.services.speaker_worker.run_speaker_worker', side_effect=detect) as worker:
        service = SpeakerDiarizationService()
        with pytest.raises(RuntimeError, match='ASR unavailable'):
            service.transcribe(audio_path=str(source), transcribe=recognize, speaker_count=2, evidence_dir=evidence)
        assert json.loads((evidence / 'speaker_evidence.json').read_text())['turns']
        assert not (evidence / 'asr_evidence.json').exists()
        result = service.transcribe(audio_path=str(source), transcribe=recognize, speaker_count=2, evidence_dir=evidence)
        assert worker.call_count == 1
        assert result.metadata['analysis_parallel'] is True
        assert result.metadata['speaker_alignment_estimated'] is True
        assert (evidence / 'asr_evidence.json').exists()
        assert source.read_bytes() == b'unchanged original'


def test_llm_keeps_chunk_text_and_independent_speaker_intervals_separate():
    from app.llm.openai_llm import OpenAILLM
    segment = TranscriptSegment(0, 60, '甲提出建议，乙没有确认。', timestamp_estimated=True,
                                speaker_evidence=[{'start': 5., 'end': 10., 'speaker_id': 'speaker_1'},
                                                  {'start': 20., 'end': 25., 'speaker_id': 'speaker_overlap'}])
    text = object.__new__(OpenAILLM)._build_segment_text([segment])
    assert '00:00–01:00' in text and '5.00–10.00 秒：speaker_1' in text
    assert '逐句时间与说话人归属不能确证' in text
    assert '不得标为某个 speaker 编号' in text
    assert '[speaker_1]' not in text


def test_meeting_summary_receives_recognition_gaps_without_fabricated_speech(tmp_path):
    from unittest.mock import Mock
    from app.services.note_service import NoteService

    llm = SimpleNamespace(summarize=Mock(return_value='# 纪要'))
    service = object.__new__(NoteService)
    service.artifact_service = SimpleNamespace(update_status=Mock())
    service.llm_service = SimpleNamespace(create_summarizer=Mock(return_value=llm))
    context = SimpleNamespace(task_dir=tmp_path, user_id=None, model_profile_id=None,
                              model_name=None, api_key=None, base_url=None, extras='会议事实',
                              style='meeting', summary_mode='default', output_language='zh-CN',
                              audio_meta=SimpleNamespace(title='会议', duration=90), step_timings={})
    transcript = TranscriptResult('zh', '确认已有决定。', [TranscriptSegment(0, 60, '确认已有决定。')],
                                  {'unrecognized_segments': [{'start': 60, 'end': 90, 'reason': 'upstream_no_speech'}]})
    assert service._summarize_audio(context, transcript) == '# 纪要'
    call = llm.summarize.call_args.kwargs
    assert call['segments'][0].text == '确认已有决定。'
    assert len(call['segments']) == 1
    assert '会议事实' in call['extras'] and '"start": 60' in call['extras']
    assert '不代表确定静音' in call['extras'] and '不得推断缺失发言' in call['extras']


def test_saved_transcript_summary_never_claims_or_calls_asr(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from app.services.note_service import NoteService
    from app.models.transcript import TranscriptResult, TranscriptSegment

    transcript = TranscriptResult('zh', '已确认的发言', [TranscriptSegment(0, 3, '已确认的发言')])
    context = SimpleNamespace(preloaded_transcript=transcript, task_dir=tmp_path, step_timings={})
    service = object.__new__(NoteService)
    service.artifact_service = SimpleNamespace(update_status=Mock(), save_transcript=Mock())
    with patch('app.services.asr_execution_binding.require_task_execution',
               side_effect=AssertionError('ASR must not be claimed')) as claim:
        assert service._transcribe_audio(context) is transcript
    claim.assert_not_called()
    assert context.step_timings['transcribe'] == 0
