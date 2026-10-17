"""Bounded private content attachments; no original-media sync endpoint."""
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from app.config import settings
from app.routers.feishu import principal
from app.services.cloud_account_service import CloudAccountService
from app.services.integration_proxy import proxy_integration
from app.services.workspace_attachment_service import MAX_BYTES, WorkspaceAttachmentService

router = APIRouter(prefix="/workspace/attachments", tags=["workspace-attachments"])
service = WorkspaceAttachmentService()


def remote_upload(identity, data):
    origin = settings.workspace_service_url or settings.feishu_service_url
    if not origin or identity[1] is None:
        return None
    token = CloudAccountService().access_token(identity[1])
    try:
        response = httpx.post(origin + "/api/workspace/attachments", headers={"Authorization": "Bearer " + token},
                              files={"file": ("content-image", data, "application/octet-stream")},
                              timeout=45, follow_redirects=False)
        payload = response.json()
    except (httpx.RequestError, ValueError):
        raise HTTPException(502, "附件未确认上传成功，请保留内容后重试") from None
    if not response.is_success:
        raise HTTPException(response.status_code, payload.get("detail", "附件上传失败"))
    return payload


@router.post("")
async def upload(file: UploadFile = File(...), identity=Depends(principal)):
    try:
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "正文图片不能超过 5 MB")
        return remote_upload(identity, data) or service.upload(identity[0], data)
    finally:
        await file.close()


@router.get("/{identifier}/access")
def access(identifier: str, identity=Depends(principal)):
    service_id(identifier)
    remote, result = proxy_integration(identity, "GET", f"/api/workspace/attachments/{identifier}/access")
    return result if remote else service.access(identity[0], identifier)


def service_id(identifier):
    import re
    if not re.fullmatch(r"[a-f0-9]{64}", identifier):
        raise HTTPException(404, "找不到内容附件")


@router.get("/{identifier}/content")
def content(identifier: str, identity=Depends(principal)):
    service_id(identifier)
    origin = settings.workspace_service_url or settings.feishu_service_url
    if origin and identity[1] is not None:
        token = CloudAccountService().access_token(identity[1])
        try:
            with httpx.stream("GET", origin + f"/api/workspace/attachments/{identifier}/content",
                              headers={"Authorization": "Bearer " + token}, timeout=30, follow_redirects=False) as response:
                if not response.is_success:
                    raise HTTPException(response.status_code, "内容附件暂不可用")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise HTTPException(502, "内容附件超过大小限制")
                media_type = response.headers.get("content-type", "application/octet-stream")
        except httpx.RequestError:
            raise HTTPException(502, "内容附件读取失败，请重试") from None
    else:
        data, media_type = service.read(identity[0], identifier)
    return Response(bytes(data), media_type=media_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
