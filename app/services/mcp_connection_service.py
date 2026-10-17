"""Account-scoped remote MCP with pinned HTTPS and durable, non-replayed calls.

No network work runs at import/startup. Provider annotations are never authority.
Transport uses only the standard library; environment HTTP proxies are ignored.
"""
import concurrent.futures
import hashlib
import hmac
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.models.mcp_connections import MCPConnectionDB, MCPRunDB
from app.models.first_party_translation import AUTH_TYPE, ENDPOINT, BRIDGE_SECONDS, TOOL_NAME
from app.services.cloud_account_service import _cipher

MAX_RESPONSE = 1024 * 1024
MAX_ARGUMENTS = 65536
TIMEOUT = 40
MAX_TOOLS = 200
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
_dns_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-dns")
_dns_slots = threading.BoundedSemaphore(4)
_network_slots = threading.BoundedSemaphore(8)
_owner_slots = [threading.BoundedSemaphore(1) for _ in range(256)]
_secret_key = re.compile(r"token|secret|password|authorization|api.?key|credential|cookie", re.I)


def fail(status, code, message):
    raise HTTPException(status, {"code": code, "message": message}, headers={"Cache-Control": "no-store"})


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        fail(422, "invalid_json", "参数必须是有限深度的有效 JSON")


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def redact(value, credential="", depth=0, mask_keys=True):
    if depth > 24:
        return "[depth limit]"
    if isinstance(value, dict):
        return {redact(str(k), credential, depth + 1, mask_keys):
                "[redacted]" if mask_keys and _secret_key.search(str(k))
                else redact(v, credential, depth + 1, mask_keys)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, credential, depth + 1, mask_keys) for item in value]
    if isinstance(value, str):
        if credential:
            value = value.replace(credential, "[redacted]")
        value = re.sub(r"(?i)\bBearer\s+[^\s\"<>]+", "Bearer [redacted]", value)
        return value
    return value


def public_address(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # Translation/tunnelling forms can conceal an internal IPv4 destination.
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
        if ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
    return True


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        fail(422, "invalid_url", "请输入 ASCII HTTPS 地址；国际域名请使用 punycode")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port or 443
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or "?" in url or "#" in url
                or "\\" in url or "%" in host or port < 1):
            raise ValueError
        host = host.lower().rstrip(".")
        if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
                raise ValueError
        else:
            if not public_address(host):
                raise ValueError
    except ValueError:
        fail(422, "invalid_url", "仅支持无查询凭证、无重定向的公网 HTTPS MCP 地址")
    authority = f"[{host}]" if ":" in host else host
    if port != 443:
        authority += f":{port}"
    return urlunsplit(("https", authority, parts.path or "/", "", ""))


class MCPTransportError(Exception):
    """Only fixed, credential-free messages may reach HTTP responses or run records."""

    def __init__(self, code, message, status=502):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise MCPTransportError("timeout", "MCP 请求超时", 504)
    return seconds


def resolve_public(host, port, deadline):
    if not _dns_slots.acquire(blocking=False):
        raise MCPTransportError("dns_busy", "地址解析繁忙，请稍后重试", 429)
    try:
        future = _dns_pool.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    except Exception:
        _dns_slots.release()
        raise
    future.add_done_callback(lambda _: _dns_slots.release())
    try:
        addresses = future.result(timeout=min(3, remaining(deadline)))
    except concurrent.futures.TimeoutError:
        raise MCPTransportError("dns_timeout", "MCP 地址解析超时", 504) from None
    except OSError:
        raise MCPTransportError("dns_failed", "无法解析 MCP 地址") from None
    if not addresses or any(not public_address(item[4][0]) for item in addresses):
        raise MCPTransportError("unsafe_address", "MCP 地址解析包含非公网地址", 422)
    # Do not let the HTTP library resolve the hostname again (DNS rebinding).
    return addresses[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, address, deadline):
        super().__init__(host, port, timeout=min(8, remaining(deadline)), context=ssl.create_default_context())
        self.address, self.deadline = address, deadline

    def connect(self):
        family, socktype, proto, _, sockaddr = self.address
        raw = socket.socket(family, socktype, proto)
        try:
            raw.settimeout(min(8, remaining(self.deadline)))
            raw.connect(sockaddr)
            if ipaddress.ip_address(raw.getpeername()[0]) != ipaddress.ip_address(sockaddr[0]):
                raise MCPTransportError("unsafe_peer", "MCP 连接地址校验失败", 422)
            raw.settimeout(min(8, remaining(self.deadline)))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def decode_message(raw, rpc_id):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise MCPTransportError("invalid_response", "MCP 返回无效 JSON") from None
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        raise MCPTransportError("invalid_response", "MCP 返回无效 JSON-RPC")
    if value.get("id") != rpc_id:
        # Notifications and server requests are not the result of this call.
        return None
    if "error" in value:
        raise MCPTransportError("rpc_error", "MCP 服务返回协议错误")
    if not isinstance(value.get("result"), dict):
        raise MCPTransportError("invalid_response", "MCP 返回缺少结果")
    return value["result"]


class StreamableHTTPClient:
    """Fresh initialize per operation; no retries, SSE resume, or token redirects."""

    def __init__(self, url, token="", deadline=None):
        self.url = validate_url(url)
        self.token = token
        self.deadline = deadline or time.monotonic() + TIMEOUT
        self.session = None
        self.protocol = None
        self.dispatched = False
        self.run_id = None

    def rpc(self, method, params=None, notification=False):
        rpc_id = None if notification else str(uuid.uuid4())
        payload = {"jsonrpc": "2.0", "method": method}
        if rpc_id:
            payload["id"] = rpc_id
        if params is not None:
            payload["params"] = params
        body = canonical(payload).encode()
        parts = urlsplit(self.url)
        address = resolve_public(parts.hostname, parts.port or 443, self.deadline)
        connection = PinnedHTTPSConnection(parts.hostname, parts.port or 443, address, self.deadline)
        response = None
        watchdog = None
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Accept-Encoding": "identity", "Connection": "close"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.run_id and self.url == ENDPOINT and method == "tools/call":
            headers["X-VINote-MCP-Run-Id"] = self.run_id
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        try:
            # Connect/TLS before marking possible dispatch; DNS never repeats here.
            connection.connect()
            stream_socket = connection.sock
            stream_socket.settimeout(remaining(self.deadline))
            # Socket inactivity timeouts alone do not bound trickling headers/SSE.
            def interrupt():
                try:
                    stream_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            watchdog = threading.Timer(remaining(self.deadline), interrupt)
            watchdog.daemon = True
            watchdog.start()
            if method == "tools/call":
                self.dispatched = True
            connection.request("POST", parts.path or "/", body=body, headers=headers)
            connection.sock.settimeout(remaining(self.deadline))
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise MCPTransportError("redirect_forbidden", "MCP 重定向被拒绝", 422)
            if response.status in (401, 403):
                raise MCPTransportError("authentication_failed", "MCP 凭证无效或权限不足", 502)
            if not 200 <= response.status < 300:
                raise MCPTransportError("http_error", "MCP 服务请求失败")
            session = response.getheader("Mcp-Session-Id")
            if session is not None:
                if not session or len(session) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in session):
                    raise MCPTransportError("invalid_session", "MCP 会话标识无效")
                if method == "initialize":
                    self.session = session
                elif session != self.session:
                    raise MCPTransportError("invalid_session", "MCP 会话标识意外变化")
            if notification:
                if response.status not in (202, 204):
                    raise MCPTransportError("invalid_notification", "MCP 未接受初始化通知")
                return {}
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise MCPTransportError("encoding_unsupported", "MCP 压缩响应不受支持")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_RESPONSE):
                raise MCPTransportError("response_too_large", "MCP 响应超过限制")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in ("application/json", "text/event-stream"):
                raise MCPTransportError("unsupported_transport", "服务未提供 Streamable HTTP MCP 响应")
            data, pending, event_lines, total = bytearray(), b"", [], 0
            while True:
                if response.isclosed():
                    break
                stream_socket.settimeout(remaining(self.deadline))
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - total))
                total += len(chunk)
                if total > MAX_RESPONSE:
                    raise MCPTransportError("response_too_large", "MCP 响应超过限制")
                if not chunk:
                    break
                if content_type == "application/json":
                    data.extend(chunk)
                    continue
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    line = line.rstrip(b"\r")
                    if not line:
                        if event_lines:
                            result = decode_message(b"\n".join(event_lines), rpc_id)
                            if result is not None:
                                return result
                        event_lines = []
                    elif line.startswith(b"data:"):
                        event_lines.append(line[5:].removeprefix(b" "))
            if content_type == "application/json":
                result = decode_message(bytes(data), rpc_id)
                if result is not None:
                    return result
            raise MCPTransportError("incomplete_response", "MCP 未返回完整调用结果")
        except (TimeoutError, socket.timeout):
            raise MCPTransportError("timeout", "MCP 请求超时", 504) from None
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            raise MCPTransportError("transport_error", "MCP 连接或响应无效") from None
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if response is not None:
                response.close()
            connection.close()

    def initialize(self):
        result = self.rpc("initialize", {"protocolVersion": PROTOCOLS[0], "capabilities": {},
                                         "clientInfo": {"name": "VINote", "version": "1.0"}})
        if result.get("protocolVersion") not in PROTOCOLS:
            raise MCPTransportError("unsupported_protocol", "MCP 协议版本不受支持")
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
            raise MCPTransportError("tools_unavailable", "MCP 服务未声明工具能力")
        self.protocol = result["protocolVersion"]
        self.rpc("notifications/initialized", notification=True)

    def discover(self):
        self.initialize()
        tools, cursor, seen = [], None, set()
        for _ in range(10):
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            page = result.get("tools")
            if not isinstance(page, list):
                raise MCPTransportError("invalid_tools", "MCP 工具列表无效")
            tools.extend(page)
            if len(tools) > MAX_TOOLS or len(canonical(tools).encode()) > MAX_RESPONSE:
                raise MCPTransportError("too_many_tools", "MCP 工具列表超过限制")
            cursor = result.get("nextCursor")
            if cursor is None:
                return tools
            if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor in seen:
                raise MCPTransportError("invalid_cursor", "MCP 工具分页无效")
            seen.add(cursor)
        raise MCPTransportError("too_many_pages", "MCP 工具分页超过限制")

    def call(self, name, arguments):
        return self.rpc("tools/call", {"name": name, "arguments": arguments})


@contextmanager
def network_slot(owner):
    slot = _owner_slots[int(hashlib.sha256(owner.encode()).hexdigest(), 16) % len(_owner_slots)]
    if not slot.acquire(blocking=False):
        fail(429, "owner_busy", "当前账号已有 MCP 请求，请稍后重试")
    global_acquired = False
    try:
        global_acquired = _network_slots.acquire(blocking=False)
        if not global_acquired:
            fail(429, "service_busy", "MCP 服务繁忙，请稍后重试")
        yield
    finally:
        if global_acquired:
            _network_slots.release()
        slot.release()


def normalize_tools(raw, previous=(), credential=""):
    old = {tool["name"]: tool for tool in previous}
    result, names = [], set()
    for tool in raw:
        if not isinstance(tool, dict):
            raise MCPTransportError("invalid_tools", "MCP 工具定义无效")
        name, schema = tool.get("name"), tool.get("inputSchema")
        if (not isinstance(name, str) or not name or len(name) > 200 or name in names
                or not isinstance(schema, dict) or schema.get("type") != "object"
                or not isinstance(tool.get("description", ""), str)
                or not isinstance(tool.get("annotations", {}), dict)):
            raise MCPTransportError("invalid_tools", "MCP 工具定义无效")
        names.add(name)
        signature = digest(tool)
        prior = old.get(name, {})
        result.append({"name": name, "description": redact(tool.get("description", ""), credential),
                       "inputSchema": redact(schema, credential, mask_keys=False),
                       "annotations": redact(tool.get("annotations", {}), credential, mask_keys=False),
                       "definitionHash": signature, "requiresConfirmation": True,
                       "enabled": bool(prior.get("enabled") and prior.get("definitionHash") == signature)})
    return result


def connection_view(row):
    return {"id": row.id, "name": row.name, "url": row.url, "authType": row.auth_type,
            "hasCredential": bool(row.credential), "enabled": row.enabled, "status": row.status,
            "lastError": row.last_error, "discoveredAt": row.discovered_at,
            "createdAt": row.created_at, "updatedAt": row.updated_at,
            "managed": row.auth_type == AUTH_TYPE and row.url == ENDPOINT,
            "providerId": "vinote-cloud-translation" if row.auth_type == AUTH_TYPE and row.url == ENDPOINT else None}


def run_view(row):
    pending = row.status == "awaiting_confirmation"
    return {"id": row.id, "connectionId": row.connection_id, "requestId": row.request_id,
            "toolName": row.tool_name, "status": row.status, "arguments": json.loads(row.arguments_json),
            "result": json.loads(row.result_json) if row.result_json else None,
            "error": json.loads(row.error_json) if row.error_json else None,
            "confirmationToken": row.confirmation_token if pending else None,
            "confirmationExpiresAt": datetime.fromtimestamp(row.confirmation_expires, timezone.utc).isoformat()
            if pending else None, "createdAt": row.created_at, "updatedAt": row.updated_at}


class MCPConnectionService:
    @staticmethod
    def capabilities():
        return {"transport": "streamable-http", "authTypes": ["none", "token"], "oauth": False,
                "remoteCancellation": False, "confirmationRequired": "all",
                "contentScope": "explicit_arguments_only", "maxResponseBytes": MAX_RESPONSE,
                "maxArgumentBytes": MAX_ARGUMENTS, "timeoutSeconds": TIMEOUT,
                "maxConcurrentPerProcess": 8, "maxConcurrentPerOwner": 1}

    @staticmethod
    def _owned(db, owner, connection_id):
        row = db.get(MCPConnectionDB, connection_id)
        if not row or row.owner != owner or row.deleted:
            fail(404, "not_found", "MCP 连接不存在")
        return row

    @staticmethod
    def _enabled(row):
        if not row.enabled:
            fail(409, "connection_disabled", "MCP 连接已禁用")

    @staticmethod
    def _token(row):
        if row.auth_type in ("none", AUTH_TYPE):
            return ""
        try:
            return _cipher().decrypt(row.credential.encode()).decode()
        except HTTPException:
            raise
        except Exception:
            fail(503, "credential_unavailable", "MCP 凭证无法解密，请重新保存凭证")

    @staticmethod
    def _credential(auth_type, token, existing=""):
        if auth_type not in ("none", "token"):
            fail(422, "invalid_auth_type", "会话连接只能从第一方入口创建")
        if auth_type == "none":
            if token:
                fail(422, "unexpected_token", "无认证模式不能保存令牌")
            return ""
        if token is None and existing:
            return existing
        if (not isinstance(token, str) or not token or len(token) > 8192
                or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            fail(422, "invalid_token", "Token 认证需要有效的 Bearer 令牌")
        return _cipher().encrypt(token.encode()).decode()

    @staticmethod
    def _update(db, row, **values):
        values.update(revision=row.revision + 1, updated_at=now())
        changed = db.execute(update(MCPConnectionDB).where(
            MCPConnectionDB.id == row.id, MCPConnectionDB.owner == row.owner,
            MCPConnectionDB.revision == row.revision, MCPConnectionDB.deleted.is_(False)
        ).values(**values), execution_options={"synchronize_session": False})
        if changed.rowcount != 1:
            fail(409, "connection_changed", "连接已在其他请求中更新，请刷新")
        db.expire(row)
        db.refresh(row)
        return row

    def list_connections(self, owner):
        with session_scope() as db:
            rows = db.scalars(select(MCPConnectionDB).where(
                MCPConnectionDB.owner == owner, MCPConnectionDB.deleted.is_(False)
            ).order_by(MCPConnectionDB.created_at.desc())).all()
            return {"connections": [connection_view(row) for row in rows]}

    def create(self, owner, body):
        name = body["name"].strip()
        if not name:
            fail(422, "invalid_name", "连接名称不能为空")
        stamp = now()
        row = MCPConnectionDB(id=str(uuid.uuid4()), owner=owner, name=name, url=validate_url(body["url"]),
                              auth_type=body.get("authType", "none"),
                              credential=self._credential(body.get("authType", "none"), body.get("token")),
                              enabled=body.get("enabled", True), deleted=False, status="unverified",
                              tools_json="[]", revision=1, created_at=stamp, updated_at=stamp)
        with session_scope() as db:
            db.add(row)
            db.flush()
            return connection_view(row)

    def patch(self, owner, connection_id, body):
        with session_scope() as db:
            row = self._owned(db, owner, connection_id)
            if row.auth_type == AUTH_TYPE and any(k != "enabled" for k in body):
                fail(409, "managed_connection", "第一方连接仅允许启用或禁用；不能替换地址或凭证")
            values = {}
            if "name" in body:
                if not body["name"].strip():
                    fail(422, "invalid_name", "连接名称不能为空")
                values["name"] = body["name"].strip()
            if "url" in body:
                values["url"] = validate_url(body["url"])
            if "enabled" in body:
                values["enabled"] = body["enabled"]
            if "authType" in body or "token" in body:
                auth_type = body.get("authType", row.auth_type)
                values["auth_type"] = auth_type
                values["credential"] = self._credential(auth_type, body.get("token"), row.credential)
            if any(key in body for key in ("url", "authType", "token")):
                values.update(tools_json="[]", status="unverified", discovered_at=None, last_error=None)
            return connection_view(self._update(db, row, **values))

    def delete(self, owner, connection_id):
        with session_scope() as db:
            row = self._owned(db, owner, connection_id)
            self._update(db, row, deleted=True, enabled=False, credential="", tools_json="[]")
            db.execute(update(MCPRunDB).where(
                MCPRunDB.owner == owner, MCPRunDB.connection_id == connection_id,
                MCPRunDB.status == "awaiting_confirmation"
            ).values(status="cancelled", confirmation_token="", updated_at=now()))
        return {"deleted": True}

    def tools(self, owner, connection_id):
        with session_scope() as db:
            return {"tools": json.loads(self._owned(db, owner, connection_id).tools_json)}

    def patch_tool(self, owner, connection_id, name, enabled):
        with session_scope() as db:
            row = self._owned(db, owner, connection_id)
            tools = json.loads(row.tools_json)
            tool = next((tool for tool in tools if tool["name"] == name), None)
            if tool is None:
                fail(404, "tool_not_found", "请先发现 MCP 工具")
            tool["enabled"] = enabled
            self._update(db, row, tools_json=canonical(tools))
            return tool

    def discover(self, owner, connection_id, session_bearer=None):
        with network_slot(owner):
            with session_scope() as db:
                row = self._owned(db, owner, connection_id)
                self._enabled(row)
                token = self._token(row)
                if row.auth_type == AUTH_TYPE:
                    from app.services.first_party_translation_service import session_token
                    token = session_token(row, session_bearer)
                url, revision, previous = row.url, row.revision, json.loads(row.tools_json)
            try:
                client = StreamableHTTPClient(url, token)
                tools = normalize_tools(client.discover(), previous, token)
            except MCPTransportError as exc:
                with session_scope() as db:
                    db.execute(update(MCPConnectionDB).where(
                        MCPConnectionDB.id == connection_id, MCPConnectionDB.owner == owner,
                        MCPConnectionDB.revision == revision, MCPConnectionDB.deleted.is_(False)
                    ).values(status="error", last_error=exc.message, updated_at=now()))
                fail(exc.status, exc.code, exc.message)
            with session_scope() as db:
                row = self._owned(db, owner, connection_id)
                if row.revision != revision:
                    fail(409, "connection_changed", "发现期间连接已更新，请重新发现工具")
                self._update(db, row, tools_json=canonical(tools), status="connected",
                             last_error=None, discovered_at=now())
                return {"connection": connection_view(row), "tools": tools}

    @staticmethod
    def _expire(db, owner):
        db.execute(update(MCPRunDB).where(
            MCPRunDB.owner == owner, MCPRunDB.status == "running", MCPRunDB.lease_until < time.time()
        ).values(status="unknown", active_owner=None, updated_at=now(), error_json=canonical({
            "code": "execution_interrupted", "message": "调用进程中断，远程结果未知；请检查外部结果，不要自动重试"})))
        db.execute(update(MCPRunDB).where(
            MCPRunDB.owner == owner, MCPRunDB.status == "awaiting_confirmation",
            MCPRunDB.confirmation_expires < time.time()
        ).values(status="failed", confirmation_token="", updated_at=now(), error_json=canonical({
            "code": "confirmation_expired", "message": "确认已过期，请重新审阅后发起新请求"})))

    def runs(self, owner, connection_id=None, limit=50, offset=0):
        with session_scope() as db:
            self._expire(db, owner)
            query = select(MCPRunDB).where(MCPRunDB.owner == owner)
            if connection_id:
                query = query.where(MCPRunDB.connection_id == connection_id)
            rows = db.scalars(query.order_by(MCPRunDB.created_at.desc(), MCPRunDB.id.desc())
                              .limit(min(100, max(1, limit))).offset(max(0, offset))).all()
            return {"runs": [run_view(row) for row in rows]}

    @staticmethod
    def _read_run(row):
        """Report stale leases conservatively without dispatch or database writes."""
        view = run_view(row)
        if row.status == "running" and row.lease_until < time.time():
            view.update(status="unknown", error={
                "code": "execution_interrupted", "message": "调用进程中断，远程结果未知；请核验，不要重放"})
        elif row.status == "awaiting_confirmation" and row.confirmation_expires < time.time():
            view.update(status="failed", confirmationToken=None, confirmationExpiresAt=None,
                        error={"code": "confirmation_expired", "message": "确认已过期，请重新审阅"})
        return view

    def get_run(self, owner, run_id):
        with session_scope() as db:
            row = db.get(MCPRunDB, run_id)
            if row is None or row.owner != owner:
                fail(404, "not_found", "MCP 运行记录不存在")
            return self._read_run(row)

    def get_run_by_request(self, owner, request_id):
        with session_scope() as db:
            row = db.scalar(select(MCPRunDB).where(
                MCPRunDB.owner == owner, MCPRunDB.request_id == request_id))
            if row is None:
                fail(404, "not_found", "MCP 运行记录不存在")
            return self._read_run(row)

    def cancel(self, owner, run_id):
        with session_scope() as db:
            self._expire(db, owner)
            row = db.get(MCPRunDB, run_id)
            if row is None or row.owner != owner:
                fail(404, "not_found", "MCP 运行记录不存在")
            if row.status == "cancelled":
                return run_view(row)
            if row.status != "awaiting_confirmation":
                fail(409, "cannot_cancel_remote", "当前状态无法确认远程取消或回滚，请检查运行结果")
            changed = db.execute(update(MCPRunDB).where(
                MCPRunDB.id == run_id, MCPRunDB.owner == owner, MCPRunDB.status == "awaiting_confirmation"
            ).values(status="cancelled", confirmation_token="", updated_at=now()))
            if changed.rowcount != 1:
                fail(409, "cannot_cancel_remote", "调用已开始，无法确认远程取消或回滚")
            db.refresh(row)
            return run_view(row)

    @staticmethod
    def _tool(row, name):
        tool = next((t for t in json.loads(row.tools_json) if t["name"] == name), None)
        if tool is None or not tool["enabled"]:
            fail(409, "tool_disabled", "工具尚未启用，或定义已变化，请重新发现并确认授权")
        return tool

    def _prepare(self, owner, connection_id, body, fingerprint, session_bearer=None):
        with session_scope() as db:
            self._expire(db, owner)
        try:
            with session_scope() as db:
                run = db.scalar(select(MCPRunDB).where(
                    MCPRunDB.owner == owner, MCPRunDB.request_id == body["requestId"]))
                if run is not None:
                    if run.fingerprint != fingerprint:
                        fail(409, "request_id_conflict", "requestId 已用于不同的连接、工具或参数")
                    return run_view(run)
                row = self._owned(db, owner, connection_id)
                self._enabled(row)
                if row.auth_type == AUTH_TYPE:
                    from app.services.first_party_translation_service import session_token
                    from app.models.first_party_translation import TranslationArguments
                    from pydantic import ValidationError
                    session_token(row, session_bearer)
                    if body["toolName"] != TOOL_NAME:
                        fail(422, "invalid_tool", "第一方连接只提供翻译工具")
                    try:
                        TranslationArguments.model_validate(body.get("arguments", {}))
                    except ValidationError:
                        fail(422, "invalid_translation_arguments", "仅接受正文与 zh/en 目标语言")
                tool = self._tool(row, body["toolName"])
                if body.get("confirmed"):
                    fail(409, "confirmation_required", "请先取得并展示待确认调用，再提交确认")
                stamp = now()
                run = MCPRunDB(id=str(uuid.uuid4()), owner=owner, connection_id=connection_id,
                               request_id=body["requestId"], tool_name=body["toolName"], fingerprint=fingerprint,
                               connection_revision=row.revision, definition_hash=tool["definitionHash"],
                               arguments_json=canonical(redact(body.get("arguments", {}), self._token(row))),
                               status="awaiting_confirmation", confirmation_token=secrets.token_urlsafe(32),
                               confirmation_expires=time.time() + 600, lease_until=0,
                               created_at=stamp, updated_at=stamp)
                db.add(run)
                db.flush()
                return run_view(run)
        except IntegrityError:
            # Unique owner/requestId handles simultaneous requests across processes.
            with session_scope() as db:
                run = db.scalar(select(MCPRunDB).where(
                    MCPRunDB.owner == owner, MCPRunDB.request_id == body["requestId"]))
                if run is None:
                    raise
                if run.fingerprint != fingerprint:
                    fail(409, "request_id_conflict", "requestId 已用于不同的连接、工具或参数")
                return run_view(run)

    def invoke(self, owner, connection_id, body, session_bearer=None):
        arguments = body.get("arguments", {})
        if len(canonical(arguments).encode()) > MAX_ARGUMENTS:
            fail(413, "arguments_too_large", "MCP 参数超过 64 KiB 限制")
        fingerprint = digest({"connectionId": connection_id, "toolName": body["toolName"], "arguments": arguments})
        prepared = self._prepare(owner, connection_id, body, fingerprint, session_bearer)
        if prepared["status"] != "awaiting_confirmation" or not body.get("confirmed"):
            return prepared
        with network_slot(owner):
            try:
                with session_scope() as db:
                    run = db.get(MCPRunDB, prepared["id"])
                    if run.owner != owner or run.fingerprint != fingerprint:
                        fail(404, "not_found", "MCP 运行记录不存在")
                    if run.status != "awaiting_confirmation":
                        return run_view(run)
                    if run.confirmation_expires <= time.time():
                        fail(409, "confirmation_expired", "确认已过期")
                    if not hmac.compare_digest(body.get("confirmationToken") or "", run.confirmation_token):
                        fail(409, "confirmation_required", "请明确确认本次目标与完整参数")
                    row = self._owned(db, owner, connection_id)
                    self._enabled(row)
                    tool = self._tool(row, body["toolName"])
                    if row.revision != run.connection_revision or tool["definitionHash"] != run.definition_hash:
                        fail(409, "authorization_changed", "连接或工具授权已变化，请重新审阅并发起新请求")
                    url, token, revision, definition_hash = row.url, self._token(row), row.revision, run.definition_hash
                    is_managed = row.auth_type == AUTH_TYPE
                    if is_managed:
                        from app.services.first_party_translation_service import session_token
                        token = session_token(row, session_bearer)
                    changed = db.execute(update(MCPRunDB).where(
                        MCPRunDB.id == run.id, MCPRunDB.owner == owner,
                        MCPRunDB.status == "awaiting_confirmation"
                    ).values(status="running", confirmation_token="", active_owner=owner,
                             lease_until=time.time() + (BRIDGE_SECONDS if is_managed else TIMEOUT) + 30, updated_at=now()))
                    if changed.rowcount != 1:
                        db.refresh(run)
                        return run_view(run)
            except IntegrityError:
                fail(429, "owner_busy", "当前账号已有 MCP 工具调用，请稍后重试")
            client = StreamableHTTPClient(url, token)
            if is_managed:
                client.deadline = time.monotonic() + BRIDGE_SECONDS
                client.run_id = prepared["id"]
            result, error, status = None, None, "failed"
            try:
                # Re-discovery on the actual execution session prevents using stale grants.
                current = normalize_tools(client.discover())
                actual = next((t for t in current if t["name"] == body["toolName"]), None)
                if actual is None or actual["definitionHash"] != definition_hash:
                    with session_scope() as db:
                        row = self._owned(db, owner, connection_id)
                        if row.revision == revision:
                            self._update(db, row, tools_json="[]", status="unverified", discovered_at=None)
                    raise MCPTransportError("tool_changed", "远程工具定义已变化，请重新发现并授权", 409)
                with session_scope() as db:
                    row = self._owned(db, owner, connection_id)
                    self._enabled(row)
                    if row.revision != revision:
                        fail(409, "authorization_changed", "调用前连接或工具授权已变化")
                raw = client.call(body["toolName"], arguments)
                if is_managed and raw.get("structuredContent", {}).get("status") in ("unknown", "running"):
                    raise MCPTransportError("provider_result_unknown", "翻译结果未知，请查询原回执，禁止重放")
                if (not isinstance(raw.get("content"), list)
                        or ("isError" in raw and not isinstance(raw["isError"], bool))):
                    raise MCPTransportError("invalid_result", "MCP 工具结果无效")
                result = redact(raw, token)
                if is_managed and isinstance(result.get("structuredContent"), dict):
                    usage = raw.get("structuredContent", {}).get("usage", {})
                    result["structuredContent"]["usage"] = {k: v for k, v in usage.items()
                        if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                        and isinstance(v, int) and not isinstance(v, bool) and v >= 0} if isinstance(usage, dict) else {}
                if len(canonical(result).encode()) > MAX_RESPONSE:
                    result = {"content": [{"type": "text", "text": "脱敏后结果超过大小限制"}], "truncated": True}
                if raw.get("isError", False):
                    status, error = "failed", {"code": "tool_error", "message": "远程工具报告执行失败，请核对结果"}
                else:
                    status = "succeeded"
            except MCPTransportError as exc:
                status = "unknown" if client.dispatched else "failed"
                error = {"code": exc.code, "message": exc.message}
            except HTTPException as exc:
                status = "unknown" if client.dispatched else "failed"
                error = exc.detail if isinstance(exc.detail, dict) else {
                    "code": "authorization_failed", "message": "MCP 调用授权检查失败"}
            except Exception:
                # Never expose exception repr: TLS/HTTP providers may include credentials.
                status = "unknown" if client.dispatched else "failed"
                error = {"code": "execution_error", "message": "MCP 执行中断，请查看运行状态"}
            with session_scope() as db:
                db.execute(update(MCPRunDB).where(
                    MCPRunDB.id == prepared["id"], MCPRunDB.owner == owner, MCPRunDB.status == "running"
                ).values(status=status, result_json=canonical(result) if result is not None else None,
                         error_json=canonical(error) if error else None, active_owner=None,
                         lease_until=0, updated_at=now()))
                return run_view(db.get(MCPRunDB, prepared["id"]))
