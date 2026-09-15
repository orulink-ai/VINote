"""Local speaker clustering followed by STT on timestamped speaking turns.

Clustering is performed over the entire recording, so speaker IDs stay stable
across STT requests. This works even with providers that return only plain text.
"""
from __future__ import annotations

import importlib.util
import math
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models.transcript import NoSpeechDetectedError, TranscriptResult, TranscriptSegment
from app.services.tracing_service import traced
from app.services.audio_preprocessing_service import prepare_meeting_audio

_INFERENCE_LOCK = threading.Lock()


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker_id: str


def build_speaker_turns(segments, duration: float) -> list[SpeakerTurn]:
    """Partition overlaps once; never attribute mixed speech to a single person."""
    events: dict[float, list[tuple[int, int]]] = {}
    for segment in segments:
        start, end = max(0.0, float(segment.start)), min(duration, float(segment.end))
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        events.setdefault(start, []).append((int(segment.speaker), 1))
        events.setdefault(end, []).append((int(segment.speaker), -1))
    active: dict[int, int] = {}
    labels: dict[int, str] = {}
    turns: list[SpeakerTurn] = []
    previous = 0.0
    for timestamp in sorted(events):
        speakers = [speaker for speaker, count in active.items() if count > 0]
        if speakers and timestamp > previous:
            for speaker in speakers:
                labels.setdefault(speaker, f"speaker_{len(labels) + 1}")
            label = labels[speakers[0]] if len(speakers) == 1 else "speaker_overlap"
            # Keep natural short pauses within one STT request for sentence context.
            # Consecutive turns ensure an intervening different speaker is never merged.
            if turns and turns[-1].speaker_id == label and previous - turns[-1].end <= 1.0:
                turns[-1] = SpeakerTurn(turns[-1].start, timestamp, label)
            else:
                turns.append(SpeakerTurn(previous, timestamp, label))
        for speaker, delta in events[timestamp]:
            active[speaker] = active.get(speaker, 0) + delta
        previous = timestamp
    return turns


class SpeakerDiarizationService:
    @staticmethod
    def model_paths() -> tuple[Path, Path]:
        root = settings.diarization_model_dir
        return root / "segmentation.onnx", root / "embedding.onnx"

    @classmethod
    def readiness(cls) -> dict:
        installed = importlib.util.find_spec("sherpa_onnx") is not None
        models_ready = all(path.is_file() for path in cls.model_paths())
        return {"available": installed and models_ready, "runtime_installed": installed,
                "models_ready": models_ready, "provider": "sherpa-onnx"}

    @classmethod
    def require_ready(cls) -> None:
        if not cls.readiness()["available"]:
            raise ValueError("说话人分离尚未就绪，请运行 python scripts/setup_diarization.py 安装模型和依赖。")

    @traced("区分会议说话人", as_type="chain")
    def transcribe(
        self, *, audio_path: str, transcribe: Callable[[str], TranscriptResult],
        speaker_count: int | None = None, update_status=None,
    ) -> TranscriptResult:
        self.require_ready()
        import numpy as np
        import sherpa_onnx

        if speaker_count is not None and not 1 <= speaker_count <= 20:
            raise ValueError("Speaker count must be between 1 and 20")
        if not 0 < settings.diarization_cluster_threshold <= 2:
            raise ValueError("DIARIZATION_CLUSTER_THRESHOLD must be in (0, 2]")
        segmentation, embedding = self.model_paths()
        with tempfile.TemporaryDirectory(prefix="diarization-", dir=settings.data_dir) as folder:
            pcm_path = Path(folder) / "audio.f32"
            if update_status:
                update_status("transcribing", "正在准备音频并区分说话人…")
            preprocessing = prepare_meeting_audio(audio_path, pcm_path)
            if pcm_path.stat().st_size < 4:
                raise ValueError("录制中没有可分析的音频。")
            # Keep large decoded recordings backed by disk, including on Windows.
            samples = np.memmap(pcm_path, dtype="float32", mode="r")
            try:
                config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                    segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                            model=str(segmentation)), num_threads=2,
                    ),
                    embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=2),
                    clustering=sherpa_onnx.FastClusteringConfig(
                        num_clusters=speaker_count or -1, threshold=settings.diarization_cluster_threshold),
                    min_duration_on=0.3, min_duration_off=0.5,
                )
                if not config.validate():
                    raise ValueError("说话人模型配置无效，请重新运行安装脚本。")
                with _INFERENCE_LOCK:
                    engine = sherpa_onnx.OfflineSpeakerDiarization(config)
                    last_progress = -1

                    def report_progress(done, total):
                        nonlocal last_progress
                        progress = int(done * 100 / max(total, 1)) // 5 * 5
                        if update_status and progress != last_progress:
                            update_status("transcribing", f"正在区分说话人：{progress}%")
                            last_progress = progress
                        return 0

                    detected = engine.process(samples, callback=report_progress).sort_by_start_time()
                duration = len(samples) / 16000
                turns = build_speaker_turns(detected, duration)
                if not turns:
                    raise ValueError("未检测到有效发言，请检查录音声音。")
                clustering = {'method': 'fixed-speaker-count', 'requested_count': speaker_count}
                if speaker_count is None:
                    from app.services.speaker_clustering_service import refine_speaker_turns
                    if update_status:
                        update_status("transcribing", "正在核对完整发言的声音特征并自动判断人数…")
                    with _INFERENCE_LOCK:
                        turns, clustering = refine_speaker_turns(turns, samples, embedding)
                result_segments: list[TranscriptSegment] = []
                unrecognized_segments: list[dict] = []
                language = None
                for index, turn in enumerate(turns):
                    if update_status:
                        update_status("transcribing", f"正在转写发言 {index + 1}/{len(turns)}（{turn.speaker_id}）…")
                    # Bound individual STT requests while preserving global speaker identity.
                    offset = turn.start
                    while offset < turn.end:
                        end = min(offset + 60, turn.end)
                        chunk_path = Path(folder) / "turn.wav"
                        audio = (np.clip(samples[int(offset * 16000):int(end * 16000)], -1, 1) * 32767).astype("<i2")
                        with wave.open(str(chunk_path), "wb") as output:
                            output.setnchannels(1)
                            output.setsampwidth(2)
                            output.setframerate(16000)
                            output.writeframes(audio.tobytes())
                        try:
                            result = transcribe(str(chunk_path))
                        except NoSpeechDetectedError:
                            unrecognized_segments.append({"start": offset, "end": end,
                                                          "reason": "provider_returned_no_text"})
                            offset = end
                            continue
                        language = language or result.language
                        segments = result.segments or [TranscriptSegment(0, end - offset, result.full_text)]
                        for segment in segments:
                            if not segment.text.strip():
                                continue
                            start_time = max(offset, min(end, offset + segment.start))
                            end_time = max(start_time, min(end, offset + segment.end))
                            if end_time <= start_time:
                                start_time, end_time = offset, end
                            label = (
                                "重叠发言（归属待确认）" if turn.speaker_id == "speaker_overlap"
                                else "说话人待确认" if turn.speaker_id == "speaker_unknown"
                                else f"说话人 {turn.speaker_id.split('_')[-1]}"
                            )
                            result_segments.append(TranscriptSegment(
                                start=start_time, end=end_time, text=segment.text,
                                raw_text=segment.raw_text or segment.text, cleaned_text=segment.cleaned_text,
                                speaker_id=turn.speaker_id, speaker_label=label,
                            ))
                        offset = end
                if not result_segments:
                    raise ValueError("说话人分离完成，但转写未返回有效文本。")
                return TranscriptResult(
                    language=language, full_text=" ".join(segment.text for segment in result_segments),
                    segments=result_segments,
                    metadata={"speaker_diarization": True, "diarization_provider": "sherpa-onnx",
                              "speaker_count": len({turn.speaker_id for turn in turns} - {"speaker_overlap", "speaker_unknown"}),
                              "clustering": clustering,
                              "timestamp_granularity": "speaker_turn", "overlap_detected": any(
                                  turn.speaker_id == "speaker_overlap" for turn in turns),
                              "cluster_threshold": settings.diarization_cluster_threshold,
                              "audio_preprocessing": preprocessing,
                              "unrecognized_segments": unrecognized_segments},
                )
            finally:
                # Release the memory map before TemporaryDirectory removes it on Windows.
                samples._mmap.close()
