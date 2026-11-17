"""Desktop CLI contracts. No real authorizations, documents or messages."""
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import feishu_cli as cli
from app.services.feishu_service import FeishuError, FeishuService


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "desktop_runtime", True)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(settings, "feishu_transport", "cli")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli, "_flows", {})
    monkeypatch.setattr(cli, "executable", lambda: "C:/trusted/lark-cli.exe")
    monkeypatch.setattr(cli.subprocess, "run", lambda **kw: (_ for _ in ()).throw(AssertionError("Real CLI forbidden")))


def test_only_desktop_selects_cli(monkeypatch):
    from app.services.feishu_cli_service import FeishuCLIService
    assert isinstance(FeishuService().for_owner("alice"), FeishuCLIService)
    monkeypatch.setattr(settings, "desktop_runtime", False)
    assert type(FeishuService().for_owner("alice")) is FeishuService
    monkeypatch.setattr(settings, "desktop_runtime", True)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", True)
    assert not cli.enabled()


def test_desktop_connection_ignores_shared_integration_url(monkeypatch):
    from app.routers import feishu

    monkeypatch.setattr(settings, "feishu_service_url", "https://integration.example.invalid")
    monkeypatch.setattr(feishu.CloudAccountService, "access_token",
                        lambda *args: pytest.fail("Local Feishu must not read a cloud token"))
    assert feishu.proxy(("local-owner", "local-owner"), "GET", "/status") == (False, None)


def test_desktop_request_does_not_fall_back_to_shared_authorization(monkeypatch):
    from fastapi import HTTPException, Request
    from app.routers import feishu

    monkeypatch.setattr(settings, "desktop_runtime", False)
    request = Request({"type": "http", "headers": [(b"x-vinote-client", b"desktop")]})
    with pytest.raises(HTTPException, match="本机飞书服务未启用") as error:
        feishu.principal(request)
    assert error.value.status_code == 503


@pytest.mark.parametrize(("client", "base_url", "expected"), [
    (("127.0.0.1", 12345), "http://127.0.0.1:8900", 200),
    (("192.0.2.1", 12345), "http://127.0.0.1:8900", 503),
    (("127.0.0.1", 12345), "https://example.invalid", 503),
])
def test_split_desktop_feishu_is_local_only(monkeypatch, client, base_url, expected):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import feishu
    from app.services import feishu_auto_runtime

    monkeypatch.setattr(settings, "desktop_runtime", False)
    monkeypatch.setattr(feishu, "get_current_user", lambda *_: SimpleNamespace(user_id="local-owner"))
    monkeypatch.setattr(feishu_auto_runtime, "decorate_status", lambda _, result: result)
    app = FastAPI()
    app.include_router(feishu.router)
    response = TestClient(app, client=client, base_url=base_url).get(
        "/feishu/status", headers={"X-VINote-Client": "desktop"},
    )
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["transport"] == "cli"
    assert not cli.enabled()


def test_uses_private_owner_config_and_never_global_profile(monkeypatch):
    monkeypatch.setenv("LARKSUITE_CLI_CONFIG_DIR", "C:/some-other-agent")
    monkeypatch.setenv("OPENCLAW_HOME", "C:/some-agent")
    monkeypatch.setenv("FEISHU_APP_SECRET", "synthetic-secret")
    first, second = cli.environment("alice"), cli.environment("bob")
    assert first["LARKSUITE_CLI_CONFIG_DIR"] != second["LARKSUITE_CLI_CONFIG_DIR"]
    assert Path(first["LARKSUITE_CLI_CONFIG_DIR"]).is_relative_to(settings.data_dir)
    assert "OPENCLAW_HOME" not in first and "FEISHU_APP_SECRET" not in first


def test_native_executable_and_no_shell_body_only_stdin(monkeypatch):
    calls = []
    def run(**kw):
        calls.append(kw)
        return SimpleNamespace(returncode=0, stdout=b'{"ok":true,"identity":"user","data":{"document_id":"synthetic"}}')
    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.api("alice", "POST", "docx/v1/documents", body={"title": "private title"}) == {"document_id": "synthetic"}
    call = calls[0]
    assert call["shell"] is False and call["args"][0].endswith("lark-cli.exe")
    assert "private title" not in " ".join(call["args"])
    assert json.loads(call["input"]) == {"title": "private title"}
    assert call["args"][call["args"].index("--as") + 1] == "user"


@pytest.mark.parametrize("method,path", [("DELETE", "drive/v1/files/x"), ("GET", "https://untrusted.invalid"),
    ("POST", "auth/v3/tenant_access_token/internal"), ("GET", "docx/../credentials"), ("GET", "search/v1/user?x=1")])
def test_cli_cannot_route_to_server_or_secret_endpoints(method, path):
    with pytest.raises(FeishuError):
        cli.api("alice", method, path)


def test_bot_fallback_is_rejected(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a, **kw: {"ok": True, "identity": "bot", "data": {"document_id": "wrong"}})
    with pytest.raises(FeishuError) as exc:
        cli.api("alice", "POST", "docx/v1/documents", body={"title": "Synthetic"})
    assert exc.value.code == "connection_changed"


def test_cli_confirmation_is_never_bypassed(monkeypatch):
    calls = []
    def run(**kw):
        calls.append(kw["args"])
        return SimpleNamespace(returncode=10, stdout=b'{"ok":false,"error":{"type":"confirmation_required"}}')
    monkeypatch.setattr(cli.subprocess, "run", run)
    with pytest.raises(FeishuError) as exc:
        cli.api("alice", "POST", "drive/v1/permissions/x/members", body={"perm": "view"})
    assert exc.value.code == "confirmation_required"
    assert len(calls) == 1 and "--yes" not in calls[0]


def test_timeout_is_unknown_and_does_not_retry(monkeypatch):
    calls = []
    def run(**kw):
        calls.append(kw)
        raise subprocess.TimeoutExpired(kw["args"], 30)
    monkeypatch.setattr(cli.subprocess, "run", run)
    with pytest.raises(FeishuError) as exc:
        cli.api("alice", "POST", "docx/v1/documents", body={"title": "Synthetic"})
    assert exc.value.uncertain and len(calls) == 1


def test_opaque_device_code_never_reaches_frontend_and_owner_is_bound(monkeypatch):
    (cli.directory("alice") / "config.json").write_text("{}")
    monkeypatch.setattr(cli, "auth_status", lambda _: {"appId": "cli_synthetic"})
    monkeypatch.setattr(cli, "run", lambda *a, **kw: {"device_code": "private-device-code",
        "verification_url": "https://open.feishu.cn/authorize?x=opaque", "expires_in": 500})
    monkeypatch.setattr(cli, "qr", lambda owner, url: "data:image/png;base64,synthetic")
    view = cli.start("alice")
    assert "private-device-code" not in json.dumps(view)
    assert cli.start("alice")["flow_id"] == view["flow_id"]
    with pytest.raises(FeishuError):
        cli.complete("bob", view["flow_id"])


def test_bad_existing_status_cannot_create_another_app(monkeypatch):
    (cli.directory("alice") / "config.json").write_text("{}")
    monkeypatch.setattr(cli, "auth_status", lambda _: (_ for _ in ()).throw(FeishuError("Synthetic outage", 502)))
    with pytest.raises(FeishuError):
        cli.start("alice")
    assert not cli._flows


def test_failed_completion_is_not_automatically_repolled(monkeypatch):
    identifier = "synthetic-flow"
    cli._flows[identifier] = {"owner": "alice", "stage": "authorization", "until": time.time() + 100,
                              "code": "private-code", "busy": False}
    calls = []
    def run(*a, **kw):
        calls.append(a)
        raise FeishuError("Synthetic unknown", 502, uncertain=True)
    monkeypatch.setattr(cli, "run", run)
    for _ in range(2):
        with pytest.raises(FeishuError):
            cli.complete("alice", identifier)
    assert len(calls) == 1


def test_cli_route_cannot_proxy_to_hongkong(monkeypatch):
    from app.routers.feishu import proxy
    monkeypatch.setattr(settings, "feishu_service_url", "https://synthetic-hk.invalid")
    assert proxy(("alice", "alice"), "POST", "/deliveries", {"content": "private"}) == (False, None)
