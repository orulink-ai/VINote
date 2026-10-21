"""Read an owned retained original's OS location; never copy, repair or proxy."""
import json
import stat
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.db import session_scope
from app.db_models import NoteDB
from app.services.local_file_service import LocalFileService
from app.services.note_repository import NoteRepository
from app.services.task_artifact_service import TaskArtifactService


def _missing():
    return HTTPException(404, "当前设备找不到可核验的原文件")


def local_file(path: Path) -> Path:
    """No URLs, UNC/device paths, links, junctions, directories or derivatives."""
    raw = str(path)
    if (not path.is_absolute() or raw.startswith(("\\\\", "//")) or "://" in raw
            or any(ord(c) < 32 or ord(c) == 127 for c in raw) or ".." in path.parts):
        raise _missing()
    try:
        for part in (path, *path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(part, "is_junction", lambda: False)():
                raise _missing()
        if not stat.S_ISREG(path.lstat().st_mode):
            raise _missing()
        return path.resolve(strict=True)
    except OSError:
        raise _missing() from None


def _text(path, maximum=65536):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum
            or getattr(path, "is_junction", lambda: False)()):
        raise _missing()
    return path.read_text(encoding="utf-8")


class OriginalLocationService:
    def __init__(self):
        self.artifacts = TaskArtifactService(settings.output_dir)

    @staticmethod
    def _result(path, filename=None):
        path = local_file(Path(path))
        return {"local_path_protocol": 1, "absolute_path": str(path), "filename": filename or path.name}

    def file(self, owner, identifier):
        # Same owned resolver as /files/{identifier}/content, including task: IDs.
        info, path = LocalFileService().get(owner, identifier)
        return self._result(path, info["filename"])

    def _folder(self, owner, task_id):
        if not isinstance(task_id, str) or str(uuid.UUID(task_id)) != task_id:
            raise _missing()
        folder = self.artifacts.find_task_dir(task_id)
        if (folder is None or folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
                or folder.resolve().parent != self.artifacts.output_dir.resolve()
                or (folder / "recording_deleted").exists()):
            raise _missing()
        mapping = folder / ".task_id"
        identity = _text(mapping, 100).strip() if mapping.exists() or mapping.is_symlink() else folder.name
        if identity != task_id or _text(folder / "recording_owner", 512) != owner:
            raise _missing()
        return folder

    def _task_source(self, owner, task_id):
        try:
            folder = self._folder(owner, task_id)
            reference_path = folder / "source_reference.json"
            canonical = folder
            if reference_path.exists() or reference_path.is_symlink():
                reference = json.loads(_text(reference_path))
                if (not isinstance(reference, dict) or set(reference) != {
                        "version", "owner", "parent_task_id", "source_version"}
                        or type(reference["version"]) is not int or reference["version"] != 1
                        or reference["owner"] != owner):
                    raise _missing()
                canonical = self._folder(owner, reference["parent_task_id"])
                if (canonical / "source_reference.json").exists() or (canonical / "source_reference.json").is_symlink():
                    raise _missing()
            # Existing resolver validates the declared original (including the
            # owner-bound single-hop reference); never fall back to audio_meta,
            # arbitrary media globbing or a playback derivative.
            local_file(canonical / "source_media.json")
            source = self.artifacts.resolve_source_media(folder)
            if source is None:
                raise _missing()
            source = local_file(source)
            media = canonical / "media"
            if media.is_symlink() or getattr(media, "is_junction", lambda: False)() or source.parent != media.resolve():
                raise _missing()
            return source
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise _missing() from None

    def task(self, owner, task_id):
        return self._result(self._task_source(owner, task_id))

    def note(self, owner, note_id):
        note = NoteRepository().get_note(owner, note_id)
        # Team read access to a note does not reveal the author's OS paths.
        if note is None or not note.task_id:
            raise _missing()
        with session_scope() as db:
            record = db.get(NoteDB, note_id)
            if record is None or record.created_by != owner or record.task_id != note.task_id:
                raise _missing()
        return self._result(self._task_source(owner, note.task_id))
