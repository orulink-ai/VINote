"""One bounded durable dispatcher per process; unknown writes are never replayed.

The desktop drains a frozen saved body through its own CLI connection and
existing side-effect journals. No integration-server handoff or cloud worker.
"""
import json
import logging
import threading
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import Float, cast, select, update

from app.db import session_scope
from app.db_models import FeishuDeliveryDB, NoteDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB, FeishuDevicePolicyDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.services import feishu_auto_outbox as outbox

bind_device_policy = outbox.bind_device_policy
_logger = logging.getLogger(__name__)
_stop = threading.Event()
_wake = threading.Event()
_thread = None
_desired_running = False
_lifecycle = threading.Lock()


def background_ready():
    return bool(_thread and _thread.is_alive() and not _stop.is_set())


def wake():
    _wake.set()


def decorate_status(identity, result):
    if identity[1] is None:
        return result
    enabled = outbox.device_enabled(identity[1], result)
    return {**result, "auto_publish": enabled, "device_auto_enabled": enabled,
            "automatic_delivery": {**(result.get("automatic_delivery") or {}),
                                   "account_enabled": bool(result.get("auto_publish"))},
            "capabilities": {**result.get("capabilities", {}),
                             "background_delivery": bool(background_ready()
                                 and result.get("automatic_delivery_protocol") == 1
                                 and result.get("capabilities", {}).get("background_delivery"))}}


def guard_manual_publish(identity, note_key):
    user_id = identity[1]
    if not user_id:
        return
    accepted = None
    with session_scope() as db:
        row = db.scalar(select(FeishuAutoOutboxDB).where(
            FeishuAutoOutboxDB.user_id == user_id, FeishuAutoOutboxDB.note_id == note_key))
        if row and row.status in {"submitting", "unknown"}:
            raise HTTPException(409, "自动交付结果尚未核验，请先核验原交付，不要重复发布")
        if row and row.status == "queued":
            # Competes with the dispatcher's queued->submitting CAS, not a stale
            # ORM write that could overwrite its claim after this read.
            changed = db.execute(update(FeishuAutoOutboxDB).where(
                FeishuAutoOutboxDB.id == row.id, FeishuAutoOutboxDB.status == "queued"
            ).values(status="cancelled", error="已选择手动发布，未提交自动交付"))
            if changed.rowcount != 1:
                raise HTTPException(409, "自动交付正在提交，请先核验原结果")
        if row and row.status == "accepted":
            db.expunge(row)
            accepted = row
    if accepted is not None:
        # Acceptance only proves the handoff, never that provider side effects
        # are confirmed. A new operation cannot bypass the original journals.
        try:
            receipt = _request(accepted, read_only=True)
            confirmed = (receipt.get("operation_id") == accepted.id
                         and receipt.get("id") == accepted.job_id
                         and receipt.get("status") == "completed" and receipt.get("phase") == "completed")
        except Exception:
            confirmed = False
        if not confirmed:
            raise HTTPException(409, "原自动交付尚未完成核验，请在原交付中查看或重试，不能重复发布")


def local_status(user_id, note_id):
    with session_scope() as db:
        row = db.scalar(select(FeishuAutoOutboxDB).where(
            FeishuAutoOutboxDB.user_id == user_id, FeishuAutoOutboxDB.note_id == note_id))
        if not row:
            raise HTTPException(404, "没有此纪要的自动交付记录")
        return {"status": row.status, "job_id": row.job_id or None, "error": row.error,
                "operation_id": row.id, "can_check": row.status in {"submitting", "unknown"}}


class HandoffError(Exception):
    def __init__(self, message, *, uncertain=False, cancelled=False):
        super().__init__(message)
        self.uncertain = uncertain
        self.cancelled = cancelled


def _assert_binding(row, *, policy_required):
    with session_scope() as db:
        if (row.integration_origin != outbox.integration_origin()
                or row.cloud_owner != outbox.cloud_owner(db, row.user_id)):
            raise HandoffError("交付绑定的账号或服务已变化，未发送到其他账号或地址", cancelled=True)
        if policy_required:
            policy = db.get(FeishuDevicePolicyDB, row.user_id)
            note = db.get(NoteDB, row.note_id)
            if (not policy or not policy.enabled or policy.policy_id != row.policy_id
                    or policy.cloud_owner != row.cloud_owner or policy.integration_origin != row.integration_origin
                    or not note or note.created_by != row.user_id or note.scope != "personal"):
                raise HandoffError("自动交付已关闭或设置已变化，未提交此纪要", cancelled=True)


def _request(row, *, read_only):
    """No credentials persisted, no model call, no redirects or HTTP retries."""
    from app.services.feishu_service import FeishuService

    _assert_binding(row, policy_required=not read_only)
    from app.services.feishu_cli import enabled
    if enabled():
        if row.integration_origin != "cli://device":
            raise HandoffError("原交付来自另一连接方式，请只核验原回执", cancelled=True)
        service = FeishuService().for_owner(row.cloud_owner)
        try:
            return (service.delivery_by_operation(row.cloud_owner, row.id) if read_only else
                    service.enqueue_automatic(row.cloud_owner, **json.loads(row.payload)))
        except HTTPException as exc:
            raise HandoffError(str(exc.detail), uncertain=(read_only or exc.status_code >= 500
                                                          or getattr(exc, "uncertain", False))) from None
    # Never transfer a device-owned publication to any integration server.
    raise HandoffError("桌面飞书连接未启用，未提交此纪要", cancelled=True)


def attempt_device(operation_id, *, read_only=False):
    now = time.time()
    with session_scope() as db:
        row = db.get(FeishuAutoOutboxDB, operation_id)
        if not row or row.status in {"accepted", "failed", "cancelled"} or row.lease_until > now:
            return
        if read_only and row.status not in {"submitting", "unknown"}:
            return
        if not read_only and row.status != "queued":
            return
        lease = now + 150
        changed = db.execute(update(FeishuAutoOutboxDB).where(
            FeishuAutoOutboxDB.id == row.id, FeishuAutoOutboxDB.status == row.status,
            FeishuAutoOutboxDB.lease_until == row.lease_until,
        ).values(status="unknown" if read_only else "submitting", lease_until=lease))
        if changed.rowcount != 1:
            return
        db.expunge(row)
    state, message, job_id = "unknown", "", ""
    try:
        result = _request(row, read_only=read_only)
        job_id = result.get("id", "")
        if (result.get("operation_id") != row.id or str(uuid.UUID(job_id)) != job_id):
            raise HandoffError("原交付回执不匹配，请核验原结果；不会重复提交", uncertain=True)
        state = "accepted"
    except HandoffError as exc:
        # A read-only error cannot establish that the prior POST was rejected.
        state = "unknown" if read_only or exc.uncertain else "cancelled" if exc.cancelled else "failed"
        message = str(exc)
    except Exception:
        message = "交付暂时中断，请核验原结果；不会重复提交"
    with session_scope() as db:
        db.execute(update(FeishuAutoOutboxDB).where(
            FeishuAutoOutboxDB.id == row.id, FeishuAutoOutboxDB.lease_until == lease,
            FeishuAutoOutboxDB.status.in_(["submitting", "unknown"]),
        ).values(status=state, error=message, job_id=job_id if state == "accepted" else "", lease_until=0))
    if state == "accepted":
        wake()


def check_local(user_id, note_id):
    state = local_status(user_id, note_id)
    if state["can_check"]:
        attempt_device(state["operation_id"], read_only=True)
    return local_status(user_id, note_id)


def run_once():
    """A bounded pass; no failure retry loop or scan of historical content."""
    from app.services.feishu_service import FeishuService
    from app.services.feishu_cli import enabled
    if not enabled():
        return

    now = time.time()
    with session_scope() as db:
        candidates = db.execute(select(FeishuAutoOutboxDB.id, FeishuAutoOutboxDB.status).where(
            FeishuAutoOutboxDB.status.in_(["queued", "submitting"]),
            FeishuAutoOutboxDB.lease_until <= now).limit(2)).all()
    for identifier, state in candidates:
        attempt_device(identifier, read_only=state == "submitting")
    # Only versioned automatic intents accepted by the new endpoint. Manual,
    # legacy queued rows and failed/unknown jobs never acquire daemon consent.
    with session_scope() as db:
        accepted = db.execute(select(FeishuDeliveryDB.owner, FeishuDeliveryDB.id,
                                     FeishuDeliveryDestinationDB.snapshot).join(
            FeishuDeliveryDestinationDB, FeishuDeliveryDestinationDB.delivery_id == FeishuDeliveryDB.id
        ).where(FeishuDeliveryDB.status.in_(["queued", "processing"]),
                cast(FeishuDeliveryDB.lease_until, Float) <= now,
                FeishuDeliveryDestinationDB.snapshot.contains('"automatic_policy_id"')).limit(2)).all()
    for owner, identifier, raw in accepted:
        snapshot = json.loads(raw)
        if snapshot.get("automatic") is True and snapshot.get("automatic_policy_id"):
            FeishuService().for_owner(owner).process(owner, identifier)


def _loop():
    while not _stop.is_set():
        try:
            run_once()
        except Exception:
            # No task body, PII, credential, endpoint or raw exception in logs.
            _logger.warning("Automatic Feishu dispatcher pass interrupted; durable receipts retained")
        _wake.wait(2)
        _wake.clear()


def _spawn_locked():
    global _thread
    _stop.clear()
    _wake.clear()
    _thread = threading.Thread(target=_worker_main, name="vinote-feishu-auto", daemon=True)
    _thread.start()


def _worker_main():
    global _thread
    try:
        _loop()
    finally:
        with _lifecycle:
            if _thread is threading.current_thread():
                _thread = None
                # A new startup requested service while old I/O was finishing.
                # Only start its successor after the old loop fully leaves.
                if _desired_running and _stop.is_set():
                    _spawn_locked()


def start():
    global _desired_running
    from app.services.feishu_cli import enabled
    if not enabled():
        return
    with _lifecycle:
        _desired_running = True
        # A previous stop may still be waiting for an in-flight provider call.
        # Never clear its stop event and accidentally keep two workers alive.
        if _thread and _thread.is_alive():
            return
        _spawn_locked()


def stop():
    global _desired_running
    with _lifecycle:
        _desired_running = False
        _stop.set()
        _wake.set()
        previous = _thread
    # Never hold the lock needed by _worker_main's finally while joining it.
    if previous and previous is not threading.current_thread():
        previous.join(timeout=5)
