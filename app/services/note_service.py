"""
Core note generation pipeline orchestration.
"""
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.tracing_service import traced, update_current, content_summary
from app.downloaders.base import Downloader
from app.downloaders.ytdlp_downloader import YtdlpDownloader
from app.llm.prompts import normalize_output_language, normalize_summary_mode
from app.models.audio import AudioDownloadResult
from app.models.note import NoteResult
from app.models.transcript import TranscriptResult
from app.services.llm_service import LLMService
from app.services.note_media_service import NoteMediaService
from app.services.screenshot_service import ScreenshotService
from app.services.task_artifact_service import TaskArtifactService
from app.services.transcription_service import TranscriptionService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineContext:
    task_id: str
    task_dir: Path
    audio_meta: AudioDownloadResult
    style: str
    summary_mode: str
    extras: str | None
    output_language: str | None
    model_profile_id: str | None
    stt_profile_id: str | None
    model_name: str | None
    api_key: str | None
    base_url: str | None
    user_id: str | None
    source_video_url: str | None
    task_start_time: float
    step_timings: dict[str, float]
    preloaded_transcript: TranscriptResult | None = None


class NoteService:
    def __init__(
        self,
        downloader: Downloader | None = None,
        transcription_service: TranscriptionService | None = None,
        llm_service: LLMService | None = None,
        artifact_service: TaskArtifactService | None = None,
        screenshot_service: ScreenshotService | None = None,
        media_service: NoteMediaService | None = None,
    ):
        self.downloader: Downloader = downloader or YtdlpDownloader()
        self.transcription_service = transcription_service or TranscriptionService()
        self.llm_service = llm_service or LLMService()
        self.artifact_service = artifact_service or TaskArtifactService()
        self.screenshot_service = screenshot_service or ScreenshotService(self.downloader)
        self.media_service = media_service or NoteMediaService()
        llm_config = self.llm_service.resolve_config(
            user_id=None,
            model_profile_id=None,
            model_name=None,
            api_key=None,
            base_url=None,
        )
        logger.info(
            "[NoteService] init transcriber=%s llm=%s",
            settings.transcriber_type,
            llm_config.model_name,
        )

    @traced("笔记生成全链路", root=True, as_type="chain")
    def generate(
        self,
        video_url: str,
        task_id: str,
        platform: str = "auto",
        style: str = "detailed",
        summary_mode: str = "default",
        extras: Optional[str] = None,
        output_language: str | None = None,
        model_profile_id: Optional[str] = None,
        stt_profile_id: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> NoteResult:
        del platform

        task_start_time = time.time()
        task_dir = self.artifact_service.create_task_dir(task_id)
        step_timings: dict[str, float] = {}

        try:
            from app.services.vilab_cloud_service import VILabCloudService

            VILabCloudService().validate_ready(user_id, needs_stt=True)
            step_start = time.time()
            self.artifact_service.update_status(task_dir, "downloading", "Downloading audio...")
            audio_meta = self._download_audio(video_url=video_url, task_dir=task_dir)
            step_timings["download"] = time.time() - step_start

            return self._run_pipeline(
                task_id=task_id,
                task_dir=task_dir,
                audio_meta=audio_meta,
                style=style,
                summary_mode=summary_mode,
                extras=extras,
                output_language=output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                preloaded_transcript=None,
                user_id=user_id,
                source_video_url=video_url,
                task_start_time=task_start_time,
                step_timings=step_timings,
            )
        except Exception as exc:
            logger.error("[Pipeline] task=%s failed: %s", task_id, exc, exc_info=True)
            failed_dir = self.artifact_service.find_task_dir(task_id) or task_dir
            if failed_dir.exists():
                self.artifact_service.update_status(failed_dir, "failed", str(exc))
            raise

    @traced("笔记生成全链路", root=True, as_type="chain")
    def generate_from_file(
        self,
        file_path: str,
        task_id: str,
        title: Optional[str] = None,
        style: str = "meeting",
        summary_mode: str = "default",
        extras: Optional[str] = None,
        output_language: str | None = None,
        model_profile_id: Optional[str] = None,
        stt_profile_id: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> NoteResult:
        task_start_time = time.time()
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file does not exist: {file_path}")

        task_dir = self.artifact_service.create_task_dir(task_id)
        step_timings: dict[str, float] = {}

        try:
            from app.services.vilab_cloud_service import VILabCloudService

            VILabCloudService().validate_ready(user_id, needs_stt=True)
            step_start = time.time()
            self.artifact_service.update_status(task_dir, "preparing", "Preparing local audio file...")
            audio_meta = self._build_local_audio_meta(file_path=file_path, task_id=task_id, title=title)
            self.artifact_service.save_audio_meta(task_dir, audio_meta)
            step_timings["prepare"] = time.time() - step_start

            return self._run_pipeline(
                task_id=task_id,
                task_dir=task_dir,
                audio_meta=audio_meta,
                style=style,
                summary_mode=summary_mode,
                extras=extras,
                output_language=output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                user_id=user_id,
                source_video_url=None,
                task_start_time=task_start_time,
                preloaded_transcript=None,
                step_timings=step_timings,
            )
        except Exception as exc:
            logger.error("[Pipeline] local task=%s failed: %s", task_id, exc, exc_info=True)
            failed_dir = self.artifact_service.find_task_dir(task_id) or task_dir
            if failed_dir.exists():
                self.artifact_service.update_status(failed_dir, "failed", str(exc))
            raise

    @traced("笔记生成全链路", root=True, as_type="chain")
    def generate_from_transcript(
        self,
        transcript: TranscriptResult,
        task_id: str,
        title: str | None = None,
        style: str = "meeting",
        summary_mode: str = "default",
        extras: Optional[str] = None,
        output_language: str | None = None,
        model_profile_id: Optional[str] = None,
        stt_profile_id: Optional[str] = None,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        user_id: Optional[str] = None,
    ) -> NoteResult:
        task_start_time = time.time()
        task_dir = self.artifact_service.create_task_dir(task_id)
        step_timings: dict[str, float] = {}

        try:
            from app.services.vilab_cloud_service import VILabCloudService

            VILabCloudService().validate_ready(user_id, needs_stt=False)
            step_start = time.time()
            self.artifact_service.update_status(task_dir, "preparing", "Preparing uploaded transcript...")
            audio_meta = self._build_transcript_audio_meta(transcript=transcript, task_id=task_id, title=title)
            self.artifact_service.save_audio_meta(task_dir, audio_meta)
            step_timings["prepare"] = time.time() - step_start

            return self._run_pipeline(
                task_id=task_id,
                task_dir=task_dir,
                audio_meta=audio_meta,
                style=style,
                summary_mode=summary_mode,
                extras=extras,
                output_language=output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                user_id=user_id,
                source_video_url=None,
                preloaded_transcript=transcript,
                task_start_time=task_start_time,
                step_timings=step_timings,
            )
        except Exception as exc:
            logger.error("[Pipeline] transcript task=%s failed: %s", task_id, exc, exc_info=True)
            failed_dir = self.artifact_service.find_task_dir(task_id) or task_dir
            if failed_dir.exists():
                self.artifact_service.update_status(failed_dir, "failed", str(exc))
            raise

    @traced("下载源媒体")
    def _download_audio(self, *, video_url: str, task_dir: Path) -> AudioDownloadResult:
        cached_audio = self.artifact_service.load_audio_meta(task_dir)
        if cached_audio:
            logger.info("[Download] cache hit for task_dir=%s", task_dir)
            return cached_audio

        audio_meta = self.downloader.download(video_url=video_url, output_dir=str(settings.data_dir))
        self.artifact_service.save_audio_meta(task_dir, audio_meta)
        return audio_meta

    @traced("准备本地媒体")
    def _build_local_audio_meta(self, *, file_path: str, task_id: str, title: str | None) -> AudioDownloadResult:
        audio_title = title or os.path.splitext(os.path.basename(file_path))[0]
        return AudioDownloadResult(
            file_path=file_path,
            title=audio_title,
            duration=self.transcription_service.get_audio_duration(file_path),
            video_id=task_id,
            platform="local",
            cover_url=None,
            raw_info={},
        )

    @traced("准备上传字幕")
    def _build_transcript_audio_meta(
        self,
        *,
        transcript: TranscriptResult,
        task_id: str,
        title: str | None,
    ) -> AudioDownloadResult:
        transcript_title = title or "Uploaded transcript"
        return AudioDownloadResult(
            file_path="",
            title=transcript_title,
            duration=max(
                0.0,
                max((segment.end for segment in transcript.segments), default=0.0),
            ),
            video_id=task_id,
            platform="transcript",
            cover_url=None,
            raw_info={},
        )


    def _run_pipeline(
        self,
        *,
        task_id: str,
        task_dir: Path,
        audio_meta: AudioDownloadResult,
        style: str,
        summary_mode: str,
        extras: str | None,
        output_language: str | None,
        model_profile_id: str | None,
        stt_profile_id: str | None,
        model_name: str | None,
        api_key: str | None,
        base_url: str | None,
        preloaded_transcript: TranscriptResult | None = None,
        user_id: str | None,
        source_video_url: str | None,
        task_start_time: float,
        step_timings: dict[str, float],
    ) -> NoteResult:
        resolved_output_language = normalize_output_language(output_language)
        resolved_summary_mode = normalize_summary_mode(summary_mode)
        final_dir = self.artifact_service.finalize_task_dir(task_dir, audio_meta.title, task_id)
        self._rebase_audio_meta_path_after_finalize(audio_meta, original_task_dir=task_dir, final_dir=final_dir)
        self.artifact_service.save_audio_meta(final_dir, audio_meta)
        context = PipelineContext(
            task_id=task_id,
            task_dir=final_dir,
            audio_meta=audio_meta,
            style=style,
            summary_mode=resolved_summary_mode,
            extras=extras,
            output_language=resolved_output_language,
            model_profile_id=model_profile_id,
            stt_profile_id=stt_profile_id,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            user_id=user_id,
            preloaded_transcript=preloaded_transcript,
            source_video_url=source_video_url,
            task_start_time=task_start_time,
            step_timings=step_timings,
        )

        try:
            from app.services.vilab_cloud_service import VILabCloudService

            with VILabCloudService().task_snapshot(user_id):
                transcript = self._transcribe_audio(context)
                markdown = self._summarize_audio(context, transcript)
            markdown = self._enrich_markdown_with_media(context, transcript, markdown)
            result = self._build_result(context, transcript, markdown)

            self.artifact_service.save_markdown(final_dir, markdown)
            self.artifact_service.save_result(final_dir, result)
            self.artifact_service.update_status(final_dir, "success", "Note generated successfully")
            logger.info("[Pipeline] task=%s completed timings=%s", task_id, step_timings)
            return result
        except Exception as exc:
            self.artifact_service.update_status(final_dir, "failed", str(exc))
            raise

    @staticmethod
    def _rebase_audio_meta_path_after_finalize(
        audio_meta: AudioDownloadResult,
        *,
        original_task_dir: Path,
        final_dir: Path,
    ) -> None:
        if not audio_meta.file_path:
            return

        source_path = Path(audio_meta.file_path)
        try:
            relative_path = source_path.resolve().relative_to(original_task_dir.resolve())
        except ValueError:
            return

        audio_meta.file_path = str(final_dir / relative_path)

    @traced("获取识别原文", as_type="chain")
    def _transcribe_audio(self, context: PipelineContext):
        if context.preloaded_transcript is not None:
            update_current(metadata={"source": "uploaded_transcript", "stt_skipped": True},
                           output=content_summary(context.preloaded_transcript.full_text))
            self.artifact_service.update_status(context.task_dir, "transcribing", "Using uploaded transcript...")
            self.artifact_service.save_transcript(context.task_dir, context.preloaded_transcript)
            context.step_timings["transcribe"] = 0.0
            return context.preloaded_transcript

        step_start = time.time()
        self.artifact_service.update_status(context.task_dir, "transcribing", "Transcribing audio...")
        transcript = self.transcription_service.transcribe(
            audio_path=context.audio_meta.file_path,
            load_cached=lambda: self.artifact_service.load_transcript(context.task_dir),
            save_transcript=lambda result: self.artifact_service.save_transcript(context.task_dir, result),
            update_status=lambda status, message: self.artifact_service.update_status(
                context.task_dir,
                status,
                message,
            ),
            user_id=context.user_id,
            stt_profile_id=context.stt_profile_id,
        )
        context.step_timings["transcribe"] = time.time() - step_start
        update_current(output=content_summary(transcript.full_text),
                       metadata={"segment_count": len(transcript.segments)})
        return transcript

    @traced("生成结构化笔记", as_type="chain")
    def _summarize_audio(self, context: PipelineContext, transcript):
        step_start = time.time()
        self.artifact_service.update_status(context.task_dir, "summarizing", "Generating note...")
        llm = self.llm_service.create_summarizer(
            user_id=context.user_id,
            model_profile_id=context.model_profile_id,
            model_name=context.model_name,
            api_key=context.api_key,
            base_url=context.base_url,
        )
        markdown = llm.summarize(
            title=context.audio_meta.title,
            segments=transcript.segments,
            style=context.style,
            summary_mode=context.summary_mode,
            extras=context.extras,
            output_language=context.output_language,
            progress_callback=lambda message: self.artifact_service.update_status(
                context.task_dir,
                "summarizing",
                message,
            ),
        )
        context.step_timings["summarize"] = time.time() - step_start
        return markdown

    @traced("处理时间戳与截图")
    def _enrich_markdown_with_media(self, context: PipelineContext, transcript, markdown: str) -> str:
        media_url = ""
        if context.audio_meta.file_path and os.path.exists(context.audio_meta.file_path):
            local_audio_file = self.artifact_service.stage_media_file(
                context.task_dir,
                context.audio_meta.file_path,
                target_stem="source_audio",
            )
            media_url = f"/api/task/{context.task_id}/artifacts/media/{local_audio_file.name}"
        local_video_path = None

        if not context.source_video_url:
            return markdown

        prepared_video = self.screenshot_service.prepare_local_video(
            video_url=context.source_video_url,
            task_dir=context.task_dir,
            task_id=context.task_id,
        )
        if prepared_video:
            local_video_path, media_url = prepared_video

        markdown = self.media_service.enrich_markdown(
            markdown=markdown,
            transcript_segments=transcript.segments,
            video_url=media_url,
            output_language=context.output_language,
        )

        step_start = time.time()
        self.artifact_service.update_status(context.task_dir, "screenshots", "Processing screenshots...")
        markdown = self.screenshot_service.inject_screenshots(
            video_url=context.source_video_url,
            markdown=markdown,
            task_dir=context.task_dir,
            task_id=context.task_id,
            media_url=media_url,
            local_video_path=local_video_path,
        )
        context.step_timings["screenshots"] = time.time() - step_start
        return markdown

    def _build_result(self, context: PipelineContext, transcript, markdown: str) -> NoteResult:
        context.step_timings["total"] = time.time() - context.task_start_time
        return NoteResult(
            markdown=markdown,
            transcript=transcript,
            audio_meta=context.audio_meta,
            summary_mode=context.summary_mode,
            output_dir=str(context.task_dir),
        )

    def get_status(self, task_id: str) -> dict:
        return self.artifact_service.get_status(task_id)

    def get_result(self, task_id: str) -> Optional[dict]:
        return self.artifact_service.get_result(task_id)
