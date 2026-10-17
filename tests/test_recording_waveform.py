import math
import shutil
import struct
import wave

import pytest
from fastapi import HTTPException

from app.services import recording_waveform_service as service
from app.services.meeting_media_service import MeetingMediaService


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
@pytest.mark.parametrize('sample_rate', [8000, 48000])
def test_real_preview_is_bounded_and_reuses_cache(tmp_path, monkeypatch, sample_rate):
    source = tmp_path / 'recording.wav'
    samples = [int((12000 if i < sample_rate * .6 else 3000) * math.sin(i * math.tau * 440 / sample_rate)) for i in range(int(sample_rate * 1.2))]
    with wave.open(str(source), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(struct.pack(f'<{len(samples)}h', *samples))
    result = service.recording_waveform(source, tmp_path)
    assert result['duration'] == pytest.approx(1.2)
    assert 0 < len(result['peaks']) <= service.POINTS
    assert all(0 <= peak <= 1 for peak in result['peaks'])
    assert result['peaks'][10] > result['peaks'][-10] * 3
    monkeypatch.setattr(service.subprocess, 'run', lambda *a, **kw: pytest.fail('cached preview decoded again'))
    assert service.recording_waveform(source, tmp_path) == result


def test_preview_worker_does_not_queue_decoders(tmp_path):
    source = tmp_path / 'recording.wav'
    source.write_bytes(b'original')
    service._worker.acquire()
    try:
        with pytest.raises(HTTPException) as failure:
            service.recording_waveform(source, tmp_path)
        assert failure.value.status_code == 503
        assert source.read_bytes() == b'original'
    finally:
        service._worker.release()


def test_deleted_original_cannot_fall_back_to_waveform(tmp_path, monkeypatch):
    (tmp_path / 'recording_deleted').write_text('deleted')
    media = MeetingMediaService()
    monkeypatch.setattr(media, '_context', lambda *args: (tmp_path, False))
    with pytest.raises(HTTPException) as failure:
        media.waveform('owner', 'note')
    assert failure.value.status_code == 404
