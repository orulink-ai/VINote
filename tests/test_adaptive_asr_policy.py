from array import array
import wave

import pytest

from app.services.adaptive_asr_policy import RecordedAudioPolicy, plan_intervals


def write_wav(path, seconds=10, pauses=()):
    samples = array("h", (0 if any(a <= i / 16000 < b for a, b in pauses)
                         else 1600 for i in range(int(seconds * 16000))))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(samples.tobytes())
    return path


@pytest.mark.parametrize("budget", [None, True, 0, -2, 641, 64 * 1024 * 1024 + 2, "2097152"])
def test_invalid_budget_rejects_before_audio_dispatch(budget):
    with pytest.raises(ValueError):
        RecordedAudioPolicy.from_capabilities({"recordedAudio": {
            "protocol": 1, "supported": True, "strategy": "adaptive_pause", "policySource": "service_budget",
            "maxSessionAudioBytes": budget}})


def test_model_catalog_policy_uses_service_budget_without_model_name():
    policy = RecordedAudioPolicy.from_capabilities({"recordedAudio": {
        "protocol": 1, "supported": True, "strategy": "adaptive_pause",
        "policySource": "service_budget", "maxSessionAudioBytes": 2097152}})
    assert policy.max_session_audio_bytes == 2097152


def test_pause_boundaries_preserve_every_sample_and_budget(tmp_path):
    path = write_wav(tmp_path / "pause.wav", pauses=[(2.8, 3.4), (6, 6.6)])
    intervals = plan_intervals(path, RecordedAudioPolicy(128000))
    assert 2.8 < intervals[0][1] / 16000 < 3.4
    assert 6 < intervals[1][1] / 16000 < 6.6
    assert intervals[0][0] == 0 and intervals[-1][1] == 160000
    assert all(a[1] == b[0] for a, b in zip(intervals, intervals[1:]))
    assert all(0 < end - start <= 64000 for start, end in intervals)
    assert sum(end - start for start, end in intervals) == 160000


def test_continuous_speech_uses_quiet_boundary_without_gap_or_fixed_duration(tmp_path):
    path = write_wav(tmp_path / "tone.wav")
    small = plan_intervals(path, RecordedAudioPolicy(98304))
    large = plan_intervals(path, RecordedAudioPolicy(196608))
    assert len(small) > len(large)
    assert small[0][1] != large[0][1]
    assert sum(end - start for start, end in small) == 160000


def test_resume_and_last_odd_sample_are_exact(tmp_path):
    path = write_wav(tmp_path / "odd.wav", seconds=1 + 1 / 16000)
    intervals = plan_intervals(path, RecordedAudioPolicy(16000), start_frame=123)
    assert intervals[0][0] == 123
    assert intervals[-1][1] == 16001
    assert sum(b - a for a, b in intervals) == 16001 - 123
