from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.speaker_diarization_service import (
    SpeakerTurn,
    align_transcript_to_speaker_turns,
    build_speaker_turns,
)
from app.services.transcription_service import TranscriptionService


def test_global_labels_follow_first_appearance_and_merge_short_silences():
    turns = build_speaker_turns([
        SimpleNamespace(start=0, end=2, speaker=7),
        SimpleNamespace(start=2.8, end=4, speaker=7),
        SimpleNamespace(start=4, end=6, speaker=3),
        SimpleNamespace(start=7, end=8, speaker=7),
    ], 8)
    assert turns == [SpeakerTurn(0, 4, 'speaker_1'), SpeakerTurn(4, 6, 'speaker_2'), SpeakerTurn(7, 8, 'speaker_1')]


def test_overlapping_speech_is_transcribed_once_without_false_attribution():
    turns = build_speaker_turns([
        SimpleNamespace(start=0, end=4, speaker=0),
        SimpleNamespace(start=2, end=6, speaker=1),
    ], 6)
    assert turns == [SpeakerTurn(0, 2, 'speaker_1'), SpeakerTurn(2, 4, 'speaker_overlap'), SpeakerTurn(4, 6, 'speaker_2')]


def test_diarization_request_does_not_reuse_plain_text_cache():
    cached = TranscriptResult('zh', 'whole file', [TranscriptSegment(0, 10, 'whole file')])
    diarized = TranscriptResult('zh', 'two turns', [TranscriptSegment(0, 2, 'one', speaker_id='speaker_1')], {'speaker_diarization': True})
    saved = []
    service = TranscriptionService(transcriber=SimpleNamespace())
    with patch('app.services.speaker_diarization_service.SpeakerDiarizationService.transcribe', return_value=diarized) as process:
        result = service.transcribe(audio_path='meeting.wav', load_cached=lambda: cached,
                                    save_transcript=saved.append, diarize=True, speaker_count=2)
    assert result is diarized
    assert saved == [diarized]
    assert process.call_args.kwargs['speaker_count'] == 2


def test_diarization_errors_are_not_silently_returned_as_success():
    service = TranscriptionService(transcriber=SimpleNamespace())
    with patch('app.services.speaker_diarization_service.SpeakerDiarizationService.transcribe', side_effect=ValueError('models missing')):
        with pytest.raises(ValueError, match='models missing'):
            service.transcribe(audio_path='meeting.wav', load_cached=lambda: None,
                               save_transcript=lambda _: pytest.fail('Should not save'), diarize=True)


def test_summary_receives_speaker_evidence():
    from app.llm.openai_llm import OpenAILLM
    summarizer = object.__new__(OpenAILLM)
    text = summarizer._build_segment_text([TranscriptSegment(1, 3, 'Review tomorrow', speaker_id='speaker_2', speaker_label='说话人 2')])
    assert '[说话人 2]' in text
    assert '00:01–00:03' in text
    assert 'Review tomorrow' in text


def test_timestamped_transcript_uses_interval_overlap_for_speakers():
    transcript = TranscriptResult(
        'zh',
        '第一句。第二句。',
        [TranscriptSegment(0.5, 2.5, '第一句。'), TranscriptSegment(3.2, 4.2, '第二句。')],
        {'timestamp_granularity': 'segment'},
    )
    segments, alignment = align_transcript_to_speaker_turns(transcript, [
        SpeakerTurn(0, 3, 'speaker_1'),
        SpeakerTurn(3, 5, 'speaker_2'),
    ])
    assert alignment == 'provider_timestamp_overlap'
    assert [segment.speaker_id for segment in segments] == ['speaker_1', 'speaker_2']
    assert [segment.start for segment in segments] == [0.5, 3.2]


def test_whole_file_transcript_is_aligned_without_additional_stt_calls():
    transcript = TranscriptResult(
        'zh',
        '短句。这里是明显更长的第二句话。',
        [TranscriptSegment(0, 10, '短句。这里是明显更长的第二句话。')],
        {'timestamp_granularity': 'file'},
    )
    segments, alignment = align_transcript_to_speaker_turns(transcript, [
        SpeakerTurn(0, 2, 'speaker_1'),
        SpeakerTurn(2, 10, 'speaker_2'),
    ])
    assert alignment == 'estimated_by_speaking_duration'
    assert [segment.text for segment in segments] == ['短句。', '这里是明显更长的第二句话。']
    assert [segment.speaker_id for segment in segments] == ['speaker_1', 'speaker_2']


def test_chunk_text_cannot_drift_into_another_speakers_time_window():
    transcript = TranscriptResult('zh', '长的第一段发言。短。', [
        TranscriptSegment(0, 300, '长的第一段发言。'),
        TranscriptSegment(300, 600, '短。'),
    ], {'timestamp_granularity': 'chunk'})
    segments, alignment = align_transcript_to_speaker_turns(transcript, [
        SpeakerTurn(0, 10, 'speaker_1'), SpeakerTurn(300, 590, 'speaker_2')])
    assert alignment == 'estimated_by_speaking_duration'
    assert [segment.speaker_id for segment in segments] == ['speaker_1', 'speaker_2']
    assert segments[0].end <= 300
    assert segments[1].start >= 300


def test_missing_speaker_turns_keep_timestamped_speech_unknown():
    transcript = TranscriptResult('zh', '保留发言', [TranscriptSegment(1, 2, '保留发言')],
                                  {'timestamp_granularity': 'segment'})
    segments, _ = align_transcript_to_speaker_turns(transcript, [])
    assert segments[0].speaker_id == 'speaker_unknown'
