"""Transactional, device-owned handoff. Never discovers or backfills old notes."""
import hashlib
import json
import stat
import uuid

from sqlalchemy import select, update

from app.config import settings
from app.db import session_scope
from app.db_models import CloudAccountDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB, FeishuDevicePolicyDB, FeishuMeetingSaveDB


def cloud_owner(db, user_id):
    account = db.get(CloudAccountDB, user_id)
    if account and account.issuer == settings.cloud_auth_url and account.subject:
        return hashlib.sha256((account.issuer + ":" + account.subject).encode()).hexdigest()
    return None if settings.feishu_service_url else user_id


def bind_device_policy(user_id, result):
    """Only called after this device explicitly saves its publishing preferences."""
    if not user_id:
        return
    policy = (result or {}).get("automatic_delivery") or {}
    identifier = policy.get("policy_id")
    try:
        valid = str(uuid.UUID(identifier)) == identifier
    except (ValueError, TypeError, AttributeError):
        valid = False
    enabled = bool(valid and result.get("automatic_delivery_protocol") == 1
                   and result.get("auto_publish") and policy.get("enabled")) if result else False
    with session_scope() as db:
        owner = cloud_owner(db, user_id)
        row = db.get(FeishuDevicePolicyDB, user_id)
        if row is None:
            row = FeishuDevicePolicyDB(user_id=user_id)
            db.add(row)
        row.policy_id = identifier if enabled else ""
        row.enabled = enabled and bool(owner)
        row.integration_origin = settings.feishu_service_url
        row.cloud_owner = owner or ""
        # Already-submitted/unknown work is never relabelled cancelled or retried.
        db.execute(update(FeishuAutoOutboxDB).where(
            FeishuAutoOutboxDB.user_id == user_id,
            FeishuAutoOutboxDB.status == "queued",
            FeishuAutoOutboxDB.policy_id != row.policy_id,
        ).values(status="cancelled", error="自动交付设置已变化，未提交此纪要"))


def device_enabled(user_id, result):
    if not user_id or not (result.get("automatic_delivery") or {}).get("enabled"):
        return False
    with session_scope() as db:
        row = db.get(FeishuDevicePolicyDB, user_id)
        return bool(row and row.enabled
                    and row.policy_id == result["automatic_delivery"].get("policy_id")
                    and row.integration_origin == settings.feishu_service_url
                    and row.cloud_owner == cloud_owner(db, user_id))


def verified_completion(record):
    """Read only small owned metadata; no audio/video reads or model calls."""
    from app.services.task_artifact_service import TaskArtifactService
    if (record.generation_client != "desktop" or record.scope != "personal"
            or record.status != "done" or not record.content.strip()
            or record.source_type not in {"meeting_recording", "meeting_video"}):
        return False
    try:
        if str(uuid.UUID(record.task_id)) != record.task_id:
            return False
        artifacts = TaskArtifactService()
        folder = artifacts.find_task_dir(record.task_id)
        if (not folder or folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
                or folder.resolve().parent != artifacts.output_dir.resolve()):
            return False

        def read(name):
            path = folder / name
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536
                    or getattr(path, "is_junction", lambda: False)()):
                raise ValueError("Unverified metadata")
            return path.read_text(encoding="utf-8")

        return (read("recording_owner").strip() == record.created_by
                and read(".task_id").strip() == record.task_id
                and json.loads(read("status.json")).get("status") == "success"
                and json.loads(read("request.json")).get("request", {}).get("workflow") == "meeting")
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def register_new_meeting(db, record):
    if (record.generation_client != "desktop" or record.scope != "personal"
            or record.source_type not in {"meeting_recording", "meeting_video"}):
        return
    if db.get(FeishuMeetingSaveDB, record.id) is not None:
        # Permanently deleting/re-saving a deterministic meeting ID is not a
        # new automatic authorization. It must still allow saving the note.
        return
    policy = db.get(FeishuDevicePolicyDB, record.created_by)
    eligible = (policy and policy.enabled and policy.integration_origin == settings.feishu_service_url
                and policy.cloud_owner == cloud_owner(db, record.created_by))
    db.add(FeishuMeetingSaveDB(note_id=record.id, user_id=record.created_by,
                              policy_id=policy.policy_id if eligible else "", completed=False))
    db.flush()
    capture_saved_meeting(db, record)


def capture_saved_meeting(db, record):
    """Use the caller's note-save transaction: no network or worker side effects."""
    first = db.get(FeishuMeetingSaveDB, record.id)
    if (not first or first.user_id != record.created_by or first.completed
            or not verified_completion(record)):
        return
    # Remember a genuine completion even while disabled: editable status flips
    # or a later opt-in can never turn that old content into a new publication.
    first.completed = True
    policy = db.get(FeishuDevicePolicyDB, record.created_by)
    if (not first.policy_id or not policy or not policy.enabled or first.policy_id != policy.policy_id
            or policy.integration_origin != settings.feishu_service_url
            or policy.cloud_owner != cloud_owner(db, record.created_by)):
        return
    existing = db.scalar(select(FeishuAutoOutboxDB.id).where(
        FeishuAutoOutboxDB.user_id == record.created_by,
        FeishuAutoOutboxDB.note_id == record.id))
    if existing:
        return
    operation_id = str(uuid.uuid4())
    payload = {"operation_id": operation_id, "policy_id": policy.policy_id,
               "note_key": record.id, "title": record.title, "content": record.content}
    too_large = len(record.content) > 300000
    db.add(FeishuAutoOutboxDB(
        id=operation_id, user_id=record.created_by, note_id=record.id,
        policy_id=policy.policy_id, integration_origin=policy.integration_origin,
        cloud_owner=policy.cloud_owner, payload=json.dumps(payload, ensure_ascii=False),
        status="failed" if too_large else "queued",
        error="纪要正文超出自动交付长度范围，请调整后手动发布" if too_large else ""))
