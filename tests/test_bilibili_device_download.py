"""Device audio intake and saved-note pipeline; all provider/model I/O is fake."""
from dataclasses import asdict
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import settings
from app.downloaders.ytdlp_downloader import YtdlpDownloader
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services import bilibili_source_service as bili
from app.services.note_service import NoteService, PipelineContext
from app.services.task_artifact_service import TaskArtifactService

BV = "BV12iFezdEZS"
URL = f"https://www.bilibili.com/video/{BV}?p=2"
BYTES = b"\x00\x00\x00\x18ftypM4A original synthetic audio bytes"


@pytest.fixture
def intake(monkeypatch):
    source = bili.BilibiliSource(URL, "分P标题", BV + "_p2", 73,
                                "https://upos-test.bilivideo.com/audio?private-signed-value", 2, 123, 456)
    resolve = Mock(return_value=source)
    targets = []

    def download(item, target, max_bytes=bili.MAX_AUDIO_BYTES):
        assert item is source
        target = Path(target)
        assert not target.exists()
        target.write_bytes(BYTES)
        targets.append(target)
        return target

    downloaded = Mock(side_effect=download)
    monkeypatch.setattr(bili, "resolve", resolve)
    monkeypatch.setattr(bili, "download_audio", downloaded)
    # Any automatic generic download, curl or FFmpeg is a regression.
    forbidden = Mock(side_effect=AssertionError("unexpected generic/subprocess I/O"))
    monkeypatch.setattr("app.downloaders.ytdlp_downloader.yt_dlp.YoutubeDL", forbidden)
    monkeypatch.setattr("app.downloaders.ytdlp_downloader.subprocess.run", forbidden)
    monkeypatch.setattr(YtdlpDownloader, "_download_bilibili_audio_with_curl", forbidden)
    return SimpleNamespace(source=source, resolve=resolve, download=downloaded,
                           targets=targets, forbidden=forbidden)


@pytest.mark.parametrize("url", [URL, f"https://m.bilibili.com/video/{BV}?p=2",
                                 "https://bilibili.com/video/av123?p=2", "https://b23.tv/abcdef"])
def test_device_uses_safe_module_and_preserves_canonical_part(intake, tmp_path, url):
    result = YtdlpDownloader().download(url, str(tmp_path))
    assert Path(result.file_path).read_bytes() == BYTES
    assert Path(result.file_path).suffix == ".m4a"
    assert Path(result.file_path).parent == tmp_path.resolve()
    assert result.video_id == BV + "_p2" and result.duration == 73 and result.title == "分P标题"
    assert result.platform == "bilibili" and result.cover_url is None
    assert result.raw_info["webpage_url"] == URL
    assert result.raw_info["source_identity"]["cid"] == 456
    assert "private-signed-value" not in json.dumps(asdict(result))
    assert "audio_url" not in json.dumps(asdict(result))
    intake.resolve.assert_called_once_with(bili.validate_input(url))
    intake.download.assert_called_once()
    intake.forbidden.assert_not_called()


def test_repeated_explicit_download_does_not_overwrite_or_delete_original(intake, tmp_path):
    original = tmp_path / "existing.m4a"
    original.write_bytes(b"keep original")
    first = YtdlpDownloader().download(URL, str(tmp_path))
    second = YtdlpDownloader().download(URL, str(tmp_path))
    assert first.file_path != second.file_path
    assert Path(first.file_path).read_bytes() == BYTES == Path(second.file_path).read_bytes()
    assert original.read_bytes() == b"keep original"


@pytest.mark.parametrize("error", [bili.BilibiliSourceError("VIDEO_SOURCE_BLOCKED"),
                                  bili.BilibiliSourceError("VIDEO_SOURCE_UNAVAILABLE"),
                                  RuntimeError("TLS unexpected EOF")])
def test_safe_resolution_error_never_falls_back(intake, tmp_path, error):
    intake.resolve.side_effect = error
    folder = tmp_path / "not-created"
    with pytest.raises(type(error)) as exc:
        YtdlpDownloader().download(URL, str(folder))
    assert exc.value is error
    assert not folder.exists()
    intake.download.assert_not_called()
    intake.forbidden.assert_not_called()


def test_cdn_error_never_calls_legacy_downloader(intake, tmp_path):
    intake.download.side_effect = bili.BilibiliSourceError("VIDEO_SOURCE_LIMIT")
    with pytest.raises(bili.BilibiliSourceError) as exc:
        YtdlpDownloader().download(URL, str(tmp_path))
    assert exc.value.code == "VIDEO_SOURCE_LIMIT" and not list(tmp_path.iterdir())
    intake.forbidden.assert_not_called()


@pytest.mark.parametrize("url", ["http://www.bilibili.com/video/" + BV,
                                 "https://user:private@www.bilibili.com/video/" + BV,
                                 "https://www.bilibili.com:444/video/" + BV,
                                 URL.replace(BV, "BVbad"), URL + "&p=1"])
def test_known_bili_host_with_invalid_input_rejected_before_any_download(intake, tmp_path, url):
    folder = tmp_path / "not-created"
    with pytest.raises(bili.BilibiliSourceError):
        YtdlpDownloader().download(url, str(folder))
    intake.resolve.assert_not_called()
    intake.download.assert_not_called()
    intake.forbidden.assert_not_called()
    assert not folder.exists()


@pytest.mark.parametrize("host", ["bilibili.com.evil.test", "evilbilibili.com", "b23.tv.evil.test",
                                  "api.bilibili.com", "other.bilibili.com"])
def test_substring_hosts_cannot_select_bili_safe_or_legacy_path(host):
    assert YtdlpDownloader().detect_platform(f"https://{host}/video/{BV}") != "bilibili"


def test_other_platform_still_uses_existing_ytdlp_behavior(intake, tmp_path, monkeypatch):
    downloader = YtdlpDownloader()
    fallback = Mock(return_value="unchanged non-Bili result")
    monkeypatch.setattr(downloader, "_download_with_ytdlp", fallback)
    url = "https://www.youtube.com/watch?v=example"
    assert downloader.download(url, str(tmp_path)) == "unchanged non-Bili result"
    fallback.assert_called_once_with(video_url=url, output_dir=str(tmp_path), platform="youtube")
    intake.resolve.assert_not_called()


class Transcriber:
    def __init__(self):
        self.paths = []

    def transcribe(self, *, audio_path, save_transcript, **kwargs):
        assert Path(audio_path).read_bytes() == BYTES
        self.paths.append(Path(audio_path))
        transcript = TranscriptResult(language="zh", full_text="仅依据音轨内容",
                                      segments=[TranscriptSegment(0, 1, "仅依据音轨内容")])
        save_transcript(transcript)
        return transcript


class LLM:
    def __init__(self):
        self.calls = []

    def resolve_config(self, **kwargs):
        return SimpleNamespace(model_name="offline-fixture")

    def create_summarizer(self, **kwargs):
        return self

    def summarize(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["segments"][0].text == "仅依据音轨内容"
        return "# 保存的正文\n[00:01]\n[[Screenshot:00:01]]"


@pytest.fixture
def pipeline(intake, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "downloaded")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr("app.services.vilab_cloud_service.VILabCloudService.status",
                        lambda *a, **k: {"mode": "local"})
    frozen = {"version": 1, "owner": "device-user", "mode": "local", "server_url": "",
              "asr_model": "", "llm_model": "", "local_llm_fingerprint": "0" * 64,
              "local_stt_fingerprint": "0" * 64}
    monkeypatch.setattr("app.services.task_model_source.capture_source", lambda *a, **k: frozen)
    forbidden_visual = Mock(side_effect=AssertionError("must not fetch video or render screenshots"))
    screenshots = SimpleNamespace(prepare_local_video=forbidden_visual, inject_screenshots=forbidden_visual)
    media = SimpleNamespace(enrich_markdown=forbidden_visual)
    artifacts = TaskArtifactService(tmp_path / "output")
    transcriber, llm = Transcriber(), LLM()
    service = NoteService(downloader=YtdlpDownloader(), transcription_service=transcriber,
                          llm_service=llm, artifact_service=artifacts,
                          screenshot_service=screenshots, media_service=media)
    return SimpleNamespace(service=service, transcriber=transcriber, llm=llm,
                           artifacts=artifacts, forbidden_visual=forbidden_visual)


@pytest.mark.parametrize("style", ["meeting", "detailed"])
def test_full_mock_device_pipeline_retains_audio_and_saves_without_video_network(intake, pipeline, style):
    result = pipeline.service.generate(URL, "device-task", style=style, user_id="device-user")
    root = Path(result.output_dir)
    assert result.audio_meta.platform == "bilibili" and result.audio_meta.video_id == BV + "_p2"
    assert result.audio_meta.raw_info["webpage_url"] == URL
    assert "Screenshot" not in result.markdown and "保存的正文" in result.markdown
    assert pipeline.artifacts.get_status("device-task")["status"] == "success"
    assert pipeline.artifacts.get_result("device-task")["video_id"] == BV + "_p2"
    retained = pipeline.artifacts.resolve_source_media(root)
    assert retained.read_bytes() == BYTES
    assert retained == Path(result.audio_meta.file_path)
    assert pipeline.transcriber.paths == [retained]
    assert intake.targets[0].read_bytes() == BYTES  # unmodified download also survives
    assert (root / "recording_owner").read_text() == "device-user"
    assert json.loads((root / "source_media.json").read_text())["media_kind"] == "audio"
    assert "private-signed-value" not in (root / "audio_meta.json").read_text(encoding="utf-8")
    assert (root / "note.md").exists() and (root / "transcript.json").exists()
    assert len(pipeline.llm.calls) == 1 and len(pipeline.transcriber.paths) == 1
    pipeline.forbidden_visual.assert_not_called()
    intake.forbidden.assert_not_called()


def test_task_cache_is_get_only_no_second_download_and_keeps_part(intake, pipeline):
    task = pipeline.artifacts.create_task_dir("cache-task")
    (task / "recording_owner").write_text("device-user", encoding="utf-8")
    first = pipeline.service._download_audio(video_url=URL, task_dir=task)
    second = pipeline.service._download_audio(video_url=URL, task_dir=task)
    assert first == second and first.raw_info["source_identity"]["page"] == 2
    intake.resolve.assert_called_once()
    intake.download.assert_called_once()
    assert Path(first.file_path).read_bytes() == BYTES


def test_bili_source_is_not_passed_as_remote_video_to_pipeline(intake, pipeline, monkeypatch):
    called = Mock(return_value="pipeline-result")
    monkeypatch.setattr(pipeline.service, "_run_pipeline", called)
    assert pipeline.service.generate(URL, "capture-task", user_id="device-user") == "pipeline-result"
    assert called.call_args.kwargs["source_video_url"] is None
    assert called.call_args.kwargs["audio_meta"].raw_info["webpage_url"] == URL


def test_historical_bili_context_cannot_trigger_hidden_video_download(pipeline, tmp_path):
    # Defense at the sink: old/recovered contexts may still carry the URL.
    audio = SimpleNamespace(platform="bilibili")
    context = PipelineContext(task_id="legacy", task_dir=tmp_path, audio_meta=audio,
                              style="detailed", summary_mode="default", extras=None,
                              output_language="zh", model_profile_id=None, stt_profile_id=None,
                              model_name=None, api_key=None, base_url=None, user_id="device-user",
                              source_video_url=URL, task_start_time=0, step_timings={})
    transcript = TranscriptResult(language="zh", full_text="text", segments=[])
    assert pipeline.service._enrich_markdown_with_media(context, transcript,
                                                       "正文[[Screenshot:00:01]]") == "正文"
    pipeline.forbidden_visual.assert_not_called()


def test_source_block_stops_before_asr_llm_or_saved_result(intake, pipeline):
    intake.resolve.side_effect = bili.BilibiliSourceError("VIDEO_SOURCE_BLOCKED")
    with pytest.raises(bili.BilibiliSourceError):
        pipeline.service.generate(URL, "blocked-task", user_id="device-user")
    assert not pipeline.transcriber.paths and not pipeline.llm.calls
    assert pipeline.artifacts.get_result("blocked-task") is None
    assert pipeline.artifacts.get_status("blocked-task")["status"] == "failed"
    intake.forbidden.assert_not_called()


@pytest.mark.parametrize("reason", ["unbound_global", "missing_owner", "mismatched_path"])
def test_historical_cache_fails_closed_without_migration_redownload_or_asr(intake, pipeline, tmp_path, reason):
    task_id = "old-cache-task"
    task = pipeline.artifacts.create_task_dir(task_id)
    (task / "recording_owner").write_text("device-user", encoding="utf-8")
    from app.models.audio import AudioDownloadResult
    global_audio = tmp_path / "historical-global.m4a"
    global_audio.write_bytes(BYTES)
    cached = AudioDownloadResult(str(global_audio), "历史标题", 73, BV + "_p2", "bilibili",
                                 raw_info={"webpage_url": URL})
    if reason != "unbound_global":
        retained = pipeline.artifacts.stage_source_media(task, str(global_audio), media_kind="audio")
        if reason == "missing_owner":
            cached.file_path = str(retained)
            (task / "recording_owner").unlink()
    pipeline.artifacts.save_audio_meta(task, cached)
    before = (task / "audio_meta.json").read_bytes()
    # Direct cache check also verifies absent owner before any outer guard can
    # create one. No historical source is changed or upgraded here.
    with pytest.raises(ValueError, match="已有资料已保留"):
        pipeline.service._download_audio(video_url=URL, task_dir=task)
    assert (task / "audio_meta.json").read_bytes() == before
    assert global_audio.read_bytes() == BYTES
    assert not pipeline.transcriber.paths and not pipeline.llm.calls
    intake.resolve.assert_not_called()
    intake.download.assert_not_called()


def test_download_failure_stops_pipeline_before_asr_and_model(intake, pipeline):
    intake.download.side_effect = bili.BilibiliSourceError("VIDEO_SOURCE_UNAVAILABLE")
    with pytest.raises(bili.BilibiliSourceError):
        pipeline.service.generate(URL, "cdn-failed-task", user_id="device-user")
    assert not pipeline.transcriber.paths and not pipeline.llm.calls
    task = pipeline.artifacts.find_task_dir("cdn-failed-task")
    assert not (task / "source_media.json").exists()
    assert not (task / "audio_meta.json").exists()
    assert pipeline.artifacts.get_result("cdn-failed-task") is None
    intake.forbidden.assert_not_called()


def test_retained_audio_source_index_is_owner_task_workflow_bound(intake, pipeline):
    from app.services.task_original_service import TaskOriginalService
    task_id = str(uuid.uuid4())
    result = pipeline.service.generate(URL, task_id, user_id="device-user")
    final = Path(result.output_dir)
    (final / "request.json").write_text(json.dumps({"request": {
        "workflow": "note_organization", "title": "分P原音轨", "video_url": URL}}), encoding="utf-8")
    index = TaskOriginalService()
    index.register("device-user", final, "分P原音轨.m4a")
    receipt = json.loads((final / "source_original.json").read_text(encoding="utf-8"))
    assert receipt["owner"] == "device-user" and receipt["task_id"] == task_id
    assert receipt["workflow"] == "note_organization"
    assert index.info("another-user", final) is None
    info, source = index.get("device-user", "task:" + task_id)
    assert info["task_id"] == task_id and source.read_bytes() == BYTES
    assert result.audio_meta.raw_info["webpage_url"] == URL
    # Wrong identity in an existing index is rejected, never repaired by guess.
    receipt["task_id"] = str(uuid.uuid4())
    (final / "source_original.json").write_text(json.dumps(receipt), encoding="utf-8")
    assert index.info("device-user", final) is None
    assert source.read_bytes() == BYTES
