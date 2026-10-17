"""Explicit public content allowlist; never register the device note router."""
import hashlib
import re
import stat
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import UploadFile

from app.config import settings
from app.models.note import TaskStatusResponse, NoteResponse
from app.models.source_request import SourceInput, SourceSubmission
from app.services.cloud_content_identity import request_user
from app.services import cloud_content_worker as worker
from app.services.document_source_service import document_text, is_document_url, _public_target
from app.services.source_request_service import SourceRequestService
from app.services.task_failure import recovery_status

router = APIRouter(tags=["cloud-content"])


class ContentOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(None, max_length=500)
    source_type: str = "media"
    workflow: str = "note_organization"
    diarize: bool = False
    speaker_count: int | None = Field(None, ge=1, le=20)
    style: str = Field("detailed", max_length=100)
    summary_mode: str = "default"
    output_language: str | None = None
    extras: str | None = Field(None, max_length=16000)
    model_name: str | None = Field(None, max_length=200)
    asr_model: str | None = Field(None, max_length=200)
    model_profile_id: str | None = None
    stt_profile_id: str | None = None
    # Empty compatibility fields are not credentials. Nonempty overrides fail.
    api_key: str | None = None
    base_url: str | None = None


def options_from(values):
    try:
        options = ContentOptions.model_validate(values)
    except ValidationError:
        raise HTTPException(422, "内容处理选项无效或包含不支持的字段") from None
    if (options.api_key or options.base_url
            or options.model_profile_id not in (None, "", "vilab-cloud")
            or options.stt_profile_id not in (None, "", "vilab-cloud")):
        raise HTTPException(422, "公网内容服务不接受临时凭证、服务地址或设备模型配置")
    if (options.source_type not in {"document", "transcript", "audio", "video", "media"}
            or options.workflow not in {"meeting", "note_organization"}
            or options.summary_mode not in {"default", "oneshot"}
            or options.output_language not in (None, "", "en", "zh-CN")):
        raise HTTPException(422, "来源、流程或输出选项不受支持")
    return options


def operation(request):
    value = request.headers.get("X-VINote-Operation-Id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise HTTPException(422, "请提供并保留本次提交的操作编号")
    return value


def task_folder(owner, task_id):
    if not re.fullmatch(r"[a-f0-9-]{36}", task_id):
        raise HTTPException(404, "Task not found")
    folder = worker.artifacts().find_task_dir(task_id)
    if folder is None:
        raise HTTPException(404, "Task not found")
    root = Path(settings.output_dir).resolve()
    marker = folder / "recording_owner"
    try:
        info = marker.lstat()
        if (folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
                or folder.resolve().parent != root or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or marker.read_text(encoding="utf-8") != owner):
            raise HTTPException(404, "Task not found")
        for name in ("status.json", "result.json", ".task_id"):
            path = folder / name
            if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise HTTPException(404, "Task not found")
        if (folder / ".task_id").is_file() and (folder / ".task_id").read_text(encoding="utf-8").strip() != task_id:
            raise HTTPException(404, "Task not found")
    except (OSError, UnicodeError):
        raise HTTPException(404, "Task not found") from None
    return folder


@router.get("/content-service/capabilities")
def capabilities(response: Response, user=Depends(request_user)):
    response.headers["Cache-Control"] = "no-store"
    from app.services.speaker_diarization_service import SpeakerDiarizationService
    return {"content_service_protocol": 1, "generation": True, "sync": False,
            "protocol": 1, "enabled": True, "bearer_required": True,
            "operation_receipts": 1, "task_owner_required": True,
            "sources": ["public_webpage", "document", "transcript", "audio", "video_upload", "bilibili"],
            "video_url": True, "video_url_platforms": ["bilibili"],
            "video_source_preflight": 1,
            "video_url_reason": "OTHER_VIDEO_PLATFORMS_NOT_SUPPORTED",
            "max_upload_bytes": settings.content_upload_max_bytes,
            "models_configured": bool(settings.vilab_server_url),
            "diarization_available": bool(SpeakerDiarizationService.readiness()["available"])}


def generation_options(options):
    return {"title": options.title, "style": options.style,
            "summary_mode": options.summary_mode, "extras": options.extras,
            "output_language": options.output_language or None,
            "model_profile_id": None, "stt_profile_id": None,
            "model_name": None, "api_key": None, "base_url": None}


class VideoSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=8192)


@router.post("/content-service/video-source")
def video_source(body: VideoSourceRequest, response: Response, user=Depends(request_user)):
    """Read source metadata only; no task, model selection or inference."""
    from app.services.bilibili_source_service import resolve, BilibiliSourceError
    response.headers["Cache-Control"] = "no-store"
    try:
        source = resolve(body.url)
    except BilibiliSourceError as error:
        status_code = 422 if error.code == "VIDEO_SOURCE_INVALID" else 503
        raise HTTPException(status_code, {"code": error.code, "message": str(error)}) from None
    except ValueError as error:
        raise HTTPException(422, "请检查 B 站视频链接与分 P 编号") from None
    except (httpx.HTTPError, OSError):
        raise HTTPException(502, "暂时无法读取视频，请稍后重试") from None
    return {"platform": "bilibili", "url": source.canonical_url,
            "title": source.title, "video_id": source.video_id, "duration": source.duration}


def submit(request, user, source, options, background, *, upload=None, source_job=None, video_url=None):
    receipts = SourceRequestService()
    claim = receipts.reserve(user.user_id, operation(request), SourceSubmission(
        source=source, options=options.model_dump(exclude_none=True)))
    if not claim.created:
        return claim.model_dump(exclude_none=True)
    needs_stt = options.source_type not in {"document", "transcript"}
    config = worker.prepare_models(user.user_id, options.model_dump(), needs_stt)
    if needs_stt and options.diarize:
        from app.services.speaker_diarization_service import SpeakerDiarizationService
        if not SpeakerDiarizationService.readiness()["available"]:
            raise HTTPException(503, "说话人分析尚未就绪，请联系服务管理员；未提交转写")
    storage = worker.artifacts()
    folder = storage.create_task_dir(claim.task_id)
    storage.write_text(folder / "recording_owner", user.user_id)
    storage.write_text(folder / ".task_id", claim.task_id)
    storage.update_status(folder, "preparing", "正在准备内容", retryable=False)
    snapshot = worker.freeze(folder, user.user_id, options.model_dump(), needs_stt, config)
    from app.services.note_origin_service import record_origin
    record_origin(folder, request.headers.get("X-VINote-Client", ""))
    job = {"snapshot": snapshot, "generation": generation_options(options)}
    if video_url is not None:
        job.update(kind="video_url", video_url=video_url)
        job["generation"].update(diarize=options.diarize, speaker_count=options.speaker_count,
                                 workflow=options.workflow)
        storage.write_json(folder / "video_source.json", {"url": video_url, "platform": "bilibili"})
    elif source_job is not None:
        job.update(kind="document", source_job=source_job)
        storage.write_json(folder / "source_job.json", source_job)
    elif options.source_type == "document":
        upload.file.seek(0)
        text = document_text(upload.filename, upload.file.read(20 * 1024 * 1024 + 1))
        title = options.title or Path(upload.filename or "文档").stem
        storage.write_json(folder / "document_text.json", {"title": title, "text": text})
        source_job = {"options": {k: v for k, v in job["generation"].items() if k != "title"}}
        job.update(kind="document", source_job=source_job)
        storage.write_json(folder / "source_job.json", source_job)
    elif options.source_type == "transcript":
        from app.routers.note import _build_transcript_from_upload, _ensure_transcript_extension
        _ensure_transcript_extension(upload.filename)
        upload.file.seek(0)
        transcript = _build_transcript_from_upload(upload.filename, upload.file.read())
        job.update(kind="transcript", transcript=transcript)
    else:
        folder.joinpath("media").mkdir()
        # Client filenames never determine a server path.
        path = folder / "media" / "upload.bin"
        upload.file.seek(0)
        with path.open("xb") as target:
            while block := upload.file.read(65536):
                target.write(block)
        job.update(kind="media", path=str(path))
        job["generation"].update(diarize=options.diarize, speaker_count=options.speaker_count,
                                 workflow=options.workflow)
    accepted = receipts.accept(user.user_id, claim.operation_id, claim.task_id,
                                status="preparing", source_type="file" if options.source_type == "document" else options.source_type)
    background.add_task(worker.run_job, claim.task_id, user.user_id, job)
    return accepted.model_dump(exclude_none=True)


@router.post("/generate")
async def generate(request: Request, background: BackgroundTasks, user=Depends(request_user)):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError()
        url = payload.pop("video_url")
        platform = payload.pop("platform", "auto")
        if platform != "auto" or not isinstance(url, str) or len(url) > 8192:
            raise ValueError()
        parsed = httpx.URL(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.host
                or parsed.username or parsed.password):
            raise ValueError()
        from app.services.bilibili_source_service import is_bilibili_url, validate_input
        video = is_bilibili_url(url)
        if video:
            # Validate syntax before reserving an operation or querying models;
            # retain the submitted URL in its immutable receipt fingerprint.
            validate_input(url)
        options = options_from({**payload, "source_type": "video" if video else "document"})
        if not video and not is_document_url(url):
            raise HTTPException(503, "目前支持 B 站视频及公开网页；其他视频请导入原文件")
        # Numeric/private targets fail before model preparation; each actual
        # extraction hop resolves and pins again via the existing safe fetcher.
        import anyio
        await anyio.to_thread.run_sync(_public_target, url)
    except (ValueError, KeyError, httpx.InvalidURL):
        raise HTTPException(422, "请提供不含凭证的有效公开网页链接") from None
    source_job = {"url": url, "options": {k: v for k, v in generation_options(options).items() if k != "title"}}
    import anyio
    return await anyio.to_thread.run_sync(lambda: submit(request, user, SourceInput(kind="url", url=url),
                                                        options, background,
                                                        source_job=None if video else source_job,
                                                        video_url=url if video else None))


@router.post("/generate_from_upload")
async def upload(request: Request, background: BackgroundTasks, user=Depends(request_user)):
    operation(request)
    async with request.form(max_files=1, max_fields=24) as form:
        if len(form.getlist("file")) != 1 or any(len(form.getlist(key)) != 1 for key in form):
            raise HTTPException(422, "请一次提交一个来源文件和一组明确选项")
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, "请选择来源文件")
        values = {k: v for k, v in form.items() if k != "file"}
        if any(not isinstance(v, str) for v in values.values()):
            raise HTTPException(422, "内容处理选项无效")
        options = options_from(values)
        if file.size is None or not 0 < file.size <= settings.content_upload_max_bytes:
            raise HTTPException(413, "文件为空或超过服务大小限制")
        import anyio

        def stage():
            digest = hashlib.sha256()
            size = 0
            while block := file.file.read(65536):
                size += len(block)
                if size > settings.content_upload_max_bytes:
                    raise HTTPException(413, "文件超过服务大小限制")
                digest.update(block)
            file.file.seek(0)
            source = SourceInput(kind="upload", file_type=Path(file.filename or "source.bin").suffix.lower() or ".bin",
                                 filename=file.filename, size=size, sha256=digest.hexdigest())
            return submit(request, user, source, options, background, upload=file)
        try:
            return await anyio.to_thread.run_sync(stage)
        except ValueError:
            raise HTTPException(422, "来源文件无法读取或格式无效，原文件仍保留在设备") from None


@router.get("/source-requests/{operation_id}")
def receipt(operation_id: str, response: Response, user=Depends(request_user)):
    response.headers["Cache-Control"] = "no-store"
    return SourceRequestService().get(user.user_id, operation_id)


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
def status(task_id: str, response: Response, user=Depends(request_user)):
    task_folder(user.user_id, task_id)
    response.headers["Cache-Control"] = "private, no-store"
    storage = worker.artifacts()
    state = recovery_status(storage.get_status(task_id))
    result = storage.get_result(task_id) if state.get("status") == "success" else None
    body = NoteResponse(task_id=task_id, title=result.get("title", ""), markdown=result.get("markdown", ""),
                        duration=result.get("duration", 0), platform=result.get("platform", ""),
                        video_id=result.get("video_id", ""), summary_mode=result.get("summary_mode", "default")) if result else None
    return TaskStatusResponse(**{k: v for k, v in state.items() if k in TaskStatusResponse.model_fields and k not in {"result", "task_id", "retryable"}},
                              task_id=task_id, result=body, retryable=False)
