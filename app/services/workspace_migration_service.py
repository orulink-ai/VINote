"""Authenticated local-to-shared import. Existing cloud records are never overwritten."""
import re
import uuid
import hashlib
import json
from fastapi import HTTPException
from app.services.workspace_service import WorkspaceService
from app.services.workspace_attachment_service import WorkspaceAttachmentService
from app.services.integration_proxy import proxy_integration
from app.routers.workspace_attachments import remote_upload


def portable_version(key, version):
    def identifier(value):
        return ("imported:" + str(uuid.uuid5(uuid.NAMESPACE_URL, key + value))
                if value and value.startswith("__vinote:") else value)
    return {**{k: v for k, v in version.items() if k != "evidence_revision"},
            "id": identifier(version["id"]), "parent_id": identifier(version.get("parent_id"))}


def version_batches(versions):
    batch, size = [], 0
    for version in versions:
        length = len(json.dumps(version, ensure_ascii=False).encode())
        if batch and (len(batch) >= 50 or size + length > 4 * 1024 * 1024):
            yield batch
            batch, size = [], 0
        batch.append(version)
        size += length
    if batch:
        yield batch


def import_local_workspace(identity, selected_keys=None):
    if not selected_keys:
        raise HTTPException(422, "请选择明确允许同步的内容，不支持默认全量迁移")
    selected_keys = set(selected_keys)
    if not identity[1]:
        raise HTTPException(409, "历史内容迁移需从已登录的桌面设备发起")
    source = WorkspaceService()
    attachments = WorkspaceAttachmentService()
    offset, imported, skipped = 0, 0, 0
    while offset is not None:
        page = source.list(identity[0], offset, 50, True)
        for item in page["items"]:
            if item["key"] not in selected_keys:
                continue
            path = "/api/workspace/notes/" + item["key"]
            remote_note = None
            try:
                remote, remote_note = proxy_integration(identity, "GET", path)
                if not remote:
                    raise HTTPException(409, "请先配置正式共享服务")
                next_offset = remote_note["next_versions_offset"]
                while next_offset is not None:
                    _, history = proxy_integration(identity, "GET", path + f"?versions_offset={next_offset}&versions_limit=100")
                    if history["revision"] != remote_note["revision"]:
                        raise HTTPException(409, "云端内容已更新，请重试历史迁移")
                    remote_note["versions"].extend(history["versions"])
                    next_offset = history["next_versions_offset"]
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
            note = source.get(identity[0], item["key"], 0, 100)
            while note["next_versions_offset"] is not None:
                history = source.get(identity[0], item["key"], note["next_versions_offset"], 100)
                note["versions"].extend(history["versions"])
                note["next_versions_offset"] = history["next_versions_offset"]
            versions = [portable_version(item["key"], version) for version in note["versions"]]
            if remote_note:
                existing = {version["id"]: version for version in remote_note["versions"]}
                for version in versions:
                    old = existing.get(version["id"])
                    if old and (old["content"] != version["content"] or old["title"] != version["title"]):
                        raise HTTPException(409, "历史版本标识冲突，两份内容均已保留")
                versions = [version for version in versions if version["id"] not in existing]
                if not versions:
                    skipped += 1
                    continue
            target = remote_note or note
            bodies = target["content"] + "".join(version["content"] for version in versions)
            for identifier in set(re.findall(r"attachment://([a-f0-9]{64})", bodies)):
                data, _ = attachments.read(identity[0], identifier)
                if not remote_upload(identity, data):
                    raise HTTPException(502, "附件尚未确认上传，历史内容保留")
            revision = target["revision"] if remote_note else 0
            for batch in (list(version_batches(versions)) or [[]]):
                payload = {key: target[key] for key in ("title", "content", "source_type", "source_device", "archived", "transcript", "metadata")}
                digest = hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest()[:24]
                payload.update(base_revision=revision, operation_id=f"migration:{item['key']}:{revision}:{digest}", versions=batch)
                _, result = proxy_integration(identity, "PUT", path, payload)
                revision = result["revision"]
            if note["deleted"] and not remote_note:
                proxy_integration(identity, "DELETE", path + f"?base_revision={revision}&operation_id=migration-delete:{item['key']}")
            imported += 1
        offset = page["next_offset"]
    return {"imported": imported, "existing": skipped, "original_media_uploaded": False}
