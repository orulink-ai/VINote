"""Read-only original identity for library grouping; grants no media access."""
import json
import stat
from uuid import UUID

from sqlalchemy import select

from app.db import session_scope
from app.models.local_file import LocalFileDB


def original_source(note, owner, artifacts, sessions=session_scope):
    def read(path):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536
                or getattr(path, 'is_junction', lambda: False)()):
            raise ValueError('Unverified metadata')
        return path.read_text(encoding='utf-8')

    def folder_for(task):
        if str(UUID(task)) != task:
            raise ValueError('Invalid task')
        folder = artifacts.find_task_dir(task)
        if (not folder or folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)()
                or folder.resolve().parent != artifacts.output_dir.resolve()):
            raise ValueError('Unverified folder')
        mapping = folder / '.task_id'
        if (read(mapping).strip() if mapping.exists() or mapping.is_symlink() else folder.name) != task:
            raise ValueError('Task mismatch')
        if read(folder / 'recording_owner') != owner:
            raise ValueError('Owner mismatch')
        return folder

    try:
        if not note.task_id or note.scope != 'personal':
            return None
        folder = folder_for(note.task_id)
        canonical = note.task_id
        reference_path = folder / 'source_reference.json'
        reference = None
        if reference_path.exists() or reference_path.is_symlink():
            reference = json.loads(read(reference_path))
            if (not isinstance(reference, dict)
                    or set(reference) != {'version', 'owner', 'parent_task_id', 'source_version'}
                    or type(reference['version']) is not int or reference['version'] != 1
                    or reference['owner'] != owner):
                raise ValueError('Invalid reference')
            canonical = reference['parent_task_id']
            folder = folder_for(canonical)
            if (folder / 'source_reference.json').exists() or (folder / 'source_reference.json').is_symlink():
                raise ValueError('Reference chain')
        # Registered documents retain their original outside the task folder.
        # Only a unique owned DB association establishes that identity.
        with sessions() as db:
            rows = db.scalars(select(LocalFileDB).where(
                LocalFileDB.owner == owner, LocalFileDB.task_id == canonical)).all()
            file_id = rows[0].id if len(rows) == 1 else None
        if reference is None and file_id:
            return dict(owner_id=owner, original_id='file:' + file_id, canonical_task_id=canonical)
        request = json.loads(read(folder / 'request.json'))
        if request['request']['workflow'] not in {'meeting', 'note_organization'}:
            raise ValueError('Unknown workflow')
        manifest = json.loads(read(folder / 'source_media.json'))
        fingerprint = manifest['sha256']
        if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                or any(c not in '0123456789abcdef' for c in fingerprint)
                or reference and reference['source_version'] != fingerprint):
            raise ValueError('Source mismatch')
        return dict(owner_id=owner, original_id=('file:' + file_id) if file_id else 'task:' + canonical,
                    canonical_task_id=canonical)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
