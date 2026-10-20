"""Explicit device-owned VILab connections. Checks never infer or activate."""
import ipaddress
import secrets
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session_scope
from app.db_models import CloudAccountDB, VILabConnectionAuthDB, VILabConnectionDB, VILabConnectionStateDB, VILabPreferenceDB
from app.services.cloud_account_service import _cipher

_checks = {}
_guard = threading.RLock()
CHECK_SECONDS = 600


def _private_address(value):
    address = ipaddress.ip_address(value)
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
    return address.is_loopback or any(address in ipaddress.ip_network(net) for net in networks)


def normalize_origin(value):
    if (not isinstance(value, str) or not value or len(value) > 2048 or
            any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in value)):
        raise HTTPException(422, "请填写有效的 VILab 服务地址")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        if parsed.scheme == "http":
            if host == "localhost" or host.endswith(".localhost"):
                addresses = ["127.0.0.1"]
            else:
                try:
                    addresses = [str(ipaddress.ip_address(host))]
                except ValueError:
                    addresses = [item[4][0] for item in socket.getaddrinfo(host, port or 80, type=socket.SOCK_STREAM)]
            if not addresses or not all(_private_address(item) for item in addresses):
                raise ValueError()
        authority = "[" + host + "]" if ":" in host else host
        if port and port != (443 if parsed.scheme == "https" else 80):
            authority += ":" + str(port)
        return urlunsplit((parsed.scheme, authority, "", "", ""))
    except (ValueError, UnicodeError, OSError):
        raise HTTPException(422, "公网 VILab 请使用 HTTPS；HTTP 仅支持内网或本机地址") from None


class VILabConnectionService:
    def __init__(self, session_factory=None):
        self.sessions = session_factory or session_scope

    @staticmethod
    def device_only():
        if settings.workspace_cloud_runtime or settings.content_cloud_runtime:
            raise HTTPException(404, "连接设置仅在当前设备提供")

    def owned(self, db, owner, identifier, origin=None):
        record = db.get(VILabConnectionDB, identifier)
        if not record or record.user_id != owner or origin is not None and record.server_url != origin:
            raise HTTPException(409, "原模型连接不可用，未切换到其他服务")
        return record

    @staticmethod
    def auth_binding(db, record):
        grant = db.get(VILabConnectionAuthDB, record.id)
        if grant is None:
            return {"mode": "api_key"}  # Original connections never gain account grants.
        if grant.mode != "account" or not grant.issuer or not grant.subject:
            raise HTTPException(409, "原连接的账号授权无效，请重新检查连接")
        return {"mode": "account", "issuer": grant.issuer, "subject": grant.subject}

    def account_binding(self, owner):
        with self.sessions() as db:
            row = db.get(CloudAccountDB, owner)
            if not row or not settings.cloud_auth_url or row.issuer != settings.cloud_auth_url or not row.subject:
                raise HTTPException(401, "请先登录 VINote 账号，再使用账号检查连接")
            return {"mode": "account", "issuer": row.issuer, "subject": row.subject}

    def account_token(self, owner, binding):
        if self.account_binding(owner) != binding:
            raise HTTPException(409, "连接绑定的账号或认证服务已变化，请重新检查连接")
        from app.services.cloud_account_service import CloudAccountService
        token = CloudAccountService().access_token(owner)
        if self.account_binding(owner) != binding:
            raise HTTPException(409, "读取凭据期间账号已变化，未发送到模型服务")
        return token

    def authorization(self, owner, origin, identifier, auth_mode=None):
        with self.sessions() as db:
            record = self.owned(db, owner, identifier, origin)
            binding = self.auth_binding(db, record)
            if (auth_mode or "api_key") != binding["mode"]:
                raise HTTPException(409, "原任务的连接认证方式不匹配，未替换凭据")
            key = _cipher().decrypt(record.credential.encode()).decode() if record.credential else ""
        if binding["mode"] == "account":
            key = self.account_token(owner, binding)
        return {"Authorization": "Bearer " + key} if key else {}

    def current(self, owner, defaults):
        with self.sessions() as db:
            state = db.get(VILabConnectionStateDB, owner)
            identifier = getattr(state, "connection_id", "")
            result = {**defaults, "connection_protocol": 1,
                      "connection_revision": getattr(state, "revision", "")}
            if identifier:
                row = self.owned(db, owner, identifier)
                result.update(configured=True, server_url=row.server_url, connection_id=row.id,
                              connection_auth_mode=self.auth_binding(db, row)["mode"],
                              asr_model=row.asr_model, llm_model=row.llm_model)
            return result

    def validate_snapshot(self, owner, snapshot):
        origin = snapshot.get("server_url")
        identifier = snapshot.get("connection_id")
        if identifier:
            with self.sessions() as db:
                record = self.owned(db, owner, identifier, origin)
                if snapshot.get("connection_auth_mode", "api_key") != self.auth_binding(db, record)["mode"]:
                    raise HTTPException(409, "原任务的连接认证方式不匹配")
        elif not isinstance(origin, str) or origin.rstrip("/") != settings.vilab_server_url.rstrip("/"):
            raise HTTPException(409, "原任务服务来源未绑定，未使用当前连接或凭据替换")

    def credential(self, owner, origin, identifier):
        with self.sessions() as db:
            record = self.owned(db, owner, identifier, origin)
            return _cipher().decrypt(record.credential.encode()).decode() if record.credential else ""

    @staticmethod
    def public(record, auth_mode="api_key"):
        return {"connection_id": record.id, "server_url": record.server_url,
                "auth_mode": auth_mode,
                "has_credential": bool(record.credential), "asr_model": record.asr_model,
                "llm_model": record.llm_model}

    def list(self, owner):
        self.device_only()
        with self.sessions() as db:
            rows = db.scalars(select(VILabConnectionDB).where(VILabConnectionDB.user_id == owner)).all()
            return {"connections": [{"connection_id": "default", "server_url": settings.vilab_server_url,
                                      "builtin": True}, *[self.public(row, self.auth_binding(db, row)["mode"]) for row in rows]]}

    def check(self, owner, *, server_url=None, api_key=None, connection_id=None,
              auth_mode=None, account_consent=False, authorized_origin=None):
        self.device_only()
        if api_key is not None and (not isinstance(api_key, str) or len(api_key) > 4096 or
                                    any(ord(c) < 32 or ord(c) == 127 for c in api_key)):
            raise HTTPException(422, "连接密钥格式无效")
        from app.services.vilab_cloud_service import VILabCloudService
        service = VILabCloudService()
        config = service.status(owner)
        target = connection_id
        binding = {"mode": "api_key"}
        previous_binding = binding
        if connection_id == "default":
            origin, key = settings.vilab_server_url, None
            if server_url is not None or api_key is not None:
                raise HTTPException(422, "内置连接不能替换地址或凭据")
            with self.sessions() as db:
                row = db.get(VILabPreferenceDB, owner)
                choices = {"asr_model": row.asr_model if row else "", "llm_model": row.llm_model if row else ""}
            headers = service.authorization(owner, origin)
        elif connection_id:
            with self.sessions() as db:
                row = self.owned(db, owner, connection_id)
                if server_url is not None and normalize_origin(server_url) != row.server_url:
                    raise HTTPException(409, "地址已变化，请作为新连接检查，不沿用旧凭据")
                origin = normalize_origin(row.server_url)
                previous_binding = self.auth_binding(db, row)
                key = (_cipher().decrypt(row.credential.encode()).decode() if row.credential else "") if api_key is None else api_key
                choices = {"asr_model": row.asr_model, "llm_model": row.llm_model}
            if api_key is not None:
                target = None  # Credentials are immutable; keep old tasks bound.
            headers = {"Authorization": "Bearer " + key} if key else {}
        else:
            origin = normalize_origin(server_url)
            key = api_key or ""
            choices = {"asr_model": "", "llm_model": ""}
            headers = {"Authorization": "Bearer " + key} if key else {}
        if connection_id != "default":
            mode = auth_mode or previous_binding["mode"]
            if mode not in {"account", "api_key"}:
                raise HTTPException(422, "请选择账号或 API key 认证方式")
            if mode == "account":
                if (account_consent is not True or not authorized_origin or
                        normalize_origin(authorized_origin) != origin):
                    raise HTTPException(409, "请明确同意使用已登录账号检查这个确切的服务地址")
                if api_key is not None:
                    raise HTTPException(422, "账号模式不使用或继承 API key")
                binding = self.account_binding(owner)
                key = ""  # Never put the shared session token in checks or connection storage.
                headers = {"Authorization": "Bearer " + self.account_token(owner, binding)}
            else:
                if previous_binding["mode"] == "account":
                    key = api_key or ""
                headers = {"Authorization": "Bearer " + key} if key else {}
            if binding != previous_binding:
                target = None  # Mode/identity changes create a new immutable grant.
        if not origin:
            raise HTTPException(503, "内置模型服务尚未配置")
        try:
            response = httpx.request("GET", origin + "/v1/models", headers=headers,
                                     timeout=10, trust_env=False, follow_redirects=False)
            data = response.json() if response.is_success else None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "无法读取此连接的模型列表，未保存或切换") from None
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise HTTPException(502, "此服务未返回有效模型列表，未保存或切换")
        models = service.catalog(data)
        if len(models) > 5000 or any(not model["id"].strip() or len(model["id"]) > 200 for model in models):
            raise HTTPException(502, "此服务的模型列表无效，未保存或切换")
        identities = [(model["modelType"], model["id"]) for model in models]
        if len(set(identities)) != len(identities):
            raise HTTPException(502, "此服务的模型标识有歧义，未保存或切换")
        identifier = secrets.token_urlsafe(32)
        with _guard:
            now = time.monotonic()
            for expired in [k for k, v in _checks.items() if v["until"] <= now]:
                _checks.pop(expired)
            if len(_checks) >= 128:
                raise HTTPException(429, "待确认连接较多，请稍后重试")
            _checks[identifier] = dict(owner=owner, origin=origin, key=key, target=target, models=models,
                binding=binding,
                revision=config.get("connection_revision", ""), until=now + CHECK_SECONDS)
        return {"check_id": identifier, "server_url": origin, "models": models,
                "auth_mode": binding["mode"], "expires_in": CHECK_SECONDS, **choices}

    def save(self, owner, check_id, asr_model, llm_model):
        self.device_only()
        from app.services.vilab_cloud_service import VILabCloudService
        service = VILabCloudService()
        with _guard:
            checked = _checks.get(check_id)
            if not checked or checked["owner"] != owner or checked["until"] <= time.monotonic():
                raise HTTPException(409, "连接检查已过期，请重新检查；尚未切换")
            for name, kind in [(asr_model, "asr"), (llm_model, "llm")]:
                if name:
                    service._validate_selection(checked["models"], name, kind)
            if checked["binding"]["mode"] == "account" and self.account_binding(owner) != checked["binding"]:
                raise HTTPException(409, "账号已变化，请重新检查连接")
            try:
                with self.sessions() as db:
                    state = db.get(VILabConnectionStateDB, owner)
                    if (state.revision if state else "") != checked["revision"]:
                        raise HTTPException(409, "模型连接已变化，请重新检查当前草稿")
                    if state is None:
                        state = VILabConnectionStateDB(user_id=owner)
                        db.add(state)
                    target = checked["target"]
                    if target == "default":
                        if checked["origin"] != settings.vilab_server_url:
                            raise HTTPException(409, "内置服务地址已变化，请重新检查")
                        selected = db.get(VILabPreferenceDB, owner)
                        if not selected:
                            selected = VILabPreferenceDB(user_id=owner)
                            db.add(selected)
                        selected.asr_model, selected.llm_model = asr_model, llm_model
                        target = ""
                    elif target:
                        selected = self.owned(db, owner, target, checked["origin"])
                        selected.asr_model, selected.llm_model = asr_model, llm_model
                    else:
                        target = str(uuid.uuid4())
                        db.add(VILabConnectionDB(id=target, user_id=owner, server_url=checked["origin"],
                            credential=_cipher().encrypt(checked["key"].encode()).decode() if checked["key"] else "",
                            asr_model=asr_model, llm_model=llm_model))
                        if checked["binding"]["mode"] == "account":
                            db.flush()
                            db.add(VILabConnectionAuthDB(connection_id=target, mode="account",
                                issuer=checked["binding"]["issuer"], subject=checked["binding"]["subject"]))
                    if checked["revision"]:
                        changed = db.execute(update(VILabConnectionStateDB).where(
                            VILabConnectionStateDB.user_id == owner,
                            VILabConnectionStateDB.revision == checked["revision"]
                        ).values(connection_id=target, revision=str(uuid.uuid4())))
                        if changed.rowcount != 1:
                            raise HTTPException(409, "连接已变化，请重新检查")
                    else:
                        state.connection_id, state.revision = target, str(uuid.uuid4())
                    preferences = db.get(VILabPreferenceDB, owner)
                    if not preferences:
                        preferences = VILabPreferenceDB(user_id=owner)
                        db.add(preferences)
                    preferences.mode = "cloud"
            except IntegrityError:
                raise HTTPException(409, "连接已变化，请重新检查") from None
            _checks.pop(check_id, None)
        return service.status(owner)
