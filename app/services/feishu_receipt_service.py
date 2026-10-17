"""Owner-scoped publication intents and conservative write-batch receipts."""
import hashlib
import json

from fastapi import HTTPException
from app.db_models import FeishuDeliveryDB
from app.models.feishu_destination import FeishuPublishReceiptDB, FeishuWriteBatchDB


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def operation_job(db, owner, operation_id, expected=None):
    receipt = db.get(FeishuPublishReceiptDB, (owner, operation_id))
    if not receipt:
        return None
    if expected is not None and receipt.fingerprint != expected:
        raise HTTPException(409, {"code": "OPERATION_REUSED", "message": "原发布操作已绑定其他输入，请核验原回执"})
    return owned_job(db, owner, receipt.job_id)


def owned_job(db, owner, job_id):
    job = db.get(FeishuDeliveryDB, job_id)
    if not job or job.owner != owner:
        raise HTTPException(404, "交付记录不存在")
    return job


def bind_operation(db, owner, operation_id, expected, job):
    if not operation_id:
        return
    existing = operation_job(db, owner, operation_id, expected)
    if existing:
        if existing.id != job.id:
            raise HTTPException(409, "发布操作绑定已变化，请核验原回执")
        return
    db.add(FeishuPublishReceiptDB(owner=owner, operation_id=operation_id,
                                fingerprint=expected, job_id=job.id))
    db.flush()


def begin_batch(db, owner, job_id, offset, body):
    owned_job(db, owner, job_id)
    expected = fingerprint(body)
    batch = db.get(FeishuWriteBatchDB, (job_id, str(offset)))
    if batch:
        if batch.fingerprint != expected:
            raise HTTPException(409, "原正文批次输入已变化，禁止重新写入")
        if batch.state == "confirmed":
            return False
        if batch.state != "failed":
            raise HTTPException(409, "正文批次结果未核验，禁止重新写入")
        batch.state = "dispatching"
    else:
        db.add(FeishuWriteBatchDB(job_id=job_id, offset=str(offset),
                                 fingerprint=expected, state="dispatching"))
    db.flush()
    return True


def finish_batch(db, owner, job_id, offset, state):
    owned_job(db, owner, job_id)
    batch = db.get(FeishuWriteBatchDB, (job_id, str(offset)))
    if batch and batch.state == "dispatching":
        batch.state = state


def has_unknown_batch(db, job_id):
    from sqlalchemy import select
    return db.scalar(select(FeishuWriteBatchDB.job_id).where(
        FeishuWriteBatchDB.job_id == job_id,
        FeishuWriteBatchDB.state.in_(["dispatching", "unknown"])).limit(1)) is not None
