"""Owned local files. File deletion never deletes a note or shared version."""
import hashlib
import mimetypes
import shutil
import uuid
from contextlib import contextmanager
from threading import Lock
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.db_models import NoteDB
from app.models.local_file import LocalFileDB
from app.services.task_artifact_service import TaskArtifactService

MEDIA = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".opus"}
TEXT = {".md", ".txt", ".srt", ".vtt", ".json"}
DOCUMENT = {".pdf", ".docx"}
ALLOWED = MEDIA | AUDIO | TEXT | DOCUMENT
_SUBMISSION_LOCK = Lock()
_SUBMITTING = set()


class LocalFileService:
    def retain_note_original(self, owner, note):
        """Detach a verified original from a note before removing its last UI link.

        The library owns a bounded-path copy; task media and imported files are
        untouched. Deterministic identity makes retries and multiple versions safe.
        """
        if note.created_by != owner or not note.task_id:
            return None
        with session_scope() as db:
            existing = db.scalar(select(LocalFileDB).where(LocalFileDB.owner == owner, LocalFileDB.task_id == note.task_id))
            if existing:
                return self._info(existing, self._path(existing))
        artifacts = TaskArtifactService(settings.output_dir)
        folder = artifacts.find_task_dir(note.task_id)
        marker = folder / "recording_owner" if folder else None
        if not marker or marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="utf-8") != owner:
            return None
        if (folder / "recording_deleted").exists():
            return None
        source = artifacts.resolve_source_media(folder)
        if not source or source.is_symlink() or source.parent.resolve() != (folder / "media").resolve() or source.suffix.lower() not in ALLOWED:
            return None
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vinote-original:{owner}:{note.task_id}"))
        root = settings.data_dir / "local-files" / hashlib.sha256(owner.encode()).hexdigest()[:32]
        root.mkdir(parents=True, exist_ok=True)
        target = root / (identifier + source.suffix.lower())
        temporary = root / (identifier + ".retaining")
        if target.is_symlink() or temporary.is_symlink():
            raise HTTPException(409, "原文件保存位置不可用，内容尚未删除")
        try:
            if not target.exists() or target.stat().st_size != source.stat().st_size:
                shutil.copyfile(source, temporary)
                temporary.replace(target)
            with session_scope() as db:
                row = db.get(LocalFileDB, identifier)
                if not row:
                    row = LocalFileDB(id=identifier, owner=owner,
                        filename=(note.title[:220] + source.suffix.lower()), path=str(target),
                        size_bytes=target.stat().st_size,
                        category="video" if source.suffix.lower() in MEDIA else "recording" if source.suffix.lower() in AUDIO else "file",
                        purpose="meeting" if note.source_type in {"meeting_recording", "meeting_video"} else "note",
                        task_id=note.task_id, created_at=note.created_at)
                    db.add(row)
                    db.flush()
                if row.owner != owner or row.task_id != note.task_id:
                    raise HTTPException(409, "原文件归属无法确认，内容尚未删除")
                return self._info(row, self._path(row))
        except OSError:
            raise HTTPException(507, "原文件尚未独立保存，内容保留，请释放存储空间后重试") from None

    def new_target(self, owner, filename):
        filename = Path((filename or "file").replace("\\", "/")).name[:250]
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED:
            raise HTTPException(422, "暂不支持此文件类型，请选择音视频、文字、字幕、PDF 或 DOCX")
        identifier = str(uuid.uuid4())
        folder = settings.data_dir / "local-files" / hashlib.sha256(owner.encode()).hexdigest()[:32]
        folder.mkdir(parents=True, exist_ok=True)
        return identifier, filename, folder / (identifier + suffix)

    def register(self, owner, identifier, filename, target, purpose="unassigned"):
        if purpose not in {"meeting", "note", "unassigned"}:
            raise HTTPException(422, "请选择会议或笔记作为文件用途")
        size = target.stat().st_size
        if not size:
            raise HTTPException(422, "文件为空，请重新选择")
        with session_scope() as db:
            row = LocalFileDB(id=identifier, owner=owner, filename=filename, path=str(target), size_bytes=size,
                              category="video" if target.suffix.lower() in MEDIA else "recording" if target.suffix.lower() in AUDIO else "file",
                              purpose=purpose)
            db.add(row)
            db.flush()
            return self._info(row, target)

    def _path(self, row, *, require_exists=True):
        target = Path(row.path)
        root = settings.data_dir / "local-files" / hashlib.sha256(row.owner.encode()).hexdigest()[:32]
        if target.is_symlink() or target.resolve().parent != root.resolve():
            raise HTTPException(404, "文件路径不可用")
        if require_exists and not target.is_file():
            raise HTTPException(404, "当前设备找不到此文件")
        return target

    def get(self, owner, identifier):
        if identifier.startswith("task:"):
            from app.services.task_original_service import TaskOriginalService
            return TaskOriginalService().get(owner, identifier)
        with session_scope() as db:
            row = db.get(LocalFileDB, identifier)
            if not row or row.owner != owner:
                raise HTTPException(404, "找不到此文件")
            path = self._path(row)
            info = self._info(row, path)
            note = db.scalar(select(NoteDB).where(NoteDB.created_by == owner, NoteDB.task_id == row.task_id).order_by(NoteDB.created_at.desc())) if row.task_id else None
            if note:
                info['note_id'] = note.id
                info['purpose'] = self._purpose(row, note)
            return info, path

    @staticmethod
    def _purpose(row, note=None):
        if row.purpose in {"meeting", "note"}:
            return row.purpose
        if note:
            return "meeting" if note.source_type in {"meeting_recording", "meeting_video"} else "note"
        # File type alone cannot tell whether an imported video or transcript
        # was intended for a meeting or a note. Keep old unlinked rows visible
        # under an explicit review group instead of silently misfiling them.
        return "unknown"

    def _info(self, row, path):
        suffix = path.suffix.lower()
        return {"id": row.id, "filename": row.filename, "category": "recording" if suffix in AUDIO else row.category,
                "purpose": self._purpose(row),
                "size_bytes": row.size_bytes, "created_at": row.created_at.isoformat(),
                "task_id": row.task_id, "available": path.is_file(), "can_delete": True,
                "can_generate": suffix in ALLOWED,
                "media_type": mimetypes.guess_type(row.filename)[0] or "application/octet-stream",
                "location": "当前电脑 · 文件库", "content_url": f"/api/files/{row.id}/content"}

    def list(self, owner):
        with session_scope() as db:
            rows = list(db.scalars(select(LocalFileDB).where(LocalFileDB.owner == owner).order_by(LocalFileDB.created_at.desc())))
            result = [self._info(row, Path(row.path)) for row in rows]
            rows_by_id = {row.id: row for row in rows}
            owned_notes = list(db.scalars(select(NoteDB).where(NoteDB.created_by == owner)))
            for item in result:
                note = next((n for n in owned_notes if item['task_id'] and n.task_id == item['task_id']), None)
                if note:
                    item['note_id'] = note.id
                    item['purpose'] = self._purpose(rows_by_id[item['id']], note)
            tasks = {row.task_id for row in rows if row.task_id}
            # Existing saved media stays accessible; only expose task sources with
            # an explicit owner marker. Imported task copies remain non-deletable.
            artifacts = TaskArtifactService(settings.output_dir)
            referenced_notes = {}
            for note in owned_notes:
                if not note.task_id or note.task_id in tasks:
                    continue
                tasks.add(note.task_id)
                folder = artifacts.find_task_dir(note.task_id)
                marker = folder / "recording_owner" if folder else None
                if not marker or marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="utf-8") != owner:
                    continue
                source = artifacts.resolve_source_media(folder)
                if not source or (folder / 'recording_deleted').exists():
                    continue
                if (folder / 'source_reference.json').exists():
                    from app.services.task_generation_context import _read_json
                    reference = _read_json(folder / 'source_reference.json')
                    previous = referenced_notes.get(reference['parent_task_id'])
                    if previous is None or note.created_at > previous.created_at:
                        referenced_notes[reference['parent_task_id']] = note
                    continue  # The canonical original has one row; every note keeps its own content history.
                from app.services.meeting_media_service import MeetingMediaService
                can_delete = False
                if note.source_type in {'meeting_recording', 'meeting_video'}:
                    try:
                        can_delete = MeetingMediaService().info(owner, note.id)['can_delete']
                    except HTTPException:
                        pass
                filename = source.name
                suffix = Path(filename).suffix.lower()
                result.append({"id": "note:" + note.id, "filename": filename, "title": note.title,
                               "purpose": "meeting" if note.source_type in {"meeting_recording", "meeting_video"} else "note",
                               "category": "video" if suffix in MEDIA else "recording" if suffix in AUDIO else "file", "size_bytes": source.stat().st_size,
                               "created_at": note.created_at.isoformat(), "note_id": note.id, "task_id": note.task_id, "available": True,
                               "can_delete": can_delete, "can_generate": False,
                               "media_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
                               "location": "当前电脑 · 已保留来源", "content_url": f"/api/notes/{note.id}/media"})
            from app.services.task_original_service import TaskOriginalService
            represented = {item.get("task_id") for item in result if item.get("task_id")}
            for item in TaskOriginalService().list(owner):
                if item["task_id"] not in represented:
                    note = next((n for n in owned_notes if n.task_id == item["task_id"]), None) or referenced_notes.get(item["task_id"])
                    if note:
                        item["note_id"] = note.id
                    result.append(item)
                    represented.add(item["task_id"])
            return {"items": result, "originals_sync": False}

    def attach_task(self, owner, identifier, task_id, purpose=None):
        with session_scope() as db:
            row = db.get(LocalFileDB, identifier)
            if not row or row.owner != owner:
                raise HTTPException(404, "找不到此文件")
            row.task_id = task_id
            if purpose in {"meeting", "note"}:
                row.purpose = purpose

    def set_purpose(self, owner, identifier, purpose):
        if purpose not in {"meeting", "note"}:
            raise HTTPException(422, "请选择会议或笔记作为文件用途")
        with session_scope() as db:
            row = db.get(LocalFileDB, identifier)
            if not row or row.owner != owner:
                raise HTTPException(404, "找不到此文件")
            row.purpose = purpose
            db.flush()
            return self._info(row, self._path(row))

    @contextmanager
    def generation_lease(self, owner, identifier):
        # The local runtime has one API worker. Do not start two pipelines while
        # the first upload is still being staged and its receipt is not saved.
        key = (owner, identifier)
        with _SUBMISSION_LOCK:
            if key in _SUBMITTING:
                raise HTTPException(409, "此文件正在提交，请稍后读取状态再重试")
            _SUBMITTING.add(key)
        try:
            yield
        finally:
            with _SUBMISSION_LOCK:
                _SUBMITTING.discard(key)

    def delete(self, owner, identifier):
        with _SUBMISSION_LOCK:
            if (owner, identifier) in _SUBMITTING:
                raise HTTPException(409, "文件正在提交，请等待完成后删除")
            self._delete(owner, identifier)

    def _delete(self, owner, identifier):
        with session_scope() as db:
            row = db.get(LocalFileDB, identifier)
            if not row or row.owner != owner:
                raise HTTPException(404, "找不到此文件")
            if row.task_id:
                status = TaskArtifactService(settings.output_dir).get_status(row.task_id).get("status")
                if status not in {"success", "failed", "error", "not_found"}:
                    raise HTTPException(409, "文件仍在处理中，请等待完成后删除")
            # A previous unlink may have succeeded before its database commit
            # failed. Retrying still removes the owned index entry safely.
            self._path(row, require_exists=False).unlink(missing_ok=True)
            db.delete(row)
