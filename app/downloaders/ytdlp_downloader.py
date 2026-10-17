"""
Generic yt-dlp based downloader.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import yt_dlp

from app.config import settings
from app.downloaders.base import Downloader
from app.models.audio import AudioDownloadResult

logger = logging.getLogger(__name__)


class YoutubeAccessBlockedError(RuntimeError):
    """Raised when YouTube challenges the server's anonymous download session."""


class YtdlpDownloader(Downloader):
    PLATFORM_PATTERNS: dict[str, list[str]] = {
        "youtube": ["youtube.com", "youtu.be"],
        "bilibili": ["bilibili.com", "b23.tv"],
        "douyin": ["douyin.com"],
        "tiktok": ["tiktok.com"],
        "xiaohongshu": ["xiaohongshu.com", "xhslink.com"],
    }

    def __init__(
        self,
        *,
        request_sleep_seconds: float | None = None,
        download_sleep_seconds: float | None = None,
        max_download_sleep_seconds: float | None = None,
    ):
        self.request_sleep_seconds = (
            settings.ytdlp_request_sleep_seconds
            if request_sleep_seconds is None
            else request_sleep_seconds
        )
        self.download_sleep_seconds = (
            settings.ytdlp_download_sleep_seconds
            if download_sleep_seconds is None
            else download_sleep_seconds
        )
        self.max_download_sleep_seconds = (
            settings.ytdlp_max_download_sleep_seconds
            if max_download_sleep_seconds is None
            else max_download_sleep_seconds
        )

    def detect_platform(self, video_url: str) -> str:
        parsed = urlparse(video_url)
        host = parsed.hostname or ""
        for platform, domains in self.PLATFORM_PATTERNS.items():
            if any(domain in host for domain in domains):
                return platform
        return "unknown"

    def detect_video_id(self, video_url: str) -> Optional[str]:
        parsed = urlparse(video_url)
        host = parsed.hostname or ""

        if "youtube.com" in host:
            return parse_qs(parsed.query).get("v", [None])[0]
        if "youtu.be" in host:
            return parsed.path.strip("/")
        if "bilibili.com" in host:
            match = re.search(r"/(BV[\w]+)", parsed.path)
            return match.group(1) if match else None

        return None

    def download(self, video_url: str, output_dir: str) -> AudioDownloadResult:
        os.makedirs(output_dir, exist_ok=True)

        platform = self.detect_platform(video_url)
        logger.info("[Download] platform=%s url=%s", platform, video_url)

        try:
            return self._download_with_ytdlp(video_url=video_url, output_dir=output_dir, platform=platform)
        except Exception as exc:
            if platform == "bilibili" and self._is_python_tls_eof_error(exc):
                logger.warning("[Download] yt-dlp failed for Bilibili over Python TLS, falling back to curl: %s", exc)
                return self._download_bilibili_audio_with_curl(video_url=video_url, output_dir=output_dir)
            raise

    def download_video(self, video_url: str, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)

        platform = self.detect_platform(video_url)
        try:
            return self._download_video_with_ytdlp(video_url=video_url, output_dir=output_dir, platform=platform)
        except Exception as exc:
            if platform == "bilibili" and self._is_python_tls_eof_error(exc):
                logger.warning("[Video] yt-dlp failed for Bilibili over Python TLS, falling back to curl: %s", exc)
                return self._download_bilibili_video_with_curl(video_url=video_url, output_dir=output_dir)
            raise

    def _download_video_with_ytdlp(self, *, video_url: str, output_dir: str, platform: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        logger.info("[Video] downloading platform=%s url=%s", platform, video_url)

        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
            "outtmpl": os.path.join(output_dir, f"{timestamp}_%(id)s_video.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 3,
            "socket_timeout": 20,
        }
        self._apply_platform_options(ydl_opts, platform)
        if platform == "bilibili":
            ydl_opts["format"] = "bestvideo+bestaudio/best"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = self._extract_info_with_ydl(ydl, video_url, platform, download=True)

        video_id = info.get("id", "unknown")
        filename_prefix = f"{timestamp}_{video_id}_video"
        candidates = sorted(
            (
                path for path in Path(output_dir).glob(f"{filename_prefix}.*")
                if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(f"Downloaded video file was not found for prefix: {filename_prefix}")

        logger.info("[Video] completed path=%s", candidates[0])
        return str(candidates[0])

    def extract_frames(
        self,
        video_path: str,
        timestamps: List[float],
        output_dir: str,
        width: int = 1280,
    ) -> List[str]:
        os.makedirs(output_dir, exist_ok=True)
        video_id = Path(video_path).stem.replace("_video", "")
        frame_paths: list[str] = []

        for index, timestamp in enumerate(timestamps):
            minutes = int(timestamp // 60)
            seconds = int(timestamp % 60)
            time_str = f"00:{minutes:02d}:{seconds:02d}"
            output_path = os.path.join(output_dir, f"{video_id}_frame_{index + 1:02d}.jpg")

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                time_str,
                "-i",
                video_path,
                "-vframes",
                "1",
                "-vf",
                f"scale={width}:-1",
                "-q:v",
                "2",
                output_path,
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=30)
                if os.path.exists(output_path):
                    frame_paths.append(output_path)
                    logger.info("[Frame] extracted time=%s path=%s", time_str, output_path)
            except Exception as exc:
                logger.warning("[Frame] failed time=%s error=%s", time_str, exc)

        return frame_paths

    def _extract_info(self, video_url: str, platform: str) -> dict:
        ydl_opts_info = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 3,
            "socket_timeout": 20,
        }
        self._apply_platform_options(ydl_opts_info, platform)

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            return self._extract_info_with_ydl(ydl, video_url, platform, download=False)

    def _download_with_ytdlp(self, *, video_url: str, output_dir: str, platform: str) -> AudioDownloadResult:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_template = os.path.join(output_dir, f"{timestamp}_%(id)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": output_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "64",
                }
            ],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 3,
            "socket_timeout": 20,
        }
        self._apply_platform_options(ydl_opts, platform)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = self._extract_info_with_ydl(ydl, video_url, platform, download=True)

        video_id = info.get("id", "unknown")
        title = info.get("title", "Untitled")
        duration = info.get("duration", 0)
        cover_url = info.get("thumbnail")
        filename_prefix = f"{timestamp}_{video_id}"
        audio_path = os.path.join(output_dir, f"{filename_prefix}.mp3")
        logger.info("[Download] completed title=%s duration=%ss path=%s", title, duration, audio_path)

        return AudioDownloadResult(
            file_path=audio_path,
            title=title,
            duration=duration,
            video_id=video_id,
            platform=platform,
            cover_url=cover_url,
            raw_info=info,
        )

    def _apply_platform_options(self, ydl_opts: dict, platform: str) -> None:
        if platform == "youtube":
            ydl_opts.update(
                {
                    "sleep_interval_requests": self.request_sleep_seconds,
                    "sleep_interval": self.download_sleep_seconds,
                    "max_sleep_interval": self.max_download_sleep_seconds,
                }
            )
        if platform == "bilibili":
            ydl_opts["http_headers"] = self._bilibili_headers()

    @staticmethod
    def _extract_info_with_ydl(
        ydl: yt_dlp.YoutubeDL,
        video_url: str,
        platform: str,
        *,
        download: bool,
    ) -> dict:
        try:
            return ydl.extract_info(video_url, download=download)
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            if (
                platform == "youtube"
                and "Sign in to confirm" in message
                and "not a bot" in message
            ):
                raise YoutubeAccessBlockedError(
                    "YouTube 触发了机器人验证，当前服务器出口暂时无法下载该视频。"
                    "请稍后重试，或切换可用的代理节点。"
                ) from exc
            raise

    def _download_bilibili_audio_with_curl(self, *, video_url: str, output_dir: str) -> AudioDownloadResult:
        info = self._extract_bilibili_info_with_curl(video_url)
        audio_url = self._select_bilibili_audio_url(info)

        video_id = info.get("id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_prefix = f"{timestamp}_{video_id}"
        raw_path = Path(output_dir) / f"{filename_prefix}.m4s"
        audio_path = Path(output_dir) / f"{filename_prefix}.mp3"

        self._curl_download(audio_url, raw_path)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw_path),
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "64k",
                    str(audio_path),
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
        finally:
            raw_path.unlink(missing_ok=True)

        logger.info("[Download] Bilibili curl fallback completed title=%s path=%s", info.get("title"), audio_path)
        return AudioDownloadResult(
            file_path=str(audio_path),
            title=info.get("title", "Untitled"),
            duration=info.get("duration", 0),
            video_id=video_id,
            platform="bilibili",
            cover_url=info.get("thumbnail"),
            raw_info=info,
        )

    def _download_bilibili_video_with_curl(self, *, video_url: str, output_dir: str) -> str:
        info = self._extract_bilibili_info_with_curl(video_url)
        video_stream_url = self._select_bilibili_video_url(info)
        audio_stream_url = self._select_bilibili_audio_url(info)

        video_id = info.get("id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_prefix = f"{timestamp}_{video_id}_video"
        raw_video_path = Path(output_dir) / f"{filename_prefix}.video.m4s"
        raw_audio_path = Path(output_dir) / f"{filename_prefix}.audio.m4s"
        output_path = Path(output_dir) / f"{filename_prefix}.mp4"

        self._curl_download(video_stream_url, raw_video_path, timeout=900, max_time=900)
        self._curl_download(audio_stream_url, raw_audio_path, timeout=900, max_time=900)
        try:
            self._merge_bilibili_streams(raw_video_path, raw_audio_path, output_path)
        finally:
            raw_video_path.unlink(missing_ok=True)
            raw_audio_path.unlink(missing_ok=True)

        logger.info("[Video] Bilibili curl fallback completed title=%s path=%s", info.get("title"), output_path)
        return str(output_path)

    @staticmethod
    def _merge_bilibili_streams(video_path: Path, audio_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        copy_command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
        try:
            subprocess.run(copy_command, check=True, capture_output=True, timeout=900)
            return
        except subprocess.CalledProcessError:
            output_path.unlink(missing_ok=True)

        transcode_command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
        subprocess.run(transcode_command, check=True, capture_output=True, timeout=1800)

    def _extract_bilibili_info_with_curl(self, video_url: str) -> dict:
        html = self._curl_text(video_url)
        initial_state = self._parse_bilibili_initial_state(html)
        video_data = initial_state.get("videoData") or {}
        bvid = video_data.get("bvid") or self.detect_video_id(video_url)
        cid = video_data.get("cid")
        if not cid:
            pages = video_data.get("pages") or []
            cid = pages[0].get("cid") if pages else None
        if not bvid or not cid:
            raise ValueError("Bilibili metadata did not include bvid/cid")

        playurl_api = "https://api.bilibili.com/x/player/playurl?" + urlencode(
            {
                "bvid": bvid,
                "cid": cid,
                "fnval": 16,
                "otype": "json",
            }
        )
        playurl = self._curl_json(playurl_api)
        return {
            "id": bvid,
            "bvid": bvid,
            "cid": cid,
            "title": video_data.get("title") or "Untitled",
            "duration": video_data.get("duration") or 0,
            "thumbnail": video_data.get("pic"),
            "webpage_url": video_url,
            "bilibili_playurl": playurl,
            "bilibili_initial_state": initial_state,
        }

    @staticmethod
    def _parse_bilibili_initial_state(html: str) -> dict:
        match = re.search(r"window\.__INITIAL_STATE__=(.*?);\s*\(function\(\)", html)
        if not match:
            raise ValueError("Bilibili page did not include __INITIAL_STATE__")
        return json.loads(match.group(1))

    @staticmethod
    def _select_bilibili_audio_url(info: dict) -> str:
        playurl = info.get("bilibili_playurl") or {}
        data = playurl.get("data") or {}
        if playurl.get("code") != 0:
            raise ValueError(f"Bilibili playurl API failed: {playurl.get('message')}")
        audios = ((data.get("dash") or {}).get("audio") or [])
        if not audios:
            raise ValueError("Bilibili playurl API did not return audio streams")
        best_audio = max(audios, key=lambda item: item.get("bandwidth") or 0)
        audio_url = best_audio.get("baseUrl") or best_audio.get("base_url")
        if not audio_url:
            raise ValueError("Bilibili audio stream did not include a URL")
        return audio_url

    @staticmethod
    def _select_bilibili_video_url(info: dict) -> str:
        playurl = info.get("bilibili_playurl") or {}
        data = playurl.get("data") or {}
        if playurl.get("code") != 0:
            raise ValueError(f"Bilibili playurl API failed: {playurl.get('message')}")
        videos = ((data.get("dash") or {}).get("video") or [])
        if not videos:
            raise ValueError("Bilibili playurl API did not return video streams")

        def stream_url(item: dict) -> str:
            return item.get("baseUrl") or item.get("base_url") or ""

        playable_videos = [item for item in videos if stream_url(item)]
        if not playable_videos:
            raise ValueError("Bilibili video streams did not include URLs")

        h264_videos = [
            item for item in playable_videos
            if item.get("codecid") == 7 or "avc" in str(item.get("codecs") or "").lower()
        ]
        candidate_pool = h264_videos or playable_videos
        max_height_pool = [
            item for item in candidate_pool
            if int(item.get("height") or 0) <= 720
        ] or candidate_pool

        best_video = max(
            max_height_pool,
            key=lambda item: (
                int(item.get("height") or 0),
                int(item.get("width") or 0),
                int(item.get("bandwidth") or 0),
            ),
        )
        return stream_url(best_video)

    def _curl_text(self, url: str) -> str:
        result = self._run_curl(url, compressed=True)
        return result.stdout.decode("utf-8", errors="replace")

    def _curl_json(self, url: str) -> dict:
        return json.loads(self._curl_text(url))

    def _curl_download(self, url: str, output_path: Path, *, timeout: int = 300, max_time: int = 120) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._curl_base_command(url, max_time=max_time)
        cmd.extend(["--output", str(output_path)])
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)

    def _run_curl(self, url: str, *, compressed: bool = False) -> subprocess.CompletedProcess[bytes]:
        cmd = self._curl_base_command(url)
        if compressed:
            cmd.insert(-1, "--compressed")
        return subprocess.run(cmd, check=True, capture_output=True, timeout=30)

    def _curl_base_command(self, url: str, *, max_time: int = 120) -> list[str]:
        cmd = [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "3",
            "--retry-all-errors",
            "--connect-timeout",
            "15",
            "--max-time",
            str(max_time),
        ]
        for key, value in self._bilibili_headers().items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.append(url)
        return cmd

    @staticmethod
    def _is_python_tls_eof_error(exc: Exception) -> bool:
        message = str(exc)
        return "UNEXPECTED_EOF_WHILE_READING" in message or "EOF occurred in violation of protocol" in message

    @staticmethod
    def _bilibili_headers() -> dict[str, str]:
        return {
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
