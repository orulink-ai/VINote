"""Proxy account-scoped integrations without changing the account issuer."""
import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.cloud_account_service import CloudAccountService


def proxy_integration(identity, method, path, body=None):
    origin = (settings.workspace_service_url or settings.feishu_service_url) if path.startswith(("/api/workspace/", "/api/plugins")) else settings.feishu_service_url
    if not origin or identity[1] is None:
        return False, None
    if not path.startswith(("/api/workspace/", "/api/mcp-connections", "/api/plugins")):
        raise ValueError("Unsupported integration path")
    token = CloudAccountService().access_token(identity[1])
    try:
        response = httpx.request(
            method, origin + path,
            headers={"Authorization": "Bearer " + token}, json=body,
            timeout=180 if path.endswith(("/generate", "/ask", "/runs", "/retry")) else 50,
            follow_redirects=False,
        )
        payload = response.json() if response.content else None
    except (httpx.RequestError, ValueError):
        raise HTTPException(502, "无法连接共享服务，已保存内容会保留，请稍后重试") from None
    if not response.is_success:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise HTTPException(response.status_code, detail or "共享服务请求未完成")
    return True, payload
