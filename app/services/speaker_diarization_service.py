"""Independent whole-recording transcription and local speaker diarization.

The configured STT receives the complete preprocessed recording once so it can
retain meeting context. Local diarization runs on the same timeline and its
turns are aligned with provider timestamps when available. Whole-file text is
only duration-aligned and is reported as estimated evidence.
"""
from __future__ import annotations

import importlib.util
import math
import re
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models.transcript import NoSpeechDetectedError, TranscriptResult, TranscriptSegment
from app.services.tracing_service import observation, traced, update_current
from app.services.audio_preprocessing_service import prepare_meeting_audio

_INFERENCE_LOCK = threading.Lock()


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker_id: str


def _speaker_label(speaker_id: str) -> str:
    if speaker_id == "speaker_overlap":
        return "重叠发言（归属待确认）"
    if speaker_id == "speaker_unknown":
        return "说话人待确认"
    return f"说话人 {speaker_id.split('_')[-1]}"


def _split_transcript_sentences(text: str) -> list[str]:
    """Keep the provider's wording while finding stable Chinese/English boundaries."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    sentences = [item.strip() for item in re.findall(r".+?(?:[。！？!?；;]+|$)", normalized)]
    return [item for item in sentences if item]


def align_transcript_to_speaker_turns(
    transcript: TranscriptResult,
    turns: list[SpeakerTurn],
) -> tuple[list[TranscriptSegment], str]:
    """Merge independent STT and diarization evidence on the recording timeline.

    Timestamped provider segments use interval overlap. A provider that only
    returns whole-file text has no exact word timing, so sentences are aligned
    in order by cumulative detected speaking duration and explicitly marked as
    estimated in metadata by the caller.
    """
    has_provider_timestamps = (
        transcript.metadata.get("timestamp_granularity") == "segment"
        and bool(transcript.segments)
    )
    aligned: list[TranscriptSegment] = []
    if has_provider_timestamps:
        for segment in transcript.segments:
            if not segment.text.strip():
                continue
            overlaps = [
                (max(0.0, min(segment.end, turn.end) - max(segment.start, turn.start)), turn)
                for turn in turns
            ]
            overlap, selected = max(overlaps, key=lambda item: item[0])
            speaker_id = selected.speaker_id if overlap > 0 else "speaker_unknown"
            aligned.append(TranscriptSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                raw_text=segment.raw_text or segment.text,
                cleaned_text=segment.cleaned_text,
                speaker_id=speaker_id,
                speaker_label=_speaker_label(speaker_id),
            ))
        return aligned, "provider_timestamp_overlap"

    sentences = _split_transcript_sentences(transcript.full_text)
    total_speech = sum(max(0.0, turn.end - turn.start) for turn in turns)
    total_weight = sum(max(1, len(re.sub(r"\s+", "", sentence))) for sentence in sentences)
    if not sentences or total_speech <= 0 or total_weight <= 0:
        return [], "unavailable"

    turn_cursor = 0
    speech_before_turn = 0.0
    text_weight_before = 0
    for sentence in sentences:
        sentence_weight = max(1, len(re.sub(r"\s+", "", sentence)))
        midpoint = total_speech * ((text_weight_before + sentence_weight / 2) / total_weight)
        while turn_cursor < len(turns) - 1:
            turn_duration = max(0.0, turns[turn_cursor].end - turns[turn_cursor].start)
            if midpoint <= speech_before_turn + turn_duration:
                break
            speech_before_turn += turn_duration
            turn_cursor += 1
        selected = turns[turn_cursor]
        aligned.append(TranscriptSegment(
            start=selected.start,
            end=selected.end,
            text=sentence,
            raw_text=sentence,
            speaker_id=selected.speaker_id,
            speaker_label=_speaker_label(selected.speaker_id),
        ))
        text_weight_before += sentence_weight
    return aligned, "estimated_by_speaking_duration"


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

    @traced("说话人识别与逐字稿对齐", as_type="chain")
    def transcribe(
        self, *, audio_path: str, transcribe: Callable[..., TranscriptResult],
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
        update_current(input={
            "audio": {"format": Path(audio_path).suffix.lower().lstrip("."),
                      "size_bytes": Path(audio_path).stat().st_size},
            "provider": "sherpa-onnx",
            "segmentation_model": segmentation.name,
            "embedding_model": embedding.name,
            "requested_speaker_count": speaker_count or "auto",
            "cluster_threshold": settings.diarization_cluster_threshold,
        })
        with tempfile.TemporaryDirectory(prefix="diarization-", dir=settings.data_dir) as folder:
            pcm_path = Path(folder) / "audio.f32"
            if update_status:
                update_status("transcribing", "正在准备音频并区分说话人…")
            with observation(
                "音频预处理",
                input={"source_format": Path(audio_path).suffix.lower().lstrip("."),
                       "target_sample_rate": 16000, "target_channels": 1,
                       "timeline_trimmed": False},
            ) as preprocess_span:
                preprocessing = prepare_meeting_audio(audio_path, pcm_path)
                if preprocess_span is not None:
                    preprocess_span.update(output=preprocessing)
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
                with observation(
                    "说话人检测",
                    input={"provider": "sherpa-onnx", "model": segmentation.name,
                           "audio_duration_seconds": len(samples) / 16000},
                    metadata={"model": segmentation.name},
                ) as detection_span:
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
                    if detection_span is not None:
                        detection_span.update(output={"detected_segments": len(detected)})
                duration = len(samples) / 16000
                turns = build_speaker_turns(detected, duration)
                if not turns:
                    raise ValueError("未检测到有效发言，请检查录音声音。")
                clustering = {'method': 'fixed-speaker-count', 'requested_count': speaker_count}
                if speaker_count is None:
                    from app.services.speaker_clustering_service import refine_speaker_turns
                    if update_status:
                        update_status("transcribing", "正在核对完整发言的声音特征并自动判断人数…")
                    with observation(
                        "说话人聚类",
                        input={"model": embedding.name, "turn_count": len(turns),
                               "cluster_threshold": settings.diarization_cluster_threshold,
                               "speaker_count": "auto"},
                        metadata={"model": embedding.name},
                    ) as clustering_span:
                        with _INFERENCE_LOCK:
                            turns, clustering = refine_speaker_turns(turns, samples, embedding)
                        if clustering_span is not None:
                            clustering_span.update(output={"turn_count": len(turns),
                                                           "clustering": clustering})
                if update_status:
                    update_status("transcribing", "正在转写完整录音（保留会议上下文）…")
                full_audio_path = Path(folder) / "meeting.wav"
                audio = (np.clip(samples, -1, 1) * 32767).astype("<i2")
                with wave.open(str(full_audio_path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(16000)
                    output.writeframes(audio.tobytes())
                try:
                    transcript = transcribe(
                        str(full_audio_path),
                        audio_duration_seconds=round(duration, 3),
                        diarization_turn_count=len(turns),
                        transcription_scope="complete_recording",
                    )
                except NoSpeechDetectedError:
                    raise ValueError("说话人分离完成，但完整录音转写未返回有效文本。") from None
                result_segments, alignment = align_transcript_to_speaker_turns(transcript, turns)
                if not result_segments:
                    raise ValueError("完整录音转写成功，但无法与说话人时间区间对齐。")
                result = TranscriptResult(
                    language=transcript.language, full_text=transcript.full_text,
                    segments=result_segments,
                    metadata={"speaker_diarization": True, "diarization_provider": "sherpa-onnx",
                              "speaker_count": len({turn.speaker_id for turn in turns} - {"speaker_overlap", "speaker_unknown"}),
                              "clustering": clustering,
                              "timestamp_granularity": transcript.metadata.get("timestamp_granularity", "file"),
                              "speaker_alignment": alignment,
                              "speaker_alignment_estimated": alignment == "estimated_by_speaking_duration",
                              "stt_request_count": 1,
                              "speaker_turn_count": len(turns), "overlap_detected": any(
                                  turn.speaker_id == "speaker_overlap" for turn in turns),
                              "cluster_threshold": settings.diarization_cluster_threshold,
                              "audio_preprocessing": preprocessing,
                              "unrecognized_segments": []},
                )
                update_current(output={
                    "speaker_count": result.metadata["speaker_count"],
                    "clustering": clustering,
                    "stt_request_count": 1,
                    "speaker_alignment": alignment,
                    "overlap_detected": result.metadata["overlap_detected"],
                    "unrecognized_segments": [],
                    "turns": [{"start": turn.start, "end": turn.end,
                               "speaker": turn.speaker_id} for turn in turns],
                    "transcript": result.full_text,
                })
                return result
            finally:
                # Release the memory map before TemporaryDirectory removes it on Windows.
                samples._mmap.close()
