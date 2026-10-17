"""Account-scoped, optimistic text sync with immutable version history."""
import hashlib
import json
import threading
from datetime import timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.models.workspace import (
    Operation, PutNote, SharedVersion, WorkspaceNoteDB,
    WorkspaceOperationDB, WorkspaceVersionDB, now,
    WorkspaceEvidenceDB, WorkspaceVersionEvidenceDB,
)

_locks = [threading.RLock() for _ in range(64)]


def lock(owner, key):
    return _locks[int(hashlib.sha256((owner + ":" + key).encode()).hexdigest(), 16) % len(_locks)]


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class WorkspaceService:
    def operation(self, owner, operation_id, note_key):
        """Exact committed receipt, never latest content or a new execution."""
        with session_scope() as db:
            row = db.get(WorkspaceOperationDB, (owner, operation_id))
            if not row or row.note_key != note_key:
                raise HTTPException(404, "尚未找到原操作回执，请保留原意图，不自动重放")
            return {"operation_id": row.operation_id, "note_key": row.note_key,
                    "acknowledged_revision": row.revision, "status": "acknowledged"}

    @staticmethod
    def _row(db, owner, key):
        row = db.get(WorkspaceNoteDB, (owner, key))
        if not row:
            raise HTTPException(404, "未找到这份同步内容")
        return row

    def _summary(self, db, row):
        count = db.scalar(select(func.count()).select_from(WorkspaceVersionDB).where(
            WorkspaceVersionDB.owner == row.owner, WorkspaceVersionDB.note_key == row.key))
        return {"key": row.key, "title": row.title, "source_type": row.source_type,
                "source_device": row.source_device, "revision": row.revision,
                "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
                "deleted": row.deleted, "archived": row.archived, "version_count": count}

    def _detail(self, db, row, offset=0, limit=50):
        versions = list(db.scalars(select(WorkspaceVersionDB).where(
            WorkspaceVersionDB.owner == row.owner, WorkspaceVersionDB.note_key == row.key,
        ).order_by(WorkspaceVersionDB.created_at.desc(), WorkspaceVersionDB.id).offset(offset).limit(limit + 1)))
        evidence = {v.version_id: v.evidence_revision for v in db.scalars(select(WorkspaceVersionEvidenceDB).where(
            WorkspaceVersionEvidenceDB.owner == row.owner, WorkspaceVersionEvidenceDB.note_key == row.key,
            WorkspaceVersionEvidenceDB.version_id.in_([v.id for v in versions[:limit]])))}
        return {**self._summary(db, row), "content": row.content,
                "transcript": json.loads(row.transcript_json), "metadata": json.loads(row.metadata_json),
                "versions": [{"id": v.id, "title": v.title, "content": v.content, "kind": v.kind,
                              "model": v.model, "parent_id": v.parent_id, "created_at": iso(v.created_at),
                              "evidence_revision": evidence.get(v.id)}
                             for v in versions[:limit]],
                "next_versions_offset": offset + limit if len(versions) > limit else None}

    def get(self, owner, key, versions_offset=0, versions_limit=50):
        with session_scope() as db:
            return self._detail(db, self._row(db, owner, key), versions_offset, versions_limit)

    def list(self, owner, offset=0, limit=50, include_deleted=False):
        with session_scope() as db:
            query = select(WorkspaceNoteDB).where(WorkspaceNoteDB.owner == owner)
            if not include_deleted:
                query = query.where(WorkspaceNoteDB.deleted.is_(False))
            rows = list(db.scalars(query.order_by(WorkspaceNoteDB.created_at.desc(), WorkspaceNoteDB.key)
                                  .offset(offset).limit(limit + 1)))
            return {"items": [self._summary(db, row) for row in rows[:limit]],
                    "next_offset": offset + limit if len(rows) > limit else None}

    def _conflict(self, db, row):
        raise HTTPException(409, {"code": "REVISION_CONFLICT",
                                 "message": "另一台设备已更新，当前草稿已保留，请比较后保存",
                                 "current": self._detail(db, row)})

    @staticmethod
    def _replay(db, owner, key, operation_id, fingerprint):
        operation = db.get(WorkspaceOperationDB, (owner, operation_id))
        if not operation:
            return None
        if operation.note_key != key or operation.digest != fingerprint:
            raise HTTPException(409, {"code": "OPERATION_REUSED", "message": "操作标识已使用，请刷新后重新保存"})
        return operation

    def _append_version(self, db, row, version, evidence_revision=None):
        old = db.get(WorkspaceVersionDB, (row.owner, row.key, version.id))
        if old:
            if old.content != version.content or old.title != version.title:
                raise HTTPException(409, {"code": "VERSION_IMMUTABLE", "message": "历史版本不能被覆盖，请保存为新版本"})
            return
        db.add(WorkspaceVersionDB(owner=row.owner, note_key=row.key, **version.model_dump()))
        if evidence_revision is not None:
            db.add(WorkspaceVersionEvidenceDB(owner=row.owner, note_key=row.key,
                version_id=version.id, evidence_revision=evidence_revision))
        db.flush()

    def put(self, owner, key, payload: PutNote, *, version_evidence=None):
        from app.services.workspace_attachment_service import WorkspaceAttachmentService
        WorkspaceAttachmentService().validate_references(owner, [payload.content, *(v.content for v in payload.versions)])
        fingerprint = digest({"key": key, "action": "put", **payload.model_dump(mode="json", exclude_unset=True)})
        try:
            with lock(owner, key), session_scope() as db:
                replay = self._replay(db, owner, key, payload.operation_id, fingerprint)
                if replay:
                    # A replay must never roll the client back to an earlier revision.
                    result = self._detail(db, self._row(db, owner, key))
                    return {**result, "acknowledged_revision": replay.revision}
                row = db.get(WorkspaceNoteDB, (owner, key))
                if row:
                    if row.revision != payload.base_revision or row.deleted:
                        self._conflict(db, row)
                    if not db.get(WorkspaceEvidenceDB, (owner, key, row.revision)):
                        db.add(WorkspaceEvidenceDB(owner=owner, note_key=key, revision=row.revision,
                            transcript_json=row.transcript_json, metadata_json=row.metadata_json))
                    claimed = db.execute(update(WorkspaceNoteDB).where(
                        WorkspaceNoteDB.owner == owner, WorkspaceNoteDB.key == key,
                        WorkspaceNoteDB.revision == payload.base_revision,
                        WorkspaceNoteDB.deleted.is_(False),
                    ).values(revision=payload.base_revision + 1))
                    if claimed.rowcount != 1:
                        db.expire(row)
                        self._conflict(db, row)
                    if row.content != payload.content or row.title != payload.title.strip():
                        self._append_version(db, row, SharedVersion(
                            id=f"__vinote:saved:{payload.base_revision}", title=row.title, content=row.content,
                            kind="edit", created_at=row.updated_at), payload.base_revision)
                    row.revision = payload.base_revision + 1
                else:
                    if payload.base_revision:
                        raise HTTPException(409, {"code": "REVISION_CONFLICT", "message": "内容已不存在，请保留草稿并刷新", "current": None})
                    row = WorkspaceNoteDB(owner=owner, key=key, title=payload.title.strip(), content=payload.content, revision=1)
                    db.add(row)
                    db.flush()
                row.title = payload.title.strip()
                row.content = payload.content
                row.source_type = payload.source_type
                # Editing text on another device does not relocate the source media.
                if not row.source_device:
                    row.source_device = payload.source_device
                row.archived = payload.archived
                if "transcript" in payload.model_fields_set:
                    row.transcript_json = payload.transcript.model_dump_json() if payload.transcript else "null"
                if "metadata" in payload.model_fields_set:
                    previous = json.loads(row.metadata_json)
                    incoming = payload.metadata.model_dump(mode="json", exclude_none=True)
                    for field in ("media_id", "source_device_id"):
                        if previous.get(field):
                            incoming[field] = previous[field]
                    row.metadata_json = json.dumps({**previous, **incoming}, ensure_ascii=False)
                row.updated_at = now()
                db.add(WorkspaceEvidenceDB(owner=owner, note_key=key, revision=row.revision,
                    transcript_json=row.transcript_json, metadata_json=row.metadata_json))
                for version in payload.versions:
                    if version.id.startswith("__vinote:") and not db.get(WorkspaceVersionDB, (owner, key, version.id)):
                        raise HTTPException(422, "内部版本标识不可用于新建版本")
                    self._append_version(db, row, version, (version_evidence or {}).get(version.id))
                # Every accepted current body is reachable from history, including initial import.
                self._append_version(db, row, SharedVersion(
                    id=f"__vinote:current:{row.revision}", title=row.title, content=row.content,
                    kind="edit" if row.revision > 1 else "imported", created_at=row.updated_at), row.revision)
                db.add(WorkspaceOperationDB(owner=owner, operation_id=payload.operation_id, note_key=key,
                                            digest=fingerprint, revision=row.revision))
                db.flush()
                return self._detail(db, row)
        except IntegrityError:
            # Another worker may have committed the same create/retry concurrently.
            with session_scope() as db:
                replay = self._replay(db, owner, key, payload.operation_id, fingerprint)
                row = db.get(WorkspaceNoteDB, (owner, key))
                if replay and row:
                    return {**self._detail(db, row), "acknowledged_revision": replay.revision}
                if row:
                    self._conflict(db, row)
            raise HTTPException(409, "内容同时发生变更，请保留草稿后刷新") from None

    def set_deleted(self, owner, key, payload: Operation, deleted):
        fingerprint = digest({"key": key, "action": "delete" if deleted else "restore", **payload.model_dump()})
        with lock(owner, key), session_scope() as db:
            replay = self._replay(db, owner, key, payload.operation_id, fingerprint)
            row = self._row(db, owner, key)
            if replay:
                return self._detail(db, row)
            if row.revision != payload.base_revision:
                self._conflict(db, row)
            changed = db.execute(update(WorkspaceNoteDB).where(
                WorkspaceNoteDB.owner == owner, WorkspaceNoteDB.key == key,
                WorkspaceNoteDB.revision == payload.base_revision,
            ).values(deleted=deleted, revision=payload.base_revision + 1, updated_at=now()))
            if changed.rowcount != 1:
                db.expire(row)
                self._conflict(db, row)
            db.add(WorkspaceOperationDB(owner=owner, operation_id=payload.operation_id, note_key=key,
                                        digest=fingerprint, revision=payload.base_revision + 1))
            db.flush()
            db.refresh(row)
            return self._detail(db, row)

    def version(self, owner, key, version_id):
        with session_scope() as db:
            self._row(db, owner, key)
            version = db.get(WorkspaceVersionDB, (owner, key, version_id))
            if not version:
                raise HTTPException(404, "历史版本不存在")
            return {"title": version.title, "content": version.content}

    def evidence(self, owner, key, revision):
        with session_scope() as db:
            self._row(db, owner, key)
            row = db.get(WorkspaceEvidenceDB, (owner, key, revision))
            if not row:
                raise HTTPException(404, "此历史版本没有保存原文快照，请查看当前逐字稿")
            return {"revision": revision, "transcript": json.loads(row.transcript_json),
                    "metadata": json.loads(row.metadata_json)}
