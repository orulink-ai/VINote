"""Deterministic remote-MCP tests; all network operations are replaced with fakes.

Run serially with pytest tests/test_mcp_connections.py. No live provider required.
"""
import copy
import json
import socket
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.mcp_connections import ConnectionPatch, MCPConnectionDB, MCPRunDB
from app.services import mcp_connection_service as module


TOOL = {"name": "notes/write", "description": "Save selected text", "inputSchema": {
    "type": "object", "properties": {"text": {"type": "string"}, "password": {"type": "string"}}},
    "annotations": {"readOnlyHint": True}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mcp.db'}", connect_args={"check_same_thread": False})
    MCPConnectionDB.__table__.create(engine)
    MCPRunDB.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    monkeypatch.setattr(module, "session_scope", sessions)
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(module, "_cipher", lambda: cipher)
    state = SimpleNamespace(calls=[], tools=[copy.deepcopy(TOOL)], error=None, discoveries=0, before_call=None)

    class FakeClient:
        def __init__(self, url, token="", deadline=None):
            self.dispatched = False

        def discover(self):
            state.discoveries += 1
            return copy.deepcopy(state.tools)

        def call(self, name, arguments):
            self.dispatched = True
            state.calls.append((name, arguments))
            if state.before_call:
                state.before_call()
            if state.error:
                raise state.error
            return {"content": [{"type": "text", "text": "done"}], "api_key": "remote-secret"}

    monkeypatch.setattr(module, "StreamableHTTPClient", FakeClient)
    state.service = module.MCPConnectionService()
    state.sessions, state.cipher = sessions, cipher
    yield state
    engine.dispose()


def connection(env, owner="a", **overrides):
    row = env.service.create(owner, {"name": "MCP", "url": "https://mcp.example/tools", **overrides})
    env.service.discover(owner, row["id"])
    env.service.patch_tool(owner, row["id"], TOOL["name"], True)
    return row["id"]


def invocation(request_id="request-1", **overrides):
    return {"requestId": request_id, "toolName": TOOL["name"], "arguments": {"text": "selected"}, **overrides}


def confirm(env, connection_id, body=None):
    body = body or invocation()
    prepared = env.service.invoke("a", connection_id, body)
    body = {**body, "confirmed": True, "confirmationToken": prepared["confirmationToken"]}
    return body


def test_credentials_encrypted_and_owner_scoped(env):
    cid = connection(env, authType="token", token="test-secret-123")
    with env.sessions() as db:
        row = db.get(MCPConnectionDB, cid)
        assert row.credential != "test-secret-123"
        assert env.cipher.decrypt(row.credential.encode()) == b"test-secret-123"
    serialized = env.service.list_connections("a")
    assert serialized["connections"][0]["hasCredential"]
    assert "test-secret-123" not in json.dumps(serialized)
    assert env.service.list_connections("b") == {"connections": []}
    operations = [lambda: env.service.patch("b", cid, {"name": "stolen"}),
                  lambda: env.service.delete("b", cid), lambda: env.service.discover("b", cid),
                  lambda: env.service.tools("b", cid),
                  lambda: env.service.patch_tool("b", cid, TOOL["name"], True),
                  lambda: env.service.invoke("b", cid, invocation())]
    for operation in operations:
        with pytest.raises(HTTPException) as caught:
            operation()
        assert caught.value.status_code == 404


def test_readonly_claim_still_requires_two_step_confirmation(env):
    cid = connection(env)
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", cid, invocation(confirmed=True))
    assert caught.value.detail["code"] == "confirmation_required"
    pending = env.service.invoke("a", cid, invocation())
    assert pending["status"] == "awaiting_confirmation"
    assert env.calls == []
    assert env.service.tools("a", cid)["tools"][0]["requiresConfirmation"] is True
    assert env.service.tools("a", cid)["tools"][0]["inputSchema"]["properties"]["password"] == {"type": "string"}
    with pytest.raises(HTTPException):
        env.service.invoke("a", cid, invocation(confirmed=True, confirmationToken="wrong"))
    body = invocation(confirmed=True, confirmationToken=pending["confirmationToken"])
    done = env.service.invoke("a", cid, body)
    assert done["status"] == "succeeded"
    assert done["confirmationToken"] is None
    assert done["result"]["api_key"] == "[redacted]"
    assert env.service.invoke("a", cid, body)["id"] == done["id"]
    assert env.calls == [(TOOL["name"], {"text": "selected"})]


def test_request_id_binds_owner_connection_tool_and_full_arguments(env):
    cid = connection(env)
    original = env.service.invoke("a", cid, invocation())
    assert env.service.invoke("a", cid, invocation())["id"] == original["id"]
    for target, body in [(cid, invocation(arguments={"text": "different"})),
                         (cid, invocation(toolName="other")), ("other-id", invocation())]:
        with pytest.raises(HTTPException) as caught:
            env.service.invoke("a", target, body)
        assert caught.value.detail["code"] == "request_id_conflict"
    other = connection(env, "b")
    assert env.service.invoke("b", other, invocation())["id"] != original["id"]


def test_timeout_after_dispatch_unknown_never_replayed(env):
    cid = connection(env)
    body = confirm(env, cid)
    env.error = module.MCPTransportError("timeout", "MCP 请求超时", 504)
    result = env.service.invoke("a", cid, body)
    assert result["status"] == "unknown"
    assert env.service.invoke("a", cid, body)["status"] == "unknown"
    assert env.service.invoke("a", cid, invocation())["status"] == "unknown"
    assert len(env.calls) == 1
    assert env.service.runs("b")["runs"] == []


def test_duplicate_request_while_running_returns_existing_claim(env):
    cid = connection(env)
    body = confirm(env, cid)
    snapshots = []
    env.before_call = lambda: snapshots.append(env.service.invoke("a", cid, body))
    done = env.service.invoke("a", cid, body)
    assert done["status"] == "succeeded"
    assert snapshots[0]["status"] == "running"
    assert snapshots[0]["id"] == done["id"]
    assert len(env.calls) == 1


def test_changed_definition_disables_grants_and_blocks_execution(env):
    cid = connection(env)
    body = confirm(env, cid)
    env.tools[0]["description"] = "Changed behavior"
    result = env.service.invoke("a", cid, body)
    assert result["status"] == "failed"
    assert result["error"]["code"] == "tool_changed"
    assert not env.calls
    discovered = env.service.discover("a", cid)
    assert discovered["tools"][0]["enabled"] is False


def test_failure_before_dispatch_is_failed_and_does_not_call(env, monkeypatch):
    cid = connection(env)
    body = confirm(env, cid)

    def unavailable(self):
        raise module.MCPTransportError("unsafe_address", "非公网地址", 422)

    monkeypatch.setattr(module.StreamableHTTPClient, "discover", unavailable)
    result = env.service.invoke("a", cid, body)
    assert result["status"] == "failed"
    assert result["error"]["code"] == "unsafe_address"
    assert not env.calls


def test_complete_tool_error_is_failed_and_not_replayed(env, monkeypatch):
    cid = connection(env)
    body = confirm(env, cid)

    def failed_call(self, name, arguments):
        self.dispatched = True
        env.calls.append(name)
        return {"isError": True, "content": [{"type": "text", "text": "remote error"}]}

    monkeypatch.setattr(module.StreamableHTTPClient, "call", failed_call)
    result = env.service.invoke("a", cid, body)
    assert result["status"] == "failed"
    assert result["error"]["code"] == "tool_error"
    assert env.service.invoke("a", cid, body)["id"] == result["id"]
    assert len(env.calls) == 1


def test_discovery_preserves_unchanged_grants_and_disables_new_tools(env):
    cid = connection(env)
    env.tools.append({**copy.deepcopy(TOOL), "name": "new/tool"})
    tools = env.service.discover("a", cid)["tools"]
    assert tools[0]["enabled"]
    assert not tools[1]["enabled"]
    env.tools[0]["annotations"]["readOnlyHint"] = False
    assert not env.service.discover("a", cid)["tools"][0]["enabled"]


@pytest.mark.parametrize("change", [{"enabled": False}, {"url": "https://other.example/mcp"},
                                   {"authType": "token", "token": "new-secret"}])
def test_connection_changes_block_pending_confirmation(env, change):
    cid = connection(env)
    body = confirm(env, cid)
    env.service.patch("a", cid, change)
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", cid, body)
    assert caught.value.status_code == 409
    assert not env.calls


def test_stale_running_becomes_unknown_without_network(env):
    cid = connection(env)
    pending = env.service.invoke("a", cid, invocation())
    with env.sessions() as db:
        row = db.get(MCPRunDB, pending["id"])
        row.status, row.lease_until, row.active_owner = "running", 1, "a"
    result = env.service.invoke("a", cid, invocation(confirmed=True, confirmationToken="anything"))
    assert result["status"] == "unknown"
    assert result["error"]["code"] == "execution_interrupted"
    assert not env.calls
    with env.sessions() as db:
        assert db.get(MCPRunDB, pending["id"]).active_owner is None


def test_cross_process_active_owner_claim_blocks_second_run(env):
    cid = connection(env)
    pending = env.service.invoke("a", cid, invocation("active"))
    body = confirm(env, cid, invocation("second"))
    with env.sessions() as db:
        row = db.get(MCPRunDB, pending["id"])
        row.status, row.lease_until, row.active_owner = "running", time.time() + 120, "a"
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", cid, body)
    assert caught.value.status_code == 429
    assert not env.calls


def test_cancel_pending_only_and_deletion_retains_run_history(env):
    cid = connection(env, authType="token", token="secret")
    pending = env.service.invoke("a", cid, invocation())
    with pytest.raises(HTTPException) as caught:
        env.service.cancel("b", pending["id"])
    assert caught.value.status_code == 404
    assert env.service.cancel("a", pending["id"])["status"] == "cancelled"
    assert env.service.invoke("a", cid, invocation())["status"] == "cancelled"
    done = env.service.invoke("a", cid, confirm(env, cid, invocation("second")))
    with pytest.raises(HTTPException) as caught:
        env.service.cancel("a", done["id"])
    assert caught.value.detail["code"] == "cannot_cancel_remote"
    env.service.delete("a", cid)
    assert env.service.list_connections("a")["connections"] == []
    assert len(env.service.runs("a", cid)["runs"]) == 2
    with env.sessions() as db:
        assert db.get(MCPConnectionDB, cid).credential == ""


def test_expired_confirmation_and_argument_redaction(env):
    cid = connection(env, authType="token", token="test-credential")
    body = invocation(arguments={"password": "private", "text": "test-credential"})
    pending = env.service.invoke("a", cid, body)
    assert pending["arguments"] == {"password": "[redacted]", "text": "[redacted]"}
    with env.sessions() as db:
        db.get(MCPRunDB, pending["id"]).confirmation_expires = 1
    assert env.service.invoke("a", cid, body)["status"] == "failed"
    assert not env.calls


def test_argument_bound_and_nonfinite_json(env):
    cid = connection(env)
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", cid, invocation(arguments={"text": "x" * module.MAX_ARGUMENTS}))
    assert caught.value.status_code == 413
    with pytest.raises(HTTPException) as caught:
        env.service.invoke("a", cid, invocation(arguments={"value": float("nan")}))
    assert caught.value.status_code == 422


@pytest.mark.parametrize("url", ["http://example.com", "https://localhost/mcp", "https://127.0.0.1/mcp",
    "https://10.2.3.4/mcp", "https://169.254.169.254/", "https://[::1]/", "https://user:pass@example.com/",
    "https://example.com/?token=secret", "https://example.com/#fragment", "https://example.com\\@127.0.0.1/",
    "https://example.com/\r\nX:injected", "https://[::ffff:127.0.0.1]/", "https://[64:ff9b::7f00:1]/"])
def test_unsafe_urls_rejected_without_network(url):
    with pytest.raises(HTTPException):
        module.validate_url(url)


def test_dns_rejects_mixed_public_and_private_answers(monkeypatch):
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(module.MCPTransportError) as caught:
        module.resolve_public("mcp.example", 443, time.monotonic() + 3)
    assert caught.value.code == "unsafe_address"


def test_connection_pins_numeric_address_and_keeps_tls_hostname(monkeypatch):
    seen = []

    class FakeSocket:
        def settimeout(self, value):
            pass

        def connect(self, address):
            seen.append(("connect", address))

        def getpeername(self):
            return ("8.8.8.8", 443)

        def close(self):
            pass

    monkeypatch.setattr(module.socket, "socket", lambda *args: FakeSocket())
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *args: pytest.fail("Second DNS lookup"))
    conn = module.PinnedHTTPSConnection("mcp.example", 443,
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)), time.monotonic() + 5)
    conn._context = SimpleNamespace(wrap_socket=lambda sock, server_hostname:
                                   seen.append(("tls", server_hostname)) or sock)
    conn.connect()
    conn.close()
    assert seen == [("connect", ("8.8.8.8", 443)), ("tls", "mcp.example")]


class ResponseFake:
    def __init__(self, body=b"", status=200, headers=None, chunk_size=11):
        self.body, self.status, self.offset, self.chunk_size = body, status, 0, chunk_size
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        chunk = self.body[self.offset:self.offset + min(size, self.chunk_size)]
        self.offset += len(chunk)
        return chunk

    def isclosed(self):
        return self.offset >= len(self.body)

    def close(self):
        pass


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(requests=[], resolutions=[], responder=None)

    def resolve(host, port, deadline):
        state.resolutions.append((host, port))
        return (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))

    class FakeConnection:
        def __init__(self, host, port, address, deadline):
            self.sock = SimpleNamespace(settimeout=lambda value: None, shutdown=lambda value: None)

        def connect(self):
            pass

        def request(self, method, path, body, headers):
            self.payload = json.loads(body)
            state.requests.append((method, path, self.payload, headers.copy()))

        def getresponse(self):
            return state.responder(self.payload)

        def close(self):
            pass

    monkeypatch.setattr(module, "resolve_public", resolve)
    monkeypatch.setattr(module, "PinnedHTTPSConnection", FakeConnection)
    return state


def json_response(payload, result, **kwargs):
    return ResponseFake(json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}).encode(), **kwargs)


def test_streamable_http_initialize_pagination_sse_call_and_session(transport):
    def respond(payload):
        method = payload["method"]
        if method == "initialize":
            return json_response(payload, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
                                 headers={"Mcp-Session-Id": "session-123"})
        if method == "notifications/initialized":
            return ResponseFake(status=202)
        if method == "tools/list":
            result = {"tools": []} if payload["params"].get("cursor") else {"tools": [TOOL], "nextCursor": "page2"}
            return json_response(payload, result)
        message = {"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [{"type": "text", "text": "好"}]}}
        return ResponseFake((": heartbeat\r\n\r\ndata: " + json.dumps(message) + "\r\n\r\n").encode(),
                            headers={"Content-Type": "text/event-stream"}, chunk_size=3)

    transport.responder = respond
    client = module.StreamableHTTPClient("https://mcp.example/path", "sensitive-token")
    assert client.discover() == [TOOL]
    assert client.call(TOOL["name"], {"text": "explicit"})["content"][0]["text"] == "好"
    assert [item[2]["method"] for item in transport.requests] == [
        "initialize", "notifications/initialized", "tools/list", "tools/list", "tools/call"]
    assert len(transport.resolutions) == 5
    assert transport.requests[0][3]["Authorization"] == "Bearer sensitive-token"
    assert "Mcp-Session-Id" not in transport.requests[0][3]
    assert transport.requests[1][3]["Mcp-Session-Id"] == "session-123"
    assert transport.requests[-1][3]["MCP-Protocol-Version"] == "2025-06-18"
    assert transport.requests[-1][2]["params"] == {"name": TOOL["name"], "arguments": {"text": "explicit"}}


@pytest.mark.parametrize("response,code", [
    (ResponseFake(status=302, headers={"Location": "https://127.0.0.1/"}), "redirect_forbidden"),
    (ResponseFake(status=401), "authentication_failed"),
    (ResponseFake(b"x", headers={"Content-Length": str(module.MAX_RESPONSE + 1)}), "response_too_large"),
    (ResponseFake(b"not-json"), "invalid_response"),
    (ResponseFake(b"x", headers={"Content-Encoding": "gzip"}), "encoding_unsupported"),
    (ResponseFake(b"data: {}\n", headers={"Content-Type": "text/event-stream"}), "incomplete_response"),
])
def test_transport_failures_not_retried_or_redirected(transport, response, code):
    transport.responder = lambda _: response
    with pytest.raises(module.MCPTransportError) as caught:
        module.StreamableHTTPClient("https://mcp.example/mcp").rpc("tools/call", {})
    assert caught.value.code == code
    assert len(transport.requests) == 1


def test_streaming_response_size_cap_without_content_length(transport, monkeypatch):
    monkeypatch.setattr(module, "MAX_RESPONSE", 128)
    transport.responder = lambda _: ResponseFake(b"x" * 129)
    with pytest.raises(module.MCPTransportError) as caught:
        module.StreamableHTTPClient("https://mcp.example/mcp").rpc("tools/list")
    assert caught.value.code == "response_too_large"


def test_routes_share_principal_and_proxy_exact_contract(env, monkeypatch):
    from app.routers import mcp_connections as router_module

    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    app.dependency_overrides[router_module.principal] = lambda: ("a", "local-user")
    monkeypatch.setattr(router_module, "service", env.service)
    captured = []
    monkeypatch.setattr(router_module, "proxy_integration", lambda *args:
                        captured.append(args) or (False, None))
    with TestClient(app) as client:
        response = client.post("/api/mcp-connections", json={"name": "Remote", "url": "https://mcp.example/",
                                                         "authType": "token", "token": "actual-secret"})
        assert response.status_code == 201
        assert response.headers["cache-control"] == "no-store"
        assert "actual-secret" not in response.text
        assert captured[-1][0] == ("a", "local-user")
        assert captured[-1][2] == "/api/mcp-connections"
        assert captured[-1][3]["token"] == "actual-secret"
        cid = response.json()["id"]
        assert client.post(f"/api/mcp-connections/{cid}/discover").status_code == 200
        assert client.patch(f"/api/mcp-connections/{cid}/tools", json={"name": TOOL["name"], "enabled": True}).status_code == 200
        result = client.post(f"/api/mcp-connections/{cid}/invoke", json=invocation()).json()
        assert result["status"] == "awaiting_confirmation"
        assert client.get("/api/mcp-connections/capabilities").json()["oauth"] is False
        assert client.get("/api/mcp-connections/runs?limit=1").json()["runs"][0]["id"] == result["id"]
        direct = client.get("/api/mcp-connections/runs/by-request/request-1")
        assert direct.status_code == 200 and direct.json()["id"] == result["id"]
        assert direct.headers["cache-control"] == "no-store"
        assert captured[-1][2] == "/api/mcp-connections/runs/by-request/request-1"
        assert client.get(f"/api/mcp-connections/runs/{result['id']}").json()["id"] == result["id"]
        app.dependency_overrides[router_module.principal] = lambda: ("b", "other-user")
        assert client.get("/api/mcp-connections/runs/by-request/request-1").status_code == 404
        assert client.get(f"/api/mcp-connections/runs/{result['id']}").status_code == 404
        app.dependency_overrides[router_module.principal] = lambda: ("a", "local-user")
        assert client.patch(f"/api/mcp-connections/{cid}", json={"enabled": None}).status_code == 422
        assert client.post("/api/mcp-connections", json={"name": "OAuth", "url": "https://mcp.example/",
                                                       "authType": "oauth"}).status_code == 422
        invalid = client.post("/api/mcp-connections", json={"name": "Token", "url": "https://mcp.example/",
                                                          "authType": "token", "token": "secret" * 2000})
        assert invalid.status_code == 422
        assert "secret" not in invalid.text
        oversized = client.post("/api/mcp-connections", content=b" " * (512 * 1024 + 1))
        assert oversized.status_code == 413
        monkeypatch.setattr(router_module, "proxy_integration", lambda *args: (True, {"connections": []}))
        assert client.get("/api/mcp-connections").json() == {"connections": []}


def test_direct_request_lookup_recovers_old_run_beyond_first_page_without_network(env):
    cid = connection(env)
    original = env.service.invoke("a", cid, invocation("old-request"))
    for index in range(55):
        env.service.invoke("a", cid, invocation(f"newer-{index}"))
    assert original["id"] not in {run["id"] for run in env.service.runs("a")["runs"]}
    discoveries = env.discoveries
    assert env.service.get_run_by_request("a", "old-request")["id"] == original["id"]
    assert env.service.get_run("a", original["id"])["requestId"] == "old-request"
    assert not env.calls and env.discoveries == discoveries
    with pytest.raises(HTTPException) as error:
        env.service.get_run_by_request("a", "missing")
    assert error.value.status_code == 404


def test_direct_lookup_is_owner_scoped_even_for_same_request_id(env):
    cid_a, cid_b = connection(env), connection(env, owner="b")
    a = env.service.invoke("a", cid_a, invocation())
    b = env.service.invoke("b", cid_b, invocation())
    assert env.service.get_run_by_request("a", "request-1")["id"] == a["id"]
    assert env.service.get_run_by_request("b", "request-1")["id"] == b["id"]
    with pytest.raises(HTTPException) as error:
        env.service.get_run("b", a["id"])
    assert error.value.status_code == 404


@pytest.mark.parametrize("expired_status", ["running", "awaiting_confirmation"])
def test_direct_lookup_reports_expiry_without_mutating_or_dispatching(env, expired_status):
    cid = connection(env)
    pending = env.service.invoke("a", cid, invocation())
    with env.sessions() as db:
        row = db.get(MCPRunDB, pending["id"])
        row.status, row.lease_until, row.confirmation_expires = expired_status, 1, 1
    recovered = env.service.get_run_by_request("a", "request-1")
    assert recovered["status"] == ("unknown" if expired_status == "running" else "failed")
    if expired_status == "awaiting_confirmation":
        assert recovered["confirmationToken"] is None
    with env.sessions() as db:
        assert db.get(MCPRunDB, pending["id"]).status == expired_status
    assert not env.calls


def test_successful_run_remains_readable_after_connection_disabled(env):
    cid = connection(env)
    succeeded = env.service.invoke("a", cid, confirm(env, cid))
    env.service.patch("a", cid, {"enabled": False})
    calls, discoveries = len(env.calls), env.discoveries
    assert env.service.get_run_by_request("a", "request-1")["result"] == succeeded["result"]
    assert env.service.get_run("a", succeeded["id"])["status"] == "succeeded"
    assert len(env.calls) == calls and env.discoveries == discoveries


def test_patch_empty_or_null_fields_rejected():
    with pytest.raises(ValueError):
        ConnectionPatch()
    with pytest.raises(ValueError):
        ConnectionPatch(enabled=None)
