"""Manage saved meeting media separately from its transcript and note."""
from fastapi import HTTPException
from sqlalchemy import select

from app.db import session_scope
from app.db_models import NoteDB
from app.services.note_repository import NoteRepository
from app.services.task_artifact_service import TaskArtifactService

MEDIA_EXTENSIONS = {'.webm', '.mp4', '.mkv', '.mov', '.wav', '.mp3', '.m4a', '.ogg', '.flac'}


class MeetingMediaService:
    def _context(self, user_id, note_id):
        note = NoteRepository().get_note(user_id, note_id)
        if not note or note.source_type not in {'meeting_recording', 'meeting_video'}:
            raise HTTPException(404, '会议录制不存在')
        artifacts = TaskArtifactService()
        folder = artifacts.find_task_dir(note.task_id) if note.task_id else None
        with session_scope() as db:
            row = db.get(NoteDB, note_id)
            owner = bool(row and row.created_by == user_id)
            references = list(db.scalars(select(NoteDB.id).where(NoteDB.task_id == note.task_id))) if note.task_id else []
        owner_file = folder / 'recording_owner' if folder else None
        trusted_owner = bool(owner_file and owner_file.is_file() and not owner_file.is_symlink()
                             and owner_file.read_text(encoding='utf-8') == user_id)
        return folder, owner and trusted_owner and len(references) == 1

    def info(self, user_id, note_id):
        folder, can_delete = self._context(user_id, note_id)
        source = TaskArtifactService().resolve_source_media(folder) if folder else None
        deleted = bool(folder and (folder / 'recording_deleted').exists())
        available = bool(source and not deleted)
        return {'available': available, 'deleted': deleted, 'can_delete': can_delete,
                'filename': source.name if available else None,
                'size_bytes': source.stat().st_size if available else 0}

    def delete(self, user_id, note_id):
        folder, can_delete = self._context(user_id, note_id)
        if not can_delete:
            raise HTTPException(403, '无法验证录制归属或文件被其他纪要共用，不能删除')
        if not folder:
            return
        root = folder.resolve()
        media = root / 'media'
        if media.is_symlink():
            raise HTTPException(409, '录制存储路径异常，未删除文件')
        targets = [path for path in media.glob('*') if path.suffix.lower() in MEDIA_EXTENSIONS]
        # Resolve every target before deleting anything. Never touch the imported original.
        if any(path.is_symlink() or not path.resolve().is_relative_to(root) for path in targets):
            raise HTTPException(409, '录制存储路径异常，未删除文件')
        try:
            for path in targets:
                if path.is_file():
                    path.unlink()
            (root / 'recording_deleted').write_text('deleted', encoding='utf-8')
        except OSError as exc:
            raise HTTPException(409, '录制文件正在使用或无法删除，请停止播放后重试') from exc
