"""
Audio transcription helpers.
"""
import importlib.util
import math
import logging
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import settings
from app.services.tracing_service import observation, content_summary, update_current, traced
from app.models.stt_profile import LOCAL_STT_PROVIDERS, ResolvedSTTConfig
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.stt_profile_service import STTProfileService
from app.transcribers.base import Transcriber

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, str], None]


@dataclass
class ChunkSpec:
    index: int
    total: int
    file_path: Path
    chunk_start: float
    chunk_end: float
    trim_start: float
    trim_end: float


def create_transcriber(config: ResolvedSTTConfig | None = None) -> Transcriber:
    resolved = config or STTProfileService().resolve_config(user_id=None, stt_profile_id=None)
    t_type = resolved.provider.lower()

    if t_type == "vliab-server":
        from app.transcribers.vilab_transcriber import VILabTranscriber

        return VILabTranscriber(resolved.base_url or "", resolved.api_key or "", resolved.model_name, resolved.language, resolved.cloud_user_id)

    if t_type == "groq":
        from app.transcribers.groq_transcriber import GroqWhisperTranscriber

        if not resolved.api_key:
            raise ValueError("GROQ_API_KEY is not configured")
        return GroqWhisperTranscriber(
            api_key=resolved.api_key,
            model=resolved.model_name or "whisper-large-v3-turbo",
            language=resolved.language,
        )

    if t_type == "whisper":
        if importlib.util.find_spec("whisper") is None:
            raise RuntimeError(
                "Whisper STT provider requires `pip install openai-whisper` in the backend environment. "
                "Install it or choose a Groq/faster-whisper STT profile."
            )
        from app.transcribers.whisper_transcriber import WhisperTranscriber

        return WhisperTranscriber(
            model_size=resolved.model_name or settings.whisper_model_size,
            device=resolved.device or settings.whisper_device,
        )

    if t_type == "faster-whisper":
        try:
            from app.transcribers.faster_whisper_transcriber import FasterWhisperTranscriber
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper STT provider requires `pip install -r requirements.local-transcribers.txt` "
                "in the backend environment."
            ) from exc

        return FasterWhisperTranscriber(
            model_size=resolved.model_name or settings.whisper_model_size,
            device=resolved.device or settings.whisper_device,
            compute_type=resolved.compute_type or settings.faster_whisper_compute_type,
            language=resolved.language,
        )

    if t_type == "sensevoice":
        from app.transcribers.sensevoice_transcriber import SenseVoiceTranscriber

        return SenseVoiceTranscriber(
            base_url=resolved.base_url or settings.sensevoice_base_url,
            language=resolved.language or settings.sensevoice_language,
        )

    if t_type == "sensevoice-local":
        from app.transcribers.sensevoice_local_transcriber import SenseVoiceLocalTranscriber

        return SenseVoiceLocalTranscriber(
            model_size=resolved.model_name or settings.sensevoice_model_size,
            device=resolved.device or ("cuda" if settings.sensevoice_use_gpu else "cpu"),
            language=resolved.language or settings.sensevoice_language,
            use_gpu=resolved.use_gpu if resolved.use_gpu is not None else settings.sensevoice_use_gpu,
        )

    raise ValueError(f"Unsupported transcriber type: {t_type}")


class TranscriptionService:
    @staticmethod
    def _transcribe_chunk(transcriber, file_path, chunk=None):
        metadata = {"adapter": type(transcriber).__name__, "streamed": False}
        model = getattr(transcriber, "model", None)
        if isinstance(model, str):
            metadata["model"] = model
        if chunk is not None:
            metadata.update(chunk_index=chunk.index, chunk_total=chunk.total,
                            start_seconds=chunk.chunk_start, end_seconds=chunk.chunk_end)
        with observation("调用语音识别", metadata=metadata):
            result = transcriber.transcribe(file_path=file_path)
            update_current(output=content_summary(result.full_text))
            return result

    def __init__(
        self,
        transcriber: Transcriber | None = None,
        stt_profile_service: STTProfileService | None = None,
    ):
        self.transcriber = transcriber
        self.stt_profile_service = stt_profile_service or STTProfileService()

    @staticmethod
    def get_audio_duration(file_path: str) -> float:
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except Exception as exc:
            logger.warning("[FFprobe] failed to read duration: %s", exc)
            return 0.0

    def _is_local_transcriber(self, config: ResolvedSTTConfig | None) -> bool:
        if config:
            return config.provider in LOCAL_STT_PROVIDERS
        return settings.transcriber_type.lower() in LOCAL_STT_PROVIDERS

    @staticmethod
    def _format_seconds(value: float) -> str:
        total_seconds = max(0, int(round(value)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _get_effective_chunk_duration(self, *, audio_path: str, duration: float) -> float:
        configured_max = max(300.0, float(settings.transcription_chunk_max_duration_seconds))
        target_size_bytes = settings.transcription_chunk_target_file_size_mb * 1024 * 1024
        file_size_bytes = Path(audio_path).stat().st_size
        if duration <= 0 or file_size_bytes <= 0 or target_size_bytes <= 0:
            return configured_max

        bytes_per_second = file_size_bytes / duration
        if bytes_per_second <= 0:
            return configured_max

        size_limited_max = (target_size_bytes / bytes_per_second) * 0.9
        effective_max = min(configured_max, size_limited_max)
        return max(180.0, effective_max)

    def _build_chunk_specs(self, *, audio_path: str, duration: float, temp_dir: Path) -> list[ChunkSpec]:
        if not settings.transcription_chunking_enabled or duration <= 0:
            return []

        max_chunk_duration = self._get_effective_chunk_duration(audio_path=audio_path, duration=duration)
        target_size_bytes = settings.transcription_chunk_target_file_size_mb * 1024 * 1024
        file_size_bytes = Path(audio_path).stat().st_size
        if duration <= max_chunk_duration and file_size_bytes <= target_size_bytes:
            return []

        overlap = max(15.0, float(settings.transcription_chunk_overlap_seconds))
        min_core = max(60.0, float(settings.transcription_chunk_min_core_seconds))
        max_allowed_overlap = max(15.0, (max_chunk_duration - 60.0) / 2)
        overlap = min(overlap, max_allowed_overlap)
        core_duration = max_chunk_duration - (2 * overlap)

        if core_duration < min_core:
            overlap = max(15.0, (max_chunk_duration - min_core) / 2)
            core_duration = max_chunk_duration - (2 * overlap)
        if core_duration <= 0:
            overlap = max(0.0, max_chunk_duration * 0.1)
            core_duration = max(60.0, max_chunk_duration - (2 * overlap))
        if core_duration <= 0:
            return []

        total = max(1, math.ceil(duration / core_duration))
        chunks: list[ChunkSpec] = []
        trim_start = 0.0

        for index in range(1, total + 1):
            trim_end = duration if index == total else min(duration, trim_start + core_duration)
            chunk_start = max(0.0, trim_start - overlap)
            chunk_end = min(duration, trim_end + overlap)
            chunks.append(
                ChunkSpec(
                    index=index,
                    total=total,
                    file_path=temp_dir / f"chunk_{index:03d}.mp3",
                    chunk_start=round(chunk_start, 3),
                    chunk_end=round(chunk_end, 3),
                    trim_start=round(trim_start, 3),
                    trim_end=round(trim_end, 3),
                )
            )
            trim_start = trim_end

        logger.info(
            "[Transcribe] chunking enabled file=%s duration=%.1fs chunks=%s max_chunk=%.1fs overlap=%.1fs",
            audio_path,
            duration,
            len(chunks),
            max_chunk_duration,
            overlap,
        )
        return chunks

    @traced("提取音频分块")
    def _extract_chunk(self, *, audio_path: str, chunk: ChunkSpec) -> None:
        duration = max(1.0, chunk.chunk_end - chunk.chunk_start)
        bitrate = max(32, int(settings.transcription_chunk_bitrate_kbps))
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{chunk.chunk_start:.3f}",
            "-i",
            audio_path,
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            f"{bitrate}k",
            str(chunk.file_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)

    @staticmethod
    def _segment_midpoint(segment: TranscriptSegment) -> float:
        return (segment.start + segment.end) / 2

    @traced("合并识别分块")
    def _merge_chunk_results(self, *, chunk_results: list[tuple[ChunkSpec, TranscriptResult]]) -> TranscriptResult:
        merged_segments: list[TranscriptSegment] = []
        languages: list[str] = []

        for chunk, result in chunk_results:
            if result.language and result.language != "unknown":
                languages.append(result.language)

            kept_in_chunk = 0
            for segment in result.segments:
                absolute_segment = TranscriptSegment(
                    start=round(chunk.chunk_start + segment.start, 2),
                    end=round(chunk.chunk_start + segment.end, 2),
                    text=segment.text.strip(),
                    raw_text=segment.raw_text,
                    cleaned_text=segment.cleaned_text,
                    speaker_id=segment.speaker_id,
                    speaker_label=segment.speaker_label,
                )
                midpoint = self._segment_midpoint(absolute_segment)
                is_last_chunk = chunk.index == chunk.total
                within_trim_window = chunk.trim_start <= midpoint <= chunk.trim_end
                if not is_last_chunk and math.isclose(midpoint, chunk.trim_end, abs_tol=0.01):
                    within_trim_window = False
                if not within_trim_window:
                    continue

                absolute_segment.start = max(absolute_segment.start, round(chunk.trim_start, 2))
                absolute_segment.end = min(absolute_segment.end, round(chunk.trim_end, 2))
                if absolute_segment.end <= absolute_segment.start or not absolute_segment.text:
                    continue

                merged_segments.append(absolute_segment)
                kept_in_chunk += 1

            if kept_in_chunk == 0 and result.full_text.strip():
                merged_segments.append(
                    TranscriptSegment(
                        start=round(chunk.trim_start, 2),
                        end=round(chunk.trim_end, 2),
                        text=result.full_text.strip(),
                    )
                )

        merged_segments.sort(key=lambda segment: (segment.start, segment.end))

        deduped_segments: list[TranscriptSegment] = []
        for segment in merged_segments:
            if not deduped_segments:
                deduped_segments.append(segment)
                continue

            previous = deduped_segments[-1]
            if (
                segment.text == previous.text
                and abs(segment.start - previous.start) <= 1.0
            ):
                previous.end = max(previous.end, segment.end)
                continue

            deduped_segments.append(segment)

        full_text = " ".join(segment.text for segment in deduped_segments).strip()
        language = Counter(languages).most_common(1)[0][0] if languages else None
        metadata = next((result.metadata for _, result in chunk_results if result.metadata), {})
        return TranscriptResult(
            language=language,
            full_text=full_text,
            segments=deduped_segments,
            metadata=metadata,
        )

    def _transcribe_in_chunks(
        self,
        *,
        audio_path: str,
        duration: float,
        transcriber: Transcriber,
        update_status: StatusCallback | None = None,
    ) -> TranscriptResult:
        with tempfile.TemporaryDirectory(prefix="transcribe_chunks_", dir=settings.data_dir) as temp_dir:
            chunk_specs = self._build_chunk_specs(
                audio_path=audio_path,
                duration=duration,
                temp_dir=Path(temp_dir),
            )
            if not chunk_specs:
                return self._transcribe_chunk(transcriber, audio_path)

            chunk_results: list[tuple[ChunkSpec, TranscriptResult]] = []
            for chunk in chunk_specs:
                self._extract_chunk(audio_path=audio_path, chunk=chunk)
                logger.info(
                    "[Transcribe] chunk=%s/%s source=%s range=%s-%s trim=%s-%s",
                    chunk.index,
                    chunk.total,
                    audio_path,
                    self._format_seconds(chunk.chunk_start),
                    self._format_seconds(chunk.chunk_end),
                    self._format_seconds(chunk.trim_start),
                    self._format_seconds(chunk.trim_end),
                )
                if update_status:
                    update_status(
                        "transcribing",
                        (
                            f"Transcribing chunk {chunk.index}/{chunk.total} "
                            f"({self._format_seconds(chunk.trim_start)} - {self._format_seconds(chunk.trim_end)})..."
                        ),
                    )
                chunk_results.append((chunk, self._transcribe_chunk(transcriber, str(chunk.file_path), chunk)))

            return self._merge_chunk_results(chunk_results=chunk_results)

    def transcribe(
        self,
        *,
        audio_path: str,
        load_cached: Callable[[], TranscriptResult | None],
        save_transcript: Callable[[TranscriptResult], None],
        update_status: StatusCallback | None = None,
        user_id: str | None = None,
        stt_profile_id: str | None = None,
        diarize: bool = False,
        speaker_count: int | None = None,
    ) -> TranscriptResult:
        cached = load_cached()
        if cached and bool(cached.metadata.get("speaker_diarization")) == diarize:
            update_current(metadata={"cache_hit": True})
            logger.info("[Transcribe] cache hit for audio=%s", audio_path)
            return cached

        resolved_config = None if self.transcriber else self.stt_profile_service.resolve_config(
            user_id=user_id,
            stt_profile_id=stt_profile_id,
        )
        transcriber = self.transcriber or create_transcriber(resolved_config)
        if resolved_config:
            update_current(metadata={"provider": resolved_config.provider,
                                     "model": resolved_config.model_name, "cache_hit": False})

        if self._is_local_transcriber(resolved_config) and update_status:
            update_status("transcribing", "Loading local speech model...")

        if diarize:
            from app.services.speaker_diarization_service import SpeakerDiarizationService
            transcript = SpeakerDiarizationService().transcribe(
                audio_path=audio_path,
                transcribe=lambda path: self._transcribe_chunk(transcriber, path),
                speaker_count=speaker_count, update_status=update_status,
            )
        else:
            duration = self.get_audio_duration(audio_path)
            transcript = self._transcribe_in_chunks(
                audio_path=audio_path, duration=duration, transcriber=transcriber,
                update_status=update_status,
            )
        if update_status:
            update_status("transcribing", "Saving transcription...")

        save_transcript(transcript)
        return transcript
