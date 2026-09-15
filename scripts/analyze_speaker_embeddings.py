"""Inspect automatic clustering on denoised, sustained speaking turns (no STT)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import numpy as np
    import sherpa_onnx
    from app.services.audio_preprocessing_service import prepare_meeting_audio
    from app.services.speaker_diarization_service import SpeakerDiarizationService

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("turns", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pcm = args.output.with_suffix('.f32')
    prepare_meeting_audio(str(args.audio), pcm)
    samples = np.fromfile(pcm, dtype=np.float32)
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(SpeakerDiarizationService.model_paths()[1]), num_threads=2,
        )
    )
    segments = json.loads(args.turns.read_text(encoding='utf-8'))['segments']
    kept, features = [], []
    for i, segment in enumerate(segments):
        if segment['speaker_id'] == 'speaker_overlap' or segment['end'] - segment['start'] < 1.5:
            continue
        stream = extractor.create_stream()
        start = int(segment['start'] * 16000)
        end = min(int(segment['end'] * 16000), start + 8 * 16000)
        stream.accept_waveform(16000, samples[start:end])
        stream.input_finished()
        if extractor.is_ready(stream):
            features.append(extractor.compute(stream))
            kept.append(i)
    np.savez(args.output, features=np.asarray(features), indices=np.asarray(kept))
    print(json.dumps({'vectors': len(features), 'file': str(args.output)}), flush=True)


if __name__ == '__main__':
    main()
