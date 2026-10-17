"""Independent whole-recording transcription and local speaker diarization.

The configured STT covers the complete preprocessed recording, with chunks
when necessary. Local diarization runs on the same timeline and its
turns are aligned with provider timestamps when available. Whole-file text is
only duration-aligned and is reported as estimated evidence.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import asdict
import math
import re
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models.transcript import NoSpeechDetectedError, TranscriptResult, TranscriptSegment
from app.services.tracing_service import observation, traced, update_current
from app.services.audio_preprocessing_service import prepare_meeting_audio



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
    return f"说话人{speaker_id.split('_')[-1]}"


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
    if transcript.metadata.get("timestamp_granularity") == "chunk":
        # Whole-file-only ASR results still have trustworthy chunk boundaries.
        # Estimate inside each boundary, never redistribute text across the meeting.
        for segment in transcript.segments:
            local_turns = [SpeakerTurn(max(segment.start, turn.start), min(segment.end, turn.end), turn.speaker_id)
                           for turn in turns if min(segment.end, turn.end) > max(segment.start, turn.start)]
            if not local_turns:
                local_turns = [SpeakerTurn(segment.start, segment.end, "speaker_unknown")]
            local, _ = align_transcript_to_speaker_turns(
                TranscriptResult(transcript.language, segment.text, [], {"timestamp_granularity": "file"}), local_turns)
            aligned.extend(local)
        return aligned, "estimated_by_speaking_duration"
    if has_provider_timestamps:
        for segment in transcript.segments:
            if not segment.text.strip():
                continue
            overlaps = [
                (max(0.0, min(segment.end, turn.end) - max(segment.start, turn.start)), turn)
                for turn in turns
            ]
            overlap, selected = max(overlaps, key=lambda item: item[0], default=(0, None))
            speaker_id = selected.speaker_id if overlap > 0 and selected else "speaker_unknown"
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
        speaker_count: int | None = None, update_status=None, evidence_dir: Path | None = None,
    ) -> TranscriptResult:
        self.require_ready()
        import numpy as np

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
                update_status("transcribing", "正在准备音频并区分说话人…", stage="diarizing")
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
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meeting-asr")
            try:
                duration = len(samples) / 16000
                full_audio_path = Path(folder) / "meeting.wav"
                with wave.open(str(full_audio_path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(16000)
                    for offset in range(0, len(samples), 16000 * 30):
                        audio = (np.clip(samples[offset:offset + 16000 * 30], -1, 1) * 32767).astype("<i2")
                        output.writeframes(audio.tobytes())
                    del audio
                def recognize():
                    result = transcribe(
                        str(full_audio_path), audio_duration_seconds=round(duration, 3),
                        transcription_scope="complete_recording",
                        diarization_parallel=True,
                    )
                    if evidence_dir:
                        evidence_dir.mkdir(parents=True, exist_ok=True)
                        self._save_evidence(evidence_dir / "asr_evidence.json", asdict(result))
                    return result
                recognition = pool.submit(copy_context().run, recognize)
                if update_status:
                    update_status("transcribing", "转写与说话人分析正在同时进行…", stage="parallel_analysis")
                signature = self._source_signature(audio_path, segmentation, embedding, speaker_count)
                cached = None
                if evidence_dir:
                    try:
                        cached = json.loads((evidence_dir / "speaker_evidence.json").read_text(encoding="utf-8"))
                        if cached.get("signature") != signature or cached.get("duration") != duration:
                            cached = None
                    except (OSError, ValueError, TypeError):
                        cached = None
                if cached:
                    try:
                        turns = [SpeakerTurn(**turn) for turn in cached["turns"]]
                        if not turns or any(not math.isfinite(t.start) or not math.isfinite(t.end) or t.start < 0 or t.end <= t.start or t.end > duration for t in turns):
                            cached = None
                        clustering = cached["clustering"] if cached else {}
                    except (KeyError, TypeError, ValueError):
                        cached = None
                if not cached:
                    from app.services.speaker_worker import run_speaker_worker

                    def worker_progress(stage, fraction):
                        if update_status:
                            if stage == "refinement":
                                update_status("transcribing", "正在核对完整发言的声音特征并自动判断人数…", stage="diarizing")
                            else:
                                percent = int(fraction * 100) // 5 * 5
                                update_status("transcribing", f"正在检测发言区间：{percent}%", stage="diarizing",
                                              speaker_detection_progress=fraction)

                    with observation(
                        "说话人检测与聚类",
                        input={"provider": "sherpa-onnx", "model": segmentation.name,
                               "audio_duration_seconds": duration, "isolated_process": True},
                        metadata={"model": segmentation.name},
                    ) as detection_span:
                        turns, clustering = run_speaker_worker(
                            pcm_path, segmentation, embedding, speaker_count,
                            settings.diarization_cluster_threshold, progress=worker_progress)
                        if detection_span is not None:
                            detection_span.update(output={"turn_count": len(turns), "clustering": clustering})
                    if signature != self._source_signature(audio_path, segmentation, embedding, speaker_count):
                        raise ValueError("录音或模型在分析期间发生变化，未保存过期分析结果")
                if evidence_dir and not cached:
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    self._save_evidence(evidence_dir / "speaker_evidence.json", {
                        "provider": "sherpa-onnx", "timeline": "recording_offset_seconds",
                        "duration": duration, "clustering": clustering, "signature": signature,
                        "turns": [asdict(turn) for turn in turns],
                    })
                try:
                    if update_status:
                        update_status("transcribing", "说话人分析已完成，正在完成完整录音转写…", stage="transcribing", speaker_analysis_ready=True)
                    transcript = recognition.result()
                except NoSpeechDetectedError:
                    raise ValueError("说话人分析完成，但完整录音转写未返回有效文本；已完成分析保留。") from None
                if update_status:
                    update_status("transcribing", "正在对齐逐字稿…", stage="aligning")
                with observation("逐字稿对齐", as_type="span"):
                    result_segments, alignment = align_transcript_to_speaker_turns(transcript, turns)
                if not result_segments:
                    raise ValueError("完整录音转写成功，但无法与说话人时间区间对齐。")
                result = TranscriptResult(
                    language=transcript.language, full_text=transcript.full_text,
                    segments=result_segments,
                    metadata={"speaker_diarization": True, "analysis_parallel": True,
                              "asr_evidence": asdict(transcript),
                              "speaker_evidence": [asdict(turn) for turn in turns], "diarization_provider": "sherpa-onnx",
                              "speaker_count": len({turn.speaker_id for turn in turns} - {"speaker_overlap", "speaker_unknown"}),
                              "clustering": clustering,
                              "timestamp_granularity": transcript.metadata.get("timestamp_granularity", "file"),
                              "speaker_alignment": alignment,
                              "speaker_alignment_estimated": alignment == "estimated_by_speaking_duration",
                              "stt_request_count": transcript.metadata.get("stt_request_count", 1),
                              "speaker_turn_count": len(turns), "overlap_detected": any(
                                  turn.speaker_id == "speaker_overlap" for turn in turns),
                              "cluster_threshold": settings.diarization_cluster_threshold,
                              "audio_preprocessing": preprocessing,
                              "unrecognized_segments": transcript.metadata.get("unrecognized_segments", [])},
                )
                update_current(output={
                    "speaker_count": result.metadata["speaker_count"],
                    "clustering": clustering,
                    "stt_request_count": result.metadata["stt_request_count"],
                    "speaker_alignment": alignment,
                    "overlap_detected": result.metadata["overlap_detected"],
                    "unrecognized_segments": result.metadata["unrecognized_segments"],
                    "turns": [{"start": turn.start, "end": turn.end,
                               "speaker": turn.speaker_id} for turn in turns],
                    "transcript": result.full_text,
                })
                return result
            finally:
                # Release the memory map before TemporaryDirectory removes it on Windows.
                pool.shutdown(wait=True)
                samples._mmap.close()

    @staticmethod
    def _source_signature(audio_path, segmentation, embedding, speaker_count):
        digest = hashlib.sha256()
        with open(audio_path, "rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        return {"version": 1, "source_sha256": digest.hexdigest(),
                "models": [[p.stat().st_size, p.stat().st_mtime_ns] for p in (segmentation, embedding)],
                "threshold": settings.diarization_cluster_threshold, "speaker_count": speaker_count,
                "clustering_revision": 2}

    @staticmethod
    def _save_evidence(path: Path, value: dict) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
