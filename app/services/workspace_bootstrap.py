"""One-time private cloud setup, repeated safely before serving requests."""
import re

import httpx

from app.config import settings


def protect_api_tables(connection, tables):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("共享服务需要 PostgreSQL，不能回退本地数据库")
    quote = connection.dialect.identifier_preparer.quote
    schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    if not schema:
        raise RuntimeError("共享服务数据库没有可用的内容 schema")
    for table in tables:
        name = f"{quote(table.schema or schema)}.{quote(table.name)}"
        connection.exec_driver_sql(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        connection.exec_driver_sql(f"REVOKE ALL ON TABLE {name} FROM PUBLIC, anon, authenticated")


def initialize_private_storage():
    """Create only the configured bucket, never relax an existing bucket."""
    bucket = settings.workspace_storage_bucket
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", bucket):
        raise RuntimeError("正文附件存储桶名称无效")
    headers = {"Authorization": "Bearer " + settings.workspace_storage_key,
               "apikey": settings.workspace_storage_key}
    desired = {"id": bucket, "name": bucket, "public": False,
               "file_size_limit": 5242880,
               "allowed_mime_types": ["image/png", "image/jpeg", "image/webp"]}
    try:
        with httpx.Client(base_url=settings.workspace_storage_url + "/storage/v1/",
                          headers=headers, timeout=15, follow_redirects=False) as client:
            response = client.get("bucket/" + bucket)
            missing = response.status_code == 404
            # Older Storage versions wrap a missing bucket as HTTP 400. Only
            # their explicit not-found code permits creation, never auth errors.
            if response.status_code == 400:
                error = response.json()
                missing = isinstance(error, dict) and str(error.get("statusCode")) == "404"
            if missing:
                created = client.post("bucket", json=desired)
                if not created.is_success and created.status_code != 409:
                    raise RuntimeError("私有附件存储初始化失败，请检查服务端凭证与权限")
                response = client.get("bucket/" + bucket)
            if not response.is_success:
                raise RuntimeError("无法核验私有附件存储，请检查服务端凭证与权限")
            value = response.json()
            if not isinstance(value, dict) or value.get("public") is not False:
                raise RuntimeError("正文附件桶必须为私有；不会自动修改已有公开桶")
            if any(value.get(key) != desired[key] for key in ("file_size_limit", "allowed_mime_types")):
                updated = client.put("bucket/" + bucket, json=desired)
                if not updated.is_success:
                    raise RuntimeError("附件大小与类型限制配置失败")
    except (httpx.RequestError, ValueError):
        raise RuntimeError("私有附件存储暂不可用，初始化未完成") from None
