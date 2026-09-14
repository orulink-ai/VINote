"""Estimate speaker groups from sustained utterances, not isolated noisy frames."""
from __future__ import annotations

from dataclasses import replace

import numpy as np


def cluster_embeddings(features, *, max_speakers=20):
    """Average-linkage clustering with silhouette selection of the group count.

    The score describes separation in embedding space; it is not a probability
    that real-world identities are correct. Very similar samples form one group.
    """
    features = np.asarray(features, dtype=np.float32)
    count = len(features)
    if count == 0:
        return [], 0.0
    normalized = features / np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-8)
    distance = np.clip(1 - normalized @ normalized.T, 0, 2)
    np.fill_diagonal(distance, 0)
    if count < 3 or float(np.quantile(distance[np.triu_indices(count, 1)], 0.9)) < 0.4:
        return [0] * count, 0.0
    clusters = [[index] for index in range(count)]
    best, best_score = None, -1.0
    while len(clusters) > 1:
        if len(clusters) <= min(max_speakers, count - 1):
            scores = []
            for group in clusters:
                for index in group:
                    within = float(distance[index, group].sum()) / max(1, len(group) - 1)
                    between = min(float(distance[index, other].mean()) for other in clusters if other is not group)
                    scores.append((between - within) / max(within, between, 1e-8) if len(group) > 1 else 0.0)
            score = float(np.mean(scores))
            if score > best_score:
                best, best_score = [list(group) for group in clusters], score
        _, left, right = min(
            (float(distance[np.ix_(a, b)].mean()), i, j)
            for i, a in enumerate(clusters) for j, b in enumerate(clusters) if j > i
        )
        clusters[left].extend(clusters.pop(right))
    labels = [0] * count
    for label, group in enumerate(best or clusters):
        for index in group:
            labels[index] = label
    return labels, best_score


def refine_speaker_turns(turns, samples, embedding_model):
    """Use sustained turns to estimate count, then classify shorter evidence.

    Limit representative vectors to keep long-meeting clustering bounded.
    Uncertain and overlapping speech remains explicitly unattributed.
    """
    import sherpa_onnx

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding_model), num_threads=2)
    )
    candidates = [i for i, turn in enumerate(turns)
                  if turn.speaker_id != 'speaker_overlap' and turn.end - turn.start >= 1.5]
    if len(candidates) > 128:
        candidates = [candidates[index] for index in np.linspace(0, len(candidates) - 1, 128, dtype=int)]
    vectors = {}

    def extract(index):
        turn = turns[index]
        stream = extractor.create_stream()
        start = int(turn.start * 16000)
        end = min(int(turn.end * 16000), start + 8 * 16000)
        stream.accept_waveform(16000, samples[start:end])
        stream.input_finished()
        if not extractor.is_ready(stream):
            return None
        value = np.asarray(extractor.compute(stream), dtype=np.float32)
        return value / max(float(np.linalg.norm(value)), 1e-8)

    for index in candidates:
        value = extract(index)
        if value is not None:
            vectors[index] = value
    if not vectors:
        return [replace(turn, speaker_id=(
            'speaker_overlap' if turn.speaker_id == 'speaker_overlap' else 'speaker_unknown'
        )) for turn in turns], {
            'method': 'sustained-turn-average-linkage', 'reliable': False, 'reason': 'insufficient_speech',
        }
    keys = list(vectors)
    features = np.asarray(list(vectors.values()))
    labels, score = cluster_embeddings(features)
    reliable = len(features) >= 3 and (len(set(labels)) == 1 or score >= 0.2)
    centroids = np.asarray([features[np.asarray(labels) == label].mean(axis=0) for label in sorted(set(labels))])
    centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-8)
    direct = dict(zip(keys, labels))
    refined = []
    for index, turn in enumerate(turns):
        label = 'speaker_unknown'
        if turn.speaker_id == 'speaker_overlap':
            label = 'speaker_overlap'
        elif reliable and index in direct:
            label = f'speaker_{direct[index] + 1}'
        elif reliable and turn.end - turn.start >= 0.6:
            value = extract(index)
            if value is not None:
                scores = centroids @ value
                order = np.argsort(scores)
                margin = scores[order[-1]] - scores[order[-2]] if len(order) > 1 else 1
                if scores[order[-1]] >= 0.45 and margin >= 0.08:
                    label = f'speaker_{int(order[-1]) + 1}'
        updated = replace(turn, speaker_id=label)
        if refined and label == refined[-1].speaker_id and turn.start - refined[-1].end <= 1:
            refined[-1] = replace(refined[-1], end=turn.end)
        else:
            refined.append(updated)
    return refined, {'method': 'sustained-turn-average-linkage', 'reliable': reliable,
                     'silhouette_score': round(score, 4), 'representative_turns': len(features)}
