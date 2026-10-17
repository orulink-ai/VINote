import shutil
import wave

import numpy as np
import pytest

from app.services.audio_preprocessing_service import prepare_meeting_audio


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_denoising_preserves_duration_and_reduces_low_frequency_rumble(tmp_path):
    rate = 16000
    time = np.arange(rate * 2) / rate
    signal = 0.2 * np.sin(2 * np.pi * 40 * time) + 0.1 * np.sin(2 * np.pi * 400 * time)
    original = tmp_path / "original.wav"
    with wave.open(str(original), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((signal * 32767).astype("<i2").tobytes())
    before = original.read_bytes()
    cleaned_path = tmp_path / "clean.f32"
    metadata = prepare_meeting_audio(str(original), cleaned_path)
    cleaned = np.fromfile(cleaned_path, dtype="<f4")
    assert original.read_bytes() == before
    assert abs(len(cleaned) - len(signal)) <= 1
    assert metadata["timeline_preserved"]
    spectrum = abs(np.fft.rfft(cleaned[rate:]))
    assert spectrum[40] / spectrum[400] < 1
    assert spectrum[400] / rate > 0.01
