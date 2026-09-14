from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.speaker_diarization_service import build_speaker_turns, SpeakerTurn
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
