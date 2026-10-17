"""Public jobs reuse the device pipeline, with no stored cloud session."""
import subprocess
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.models.note import LocalFileRequest
from app.services.cloud_content_identity import content_bearer
from app.services.note_service import NoteService
from app.services.source_note_job import run_source_job
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_model_source import ensure_source
from app.services.transcription_service import TranscriptionService
from app.services.vilab_cloud_service import VILabCloudService
from app.transcribers.vilab_transcriber import VILabTranscriber


class ContentTranscriber(VILabTranscriber):
    def _recognition_bearer(self):
        return content_bearer(self.cloud_user_id)


def artifacts():
    return TaskArtifactService()


def prepare_models(owner, options, needs_stt):
    cloud = VILabCloudService()
    if not settings.vilab_server_url:
        raise HTTPException(503, "内容服务尚未配置云端模型")
    config = cloud.status(owner)
    # Public jobs cannot select device profiles or local inference. Explicit
    # model IDs are checked, never replaced silently with another model.
    config = {**config, "mode": "cloud", "server_url": settings.vilab_server_url,
              "configured": True}
    if options.get("model_name"):
        config["llm_model"] = options["model_name"]
    if options.get("asr_model"):
        config["asr_model"] = options["asr_model"]
    if not config.get("llm_model") or (needs_stt and not config.get("asr_model")):
        defaults = cloud.request(owner, "GET", "/v1/default-models")
        for key in ("llm_model", "asr_model"):
            if not config.get(key):
                config[key] = defaults.get(key, "")
    models = cloud.models(owner)
    cloud._validate_selection(models, config.get("llm_model"), "llm")
    if needs_stt:
        cloud._validate_selection(models, config.get("asr_model"), "asr")
    return config


def freeze(folder, owner, options, needs_stt, config):
    with VILabCloudService().task_snapshot(owner, snapshot=config):
        return ensure_source(folder, owner, {**options, "needs_stt": needs_stt}, allow_capture=True)


def normalize_media(source: Path, target: Path):
    # Never let an uploaded playlist masquerade as a media file and ask ffmpeg
    # to fetch arbitrary URLs. Fix the demuxer and disable network protocols,
    # including nested external references. Downstream only sees canonical WAV.
    with source.open("rb") as stream:
        head = stream.read(32)
    if head[:4] in {b"RIFF", b"RF64"} and head[8:12] == b"WAVE":
        format_name = "wav"
    elif head[4:8] == b"ftyp":
        format_name = "mov"
    elif head.startswith(b"\x1aE\xdf\xa3"):
        format_name = "matroska"
    elif head.startswith(b"fLaC"):
        format_name = "flac"
    elif head.startswith(b"OggS"):
        format_name = "ogg"
    elif head.startswith(b"ID3") or len(head) > 1 and head[0] == 255 and head[1] & 0xE0 == 0xE0:
        format_name = "mp3"
    else:
        raise HTTPException(422, "媒体格式无法安全识别，请导出为 WAV、MP3、MP4 或 WebM")
    limit = settings.content_upload_max_bytes
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-protocol_whitelist", "file,pipe", "-f", format_name,
                        *(["-enable_drefs", "0", "-use_absolute_path", "0"] if format_name == "mov" else []),
                        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", "-fs", str(limit), str(target)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=180, check=True)
    except (OSError, subprocess.SubprocessError):
        target.unlink(missing_ok=True)
        raise HTTPException(422, "媒体准备未完成，原文件仍保留在设备") from None
    if not target.is_file() or target.stat().st_size < 44 or target.stat().st_size >= limit - 64:
        target.unlink(missing_ok=True)
        raise HTTPException(413, "媒体解码后超过服务限制或没有有效音频，未提交转写")


def run_job(task_id, owner, job):
    """BackgroundTasks runs this in a copied request context, not a new queue.

    No auto restart: reserved/accepted receipts are GET-only after interruption.
    A token expiry is terminal for this attempt; no refresh token is requested.
    """
    storage = artifacts()
    folder = storage.find_task_dir(task_id)
    try:
        content_bearer(owner)
        snapshot = job["snapshot"]
        transcriber = (ContentTranscriber(settings.vilab_server_url, "",
                       model=snapshot["asr_model"], cloud_user_id=owner)
                       if job["kind"] == "media" else None)
        service = NoteService(artifact_service=storage,
                              transcription_service=TranscriptionService(transcriber=transcriber))
        if job["kind"] == "document":
            run_source_job(service, task_id, job["source_job"], owner)
        elif job["kind"] == "transcript":
            service.generate_from_transcript(task_id=task_id, user_id=owner,
                transcript=job["transcript"], **job["generation"])
        else:
            target = folder / "media" / "normalized.wav"
            normalize_media(Path(job["path"]), target)
            req = LocalFileRequest(file_path=str(target), **job["generation"])
            storage.write_json(folder / "request.json", {"request": req.model_dump(), "trace": None})
            service.generate_from_file(task_id=task_id, user_id=owner, **req.model_dump(exclude={"workflow"}))
    except Exception:
        # Do not serialize exceptions, tokens or downstream URLs in public jobs.
        current = storage.find_task_dir(task_id) or folder
        if current:
            state = storage.get_status(task_id)
            from app.services.task_failure import recovery_status
            safe = recovery_status(state)
            storage.update_status(current, "failed", "处理未完成，已有资料与原提交已保留，请核验原任务",
                                  retryable=False, **{key: safe[key] for key in ("error_code", "failed_stage") if key in safe})
