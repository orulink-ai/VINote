"""User-owned Feishu documents and checkpointed bot delivery. No client secrets."""
import hashlib
import base64
from io import BytesIO
import json
import math
import re
import secrets
import threading
import time
import uuid
from datetime import timezone
from urllib.parse import urlparse
from urllib.parse import urlencode

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session_scope
from app.db_models import FeishuConnectionDB, FeishuDeliveryDB, FeishuOAuthDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.workspace import WorkspaceNoteDB, WorkspaceVersionDB
from app.services import feishu_receipt_service as receipts
from app.services import feishu_markdown as native_markdown
from app.services import feishu_recipient_access as recipient_access
from app.services.feishu_notification_card import document_card
from app.services.cloud_account_service import _cipher

_locks = [threading.RLock() for _ in range(64)]


class FeishuError(HTTPException):
    def __init__(self, message, status=400, uncertain=False, code=""):
        super().__init__(status, message)
        self.uncertain = uncertain
        self.code = code or ("authorization_required" if status == 401 else
                             "permission_denied" if status == 403 else
                             "result_unknown" if uncertain else "provider_error")


def _lock(owner):
    return _locks[int(hashlib.sha256(owner.encode()).hexdigest(), 16) % len(_locks)]


class FeishuService:
    def __init__(self, owner=None):
        self.owner = owner

    def for_owner(self, owner):
        return FeishuService(owner)

    @property
    def config(self):
        from app.services.feishu_application_service import application_config
        return application_config(self.owner)

    def setup_status(self):
        """Expose requirements, never credentials or another local CLI identity."""
        required = {
            "application": bool(self.config.feishu_app_id and self.config.feishu_app_secret),
            "callback": bool(self.config.feishu_redirect_uri),
            "organization": bool(self.config.feishu_tenant_key),
            "documents": bool(self.config.feishu_doc_base_url),
            "encryption": bool(settings.model_profile_encryption_key),
        }
        return {"ready": self.configured(), "missing": [key for key, ready in required.items() if not ready]}

    def configured(self):
        domain = urlparse(self.config.feishu_doc_base_url)
        return bool(domain.scheme == "https" and (domain.hostname or "").endswith(".feishu.cn") and
                    not domain.username and not domain.password and self.config.feishu_app_id and self.config.feishu_app_secret and
                    self.config.feishu_redirect_uri and self.config.feishu_tenant_key and
                    settings.model_profile_encryption_key)

    def require_config(self):
        if not self.configured():
            raise FeishuError("飞书接入尚未启用，请联系管理员完成应用配置", 503, code="not_configured")

    def request(self, method, path, *, token=None, body=None, params=None):
        try:
            response = httpx.request(method, "https://open.feishu.cn/open-apis/" + path,
                                     headers={"Authorization": "Bearer " + token} if token else {},
                                     json=body, params=params, timeout=30, follow_redirects=False)
        except httpx.RequestError:
            raise FeishuError("暂时无法连接飞书，请重试。已完成的交付步骤会保留", 502, uncertain=True) from None
        try:
            data = response.json()
        except ValueError:
            raise FeishuError("飞书返回异常，请稍后重试", 502, uncertain=True) from None
        if not isinstance(data, dict):
            raise FeishuError("飞书响应格式异常，需要核验操作结果", 502, uncertain=True)
        code = data.get("code", 0)
        if response.status_code == 401 or data.get("error") in ("invalid_grant", "invalid_token") or code in (99991663, 99991668, 99991669, 99991677, 20024, 20037):
            raise FeishuError("飞书授权或访问权限失效，请重新连接并检查文档、群权限", 401)
        if response.status_code >= 500 or code in (131001, 131007, 1066001, 1066002):
            raise FeishuError("飞书服务异常，操作结果需要核验", 502, uncertain=True)
        if code == 99991672:
            raise FeishuError("应用尚未开通所需接口权限，请联系管理员", 403, code="app_scope_missing")
        if code == 99991679:
            raise FeishuError("当前用户尚未授权所需权限，请重新连接并授权", 403, code="user_scope_missing")
        if code in (99991662, 99991673):
            raise FeishuError("企业应用已停用或尚未安装，请联系管理员", 403, code="app_unavailable")
        if code == 230013:
            raise FeishuError("联系人不在机器人的可用范围内或已离职，文档已保留", 403, code="recipient_unavailable")
        if code in (1770039, 1770002, 1770003, 131005, 1063005, 1061003, 1061007, 91203):
            raise FeishuError("目标不存在或已移除，请刷新并重新选择", 404, code="target_unavailable")
        if code in (1770040, 1770032, 131006, 1063002, 1063004, 1061004, 91204) or response.status_code == 403:
            raise FeishuError("当前身份无目标操作权限，请检查目录、知识库或文档授权", 403)
        if code == 1063003:
            raise FeishuError("组织策略或已有协作者权限不允许此操作，请检查飞书权限", 403, code="policy_restricted")
        if response.status_code == 429 or code in (99991400, 1063006):
            raise FeishuError("飞书请求过于频繁，请稍后重试", 429, code="rate_limited")
        if not response.is_success or code:
            # Raw provider messages may contain identifiers or request details.
            raise FeishuError("飞书操作未完成，请检查应用权限和目标群后重试", 400)
        payload = data.get("data", data)
        if not isinstance(payload, dict):
            raise FeishuError("飞书响应格式异常，需要核验操作结果", 502, uncertain=True)
        return payload

    def status(self, owner):
        # Refresh and read the resulting grants under the same identity lock as
        # disconnect, app replacement and OAuth connection writes.
        with _lock(owner):
            refresh_unavailable = False
            if self.configured():
                with session_scope() as db:
                    row = db.get(FeishuConnectionDB, owner)
                    needs_token = bool(row and row.tokens and not row.expired)
                if needs_token:
                    try:
                        self.user_token(owner)
                    except FeishuError as exc:
                        # Only explicit authorization failure invalidates a grant.
                        # Outages/invalid responses never erase encrypted credentials.
                        refresh_unavailable = exc.status_code != 401
            return self._connection_status(owner, refresh_unavailable)

    def _connection_status(self, owner, refresh_unavailable=False):
        with session_scope() as db:
            row = db.get(FeishuConnectionDB, owner)
            preferences = json.loads(row.preferences) if row else {}
            connected = bool(self.configured() and row and row.tokens and not row.expired and not refresh_unavailable)
            scopes = self.granted_scopes(row) if connected else set()
            can_write = bool(scopes & {"docx:document", "docx:document:write_only"})
            can_create_doc = bool(scopes & {"docx:document", "docx:document:create"}) and can_write
            destination = preferences.get("destination_config", {"kind": "personal"})
            return {"configured": self.configured(), "setup": self.setup_status(),
                    "publish_receipt_protocol": 1,
                    "contact_selection_protocol": 1,
                    "recipient_access_protocol": recipient_access.PROTOCOL,
                    "formatting_protocol": 2,
                    "markdown_conversion_preflight": {
                        "user_grant_available": connected and "docx:document.block:convert" in scopes and can_write,
                        "required_scope": "docx:document.block:convert",
                        "app_permission_verified": False,
                        "needed_only_for": ["table", "code", "inline"],
                        "image_mode": "unsupported_before_write"},
                    "grant_state": "unavailable" if refresh_unavailable or not self.configured() else "verified" if connected else "reauthorization_required" if row and row.expired else "disconnected",
                    "connection_state": "service_unavailable" if refresh_unavailable or not self.configured() else "reauthorization_required" if row and row.expired else "connected" if row and row.tokens else "disconnected",
                    "connected": connected,
                    "expired": bool(row and row.expired), "name": row.name if row else "",
                    "notify_self": preferences.get("notify_self", True), "groups": preferences.get("groups", []),
                    "auto_publish": preferences.get("auto_publish", False), "destination": destination["kind"],
                    "destination_config": destination,
                    "permission_policy": preferences.get("permission_policy", "private" if destination["kind"] == "personal" else "inherit"),
                    "capabilities": {
                        "personal": connected and can_create_doc,
                        "folder": connected and can_create_doc and bool(scopes & {"drive:drive", "drive:drive.metadata:readonly"}),
                        "wiki": connected and bool(scopes & {"wiki:wiki", "wiki:node:create"}) and can_write,
                        "update_existing": False, "background_delivery": False,
                        "resume_pending": connected,
                        "contact_search": connected and "contact:user:search" in scopes,
                        "contact_notification": connected,
                        "organization_wide_sharing": False, "recipient_edit_permission": False,
                    }, "capability_reason": "暂时无法核验飞书授权，请稍后重试；无需因此重新授权" if refresh_unavailable else "" if scopes else "需真实用户授权并确认已授予的权限范围",
                    "tenant_key": self.config.feishu_tenant_key if connected else ""}

    @staticmethod
    def granted_scopes(row):
        if not row or not row.tokens or row.expired:
            return set()
        tokens = json.loads(_cipher().decrypt(row.tokens.encode()))
        if tokens.get("expires_at", 0) <= time.time():
            return set()
        return set(str(tokens.get("scope", "")).split())

    @staticmethod
    def normalize_destination(value):
        if value is None:
            value = {"kind": "personal"}
        if not isinstance(value, dict) or set(value) - {"kind", "folder_token", "space_id", "node_token"}:
            raise FeishuError("无效的发布位置", 422, code="invalid_destination")
        kind = value.get("kind", "personal")
        if kind not in ("personal", "folder", "wiki"):
            raise FeishuError("不支持的发布位置", 422, code="invalid_destination")
        fields = {key: value.get(key, "") for key in ("folder_token", "space_id", "node_token")}
        if any(not isinstance(v, str) or len(v) > 200 or (v and not re.fullmatch(r"[A-Za-z0-9_-]+", v)) for v in fields.values()):
            raise FeishuError("无效的位置标识", 422, code="invalid_destination")
        required = {"personal": set(), "folder": {"folder_token"}, "wiki": {"space_id", "node_token"}}[kind]
        if {k for k, v in fields.items() if v} != required:
            raise FeishuError("个人位置不带标识；文件夹需 folder_token；知识库需 space_id 和父节点 node_token", 422, code="invalid_destination")
        return {"kind": kind, **{key: fields[key] for key in sorted(required)}}

    @staticmethod
    def normalize_policy(destination, policy):
        policy = policy or ("private" if destination["kind"] == "personal" else "inherit")
        if policy not in ("private", "inherit") or (destination["kind"] != "personal" and policy != "inherit"):
            raise FeishuError("组织目录和知识库只能沿用目标权限，不能承诺缩窄继承权限", 422, code="unsupported_permission")
        return policy

    @staticmethod
    def validate_groups(groups):
        if (not isinstance(groups, list) or len(groups) > 20 or
                any(not isinstance(group, str) or not re.fullmatch(r"oc_[A-Za-z0-9_-]{1,196}", group) for group in groups)):
            raise FeishuError("通知群列表无效", 422, code="invalid_recipient")
        return list(dict.fromkeys(groups))

    def destinations(self, owner, kind="folder", folder_token="", space_id="", parent_node_token="", page_token=""):
        self.require_config()
        token = self.user_token(owner)
        for value in (folder_token, space_id, parent_node_token):
            if value and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise FeishuError("无效的位置标识", 422, code="invalid_destination")
        params = {"page_size": 50, **({"page_token": page_token} if page_token else {})}
        if kind == "folder":
            data = self.request("GET", "drive/v1/files", token=token, params={**params, "folder_token": folder_token})
            items = [{"kind": "folder", "folder_token": item["token"], "name": item.get("name", ""),
                      "can_create": False, "permission_state": "unchecked"}
                     for item in data.get("files", []) if item.get("type") == "folder"]
            next_page = data.get("next_page_token", "")
        elif kind == "wiki":
            path = f"wiki/v2/spaces/{space_id}/nodes" if space_id else "wiki/v2/spaces"
            if parent_node_token:
                params["parent_node_token"] = parent_node_token
            data = self.request("GET", path, token=token, params=params)
            items = [{"kind": "wiki", "space_id": item["space_id"], "node_token": item.get("node_token", ""),
                      "name": item.get("title", item.get("name", "")), "can_create": False,
                      "permission_state": "unchecked", "has_child": item.get("has_child", True)}
                     for item in data.get("items", [])]
            next_page = data.get("page_token", "")
        else:
            raise FeishuError("不支持的位置类型", 422)
        return {"items": items, "has_more": bool(data.get("has_more")), "page_token": next_page}

    def check_destination(self, owner, destination):
        """Read-only evidence, never a write probe. See official docs linked below.

        drive-v1/folder/get-folder-meta.md does not expose a write permission.
        permission/permission-member/auth.md supports wiki/edit, NOT folder.
        wiki-v2/space-node/create.md requires parent container edit permission.
        All paths are under https://open.feishu.cn/document/server-docs/docs/.
        """
        target = self.normalize_destination(destination)
        result = {**target, "name": "个人云文档" if target["kind"] == "personal" else "",
                  "path": [], "path_complete": False, "tenant_key": "", "can_create": False,
                  "can_attempt_create": False, "permission_state": "unchecked", "reason": "",
                  "error_code": "", "checked_at": time.time(), "identity": "user"}
        try:
            self.require_config()
            token = self.user_token(owner)
            with session_scope() as db:
                scopes = self.granted_scopes(db.get(FeishuConnectionDB, owner))
            result["tenant_key"] = self.config.feishu_tenant_key
            write_scope = bool(scopes & {"docx:document", "docx:document:write_only"})
            doc_scope = bool(scopes & {"docx:document", "docx:document:create"}) and write_scope
            if target["kind"] == "personal":
                result.update(path=[result["name"]], path_complete=True, can_create=doc_scope,
                              can_attempt_create=doc_scope, permission_state="allowed" if doc_scope else "scope_missing",
                              reason="" if doc_scope else "用户授权未包含创建文档权限", error_code="" if doc_scope else "user_scope_missing")
            elif target["kind"] == "folder":
                folder = self.request("GET", f"drive/explorer/v2/folder/{target['folder_token']}/meta", token=token)
                result.update(name=folder.get("name", "文件夹"), path=[folder.get("name", "文件夹")],
                              can_attempt_create=doc_scope, permission_state="unknown" if doc_scope else "scope_missing",
                              reason="目录可读；官方只读接口未提供创建权限，提交创建时由飞书核验。权限沿用目录，完整祖先路径未核验。",
                              error_code="create_permission_unverified" if doc_scope else "user_scope_missing")
            else:
                node = self.request("GET", "wiki/v2/spaces/get_node", token=token,
                                    params={"token": target["node_token"]})["node"]
                if node.get("space_id") != target["space_id"] or node.get("node_type") != "origin":
                    raise FeishuError("请选择当前空间的实体父节点", 422, code="invalid_destination")
                result.update(name=node.get("title", "知识库节点"), path=[node.get("title", "知识库节点")])
                permission = self.request("GET", f"drive/v1/permissions/{target['node_token']}/members/auth",
                                          token=token, params={"type": "wiki", "action": "edit"})
                allowed = permission.get("auth_result") is True
                wiki_scope = bool(scopes & {"wiki:wiki", "wiki:node:create"})
                can_create = allowed and wiki_scope and write_scope
                result.update(can_create=can_create, can_attempt_create=can_create,
                              permission_state="allowed" if can_create else "denied" if not allowed else "scope_missing",
                              reason="已核验父知识库节点编辑权限；最终创建仍受空间策略限制。" if can_create else "缺少父节点编辑权限或用户授权的知识库创建权限",
                              error_code="" if can_create else "permission_denied" if not allowed else "user_scope_missing")
                result["public_permission"] = self.request("GET", f"drive/v2/permissions/{target['node_token']}/public",
                                                            token=token, params={"type": "wiki"}).get("permission_public", {})
                # Full paths are best-effort evidence, never fabricated from caller labels.
                try:
                    names, seen = [node.get("title", "知识库节点")], {target["node_token"]}
                    ancestor = node.get("parent_node_token", "")
                    for _ in range(24):
                        if not ancestor or ancestor in seen:
                            break
                        seen.add(ancestor)
                        parent = self.request("GET", "wiki/v2/spaces/get_node", token=token,
                                              params={"token": ancestor})["node"]
                        if parent.get("space_id") != target["space_id"]:
                            break
                        names.insert(0, parent.get("title", "知识库节点"))
                        ancestor = parent.get("parent_node_token", "")
                    space = self.request("GET", f"wiki/v2/spaces/{target['space_id']}", token=token)["space"]
                    result.update(path=[space["name"], *names], path_complete=not ancestor)
                except (FeishuError, KeyError):
                    pass
        except FeishuError as exc:
            result.update(can_create=False, can_attempt_create=False, permission_state="unavailable",
                          reason=exc.detail, error_code=exc.code, http_status=exc.status_code,
                          uncertain=exc.uncertain)
        return result

    def authorize(self, owner):
        self.require_config()
        state = secrets.token_urlsafe(32)
        with session_scope() as db:
            db.execute(delete(FeishuOAuthDB).where(FeishuOAuthDB.owner == owner))
            db.add(FeishuOAuthDB(digest=hashlib.sha256(state.encode()).hexdigest(), owner=owner,
                                 expires=str(time.time() + 600)))
        url = "https://accounts.feishu.cn/open-apis/authen/v1/authorize?" + urlencode(
            {"client_id": self.config.feishu_app_id, "redirect_uri": self.config.feishu_redirect_uri,
             "scope": self.config.feishu_scopes, "state": state})
        import qrcode
        output = BytesIO()
        qrcode.make(url).save(output, format="PNG")
        return {"state": state, "url": url, "expires_at": time.time() + 600,
                "qr_data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()}

    def consume_state(self, state):
        digest = hashlib.sha256(state.encode()).hexdigest()
        with session_scope() as db:
            row = db.get(FeishuOAuthDB, digest)
            if not row or float(row.expires) < time.time():
                raise FeishuError("授权请求已过期，请回到 VINote 重新连接")
            owner = row.owner
            result = db.execute(delete(FeishuOAuthDB).where(FeishuOAuthDB.digest == digest))
            if result.rowcount != 1:
                raise FeishuError("授权请求已使用，请重新连接")
            return owner

    def exchange(self, body):
        return self.request("POST", "authen/v2/oauth/token", body={
            "client_id": self.config.feishu_app_id, "client_secret": self.config.feishu_app_secret, **body})

    def callback(self, state, code):
        digest = hashlib.sha256(state.encode()).hexdigest()
        with session_scope() as db:
            pending = db.get(FeishuOAuthDB, digest)
            if not pending:
                raise FeishuError("授权请求已过期，请重新连接")
            owner = pending.owner
        with _lock(owner):
            self.consume_state(state)
            return self.for_owner(owner)._finish_callback(code)

    def _finish_callback(self, code):
        self.require_config()
        owner = self.owner
        tokens = self.exchange({"grant_type": "authorization_code", "code": code,
                                "redirect_uri": self.config.feishu_redirect_uri})
        identity = self.request("GET", "authen/v1/user_info", token=tokens["access_token"])
        self.store_connection(owner, tokens, identity)

    def store_connection(self, owner, tokens, identity):
        if identity.get("tenant_key") != self.config.feishu_tenant_key:
            raise FeishuError("第一版仅支持当前公司飞书账号", 403)
        if not identity.get("open_id"):
            raise FeishuError("无法确认飞书身份，请重新连接")
        tokens = {**tokens, "expires_at": time.time() + tokens.get("expires_in", 7200)}
        with _lock(owner), session_scope() as db:
            row = db.get(FeishuConnectionDB, owner)
            if row and row.open_id and row.open_id != identity["open_id"]:
                raise FeishuError("请先断开已有飞书账号再绑定新账号", 409)
            if not row:
                row = FeishuConnectionDB(owner=owner)
                db.add(row)
            row.open_id, row.name = identity["open_id"], identity.get("name", "飞书用户")
            preferences = json.loads(row.preferences or "{}")
            preferences.setdefault("connection_id", str(uuid.uuid4()))
            row.preferences = json.dumps(preferences)
            row.tokens = _cipher().encrypt(json.dumps(tokens).encode()).decode()
            row.expired = False

    def user_token(self, owner):
        # Keep failure marking inside the lock too: a late 401 must not mark a
        # newly connected identity expired after disconnect/reconnect.
        with _lock(owner):
            with session_scope() as db:
                row = db.get(FeishuConnectionDB, owner)
                expected_tokens = row.tokens if row else None
            try:
                return self._user_token(owner)
            except FeishuError as exc:
                if exc.status_code == 401:
                    with session_scope() as db:
                        # Compare the encrypted credential snapshot as well: a
                        # different process may have disconnected/reconnected.
                        db.execute(update(FeishuConnectionDB).where(
                            FeishuConnectionDB.owner == owner,
                            FeishuConnectionDB.tokens == expected_tokens,
                        ).values(expired=True))
                raise

    def _user_token(self, owner):
        with _lock(owner), session_scope() as db:
            row = db.scalar(select(FeishuConnectionDB).where(FeishuConnectionDB.owner == owner).with_for_update())
            if not row or not row.tokens or row.expired:
                raise FeishuError("请先在设置中连接飞书", 401)
            try:
                tokens = json.loads(_cipher().decrypt(row.tokens.encode()))
                if tokens["expires_at"] > time.time() + 120:
                    return tokens["access_token"]
                refresh_token = tokens["refresh_token"]
                if not isinstance(refresh_token, str) or not refresh_token:
                    raise ValueError("missing refresh credential")
            except (InvalidToken, KeyError, ValueError, TypeError):
                raise FeishuError("飞书授权已过期，请重新连接", 401) from None
            refreshed = self.exchange({"grant_type": "refresh_token", "refresh_token": refresh_token})
            # A malformed refresh must not make the old access token fresh.
            lifetime = refreshed.get("expires_in") if isinstance(refreshed, dict) else None
            if (not isinstance(refreshed, dict) or
                    not isinstance(refreshed.get("access_token"), str) or not refreshed["access_token"] or
                    isinstance(lifetime, bool) or not isinstance(lifetime, (int, float)) or
                    not math.isfinite(lifetime) or lifetime <= 0 or
                    ("scope" in refreshed and not isinstance(refreshed["scope"], str)) or
                    ("refresh_token" in refreshed and
                     (not isinstance(refreshed["refresh_token"], str) or not refreshed["refresh_token"]))):
                raise FeishuError("暂时无法核验飞书授权，请稍后重试", 502)
            # OAuth refresh may omit unchanged scope or refresh_token; explicit
            # reduced/empty scope replaces the old grant rather than unioning it.
            tokens = {**tokens, **refreshed, "expires_at": time.time() + lifetime}
            row.tokens = _cipher().encrypt(json.dumps(tokens).encode()).decode()
            return tokens["access_token"]

    def bot_token(self):
        self.require_config()
        return self.request("POST", "auth/v3/tenant_access_token/internal", body={
            "app_id": self.config.feishu_app_id, "app_secret": self.config.feishu_app_secret})["tenant_access_token"]

    def groups(self, owner):
        user_token, bot_token = self.user_token(owner), self.bot_token()
        def chats(token):
            items, page = [], ""
            while True:
                result = self.request("GET", "im/v1/chats", token=token,
                                      params={"page_size": 100, **({"page_token": page} if page else {})})
                items.extend(result.get("items", []))
                if not result.get("has_more"):
                    return items
                page = result["page_token"]
        bot_ids = {item["chat_id"] for item in chats(bot_token)}
        return [{"chat_id": item["chat_id"], "name": item.get("name", "群聊")}
                for item in chats(user_token) if item["chat_id"] in bot_ids]

    def contact_binding(self, owner):
        with session_scope() as db:
            row = db.get(FeishuConnectionDB, owner)
            if not row or not row.tokens or row.expired:
                raise FeishuError("请先连接飞书", 401)
            if "contact:user:search" not in self.granted_scopes(row):
                raise FeishuError("当前授权缺少联系人搜索权限", 403, code="user_scope_missing")
            connection_id = json.loads(row.preferences).get("connection_id")
            if not connection_id:
                raise FeishuError("请重新连接飞书后选择联系人", 409, code="connection_changed")
            return {"owner": owner, "connection_id": connection_id, "sender_open_id": row.open_id,
                    "app_id": self.config.feishu_app_id, "tenant_key": self.config.feishu_tenant_key}

    def contacts(self, owner, query, page_size=20, page_token=""):
        """Read-only search, one page, no bot identity fallback or scope expansion.

        Official evidence: contact-v3/user/search-users.md specifies GET
        search/v1/user, user_access_token, contact:user:search and data.users.
        Selection tokens are opaque 15-minute proofs of this owner's results;
        they are not Feishu credentials or a promise of bot availability/access.
        """
        if (not isinstance(query, str) or not query.strip() or len(query) > 50 or
                type(page_size) is not int or not 1 <= page_size <= 50 or
                not isinstance(page_token, str) or len(page_token) > 2000):
            raise FeishuError("联系人查询参数无效", 422, code="invalid_contact_query")
        with _lock(owner):
            token = self.user_token(owner)
            binding = self.contact_binding(owner)
            result = self.request("GET", "search/v1/user", token=token,
                                  params={"query": query.strip(), "page_size": page_size,
                                          **({"page_token": page_token} if page_token else {})})
            users = result.get("users")
            has_more, next_page = result.get("has_more"), result.get("page_token", "")
            if (not isinstance(users, list) or type(has_more) is not bool or
                    not isinstance(next_page, str) or len(next_page) > 2000 or
                    (has_more and not next_page)):
                raise FeishuError("飞书联系人响应不完整，请重新读取", 502, code="contacts_response_invalid")
            if self.contact_binding(owner) != binding:
                raise FeishuError("飞书连接已变化，请重新选择联系人", 409, code="connection_changed")
            items = []
            for user in users:
                if (not isinstance(user, dict) or not isinstance(user.get("open_id"), str) or
                        not re.fullmatch(r"ou_[A-Za-z0-9_-]{1,196}", user["open_id"]) or
                        not isinstance(user.get("name"), str) or not user["name"].strip() or
                        len(user["name"]) > 500):
                    raise FeishuError("飞书联系人身份不完整，请重新读取", 502, code="contacts_response_invalid")
                identity = {"open_id": user["open_id"], "name": user["name"]}
                selection = _cipher().encrypt(json.dumps({"purpose": "feishu_contact_selection_v1",
                                                          **binding, **identity}).encode()).decode()
                items.append({**identity, "selection_token": selection})
            return {"items": items, "has_more": has_more, "page_token": next_page if has_more else "",
                    "selection_expires_in": 900, "reading_permission": "not_checked",
                    "bot_availability": "not_checked"}

    def validate_contacts(self, owner, contacts):
        if not isinstance(contacts, list) or len(contacts) > 20:
            raise FeishuError("联系人列表无效", 422, code="invalid_recipient")
        if not contacts:
            return []
        self.user_token(owner)
        binding = self.contact_binding(owner)
        selected = {}
        for item in contacts:
            if (not isinstance(item, dict) or set(item) != {"open_id", "selection_token"} or
                    not isinstance(item["open_id"], str) or
                    not re.fullmatch(r"ou_[A-Za-z0-9_-]{1,196}", item["open_id"]) or
                    not isinstance(item["selection_token"], str) or not 1 <= len(item["selection_token"]) <= 4096):
                raise FeishuError("联系人选择无效", 422, code="invalid_recipient")
            try:
                proof = json.loads(_cipher().decrypt(item["selection_token"].encode(), ttl=900))
            except (InvalidToken, ValueError, UnicodeError):
                raise FeishuError("联系人选择已失效，请重新搜索并选择", 422, code="contact_selection_expired") from None
            if (not isinstance(proof, dict) or proof.get("purpose") != "feishu_contact_selection_v1" or
                    any(proof.get(key) != value for key, value in binding.items()) or
                    proof.get("open_id") != item["open_id"] or not isinstance(proof.get("name"), str)):
                raise FeishuError("联系人选择与当前账号或应用不匹配", 422, code="invalid_recipient")
            selected[item["open_id"]] = proof
        return list(selected.values())

    def save_preferences(self, owner, preferences):
        self.user_token(owner)
        with session_scope() as db:
            saved = json.loads(db.get(FeishuConnectionDB, owner).preferences)
        destination = self.normalize_destination(preferences.get("destination_config", saved.get("destination_config")))
        policy = self.normalize_policy(destination, preferences.get("permission_policy") or (
            saved.get("permission_policy") if "destination_config" not in preferences else None))
        if "destination_config" in preferences:
            checked = self.check_destination(owner, destination)
            if not checked["can_attempt_create"]:
                raise FeishuError(checked["reason"], 403, code=checked["error_code"])
        groups = self.validate_groups(preferences.get("groups", []))
        available_groups = self.groups(owner) if groups else []
        available = {item["chat_id"] for item in available_groups}
        if any(group not in available for group in groups):
            raise FeishuError("目标群不可用，请确认你与机器人均在群内并刷新列表")
        if preferences.get("auto_publish") and not (preferences.get("notify_self") or groups) and "destination_config" not in preferences and "destination_config" not in saved:
            raise FeishuError("自动交付至少需要选择本人或一个群")
        with session_scope() as db:
            row = db.get(FeishuConnectionDB, owner)
            if not row or not row.tokens:
                raise FeishuError("飞书连接已断开", 401)
            merged = {**json.loads(row.preferences),
                "notify_self": bool(preferences.get("notify_self")), "groups": groups,
                "group_names": {item["chat_id"]: item["name"] for item in available_groups if item["chat_id"] in groups},
                "auto_publish": bool(preferences.get("auto_publish"))}
            # Legacy clients must not reset a destination selected by another device.
            if "destination_config" in preferences or "destination_config" in saved or "permission_policy" in preferences:
                merged.update(destination_config=destination, permission_policy=policy)
            row.preferences = json.dumps(merged)
        return self.status(owner)

    def disconnect(self, owner):
        with _lock(owner), session_scope() as db:
            db.execute(delete(FeishuConnectionDB).where(FeishuConnectionDB.owner == owner))
            db.execute(delete(FeishuOAuthDB).where(FeishuOAuthDB.owner == owner))
        return self.status(owner)

    def serialize(self, row, db=None):
        if db is None:
            with session_scope() as session:
                return self.serialize(row, db=session)
        interrupted = (row.status == "processing" and float(row.lease_until) < time.time()) or (row.status == "queued" and row.created_at.replace(tzinfo=timezone.utc).timestamp() < time.time() - 300)
        metadata = db.get(FeishuDeliveryDestinationDB, row.id)
        snapshot = json.loads(metadata.snapshot) if metadata else {}
        source = snapshot.get("content_source", {"kind": "legacy_unverified", "verified": False})
        recipients = json.loads(row.recipients)
        phase = metadata.phase if metadata else ("completed" if row.status == "completed" else "pending_create" if row.status == "queued" else "failed")
        if row.document_id == "__creating__" or (any(item.get("status") in ("unknown", "sending") for item in recipients.values()) and row.status != "processing"):
            phase = "unknown"
        elif receipts.has_unknown_batch(db, row.id) or (interrupted and phase == "writing"):
            phase = "unknown"
        elif recipient_access.has_permission_unknown(recipients):
            phase = "permission_unknown"
        elif interrupted:
            phase = "unknown" if any(item.get("status") == "sending" for item in recipients.values()) else "failed"
        return {"id": row.id, "status": "failed" if interrupted else row.status, "document_url": row.document_url,
                "needs_document_recovery": row.document_id == "__creating__",
                "recipients": recipients, "error": "交付被中断，请重试" if interrupted else row.error, "revision": row.revision,
                "phase": phase, "destination": snapshot.get("destination", {"kind": "personal"}),
                "recipient_access_policy": snapshot.get("recipient_access_policy"),
                "permission": json.loads(metadata.permission) if metadata else {"status": "legacy_unverified"},
                "error_code": "permission_unknown" if phase == "permission_unknown" else metadata.error_code if metadata else "",
                "content_revision": snapshot.get("content_revision", row.revision),
                "version_id": source.get("version_id") if source.get("verified") else None,
                "revision_id": source.get("revision_id") if source.get("verified") else None,
                "content_source": source,
                "formatting": {
                    **snapshot.get("format_selection", {"protocol": "legacy-unknown", "message": "历史交付未核验转换范围"}),
                    "status": ("unsupported" if snapshot.get("format_selection", {}).get("image_source_preserved") else
                               "written" if row.status == "completed" and "body_plan" in snapshot else
                               "basic" if not snapshot.get("format_selection", {}).get("needs_converter") else "pending"),
                    "native_write_confirmed": bool(row.status == "completed" and "body_plan" in snapshot),
                    "images_embedded": False},
                "publication_mode": "new_document", "execution_location": "server"}

    def recover_document(self, owner, job_id, url):
        """Resolve an unknown create outcome without silently creating a duplicate."""
        parsed = urlparse(url)
        expected = urlparse(self.config.feishu_doc_base_url)
        parts = parsed.path.strip("/").split("/")
        if parsed.scheme != "https" or parsed.netloc != expected.netloc or parsed.username or parsed.password or len(parts) != 2 or parts[0] not in ("docx", "wiki") or not parts[1].isalnum():
            raise FeishuError("请填写本公司飞书文档链接")
        with _lock(owner), session_scope() as db:
            job = db.get(FeishuDeliveryDB, job_id)
            if not job or job.owner != owner:
                raise FeishuError("交付记录不存在", 404)
            if job.document_id != "__creating__" or float(job.lease_until) > time.time():
                raise FeishuError("此交付当前不需要恢复文档")
            metadata = db.get(FeishuDeliveryDestinationDB, job_id)
            snapshot = json.loads(metadata.snapshot) if metadata else {}
            destination = snapshot.get("destination", {"kind": "personal"})
            self.assert_delivery_connection(owner, snapshot)
            token = self.user_token(owner)
            document_id = parts[1]
            if destination["kind"] == "wiki":
                node = self.request("GET", "wiki/v2/spaces/get_node", token=token,
                                    params={"token": parts[1], "obj_type": parts[0]})["node"]
                if (node.get("space_id") != destination["space_id"] or
                        node.get("parent_node_token") != destination["node_token"] or
                        node.get("obj_type") != "docx" or node.get("node_type") != "origin"):
                    raise FeishuError("恢复文档不在本次发布的知识库父节点下", 409, code="destination_mismatch")
                document_id = node["obj_token"]
                url = self.config.feishu_doc_base_url + "/wiki/" + node["node_token"]
            elif parts[0] != "docx":
                raise FeishuError("此交付需要云文档链接，不能改为知识库节点", 409, code="destination_mismatch")
            if destination["kind"] == "folder":
                found, page, seen = False, "", set()
                for _ in range(100):
                    listing = self.request("GET", "drive/v1/files", token=token,
                                           params={"folder_token": destination["folder_token"], "page_size": 200,
                                                   **({"page_token": page} if page else {})})
                    found = any(item.get("token") == document_id and item.get("type") == "docx" for item in listing.get("files", []))
                    if found or not listing.get("has_more"):
                        break
                    page = listing.get("next_page_token", "")
                    if not page or page in seen:
                        break
                    seen.add(page)
                if not found:
                    raise FeishuError("无法核验恢复文档在本次目标文件夹内", 409, code="destination_mismatch")
            document = self.request("GET", f"docx/v1/documents/{document_id}", token=token)["document"]
            children = self.request("GET", f"docx/v1/documents/{document_id}/blocks/{document_id}/children", token=token, params={"page_size": 500})
            # A create-time interruption occurs before writing any body blocks.
            if document.get("title") != job.title or children.get("items") or children.get("has_more"):
                raise FeishuError("仅可关联本次会议同名、空白且可访问的文档；请检查所填链接")
            job.document_id = document_id
            job.document_url = url if destination["kind"] == "wiki" else self.config.feishu_doc_base_url + "/docx/" + document_id
            job.status, job.error, job.lease_until = "failed", "文档已关联，可以重试继续交付", "0"
            if metadata:
                metadata.phase, metadata.error_code = "pending_create", ""
            return self.serialize(job, db=db)

    def delivery(self, owner, note_key):
        with session_scope() as db:
            row = db.scalar(select(FeishuDeliveryDB).where(FeishuDeliveryDB.owner == owner,
                FeishuDeliveryDB.note_key == note_key).order_by(FeishuDeliveryDB.created_at.desc()))
            return self.serialize(row, db=db) if row else None

    def delivery_by_id(self, owner, job_id):
        with session_scope() as db:
            return self.serialize(receipts.owned_job(db, owner, job_id), db=db)

    def delivery_by_operation(self, owner, operation_id):
        with session_scope() as db:
            job = receipts.operation_job(db, owner, operation_id)
            if not job:
                raise FeishuError("未找到原发布回执，请保留未确认请求；不会自动重新发布", 404, code="receipt_not_found")
            return {**self.serialize(job, db=db), "operation_id": operation_id}

    @staticmethod
    def resolve_content(db, owner, note_key, title, content, version_id, revision_id, source_mode=None):
        """Bind publication to account-owned immutable data, never caller labels.

        revision_id is the observed workspace aggregate revision (a CAS guard),
        not a claimed original creation revision of an imported historical version.
        A deliberately published device snapshot is frozen from the request,
        even when a retired workspace row exists for the same note key.
        """
        note = db.get(WorkspaceNoteDB, (owner, note_key))
        referenced = version_id is not None or revision_id is not None
        if source_mode == "local_snapshot" and referenced:
            raise FeishuError("当前发布不能同时引用旧的同步版本", 422, code="invalid_source_reference")
        if source_mode == "local_snapshot" or not note:
            if referenced:
                raise FeishuError("未找到此账号的同步内容，请先同步并刷新版本", 404, code="workspace_reference_not_found")
            if not isinstance(title, str) or not title.strip() or not isinstance(content, str) or not content.strip():
                raise FeishuError("发布必须提供标题和正文", 422, code="local_content_required")
            return title, content, {"kind": "local_snapshot", "verified": False, "note_key": note_key,
                                    "version_id": None, "revision_id": None, "captured_at": time.time(),
                                    "explicit": source_mode == "local_snapshot"}
        if note.deleted:
            raise FeishuError("同步内容已进入回收站，请先恢复再发布", 409, code="workspace_deleted")
        if referenced:
            if not isinstance(revision_id, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", revision_id):
                raise FeishuError("revision_id 必须是服务端 workspace.revision 的十进制字符串", 422, code="invalid_workspace_revision")
            if str(note.revision) != revision_id:
                raise FeishuError("同步内容已更新，请刷新后确认要发布的版本", 409, code="workspace_revision_conflict")
        selected = None
        if version_id is not None:
            selected = db.get(WorkspaceVersionDB, (owner, note_key, version_id))
            if not selected:
                raise FeishuError("未找到此笔记的已保存版本，请刷新版本列表", 404, code="workspace_reference_not_found")
        else:
            # Normal saves have an immutable current-N entry. Restore-only revisions
            # may not; the aggregate row itself still establishes the saved content.
            current = db.get(WorkspaceVersionDB, (owner, note_key, f"current-{note.revision}"))
            if current and current.title == note.title and current.content == note.content:
                selected = current
        saved_title = selected.title if selected else note.title
        saved_content = selected.content if selected else note.content
        if not saved_content.strip():
            raise FeishuError("所选已保存版本没有可发布正文", 422, code="empty_workspace_content")
        if (title is not None and title != saved_title) or (content is not None and content != saved_content):
            raise FeishuError("提交内容与服务端已保存版本不一致，请先保存同步或重新选择版本", 409, code="workspace_content_mismatch")
        return saved_title, saved_content, {"kind": "workspace", "verified": True, "note_key": note_key,
            "version_id": selected.id if selected else None, "revision_id": str(note.revision),
            "captured_at": time.time(), "revision_semantics": "observed_workspace_revision"}

    @staticmethod
    def verify_source_unchanged(db, owner, source, title, content):
        # Network preflight is outside the write transaction. Recheck before the
        # snapshot commit so a concurrent edit/deletion cannot change its meaning.
        note = db.scalar(select(WorkspaceNoteDB).where(
            WorkspaceNoteDB.owner == owner, WorkspaceNoteDB.key == source["note_key"]).with_for_update())
        if source["kind"] == "local_snapshot":
            if note and not source.get("explicit"):
                raise FeishuError("内容刚刚同步到服务端，请刷新后再发布", 409, code="workspace_revision_conflict")
            return
        if not note or note.deleted or str(note.revision) != source["revision_id"]:
            raise FeishuError("发布准备期间同步内容已变更，请刷新后重新确认", 409, code="workspace_revision_conflict")
        selected = db.get(WorkspaceVersionDB, (owner, note.key, source["version_id"])) if source["version_id"] else note
        if not selected or selected.title != title or selected.content != content:
            raise FeishuError("已保存版本发生冲突，停止发布", 409, code="workspace_content_mismatch")

    def enqueue(self, owner, note_key, title=None, content=None, automatic=False, *, destination_config=None,
                permission_policy=None, notify_self=None, groups=None, version_id=None, revision_id=None,
                operation_id=None, source_mode=None, contacts=None, recipient_access_policy=None):
        if recipient_access_policy is not None and (
                recipient_access_policy != recipient_access.POLICY or automatic or not operation_id):
            raise FeishuError("阅读授权与通知需要明确的新发布操作", 422, code="explicit_publish_required")
        if contacts and (automatic or not operation_id):
            raise FeishuError("联系人通知需要手动确认及 operation_id", 422, code="explicit_publish_required")
        if source_mode == "local_snapshot" and automatic:
            raise FeishuError("请在预览正文后手动确认发布", 422, code="explicit_publish_required")
        request_payload = dict(note_key=note_key, title=title, content=content, automatic=automatic,
            destination_config=destination_config, permission_policy=permission_policy, notify_self=notify_self,
            groups=groups, version_id=version_id, revision_id=revision_id, source_mode=source_mode)
        if contacts is not None:
            request_payload["contacts"] = contacts
        if recipient_access_policy is not None:
            request_payload["recipient_access_policy"] = recipient_access_policy
        request_hash = receipts.fingerprint(request_payload)
        if operation_id:
            with session_scope() as db:
                prior = receipts.operation_job(db, owner, operation_id, request_hash)
                if prior:
                    return {**self.serialize(prior, db=db), "operation_id": operation_id, "_dispatch_required": False}
        # Resolve and validate outside the write transaction (network calls can refresh OAuth).
        with session_scope() as db:
            account = db.get(FeishuConnectionDB, owner)
            preferences = json.loads(account.preferences) if account else {}
            title, content, source = self.resolve_content(db, owner, note_key, title, content, version_id, revision_id, source_mode)
        if automatic and not preferences.get("auto_publish"):
            return None
        selected_contacts = self.validate_contacts(owner, contacts if contacts is not None else [])
        enhanced = bool(recipient_access_policy) or bool(selected_contacts) or source["kind"] == "workspace" or any(v is not None for v in (destination_config, permission_policy, notify_self, groups, version_id, revision_id)) or "destination_config" in preferences
        version_id, revision_id = source["version_id"], source["revision_id"]
        target = self.normalize_destination(destination_config or preferences.get("destination_config"))
        policy = self.normalize_policy(target, permission_policy or (preferences.get("permission_policy") if destination_config is None else None))
        destination = self.check_destination(owner, target) if enhanced else {"kind": "personal"}
        if enhanced and not destination["can_attempt_create"]:
            raise FeishuError(destination["reason"], destination.get("http_status", 403),
                              uncertain=destination.get("uncertain", False), code=destination["error_code"])
        selected_groups = self.validate_groups(groups if groups is not None else
                                              [] if recipient_access_policy else preferences.get("groups", []))
        notify = (False if recipient_access_policy else preferences.get("notify_self", True)) if notify_self is None else notify_self
        available_groups = self.groups(owner) if enhanced and selected_groups else []
        if enhanced and any(g not in {item["chat_id"] for item in available_groups} for g in selected_groups):
            raise FeishuError("目标群不可用，请确认本人和机器人均在群内", 403, code="recipient_unavailable")
        content_revision = hashlib.sha256((title + "\n" + content).encode()).hexdigest()
        context = {"destination": target, "permission_policy": policy, "notify_self": notify,
                   "connection_id": preferences.get("connection_id"),
                   "groups": sorted(selected_groups), "version_id": version_id, "revision_id": revision_id}
        if selected_contacts:
            context["contacts"] = sorted(item["open_id"] for item in selected_contacts)
        if recipient_access_policy is not None:
            context["recipient_access_policy"] = recipient_access_policy
        revision = hashlib.sha256((content_revision + json.dumps(context, sort_keys=True)).encode()).hexdigest() if enhanced else content_revision
        try:
            return self._enqueue(owner, note_key, title, content, automatic, enhanced, destination, policy,
                                 notify, selected_groups, available_groups, version_id, revision_id, content_revision, revision, source,
                                 operation_id, request_hash, selected_contacts, recipient_access_policy)
        except IntegrityError:
            # Cross-process duplicate requests converge on the DB unique constraint.
            with session_scope() as db:
                if operation_id:
                    prior = receipts.operation_job(db, owner, operation_id, request_hash)
                    if prior:
                        return {**self.serialize(prior, db=db), "operation_id": operation_id, "_dispatch_required": False}
                previous = db.scalar(select(FeishuDeliveryDB).where(FeishuDeliveryDB.owner == owner,
                    FeishuDeliveryDB.note_key == note_key, FeishuDeliveryDB.revision == revision))
                if previous:
                    receipts.bind_operation(db, owner, operation_id, request_hash, previous)
                    return {**self.serialize(previous, db=db), **({"operation_id": operation_id, "_dispatch_required": False} if operation_id else {})}
            raise

    def _enqueue(self, owner, note_key, title, content, automatic, enhanced, destination, policy,
                 notify_self, groups, available_groups, version_id, revision_id, content_revision, revision, source,
                 operation_id=None, request_hash=None, contacts=None, recipient_access_policy=None):
        with _lock(owner), session_scope() as db:
            if operation_id:
                prior = receipts.operation_job(db, owner, operation_id, request_hash)
                if prior:
                    return {**self.serialize(prior, db=db), "operation_id": operation_id, "_dispatch_required": False}
            account = db.scalar(select(FeishuConnectionDB).where(FeishuConnectionDB.owner == owner).with_for_update())
            if not account or not account.tokens:
                if automatic:
                    return None
                raise FeishuError("请先连接飞书", 401)
            preferences = json.loads(account.preferences)
            for contact in contacts or []:
                if (contact["connection_id"] != preferences.get("connection_id") or
                        contact["sender_open_id"] != account.open_id or account.expired or
                        contact["app_id"] != self.config.feishu_app_id or
                        contact["tenant_key"] != self.config.feishu_tenant_key):
                    raise FeishuError("飞书连接已变化，请重新选择联系人", 409, code="connection_changed")
            if automatic and not preferences.get("auto_publish"):
                return None
            self.verify_source_unchanged(db, owner, source, title, content)
            # Auto publication is the first successful minutes only; edits are explicit.
            existing = db.scalar(select(FeishuDeliveryDB).where(FeishuDeliveryDB.owner == owner,
                FeishuDeliveryDB.note_key == note_key).order_by(FeishuDeliveryDB.created_at.desc()))
            if existing and (automatic or existing.revision == revision):
                receipts.bind_operation(db, owner, operation_id, request_hash, existing)
                return {**self.serialize(existing, db=db), **({"operation_id": operation_id, "_dispatch_required": False} if operation_id else {})}
            previous = db.scalar(select(FeishuDeliveryDB).where(FeishuDeliveryDB.owner == owner,
                FeishuDeliveryDB.note_key == note_key, FeishuDeliveryDB.revision == revision))
            if previous:
                receipts.bind_operation(db, owner, operation_id, request_hash, previous)
                return {**self.serialize(previous, db=db), **({"operation_id": operation_id, "_dispatch_required": False} if operation_id else {})}
            targets = ([account.open_id] if notify_self else []) + groups + [item["open_id"] for item in contacts or []]
            if not targets and not enhanced:
                raise FeishuError("请先设置通知对象")
            group_names = {**preferences.get("group_names", {}), **{item["chat_id"]: item["name"] for item in available_groups}}
            contact_names = {item["open_id"]: item["name"] for item in contacts or []}
            row = FeishuDeliveryDB(owner=owner, note_key=note_key, revision=revision, title=title, content=content,
                recipients=json.dumps({target: {"status": "pending", "name": "本人" if target == account.open_id else
                    contact_names.get(target, group_names.get(target, "指定群")),
                    **({"kind": "contact", "reading_permission": {"status": "not_checked"}}
                       if target in contact_names else {})}
                                       for target in targets}))
            db.add(row)
            db.flush()
            snapshot = {"destination": destination, "permission_policy": policy, "enhanced": enhanced,
                        "format_selection": native_markdown.format_selection(content),
                        **({"body_format": native_markdown.SELECTIVE_PROTOCOL,
                            "format_segments": native_markdown.segments(content)}
                           if native_markdown.format_selection(content)["needs_converter"] else {}),
                        "content_revision": content_revision, "version_id": version_id, "revision_id": revision_id,
                        "content_source": source, "automatic": automatic,
                        "open_id": account.open_id, "connection_id": preferences.get("connection_id"),
                        "tenant_key": self.config.feishu_tenant_key}
            if contacts:
                snapshot["contacts"] = [{"open_id": item["open_id"], "name": item["name"]} for item in contacts]
                snapshot["contact_selection_protocol"] = 1
                snapshot["app_id"] = contacts[0]["app_id"]
            if recipient_access_policy is not None:
                snapshot.update(recipient_access_policy=recipient_access_policy,
                                recipient_access_protocol=recipient_access.PROTOCOL,
                                app_id=self.config.feishu_app_id)
            db.add(FeishuDeliveryDestinationDB(delivery_id=row.id, snapshot=json.dumps(snapshot),
                                              permission=json.dumps({"status": "pending" if enhanced else "legacy_unverified"})))
            db.flush()
            receipts.bind_operation(db, owner, operation_id, request_hash, row)
            return {**self.serialize(row, db=db), **({"operation_id": operation_id, "_dispatch_required": True} if operation_id else {})}

    def pending_recovery(self, owner, limit=3):
        """Bounded, explicitly triggered recovery; no daemon or infinite retry loop."""
        if not isinstance(limit, int) or not 1 <= limit <= 5:
            raise FeishuError("一次最多恢复 5 个任务", 422)
        self.require_config()
        self.user_token(owner)
        scheduled, attention = [], []
        with session_scope() as db:
            account = db.get(FeishuConnectionDB, owner)
            connection_id = json.loads(account.preferences).get("connection_id")
            jobs = db.scalars(select(FeishuDeliveryDB).where(
                FeishuDeliveryDB.owner == owner, FeishuDeliveryDB.status.in_(["queued", "processing"])
            ).order_by(FeishuDeliveryDB.created_at).limit(100)).all()
            for job in jobs:
                if float(job.lease_until) > time.time():
                    continue
                metadata = db.get(FeishuDeliveryDestinationDB, job.id)
                snapshot = json.loads(metadata.snapshot) if metadata else {}
                recipients = json.loads(job.recipients)
                # Never infer consent for legacy records or reconnection; never
                # replay an unknown side effect using a time-bounded provider UUID.
                if (not snapshot.get("connection_id") or snapshot["connection_id"] != connection_id or
                        snapshot.get("open_id") != account.open_id or job.document_id == "__creating__" or
                        any(item.get("status") in ("sending", "unknown") for item in recipients.values()) or
                        recipient_access.has_permission_unknown(recipients) or
                        (job.status == "processing" and metadata.phase == "writing")):
                    attention.append(job.id)
                    continue
                if len(scheduled) < limit:
                    scheduled.append(job.id)
        return {"scheduled": scheduled, "needs_attention": attention, "background_delivery": False,
                "scan_limit": 100}

    def checkpoint(self, owner, job_id, **patch):
        patch.setdefault("lease_until", str(time.time() + 300))
        with session_scope() as db:
            row = db.get(FeishuDeliveryDB, job_id)
            if not row or row.owner != owner:
                raise FeishuError("交付记录不存在", 404)
            metadata_patch = {key: patch.pop(key) for key in ("phase", "permission", "error_code") if key in patch}
            metadata = db.get(FeishuDeliveryDestinationDB, job_id)
            if metadata:
                for key, value in metadata_patch.items():
                    setattr(metadata, key, json.dumps(value) if key == "permission" else value)
            for key, value in patch.items():
                setattr(row, key, value)

    def create_document(self, owner, title):
        result = self.request("POST", "docx/v1/documents", token=self.user_token(owner), body={"title": title})
        document = result.get("document", {})
        if not document.get("document_id"):
            raise FeishuError("创建响应缺少文档标识，需要核验", 502, uncertain=True)
        return document["document_id"], self.config.feishu_doc_base_url + "/docx/" + document["document_id"]

    def create_at_destination(self, owner, title, destination):
        target = {key: destination[key] for key in ("kind", "folder_token", "space_id", "node_token") if key in destination}
        checked = self.check_destination(owner, target)
        if not checked["can_attempt_create"]:
            raise FeishuError(checked["reason"], 403, code=checked["error_code"])
        if target["kind"] == "personal":
            return self.create_document(owner, title)
        token = self.user_token(owner)
        if target["kind"] == "folder":
            data = self.request("POST", "docx/v1/documents", token=token,
                                body={"title": title, "folder_token": target["folder_token"]})
            document_id = data.get("document", {}).get("document_id")
            if not document_id:
                raise FeishuError("创建响应缺少文档标识，需要核验", 502, uncertain=True)
            return document_id, self.config.feishu_doc_base_url + "/docx/" + document_id
        data = self.request("POST", f"wiki/v2/spaces/{target['space_id']}/nodes", token=token,
                            body={"obj_type": "docx", "node_type": "origin", "title": title,
                                  "parent_node_token": target["node_token"]})
        node = data.get("node", {})
        if not node.get("obj_token") or not node.get("node_token") or node.get("obj_type") != "docx":
            raise FeishuError("创建响应缺少知识库文档标识，需要核验", 502, uncertain=True)
        return node["obj_token"], self.config.feishu_doc_base_url + "/wiki/" + node["node_token"]

    def ensure_permission(self, owner, job, snapshot):
        policy = snapshot["permission_policy"]
        token = self.user_token(owner)
        path = f"drive/v2/permissions/{job.document_id}/public"
        if policy == "private":
            self.request("PATCH", path, token=token, params={"type": "docx"}, body={
                "external_access_entity": "closed", "link_share_entity": "closed",
                "share_entity": "same_tenant", "manage_collaborator_entity": "collaborator_full_access"})
        actual = self.request("GET", path, token=token, params={"type": "docx"}).get("permission_public")
        if not isinstance(actual, dict) or not actual.get("link_share_entity"):
            raise FeishuError("无法核验文档实际权限，不发送通知", 502, code="permission_unverified")
        if policy == "private" and (actual.get("external_access_entity") != "closed" or actual.get("link_share_entity") != "closed"):
            raise FeishuError("文档未达到私有权限要求，不写入正文或发送通知", 403, code="permission_mismatch")
        return {"status": "verified", "policy": policy, "actual": actual,
                "access_scope": "external_and_link_sharing_closed" if policy == "private" else "inherited",
                "verification_scope": "public_sharing_settings",
                "organization_policy_verified": False,
                "note": "继承目标权限，未收窄父级访问范围" if policy == "inherit" else
                "已核验关闭组织外及链接分享；组织内部、上级与继承权限仍由飞书组织策略管理，接收人授权另行核验"}

    @staticmethod
    def validate_retry_recipients(job, selected):
        if not selected or set(selected) - set(json.loads(job.recipients)):
            raise FeishuError("只能重试该交付中已有的通知对象", 422, code="invalid_recipient")

    def assert_delivery_connection(self, owner, snapshot):
        if (snapshot.get("contact_selection_protocol") == 1 or snapshot.get("recipient_access_policy")) and (
                snapshot.get("app_id") != self.config.feishu_app_id or
                snapshot.get("tenant_key") != self.config.feishu_tenant_key):
            raise FeishuError("原联系人交付绑定的飞书应用或租户已变化，请核验原回执", 409, code="connection_changed")
        self.user_token(owner)
        with session_scope() as db:
            account = db.get(FeishuConnectionDB, owner)
            if not account or (snapshot.get("open_id") and account.open_id != snapshot["open_id"]):
                raise FeishuError("交付绑定的飞书账号已变更，请重新发布", 409, code="connection_changed")
            if snapshot.get("connection_id") and json.loads(account.preferences).get("connection_id") != snapshot["connection_id"]:
                raise FeishuError("原交付授权已随断开连接撤销，请重新发布", 409, code="connection_changed")

    def prepare_native_body(self, owner, job):
        # The new format is opt-in at enqueue. Old jobs keep exactly the old path.
        with session_scope() as db:
            receipts.owned_job(db, owner, job.id)
            metadata = db.get(FeishuDeliveryDestinationDB, job.id)
            snapshot = json.loads(metadata.snapshot) if metadata else {}
            if snapshot.get("format_selection", {}).get("image_source_preserved"):
                raise FeishuError("正文含图片，尚不支持原生图片写入；已在创建或写入文档前停止",
                                  422, code="format_unsupported")
            if "body_format" not in snapshot:
                return None
            if snapshot["body_format"] not in (native_markdown.PROTOCOL, native_markdown.SELECTIVE_PROTOCOL):
                raise FeishuError("原转换协议不可用，请核验交付回执", 409, code="format_changed")
            frozen = snapshot.get("body_plan")
            if frozen is not None:
                if (frozen.get("protocol") != snapshot["body_format"] or
                        frozen.get("source_hash") != native_markdown.source_hash(job.content) or
                        receipts.fingerprint(frozen) != snapshot.get("body_plan_hash")):
                    raise FeishuError("原转换计划已变化，禁止写入", 409, code="format_changed")
                try:
                    native_markdown.validate_frozen_inline_styles(job.content, frozen, snapshot.get("format_segments"))
                except native_markdown.FormatError as exc:
                    raise FeishuError(str(exc), 422, code="format_unsupported") from None
                return frozen
            from app.models.feishu_destination import FeishuWriteBatchDB
            prior = db.scalar(select(FeishuWriteBatchDB.job_id).where(
                FeishuWriteBatchDB.job_id == job.id).limit(1))
            if prior or int(job.written_blocks):
                raise FeishuError("已有正文写入但缺少冻结计划，请核验原文档", 409,
                                  uncertain=True, code="write_unknown")
        if not 1 <= len(job.content) <= 10485760:
            raise FeishuError("正文超出转换接口长度范围", 422, code="format_unsupported")
        if snapshot["body_format"] == native_markdown.SELECTIVE_PROTOCOL:
            if snapshot.get("format_selection", {}).get("blocked_image_table"):
                raise FeishuError("表格含图片，暂不支持原生写入；不能以管道文本标为完成", 422, code="format_unsupported")
            # Refresh first; then inspect actual current user grants, not config scopes.
            self.user_token(owner)
            with session_scope() as db:
                account = db.get(FeishuConnectionDB, owner)
                grants = self.granted_scopes(account)
            if "docx:document.block:convert" not in grants:
                raise FeishuError("此正文需要原生格式转换，请开通并重新授权 docx:document.block:convert；简单正文不需要此权限", 403, code="converter_scope_missing")
            if not grants & {"docx:document", "docx:document:write_only"}:
                raise FeishuError("当前授权缺少文档编辑权限", 403, code="user_scope_missing")
        # Pure official conversion; never sends a model request or creates a document.
        # A conversion timeout is safe to retry: no target document was edited.
        def convert(text):
            try:
                return self.request("POST", "docx/v1/documents/blocks/convert",
                                    token=self.user_token(owner),
                                    body={"content_type": "markdown", "content": text})
            except FeishuError as exc:
                raise FeishuError(exc.detail, exc.status_code, code=exc.code) from None
        try:
            plan = (native_markdown.selective_plan(job.content, convert, snapshot.get("format_segments"))
                    if snapshot["body_format"] == native_markdown.SELECTIVE_PROTOCOL else
                    native_markdown.prepare_plan(job.content, convert(job.content)))
        except native_markdown.FormatError as exc:
            raise FeishuError(str(exc), 422, code="format_unsupported") from None
        with session_scope() as db:
            original = receipts.owned_job(db, owner, job.id)
            metadata = db.get(FeishuDeliveryDestinationDB, job.id)
            current = json.loads(metadata.snapshot)
            if current.get("body_format") != snapshot["body_format"] or original.content != job.content:
                raise FeishuError("原转换来源已变化", 409, code="format_changed")
            # Compare-and-swap: a competing converter may have frozen the plan first.
            if "body_plan" not in current:
                current.update(body_plan=plan, body_plan_hash=receipts.fingerprint(plan))
                changed = db.execute(update(FeishuDeliveryDestinationDB).where(
                    FeishuDeliveryDestinationDB.delivery_id == job.id,
                    FeishuDeliveryDestinationDB.snapshot == metadata.snapshot
                ).values(snapshot=json.dumps(current, ensure_ascii=False)))
                if changed.rowcount != 1:
                    raise FeishuError("转换计划正在保存，请查询原任务后重试", 409, code="format_pending")
        return self.prepare_native_body(owner, job)

    def write_native_body(self, owner, job, plan):
        start = int(job.written_blocks)
        ends = {0} | {batch["offset"] + len(batch["body"]["children_id"]) for batch in plan["batches"]}
        if start not in ends:
            raise FeishuError("正文检查点不匹配冻结计划", 409, uncertain=True, code="write_unknown")
        path = f"docx/v1/documents/{job.document_id}/blocks/{job.document_id}/descendant"
        for batch in plan["batches"]:
            offset, body = batch["offset"], batch["body"]
            if offset < start:
                continue
            # Receipt binds target, API, UUIDv4 and body, not just a block count.
            bound = {"path": path, "client_token": batch["client_token"], "body": body}
            token = self.user_token(owner)
            try:
                with session_scope() as db:
                    dispatch = receipts.begin_batch(db, owner, job.id, offset, bound)
            except HTTPException:
                raise FeishuError("原正文批次结果未核验，禁止重新写入", 409,
                                  uncertain=True, code="write_unknown") from None
            if dispatch:
                try:
                    response = self.request("POST", path, token=token, body=body,
                                            params={"client_token": batch["client_token"]})
                    relations = response.get("block_id_relations", [])
                    mapped = {item.get("temporary_block_id") for item in relations
                              if isinstance(item, dict) and item.get("block_id")}
                    if not {block["block_id"] for block in body["descendants"]} <= mapped:
                        raise FeishuError("写入响应缺少块映射，需要核验", 502,
                                          uncertain=True, code="write_unknown")
                except Exception as exc:
                    state = "failed" if isinstance(exc, FeishuError) and not exc.uncertain else "unknown"
                    with session_scope() as db:
                        receipts.finish_batch(db, owner, job.id, offset, state)
                    if state == "unknown":
                        raise FeishuError("原正文批次结果未核验，禁止重发，请核对原文档", 502,
                                          uncertain=True, code="write_unknown") from None
                    raise
                with session_scope() as db:
                    receipts.finish_batch(db, owner, job.id, offset, "confirmed")
                # Conservative per-job pacing below the documented 3 edits/s.
                # Cross-job application limits still return definite rate_limited.
                time.sleep(0.35)
            self.checkpoint(owner, job.id, written_blocks=str(offset + len(body["children_id"])))

    def write_document(self, owner, job):
        plan = self.prepare_native_body(owner, job)
        if plan is not None:
            return self.write_native_body(owner, job, plan)
        blocks = []
        for line in job.content.splitlines():
            if not line.strip():
                continue
            level = len(line) - len(line.lstrip("#"))
            kind = f"heading{level}" if 1 <= level <= 6 and line[level:level + 1] == " " else "text"
            text = line[level + 1:] if kind != "text" else line
            block_type = level + 2 if kind != "text" else 2
            if kind == "text" and re.match(r"^\s*[-*+]\s+", text):
                kind, block_type = "bullet", 12
                text = re.sub(r"^\s*[-*+]\s+", "", text)
            elif kind == "text" and re.match(r"^\s*\d+\.\s+", text):
                kind, block_type = "ordered", 13
                text = re.sub(r"^\s*\d+\.\s+", "", text)
            # Bound native text-run sizes while preserving all source content.
            elements = []
            for piece in re.split(r"(\*\*[^*]+\*\*)", text):
                bold = piece.startswith("**") and piece.endswith("**") and len(piece) > 4
                value = piece[2:-2] if bold else piece
                for offset in range(0, len(value), 1000):
                    elements.append({"text_run": {"content": value[offset:offset + 1000],
                                                  **({"text_element_style": {"bold": True}} if bold else {})}})
            # Extremely long paragraphs become consecutive paragraphs, not lost text.
            for offset in range(0, len(elements), 20):
                blocks.append({"block_type": block_type, kind: {"elements": elements[offset:offset + 20]}})
        start = int(job.written_blocks)
        for offset in range(start, len(blocks), 50):
            body = {"children": blocks[offset:offset + 50], "index": offset}
            token = self.user_token(owner)
            try:
                with session_scope() as db:
                    dispatch = receipts.begin_batch(db, owner, job.id, offset, body)
            except HTTPException:
                raise FeishuError("原正文批次结果未核验，禁止重新写入；请打开原文档核对", 409, uncertain=True, code="write_unknown") from None
            if dispatch:
                try:
                    self.request("POST", f"docx/v1/documents/{job.document_id}/blocks/{job.document_id}/children",
                                 token=token, body=body,
                                 params={"client_token": str(uuid.uuid5(uuid.NAMESPACE_URL, job.id + str(offset)))})
                except Exception as exc:
                    state = "failed" if isinstance(exc, FeishuError) and not exc.uncertain else "unknown"
                    with session_scope() as db:
                        receipts.finish_batch(db, owner, job.id, offset, state)
                    if state == "unknown":
                        raise FeishuError("原正文批次结果未核验，禁止重新写入；请查询原回执并核对文档", 502, uncertain=True, code="write_unknown") from None
                    raise
                with session_scope() as db:
                    receipts.finish_batch(db, owner, job.id, offset, "confirmed")
            self.checkpoint(owner, job.id, written_blocks=str(offset + len(blocks[offset:offset + 50])))

    def grant_group(self, owner, target, job):
        self.request("POST", f"drive/v1/permissions/{job.document_id}/members", token=self.user_token(owner),
                     params={"type": "docx", "need_notification": "false"},
                     body={"member_type": "openchat", "member_id": target, "perm": "view"})

    def verify_group_permission(self, owner, target, job):
        members = self.request("GET", f"drive/v1/permissions/{job.document_id}/members",
                               token=self.user_token(owner), params={"type": "docx"}).get("items", [])
        return any(item.get("member_type") == "openchat" and item.get("member_id") == target and
                   item.get("perm") in ("view", "edit", "full_access") for item in members)

    def contact_reading_permission(self, owner, target, job):
        """Only verify existing direct membership; never add collaborators.

        Official permission/permission-member/list.md: GET drive/v1/
        permissions/:token/members, type=docx, member_type=openid. No fields
        parameter is requested (names/avatars require extra contact scopes).
        Absence cannot disprove inherited/group/organization access, and a
        successful bot message never proves that a human opened the document.
        """
        result = self.request("GET", f"drive/v1/permissions/{job.document_id}/members",
                              token=self.user_token(owner), params={"type": "docx"})
        members = result.get("items")
        if not isinstance(members, list) or any(not isinstance(item, dict) for item in members):
            raise FeishuError("无法核验联系人文档读取权限", 502, code="recipient_permission_unverified")
        member = next((item for item in members if item.get("member_type") == "openid" and
                       item.get("member_id") == target and item.get("perm") in ("view", "edit", "full_access")), None)
        return {"status": "verified" if member else "unverified",
                "verification_scope": "direct_document_collaborator", "permission_changed": False,
                "role": member["perm"] if member else None,
                "note": "已核验现有直接协作者角色；不代表实际打开或阅读" if member else
                        "未核验到直接协作者读取权限；继承、群或组织访问仍未核验，未发送通知"}

    def recipient_reading_permission(self, owner, target, job):
        if target.startswith("oc_"):
            verified = self.verify_group_permission(owner, target, job)
            return {"status": "verified" if verified else "unverified",
                    "verification_scope": "direct_document_collaborator", "permission_changed": False}
        return self.contact_reading_permission(owner, target, job)

    def ensure_recipient_reading(self, owner, target, job, recipients):
        """Journal before granting. A read failure after dispatch is never a retry grant."""
        state = recipients[target]
        was_unknown = recipient_access.permission_unknown(target, state)
        if was_unknown:
            raise FeishuError("阅读授权结果未确认，请先核验原文档权限", 409,
                              uncertain=True, code="permission_unknown")
        reading = self.recipient_reading_permission(owner, target, job)
        if reading["status"] == "verified":
            state["reading_permission"] = reading
            self.checkpoint(owner, job.id, recipients=json.dumps(recipients))
            return
        # Only the new explicit contact policy or an already-consented legacy
        # group path calls this function. No preferences or arbitrary IDs are used.
        state["reading_permission"] = {"status": "granting", "role": "view",
                                       "verification_scope": "direct_document_collaborator"}
        self.checkpoint(owner, job.id, recipients=json.dumps(recipients))
        try:
            if target.startswith("oc_"):
                self.grant_group(owner, target, job)
            else:
                self.request("POST", f"drive/v1/permissions/{job.document_id}/members",
                             token=self.user_token(owner),
                             params={"type": "docx", "need_notification": "false"},
                             body={"member_type": "openid", "member_id": target, "perm": "view"})
        except Exception as exc:
            definite = isinstance(exc, FeishuError) and not exc.uncertain
            state["reading_permission"]["status"] = "failed" if definite else "unknown"
            state["status"] = "failed" if definite else "permission_unknown"
            self.checkpoint(owner, job.id, recipients=json.dumps(recipients))
            if definite:
                raise
            raise FeishuError("阅读授权结果未确认，请核验原文档权限；不会重复授权", 502,
                              uncertain=True, code="permission_unknown") from None
        try:
            reading = self.recipient_reading_permission(owner, target, job)
            if reading["status"] != "verified":
                raise FeishuError("尚未核验到阅读权限", 502)
        except Exception:
            state["reading_permission"]["status"] = "unknown"
            state["status"] = "permission_unknown"
            self.checkpoint(owner, job.id, recipients=json.dumps(recipients))
            raise FeishuError("授权后的阅读权限尚未核验；不会发送或重复授权", 502,
                              uncertain=True, code="permission_unknown") from None
        state["reading_permission"] = reading
        self.checkpoint(owner, job.id, recipients=json.dumps(recipients))

    def verify_delivery_permissions(self, owner, job_id):
        """Explicit recovery: provider GETs only, local evidence updates, no worker."""
        with _lock(owner):
            with session_scope() as db:
                job = receipts.owned_job(db, owner, job_id)
                if float(job.lease_until) > time.time():
                    raise FeishuError("原交付仍在处理中，请稍后核验", 409, code="delivery_busy")
                metadata = db.get(FeishuDeliveryDestinationDB, job_id)
                snapshot = json.loads(metadata.snapshot) if metadata else {}
                recipients = json.loads(job.recipients)
                if not recipient_access.has_permission_unknown(recipients):
                    return self.serialize(job, db=db)
                if not job.document_id or job.document_id == "__creating__":
                    raise FeishuError("原文档尚未确认，不能核验阅读权限", 409, code="create_unknown")
                db.expunge(job)
            self.assert_delivery_connection(owner, snapshot)
            for target, state in recipients.items():
                if not recipient_access.permission_unknown(target, state):
                    continue
                # Only original contacts with explicit policy, or original group
                # recipients whose legacy contract already included granting.
                is_contact = state.get("kind") == "contact" and any(
                    item.get("open_id") == target for item in snapshot.get("contacts", []))
                if not target.startswith("oc_") and not (
                        is_contact and snapshot.get("recipient_access_policy") == recipient_access.POLICY):
                    raise FeishuError("原发布没有阅读授权确认，不能改变其恢复语义", 409,
                                      code="recipient_access_policy_missing")
                try:
                    reading = self.recipient_reading_permission(owner, target, job)
                except FeishuError:
                    reading = {"status": "unknown", "note": "暂时无法核验原文档阅读权限，未重新授权或发送"}
                if reading["status"] == "verified":
                    state.update(status="pending", error="", error_code="", reading_permission=reading)
                else:
                    state.update(status="permission_unknown", error_code="permission_unknown",
                                 error="原阅读授权仍未核验，不会重复授权或发送",
                                 reading_permission={**reading, "status": "unknown"})
            message_unknown = any(s.get("status") in ("sending", "unknown") for s in recipients.values())
            acl_unknown = recipient_access.has_permission_unknown(recipients)
            with session_scope() as db:
                current = receipts.owned_job(db, owner, job_id)
                # Unknown body writes/creation/messages are not resolved by ACL evidence.
                write_unknown = receipts.has_unknown_batch(db, job_id)
                metadata = db.get(FeishuDeliveryDestinationDB, job_id)
                write_unknown = write_unknown or bool(metadata and metadata.phase == "unknown" and
                    metadata.error_code in ("write_unknown", "result_unknown", "interrupted"))
                current.recipients = json.dumps(recipients)
                current.status, current.lease_until = "failed", "0"
                current.error = "阅读权限仍待核验" if acl_unknown else "已核验阅读权限；尚未继续通知"
                if metadata:
                    metadata.phase = "unknown" if message_unknown or write_unknown else "permission_unknown" if acl_unknown else "partial_success"
                    metadata.error_code = "write_unknown" if write_unknown else "message_unknown" if message_unknown else "permission_unknown" if acl_unknown else "recipient_failed"
            return self.delivery_by_id(owner, job_id)

    def send_message(self, owner, target, job):
        with session_scope() as db:
            metadata = db.get(FeishuDeliveryDestinationDB, job.id)
            snapshot = json.loads(metadata.snapshot) if metadata else {}
        content = document_card(job.title, snapshot.get("destination", {}), job.document_url)
        result = self.request("POST", "im/v1/messages", token=self.bot_token(),
            params={"receive_id_type": "chat_id" if target.startswith("oc_") else "open_id"},
            body={"receive_id": target, "msg_type": "interactive", "content": json.dumps(content),
                  "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, job.id + target))})
        if not result.get("message_id"):
            raise FeishuError("消息响应缺少标识，需要核验送达结果", 502, uncertain=True)
        return result["message_id"]

    def process(self, owner, job_id, selected_recipients=None):
        with _lock(owner):
            with session_scope() as db:
                job = db.get(FeishuDeliveryDB, job_id)
                if not job or job.owner != owner:
                    raise FeishuError("交付记录不存在", 404)
                if selected_recipients is not None:
                    self.validate_retry_recipients(job, selected_recipients)
                if job.status == "completed" or float(job.lease_until) > time.time():
                    return
                metadata = db.get(FeishuDeliveryDestinationDB, job_id)
                if receipts.has_unknown_batch(db, job_id) or (metadata and (
                        (job.status == "processing" and metadata.phase == "writing") or
                        (metadata.phase == "unknown" and metadata.error_code in ("write_unknown", "result_unknown", "interrupted")))):
                    job.status, job.error, job.lease_until = "failed", "原交付步骤结果未核验，禁止重新写入；请查询原回执并核对文档", "0"
                    if metadata:
                        metadata.phase, metadata.error_code = "unknown", "write_unknown"
                    return
                snapshot = json.loads(metadata.snapshot) if metadata else {}
                permission = json.loads(metadata.permission) if metadata else {"status": "legacy_unverified"}
                if recipient_access.has_permission_unknown(json.loads(job.recipients)):
                    job.status, job.error, job.lease_until = "failed", "阅读授权结果未确认，请先核验原文档权限", "0"
                    if metadata:
                        metadata.phase, metadata.error_code = "permission_unknown", "permission_unknown"
                    return
                result = db.execute(update(FeishuDeliveryDB).where(FeishuDeliveryDB.id == job_id,
                    FeishuDeliveryDB.lease_until == job.lease_until).values(lease_until=str(time.time() + 300), status="processing"))
                if result.rowcount != 1:
                    return
                db.expunge(job)
            try:
                self.assert_delivery_connection(owner, snapshot)
                self.prepare_native_body(owner, job)
                if job.document_id == "__creating__":
                    raise FeishuError("创建文档结果未确认。请在所选位置查找同名空白文档，关联链接后继续，避免重复创建", uncertain=True, code="create_unknown")
                if not job.document_id:
                    self.checkpoint(owner, job_id, document_id="__creating__", phase="pending_create", error_code="")
                    try:
                        if snapshot.get("enhanced"):
                            document_id, url = self.create_at_destination(owner, job.title, snapshot["destination"])
                        else:
                            document_id, url = self.create_document(owner, job.title)
                    except FeishuError as exc:
                        if not exc.uncertain:
                            self.checkpoint(owner, job_id, document_id="")
                        else:
                            raise FeishuError("创建文档结果未确认。请在所选位置查找同名空白文档，关联后继续；若未创建，可在该位置新建同名空白文档", uncertain=True, code="create_unknown") from None
                        raise
                    self.checkpoint(owner, job_id, document_id=document_id, document_url=url)
                    job.document_id, job.document_url = document_id, url
                if snapshot.get("enhanced"):
                    self.checkpoint(owner, job_id, phase="setting_permissions")
                    try:
                        # Before any content upload: enforce private policy or read inherited scope.
                        permission = self.ensure_permission(owner, job, snapshot)
                    except FeishuError as exc:
                        self.checkpoint(owner, job_id, permission={"status": "failed", "policy": snapshot["permission_policy"],
                                                                 "error": exc.detail, "error_code": exc.code})
                        raise
                    self.checkpoint(owner, job_id, permission=permission)
                self.checkpoint(owner, job_id, phase="writing")
                self.write_document(owner, job)
                recipients = json.loads(job.recipients)
                for target, state in recipients.items():
                    if state["status"] == "sent":
                        continue
                    if state["status"] in ("sending", "unknown"):
                        # Message UUID deduplication is time-bounded; never blindly replay unknown sends.
                        state.update(status="unknown", error="消息结果未确认，请先在飞书核对", error_code="message_unknown")
                        self.checkpoint(owner, job_id, recipients=json.dumps(recipients))
                        continue
                    if selected_recipients is not None and target not in selected_recipients:
                        continue
                    sending = False
                    try:
                        self.assert_delivery_connection(owner, snapshot)
                        if state.get("kind") == "contact" and snapshot.get("recipient_access_policy") == recipient_access.POLICY:
                            self.checkpoint(owner, job_id, phase="setting_permissions")
                            self.ensure_recipient_reading(owner, target, job, recipients)
                        elif state.get("kind") == "contact":
                            # Re-read on each definite retry; permission may have been revoked.
                            state["reading_permission"] = {"status": "not_checked"}
                            self.checkpoint(owner, job_id, phase="setting_permissions", recipients=json.dumps(recipients))
                            reading = self.contact_reading_permission(owner, target, job)
                            state["reading_permission"] = reading
                            self.checkpoint(owner, job_id, recipients=json.dumps(recipients))
                            if reading["status"] != "verified":
                                raise FeishuError(reading["note"], 403, code="recipient_permission_unverified")
                        if target.startswith("oc_"):
                            self.checkpoint(owner, job_id, phase="setting_permissions")
                            if target not in {group["chat_id"] for group in self.groups(owner)}:
                                raise FeishuError("机器人或当前用户已不在目标群，请检查群设置", 403, code="recipient_unavailable")
                            self.ensure_recipient_reading(owner, target, job, recipients)
                            state["permission_granted"] = True
                            self.checkpoint(owner, job_id, recipients=json.dumps(recipients))
                        state.update(status="sending", error="", error_code="")
                        self.checkpoint(owner, job_id, phase="notifying", recipients=json.dumps(recipients))
                        sending = True
                        message_id = self.send_message(owner, target, job)
                        state.update(status="sent", message_id=message_id, error="", error_code="")
                    except FeishuError as exc:
                        state.update(status="unknown" if sending and exc.uncertain else "permission_unknown" if exc.code == "permission_unknown" else "failed", error=exc.detail,
                                     error_code="message_unknown" if sending and exc.uncertain else exc.code)
                    self.checkpoint(owner, job_id, recipients=json.dumps(recipients))
                failed = any(state["status"] != "sent" for state in recipients.values())
                unknown = any(state["status"] == "unknown" for state in recipients.values())
                acl_unknown = recipient_access.has_permission_unknown(recipients)
                self.checkpoint(owner, job_id, status="failed" if failed else "completed",
                                phase="unknown" if unknown else "permission_unknown" if acl_unknown else "partial_success" if failed else "completed",
                                error_code="message_unknown" if unknown else "permission_unknown" if acl_unknown else "recipient_failed" if failed else "",
                                error="部分通知未送达，文档已保留，请重试失败对象" if failed else "", lease_until="0")
            except Exception as exc:
                code = exc.code if isinstance(exc, FeishuError) else "interrupted"
                phase = "awaiting_authorization" if isinstance(exc, FeishuError) and exc.status_code == 401 else "unknown" if isinstance(exc, FeishuError) and exc.uncertain else "failed"
                self.checkpoint(owner, job_id, status="failed", lease_until="0",
                                phase=phase, error_code=code,
                                error=exc.detail if isinstance(exc, FeishuError) else "交付暂时中断，请重试")
