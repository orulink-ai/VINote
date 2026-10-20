"""Desktop-only native CLI boundary. Never reads CLI secrets or uses a shell.

Each VINote account has a private CLI configuration directory. It cannot alter
the default CLI/ViTalk profile. Device codes stay in process memory. Existing
publication journals, rather than CLI retry behavior, own write recovery.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from urllib.parse import urlparse

from app.config import settings
from app.services.feishu_service import FeishuError

_flows = {}
_flow_lock = threading.RLock()
_owner_generations = {}
SCOPES = ("offline_access docx:document docx:document.block:convert "
          "docs:permission.member:create docs:permission.member:auth "
          "docs:permission.setting:read docs:permission.setting:write_only "
          "drive:drive.metadata:readonly wiki:space:read wiki:node:read wiki:node:create "
          "contact:user:search im:chat:read im:message.send_as_user")


def enabled():
    return (settings.desktop_runtime and settings.feishu_transport == "cli"
            and not settings.workspace_cloud_runtime and not settings.content_cloud_runtime)


def executable():
    # npm's .cmd/.ps1 wrappers require a shell. Resolve its actual native binary.
    for folder in os.get_exec_path():
        root = Path(folder)
        native = root / ("lark-cli.exe" if os.name == "nt" else "lark-cli")
        if native.is_file():
            return str(native.resolve())
        bundled = root / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe"
        if os.name == "nt" and (root / "lark-cli.cmd").is_file() and bundled.is_file():
            return str(bundled.resolve())
    raise FeishuError("飞书连接组件尚未安装，请安装 lark-cli 后重新连接", 503, code="cli_missing")


def directory(owner):
    digest = hashlib.sha256(owner.encode()).hexdigest()
    root = Path(settings.data_dir) / "feishu-cli" / digest
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        raise FeishuError("飞书配置目录不可用", 503)
    return root.resolve()


def environment(owner):
    result = os.environ.copy()
    # Never inherit a different Agent workspace or credential injection.
    for key in list(result):
        if (key.startswith(("LARKSUITE_", "LARK_CLI_", "FEISHU_"))
                or key in {"OPENCLAW_HOME", "HERMES_HOME"}):
            result.pop(key)
    result.update(LARKSUITE_CLI_CONFIG_DIR=str(directory(owner)),
                  LARKSUITE_CLI_WORKSPACE="local", LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
                  LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    return result


def _command(owner, args):
    return dict(args=[executable(), *args], cwd=str(directory(owner)), env=environment(owner),
                shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def run(owner, args, *, body=None, timeout=30, credential_identity=None):
    from app.services.feishu_cli_lock import credential_lock
    try:
        with credential_lock(credential_identity, directory(owner)):
            result = subprocess.run(**_command(owner, args),
                                    input=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise FeishuError("飞书调用未得到确认，请核对原结果；不会自动重发", 502, uncertain=True) from None
    if len(result.stdout) > 8_000_000:
        raise FeishuError("飞书响应超出范围，请核对原结果", 502, uncertain=True)
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise FeishuError("飞书调用未完成，请检查连接组件和授权", 502, uncertain=True) from None
    if result.returncode or not isinstance(value, dict) or value.get("ok") is False:
        error = value.get("error", {}) if isinstance(value, dict) else {}
        category = error.get("type", "") if isinstance(error, dict) else ""
        if result.returncode == 10 or category == "confirmation_required":
            # Never append --yes or switch to an alternate HTTP path.
            raise FeishuError("此操作需要再次明确确认，尚未自动执行", 409, code="confirmation_required")
        if category in {"auth", "authentication", "not_configured"}:
            raise FeishuError("请扫码重新连接飞书", 401)
        if category in {"permission", "permission_denied"}:
            raise FeishuError("飞书权限不足，请检查本次授权", 403)
        raise FeishuError("飞书尚未确认操作结果，请核对原记录", 502, uncertain=True)
    return value


def auth_status(owner):
    return run(owner, ["auth", "status", "--json"])


def api(owner, method, path, *, body=None, params=None, credential_identity=None):
    if (method not in {"GET", "POST", "PATCH"} or not re.fullmatch(r"[A-Za-z0-9_/-]+", path)
            or ".." in path or not path.startswith(("authen/", "docx/", "drive/", "wiki/", "im/", "search/"))):
        raise FeishuError("不支持的飞书调用", 422)
    args = ["api", method, "/open-apis/" + path, "--as", "user", "--json"]
    if params:
        args += ["--params", json.dumps(params)]
    if body is not None:
        args += ["--data", "-"]
    raw = run(owner, args, body=body, credential_identity=credential_identity)
    if not isinstance(raw, dict) or raw.get("identity") != "user":
        writing = method in {"POST", "PATCH"}
        message = ("飞书返回身份异常，写入结果尚未确认；不会自动重发" if writing else
                   "飞书未确认用户身份，已停止")
        raise FeishuError(message, 409, uncertain=writing, code="connection_changed")
    data = raw.get("data")
    if not isinstance(data, dict):
        raise FeishuError("飞书返回格式异常，请核对原结果", 502, uncertain=True)
    return data


def qr(owner, url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"open.feishu.cn", "accounts.feishu.cn"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise FeishuError("飞书授权地址未通过校验", 502)
    name = "authorization-" + uuid.uuid4().hex + ".png"
    path = directory(owner) / name
    try:
        # This command emits a human success line, not a JSON envelope.
        result = subprocess.run(**_command(owner, ["auth", "qrcode", url, "--output", name]),
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10)
        data = path.read_bytes() if result.returncode == 0 else b""
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 1_000_000:
            raise ValueError()
        return "data:image/png;base64," + base64.b64encode(data).decode()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise FeishuError("授权二维码暂时无法生成，请重新连接", 502) from None
    finally:
        path.unlink(missing_ok=True)


def _view(owner, identifier, flow):
    if flow.get("error"):
        raise FeishuError(flow["error"], 409)
    url = flow.get("url")
    if not url:
        return {"flow_id": identifier, "stage": "application", "pending": True,
                "expires_at": flow["until"], "url": "", "qr_data_url": ""}
    return {"flow_id": identifier, "stage": flow["stage"], "expires_at": flow["until"],
            "url": url, "qr_data_url": qr(owner, url)}


def _new_application(owner, flow):
    """Only initiated by an explicit connect action; approval happens in Feishu."""
    try:
        command = _command(owner, ["config", "init", "--new", "--name", "VINote"])
        with subprocess.Popen(**command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as child:
            flow["process"] = child
            def expire():
                if child.poll() is None:
                    child.kill()
            timer = threading.Timer(600, expire)
            timer.daemon = True
            timer.start()
            try:
                total = 0
                for line in iter(child.stdout.readline, b""):
                    total += len(line)
                    if total > 1_000_000:
                        child.kill()
                        raise ValueError()
                    # Never retain/output the subprocess log: allowlist only the
                    # opaque official confirmation URL from the registration step.
                    text = line.decode("utf-8", errors="replace")
                    for match in re.findall(r'https://(?:open|accounts)\.feishu\.cn/[^\s<>"\x1b]+', text):
                        if "/page/cli?" in match:
                            flow["url"] = match
                code = child.wait(timeout=5)
                flow["done"] = code == 0
                if code:
                    flow["error"] = "应用创建尚未完成，请核对飞书确认页后重新连接"
            finally:
                timer.cancel()
    except Exception:
        flow["error"] = "飞书应用配置尚未完成，请重新连接"


def start(owner):
    if not enabled():
        raise FeishuError("此连接方式仅供桌面端使用", 403)
    executable()
    with _flow_lock:
        for identifier, flow in list(_flows.items()):
            if flow["until"] <= time.time():
                flow["revoked"] = True
                child = flow.get("process")
                if child and child.poll() is None:
                    child.kill()
                del _flows[identifier]
            elif flow["owner"] == owner and not flow.get("error"):
                return _view(owner, identifier, flow)
        if len(_flows) >= 16:
            raise FeishuError("连接请求较多，请稍后再试", 429)
        # A private directory, never the system default CLI profile.
        # An outage or malformed status is not permission to create a second
        # app. Only an absent private configuration starts registration.
        configured = (directory(owner) / "config.json").is_file()
        if configured:
            status = auth_status(owner)
            if not status.get("appId"):
                raise FeishuError("已有飞书配置尚未核验，请检查后重新连接", 409)
        identifier = str(uuid.uuid4())
        if not configured:
            marker = directory(owner) / "application-intent.json"
            # A restart must not create another personal application while the
            # previous provider outcome is unknown. No device code is persisted.
            if marker.exists():
                raise FeishuError("上次应用创建结果尚未确认，请先在飞书应用后台核对，避免重复创建", 409,
                                  code="application_result_unknown")
            with marker.open("x", encoding="utf-8") as handle:
                json.dump({"operation_id": identifier, "started_at": time.time()}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            flow = {"owner": owner, "stage": "application", "until": time.time() + 600}
            flow["generation"] = _owner_generations[owner] = uuid.uuid4().hex
            _flows[identifier] = flow
            threading.Thread(target=_new_application, args=(owner, flow), daemon=True).start()
            return _view(owner, identifier, flow)
        raw = run(owner, ["auth", "login", "--scope", SCOPES, "--no-wait", "--json"])
        value = raw.get("data", raw)
        url = value.get("verification_url") or value.get("verification_uri_complete")
        if not isinstance(value.get("device_code"), str) or not value["device_code"] or not url:
            raise FeishuError("飞书未返回有效授权流程", 502)
        lifetime = value.get("expires_in", 600)
        if type(lifetime) not in {int, float} or not 0 < lifetime <= 3600:
            raise FeishuError("授权有效期无效", 502)
        flow = {"owner": owner, "stage": "authorization", "until": time.time() + lifetime,
                "url": url, "code": value["device_code"], "busy": False}
        flow["generation"] = _owner_generations[owner] = uuid.uuid4().hex
        _flows[identifier] = flow
        return _view(owner, identifier, flow)


def _live_flow(owner, identifier, expected=None):
    """Caller holds _flow_lock; generations are internal, never client input."""
    flow = _flows.get(identifier)
    if (not flow or flow.get("owner") != owner or flow.get("until", 0) <= time.time() or
            flow.get("revoked") or not flow.get("generation") or
            flow["generation"] != _owner_generations.get(owner) or
            (expected is not None and flow is not expected)):
        raise FeishuError("连接流程已取消或过期，请重新连接", 409, code="authorization_cancelled")
    return flow


def completion_check(owner, identifier):
    """Check before/after service identity readback; performs no external I/O.

    This check alone is NOT permission to commit later. The final transaction
    must run inside completion_commit, including its actual DB commit on exit.
    """
    with _flow_lock:
        flow = _live_flow(owner, identifier)
        if flow.get("exchange_complete") is not True:
            raise FeishuError("授权交换尚未确认，不能保存连接", 409, code="authorization_not_confirmed")


@contextmanager
def completion_commit(owner, identifier):
    """Consume one exchanged flow while serializing cancellation and DB commit.

    Service integration: do network reads OUTSIDE this guard, then acquire its
    owner lock, enter this guard, and enter the DB transaction INSIDE the guard.
    The DB transaction must commit/rollback BEFORE this guard exits. Both success
    and failure consume the exchange; neither can replay the provider call.
    """
    with _flow_lock:
        completion_check(owner, identifier)
        flow = _live_flow(owner, identifier)
        if flow.get("committing"):
            raise FeishuError("正在保存已核验连接，请稍候", 409, code="authorization_in_progress")
        flow["committing"] = True
        try:
            yield
        finally:
            flow["revoked"] = True
            flow.pop("code", None)
            if _flows.get(identifier) is flow:
                del _flows[identifier]


def complete(owner, identifier):
    with _flow_lock:
        flow = _flows.get(identifier)
        if not flow or flow["owner"] != owner or flow["until"] <= time.time():
            raise FeishuError("连接流程已过期，请重新连接", 409)
        # In-memory legacy/test flows have no stamp; initialize it once. New
        # start() flows already carry a stamp before any exchange can begin.
        if "generation" not in flow:
            flow["generation"] = _owner_generations.setdefault(owner, uuid.uuid4().hex)
        _live_flow(owner, identifier, expected=flow)
        if flow.get("error"):
            raise FeishuError(flow["error"], 409)
        if flow["stage"] == "application":
            if not flow.get("done"):
                return _view(owner, identifier, flow)
            del _flows[identifier]
            return start(owner)
        if flow.get("busy"):
            raise FeishuError("正在核验授权，请稍候", 409)
        flow["busy"] = True
        code = flow["code"]
    try:
        run(owner, ["auth", "login", "--device-code", code, "--json"], timeout=30)
        with _flow_lock:
            _live_flow(owner, identifier, expected=flow)
            flow["exchange_complete"] = True
            flow.pop("code", None)
            # Retain the one-shot completion through service identity readback.
            # completion_commit, cancel or expiry consumes it, not another POST.
        return None
    except BaseException:
        with _flow_lock:
            # A token-exchange timeout is never automatically repeated.
            flow["revoked"] = True
            flow.pop("code", None)
            if _flows.get(identifier) is flow:
                del _flows[identifier]
        raise


def cancel(owner):
    with _flow_lock:
        # Advance even if no flow is currently listed. A previously captured
        # completion may never bind a connection after this cancellation.
        _owner_generations[owner] = uuid.uuid4().hex
        for identifier, flow in list(_flows.items()):
            if flow["owner"] == owner:
                flow["revoked"] = True
                flow.pop("code", None)
                child = flow.get("process")
                try:
                    if child and child.poll() is None:
                        child.kill()
                except OSError:
                    # A process may have exited between poll() and kill(). Its
                    # lost OS handle cannot restore the revoked flow epoch.
                    pass
                del _flows[identifier]


def shutdown():
    with _flow_lock:
        owners = {flow["owner"] for flow in _flows.values()}
        for owner in owners:
            cancel(owner)
