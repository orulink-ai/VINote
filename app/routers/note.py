"""
Note generation API routes.
"""
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.llm.prompts import STYLE_MAP
from app.models.auth import AuthenticatedUser
from app.models.note import LocalFileRequest, NoteRequest, NoteResponse, SummaryMode, TaskStatusResponse
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.auth_service import get_current_user, get_optional_current_user
from app.services.audio_normalizer import normalize_audio_for_transcription
from app.services.note_service import NoteService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notes"])
_note_service = NoteService()

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
    if normalized in {"audio", "video", "transcript"}:
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
) -> LocalFileRequest:
    return LocalFileRequest(
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
        api_key=api_key,
        base_url=base_url,
    )


@router.post("/generate")
def generate_note_async(
    req: NoteRequest,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    background_tasks.add_task(_run_task, task_id=task_id, req=req, user_id=user.user_id if user else None)
    return {"task_id": task_id, "status": "pending", "message": "Task submitted"}


@router.post("/generate_sync", response_model=NoteResponse)
def generate_note_sync(
    req: NoteRequest,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    try:
        result = _note_service.generate(
            video_url=req.video_url,
            task_id=task_id,
            platform=req.platform,
            style=req.style or "detailed",
            summary_mode=req.summary_mode,
            extras=req.extras,
            output_language=req.output_language,
            model_profile_id=req.model_profile_id,
            stt_profile_id=req.stt_profile_id,
            model_name=req.model_name,
            api_key=req.api_key,
            base_url=req.base_url,
            user_id=user.user_id if user else None,
        )
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


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str):
    status_data = _note_service.get_status(task_id)
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
    return TaskStatusResponse(task_id=task_id, status=status, message=message, result=result)


@router.get("/task/{task_id}/artifacts/{asset_path:path}", include_in_schema=False)
def get_task_artifact(task_id: str, asset_path: str):
    task_dir = _note_service.artifact_service.find_task_dir(task_id)
    if not task_dir:
        raise HTTPException(status_code=404, detail="Task not found")

    normalized_parts = Path(asset_path).parts
    if not normalized_parts or normalized_parts[0] not in {"screenshots", "media"}:
        raise HTTPException(status_code=404, detail="Artifact not found")

    requested_path = (task_dir / asset_path).resolve()
    task_root = task_dir.resolve()
    if task_root not in requested_path.parents and requested_path != task_root:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not requested_path.exists() or not requested_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

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
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_task_from_file,
        task_id=task_id,
        req=req,
        user_id=user.user_id if user else None,
    )
    return {"task_id": task_id, "status": "pending", "message": "Task submitted"}


@router.post("/generate_from_file_sync", response_model=NoteResponse)
def generate_from_file_sync(
    req: LocalFileRequest,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    try:
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
            model_name=req.model_name,
            api_key=req.api_key,
            base_url=req.base_url,
            user_id=user.user_id if user else None,
        )
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
    api_key: str | None = Form(None),
    base_url: str | None = Form(None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    try:
        normalized_source_type = _normalize_source_type(source_type)
        normalized_summary_mode = _normalize_summary_mode(summary_mode)
        normalized_output_language = _normalize_output_language(output_language)
        if diarize and normalized_source_type != "transcript":
            from app.services.speaker_diarization_service import SpeakerDiarizationService
            SpeakerDiarizationService.require_ready()
        task_id = str(uuid.uuid4())

        if normalized_source_type == "transcript":
            _ensure_transcript_extension(file.filename)
            file_bytes = await file.read()
            if not file_bytes:
                raise ValueError("Uploaded file is empty.")
            transcript = _build_transcript_from_upload(file.filename, file_bytes)
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
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                user_id=user.user_id if user else None,
            )
        else:
            _ensure_media_extension(normalized_source_type, file.filename)
            task_dir = _note_service.artifact_service.create_task_dir(task_id)
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
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
            )
            background_tasks.add_task(
                _run_task_from_file,
                task_id=task_id,
                req=req,
                user_id=user.user_id if user else None,
            )
        return {"task_id": task_id, "status": "uploaded" if normalized_source_type == "audio" else "pending", "message": "Task submitted"}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[API] generate_from_upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/generate_from_upload_sync", response_model=NoteResponse)
async def generate_from_upload_sync(
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
    api_key: str | None = Form(None),
    base_url: str | None = Form(None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    task_id = str(uuid.uuid4())
    try:
        normalized_source_type = _normalize_source_type(source_type)
        normalized_summary_mode = _normalize_summary_mode(summary_mode)
        normalized_output_language = _normalize_output_language(output_language)
        _ensure_media_extension(normalized_source_type, file.filename)

        if normalized_source_type == "transcript":
            _ensure_transcript_extension(file.filename)
            file_bytes = await file.read()
            if not file_bytes:
                raise ValueError("Uploaded file is empty.")
            transcript = _build_transcript_from_upload(file.filename, file_bytes)
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
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                user_id=user.user_id if user else None,
            )
        else:
            task_dir = _note_service.artifact_service.create_task_dir(task_id)
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
            _note_service.artifact_service.record_source_media(
                task_dir,
                upload_path,
                media_kind=normalized_source_type,
            )
            if normalized_source_type == "audio":
                upload_path = normalize_audio_for_transcription(upload_path)
            req = _build_note_request_fields(
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
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
            )
            result = _note_service.generate_from_file(
                file_path=req.file_path,
                task_id=task_id,
                title=req.title,
                style=req.style or "meeting",
                summary_mode=req.summary_mode,
                extras=req.extras,
                output_language=req.output_language,
                model_profile_id=req.model_profile_id,
                stt_profile_id=req.stt_profile_id,
                model_name=req.model_name,
                api_key=req.api_key,
                base_url=req.base_url,
                user_id=user.user_id if user else None,
            )
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


def _run_task(task_id: str, req: NoteRequest, user_id: str | None):
    try:
        _note_service.generate(
            video_url=req.video_url,
            task_id=task_id,
            platform=req.platform,
            style=req.style or "detailed",
            summary_mode=req.summary_mode,
            extras=req.extras,
            output_language=req.output_language,
            model_profile_id=req.model_profile_id,
            stt_profile_id=req.stt_profile_id,
            model_name=req.model_name,
            api_key=req.api_key,
            base_url=req.base_url,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error("[Background] task failed task_id=%s error=%s", task_id, exc, exc_info=True)


def _run_task_from_file(task_id: str, req: LocalFileRequest, user_id: str | None):
    try:
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
            model_name=req.model_name,
            api_key=req.api_key,
            base_url=req.base_url,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error("[Background] local task failed task_id=%s error=%s", task_id, exc, exc_info=True)


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
):
    try:
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
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error("[Background] transcript task failed task_id=%s error=%s", task_id, exc, exc_info=True)
