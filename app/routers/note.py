"""
Note generation API routes.
"""
from app.services.note_origin_service import record_origin
import json
import hashlib
import logging
import math
import re
import uuid
import threading
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.llm.prompts import STYLE_MAP
from app.models.auth import AuthenticatedUser
from app.models.note import LocalFileRequest, NoteRequest, NoteResponse, SummaryMode, TaskStatusResponse
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.generation_auth_service import (
    get_generation_user as get_current_user,
    get_optional_generation_user as get_optional_current_user,
)
from app.services.audio_normalizer import normalize_audio_for_transcription
from app.services.note_service import NoteService
from app.services.task_model_source import ensure_source
from app.services.document_source_service import document_text, is_document_url, MAX_BYTES
from app.services.source_note_job import run_source_job
from app.models.source_request import SourceInput, SourceSubmission, SourceRequestReceipt
from app.services.source_request_service import SourceRequestService
from app.services.tracing_service import DesktopTraceContext, desktop_trace

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notes"])
_note_service = NoteService()
_FILE_TASK_LOCK = threading.RLock()
_ACTIVE_FILE_TASKS: set[str] = set()
_UPLOADING_MEETINGS: set[str] = set()
_source_requests = SourceRequestService()


def _reserve_source(request, user, source, options, *, task_id=None):
    operation = request.headers.get("X-VINote-Operation-Id")
    if operation is None:
        return None  # Existing clients keep their historical submission behavior.
    if not user:
        raise HTTPException(401, "请登录后提交可恢复的来源任务")
    if options.get("api_key"):
        raise HTTPException(400, "请使用已保存的模型配置，不支持临时密钥")
    # Absent new fields must not alter fingerprints of historical submissions.
    options = {key: value for key, value in options.items() if key != "asr_model" or value is not None}
    return _source_requests.reserve(user.user_id, operation,
        SourceSubmission(source=source, options=options), task_id=task_id)


def _accept_source(user, claim, result):
    if claim is None:
        return result
    receipt = _source_requests.accept(user.user_id, claim.operation_id, claim.task_id,
        status=result["status"], source_type=result.get("source_type"))
    return {**result, **receipt.model_dump(exclude_none=True)}


def _document_source(filename, content, retained_id=None):
    sha = hashlib.sha256(content).hexdigest()
    values = dict(file_type=Path(filename or "").suffix.lower(), filename=filename,
                  size=len(content), sha256=sha)
    return (SourceInput(kind="retained_file", retained_file_id=retained_id,
                        retained_file_version=sha, **values) if retained_id
            else SourceInput(kind="upload", **values))


from app.services.task_new_generation import NewGenerationConfirmation, NewGenerationService
from app.services.task_generation_context import frozen_generation_context


@router.get("/task/{task_id}/new-generation-context")
def new_generation_context(task_id: str, response: Response, user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return frozen_generation_context(user.user_id, task_id, active=task_id in _ACTIVE_FILE_TASKS)


@router.post("/task/{task_id}/new-generation", response_model=SourceRequestReceipt)
def accept_new_generation(task_id: str, body: NewGenerationConfirmation,
                          background_tasks: BackgroundTasks, response: Response,
                          user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return NewGenerationService(_source_requests).accept(user.user_id, task_id, body,
        background_tasks, _run_task_from_file, active=task_id in _ACTIVE_FILE_TASKS)


@router.get("/source-requests/{operation_id}", response_model=SourceRequestReceipt)
def source_receipt(operation_id: str, response: Response, user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return _source_requests.get(user.user_id, operation_id)

_ALLOWED_OUTPUT_LANGUAGES = {"en", "zh-CN"}
_ALLOWED_SUMMARY_MODES = {"default", "accurate", "oneshot"}
_ALLOWED_MEDIA_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".aac",
    ".opus",
    ".webm",
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".m4v",
    ".ts",
    ".mts",
    ".flv",
    ".3gp",
    ".mpg",
    ".mpeg",
    ".wmv",
}
_ALLOWED_TRANSCRIPT_EXTENSIONS = {".txt", ".vtt", ".srt", ".json", ".md"}
def _is_desktop_request(request: Request) -> bool:
    return request.headers.get("X-VINote-Client", "").strip().lower() == "desktop"


def _desktop_trace_context(
    request: Request,
    *,
    workflow: str,
    source: str,
    media_type: str,
    title: str | None = None,
    filename: str | None = None,
    size_bytes: int | None = None,
    url: str | None = None,
    summary_mode: str = "default",
    output_language: str | None = None,
    meeting_session_id: str | None = None,
    meeting_mode: str | None = None,
    meeting_type: str | None = None,
) -> DesktopTraceContext | None:
    if not _is_desktop_request(request):
        return None
    normalized_workflow = "meeting" if workflow == "meeting" else "note_organization"
    payload = {
        "workflow": normalized_workflow,
        "source": source,
        "media_type": media_type,
        "title": title or "",
        "summary_mode": summary_mode,
        "output_language": output_language or "",
    }
    if filename:
        payload["filename"] = Path(filename).name
        payload["format"] = Path(filename).suffix.lower().lstrip(".")
    if size_bytes is not None:
        payload["size_bytes"] = size_bytes
    if url:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url)
        payload["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        payload["platform"] = parts.netloc.lower()
    if meeting_mode in {"recording", "minutes"}:
        payload["meeting_mode"] = meeting_mode
    if meeting_type in {"audio", "video"}:
        payload["meeting_type"] = meeting_type
    if normalized_workflow == "meeting" and meeting_session_id:
        payload["recording_id"] = meeting_session_id.strip()[:128]
    return DesktopTraceContext(
        workflow=normalized_workflow,
        source=source,
        media_type=media_type,
        client_version=request.headers.get("X-VINote-Client-Version", ""),
        channel=settings.langfuse_environment,
        session_id=(meeting_session_id or "").strip()[:128],
        input=payload,
    )


def _coerce_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_string(value, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _normalize_source_type(value: str | None) -> str:
    normalized = (value or "media").strip().lower()
    if normalized in {"media", ""}:
        return "audio"
    if normalized in {"audio", "video", "transcript", "document"}:
        return normalized
    raise ValueError("Invalid source_type. Allowed values are audio, video, transcript.")


def _normalize_summary_mode(value: str) -> SummaryMode:
    normalized = (value or "default").strip().lower()
    if normalized not in _ALLOWED_SUMMARY_MODES:
        raise ValueError("Invalid summary_mode. Allowed: default, accurate, oneshot.")
    return normalized  # type: ignore[return-value]


def _normalize_output_language(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized not in _ALLOWED_OUTPUT_LANGUAGES:
        raise ValueError("Invalid output_language. Allowed: en, zh-CN.")
    return normalized


def _sanitize_filename(value: str | None) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", (value or "").strip())
    safe = re.sub(r"_+", "_", safe).strip("._")
    return safe or "upload"


def _build_upload_path(task_id: str, source_type: str, filename: str | None) -> Path:
    uploads_dir = settings.data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    sanitized_name = _sanitize_filename(filename)
    file_suffix = Path(sanitized_name).suffix.lower()
    stem = Path(sanitized_name).stem
    if not file_suffix:
        file_suffix = ".bin"
    if not stem:
        stem = task_id
    file_name = f"{task_id}_{source_type}_{stem}{file_suffix}"
    return uploads_dir / file_name


def _ensure_media_extension(source_type: str, filename: str | None):
    if source_type == "transcript":
        return
    ext = Path(filename or "").suffix.lower()
    if ext and ext not in _ALLOWED_MEDIA_EXTENSIONS:
        raise ValueError(f"Unsupported media format: {ext}")


def _ensure_transcript_extension(filename: str | None):
    ext = Path(filename or "").suffix.lower()
    if ext and ext not in _ALLOWED_TRANSCRIPT_EXTENSIONS:
        raise ValueError(f"Unsupported transcript format: {ext}")


def _parse_timestamp(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    if not normalized:
        return 0.0
    parts = normalized.split(":")
    if len(parts) == 3:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return max(0.0, hours * 3600 + minutes * 60 + seconds)
    if len(parts) == 2:
        minutes = float(parts[0])
        seconds = float(parts[1])
        return max(0.0, minutes * 60 + seconds)
    return float(normalized)


def _parse_timestamped_segments(raw_text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    lines = raw_text.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.isdigit():
            index += 1
            if index >= len(lines):
                break
            line = lines[index].strip()
            if not line:
                continue
        if "-->" not in line:
            index += 1
            continue

        try:
            start_text, end_text = [part.strip() for part in line.split("-->", 1)]
            start_text = start_text.split(" ", 1)[0].strip()
            end_text = end_text.split(" ", 1)[0].strip()
            start = _parse_timestamp(start_text)
            end = _parse_timestamp(end_text)
        except ValueError:
            index += 1
            continue

        index += 1
        text_lines: list[str] = []
        while index < len(lines):
            current = lines[index].strip()
            if not current:
                break
            if current.startswith("NOTE") and " --> " not in current:
                break
            text_lines.append(current)
            index += 1

        text = " ".join(text_lines).strip()
        if text:
            if end < start:
                end = start
            segments.append(TranscriptSegment(start=start, end=end, text=text))
        index += 1
    return segments


def _build_transcript_segments(segment_values: list[object]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for segment_value in segment_values:
        if not isinstance(segment_value, dict):
            continue
        text = _coerce_string(segment_value.get("text"), "")
        if not text:
            continue
        start = _coerce_float(segment_value.get("start"), 0.0)
        end = _coerce_float(segment_value.get("end"), start)
        if end < start:
            end = start
        segments.append(
            TranscriptSegment(
                start=start,
                end=end,
                text=text,
                raw_text=_coerce_string(segment_value.get("raw_text"), "") or None,
                cleaned_text=_coerce_string(segment_value.get("cleaned_text"), "") or None,
                speaker_id=_coerce_string(segment_value.get("speaker_id"), "") or None,
                speaker_label=_coerce_string(segment_value.get("speaker_label"), "") or None,
            )
        )
    return segments


def _build_transcript_from_json(raw_text: str, filename: str | None) -> TranscriptResult:
    data = json.loads(raw_text)
    language: str | None = None
    segments: list[TranscriptSegment] = []
    full_text = ""
    metadata: dict = {}

    if isinstance(data, dict):
        language = _coerce_string(data.get("language"), "") or None
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        segment_values = data.get("segments")
        if isinstance(segment_values, list):
            segments = _build_transcript_segments(segment_values)
            if "full_text" in data:
                full_text = _coerce_string(data.get("full_text"), "")
        elif "text" in data and isinstance(data.get("text"), str):
            full_text = _coerce_string(data.get("text"), "")
    elif isinstance(data, list):
        segments = _build_transcript_segments(data)
        full_text = " ".join(segment.text for segment in segments)
    else:
        raise ValueError("Invalid JSON transcript format.")

    if not full_text:
        full_text = "\n".join(segment.text for segment in segments)
    if not segments and not full_text:
        raise ValueError("No transcript segments found in JSON.")
    if not full_text and not segments:
        raise ValueError("JSON transcript is empty.")

    return TranscriptResult(language=language, full_text=full_text, segments=segments, metadata=metadata)


def _build_transcript_from_text(raw_text: str) -> TranscriptResult:
    content = raw_text.strip()
    if not content:
        raise ValueError("Transcript file is empty.")
    segment = TranscriptSegment(start=0.0, end=0.0, text=content)
    return TranscriptResult(language=None, full_text=content, segments=[segment])


def _build_transcript_from_upload(file_name: str | None, file_bytes: bytes) -> TranscriptResult:
    raw_text = file_bytes.decode("utf-8", errors="replace").strip()
    if not raw_text:
        raise ValueError("Uploaded transcript is empty.")

    ext = Path(file_name or "").suffix.lower()
    if ext == ".json":
        try:
            return _build_transcript_from_json(raw_text, file_name)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON transcript: {exc}") from exc

    if ext in {".srt", ".vtt"}:
        segments = _parse_timestamped_segments(raw_text)
        if not segments:
            raise ValueError("No timestamped segments found in subtitle file.")
        return TranscriptResult(
            language="en",
            full_text="\n".join(segment.text for segment in segments),
            segments=segments,
        )

    # Try best-effort subtitle parsing for .txt with SRT-like blocks.
    segments = _parse_timestamped_segments(raw_text)
    if segments:
        return TranscriptResult(
            language="en",
            full_text="\n".join(segment.text for segment in segments),
            segments=segments,
        )

    return _build_transcript_from_text(raw_text)


def _build_note_request_fields(
    *,
    file_path: str,
    title: str | None,
    style: str | None,
    summary_mode: str,
    extras: str | None,
    output_language: str | None,
    model_profile_id: str | None,
    stt_profile_id: str | None,
    model_name: str | None,
    api_key: str | None,
    base_url: str | None,
    diarize: bool = False,
    speaker_count: int | None = None,
    workflow: str = "note_organization",
    asr_model: str | None = None,
) -> LocalFileRequest:
    return LocalFileRequest(
        workflow="meeting" if workflow == "meeting" else "note_organization",
        file_path=file_path,
        diarize=diarize,
        speaker_count=speaker_count,
        title=title,
        style=style or "meeting",
        summary_mode=summary_mode,
        extras=extras,
        output_language=output_language,
        model_profile_id=model_profile_id,
        stt_profile_id=stt_profile_id,
        model_name=model_name,
        asr_model=asr_model,
        api_key=api_key,
        base_url=base_url,
    )


@router.post("/generate")
def generate_note_async(
    req: NoteRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    if req.workflow == "note_organization" and is_document_url(req.video_url):
        job = {"url": req.video_url, "options": req.model_dump(exclude={"video_url", "workflow", "platform", "diarize", "speaker_count", "style"})}
        claim = _reserve_source(request, user, SourceInput(kind="url", url=req.video_url), job["options"])
        if claim and not claim.created:
            return claim.model_dump(exclude_none=True)
        result = _queue_source_job(claim.task_id if claim else task_id, job, background_tasks, user, request)
        return _accept_source(user, claim, result)
    from urllib.parse import urlsplit
    from app.services.bilibili_source_service import INPUT_HOSTS, validate_input
    try:
        parsed = urlsplit(req.video_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("请提供有效且不含账号密码的视频链接")
        if parsed.hostname in INPUT_HOSTS:
            req = req.model_copy(update={"video_url": validate_input(req.video_url)})
    except ValueError as exc:
        raise HTTPException(400, "请提供有效且不含账号密码的视频链接，并检查分P编号") from exc
    trace_context = _desktop_trace_context(
        request, workflow=req.workflow, source="url", media_type="video",
        title=None, url=req.video_url, summary_mode=req.summary_mode,
        output_language=req.output_language,
    )
    if trace_context is not None and req.workflow == "meeting":
        req = req.model_copy(update={"diarize": True, "speaker_count": None})
    req = req.model_copy(update={"style": req.style or "detailed"})
    # Fingerprint the actual worker options, including desktop overrides. Only
    # a newly reserved claim may publish a new pending task or queue work.
    claim = _reserve_source(request, user, SourceInput(kind="url", url=req.video_url),
                            req.model_dump(exclude={"video_url"}))
    if claim and not claim.created:
        return claim.model_dump(exclude_none=True)
    task_id = claim.task_id if claim else task_id
    artifacts = _note_service.artifact_service
    folder = artifacts.create_task_dir(task_id)
    owner_path = folder / "recording_owner"
    if owner_path.is_symlink() or (owner_path.exists() and
            owner_path.read_text(encoding="utf-8") != (user.user_id if user else None)):
        raise HTTPException(404, "Task not found")
    if user:
        owner_path.write_text(user.user_id, encoding="utf-8")
    record_origin(folder, request.headers.get("X-VINote-Client", ""))
    # Do not capture models or write request.json here: capture may perform a
    # slow catalog request, and the worker's frozen-model guard still owns it.
    artifacts.update_status(folder, "pending", "任务已提交，正在准备来源…", retryable=False)
    result = _accept_source(user, claim,
                            {"task_id": task_id, "status": "pending", "source_type": "video",
                             "message": "Task submitted"})
    background_tasks.add_task(_run_task, task_id=task_id, req=req,
                              user_id=user.user_id if user else None,
                              trace_context=trace_context)
    return result


@router.post("/generate_sync", response_model=NoteResponse)
def generate_note_sync(
    req: NoteRequest,
    request: Request,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    try:
        trace_context = _desktop_trace_context(
            request, workflow=req.workflow, source="url", media_type="video",
            url=req.video_url, summary_mode=req.summary_mode,
            output_language=req.output_language,
        )
        effective_diarize = req.diarize or (trace_context is not None and req.workflow == "meeting")
        with desktop_trace(trace_context):
            result = _note_service.generate(
                video_url=req.video_url, task_id=task_id, platform=req.platform,
                style=req.style or "detailed", summary_mode=req.summary_mode,
                extras=req.extras, output_language=req.output_language,
                model_profile_id=req.model_profile_id, stt_profile_id=req.stt_profile_id,
                **({"asr_model": req.asr_model} if req.asr_model is not None else {}),
                model_name=req.model_name, api_key=req.api_key, base_url=req.base_url,
                user_id=user.user_id if user else None,
                diarize=effective_diarize, speaker_count=req.speaker_count,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] generate_sync failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return NoteResponse(
        task_id=task_id,
        title=result.audio_meta.title,
        markdown=result.markdown,
        duration=result.audio_meta.duration,
        platform=result.audio_meta.platform,
        video_id=result.audio_meta.video_id,
        summary_mode=result.summary_mode,
    )


def _require_recording_access(task_id: str, user: AuthenticatedUser | None):
    folder = _note_service.artifact_service.find_task_dir(task_id)
    owner_path = folder / "recording_owner" if folder else None
    if not owner_path or not owner_path.exists():
        return
    if user and not owner_path.is_symlink() and owner_path.read_text(encoding="utf-8") == user.user_id:
        return
    if user:
        from app.services.note_repository import NoteRepository
        if NoteRepository().can_access_task(user.user_id, task_id):
            return
    raise HTTPException(404, "Task not found")


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, user: AuthenticatedUser | None = Depends(get_optional_current_user)):
    _require_recording_access(task_id, user)
    status_data = _note_service.get_status(task_id)
    from app.services.task_failure import recovery_status
    status_data = recovery_status(status_data)
    status = status_data.get("status", "not_found")
    message = status_data.get("message", "")
    result = None
    if status == "success":
        result_data = _note_service.get_result(task_id)
        if result_data:
            result = NoteResponse(
                task_id=task_id,
                title=result_data.get("title", ""),
                markdown=result_data.get("markdown", ""),
                duration=result_data.get("duration", 0),
                platform=result_data.get("platform", ""),
                video_id=result_data.get("video_id", ""),
                summary_mode=result_data.get("summary_mode", "default"),
            )
    return TaskStatusResponse(
        task_id=task_id, status=status, message=message, result=result,
        langfuse_trace_id=status_data.get("langfuse_trace_id"),
        stage=status_data.get("stage"), progress=status_data.get("progress"),
        processed_seconds=status_data.get("processed_seconds"),
        received_seconds=status_data.get("received_seconds"),
        speaker_detection_progress=status_data.get("speaker_detection_progress"),
        speaker_analysis_ready=status_data.get("speaker_analysis_ready"),
        total_seconds=status_data.get("total_seconds"),
        eta_seconds=status_data.get("eta_seconds"),
        updated_at=status_data.get("updated_at"), retryable=status_data.get("retryable"),
        error_code=status_data.get("error_code"),
        failed_stage=status_data.get("failed_stage"), attempt=status_data.get("attempt"),
    )


@router.get("/task/{task_id}/model-confirmation")
def task_model_confirmation(task_id: str, user=Depends(get_current_user)):
    """Read owner-validated recovery context; this never writes or starts generation."""
    from app.services.task_model_source import SNAPSHOT_FILE, capture_source
    from app.services.vilab_cloud_service import VILabCloudService
    artifacts = _note_service.artifact_service
    folder = artifacts.find_task_dir(task_id)
    if not folder or not (folder / "recording_owner").exists() or (folder / "recording_owner").read_text(encoding="utf-8") != user.user_id:
        raise HTTPException(404, "Task not found")
    status = artifacts.get_status(task_id)
    if task_id in _ACTIVE_FILE_TASKS or status.get("status") not in {"failed", "error"}:
        raise HTTPException(409, "原任务正在处理或已完成，请先查询原任务状态")
    if (folder / "source_job.json").exists():
        job = json.loads((folder / "source_job.json").read_text(encoding="utf-8"))
        options = dict(job.get("options", {}), needs_stt=False)
        title = "原文档或链接"
        if (folder / "document_text.json").exists():
            title = json.loads((folder / "document_text.json").read_text(encoding="utf-8")).get("title") or title
        source_type = "document"
    else:
        source = artifacts.resolve_source_media(folder)
        if not source or not (folder / "request.json").exists():
            raise HTTPException(409, "原任务缺少可恢复来源，请保留原件并查看处理历史")
        options = json.loads((folder / "request.json").read_text(encoding="utf-8"))["request"]
        title = options.get("title") or source.name
        source_type = "media"
    context = {"task_id": task_id, "source": {"title": title, "type": source_type}}
    if (folder / SNAPSHOT_FILE).exists():
        ensure_source(folder, user.user_id, options)
        return {**context, "requires_confirmation": False}
    selection = capture_source(user.user_id, options)
    if selection["mode"] != "cloud":
        raise HTTPException(409, "原任务缺少本地模型快照，请保留原件并另建明确确认的生成操作")
    service = VILabCloudService()
    with service.task_snapshot(user.user_id, snapshot=selection):
        models = service.models(user.user_id)
    allowed = True
    for key, kind in (("asr_model", "asr"), ("llm_model", "llm")):
        try:
            service._validate_selection(models, selection[key], kind)
        except HTTPException:
            allowed = False
    return {**context, "requires_confirmation": True, "can_confirm": allowed,
            "selection": {key: selection[key] for key in ("mode", "server_url", "asr_model", "llm_model")}}


@router.post("/task/{task_id}/retry")
def retry_media_task(task_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user),
                     model_confirmation: dict | None = Body(default=None)):
    if model_confirmation is not None and not isinstance(model_confirmation, dict):
        model_confirmation = None
    artifacts = _note_service.artifact_service
    with _FILE_TASK_LOCK:
        folder = artifacts.find_task_dir(task_id)
        if not folder or not (folder / "recording_owner").exists() or (folder / "recording_owner").read_text(encoding="utf-8") != user.user_id:
            raise HTTPException(404, "Task not found")
        if (folder / "new_generation.json").exists():
            raise HTTPException(409, {"code": "independent_operation_query_only",
                "message": "本次独立提交只能查询原任务，不会重复执行。"})
        status = artifacts.get_status(task_id)
        if task_id in _ACTIVE_FILE_TASKS or status.get("status") == "success":
            return {"task_id": task_id, "status": status["status"]}
        from app.services.task_failure import recovery_status
        status = recovery_status(status)
        if status.get("retryable") is False:
            raise HTTPException(409, {"code": status.get("error_code") or "retry_not_confirmed",
                "message": "原任务尚不能安全重试，请查询原结果；原文件已保留。"})
        if (folder / "source_job.json").exists():
            job = json.loads((folder / "source_job.json").read_text(encoding="utf-8"))
            ensure_source(folder, user.user_id, dict(job.get("options", {}), needs_stt=False), confirmation=model_confirmation)
            artifacts.update_status(folder, "preparing", "正在恢复笔记处理…", retryable=True)
            _ACTIVE_FILE_TASKS.add(task_id)
            background_tasks.add_task(_run_source_job, task_id, job, user.user_id)
            return {"task_id": task_id, "status": "preparing"}
        source = artifacts.resolve_source_media(folder)
        if not source or not (folder / "request.json").exists():
            raise HTTPException(409, "原任务缺少可恢复信息，请保留本地录制。")
        saved = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        req = LocalFileRequest(**{**saved["request"], "file_path": str(source)})
        ensure_source(folder, user.user_id, req.model_dump(), confirmation=model_confirmation)
        trace = DesktopTraceContext(**saved["trace"]) if saved.get("trace") else None
        if trace:
            trace = replace(trace, input={**(trace.input or {}),
                            "retry_attempt": (status.get("attempt") or 1) + 1})
        artifacts.update_status(folder, "uploaded", "正在恢复会后处理", attempt=(status.get("attempt") or 1) + 1)
        _ACTIVE_FILE_TASKS.add(task_id)
        background_tasks.add_task(_run_task_from_file, task_id, req, user.user_id, trace)
        return {"task_id": task_id, "status": "uploaded"}


@router.get("/task/{task_id}/artifacts/{asset_path:path}", include_in_schema=False)
def get_task_artifact(task_id: str, asset_path: str, user: AuthenticatedUser | None = Depends(get_optional_current_user), playback: bool = False):
    _require_recording_access(task_id, user)
    task_dir = _note_service.artifact_service.find_task_dir(task_id)
    if not task_dir:
        raise HTTPException(status_code=404, detail="Task not found")

    normalized_parts = Path(asset_path).parts
    if not normalized_parts or normalized_parts[0] not in {"screenshots", "media"}:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if (task_dir / "source_reference.json").exists() and normalized_parts[0] == "media":
        source = _note_service.artifact_service.resolve_source_media(task_dir)
        if source and asset_path == "media/" + source.name:
            if playback:
                from app.services.media_playback_service import playback_file
                return FileResponse(playback_file(source), headers={"Cache-Control": "private, no-store"})
            return FileResponse(source)
        raise HTTPException(404, "Artifact not found")

    requested_path = (task_dir / asset_path).resolve()
    task_root = task_dir.resolve()
    if task_root not in requested_path.parents and requested_path != task_root:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not requested_path.exists() or not requested_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    if playback and normalized_parts[0] == "media":
        from app.services.media_playback_service import playback_file
        return FileResponse(playback_file(requested_path), headers={"Cache-Control": "private, no-store"})
    return FileResponse(Path(requested_path))


@router.get("/meeting-capabilities")
def meeting_capabilities(user: AuthenticatedUser = Depends(get_current_user)):
    from app.services.speaker_diarization_service import SpeakerDiarizationService
    return {"diarization": SpeakerDiarizationService.readiness()}


@router.get("/styles")
def get_styles():
    return {"styles": [{"value": key, "description": value} for key, value in STYLE_MAP.items()]}


@router.post("/generate_from_file", response_model=dict)
def generate_from_file_async(
    req: LocalFileRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    trace_context = _desktop_trace_context(
        request, workflow=req.workflow, source="local_file", media_type="audio",
        title=req.title, filename=req.file_path, summary_mode=req.summary_mode,
        output_language=req.output_language,
    )
    if trace_context is not None:
        req = req.model_copy(update={"diarize": True, "speaker_count": None})
    task_dir = _note_service.artifact_service.create_task_dir(task_id)
    _persist_file_request(task_dir, req, user.user_id if user else None, trace_context)
    background_tasks.add_task(
        _run_task_from_file,
        task_id=task_id,
        req=req,
        user_id=user.user_id if user else None,
        trace_context=trace_context,
    )
    return {"task_id": task_id, "status": "pending", "message": "Task submitted"}


@router.post("/generate_from_file_sync", response_model=NoteResponse)
def generate_from_file_sync(
    req: LocalFileRequest,
    request: Request,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    try:
        trace_context = _desktop_trace_context(
            request, workflow=req.workflow, source="local_file", media_type="audio",
            title=req.title, filename=req.file_path, summary_mode=req.summary_mode,
            output_language=req.output_language,
        )
        effective_diarize = req.diarize or trace_context is not None
        with desktop_trace(trace_context):
            result = _note_service.generate_from_file(
                file_path=req.file_path,
                diarize=effective_diarize,
                speaker_count=req.speaker_count,
                task_id=task_id,
                title=req.title,
                style=req.style or "meeting",
                summary_mode=req.summary_mode,
                extras=req.extras,
                output_language=req.output_language,
                model_profile_id=req.model_profile_id,
                stt_profile_id=req.stt_profile_id,
                **({"asr_model": req.asr_model} if req.asr_model is not None else {}),
                model_name=req.model_name,
                api_key=req.api_key,
                base_url=req.base_url,
                user_id=user.user_id if user else None,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] generate_from_file_sync failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return NoteResponse(
        task_id=task_id,
        title=result.audio_meta.title,
        markdown=result.markdown,
        duration=result.audio_meta.duration,
        platform=result.audio_meta.platform,
        video_id=result.audio_meta.video_id,
        summary_mode=result.summary_mode,
    )


@router.post("/generate_from_upload", response_model=dict)
async def generate_from_upload(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    source_type: str = Form("media"),
    diarize: bool = Form(False),
    speaker_count: int | None = Form(None, ge=1, le=20),
    title: str | None = Form(None),
    style: str | None = Form("meeting"),
    summary_mode: str = Form("default"),
    extras: str | None = Form(None),
    output_language: str | None = Form(None),
    model_profile_id: str | None = Form(None),
    stt_profile_id: str | None = Form(None),
    model_name: str | None = Form(None),
    asr_model: Annotated[str | None, Form(max_length=200)] = None,
    api_key: str | None = Form(None),
    base_url: str | None = Form(None),
    workflow: str = Form("note_organization"),
    trace_source: str = Form("local_file"),
    meeting_session_id: str | None = Form(None),
    meeting_mode: str | None = Form(None),
    meeting_type: str | None = Form(None),
    local_file_id: str | None = Form(None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    try:
        normalized_source_type = _normalize_source_type(source_type)
        normalized_summary_mode = _normalize_summary_mode(summary_mode)
        normalized_output_language = _normalize_output_language(output_language)
        desktop_request = _is_desktop_request(request)
        diarize = diarize or (desktop_request and normalized_source_type not in {"transcript", "document"})
        if desktop_request:
            speaker_count = None
        if diarize and normalized_source_type not in {"transcript", "document"}:
            from app.services.speaker_diarization_service import SpeakerDiarizationService
            SpeakerDiarizationService.require_ready()
        task_id = str(uuid.uuid4())

        if normalized_source_type == "document":
            def queue_document(filename, content, retained_id=None):
                text = document_text(filename, content)
                job = {"options": dict(summary_mode=normalized_summary_mode, output_language=normalized_output_language,
                    extras=extras, model_profile_id=model_profile_id, stt_profile_id=stt_profile_id,
                    asr_model=asr_model, model_name=model_name, api_key=api_key, base_url=base_url)}
                # Never persist ad-hoc API keys in recovery artifacts.
                if api_key:
                    raise ValueError("文档处理请使用已保存的模型配置，不支持临时密钥")
                resolved_title = title or Path(filename or "文档").stem
                claim = _reserve_source(request, user, _document_source(filename, content, retained_id),
                    {**job["options"], "title": resolved_title})
                if claim and not claim.created:
                    return claim.model_dump(exclude_none=True)
                result = _queue_source_job(claim.task_id if claim else task_id, job, background_tasks, user, request,
                    {"title": resolved_title, "text": text})
                return _accept_source(user, claim, result)

            # Only the document branch accepts a registered device-local original.
            # Resolve it by owner, and keep its lease until the task is attached.
            if isinstance(local_file_id, str) and local_file_id:
                if not user:
                    raise HTTPException(401, "请登录后整理文件库文档")
                from app.services.local_file_service import DOCUMENT, LocalFileService
                local_files = LocalFileService()
                with local_files.generation_lease(user.user_id, local_file_id):
                    info, path = local_files.get(user.user_id, local_file_id)
                    if path.suffix.lower() not in DOCUMENT:
                        raise HTTPException(422, "请选择文件库中的 PDF 或 DOCX 文档")
                    if info["task_id"] and request.headers.get("X-VINote-Operation-Id") is None:
                        status = _note_service.artifact_service.get_status(info["task_id"]).get("status")
                        if status not in {"failed", "error", "not_found"}:
                            return {"task_id": info["task_id"], "status": status, "source_type": "file"}
                        return {**retry_media_task(info["task_id"], background_tasks, user), "source_type": "file"}
                    with path.open("rb") as original:
                        content = original.read(MAX_BYTES + 1)
                    if len(content) > MAX_BYTES:
                        raise ValueError("PDF 和 Word 文件不能超过 20 MB")
                    if info["task_id"]:
                        claim = _reserve_source(request, user, _document_source(info["filename"], content, local_file_id),
                            dict(summary_mode=normalized_summary_mode, output_language=normalized_output_language,
                                 extras=extras, model_profile_id=model_profile_id, stt_profile_id=stt_profile_id,
                                 asr_model=asr_model, model_name=model_name, api_key=api_key, base_url=base_url,
                                 title=title or Path(info["filename"]).stem), task_id=info["task_id"])
                        if not claim.created:
                            return claim.model_dump(exclude_none=True)
                        status = _note_service.artifact_service.get_status(info["task_id"]).get("status")
                        result = ({"task_id": info["task_id"], "status": status, "source_type": "file"}
                                  if status not in {"failed", "error", "not_found"} else
                                  {**retry_media_task(info["task_id"], background_tasks, user), "source_type": "file"})
                        return _accept_source(user, claim, result)
                    result = queue_document(info["filename"], content, local_file_id)
                    local_files.attach_task(user.user_id, local_file_id, result["task_id"], "note")
                    return result

            content = bytearray()
            while chunk := await file.read(65536):
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError("PDF 和 Word 文件不能超过 20 MB")
            return queue_document(file.filename or "", bytes(content))

        if normalized_source_type == "transcript":
            _ensure_transcript_extension(file.filename)
            file_bytes = await file.read()
            if not file_bytes:
                raise ValueError("Uploaded file is empty.")
            transcript = _build_transcript_from_upload(file.filename, file_bytes)
            trace_context = _desktop_trace_context(
                request, workflow=workflow, source=trace_source, media_type="transcript",
                title=title, filename=file.filename, size_bytes=len(file_bytes),
                summary_mode=normalized_summary_mode, output_language=normalized_output_language,
                meeting_session_id=meeting_session_id, meeting_mode=meeting_mode,
                meeting_type=meeting_type,
            )
            background_tasks.add_task(
                _run_task_from_transcript,
                task_id=task_id,
                transcript=transcript,
                title=title or Path(file.filename or "transcript.txt").stem,
                style=style or "meeting",
                summary_mode=normalized_summary_mode,
                extras=extras,
                output_language=normalized_output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                **({"asr_model": asr_model} if asr_model is not None else {}),
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                user_id=user.user_id if user else None,
                trace_context=trace_context,
            )
        else:
            _ensure_media_extension(normalized_source_type, file.filename)
            if workflow == "meeting" and meeting_session_id and user:
                task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
                    ["vinote-recording-task", user.user_id, meeting_session_id],
                )))
                artifacts = _note_service.artifact_service
                with _FILE_TASK_LOCK:
                    existing = artifacts.find_task_dir(task_id)
                    if existing and (existing / "request.json").exists():
                        return {"task_id": task_id, "status": artifacts.get_status(task_id)["status"]}
                    # Only one upload may write this recording's source at a time.
                    if task_id in _UPLOADING_MEETINGS:
                        raise HTTPException(409, "这条录制正在上传，请稍后重试。") from None
                    _UPLOADING_MEETINGS.add(task_id)
                    reserved_upload = task_id
            task_dir = _note_service.artifact_service.create_task_dir(task_id)
            ensure_source(task_dir, user.user_id if user else None,
                dict(model_profile_id=model_profile_id, stt_profile_id=stt_profile_id,
                     asr_model=asr_model, model_name=model_name, api_key=api_key, base_url=base_url), allow_capture=True)
            record_origin(task_dir, request.headers.get("X-VINote-Client", ""))
            media_dir = task_dir / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(_sanitize_filename(file.filename)).suffix.lower() or ".webm"
            upload_path = media_dir / f"source_{normalized_source_type}{suffix}"
            # Stream large recordings instead of retaining the whole video in RAM.
            with upload_path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    destination.write(chunk)
            if not upload_path.stat().st_size:
                upload_path.unlink()
                raise ValueError("Uploaded file is empty.")
            uploaded_size_bytes = upload_path.stat().st_size
            _note_service.artifact_service.record_source_media(
                task_dir,
                upload_path,
                media_kind=normalized_source_type,
            )
            if normalized_source_type == "audio":
                # The original browser recording can have a malformed webm
                # header (notably from Tauri's WKWebView). Normalize it to a
                # canonical 16kHz mono WAV so faster-whisper can decode it.
                # The original file is kept untouched on disk for download.
                upload_path = normalize_audio_for_transcription(upload_path)
            _note_service.artifact_service.update_status(task_dir, "uploaded", "Media uploaded")
            req = _build_note_request_fields(
                workflow=workflow,
                file_path=str(upload_path),
                diarize=diarize,
                speaker_count=speaker_count,
                title=title,
                style=style,
                summary_mode=normalized_summary_mode,
                extras=extras,
                output_language=normalized_output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                **({"asr_model": asr_model} if asr_model is not None else {}),
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
            )
            trace_context = _desktop_trace_context(
                request, workflow=workflow, source=trace_source,
                media_type=normalized_source_type, title=title, filename=file.filename,
                size_bytes=uploaded_size_bytes,
                summary_mode=normalized_summary_mode, output_language=normalized_output_language,
                meeting_session_id=meeting_session_id, meeting_mode=meeting_mode,
                meeting_type=meeting_type,
            )
            _persist_file_request(task_dir, req, user.user_id if user else None, trace_context)
            with _FILE_TASK_LOCK:
                _ACTIVE_FILE_TASKS.add(task_id)
            background_tasks.add_task(
                _run_task_from_file,
                task_id=task_id,
                req=req,
                user_id=user.user_id if user else None,
                trace_context=trace_context,
            )
        return {"task_id": task_id, "status": "uploaded" if normalized_source_type == "audio" else "pending", "message": "Task submitted"}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[API] generate_from_upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if "reserved_upload" in locals():
            with _FILE_TASK_LOCK:
                _UPLOADING_MEETINGS.discard(reserved_upload)


@router.post("/generate_from_upload_sync", response_model=NoteResponse)
async def generate_from_upload_sync(
    request: Request,
    file: UploadFile = File(...),
    source_type: str = Form("media"),
    diarize: bool = Form(False),
    speaker_count: int | None = Form(None, ge=1, le=20),
    title: str | None = Form(None),
    style: str | None = Form("meeting"),
    summary_mode: str = Form("default"),
    extras: str | None = Form(None),
    output_language: str | None = Form(None),
    model_profile_id: str | None = Form(None),
    stt_profile_id: str | None = Form(None),
    model_name: str | None = Form(None),
    asr_model: Annotated[str | None, Form(max_length=200)] = None,
    api_key: str | None = Form(None),
    base_url: str | None = Form(None),
    workflow: str = Form("note_organization"),
    trace_source: str = Form("local_file"),
    meeting_session_id: str | None = Form(None),
    meeting_mode: str | None = Form(None),
    meeting_type: str | None = Form(None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    try:
        normalized_source_type = _normalize_source_type(source_type)
        normalized_summary_mode = _normalize_summary_mode(summary_mode)
        normalized_output_language = _normalize_output_language(output_language)
        desktop_request = _is_desktop_request(request)
        diarize = diarize or (desktop_request and normalized_source_type != "transcript")
        if desktop_request:
            speaker_count = None
        _ensure_media_extension(normalized_source_type, file.filename)

        if normalized_source_type == "transcript":
            _ensure_transcript_extension(file.filename)
            file_bytes = await file.read()
            if not file_bytes:
                raise ValueError("Uploaded file is empty.")
            transcript = _build_transcript_from_upload(file.filename, file_bytes)
            trace_context = _desktop_trace_context(
                request, workflow=workflow, source=trace_source, media_type="transcript",
                title=title, filename=file.filename, size_bytes=len(file_bytes),
                summary_mode=normalized_summary_mode, output_language=normalized_output_language,
                meeting_session_id=meeting_session_id, meeting_mode=meeting_mode,
                meeting_type=meeting_type,
            )
            with desktop_trace(trace_context):
                result = _note_service.generate_from_transcript(
                    transcript=transcript,
                    task_id=task_id,
                    title=title,
                    style=style or "meeting",
                    summary_mode=normalized_summary_mode,
                    extras=extras,
                    output_language=normalized_output_language,
                    model_profile_id=model_profile_id,
                    stt_profile_id=stt_profile_id,
                    **({"asr_model": asr_model} if asr_model is not None else {}),
                    model_name=model_name,
                    api_key=api_key,
                    base_url=base_url,
                    user_id=user.user_id if user else None,
                )
        else:
            task_dir = _note_service.artifact_service.create_task_dir(task_id)
            ensure_source(task_dir, user.user_id if user else None,
                dict(model_profile_id=model_profile_id, stt_profile_id=stt_profile_id,
                     asr_model=asr_model, model_name=model_name, api_key=api_key, base_url=base_url), allow_capture=True)
            record_origin(task_dir, request.headers.get("X-VINote-Client", ""))
            media_dir = task_dir / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(_sanitize_filename(file.filename)).suffix.lower() or ".webm"
            upload_path = media_dir / f"source_{normalized_source_type}{suffix}"
            # Stream large recordings instead of retaining the whole video in RAM.
            with upload_path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    destination.write(chunk)
            if not upload_path.stat().st_size:
                upload_path.unlink()
                raise ValueError("Uploaded file is empty.")
            uploaded_size_bytes = upload_path.stat().st_size
            _note_service.artifact_service.record_source_media(
                task_dir,
                upload_path,
                media_kind=normalized_source_type,
            )
            if normalized_source_type == "audio":
                upload_path = normalize_audio_for_transcription(upload_path)
            req = _build_note_request_fields(
                workflow=workflow,
                file_path=str(upload_path),
                diarize=diarize,
                speaker_count=speaker_count,
                title=title,
                style=style,
                summary_mode=normalized_summary_mode,
                extras=extras,
                output_language=normalized_output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                **({"asr_model": asr_model} if asr_model is not None else {}),
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
            )
            trace_context = _desktop_trace_context(
                request, workflow=workflow, source=trace_source,
                media_type=normalized_source_type, title=title, filename=file.filename,
                size_bytes=uploaded_size_bytes,
                summary_mode=normalized_summary_mode, output_language=normalized_output_language,
                meeting_session_id=meeting_session_id, meeting_mode=meeting_mode,
                meeting_type=meeting_type,
            )
            with desktop_trace(trace_context):
                result = _note_service.generate_from_file(
                    file_path=req.file_path,
                    diarize=req.diarize,
                    speaker_count=req.speaker_count,
                    task_id=task_id,
                    title=req.title,
                    style=req.style or "meeting",
                    summary_mode=req.summary_mode,
                    extras=req.extras,
                    output_language=req.output_language,
                    model_profile_id=req.model_profile_id,
                    stt_profile_id=req.stt_profile_id,
                    **({"asr_model": req.asr_model} if req.asr_model is not None else {}),
                    model_name=req.model_name,
                    api_key=req.api_key,
                    base_url=req.base_url,
                    user_id=user.user_id if user else None,
                )
    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("[API] generate_from_upload_sync failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[API] generate_from_upload_sync failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return NoteResponse(
        task_id=task_id,
        title=result.audio_meta.title,
        markdown=result.markdown,
        duration=result.audio_meta.duration,
        platform=result.audio_meta.platform,
        video_id=result.audio_meta.video_id,
        summary_mode=result.summary_mode,
    )


def _persist_url_request(task_id: str, req: NoteRequest, user_id: str | None,
                         trace_context: DesktopTraceContext | None) -> bool:
    """Forward-only pending URL submission; never infer a historical request."""
    from app.services.task_model_source import _bind_task_owner
    from app.services.vilab_cloud_service import VILabCloudService
    artifacts = _note_service.artifact_service
    folder = artifacts.find_task_dir(task_id)
    if not folder or artifacts.get_status(task_id).get("status") != "pending":
        return False
    _bind_task_owner(folder, artifacts.output_dir, user_id)
    path = folder / "request.json"
    if path.exists():
        return False  # Existing submissions/recovery never acquire a new URL worker.
    # Capture first: request.json would otherwise forbid fresh capture in the
    # generation decorator. Neither this preparation nor validation runs ASR.
    snapshot = ensure_source(folder, user_id, {**req.model_dump(), "needs_stt": True}, allow_capture=True)
    with VILabCloudService().task_snapshot(user_id, snapshot=snapshot):
        VILabCloudService().validate_ready(user_id)
    artifacts.write_json(path, {"kind": "media_url",
        "request": req.model_dump(exclude={"api_key", "base_url", "model_name"}),
        "trace": asdict(trace_context) if trace_context else None})
    return True


def _run_task(task_id: str, req: NoteRequest, user_id: str | None,
              trace_context: DesktopTraceContext | None = None):
    try:
        if not _persist_url_request(task_id, req, user_id, trace_context):
            return
        with desktop_trace(trace_context):
            _note_service.generate(
                video_url=req.video_url, task_id=task_id, platform=req.platform,
                style=req.style or "detailed", summary_mode=req.summary_mode,
                extras=req.extras, output_language=req.output_language,
                model_profile_id=req.model_profile_id, stt_profile_id=req.stt_profile_id,
                **({"asr_model": req.asr_model} if req.asr_model is not None else {}),
                model_name=req.model_name, api_key=req.api_key, base_url=req.base_url,
                user_id=user_id,
                diarize=req.diarize, speaker_count=req.speaker_count,
            )
    except Exception as exc:
        logger.error("[Background] task failed task_id=%s error=%s", task_id, exc, exc_info=True)
        # Snapshot/catalog failures happen before NoteService's own failure
        # handler. Publish a terminal outcome rather than leave pending forever.
        try:
            artifacts = _note_service.artifact_service
            folder = artifacts.find_task_dir(task_id)
            marker = folder / "recording_owner" if folder else None
            owned = (marker and not marker.is_symlink() and marker.is_file()
                     and marker.read_text(encoding="utf-8") == user_id)
            if folder and (owned or not user_id and not marker.exists()) and artifacts.get_status(task_id).get("status") != "failed":
                artifacts.update_status(folder, "failed", "来源准备未完成，原提交和已有资料已保留，请核验原任务",
                                        retryable=False)
        except Exception:
            logger.warning("[Background] cannot persist URL preparation failure task_id=%s", task_id)


def _persist_file_request(task_dir: Path, req: LocalFileRequest, user_id: str | None,
                          trace_context: DesktopTraceContext | None) -> None:
    owner_path = task_dir / "recording_owner"
    if owner_path.exists() and owner_path.read_text(encoding="utf-8") != user_id:
        raise HTTPException(404, "Task not found")
    if user_id:
        owner_path.write_text(user_id, encoding="utf-8")
    request_path = task_dir / "request.json"
    ensure_source(task_dir, user_id, req.model_dump(), allow_capture=not request_path.exists())
    if request_path.exists():
        if user_id:
            from app.services.task_original_service import TaskOriginalService
            TaskOriginalService().register(user_id, task_dir, req.title)
        return  # Keep the original request immutable during task recovery.
    _note_service.artifact_service.write_json(request_path, {
        "request": req.model_dump(exclude={"api_key", "base_url", "model_name"}),
        "trace": asdict(trace_context) if trace_context else None,
    })
    if user_id:
        from app.services.task_original_service import TaskOriginalService
        TaskOriginalService().register(user_id, task_dir, req.title)


def _run_task_from_file(task_id: str, req: LocalFileRequest, user_id: str | None,
                        trace_context: DesktopTraceContext | None = None):
    with _FILE_TASK_LOCK:
        _ACTIVE_FILE_TASKS.add(task_id)
    try:
        task_dir = _note_service.artifact_service.create_task_dir(task_id)
        _persist_file_request(task_dir, req, user_id, trace_context)
        with desktop_trace(trace_context):
            _note_service.generate_from_file(
                file_path=req.file_path,
                diarize=req.diarize,
                speaker_count=req.speaker_count,
                task_id=task_id,
                title=req.title,
                style=req.style or "meeting",
                summary_mode=req.summary_mode,
                extras=req.extras,
                output_language=req.output_language,
                model_profile_id=req.model_profile_id,
                stt_profile_id=req.stt_profile_id,
                **({"asr_model": req.asr_model} if req.asr_model is not None else {}),
                model_name=req.model_name,
                api_key=req.api_key,
                base_url=req.base_url,
                user_id=user_id,
            )
    except Exception as exc:
        logger.error("[Background] local task failed task_id=%s error=%s", task_id, exc, exc_info=True)
        try:
            artifacts = _note_service.artifact_service
            folder = artifacts.find_task_dir(task_id)
            if folder and artifacts.get_status(task_id).get("status") != "failed":
                artifacts.update_status(folder, "failed", "会后处理异常中断，请重试。", retryable=True)
        except Exception:
            logger.exception("[Background] cannot persist failure task_id=%s", task_id)
    finally:
        with _FILE_TASK_LOCK:
            _ACTIVE_FILE_TASKS.discard(task_id)


def _queue_source_job(task_id, job, background_tasks, user, request, source=None):
    if job.get("options", {}).get("api_key"):
        raise HTTPException(400, "请使用已保存的模型配置，不支持临时密钥")
    folder = _note_service.artifact_service.create_task_dir(task_id)
    if user:
        (folder / "recording_owner").write_text(user.user_id, encoding="utf-8")
    ensure_source(folder, user.user_id if user else None, dict(job.get("options", {}), needs_stt=False),
                  allow_capture=not (folder / "source_job.json").exists())
    record_origin(folder, request.headers.get("X-VINote-Client", ""))
    trace = _desktop_trace_context(request, workflow="note_organization", source="local_file" if source else "url",
        media_type="document", title=source.get("title") if source else None,
        url=job.get("url"), summary_mode=job.get("options", {}).get("summary_mode", "default"),
        output_language=job.get("options", {}).get("output_language"))
    if trace:
        job = {**job, "trace": asdict(trace)}
    (folder / "source_job.json").write_text(json.dumps(job), encoding="utf-8")
    if source:
        (folder / "document_text.json").write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    _note_service.artifact_service.update_status(folder, "preparing", "正在准备来源正文…", retryable=True)
    with _FILE_TASK_LOCK:
        _ACTIVE_FILE_TASKS.add(task_id)
    background_tasks.add_task(_run_source_job, task_id, job, user.user_id if user else None)
    return {"task_id": task_id, "status": "preparing", "source_type": "file"}


def _run_source_job(task_id, job, user_id):
    try:
        trace = DesktopTraceContext(**job["trace"]) if job.get("trace") else None
        with desktop_trace(trace):
            run_source_job(_note_service, task_id, job, user_id)
    except Exception:
        logger.warning("Document task failed task_id=%s", task_id)
    finally:
        with _FILE_TASK_LOCK:
            _ACTIVE_FILE_TASKS.discard(task_id)


def _run_task_from_transcript(
    task_id: str,
    transcript: TranscriptResult,
    title: str | None,
    style: str,
    summary_mode: str,
    extras: str | None,
    output_language: str | None,
    model_profile_id: str | None,
    stt_profile_id: str | None,
    model_name: str | None,
    api_key: str | None,
    base_url: str | None,
    user_id: str | None,
    trace_context: DesktopTraceContext | None = None,
    asr_model: str | None = None,
):
    try:
        with desktop_trace(trace_context):
            _note_service.generate_from_transcript(
                transcript=transcript,
                task_id=task_id,
                title=title,
                style=style,
                summary_mode=summary_mode,
                extras=extras,
                output_language=output_language,
                model_profile_id=model_profile_id,
                stt_profile_id=stt_profile_id,
                **({"asr_model": asr_model} if asr_model is not None else {}),
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                user_id=user_id,
            )
    except Exception as exc:
        logger.error("[Background] transcript task failed task_id=%s error=%s", task_id, exc, exc_info=True)
