from app.services import audio_normalizer


def test_unreadable_wav_recovery_never_overwrites_original(tmp_path, monkeypatch):
    original = tmp_path / "recording.wav"
    original.write_bytes(b"original")
    monkeypatch.setattr(audio_normalizer, "_ffprobe_readable", lambda _: False)

    def recover(source, target):
        assert source != target
        target.write_bytes(b"recovered")
        return True

    monkeypatch.setattr(audio_normalizer, "_reencode_to_wav", recover)
    result = audio_normalizer.normalize_audio_for_transcription(original)
    assert original.read_bytes() == b"original"
    assert result.read_bytes() == b"recovered"
