import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import yt_dlp

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.downloaders.ytdlp_downloader import (
    YoutubeAccessBlockedError,
    YtdlpDownloader,
)


class YtdlpDownloaderBilibiliFallbackTest(unittest.TestCase):
    def test_parse_bilibili_initial_state(self):
        html = (
            "<html><script>"
            'window.__INITIAL_STATE__={"videoData":{"bvid":"BV123","cid":456,"title":"Demo"}};'
            "(function(){})"
            "</script></html>"
        )

        state = YtdlpDownloader._parse_bilibili_initial_state(html)

        self.assertEqual(state["videoData"]["bvid"], "BV123")
        self.assertEqual(state["videoData"]["cid"], 456)

    def test_selects_highest_bandwidth_audio_url(self):
        info = {
            "bilibili_playurl": {
                "code": 0,
                "data": {
                    "dash": {
                        "audio": [
                            {"bandwidth": 64000, "baseUrl": "https://example.test/low.m4s"},
                            {"bandwidth": 128000, "baseUrl": "https://example.test/high.m4s"},
                        ]
                    }
                },
            }
        }

        audio_url = YtdlpDownloader._select_bilibili_audio_url(info)

        self.assertEqual(audio_url, "https://example.test/high.m4s")

    def test_selects_h264_video_stream_under_720p(self):
        info = {
            "bilibili_playurl": {
                "code": 0,
                "data": {
                    "dash": {
                        "video": [
                            {
                                "height": 1080,
                                "width": 1920,
                                "bandwidth": 1_000_000,
                                "codecs": "avc1.640032",
                                "baseUrl": "https://example.test/1080p-avc.m4s",
                            },
                            {
                                "height": 720,
                                "width": 1280,
                                "bandwidth": 800_000,
                                "codecs": "avc1.640028",
                                "baseUrl": "https://example.test/720p-avc.m4s",
                            },
                            {
                                "height": 720,
                                "width": 1280,
                                "bandwidth": 900_000,
                                "codecs": "hev1.1.6.L120.90",
                                "baseUrl": "https://example.test/720p-hevc.m4s",
                            },
                        ]
                    }
                },
            }
        }

        video_url = YtdlpDownloader._select_bilibili_video_url(info)

        self.assertEqual(video_url, "https://example.test/720p-avc.m4s")

    def test_bilibili_headers_include_origin_and_referer(self):
        headers = YtdlpDownloader._bilibili_headers()

        self.assertEqual(headers["Origin"], "https://www.bilibili.com")
        self.assertEqual(headers["Referer"], "https://www.bilibili.com/")
        self.assertIn("Mozilla/5.0", headers["User-Agent"])

    def test_bilibili_curl_fallback_downloads_and_converts_audio(self):
        downloader = YtdlpDownloader()
        page_html = (
            "<html><script>"
            'window.__INITIAL_STATE__={"videoData":{"bvid":"BV123","cid":456,'
            '"title":"Demo Title","duration":12,"pic":"https://example.test/cover.jpg"}};'
            "(function(){})"
            "</script></html>"
        ).encode()
        playurl_json = json.dumps(
            {
                "code": 0,
                "message": "OK",
                "data": {
                    "dash": {
                        "audio": [
                            {
                                "bandwidth": 128000,
                                "baseUrl": "https://example.test/audio.m4s",
                            }
                        ]
                    }
                },
            }
        ).encode()

        def fake_run(cmd, **kwargs):
            if cmd[0] == "curl" and "www.bilibili.com" in cmd[-1]:
                return CompletedProcess(cmd, 0, stdout=page_html, stderr=b"")
            if cmd[0] == "curl" and "api.bilibili.com" in cmd[-1]:
                return CompletedProcess(cmd, 0, stdout=playurl_json, stderr=b"")
            if cmd[0] == "curl" and any("audio.m4s" in part for part in cmd):
                output_path = Path(cmd[cmd.index("--output") + 1])
                output_path.write_bytes(b"audio")
                return CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            if cmd[0] == "ffmpeg":
                Path(cmd[-1]).write_bytes(b"mp3")
                return CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            raise AssertionError(f"Unexpected command: {cmd}")

        with tempfile.TemporaryDirectory() as temp_dir, patch("subprocess.run", side_effect=fake_run):
            result = downloader._download_bilibili_audio_with_curl(
                video_url="https://www.bilibili.com/video/BV123/",
                output_dir=temp_dir,
            )

        self.assertEqual(result.title, "Demo Title")
        self.assertEqual(result.duration, 12)
        self.assertEqual(result.video_id, "BV123")
        self.assertTrue(result.file_path.endswith(".mp3"))
        self.assertEqual(result.cover_url, "https://example.test/cover.jpg")

    def test_bilibili_curl_fallback_downloads_and_merges_video(self):
        downloader = YtdlpDownloader()
        page_html = (
            "<html><script>"
            'window.__INITIAL_STATE__={"videoData":{"bvid":"BV123","cid":456,'
            '"title":"Demo Title","duration":12,"pic":"https://example.test/cover.jpg"}};'
            "(function(){})"
            "</script></html>"
        ).encode()
        playurl_json = json.dumps(
            {
                "code": 0,
                "message": "OK",
                "data": {
                    "dash": {
                        "video": [
                            {
                                "height": 720,
                                "width": 1280,
                                "bandwidth": 800000,
                                "codecs": "avc1.640028",
                                "baseUrl": "https://example.test/video.m4s",
                            }
                        ],
                        "audio": [
                            {
                                "bandwidth": 128000,
                                "baseUrl": "https://example.test/audio.m4s",
                            }
                        ],
                    }
                },
            }
        ).encode()

        def fake_run(cmd, **kwargs):
            if cmd[0] == "curl" and "www.bilibili.com" in cmd[-1]:
                return CompletedProcess(cmd, 0, stdout=page_html, stderr=b"")
            if cmd[0] == "curl" and "api.bilibili.com" in cmd[-1]:
                return CompletedProcess(cmd, 0, stdout=playurl_json, stderr=b"")
            if cmd[0] == "curl" and any("video.m4s" in part for part in cmd):
                output_path = Path(cmd[cmd.index("--output") + 1])
                output_path.write_bytes(b"video")
                return CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            if cmd[0] == "curl" and any("audio.m4s" in part for part in cmd):
                output_path = Path(cmd[cmd.index("--output") + 1])
                output_path.write_bytes(b"audio")
                return CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            if cmd[0] == "ffmpeg":
                Path(cmd[-1]).write_bytes(b"mp4")
                return CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
            raise AssertionError(f"Unexpected command: {cmd}")

        with tempfile.TemporaryDirectory() as temp_dir, patch("subprocess.run", side_effect=fake_run):
            video_path = downloader._download_bilibili_video_with_curl(
                video_url="https://www.bilibili.com/video/BV123/",
                output_dir=temp_dir,
            )
            self.assertTrue(Path(video_path).exists())

        self.assertTrue(video_path.endswith(".mp4"))


class FakeYoutubeDL:
    instances: list["FakeYoutubeDL"] = []
    error: Exception | None = None

    def __init__(self, options):
        self.options = options
        self.extract_calls: list[tuple[str, bool]] = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, video_url: str, download: bool):
        self.extract_calls.append((video_url, download))
        if self.__class__.error:
            raise self.__class__.error

        info = {
            "id": "video-123",
            "title": "Demo video",
            "duration": 42,
            "thumbnail": "https://example.com/cover.jpg",
        }
        if download:
            output_template = self.options["outtmpl"]
            output_path = Path(
                output_template
                .replace("%(id)s", info["id"])
                .replace("%(ext)s", "mp4")
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if self.options.get("postprocessors"):
                output_path = output_path.with_suffix(".mp3")
            output_path.write_bytes(b"media")
        return info


class YtdlpDownloaderYoutubeStabilityTest(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.instances = []
        FakeYoutubeDL.error = None

    @patch("app.downloaders.ytdlp_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_download_extracts_once_and_applies_request_pacing(self):
        downloader = YtdlpDownloader(
            request_sleep_seconds=1.5,
            download_sleep_seconds=3.0,
            max_download_sleep_seconds=6.0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = downloader.download(
                "https://www.youtube.com/watch?v=video-123",
                temp_dir,
            )

        self.assertEqual(len(FakeYoutubeDL.instances), 1)
        instance = FakeYoutubeDL.instances[0]
        self.assertEqual(
            instance.extract_calls,
            [("https://www.youtube.com/watch?v=video-123", True)],
        )
        self.assertEqual(instance.options["sleep_interval_requests"], 1.5)
        self.assertEqual(instance.options["sleep_interval"], 3.0)
        self.assertEqual(instance.options["max_sleep_interval"], 6.0)
        self.assertEqual(result.title, "Demo video")
        self.assertEqual(result.video_id, "video-123")

    @patch("app.downloaders.ytdlp_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_download_video_extracts_once(self):
        downloader = YtdlpDownloader(
            request_sleep_seconds=0,
            download_sleep_seconds=0,
            max_download_sleep_seconds=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = downloader.download_video(
                "https://www.youtube.com/watch?v=video-123",
                temp_dir,
            )
            self.assertTrue(Path(video_path).exists())

        self.assertEqual(len(FakeYoutubeDL.instances), 1)
        self.assertEqual(
            FakeYoutubeDL.instances[0].extract_calls,
            [("https://www.youtube.com/watch?v=video-123", True)],
        )

    @patch("app.downloaders.ytdlp_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_youtube_bot_challenge_is_translated_to_safe_error(self):
        FakeYoutubeDL.error = yt_dlp.utils.DownloadError(
            "Sign in to confirm you’re not a bot. Use --cookies for authentication."
        )
        downloader = YtdlpDownloader()

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(YoutubeAccessBlockedError) as context:
                downloader.download(
                    "https://www.youtube.com/watch?v=video-123",
                    temp_dir,
                )

        message = str(context.exception)
        self.assertIn("YouTube", message)
        self.assertIn("机器人验证", message)
        self.assertIn("稍后重试", message)
        self.assertNotIn("cookies", message.lower())


if __name__ == "__main__":
    unittest.main()
