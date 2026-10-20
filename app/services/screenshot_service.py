"""
Screenshot placeholder processing for generated notes.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from app.downloaders.base import Downloader
from app.services.task_artifact_service import TaskArtifactService
from app.services.video_link_service import build_video_jump_url, format_timestamp_label
from app.services.video_evidence_service import VideoEvidenceService, VideoEvidenceError

logger = logging.getLogger(__name__)


class ScreenshotService:
    def __init__(self, downloader: Downloader, artifact_service: TaskArtifactService | None = None):
        self.downloader = downloader
        self.artifact_service = artifact_service or TaskArtifactService()

    def prepare_local_video(
        self,
        *,
        video_url: str,
        task_dir: Path,
        task_id: str,
    ) -> tuple[Path, str] | None:
        try:
            downloaded_video = self.downloader.download_video(video_url=video_url, output_dir=str(task_dir / "downloads"))
            staged_video = self.artifact_service.stage_media_file(task_dir, downloaded_video, target_stem="source_video")
            return staged_video, self._build_task_media_url(task_id, staged_video.name)
        except Exception as exc:
            logger.warning("[Screenshot] local video preparation failed: %s", exc)
            return None

    def inject_screenshots(
        self,
        *,
        video_url: str,
        markdown: str,
        task_dir: Path,
        task_id: str,
        media_url: str,
        local_video_path: Path | None = None,
    ) -> str:
        pattern = r"\[\[Screenshot:(\d{1,4}):([0-5]\d)\]\]"
        matches = re.findall(pattern, markdown)
        if not matches:
            return markdown

        # A generated marker never authorizes downloading another original.
        if not local_video_path or not Path(local_video_path).is_file():
            return re.sub(pattern, "", markdown)

        timestamps = [int(minutes) * 60 + int(seconds) for minutes, seconds in matches]
        unique_timestamps = list(dict.fromkeys(timestamps))

        try:
            output_dir = task_dir / 'screenshots'
            output_dir.mkdir(exist_ok=True)
            frame_by_timestamp = {}
            for timestamp in unique_timestamps[:32]:
                destination = output_dir / f'frame-{timestamp:08d}.jpg'
                try:
                    VideoEvidenceService._extract_frame(Path(local_video_path).resolve(), timestamp, destination)
                    frame_by_timestamp[timestamp] = destination
                except (VideoEvidenceError, OSError, ValueError, subprocess.SubprocessError):
                    # Missing one frame must not move the next successful image
                    # onto this timestamp (downloaders historically compact lists).
                    continue
            for index, (minutes, seconds) in enumerate(matches):
                marker = f"[[Screenshot:{minutes}:{seconds}]]"
                timestamp = timestamps[index]
                frame_path = frame_by_timestamp.get(timestamp)
                if frame_path:
                    asset_path = f"/api/task/{task_id}/artifacts/screenshots/{Path(frame_path).name}"
                    label = format_timestamp_label(timestamp)
                    jump_url = build_video_jump_url(media_url, timestamp)
                    image_markdown = f"[![Screenshot {label}]({asset_path})]({jump_url})"
                    markdown = markdown.replace(marker, image_markdown, 1)
                else:
                    markdown = markdown.replace(marker, "", 1)
        except Exception as exc:
            logger.warning("[Screenshot] processing failed: %s", exc)
            markdown = re.sub(pattern, "", markdown)
        return markdown

    @staticmethod
    def _build_task_media_url(task_id: str, file_name: str) -> str:
        return f"/api/task/{task_id}/artifacts/media/{file_name}"
