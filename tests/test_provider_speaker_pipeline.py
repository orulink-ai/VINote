from unittest.mock import patch
import pytest
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.transcription_service import TranscriptionService

@pytest.mark.parametrize('speaker', ['speaker_1', None])
def test_meeting_uses_only_provider_speakers(speaker):
    transcript = TranscriptResult('zh', 'hello', [TranscriptSegment(0, 2, 'hello', speaker_id=speaker)], {'model_speaker_diarization': speaker is not None})
    service = TranscriptionService(transcriber=object())
    saved = []
    with patch.object(service, 'get_audio_duration', return_value=2), patch.object(service, '_transcribe_in_chunks', return_value=transcript), patch('app.services.speaker_diarization_service.SpeakerDiarizationService.transcribe', side_effect=AssertionError('legacy speaker analysis called')):
        result = service.transcribe(audio_path='meeting.wav', load_cached=lambda: None, save_transcript=saved.append, diarize=True)
    assert result is transcript
    assert result.segments[0].speaker_id == speaker
    assert saved == [transcript]
