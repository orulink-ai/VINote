import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.models.auth import AuthenticatedUser
from app.models.note_library import (
    NoteCreateRequest,
    NoteRecordResponse,
    NoteScope,
    NoteUpdateRequest,
    SpeakerAliasesResponse,
    SpeakerAliasesUpdateRequest,
    TranscriptEvidenceResponse,
)
from app.services.auth_service import get_current_user
from app.services.task_artifact_service import TaskArtifactService
from app.services.note_repository import NoteRepository
from app.services.meeting_media_service import MeetingMediaService
from app.services.note_origin_service import read_origin

router = APIRouter(tags=["notes-library"])
_repository = NoteRepository()
_artifact_service = TaskArtifactService()


@router.get("/notes", response_model=list[NoteRecordResponse])
def list_notes(
    scope: NoteScope = Query(default="personal"),
    team_id: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
):
    return _repository.list_notes(user.user_id, scope=scope, team_id=team_id)


@router.get("/notes/{note_id}", response_model=NoteRecordResponse)
def get_note(note_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    note = _repository.get_note(user.user_id, note_id)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@router.get("/notes/{note_id}/media", include_in_schema=False)
def get_note_media(note_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    note = _repository.get_note(user.user_id, note_id)
    if not note or not note.task_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    task_dir = _artifact_service.find_task_dir(note.task_id)
    if not task_dir or (task_dir / "recording_deleted").exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    declared_source = _artifact_service.resolve_source_media(task_dir)
    if declared_source:
        media_type = mimetypes.guess_type(declared_source.name)[0] or "application/octet-stream"
        if declared_source.suffix.lower() == ".webm" and note.source_type in {"audio", "meeting_recording"}:
            media_type = "audio/webm"
        return FileResponse(path=declared_source, media_type=media_type, filename=declared_source.name)

    media_dir = task_dir / "media"
    media_candidates = [
        path for path in sorted(media_dir.glob("*"))
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".wav", ".ogg"}
    ]
    preferred_media = next((path for path in media_candidates if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}), None)
    if not preferred_media:
        preferred_media = next(iter(media_candidates), None)
    if preferred_media:
        media_path = preferred_media.resolve()
    else:
        audio_meta = _artifact_service.load_audio_meta(task_dir)
        if not audio_meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        media_path = Path(audio_meta.file_path).resolve()

    if not media_path.exists() or not media_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    media_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    return FileResponse(path=media_path, media_type=media_type, filename=media_path.name)


@router.get("/notes/{note_id}/recording")
def recording_info(note_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    return MeetingMediaService().info(user.user_id, note_id)


@router.delete("/notes/{note_id}/recording", status_code=204)
def delete_recording(note_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    MeetingMediaService().delete(user.user_id, note_id)


@router.get("/notes/{note_id}/transcript", response_model=TranscriptEvidenceResponse)
def get_note_transcript(note_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    note = _repository.get_note(user.user_id, note_id)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    aliases = _repository.get_speaker_aliases(user.user_id, note_id) or {}
    if not note.task_id:
        return {"language": None, "full_text": "", "segments": [], "aliases": aliases, "metadata": {}}
    task_dir = _artifact_service.find_task_dir(note.task_id)
    transcript = _artifact_service.load_transcript(task_dir) if task_dir else None
    if not transcript:
        return {"language": None, "full_text": "", "segments": [], "aliases": aliases, "metadata": {}}

    segments = []
    for segment in transcript.segments:
        speaker_label = aliases.get(segment.speaker_id, segment.speaker_label)
        segments.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "raw_text": segment.raw_text,
                "cleaned_text": segment.cleaned_text,
                "speaker_id": segment.speaker_id,
                "speaker_label": speaker_label,
            }
        )
    return {
        "language": transcript.language,
        "full_text": transcript.full_text,
        "segments": segments,
        "aliases": aliases,
        "metadata": transcript.metadata,
    }


@router.patch("/notes/{note_id}/speakers", response_model=SpeakerAliasesResponse)
def update_note_speakers(
    note_id: str,
    payload: SpeakerAliasesUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        aliases = _repository.update_speaker_aliases(user.user_id, note_id, payload.aliases)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if aliases is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return {"aliases": aliases}


@router.post("/notes", response_model=NoteRecordResponse, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreateRequest, request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        # 以生成任务为准，不能用当前保存请求冒充原始生成来源。
        folder = _artifact_service.find_task_dir(payload.task_id) if payload.task_id else None
        client = read_origin(folder)
        return _repository.create_note(user.user_id, payload, generation_client=client)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/notes/{note_id}", response_model=NoteRecordResponse)
def update_note(note_id: str, payload: NoteUpdateRequest, user: AuthenticatedUser = Depends(get_current_user)):
    note = _repository.update_note(user.user_id, note_id, payload)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    deleted = _repository.delete_note(user.user_id, note_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
