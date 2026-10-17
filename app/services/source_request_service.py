"""Durable owner-scoped source POST claims, without generation or remote replay.

Validate the source and effective options before reserve(). Only created=True
may stage/queue a task. An existing reserved receipt is deliberately uncertain:
never queue it automatically, even after a worker restart. Use the same task's
explicit recovery path after inspecting its artifacts. accept() records the
submission response, not completion of generation. GET performs no dispatch.
"""
import hashlib
import json
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.db_models import SourceRequestDB
from app.models.source_request import SourceRequestReceipt, SourceSubmission


def _identity(owner, operation_id):
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
        raise HTTPException(401, "请登录后提交或查询来源任务")
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", operation_id):
        raise HTTPException(422, "来源提交操作标识格式无效")


def _fingerprint(submission):
    payload = submission.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt(row, *, created=False):
    saved = json.loads(row.receipt_json or "{}")
    return SourceRequestReceipt(operation_id=row.operation_id, task_id=row.task_id,
                                state=row.state, status=saved.get("status", "reserved"),
                                source_type=saved.get("source_type"), created=created)


def _conflict():
    raise HTTPException(409, {"code": "SOURCE_OPERATION_REUSED",
                             "message": "该提交标识已用于其他来源或选项，请保留原任务并核验"})


class SourceRequestService:
    def __init__(self, sessions=None):
        self.sessions = sessions or session_scope

    def reserve(self, owner: str, operation_id: str, submission: SourceSubmission,
                *, task_id: str | None = None) -> SourceRequestReceipt:
        """Reserve once. DB uniqueness, not process locks, selects the winner.

        task_id may bind an already verified retained-file task. The router must
        supply server-hashed upload identities and owner-verified file versions;
        a client's alleged digest is insufficient. Persist only the fingerprint.
        """
        _identity(owner, operation_id)
        if not isinstance(submission, SourceSubmission):
            submission = SourceSubmission.model_validate(submission)
        fingerprint = _fingerprint(submission)
        if task_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", task_id):
            raise HTTPException(422, "任务标识格式无效")
        try:
            with self.sessions() as db:
                existing = db.get(SourceRequestDB, (owner, operation_id))
                if existing:
                    if existing.fingerprint != fingerprint:
                        _conflict()
                    return _receipt(existing)
                row = SourceRequestDB(owner=owner, operation_id=operation_id,
                                      fingerprint=fingerprint, task_id=task_id or str(uuid.uuid4()),
                                      state="reserved", receipt_json="{}")
                db.add(row)
                db.flush()
                receipt = _receipt(row, created=True)
            return receipt  # Commit must succeed before a caller may dispatch.
        except IntegrityError:
            # Another process committed this owner+operation while we inserted.
            # The failed transaction is rolled back before reading its winner.
            with self.sessions() as db:
                existing = db.get(SourceRequestDB, (owner, operation_id))
                if not existing:
                    raise  # Do not mislabel a different constraint failure.
                if existing.fingerprint != fingerprint:
                    _conflict()
                return _receipt(existing)

    def get(self, owner: str, operation_id: str) -> SourceRequestReceipt:
        _identity(owner, operation_id)
        with self.sessions() as db:
            row = db.get(SourceRequestDB, (owner, operation_id))
            if not row:
                raise HTTPException(404, {"code": "SOURCE_RECEIPT_NOT_FOUND",
                                          "message": "尚未查到该提交回执，请保留原提交标识核验"})
            return _receipt(row)

    def accept(self, owner: str, operation_id: str, task_id: str, *, status: str,
               source_type: str | None = None) -> SourceRequestReceipt:
        """Acknowledge a staged task once; cannot overwrite another task/receipt."""
        _identity(owner, operation_id)
        if not isinstance(status, str) or not status or len(status) > 64:
            raise HTTPException(422, "提交状态格式无效")
        if source_type is not None and (not isinstance(source_type, str) or len(source_type) > 64):
            raise HTTPException(422, "来源类型格式无效")
        saved = {"status": status, "source_type": source_type}
        with self.sessions() as db:
            row = db.get(SourceRequestDB, (owner, operation_id))
            if not row:
                raise HTTPException(404, "尚未登记该来源提交")
            if row.task_id != task_id:
                _conflict()
            db.execute(update(SourceRequestDB).where(
                SourceRequestDB.owner == owner,
                SourceRequestDB.operation_id == operation_id,
                SourceRequestDB.task_id == task_id,
                SourceRequestDB.state == "reserved",
            ).values(state="accepted", receipt_json=json.dumps(saved)),
                execution_options={"synchronize_session": False})
            db.expire(row)
            receipt = _receipt(row)
        return receipt


def create_receipt_router(service=None, principal=None):
    """Mount under /api; verified owner comes solely from the auth dependency."""
    if principal is None:
        from app.services.generation_auth_service import get_generation_user
        principal = get_generation_user
    service = service or SourceRequestService()
    router = APIRouter()

    @router.get("/source-requests/{operation_id}", response_model=SourceRequestReceipt)
    def read_receipt(operation_id: str, identity=Depends(principal)):
        owner = identity if isinstance(identity, str) else identity.user_id
        return service.get(owner, operation_id)

    return router
