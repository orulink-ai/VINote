"""Device-local originals API. Cloud shared service rejects original uploads."""
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.services.auth_service import get_current_user
from app.services.local_file_service import AUDIO, DOCUMENT, TEXT, LocalFileService


def local_only():
    if settings.workspace_cloud_runtime:
        raise HTTPException(409, "原始文件默认留在来源设备，请在设备文件库操作")


router = APIRouter(prefix="/files", tags=["local-files"], dependencies=[Depends(local_only)])
service = LocalFileService()


@router.get("")
def list_files(user=Depends(get_current_user)):
    return service.list(user.user_id)


@router.post("")
async def upload(file: UploadFile = File(...), purpose: str = Form("unassigned"), user=Depends(get_current_user)):
    identifier, filename, target = service.new_target(user.user_id, file.filename)
    try:
        size = 0
        with target.open("xb") as output:
            while data := await file.read(1024 * 1024):
                size += len(data)
                if size > 2 * 1024 * 1024 * 1024:
                    raise HTTPException(413, "文件不能超过 2 GB")
                output.write(data)
        return service.register(user.user_id, identifier, filename, target, purpose)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/{identifier}")
def info(identifier: str, user=Depends(get_current_user)):
    return service.get(user.user_id, identifier)[0]


@router.get("/{identifier}/content")
def content(identifier: str, download: bool = False, user=Depends(get_current_user), playback: bool = False):
    info, path = service.get(user.user_id, identifier)
    if playback and not download and info['media_type'].startswith(('video/', 'audio/')):
        from app.services.media_playback_service import playback_file
        path = playback_file(path)
    return FileResponse(path, media_type=info["media_type"], filename=info["filename"] if download else None,
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/{identifier}")
def delete(identifier: str, user=Depends(get_current_user)):
    service.delete(user.user_id, identifier)
    return {"deleted": True, "notes_preserved": True}


class FilePurpose(BaseModel):
    purpose: str


@router.patch("/{identifier}")
def set_file_purpose(identifier: str, payload: FilePurpose, user=Depends(get_current_user)):
    return service.set_purpose(user.user_id, identifier, payload.purpose)


class GenerateFile(BaseModel):
    model_profile_id: str | None = None
    stt_profile_id: str | None = None
    meeting: bool = False


@router.post("/{identifier}/generate")
async def generate(identifier: str, payload: GenerateFile, request: Request,
                   background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    with service.generation_lease(user.user_id, identifier):
        return await _generate(identifier, payload, request, background_tasks, user)


async def _generate(identifier, payload, request, background_tasks, user):
    from app.routers.note import generate_from_upload
    info, path = service.get(user.user_id, identifier)
    if not info["can_generate"]:
        raise HTTPException(422, "此格式可保留和导出，暂未支持直接整理")
    if info["task_id"]:
        from app.services.task_artifact_service import TaskArtifactService
        from app.services.task_failure import recovery_status
        task_status = recovery_status(TaskArtifactService(settings.output_dir).get_status(info["task_id"]))
        status = task_status.get("status")
        if status in {"failed", "error"} and task_status.get("retryable") is False:
            raise HTTPException(409, {"code": task_status.get("error_code") or "retry_not_confirmed",
                "message": "原任务尚不能安全重试，请查询原结果；原文件已保留。"})
        # Unknown/in-flight/completed submissions never create a duplicate task.
        if status not in {"failed", "error", "not_found"}:
            return {"task_id": info["task_id"], "status": status,
                    **({"source_type": "file"} if path.suffix.lower() in DOCUMENT else {})}
        from app.routers.note import retry_media_task
        if path.suffix.lower() not in TEXT:
            result = retry_media_task(info["task_id"], background_tasks, user)
            return {**result, **({"source_type": "file"} if path.suffix.lower() in DOCUMENT else {})}
    with path.open("rb") as stream:
        result = await generate_from_upload(
            background_tasks=background_tasks, request=request, file=UploadFile(stream, filename=info["filename"]),
            source_type="document" if path.suffix.lower() in DOCUMENT else "transcript" if path.suffix.lower() in TEXT else "audio" if path.suffix.lower() in AUDIO else "video",
            diarize=payload.meeting, speaker_count=None, title=path.stem if info["filename"] == "file" else info["filename"].rsplit(".", 1)[0],
            style="meeting" if payload.meeting else "default", summary_mode="default", extras=None, output_language=None,
            model_profile_id=payload.model_profile_id, stt_profile_id=payload.stt_profile_id, model_name=None,
            api_key=None, base_url=None, workflow="meeting" if payload.meeting else "note_organization",
            trace_source="local_file", meeting_session_id=identifier if payload.meeting else None,
            meeting_mode="minutes" if payload.meeting else None,
            meeting_type="audio" if path.suffix.lower() in AUDIO else "video", user=user,
        )
    service.attach_task(user.user_id, identifier, result["task_id"], "meeting" if payload.meeting else "note")
    return result
