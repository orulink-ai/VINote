import numpy as np

from app.services.speaker_clustering_service import cluster_embeddings, supported_voice_groups, refine_speaker_turns
from app.services.speaker_diarization_service import SpeakerTurn
from types import SimpleNamespace
from unittest.mock import patch


def test_automatic_clustering_recovers_four_distinct_voice_groups():
    rng = np.random.default_rng(42)
    samples = np.concatenate([center + rng.normal(0, 0.02, (5, 4)) for center in np.eye(4)])
    labels, score = cluster_embeddings(samples)
    assert len(set(labels)) == 4
    assert score > 0.8
    for start in range(0, 20, 5):
        assert len(set(labels[start:start + 5])) == 1


def test_consistent_voice_does_not_gain_extra_speakers():
    samples = np.tile([1.0, 0.1, 0.0], (8, 1))
    labels, _ = cluster_embeddings(samples)
    assert len(set(labels)) == 1


def test_brief_or_singleton_groups_are_not_confirmed_speakers():
    assert supported_voice_groups([0, 0, 0, 1], [4, 4, 4, 1.6]) == {0: 0}
    assert supported_voice_groups([0, 0, 1, 1], [3, 3, 3, 3]) == {0: 0, 1: 1}
    assert supported_voice_groups([0, 0], [1.5, 1.5]) == {}


def test_refinement_keeps_singleton_and_overlap_unattributed():
    turns = [SpeakerTurn(start, end, 'speaker_legacy') for start, end in
             [(0, 4), (6, 10), (12, 16), (20, 21.6)]]
    turns.append(SpeakerTurn(24, 26, 'speaker_overlap'))
    samples = np.arange(26 * 16000, dtype=np.float32)

    class Stream:
        def accept_waveform(self, rate, data):
            assert rate == 16000 and len(data) <= 8 * 16000
            self.start = float(data[0]) / rate

        def input_finished(self):
            pass

    extractor = SimpleNamespace(create_stream=Stream, is_ready=lambda stream: True,
                                compute=lambda stream: [0, 1] if stream.start == 20 else [1, 0])
    with patch('sherpa_onnx.SpeakerEmbeddingExtractor', return_value=extractor):
        refined, report = refine_speaker_turns(turns, samples, 'unused.onnx')
    assert report['speaker_count'] == 1 and report['rejected_groups'] == 1
    assert refined[-2].speaker_id == 'speaker_unknown'
    assert refined[-1] == turns[-1]
    assert all(turn.speaker_id == 'speaker_1' for turn in refined[:3])
    assert turns[0].speaker_id == 'speaker_legacy'


def test_long_recording_feature_work_is_bounded_without_repeating_windows():
    turns = [SpeakerTurn(i * 2, i * 2 + 1.8, 'speaker_legacy') for i in range(300)]
    samples = np.arange(600 * 16000, dtype=np.float32)
    starts = []

    class Stream:
        def accept_waveform(self, rate, data):
            assert len(data) <= 8 * rate
            starts.append(float(data[0]) / rate)

        def input_finished(self):
            pass

    extractor = SimpleNamespace(create_stream=Stream, is_ready=lambda stream: True,
                                compute=lambda stream: [1, 0])
    with patch('sherpa_onnx.SpeakerEmbeddingExtractor', return_value=extractor):
        refined, report = refine_speaker_turns(turns, samples, 'unused.onnx')
    assert len(starts) == len(set(starts)) == 256
    assert report['representative_turns'] == 128
    assert report['speaker_count'] == 1
    assert any(turn.speaker_id == 'speaker_unknown' for turn in refined)
