import json
import time
import pytest
from app.services.feishu_service import FeishuError

from app.services import feishu_cli as cli


def test_process_launch_failure_releases_only_own_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "directory", lambda owner: tmp_path)
    monkeypatch.setattr(cli, "_command", lambda *args: {})
    monkeypatch.setattr(cli.subprocess, "Popen", lambda **kwargs: (_ for _ in ()).throw(OSError()))
    marker = tmp_path / "application-intent.json"
    marker.write_text(json.dumps({"operation_id": "this-flow"}), encoding="utf-8")
    flow = {"operation_id": "this-flow", "until": time.time() + 100}
    cli._new_application("alice", flow)
    assert not marker.exists()
    assert flow.get("error")


def test_process_launch_failure_preserves_different_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "directory", lambda owner: tmp_path)
    monkeypatch.setattr(cli, "_command", lambda *args: {})
    monkeypatch.setattr(cli.subprocess, "Popen", lambda **kwargs: (_ for _ in ()).throw(OSError()))
    marker = tmp_path / "application-intent.json"
    marker.write_text(json.dumps({"operation_id": "other-flow"}), encoding="utf-8")
    cli._new_application("alice", {"operation_id": "this-flow"})
    assert marker.exists()


def test_confirmed_recovery_preserves_old_marker_and_does_not_register(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "directory", lambda owner: tmp_path)
    monkeypatch.setattr(cli, "_flows", {})
    marker = tmp_path / "application-intent.json"
    original = json.dumps({"operation_id": "old", "started_at": time.time() - 2000})
    marker.write_text(original, encoding="utf-8")
    info = cli.registration_recovery_info("alice")
    assert info["available"]
    cli.recover_registration("alice", info["revision"], True)
    assert not marker.exists()
    assert [p.read_text(encoding="utf-8") for p in tmp_path.glob("application-intent-recovered-*.json")] == [original]


def test_recovery_rejects_stale_confirmation_and_existing_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "directory", lambda owner: tmp_path)
    monkeypatch.setattr(cli, "_flows", {})
    marker = tmp_path / "application-intent.json"
    marker.write_text(json.dumps({"operation_id": "old", "started_at": time.time() - 2000}))
    info = cli.registration_recovery_info("alice")
    with pytest.raises(FeishuError):
        cli.recover_registration("alice", "0" * 64, True)
    (tmp_path / "config.json").write_text("{}")
    with pytest.raises(FeishuError):
        cli.recover_registration("alice", info["revision"], True)
    assert marker.exists()


def test_recovery_requires_elapsed_window_and_no_active_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "directory", lambda owner: tmp_path)
    marker = tmp_path / "application-intent.json"
    marker.write_text(json.dumps({"operation_id": "old", "started_at": time.time()}))
    monkeypatch.setattr(cli, "_flows", {})
    assert not cli.registration_recovery_info("alice")["available"]
    marker.write_text(json.dumps({"operation_id": "old", "started_at": time.time() - 2000}))
    monkeypatch.setattr(cli, "_flows", {"old": {"owner": "alice", "stage": "application", "until": time.time() + 5}})
    assert not cli.registration_recovery_info("alice")["available"]


def test_recovery_http_requires_confirmed_owner_and_desktop(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import feishu
    monkeypatch.setattr(cli, "directory", lambda owner: tmp_path / owner)
    monkeypatch.setattr(cli, "_flows", {})
    monkeypatch.setattr(cli, "enabled", lambda: True)
    root = tmp_path / "alice"
    root.mkdir()
    marker = root / "application-intent.json"
    marker.write_text(json.dumps({"operation_id": "old", "started_at": time.time() - 2000}))
    app = FastAPI()
    app.include_router(feishu.router)
    app.dependency_overrides[feishu.principal] = lambda: ("alice", "alice")
    client = TestClient(app)
    response = client.get("/feishu/authorize/recovery")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    revision = response.json()["revision"]
    assert client.post("/feishu/authorize/recovery", json={"revision": revision, "confirmed": False}).status_code == 422
    assert marker.exists()
    assert client.post("/feishu/authorize/recovery", json={"revision": revision, "confirmed": True}).json() == {"recovered": True}
    assert client.post("/feishu/authorize/recovery", json={"revision": revision, "confirmed": True}).status_code == 409
    monkeypatch.setattr(cli, "enabled", lambda: False)
    assert client.get("/feishu/authorize/recovery").status_code == 404
