import numpy as np

from app.services.speaker_clustering_service import cluster_embeddings


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
