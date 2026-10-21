"""Manual grouping only. Nothing here dispatches, publishes or grants media."""
import hashlib
import json
import os
import re
import stat
import time
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db_models import NoteDB
from app.models.meeting_source_link import MeetingSourceLinkDB as Link
from app.services.meeting_recording_metadata import recording_started_at


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Noncanonical UUID')
    return value


def _regular(path, *, limit=65536):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
            or getattr(path, 'is_junction', lambda: False)()):
        raise ValueError('Unverified metadata')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        if _stamp(os.fstat(stream.fileno())) != _stamp(info):
            raise ValueError('Metadata changed')
        content = stream.read(limit + 1)
        if len(content) > limit or _stamp(os.fstat(stream.fileno())) != _stamp(info):
            raise ValueError('Metadata changed')
    if _stamp(path.lstat()) != _stamp(info):
        raise ValueError('Metadata changed')
    return content.decode('utf-8')


def _present(path):
    return path.exists() or path.is_symlink()


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Invalid source version')
    return value


def _stamp(info):
    # Windows path stat and CRT fstat expose different legacy ctime semantics.
    # File identity, size and write time are comparable across both handles.
    stamp = info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    return stamp + ((info.st_ctime_ns,) if os.name != 'nt' else ())


class MeetingSourceLinkService:
    def __init__(self, session_factory=None, artifacts=None):
        from app.db import session_scope
        from app.services.task_artifact_service import TaskArtifactService
        self.sessions = session_factory or session_scope
        self.artifacts = artifacts or TaskArtifactService()

    def _folder(self, owner, task):
        task = _uuid(task)
        folder = self.artifacts.find_task_dir(task)
        if (not folder or folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)()
                or folder.resolve().parent != self.artifacts.output_dir.resolve()):
            raise ValueError('Unverified task')
        mapping = folder / '.task_id'
        if (_regular(mapping).strip() if _present(mapping) else folder.name) != task:
            raise ValueError('Task mismatch')
        if _regular(folder / 'recording_owner') != owner:
            raise ValueError('Owner mismatch')
        return folder

    def _metadata(self, owner, task, *, capture_only=False):
        folder = self._folder(owner, task)
        if _present(folder / 'source_reference.json'):
            raise ValueError('Canonical original required')
        request_path = folder / 'request.json'
        request = json.loads(_regular(request_path)) if _present(request_path) else None
        if request is not None:
            if request['request']['workflow'] != 'meeting':
                raise ValueError('Not a meeting')
        elif not capture_only:
            raise ValueError('Missing meeting workflow')
        manifest = json.loads(_regular(folder / 'source_media.json'))
        version = _sha(manifest['sha256'])
        index = folder / 'source_original.json'
        if _present(index):
            declared = json.loads(_regular(index))
            if any(declared.get(k) != v for k, v in {
                    'owner': owner, 'task_id': task, 'workflow': 'meeting'}.items()):
                raise ValueError('Original binding mismatch')
        return folder, request, manifest, version

    def _trusted_relation(self, owner, note):
        """Artifact-only preflight, deliberately independent of display fallback.

        Mirrors note_library's proven one-hop relation. No call back into its
        projected helper, so adding the manual fallback cannot recurse.
        Missing media does not weaken an existing proven relation.
        """
        try:
            folder = self._folder(owner, note.task_id)
            task = note.task_id
            reference = None
            path = folder / 'source_reference.json'
            if _present(path):
                reference = json.loads(_regular(path))
                if (set(reference) != {'version', 'owner', 'parent_task_id', 'source_version'}
                        or type(reference['version']) is not int or reference['version'] != 1
                        or reference['owner'] != owner):
                    raise ValueError('Unverified reference')
                task = reference['parent_task_id']
            _, request, _, version = self._metadata(owner, task,
                capture_only=not reference and note.source_type in {'meeting_recording', 'meeting_video'})
            if reference and reference['source_version'] != version:
                raise ValueError('Source mismatch')
            return task, version, recording_started_at(request)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def _note(self, db, owner, note_id, *, lock=False):
        try:
            _uuid(note_id)
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(404, '找不到此会议稿') from None
        query = select(NoteDB).where(NoteDB.id == note_id)
        note = db.scalar(query.with_for_update() if lock else query)
        if (not note or note.created_by != owner or note.scope != 'personal' or note.team_id
                or note.status != 'done'):
            raise HTTPException(404, '找不到此会议稿')
        if note.source_type not in {'meeting_recording', 'meeting_video'} and not self._trusted_relation(owner, note):
            raise HTTPException(409, '此内容没有可核验的会议来源，未归档')
        return note

    def _target(self, owner, task, *, verify_hash=False):
        try:
            folder, request, manifest, version = self._metadata(owner, task)
            if _present(folder / 'recording_deleted') or manifest.get('media_kind') not in {'audio', 'video'}:
                raise ValueError('Original unavailable')
            from pathlib import Path
            relative = Path(manifest['relative_path'])
            if (relative.is_absolute() or relative.drive or len(relative.parts) != 2
                    or relative.parts[0] != 'media' or '..' in relative.parts
                    or ':' in str(relative)):
                raise ValueError('Contained original required')
            directory = folder / 'media'
            source = folder / relative
            if (directory.is_symlink() or getattr(directory, 'is_junction', lambda: False)()
                    or source.resolve().parent != directory.resolve()):
                raise ValueError('Unverified original directory')
            info = source.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0
                    or type(manifest['size_bytes']) is not int or info.st_size != manifest['size_bytes']):
                raise ValueError('Invalid original file')
            if verify_hash:
                descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
                with os.fdopen(descriptor, 'rb') as stream:
                    if _stamp(os.fstat(stream.fileno())) != _stamp(info):
                        raise ValueError('Original changed')
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                    if digest.hexdigest() != version or _stamp(os.fstat(stream.fileno())) != _stamp(info):
                        raise ValueError('Original changed')
                if _stamp(source.lstat()) != _stamp(info):
                    raise ValueError('Original changed')
            started = recording_started_at(request)
            return {'canonical_task_id': task, 'source_version': version,
                    'media_kind': manifest['media_kind'], 'recording_started_at': started.isoformat() if started else None,
                    # Compatibility hint only. Clients format the ISO instant
                    # in the user's timezone, never treat this UTC label as local.
                    'display_name': started.strftime('%Y-%m-%d %H:%M UTC') if started else '录制时间未记录',
                    '_stamp': _stamp(info)}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(409, '原始录制不可用或已变化，请重新核验') from None

    def targets(self, owner):
        result = []
        seen = set()
        if not self.artifacts.output_dir.is_dir():
            return {'targets': result}
        for folder in self.artifacts.output_dir.iterdir():
            try:
                task = _regular(folder / '.task_id').strip() if _present(folder / '.task_id') else folder.name
                item = self._target(owner, task)
            except (OSError, ValueError, TypeError, HTTPException):
                continue
            if task not in seen:
                result.append({k: v for k, v in item.items() if k != '_stamp'})
                seen.add(task)
        result.sort(key=lambda item: (item['recording_started_at'] or '', item['canonical_task_id']), reverse=True)
        return {'targets': result}

    def _result(self, owner, note, row, trusted):
        if trusted:
            task, version, started = trusted
            source = {'owner_id': owner, 'canonical_task_id': task,
                      'recording_started_at': started.isoformat() if started else None}
            return {'note_id': note.id, 'revision': row.revision if row else 0,
                    'source_version': version, 'meeting_source': source, 'association_kind': 'artifact'}
        valid = row is not None and row.original_note_task_id == note.task_id
        started = None
        if valid:
            # Explicit persisted assertions survive a missing original. This
            # display projection still never grants access to that original.
            try:
                _, request, _, version = self._metadata(owner, row.canonical_task_id)
                if version == row.source_version:
                    started = recording_started_at(request)
                else:
                    valid = False
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                valid = False
        return {'note_id': note.id, 'revision': row.revision if row else 0,
                'source_version': row.source_version if row else None,
                'meeting_source': {'owner_id': owner, 'canonical_task_id': row.canonical_task_id,
                    'recording_started_at': started.isoformat() if started else None} if valid else None,
                'association_kind': 'manual' if valid else None}

    def get(self, owner, note_id):
        with self.sessions() as db:
            note = self._note(db, owner, note_id)
            return self._result(owner, note, db.get(Link, (owner, note_id)), self._trusted_relation(owner, note))

    def project(self, owner, note_id):
        """Return a display dict or None; caller keeps proven source priority.

        Call ONLY as note-library fallback. Never use this to authorize media,
        generation, ASR cache reuse, attendees or Feishu publication.
        """
        try:
            return self.get(owner, note_id)['meeting_source']
        except HTTPException:
            return None

    def confirm(self, owner, note_id, payload):
        if payload.confirmed is not True:
            raise HTTPException(422, '请明确确认原始录制')
        # Authenticate the note before hashing any target or disclosing errors.
        with self.sessions() as db:
            self._note(db, owner, note_id)
        target = self._target(owner, payload.canonical_task_id, verify_hash=True)
        if target['source_version'] != payload.source_version:
            raise HTTPException(409, '原始录制已变化，未归档')
        try:
            with self.sessions() as db:
                # SQLite lacks row-level FOR UPDATE. Serialize before reading
                # so two workers cannot both create or bypass an updated note.
                if db.get_bind().dialect.name == 'sqlite':
                    db.connection().exec_driver_sql('BEGIN IMMEDIATE')
                note = self._note(db, owner, note_id, lock=True)
                trusted = self._trusted_relation(owner, note)
                if trusted and trusted[:2] != (payload.canonical_task_id, payload.source_version):
                    raise HTTPException(409, '此稿已有可信的其他会议来源，不能覆盖')
                row = db.get(Link, (owner, note_id))
                if row:
                    if (row.canonical_task_id != payload.canonical_task_id or row.source_version != payload.source_version
                            or row.original_note_task_id != note.task_id):
                        raise HTTPException(409, '此稿已有其他归档关联，不能覆盖')
                    if payload.expected_revision not in {0, row.revision}:
                        raise HTTPException(409, '归档记录已变化，请重新读取')
                elif payload.expected_revision != 0:
                    raise HTTPException(409, '归档记录已变化，请重新读取')
                if self._target(owner, payload.canonical_task_id) != target:
                    raise HTTPException(409, '核验期间原始录制已变化，未归档')
                if not row and not trusted:
                    row = Link(owner=owner, note_id=note_id, original_note_task_id=note.task_id,
                               canonical_task_id=payload.canonical_task_id, source_version=payload.source_version,
                               revision=1, confirmed_at=time.time())
                    db.add(row)
                    db.flush()
                result = self._result(owner, note, row, trusted)
            return result
        except IntegrityError:
            raise HTTPException(409, '归档记录已变化，请重新读取') from None
