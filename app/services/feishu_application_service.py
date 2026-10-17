"""Account-owned enterprise app credentials, encrypted at rest and never returned."""
from dataclasses import asdict
import json
import re
from types import SimpleNamespace
from urllib.parse import urlparse
from sqlalchemy import delete
from app.config import settings
from app.db import session_scope
from app.db_models import FeishuApplicationDB, FeishuOAuthDB, FeishuConnectionDB
from app.services.cloud_account_service import _cipher


def application_config(owner=None):
    if owner:
        with session_scope() as db:
            row = db.get(FeishuApplicationDB, owner)
            if row:
                values = json.loads(_cipher().decrypt(row.credentials.encode()))
                return SimpleNamespace(**{**asdict(settings), **values})
    return settings


def application_status(owner):
    config = application_config(owner)
    with session_scope() as db:
        personal = db.get(FeishuApplicationDB, owner) is not None
    return {"custom": personal, "app_id": config.feishu_app_id or "",
            "redirect_uri": settings.feishu_redirect_uri or "",
            "tenant_key": config.feishu_tenant_key or "", "document_domain": config.feishu_doc_base_url or ""}


def save_application(owner, payload):
    if not settings.feishu_redirect_uri or not settings.model_profile_encryption_key:
        raise ValueError("授权服务回调或加密配置未就绪，请联系管理员")
    if not re.fullmatch(r"cli_[A-Za-z0-9_]{5,100}", payload["app_id"]):
        raise ValueError("App ID 格式不正确")
    url = urlparse(payload["document_domain"])
    if url.scheme != "https" or not (url.hostname or "").endswith(".feishu.cn") or url.username or url.password or url.port or url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError("请填写公司飞书云文档 HTTPS 域名，例如 https://公司.feishu.cn")
    values = dict(feishu_app_id=payload["app_id"], feishu_app_secret=payload["app_secret"],
                  feishu_tenant_key=payload["tenant_key"], feishu_doc_base_url=payload["document_domain"].rstrip("/"))
    from app.services.feishu_service import FeishuService, _lock
    # Authentication probe: no document creation or messages, and no secret echoed.
    FeishuService().request("POST", "auth/v3/tenant_access_token/internal", body={"app_id": values["feishu_app_id"], "app_secret": values["feishu_app_secret"]})
    with _lock(owner), session_scope() as db:
        row = db.get(FeishuApplicationDB, owner)
        if not row:
            row = FeishuApplicationDB(owner=owner)
            db.add(row)
        row.credentials = _cipher().encrypt(json.dumps(values).encode()).decode()
        db.execute(delete(FeishuOAuthDB).where(FeishuOAuthDB.owner == owner))
        connection = db.get(FeishuConnectionDB, owner)
        if connection:
            connection.tokens = ""
            connection.expired = True
    return application_status(owner)


def clear_application(owner):
    from app.services.feishu_service import _lock
    with _lock(owner), session_scope() as db:
        db.execute(delete(FeishuApplicationDB).where(FeishuApplicationDB.owner == owner))
        db.execute(delete(FeishuOAuthDB).where(FeishuOAuthDB.owner == owner))
        row = db.get(FeishuConnectionDB, owner)
        if row:
            row.tokens = ""
            row.expired = True
    return {"cleared": True}
