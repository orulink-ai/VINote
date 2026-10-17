"""Owner-bound index of retained task originals; no copy and no generation."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from app.config import settings
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_failure import recovery_status

class TaskOriginalService:
    def _folder(self, folder):
        root = settings.output_dir.resolve()
        return not folder.is_symlink() and folder.resolve().parent == root

    def info(self, owner, folder):
        if folder and (folder / "source_reference.json").exists():
            return None
        try:
            if not self._folder(folder):
                return None
            for name in (".task_id", "recording_owner", "request.json", "source_media.json"):
                if (folder / name).is_symlink():
                    return None
            if (folder / "recording_owner").read_text(encoding="utf-8") != owner or (folder / "recording_deleted").exists():
                return None
            mapping = folder / ".task_id"
            task_id = mapping.read_text(encoding="utf-8").strip() if mapping.exists() else folder.name
            if str(uuid.UUID(task_id)) != task_id:
                return None
            request = json.loads((folder / "request.json").read_text(encoding="utf-8"))["request"]
            if not isinstance(request, dict):
                return None
            workflow = request.get("workflow")
            if workflow not in {"meeting", "note_organization"}:
                return None  # No guess based on file format or title.
            artifacts = TaskArtifactService(settings.output_dir)
            source = artifacts.resolve_source_media(folder)
            if not source or (folder / "media").is_symlink() or source.parent != (folder / "media").resolve():
                return None
            from app.services.local_file_service import ALLOWED, MEDIA, AUDIO
            if source.suffix.lower() not in ALLOWED:
                return None
            marker = folder / "source_original.json"
            if marker.is_symlink():
                return None
            index = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
            if marker.exists() and (not isinstance(index, dict) or any(index.get(k) != v for k, v in {"owner": owner, "task_id": task_id, "workflow": workflow}.items())):
                return None
            title = (index or {}).get("filename") or request.get("title") or ("会议资料" if workflow == "meeting" else "来源文件")
            filename = Path(str(title).replace("\\", "/")).name[:250]
            if not filename or filename.startswith(("source_audio.", "source_video.")):
                filename = "来源文件"
            import mimetypes
            status = recovery_status(artifacts.get_status(task_id))
            info = {"id": "task:" + task_id, "filename": filename, "title": filename,
                "task_id": task_id, "purpose": "meeting" if workflow == "meeting" else "note",
                "source_type": "meeting_video" if workflow == "meeting" and source.suffix.lower() in MEDIA else "meeting_recording" if workflow == "meeting" else "video" if source.suffix.lower() in MEDIA else "audio",
                "category": "video" if source.suffix.lower() in MEDIA else "recording" if source.suffix.lower() in AUDIO else "file",
                "size_bytes": source.stat().st_size,
                "created_at": (index or {}).get("created_at") or datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
                "available": True, "can_delete": False, "can_generate": False,
                "media_type": mimetypes.guess_type("original" + source.suffix.lower())[0] or "application/octet-stream",
                "location": "当前电脑 · 已保留来源", "content_url": "/api/files/task:" + task_id + "/content",
                "processing_status": status.get("status"), "error_code": status.get("error_code"),
                "retryable": status.get("retryable") is True}
            return info, source
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def register(self, owner, folder, filename):
        verified = self.info(owner, folder)
        if not verified:
            return
        info, _ = verified
        manifest = folder / "source_original.json"
        if manifest.exists():
            return
        payload = {"owner": owner, "task_id": info["task_id"],
                   "workflow": "meeting" if info["purpose"] == "meeting" else "note_organization",
                   "filename": Path(str(filename or info["filename"]).replace("\\", "/")).name[:250],
                   "created_at": info["created_at"]}
        temporary = folder / (".source_original." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(manifest)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self, owner):
        if not settings.output_dir.is_dir():
            return []
        result = []
        for folder in settings.output_dir.iterdir():
            if folder.is_dir():
                entry = self.info(owner, folder)
                if entry:
                    result.append(entry[0])
        return result

    def get(self, owner, identifier):
        if not identifier.startswith("task:"):
            raise HTTPException(404, "找不到此文件")
        task_id = identifier[5:]
        try:
            if str(uuid.UUID(task_id)) != task_id:
                raise ValueError()
        except ValueError:
            raise HTTPException(404, "找不到此文件") from None
        folder = TaskArtifactService(settings.output_dir).find_task_dir(task_id)
        result = self.info(owner, folder) if folder else None
        if not result:
            raise HTTPException(404, "找不到此文件")
        return result
