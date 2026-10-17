"""Narrow owner-bound source references. No client paths, media copies or cycles."""
import threading
import uuid
from fastapi import HTTPException
from app.services.task_generation_context import _read_json

SOURCE_LOCK = threading.RLock()


def resolve_reference(artifacts, folder):
    from app.services.task_original_service import TaskOriginalService
    try:
        reference = _read_json(folder / 'source_reference.json')
        if set(reference) != {'version', 'owner', 'parent_task_id', 'source_version'} or reference['version'] != 1:
            return None
        owner = (folder / 'recording_owner')
        if owner.is_symlink() or owner.read_text(encoding='utf-8') != reference['owner']:
            return None
        parent = reference['parent_task_id']
        if str(uuid.UUID(parent)) != parent:
            return None
        parent_folder = artifacts.find_task_dir(parent)
        if not parent_folder or (parent_folder / 'source_reference.json').exists():
            return None  # No chains/cycles; canonical original only.
        _, source = TaskOriginalService().get(reference['owner'], 'task:' + parent)
        manifest = _read_json(parent_folder / 'source_media.json')
        if manifest['sha256'] != reference['source_version']:
            return None
        return source
    except (OSError, ValueError, KeyError, TypeError, HTTPException):
        return None


def assert_unreferenced(artifacts, folder):
    """Persisted references also protect originals across worker restarts.

    Keep protection after completion: saved children still need playback. A
    later explicit reference lifecycle must release it; do not infer from EOF.
    """
    parent = (folder / '.task_id').read_text(encoding='utf-8') if (folder / '.task_id').is_file() else folder.name
    for child in artifacts.output_dir.iterdir():
        reference = child / 'source_reference.json'
        if reference.exists():
            try:
                if _read_json(reference).get('parent_task_id') == parent:
                    raise HTTPException(409, '原文件仍被处理记录引用，请保留原文件。')
            except HTTPException as exc:
                if exc.status_code == 409:
                    raise  # Corrupt reference fails closed rather than deleting.
