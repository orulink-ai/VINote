from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.transcription_service import TranscriptionService


def test_container_duration_does_not_scan_packets():
    with patch('app.services.transcription_service.subprocess.run', return_value=SimpleNamespace(stdout='27.5')) as run:
        assert TranscriptionService.get_audio_duration('recording.webm') == 27.5
        assert run.call_count == 1


@pytest.mark.parametrize('header', ['N/A', '', '0', 'nan', 'inf'])
def test_missing_webm_duration_uses_packet_end_times(header):
    with patch('app.services.transcription_service.subprocess.run', side_effect=[
        SimpleNamespace(stdout=header),
        SimpleNamespace(stdout='-0.007,0.020\nN/A,N/A\n27.456,0.033\n26.1,N/A\n'),
    ]):
        assert TranscriptionService.get_audio_duration('recording.webm') == pytest.approx(27.489)


def test_invalid_media_stays_unknown_instead_of_inventing_duration():
    with patch('app.services.transcription_service.subprocess.run', side_effect=RuntimeError('invalid media')):
        assert TranscriptionService.get_audio_duration('broken.webm') == 0
