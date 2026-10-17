"""Offline protocol/authorization/receipt regressions. No service or real tokens."""
import copy
import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.first_party_translation import (
    AUTH_TYPE, ENDPOINT, FirstPartyTranslationDB, TOOL, TOOL_NAME,
)
from app.models.mcp_connections import MCPConnectionDB, MCPRunDB
from app.services import first_party_translation_service as provider
from app.services import mcp_connection_service as mcp

ACTUAL_PROVIDER_JSON = provider.provider_json
ACTUAL_STREAMABLE_CLIENT = mcp.StreamableHTTPClient


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'translation.db'}", connect_args={"check_same_thread": False})
    for model in (MCPConnectionDB, MCPRunDB, FirstPartyTranslationDB):
        model.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    monkeypatch.setattr(provider, "session_scope", sessions)
    monkeypatch.setattr(mcp, "session_scope", sessions)
    monkeypatch.setattr(provider.settings, "vilab_server_url", "https://cloud.example")
    state = SimpleNamespace(calls=[], wires=[], failure=None, hook=None, finish="stop", refusal=None,
        catalog={"models": [{"id": "actual-model", "modelType": "llm", "runtimeStatus": "available"}]},
        defaults={"llm_model": "actual-model"})

    def cloud(path, bearer, deadline, payload=None):
        state.wires.append((path, bearer, payload))
        if path == "/v1/models":
            return copy.deepcopy(state.catalog)
        if path == "/v1/default-models":
            return copy.deepcopy(state.defaults)
        state.calls.append(payload)
        if state.hook:
            state.hook()
        if state.failure:
            raise state.failure
        return {"model": "actual-provider-model", "choices": [{"finish_reason": state.finish, "message": {
            "content": "真实测试译文", "refusal": state.refusal}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "untrusted": "secret"}}

    monkeypatch.setattr(provider, "provider_json", cloud)
    from app.routers import first_party_translation as rpc, mcp_connections as routes
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.include_router(rpc.router, prefix="/api")
    app.dependency_overrides[rpc.principal] = lambda: ("a", None)
    monkeypatch.setattr(routes, "proxy_integration", lambda *args: (False, None))
    monkeypatch.setattr(rpc, "proxy_integration", lambda *args: (False, None))
    state.client = TestClient(app)
    state.service, state.sessions = mcp.MCPConnectionService(), sessions
    state.cid = provider.provision("a", "test-session")["connection"]["id"]

    class Bridge:
        def __init__(self, url, token="", deadline=None):
            assert url == ENDPOINT
            self.token, self.dispatched, self.run_id = token, False, None

        def rpc(self, method, params=None):
            headers = {"Authorization": "Bearer " + self.token}
            if self.run_id:
                headers["X-VINote-MCP-Run-Id"] = self.run_id
            response = state.client.post("/api/mcp-first-party/translation", json={
                "jsonrpc": "2.0", "id": "rpc-test", "method": method, "params": params or {}}, headers=headers)
            if response.status_code != 200:
                raise mcp.MCPTransportError("adapter_rejected", "Adapter rejected")
            return response.json()["result"]

        def discover(self):
            self.rpc("initialize", {"protocolVersion": mcp.PROTOCOLS[0]})
            return self.rpc("tools/list")["tools"]

        def call(self, name, arguments):
            self.dispatched = True
            return self.rpc("tools/call", {"name": name, "arguments": arguments})

    monkeypatch.setattr(mcp, "StreamableHTTPClient", Bridge)
    state.service.discover("a", state.cid, session_bearer="test-session")
    state.service.patch_tool("a", state.cid, TOOL_NAME, True)
    yield state
    state.client.close()
    engine.dispose()


def body(request="one", **args):
    return {"requestId": request, "toolName": TOOL_NAME,
            "arguments": {"text": "# Frozen source", "target_language": "zh", **args}}


def confirm(env, request=None):
    request = request or body()
    prepared = env.service.invoke("a", env.cid, request, session_bearer="test-session")
    return env.service.invoke("a", env.cid, {**request, "confirmed": True,
        "confirmationToken": prepared["confirmationToken"]}, session_bearer="test-session")


def running(env, request=None):
    request = request or body()
    prepared = env.service.invoke("a", env.cid, request, session_bearer="test-session")
    with env.sessions() as db:
        row = db.get(MCPRunDB, prepared["id"])
        row.status, row.active_owner, row.lease_until = "running", "a", time.time() + 150
    return prepared["id"], request["arguments"]


def test_real_protocol_and_confirmation_flow(env):
    pending = env.service.invoke("a", env.cid, body(), session_bearer="test-session")
    assert pending["status"] == "awaiting_confirmation" and env.calls == []
    done = confirm(env)
    assert done["status"] == "succeeded"
    assert done["result"]["content"][0]["text"] == "真实测试译文"
    metadata = done["result"]["structuredContent"]
    assert metadata["model"] == "actual-model" and metadata["finishReason"] == "stop"
    assert metadata["requestedModel"] == "actual-model" and metadata["reportedModel"] == "actual-provider-model"
    assert metadata["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert env.calls[0]["model"] == "actual-model"
    assert env.calls[0]["messages"][1]["content"] == "# Frozen source"
    assert env.calls[0]["stream"] is False
    assert len(env.calls) == 1
    assert confirm(env)["id"] == done["id"] and len(env.calls) == 1
    assert provider.get_receipt("a", done["id"])["status"] == "succeeded"
    assert env.service.get_run_by_request("a", "one")["id"] == done["id"]


def test_session_is_memory_only_and_provision_owner_idempotent(env):
    again = provider.provision("a", "another-session")
    assert again["connection"]["id"] == env.cid
    assert again["connection"]["authType"] == AUTH_TYPE
    assert again["connection"]["managed"] and not again["connection"]["hasCredential"]
    other = provider.provision("b", "b-session")
    assert other["connection"]["id"] != env.cid
    confirm(env)
    with env.sessions() as db:
        assert db.get(MCPConnectionDB, env.cid).credential == ""
        run = db.get(MCPRunDB, env.service.get_run_by_request("a", "one")["id"])
        assert "test-session" not in run.arguments_json + (run.result_json or "")
    assert all(w[1] == "test-session" for w in env.wires)


@pytest.mark.parametrize("args", [{"target_language": "ja"}, {"target_language": "EN"},
    {"target_language": None}, {"text": " "}, {"text": ["source"]}, {"text": "a" * 60001},
    {"extra": "value"}, {"text": "中" * 23000}])
def test_arguments_rejected_before_model_and_intent(env, args):
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", env.cid, body(**args), session_bearer="test-session")
    assert caught.value.status_code in (413, 422) and env.calls == []


@pytest.mark.parametrize("patch", [{"url": "https://evil.example/mcp"},
    {"authType": "none"}, {"token": "stolen"}, {"name": "Third-party"}])
def test_managed_configuration_cannot_relay_session_elsewhere(env, patch):
    with pytest.raises(HTTPException) as caught:
        env.service.patch("a", env.cid, patch)
    assert caught.value.status_code == 409
    with env.sessions() as db:
        db.get(MCPConnectionDB, env.cid).url = "https://evil.example/mcp"
    with pytest.raises(HTTPException):
        env.service.discover("a", env.cid, session_bearer="test-session")
    assert env.wires == []


def test_public_create_cannot_forge_session_auth(env):
    with pytest.raises(HTTPException):
        env.service.create("a", {"name": "Fake", "url": ENDPOINT, "authType": AUTH_TYPE, "token": "fake"})
    with pytest.raises(HTTPException):
        env.service.discover("a", env.cid)


@pytest.mark.parametrize("finish,refusal", [("length", None), ("content_filter", None),
                                           (None, None), ("stop", "refused")])
def test_incomplete_or_refused_output_never_preview_ready(env, finish, refusal):
    env.finish, env.refusal = finish, refusal
    done = confirm(env)
    assert done["status"] == "failed" and done["result"]["content"] == []
    assert provider.get_receipt("a", done["id"])["result"] is None
    confirm(env)
    assert len(env.calls) == 1


def test_unknown_call_not_replayed_and_readonly_original_lookup(env):
    env.failure = provider.ProviderFailure("provider_unavailable", True)
    done = confirm(env)
    assert done["status"] == "unknown"
    original = provider.get_receipt("a", done["id"])
    assert original["status"] == "unknown" and original["replayAllowed"] is False
    assert confirm(env)["status"] == "unknown" and len(env.calls) == 1
    assert provider.call_translation("a", done["id"], body()["arguments"], "test-session")["isError"]
    assert len(env.calls) == 1
    for fn in (lambda: provider.get_receipt("b", done["id"]),
               lambda: provider.get_receipt("a", "absent")):
        with pytest.raises(HTTPException) as caught:
            fn()
        assert caught.value.status_code == 404


def test_changed_input_existing_receipt_conflicts(env):
    done = confirm(env)
    with pytest.raises(HTTPException) as caught:
        provider.call_translation("a", done["id"], body(text="different")["arguments"], "test-session")
    assert caught.value.status_code == 409 and len(env.calls) == 1


@pytest.mark.parametrize("mutation", ["owner", "status", "lease", "grant", "revision", "fingerprint"])
def test_call_cannot_bypass_original_confirmation(env, mutation):
    run_id, args = running(env)
    with env.sessions() as db:
        run, connection = db.get(MCPRunDB, run_id), db.get(MCPConnectionDB, env.cid)
        if mutation == "owner": run.owner = "b"
        elif mutation == "status": run.status = "awaiting_confirmation"
        elif mutation == "lease": run.lease_until = 0
        elif mutation == "grant": connection.tools_json = "[]"
        elif mutation == "revision": connection.revision += 1
        elif mutation == "fingerprint": run.fingerprint = "changed"
    with pytest.raises(HTTPException):
        provider.call_translation("a", run_id, args, "test-session")
    assert env.calls == []


def test_competing_claim_reads_original_while_model_runs(env):
    run_id, args = running(env)
    entered, release = threading.Event(), threading.Event()
    env.hook = lambda: (entered.set(), release.wait(5))
    outputs = []
    worker = threading.Thread(target=lambda: outputs.append(provider.call_translation("a", run_id, args, "test-session")))
    worker.start()
    try:
        assert entered.wait(5)
        original = provider.call_translation("a", run_id, args, "test-session")
        assert original["structuredContent"]["status"] == "running"
        assert len(env.calls) == 1
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and outputs[0]["isError"] is False


def test_expired_receipt_is_unknown_without_mutation(env):
    run_id, args = running(env)
    with env.sessions() as db:
        db.add(FirstPartyTranslationDB(owner="a", run_id=run_id, fingerprint=mcp.digest(args),
            target_language="zh", status="running", dispatched=True, lease_until=0,
            created_at=mcp.now(), updated_at=mcp.now()))
    assert provider.get_receipt("a", run_id)["status"] == "unknown"
    assert provider.call_translation("a", run_id, args, "test-session")["structuredContent"]["status"] == "unknown"
    with env.sessions() as db:
        assert db.get(FirstPartyTranslationDB, ("a", run_id)).status == "running"
    assert env.calls == []


def test_protocol_auth_origin_schema_no_store_and_static_provision(env):
    root = "/api/mcp-first-party/translation"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert env.client.post(root, json=request).status_code == 401
    headers = {"Authorization": "Bearer test-session"}
    assert env.client.post(root, json=request, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    response = env.client.post(root, json=request, headers=headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["result"]["tools"] == [TOOL]
    assert env.client.post(root, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code == 202
    assert env.client.post(root, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": TOOL_NAME, "arguments": body()["arguments"]}}, headers=headers).status_code == 422
    provisioned = env.client.post("/api/mcp-connections/first-party/translation", json={}, headers=headers)
    assert provisioned.status_code == 201 and provisioned.json()["connection"]["id"] == env.cid
    assert env.client.post("/api/mcp-connections/first-party/translation", json={"url": "https://evil.example"}, headers=headers).status_code == 422
    done = confirm(env)
    for path in (root + "/receipts/", "/api/mcp-connections/first-party/translation/receipts/"):
        assert env.client.get(path + done["id"], headers=headers).json()["status"] == "succeeded"


def test_provider_unconfigured_no_fake_connected_provision(env, monkeypatch):
    monkeypatch.setattr(provider.settings, "vilab_server_url", "")
    with pytest.raises(HTTPException) as caught:
        provider.provision("a", "test-session")
    assert caught.value.status_code == 503


def test_generation_busy_is_known_no_dispatch_and_same_run_not_retried(env):
    from app.services.workspace_generation import _generation_slot
    assert _generation_slot.acquire(blocking=False)
    try:
        done = confirm(env)
        assert done["status"] == "failed" and env.calls == []
        assert provider.get_receipt("a", done["id"])["providerDispatched"] is False
    finally:
        _generation_slot.release()
    assert confirm(env)["status"] == "failed" and env.calls == []


def test_provider_cannot_persist_echoed_session_as_model_metadata(env, monkeypatch):
    def models(path, bearer, deadline, payload=None):
        if path == "/v1/models":
            return [{"id": bearer, "modelType": "llm", "runtimeStatus": "available"}]
        return {"llm_model": bearer}
    monkeypatch.setattr(provider, "provider_json", models)
    done = confirm(env)
    assert done["status"] == "failed"
    receipt = provider.get_receipt("a", done["id"])
    assert receipt["model"] == "" and "test-session" not in json.dumps(receipt)


def live_metadata(env):
    # Shape and IDs from the user's authenticated GET evidence; no real network.
    env.catalog = {"data": [
        {"id": "deepseek-v4.1-flash", "modelType": "llm", "runtimeStatus": "available"},
        {"id": "codex/gpt-6-luna", "modelType": "llm", "runtimeStatus": "available"},
        {"id": "asr-model", "modelType": "asr", "runtimeStatus": "available"}]}
    env.defaults = {"llm_model": None, "models": env.catalog["data"]}


def test_explicit_owner_selection_works_with_null_service_default(env):
    live_metadata(env)
    request = body(model="codex/gpt-6-luna")
    pending = env.service.invoke("a", env.cid, request, session_bearer="test-session")
    assert pending["arguments"]["model"] == "codex/gpt-6-luna" and not env.wires
    done = confirm(env, request)
    assert done["status"] == "succeeded"
    assert env.calls[0]["model"] == "codex/gpt-6-luna"
    assert done["result"]["structuredContent"]["requestedModel"] == "codex/gpt-6-luna"
    assert provider.get_receipt("a", done["id"])["model"] == "codex/gpt-6-luna"
    assert [w[0] for w in env.wires] == ["/v1/models", "/openai/v1/chat/completions"]
    assert confirm(env, request)["id"] == done["id"] and len(env.calls) == 1


@pytest.mark.parametrize("model", ["unknown", "asr-model", "offline-model"])
def test_unavailable_explicit_model_does_not_switch_to_default(env, model):
    live_metadata(env)
    env.catalog["data"].append({"id": "offline-model", "modelType": "llm", "runtimeStatus": "stopped"})
    env.defaults = {"llm_model": "deepseek-v4.1-flash"}
    done = confirm(env, body(model=model))
    assert done["status"] == "failed" and env.calls == []
    assert done["result"]["structuredContent"]["error"]["code"] == "model_unavailable"
    assert provider.get_receipt("a", done["id"])["providerDispatched"] is False
    assert [w[0] for w in env.wires] == ["/v1/models"]


@pytest.mark.parametrize("default", [None, "missing", "asr-model"])
def test_missing_or_invalid_default_never_selects_first_available(env, default):
    live_metadata(env)
    env.defaults["llm_model"] = default
    done = confirm(env)
    assert done["status"] == "failed" and env.calls == []
    # Later configuration changes cannot turn this original failed run into a replay.
    env.defaults["llm_model"] = "codex/gpt-6-luna"
    assert confirm(env)["id"] == done["id"] and env.calls == []
    with pytest.raises(HTTPException) as caught:
        confirm(env, body(model="codex/gpt-6-luna"))
    assert caught.value.status_code == 409 and env.calls == []


def test_omitted_model_uses_only_validated_default_and_keeps_original_arguments(env):
    live_metadata(env)
    env.defaults["llm_model"] = "codex/gpt-6-luna"
    done = confirm(env)
    assert done["status"] == "succeeded" and "model" not in done["arguments"]
    assert env.calls[0]["model"] == "codex/gpt-6-luna"


@pytest.mark.parametrize("model", [None, "", " model", "https://other.example/?key=secret", "a" * 201])
def test_invalid_model_argument_rejected_before_intent(env, model):
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", env.cid, body(model=model), session_bearer="test-session")
    assert caught.value.status_code == 422 and not env.wires


def test_model_change_invalidates_original_confirmation(env):
    request = body(model="actual-model")
    prepared = env.service.invoke("a", env.cid, request, session_bearer="test-session")
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", env.cid, {**body(model="another-model"), "confirmed": True,
            "confirmationToken": prepared["confirmationToken"]}, session_bearer="test-session")
    assert caught.value.status_code == 409 and not env.wires


def test_new_schema_requires_rediscovery_and_regrant(env):
    old_tool = copy.deepcopy(TOOL)
    old_tool["inputSchema"]["properties"].pop("model")
    old_tools = mcp.normalize_tools([old_tool])
    old_tools[0]["enabled"] = True
    with env.sessions() as db:
        db.get(MCPConnectionDB, env.cid).tools_json = mcp.canonical(old_tools)
    discovered = env.service.discover("a", env.cid, session_bearer="test-session")
    assert discovered["tools"][0]["enabled"] is False
    with pytest.raises(HTTPException):
        env.service.invoke("a", env.cid, body(model="actual-model"), session_bearer="test-session")
    assert not env.wires
    env.service.patch_tool("a", env.cid, TOOL_NAME, True)
    assert confirm(env, body(model="actual-model"))["status"] == "succeeded"


def test_owner_model_endpoint_is_readonly_whitelist_no_store(env):
    live_metadata(env)
    env.catalog["data"] += [
        {"id": "test-session", "modelType": "llm", "runtimeStatus": "available", "apiKey": "secret"},
        {"id": "evil\nID", "modelType": "llm", "runtimeStatus": "available"}]
    env.catalog["secret"] = "must not escape"
    with env.sessions() as db:
        row = db.get(MCPConnectionDB, env.cid)
        previous = (row.revision, row.tools_json, row.credential)
    root = "/api/mcp-connections/first-party/translation/models"
    assert env.client.get(root).status_code == 401
    response = env.client.get(root, headers={"Authorization": "Bearer test-session"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"providerId": "vinote-cloud-translation", "modelParameter": "model",
        "models": env.catalog["data"][:2], "defaultModel": None}
    assert env.calls == []
    with env.sessions() as db:
        row = db.get(MCPConnectionDB, env.cid)
        assert (row.revision, row.tools_json, row.credential) == previous
    from app.routers import mcp_connections as routes
    env.client.app.dependency_overrides[routes.principal] = lambda: ("b", None)
    count = len(env.wires)
    assert env.client.get(root, headers={"Authorization": "Bearer b-session"}).status_code == 404
    assert len(env.wires) == count


def test_model_endpoint_defaults_outage_does_not_hide_explicit_choices(env, monkeypatch):
    live_metadata(env)
    def metadata(path, bearer, deadline, payload=None):
        if path == "/v1/models":
            return env.catalog
        raise provider.ProviderFailure("provider_unavailable")
    monkeypatch.setattr(provider, "provider_json", metadata)
    result = provider.model_options("a", "test-session")
    assert result["defaultModel"] is None and result["models"] == env.catalog["data"][:2]
    assert env.calls == []


def test_model_endpoint_cookie_clients_proxy_current_identity(env, monkeypatch):
    from app.routers import mcp_connections as routes
    calls = []
    env.client.app.dependency_overrides[routes.principal] = lambda: ("a", "local-user")
    def proxy(identity, method, path):
        calls.append((identity, method, path))
        return True, {"models": [], "defaultModel": None}
    monkeypatch.setattr(routes, "proxy_integration", proxy)
    response = env.client.get("/api/mcp-connections/first-party/translation/models")
    assert response.status_code == 200 and calls == [(("a", "local-user"), "GET",
        "/api/mcp-connections/first-party/translation/models")]
    assert not env.wires


def test_model_catalog_failure_returns_no_provider_body_or_credentials(env, monkeypatch):
    def invalid(path, bearer, deadline, payload=None):
        return {"data": {"token": bearer}, "error": "private provider details"}
    monkeypatch.setattr(provider, "provider_json", invalid)
    response = env.client.get("/api/mcp-connections/first-party/translation/models",
        headers={"Authorization": "Bearer test-session"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "invalid_model_catalog"
    assert "test-session" not in response.text and "private provider details" not in response.text
    assert not env.calls


def test_normal_remote_does_not_receive_session(env, monkeypatch):
    captured = []
    class Remote:
        def __init__(self, url, token="", deadline=None):
            captured.append((url, token))
        def discover(self): return [copy.deepcopy(TOOL)]
    monkeypatch.setattr(mcp, "StreamableHTTPClient", Remote)
    cid = env.service.create("a", {"name": "Remote", "url": "https://remote.example/mcp"})["id"]
    env.service.discover("a", cid, session_bearer="test-session")
    assert captured == [("https://remote.example/mcp", "")]


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(requests=[], timeouts=[], resolutions=[], shutdowns=[], timers=[],
                            chunks=[b'{"ok":true}'], status=200, encoding="identity", crash=False)

    def resolve(host, port, deadline):
        state.resolutions.append((host, port, deadline))
        return (2, 1, 6, "", ("8.8.8.8", port))

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds, self.callback, self.cancelled = seconds, callback, False
            state.timers.append(self)
        def start(self): pass
        def cancel(self): self.cancelled = True

    class Response:
        def __init__(self): self.status = state.status
        def getheader(self, name, default=None):
            if name == "Content-Encoding": return state.encoding
            if name == "Content-Type": return "application/json"
            return default
        def isclosed(self): return not state.chunks
        def read1(self, size):
            if state.crash: raise TimeoutError("sensitive transport exception")
            return state.chunks.pop(0)
        def close(self): pass

    class Connection:
        def __init__(self, host, port, address, deadline):
            self.sock = SimpleNamespace(settimeout=lambda seconds: state.timeouts.append(seconds),
                                        shutdown=lambda value: state.shutdowns.append(value))
        def connect(self): pass
        def request(self, method, path, body, headers): state.requests.append((method, path, body, headers))
        def getresponse(self): return Response()
        def close(self): pass

    monkeypatch.setattr(provider, "resolve_public", resolve)
    monkeypatch.setattr(provider, "PinnedHTTPSConnection", Connection)
    monkeypatch.setattr(provider.threading, "Timer", Timer)
    monkeypatch.setattr(provider.settings, "vilab_server_url", "https://cloud.example/cloud-prefix")
    return state


def test_provider_real_transport_path_session_bounded_reads_watchdog_no_retry(wire):
    deadline = time.monotonic() + 8
    result = ACTUAL_PROVIDER_JSON("/openai/v1/chat/completions", "memory-session", deadline, {"model": "real"})
    assert result == {"ok": True}
    assert len(wire.requests) == len(wire.resolutions) == 1
    method, path, data, headers = wire.requests[0]
    assert method == "POST" and path == "/cloud-prefix/openai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer memory-session" and json.loads(data) == {"model": "real"}
    assert headers["Accept-Encoding"] == "identity"
    assert 0 < wire.timers[0].seconds <= 8 and wire.timers[0].cancelled
    wire.timers[0].callback()
    assert wire.shutdowns and all(0 < value <= 8 for value in wire.timeouts)


@pytest.mark.parametrize("status,unknown", [(302, True), (400, False), (401, False),
                                          (403, False), (408, True), (429, False), (500, True), (503, True)])
def test_provider_http_failure_one_wire_request_no_error_body_or_redirect(wire, status, unknown):
    wire.status, wire.chunks = status, [b'private token error body']
    with pytest.raises(provider.ProviderFailure) as caught:
        ACTUAL_PROVIDER_JSON("/openai/v1/chat/completions", "session", time.monotonic() + 8, {"model": "real"})
    assert caught.value.unknown is unknown
    assert "private" not in str(caught.value) and len(wire.requests) == 1


def test_provider_post_interruption_unknown_preflight_interruption_failed(wire):
    wire.crash = True
    with pytest.raises(provider.ProviderFailure) as caught:
        ACTUAL_PROVIDER_JSON("/openai/v1/chat/completions", "session", time.monotonic() + 8, {"model": "real"})
    assert caught.value.unknown and len(wire.requests) == 1
    with pytest.raises(provider.ProviderFailure) as caught:
        ACTUAL_PROVIDER_JSON("/v1/models", "session", time.monotonic() + 8)
    assert not caught.value.unknown and len(wire.requests) == 2
    assert all(timer.cancelled for timer in wire.timers)


def test_provider_expired_deadline_never_sends(wire):
    with pytest.raises(provider.ProviderFailure) as caught:
        ACTUAL_PROVIDER_JSON("/openai/v1/chat/completions", "session", time.monotonic() - 1, {})
    assert not caught.value.unknown and wire.requests == []


@pytest.mark.parametrize("chunks,encoding", [([b'x' * (mcp.MAX_RESPONSE + 1)], "identity"),
                                             ([b'not-json'], "identity"), ([b'{}'], "gzip")])
def test_provider_unusable_response_not_success_and_no_retry(wire, chunks, encoding):
    wire.chunks, wire.encoding = chunks, encoding
    with pytest.raises(provider.ProviderFailure) as caught:
        ACTUAL_PROVIDER_JSON("/openai/v1/chat/completions", "session", time.monotonic() + 8, {})
    assert caught.value.unknown and len(wire.requests) == 1


def test_bridge_run_header_only_fixed_official_tools_call(wire, monkeypatch):
    # Exercise the actual transport, rather than the protocol integration fake.
    monkeypatch.setattr(mcp, "resolve_public", provider.resolve_public)
    monkeypatch.setattr(mcp, "PinnedHTTPSConnection", provider.PinnedHTTPSConnection)
    for url, method, expected in [(ENDPOINT, "tools/call", True),
                                  (ENDPOINT, "tools/list", False),
                                  ("https://remote.example/mcp", "tools/call", False)]:
        wire.chunks = [b'{"jsonrpc":"2.0","id":"request","result":{"content":[]}}']
        monkeypatch.setattr(mcp.uuid, "uuid4", lambda: "request")
        client = ACTUAL_STREAMABLE_CLIENT(url, "session")
        client.run_id = "original-run"
        client.rpc(method, {})
        assert ("X-VINote-MCP-Run-Id" in wire.requests[-1][3]) is expected
