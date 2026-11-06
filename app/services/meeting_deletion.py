"""Durable, owner-scoped deletion of a canonical meeting on the local runtime."""
import json
import shutil
import uuid
import hashlib
import os
from pathlib import Path
import stat
import time
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.config import settings
from app.db import session_scope
from app.db_models import FeishuDeliveryDB, MeetingDeletionDB, NoteDB, NoteVersionDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.feishu_native_images import FeishuNativeImagePlanDB
from app.models.local_file import LocalFileDB
from app.models.meeting_source_link import MeetingDisplayDB, MeetingSourceLinkDB
from app.services.local_file_service import LocalFileService, _SUBMISSION_LOCK, _SUBMITTING
from app.services.retained_task_source import SOURCE_LOCK
from app.services.task_artifact_service import TaskArtifactService


def deleted_task(db, task_id):
    if not task_id:
        return False
    return any(task_id in json.loads(row.plan_json)['task_ids']
               for row in db.scalars(select(MeetingDeletionDB)))


def deleted_note(db, note_key):
    if not isinstance(note_key, str):
        return False
    unwrapped = note_key.removeprefix('publish:')
    aliases = {note_key, unwrapped, unwrapped.removeprefix('desktop-')}
    return any(aliases.intersection(json.loads(row.plan_json)['note_ids'])
               for row in db.scalars(select(MeetingDeletionDB)))


@contextmanager
def _deletion_transaction(owner, task_id):
    # A 409 before a receipt exists proves that nothing was committed. Failures
    # after a durable receipt must instead be retried using that same receipt.
    with session_scope() as db:
        try:
            yield db
        except HTTPException as exc:
            if exc.status_code in {404, 409} and db.get(MeetingDeletionDB, (owner, task_id)) is None:
                message = exc.detail.get('message', '会议删除未开始') if isinstance(exc.detail, dict) else str(exc.detail)
                raise HTTPException(exc.status_code, {'code': 'deletion_not_started', 'message': message}) from None
            raise


def _scrub_feishu(db, owner, note_ids):
    rows = db.scalars(select(FeishuAutoOutboxDB).where(
        FeishuAutoOutboxDB.user_id == owner, FeishuAutoOutboxDB.note_id.in_(note_ids))).all()
    # A submitting worker may hold a detached copy of the plaintext and can
    # still cross the network boundary. Do not claim deletion while it runs.
    if any(row.status == 'submitting' for row in rows):
        raise HTTPException(409, '飞书交付正在提交，请等待处理结果后再删除会议')
    if db.scalar(select(FeishuAutoOutboxDB.id).where(
            FeishuAutoOutboxDB.user_id == owner,
            FeishuAutoOutboxDB.status == 'submitting',
            FeishuAutoOutboxDB.note_id.not_in(note_ids)).limit(1)):
        raise HTTPException(409, '飞书还有正在提交的交付，请等待完成后再删除会议')
    owners = {owner, *(row.cloud_owner for row in rows if row.cloud_owner)}
    aliases = (set(note_ids) | {'publish:' + ident for ident in note_ids}
               | {'desktop-' + ident for ident in note_ids}
               | {'publish:desktop-' + ident for ident in note_ids})
    # Legacy device-only workspace keys have no server-side mapping to a note.
    # While an owned delivery with such a key is in flight its relationship is
    # unknown, so avoid deleting under a detached, potentially related body.
    unknown_active = db.scalar(select(FeishuDeliveryDB.id).where(
        FeishuDeliveryDB.owner.in_(owners),
        FeishuDeliveryDB.status.in_(['queued', 'processing']),
        FeishuDeliveryDB.note_key.not_in(aliases)).limit(1))
    if unknown_active:
        raise HTTPException(409, '飞书还有正在处理的交付，请等待完成后再删除会议')
    jobs = db.scalars(select(FeishuDeliveryDB).where(
        FeishuDeliveryDB.owner.in_(owners), FeishuDeliveryDB.note_key.in_(aliases))).all()
    for job in jobs:
        try:
            lease = float(job.lease_until or 0)
        except (TypeError, ValueError):
            _conflict()
        if job.status in {'queued', 'processing'} or lease > time.time():
            raise HTTPException(409, '飞书交付正在处理，请等待处理结果后再删除会议')
    for row in rows:
        row.payload = '{}'
        if row.status in {'queued', 'waiting_participants'}:
            row.status, row.error = 'cancelled', '会议已删除，尚未提交的自动交付已取消'
    for job in jobs:
        job.title, job.content = '', ''
        meta = db.get(FeishuDeliveryDestinationDB, job.id)
        if meta:
            # Segments and graphical snapshots can contain the frozen body.
            meta.snapshot = '{}'
        image_plan = db.get(FeishuNativeImagePlanDB, job.id)
        if image_plan:
            # The native-image journal embeds converted text blocks too.
            image_plan.manifest = '{}'


def _conflict():
    raise HTTPException(409, '会议正在处理或关联无法安全核验，未完成删除')


def _clean_path(path):
    return not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)()


def verified_meeting(db, owner, task_id, artifacts):
    """Verify task identity independently of whether its original still exists."""
    from app.services.meeting_source_link import MeetingSourceLinkService, _present, _regular, _stamp
    from contextlib import nullcontext
    links = MeetingSourceLinkService(lambda: nullcontext(db), artifacts)
    try:
        folder = links._folder(owner, task_id)
        if _present(folder / 'source_reference.json'):
            raise ValueError('Canonical task required')
        notes = db.scalars(select(NoteDB).where(NoteDB.task_id == task_id,
            NoteDB.created_by == owner, NoteDB.scope == 'personal', NoteDB.team_id.is_(None))).all()
        meeting_note = any(note.source_type in {'meeting_recording', 'meeting_video'} for note in notes)
        meeting_file = db.scalar(select(LocalFileDB.id).where(LocalFileDB.owner == owner,
            LocalFileDB.task_id == task_id, LocalFileDB.purpose == 'meeting').limit(1))
        request_path = folder / 'request.json'
        if _present(request_path):
            request = json.loads(_regular(request_path))
            if request['request']['workflow'] != 'meeting':
                raise ValueError('Not a meeting')
        elif not meeting_note and not meeting_file:
            raise ValueError('Missing meeting evidence')
        manifest_path = folder / 'source_media.json'
        if not _present(manifest_path):
            if not notes and not meeting_file:
                raise ValueError('Missing source evidence')
            # No source version means no child reference can be trusted.
            if _present(folder / 'source_original.json'):
                index = json.loads(_regular(folder / 'source_original.json'))
                if any(index.get(k) != v for k, v in {'owner': owner, 'task_id': task_id, 'workflow': 'meeting'}.items()):
                    raise ValueError('Original binding mismatch')
            return folder, None
        folder, _, manifest, version = links._metadata(owner, task_id, capture_only=bool(meeting_note or meeting_file))
        relative = Path(manifest['relative_path'])
        if (relative.is_absolute() or relative.drive or len(relative.parts) != 2
                or relative.parts[0] != 'media' or '..' in relative.parts or ':' in str(relative)):
            raise ValueError('Invalid source path')
        directory, source = folder / 'media', folder / relative
        if not _clean_path(directory) or not _clean_path(source) or source.resolve().parent != directory.resolve():
            raise ValueError('Invalid source path')
        if source.exists():
            info = source.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or type(manifest['size_bytes']) is not int
                    or info.st_size != manifest['size_bytes']):
                raise ValueError('Source changed')
            digest = hashlib.sha256()
            descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                if _stamp(os.fstat(stream.fileno())) != _stamp(info):
                    raise ValueError('Source changed')
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
                if _stamp(os.fstat(stream.fileno())) != _stamp(info):
                    raise ValueError('Source changed')
            if digest.hexdigest() != version or _stamp(source.lstat()) != _stamp(info):
                raise ValueError('Source changed')
        return folder, version
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, '会议归属或来源无法安全核验，未完成删除') from None


def delete_meeting(owner, task_id):
    try:
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(404, {'code': 'deletion_not_started', 'message': '找不到此会议'}) from None
    # All local generation paths use one of these runtime locks. Database
    # tombstones remain authoritative after a restart.
    from app.routers.note import _FILE_TASK_LOCK, _ACTIVE_FILE_TASKS
    with SOURCE_LOCK, _FILE_TASK_LOCK, _SUBMISSION_LOCK:
        with _deletion_transaction(owner, task_id) as db:
            if db.get_bind().dialect.name != 'sqlite':
                _conflict()
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            receipt = db.get(MeetingDeletionDB, (owner, task_id))
            if receipt:
                plan = json.loads(receipt.plan_json)
            else:
                artifacts = TaskArtifactService(settings.output_dir)
                folder, source_version = verified_meeting(db, owner, task_id, artifacts)
                if not folder or not _clean_path(folder) or folder.resolve().parent != settings.output_dir.resolve():
                    _conflict()
                folders = [folder]
                task_ids = [task_id]
                for child in settings.output_dir.iterdir():
                    ref = child / 'source_reference.json'
                    if not ref.exists() and not ref.is_symlink():
                        continue
                    try:
                        if not _clean_path(child) or not _clean_path(ref):
                            _conflict()
                        reference = json.loads(ref.read_text(encoding='utf-8'))
                        if reference.get('parent_task_id') != task_id:
                            continue
                        child_id = (child / '.task_id').read_text(encoding='utf-8').strip() if (child / '.task_id').exists() else child.name
                        if (set(reference) != {'version', 'owner', 'parent_task_id', 'source_version'}
                                or reference.get('version') != 1 or not source_version or reference.get('source_version') != source_version
                                or str(uuid.UUID(child_id)) != child_id or reference.get('owner') != owner
                                or artifacts.find_task_dir(child_id) != child
                                or (child / 'recording_owner').read_text(encoding='utf-8') != owner):
                            _conflict()
                        folders.append(child)
                        task_ids.append(child_id)
                    except (OSError, ValueError, TypeError, KeyError):
                        _conflict()
                for ident, path in zip(task_ids, folders):
                    try:
                        state = json.loads((path / 'status.json').read_text(encoding='utf-8'))['status']
                        if state not in {'success', 'failed', 'error'} or ident in _ACTIVE_FILE_TASKS:
                            _conflict()
                        if any(not _clean_path(p) for p in path.rglob('*')):
                            _conflict()
                    except (OSError, ValueError, KeyError):
                        _conflict()
                for child in settings.output_dir.iterdir():
                    ref = child / 'source_reference.json'
                    if ref.exists():
                        try:
                            target = json.loads(ref.read_text(encoding='utf-8')).get('parent_task_id')
                            if target in task_ids and target != task_id:
                                _conflict()
                        except (OSError, ValueError, TypeError):
                            _conflict()
                links = db.scalars(select(MeetingSourceLinkDB).where(MeetingSourceLinkDB.canonical_task_id == task_id)).all()
                if any(link.owner != owner for link in links):
                    _conflict()
                linked_ids = [link.note_id for link in links]
                notes = db.scalars(select(NoteDB).where((NoteDB.task_id.in_(task_ids)) | (NoteDB.id.in_(linked_ids)))).all()
                if any(n.created_by != owner or n.scope != 'personal' or n.team_id for n in notes):
                    _conflict()
                if len({n.id for n in notes} & set(linked_ids)) != len(set(linked_ids)):
                    _conflict()
                files = db.scalars(select(LocalFileDB).where(LocalFileDB.task_id.in_(task_ids))).all()
                if any(f.owner != owner or (owner, f.id) in _SUBMITTING for f in files):
                    _conflict()
                file_paths = []
                for file in files:
                    path = LocalFileService()._path(file, require_exists=False)
                    if path.name != file.id + path.suffix.lower():
                        _conflict()
                    file_paths.append(str(path))
                plan = {'task_ids': task_ids, 'note_ids': sorted(n.id for n in notes),
                        'folders': [p.name for p in folders], 'files': file_paths}
                _scrub_feishu(db, owner, plan['note_ids'])
                db.add(MeetingDeletionDB(owner=owner, task_id=task_id, plan_json=json.dumps(plan), state='pending'))
                db.execute(delete(NoteVersionDB).where(NoteVersionDB.note_id.in_(plan['note_ids'])))
                db.execute(delete(MeetingSourceLinkDB).where(MeetingSourceLinkDB.note_id.in_(plan['note_ids'])))
                db.execute(delete(NoteDB).where(NoteDB.id.in_(plan['note_ids'])))
                db.execute(delete(LocalFileDB).where(LocalFileDB.id.in_([f.id for f in files])))
                db.execute(delete(MeetingDisplayDB).where(MeetingDisplayDB.owner == owner,
                    MeetingDisplayDB.source_key.in_(['task:' + t for t in task_ids] + ['file:' + f.id for f in files])))
        # A committed plan survives interruption or an unlink failure. Repeating
        # this request resumes cleanup using only validated contained paths.
        try:
            root = (settings.data_dir / 'local-files' /
                    hashlib.sha256(owner.encode()).hexdigest()[:32]).resolve()
            for raw in plan['files']:
                path = Path(raw)
                if not _clean_path(path) or path.resolve().parent != root:
                    _conflict()
                path.unlink(missing_ok=True)
            root = settings.output_dir.resolve()
            for name in plan['folders']:
                folder = root / name
                if Path(name).name != name or not _clean_path(folder) or folder.resolve().parent != root:
                    _conflict()
                if folder.exists():
                    if any(not _clean_path(p) for p in folder.rglob('*')):
                        _conflict()
                    shutil.rmtree(folder)
        except OSError as exc:
            raise HTTPException(409, '会议删除尚未完成，请关闭占用文件后重试') from exc
        with session_scope() as db:
            db.get(MeetingDeletionDB, (owner, task_id)).state = 'done'
        return {'deleted': True, 'note_ids': plan['note_ids'], 'task_ids': plan['task_ids']}
