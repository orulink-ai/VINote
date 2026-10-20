"""Offline contact selection and notification contracts; no provider writes.

Official evidence (read 2026-10-13):
https://open.feishu.cn/document/server-docs/contact-v3/user/search-users.md
https://open.feishu.cn/document/server-docs/docs/permission/permission-member/list.md
https://open.feishu.cn/document/server-docs/im-v1/message/create.md
"""
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from app.routers import feishu
from app.services import feishu_service as module
from test_feishu_delivery import service  # noqa: F401


@pytest.fixture
def contact_service(service, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("tests must never call Feishu")
    monkeypatch.setattr(module.httpx, "request", no_network)
    service.store_connection("a", {"access_token": "token", "refresh_token": "refresh",
                                   "expires_in": 7200, "scope": "contact:user:search docx:document"},
                             {"open_id": "ou_a", "name": "A", "tenant_key": "company"})
    monkeypatch.setattr(service, "check_destination", lambda owner, target: {
        **target, "can_attempt_create": True})
    return service


def selection(service, monkeypatch, open_id="ou_b", name="同名联系人"):
    def search(method, path, **kwargs):
        assert (method, path) == ("GET", "search/v1/user")
        assert kwargs["token"] == "token"
        return {"users": [{"open_id": open_id, "name": name}], "has_more": False}
    monkeypatch.setattr(service, "request", search)
    item = service.contacts("a", "同名")["items"][0]
    return {key: item[key] for key in ("open_id", "selection_token")}


def publish(service, chosen, **kwargs):
    return service.enqueue("a", "note", "标题", "冻结正文", contacts=[chosen],
                           operation_id="op", notify_self=False, groups=[], **kwargs)


def prepare_worker(service, monkeypatch, members):
    created, writes, messages = [], [], []
    monkeypatch.setattr(service, "create_at_destination", lambda *args: created.append(args) or
                        ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(service, "ensure_permission", lambda *args: {"status": "verified"})
    monkeypatch.setattr(service, "write_document", lambda *args: writes.append(args))
    def request(method, path, **kwargs):
        assert (method, path) == ("GET", "drive/v1/permissions/doc1/members")
        assert kwargs["params"] == {"type": "docx"}
        return {"items": members}
    monkeypatch.setattr(service, "request", request)
    monkeypatch.setattr(service, "send_message", lambda owner, target, job: messages.append(target) or "om_sent")
    return created, writes, messages


def test_search_is_one_user_page_and_minimal_fields(contact_service, monkeypatch):
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"users": [{"open_id": "ou_b", "name": "同名", "email": "private@example.com"},
                          {"open_id": "ou_c", "name": "同名"}],
                "has_more": True, "page_token": "next"}
    monkeypatch.setattr(contact_service, "request", request)
    result = contact_service.contacts("a", " 同名 ", 2, "previous")
    assert len(calls) == 1 and calls[0][:2] == ("GET", "search/v1/user")
    assert calls[0][2]["params"] == {"query": "同名", "page_size": 2, "page_token": "previous"}
    assert result["has_more"] is True and result["page_token"] == "next"
    assert result["reading_permission"] == result["bot_availability"] == "not_checked"
    assert [item["open_id"] for item in result["items"]] == ["ou_b", "ou_c"]
    assert all(set(item) == {"open_id", "name", "selection_token"} for item in result["items"])


@pytest.mark.parametrize("result", [{}, {"users": [], "has_more": True},
                                  {"users": None, "has_more": False},
                                  {"users": [{"name": "missing ID"}], "has_more": False}])
def test_malformed_search_is_not_an_empty_contact_list(contact_service, monkeypatch, result):
    monkeypatch.setattr(contact_service, "request", lambda *args, **kwargs: result)
    with pytest.raises(module.FeishuError) as error:
        contact_service.contacts("a", "姓名")
    assert error.value.code == "contacts_response_invalid"


def test_scope_denial_never_falls_back_to_bot(contact_service, monkeypatch):
    with module.session_scope() as db:
        row = db.get(module.FeishuConnectionDB, "a")
        tokens = json.loads(module._cipher().decrypt(row.tokens.encode()))
        tokens["scope"] = "docx:document"
        row.tokens = module._cipher().encrypt(json.dumps(tokens).encode()).decode()
    with pytest.raises(module.FeishuError) as error:
        contact_service.contacts("a", "姓名")
    assert error.value.status_code == 403 and error.value.code == "user_scope_missing"


@pytest.mark.parametrize("query,size", [(" ", 20), ("x" * 51, 20), ("姓名", 51), ("姓名", True)])
def test_invalid_search_never_calls_provider(contact_service, query, size):
    with pytest.raises(module.FeishuError) as error:
        contact_service.contacts("a", query, size)
    assert error.value.status_code == 422


@pytest.mark.parametrize("change", ["id", "token", "expired", "owner", "connection", "app", "tenant"])
def test_selection_cannot_be_forged_rebound_or_used_after_expiry(contact_service, monkeypatch, change):
    chosen = selection(contact_service, monkeypatch)
    owner = "a"
    if change == "id":
        chosen["open_id"] = "ou_c"
    elif change == "token":
        chosen["selection_token"] = "tampered"
    elif change == "expired":
        proof = module._cipher().decrypt(chosen["selection_token"].encode())
        chosen["selection_token"] = module._cipher().encrypt_at_time(proof, int(time.time()) - 901).decode()
    elif change == "owner":
        contact_service.store_connection("b", {"access_token": "other", "expires_in": 7200,
                                               "scope": "contact:user:search"},
                                        {"open_id": "ou_owner_b", "tenant_key": "company"})
        owner = "b"
    elif change == "connection":
        with module.session_scope() as db:
            row = db.get(module.FeishuConnectionDB, "a")
            prefs = json.loads(row.preferences)
            prefs["connection_id"] = "new-connection"
            row.preferences = json.dumps(prefs)
    elif change == "app":
        monkeypatch.setattr(module.settings, "feishu_app_id", "another-app")
    else:
        monkeypatch.setattr(module.settings, "feishu_tenant_key", "another-tenant")
    with pytest.raises(module.FeishuError) as error:
        contact_service.validate_contacts(owner, [chosen])
    assert error.value.status_code == 422


def test_recipients_frozen_and_operation_replay_never_revalidates_expired_selection(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    first = publish(contact_service, chosen)
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, first["id"])
        metadata = db.get(module.FeishuDeliveryDestinationDB, first["id"])
        assert row.content == "冻结正文"
        assert chosen["selection_token"] not in row.recipients + metadata.snapshot
        assert json.loads(metadata.snapshot)["contacts"] == [{"open_id": "ou_b", "name": "同名联系人"}]
    assert first["recipients"]["ou_b"]["name"] == "同名联系人"
    monkeypatch.setattr(contact_service, "validate_contacts", lambda *args: (_ for _ in ()).throw(AssertionError("replay")))
    again = publish(contact_service, chosen)
    assert again["id"] == first["id"] and again["_dispatch_required"] is False
    with pytest.raises(HTTPException) as error:
        publish(contact_service, {**chosen, "open_id": "ou_c"})
    assert error.value.status_code == 409


def test_connection_changed_before_commit_cannot_freeze_old_selection(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    validate = contact_service.validate_contacts
    def changed(*args):
        contacts = validate(*args)
        with module.session_scope() as db:
            row = db.get(module.FeishuConnectionDB, "a")
            prefs = json.loads(row.preferences)
            prefs["connection_id"] = "changed"
            row.preferences = json.dumps(prefs)
        return contacts
    monkeypatch.setattr(contact_service, "validate_contacts", changed)
    with pytest.raises(module.FeishuError) as error:
        publish(contact_service, chosen)
    assert error.value.code == "connection_changed"


def test_contact_publish_requires_explicit_operation_and_never_automatic(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    for kwargs in ({}, {"operation_id": "op", "automatic": True}):
        with pytest.raises(module.FeishuError) as error:
            contact_service.enqueue("a", "note", "标题", "正文", contacts=[chosen], **kwargs)
        assert error.value.code == "explicit_publish_required"


@pytest.mark.parametrize("members", [[], [{"member_type": "openchat", "member_id": "oc_group", "perm": "view"}],
                                     [{"member_type": "userid", "member_id": "ou_b", "perm": "edit"}]])
def test_missing_direct_access_does_not_grant_or_send(contact_service, monkeypatch, members):
    chosen = selection(contact_service, monkeypatch)
    job = publish(contact_service, chosen)
    created, _, messages = prepare_worker(contact_service, monkeypatch, members)
    contact_service.process("a", job["id"])
    result = contact_service.delivery_by_id("a", job["id"])
    recipient = result["recipients"]["ou_b"]
    assert len(created) == 1 and not messages
    assert result["document_url"] and recipient["status"] == "failed"
    assert recipient["error_code"] == "recipient_permission_unverified"
    assert recipient["reading_permission"]["status"] == "unverified"
    assert recipient["reading_permission"]["permission_changed"] is False


def test_verified_contact_sent_once_and_unknown_send_is_never_replayed(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    job = publish(contact_service, chosen)
    created, _, messages = prepare_worker(contact_service, monkeypatch, [
        {"member_type": "openid", "member_id": "ou_b", "perm": "view"}])
    def unknown(owner, target, job):
        messages.append(target)
        raise module.FeishuError("结果未知", 502, uncertain=True)
    monkeypatch.setattr(contact_service, "send_message", unknown)
    contact_service.process("a", job["id"])
    contact_service.process("a", job["id"])
    result = contact_service.delivery_by_id("a", job["id"])
    assert result["phase"] == "unknown" and len(created) == 1 and messages == ["ou_b"]
    assert result["recipients"]["ou_b"]["reading_permission"]["status"] == "verified"


def test_definite_retry_rechecks_access_and_keeps_original_document(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    job = publish(contact_service, chosen)
    members = []
    created, _, messages = prepare_worker(contact_service, monkeypatch, members)
    contact_service.process("a", job["id"])
    members.append({"member_type": "openid", "member_id": "ou_b", "perm": "edit"})
    contact_service.process("a", job["id"], ["ou_b"])
    contact_service.process("a", job["id"])
    assert len(created) == 1 and messages == ["ou_b"]
    result = contact_service.delivery_by_id("a", job["id"])
    assert result["status"] == "completed"
    assert result["recipients"]["ou_b"]["reading_permission"]["role"] == "edit"


def test_bot_link_contract_does_not_leak_body_and_uses_stable_uuid(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    result = publish(contact_service, chosen)
    with module.session_scope() as db:
        job = db.get(module.FeishuDeliveryDB, result["id"])
        job.document_id, job.document_url = "doc1", "https://company.feishu.cn/docx/doc1"
        db.flush()
        db.expunge(job)
    monkeypatch.setattr(contact_service, "bot_token", lambda: "bot-test-token")
    calls = []
    monkeypatch.setattr(contact_service, "request", lambda method, path, **kwargs:
                        calls.append((method, path, kwargs)) or {"message_id": "om_sent"})
    assert contact_service.send_message("a", "ou_b", job) == "om_sent"
    method, path, args = calls[0]
    assert (method, path) == ("POST", "im/v1/messages")
    assert args["token"] == "bot-test-token" and args["params"] == {"receive_id_type": "open_id"}
    assert args["body"]["receive_id"] == "ou_b"
    assert args["body"]["uuid"] == str(uuid.uuid5(uuid.NAMESPACE_URL, job.id + "ou_b"))
    card = json.loads(args["body"]["content"])
    assert "冻结正文" not in str(card)
    assert card["elements"][1]["actions"][0]["url"] == job.document_url


def test_auth_validation_and_contact_proxy_query(contact_service, monkeypatch):
    app = FastAPI()
    app.include_router(feishu.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/feishu/contacts?query=姓名").status_code == 401
    app.dependency_overrides[feishu.principal] = lambda: ("a", "local")
    calls = []
    monkeypatch.setattr(feishu, "proxy", lambda *args: calls.append(args) or
                        (True, {"items": [], "has_more": False, "page_token": ""}))
    result = client.get("/api/feishu/contacts", params={"query": "姓名 & x", "page_token": "a&b"})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert calls[0][1] == "GET" and "page_token=a%26b" in calls[0][2]
    assert client.get("/api/feishu/contacts?query=%20").status_code == 422
    assert client.get("/api/feishu/contacts?query=x&page_size=51").status_code == 422


def test_old_proxy_cannot_silently_drop_contact_selection(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    payload = feishu.Publish(note_key="note", title="标题", content="正文", operation_id="op", contacts=[chosen])
    calls = []
    monkeypatch.setattr(feishu, "proxy", lambda *args: calls.append(args) or (True, {"connected": True}))
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as error:
        feishu.publish(payload, tasks, ("a", "local"))
    assert error.value.status_code == 409 and error.value.detail["code"] == "CONTACT_PROTOCOL_UNAVAILABLE"
    assert len(calls) == 1 and calls[0][1:3] == ("GET", "/status") and not tasks.tasks
    assert "contact_selection_protocol" not in feishu.status(("a", "local"), Response())


def test_capability_is_support_not_permission_or_delivery_claim(contact_service):
    status = contact_service.status("a")
    assert status["contact_selection_protocol"] == 1
    assert status["capabilities"]["contact_search"] is True
    assert status["capabilities"]["organization_wide_sharing"] is False


def test_permission_read_failure_never_claims_contact_can_read(contact_service, monkeypatch):
    monkeypatch.setattr(contact_service, "request", lambda *args, **kwargs: {})
    with pytest.raises(module.FeishuError) as error:
        contact_service.contact_reading_permission("a", "ou_b", SimpleNamespace(document_id="doc1"))
    assert error.value.code == "recipient_permission_unverified"


def test_official_bot_availability_error_is_definite_and_sanitized(contact_service, monkeypatch):
    import httpx
    monkeypatch.setattr(module.httpx, "request", lambda *args, **kwargs:
                        httpx.Response(400, json={"code": 230013, "msg": "sensitive provider detail"}))
    with pytest.raises(module.FeishuError) as error:
        contact_service.request("POST", "im/v1/messages", token="test-token", body={})
    assert error.value.status_code == 403 and error.value.code == "recipient_unavailable"
    assert error.value.uncertain is False and "sensitive" not in error.value.detail


def test_modern_proxy_forwards_original_contact_body_once(contact_service, monkeypatch):
    from app.services import feishu_auto_runtime
    # This test isolates proxying; the device outbox guard has its own SQLite tests.
    monkeypatch.setattr(feishu_auto_runtime, 'guard_manual_publish', lambda *args: None)
    chosen = selection(contact_service, monkeypatch)
    payload = feishu.Publish(note_key="note", title="标题", content="正文", operation_id="op", contacts=[chosen])
    calls = []
    def proxy(*args):
        calls.append(args)
        return (True, {"contact_selection_protocol": 1} if args[1] == "GET" else {"id": "remote-job"})
    monkeypatch.setattr(feishu, "proxy", proxy)
    tasks = BackgroundTasks()
    assert feishu.publish(payload, tasks, ("a", "local")) == {"id": "remote-job"}
    assert len(calls) == 2 and calls[1][1:3] == ("POST", "/deliveries")
    assert calls[1][3]["contacts"] == [chosen] and not tasks.tasks


def test_frozen_contact_job_rejects_changed_app_before_any_write(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    job = publish(contact_service, chosen)
    created, writes, messages = prepare_worker(contact_service, monkeypatch, [])
    monkeypatch.setattr(module.settings, "feishu_app_id", "changed-app")
    contact_service.process("a", job["id"])
    assert not created and not writes and not messages
    assert contact_service.delivery_by_id("a", job["id"])["error_code"] == "connection_changed"
