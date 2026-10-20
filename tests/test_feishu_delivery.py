from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.services import feishu_service as module


@pytest.mark.parametrize('mode', ['confirmed', 'grant_denied', 'readback_denied', 'membership_changed', 'message_unknown'])
def test_enhanced_group_contract_freezes_target_and_orders_permission_before_send(scoped_service, monkeypatch, mode):
    events = []
    monkeypatch.setattr(scoped_service, 'create_document', lambda *args: events.append('create') or ('doc1', 'https://company.feishu.cn/docx/doc1'))
    monkeypatch.setattr(scoped_service, 'write_document', lambda *args: events.append('write'))
    monkeypatch.setattr(scoped_service, 'ensure_permission', lambda *args: events.append('destination_permission') or {'status': 'verified'})
    readable = False
    def verify(owner, target, job):
        assert target == 'oc_group'
        events.append('readback')
        return readable
    def grant(owner, target, job):
        nonlocal readable
        assert target == 'oc_group'
        events.append('grant')
        if mode == 'grant_denied':
            raise module.FeishuError('权限不足', 403, code='permission_denied')
        readable = mode != 'readback_denied'
    def send(owner, target, job):
        assert target == 'oc_group' and readable
        events.append('send')
        if mode == 'message_unknown':
            raise module.FeishuError('通知结果未知', 502, uncertain=True)
        return 'confirmed-message'
    monkeypatch.setattr(scoped_service, 'verify_group_permission', verify)
    monkeypatch.setattr(scoped_service, 'grant_group', grant)
    monkeypatch.setattr(scoped_service, 'send_message', send)
    job = scoped_service.enqueue('a', 'group-contract', '纪要', '正文', notify_self=False,
                                 destination_config={'kind': 'personal'}, groups=['oc_group'])
    # The current catalog cannot substitute another chat for a frozen chosen ID.
    if mode == 'membership_changed':
        monkeypatch.setattr(scoped_service, 'groups', lambda owner: [{'chat_id': 'oc_new', 'name': '新群'}])
    scoped_service.process('a', job['id'])
    result = scoped_service.delivery_by_id('a', job['id'])
    assert set(result['recipients']) == {'oc_group'}
    assert events[:3] == ['create', 'destination_permission', 'write']
    if mode in ('confirmed', 'message_unknown'):
        assert events[3:] == ['readback', 'grant', 'readback', 'send']
    else:
        assert 'send' not in events
        assert result['recipients']['oc_group']['status'] == ('permission_unknown' if mode == 'readback_denied' else 'failed')
    if mode == 'message_unknown':
        assert result['phase'] == 'unknown'
        scoped_service.process('a', job['id'], ['oc_group'])
        assert events.count('send') == 1 and events.count('create') == 1
        assert scoped_service.delivery_by_id('a', job['id'])['phase'] == 'unknown'
    if mode == 'confirmed':
        assert result['recipients']['oc_group']['message_id'] == 'confirmed-message'
        assert result['status'] == 'completed'


@pytest.fixture
def service(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'feishu.db'}")
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db
    monkeypatch.setattr(module, "session_scope", sessions)
    monkeypatch.setattr(module.settings, "feishu_app_id", "app-test")
    monkeypatch.setattr(module.settings, "feishu_app_secret", "secret-test")
    monkeypatch.setattr(module.settings, "feishu_redirect_uri", "https://notes.example/api/feishu/callback")
    monkeypatch.setattr(module.settings, "feishu_tenant_key", "company")
    monkeypatch.setattr(module.settings, "feishu_doc_base_url", "https://company.feishu.cn")
    monkeypatch.setattr(module.settings, "model_profile_encryption_key", "test-key")
    client = module.FeishuService()
    client.store_connection("a", {"access_token": "token", "refresh_token": "refresh", "expires_in": 7200},
                            {"open_id": "ou_a", "name": "A", "tenant_key": "company"})
    monkeypatch.setattr(client, "groups", lambda owner: [{"chat_id": "oc_group", "name": "项目群"}])
    monkeypatch.setattr(client, "verify_group_permission", lambda *args: True)
    client.save_preferences("a", {"notify_self": True, "groups": ["oc_group"], "auto_publish": True,
                                  "automatic_delivery_consent": True})
    yield client
    engine.dispose()


@pytest.mark.parametrize('cached_grant', [False, True])
def test_legacy_group_never_trusts_grant_success_or_cached_permission(service, monkeypatch, cached_grant):
    sent = []
    monkeypatch.setattr(service, 'create_document', lambda *args: ('doc1', 'https://company.feishu.cn/docx/doc1'))
    monkeypatch.setattr(service, 'write_document', lambda *args: None)
    monkeypatch.setattr(service, 'verify_group_permission', lambda *args: False)
    monkeypatch.setattr(service, 'grant_group', lambda *args: None)
    monkeypatch.setattr(service, 'send_message', lambda owner, target, job: sent.append(target) or 'message')
    job = service.enqueue('a', 'legacy-grant', '纪要', '正文')
    with module.session_scope() as db:
        from app.db_models import FeishuDeliveryDB
        import json
        row = db.get(FeishuDeliveryDB, job['id'])
        recipients = json.loads(row.recipients)
        recipients['oc_group']['permission_granted'] = cached_grant
        row.recipients = json.dumps(recipients)
    service.process('a', job['id'])
    result = service.delivery_by_id('a', job['id'])
    assert 'oc_group' not in sent
    assert result['recipients']['oc_group']['error_code'] == 'permission_unknown'


def test_partial_delivery_retry_preserves_document_and_successful_self(service, monkeypatch):
    created, sent = [], []
    monkeypatch.setattr(service, "create_document", lambda owner, title: created.append(title) or ("doc-id", "https://example.feishu.cn/docx/doc-id"))
    monkeypatch.setattr(service, "write_document", lambda *args: None)
    monkeypatch.setattr(service, "grant_group", lambda *args: None)
    def send(owner, target, job):
        sent.append(target)
        if target == "oc_group" and sent.count(target) == 1:
            raise module.FeishuError("机器人无法发送到此群", 403)
        return "message-id"
    monkeypatch.setattr(service, "send_message", send)
    job = service.enqueue("a", "meeting", "纪要", "# 主题\n记录")
    service.process("a", job["id"])
    failed = service.delivery("a", "meeting")
    assert failed["status"] == "failed"
    assert failed["document_url"]
    assert failed["recipients"]["ou_a"]["status"] == "sent"
    service.process("a", job["id"])
    assert service.delivery("a", "meeting")["status"] == "completed"
    assert created == ["纪要"]
    assert sent == ["ou_a", "oc_group", "oc_group"]


def test_duplicate_enqueue_and_owner_isolation(service):
    first = service.enqueue("a", "meeting", "纪要", "text")
    second = service.enqueue("a", "meeting", "纪要", "text")
    assert first["id"] == second["id"]
    service.enqueue("a", "meeting", "纪要", "edited")
    assert service.enqueue("a", "meeting", "纪要", "text")["id"] == first["id"]
    assert service.delivery("b", "meeting") is None
    with pytest.raises(module.FeishuError):
        service.process("b", first["id"])


def test_private_sharing_receipt_does_not_claim_exclusive_effective_readers(service, monkeypatch):
    from types import SimpleNamespace

    def response(method, path, **kwargs):
        return {"permission_public": {"external_access_entity": "closed", "link_share_entity": "closed"}}

    monkeypatch.setattr(service, "request", response)
    permission = service.ensure_permission("a", SimpleNamespace(document_id="doc1"), {"permission_policy": "private"})
    assert permission["status"] == "verified"
    assert permission["access_scope"] == "external_and_link_sharing_closed"
    assert permission["verification_scope"] == "public_sharing_settings"
    assert permission["organization_policy_verified"] is False
    assert "继承权限" in permission["note"]


def test_oauth_state_is_single_use_and_wrong_company_rejected(service):
    from fastapi import HTTPException
    auth = service.authorize("a")
    import base64
    assert base64.b64decode(auth["qr_data_url"].split(',', 1)[1]).startswith(b'\x89PNG')
    assert auth["expires_at"] > __import__('time').time()
    assert service.consume_state(auth["state"]) == "a"
    with pytest.raises(HTTPException):
        service.consume_state(auth["state"])
    with pytest.raises(module.FeishuError):
        service.store_connection("a", {"access_token": "bad"}, {"tenant_key": "other", "open_id": "ou_other"})


def test_unknown_create_result_requires_reconciliation_before_retry(service, monkeypatch):
    calls = []
    def create(*args):
        calls.append(args)
        raise module.FeishuError("timeout", 502, uncertain=True)
    monkeypatch.setattr(service, "create_document", create)
    job = service.enqueue("a", "interrupted", "纪要", "text")
    service.process("a", job["id"])
    assert service.delivery("a", "interrupted")["needs_document_recovery"]
    service.process("a", job["id"])
    assert len(calls) == 1
    monkeypatch.setattr(service, "request", lambda method, path, **kwargs: {"document": {"title": "纪要"}} if path.endswith("/doc123") else {"items": []})
    with pytest.raises(module.FeishuError):
        service.recover_document("b", job["id"], "https://company.feishu.cn/docx/doc123")
    with pytest.raises(module.FeishuError):
        service.recover_document("a", job["id"], "https://other.feishu.cn/docx/doc123")
    recovered = service.recover_document("a", job["id"], "https://company.feishu.cn/docx/doc123")
    assert not recovered["needs_document_recovery"]
    monkeypatch.setattr(service, "write_document", lambda *args: None)
    monkeypatch.setattr(service, "grant_group", lambda *args: None)
    monkeypatch.setattr(service, "send_message", lambda *args: "message")
    service.process("a", job["id"])
    assert service.delivery("a", "interrupted")["status"] == "completed"
    assert len(calls) == 1


def test_interrupted_worker_becomes_retryable(service):
    job = service.enqueue("a", "crash", "纪要", "text")
    service.checkpoint("a", job["id"], status="processing", lease_until="1")
    assert service.delivery("a", "crash")["status"] == "failed"


def test_oauth_callback_query_is_removed_from_access_log():
    import logging
    from app.routers.feishu import OAuthAccessLogFilter
    record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("client", "GET", "/api/feishu/callback?code=secret&state=nonce", "1.1", 200), None)
    assert OAuthAccessLogFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "nonce" not in record.getMessage()


def test_document_unknown_batch_preserves_checkpoint_and_blocks_rewrite(service, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "create_document", lambda *args: ("doc123", "https://company.feishu.cn/docx/doc123"))
    monkeypatch.setattr(service, "grant_group", lambda *args: None)
    monkeypatch.setattr(service, "send_message", lambda *args: "message")
    def request(method, path, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise module.FeishuError("中断", 502, uncertain=True)
        return {}
    monkeypatch.setattr(service, "request", request)
    job = service.enqueue("a", "batches", "纪要", "# 主题\n- **确认行动**\n" + "\n".join(f"第{i}段" for i in range(65)))
    service.process("a", job["id"])
    assert service.delivery("a", "batches")["status"] == "failed"
    service.process("a", job["id"])
    assert service.delivery("a", "batches")["phase"] == "unknown"
    assert [call["body"]["index"] for call in calls] == [0, 50]
    assert calls[0]["body"]["children"][0]["block_type"] == 3
    bullet = calls[0]["body"]["children"][1]
    assert bullet["block_type"] == 12
    assert bullet["bullet"]["elements"][0]["text_run"]["text_element_style"]["bold"]


def test_shared_service_only_uses_verified_cloud_identity(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.routers import feishu
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer supplied-token")]})
    observed = []
    monkeypatch.setattr(feishu, "_request", lambda path, token: observed.append((path, token)) or {"id": "verified", "email_confirmed_at": "today"})
    assert feishu.principal(request) == (feishu.cloud_owner("verified"), None)
    assert observed == [("user", "supplied-token")]
    monkeypatch.setattr(feishu, "_request", lambda *args, **kwargs: {"id": "anonymous", "email_confirmed_at": "today", "is_anonymous": True})
    with pytest.raises(HTTPException):
        feishu.principal(request)


@pytest.fixture
def scoped_service(service, monkeypatch):
    """All new integration tests are mocked; never contact a real tenant."""
    service.store_connection("a", {
        "access_token": "token", "refresh_token": "refresh", "expires_in": 7200,
        "scope": "docx:document drive:drive wiki:wiki docs:permission.member:auth",
    }, {"open_id": "ou_a", "name": "A", "tenant_key": "company"})

    def reject_network(*args, **kwargs):
        raise AssertionError("Unexpected real Feishu HTTP request")

    monkeypatch.setattr(module.httpx, "request", reject_network)
    return service


def test_capabilities_require_actual_granted_scope(service, monkeypatch):
    assert not service.status("a")["capabilities"]["wiki"]
    assert not service.status("missing")["capabilities"]["personal"]
    monkeypatch.setattr(module.settings, "feishu_app_id", "")
    checked = service.check_destination("a", {"kind": "personal"})
    assert checked["can_create"] is False
    assert checked["can_attempt_create"] is False
    assert checked["error_code"] == "not_configured"


def test_folder_listing_preserves_provider_pagination_without_claiming_write(scoped_service, monkeypatch):
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"files": [{"type": "folder", "token": "fld1", "name": "共享目录"},
                          {"type": "docx", "token": "doc1"}], "has_more": True, "next_page_token": "next"}
    monkeypatch.setattr(scoped_service, "request", request)
    page = scoped_service.destinations("a", folder_token="fldParent", page_token="previous")
    assert page["page_token"] == "next" and page["has_more"]
    assert len(page["items"]) == 1
    assert page["items"][0]["can_create"] is False
    assert calls[0][1] == "drive/v1/files"
    assert calls[0][2]["params"]["page_token"] == "previous"


def test_folder_read_permission_is_not_creation_permission(scoped_service, monkeypatch):
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path))
        return {"name": "共享目录", "parentId": "123"}
    monkeypatch.setattr(scoped_service, "request", request)
    checked = scoped_service.check_destination("a", {"kind": "folder", "folder_token": "fld1"})
    assert checked["can_create"] is False
    assert checked["can_attempt_create"] is True
    assert checked["permission_state"] == "unknown"
    assert checked["path_complete"] is False
    assert calls == [("GET", "drive/explorer/v2/folder/fld1/meta")]


@pytest.mark.parametrize("allowed", [True, False])
def test_wiki_checks_node_edit_not_just_visibility(scoped_service, monkeypatch, allowed):
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("get_node"):
            return {"node": {"space_id": "space1", "node_token": "wiki1", "node_type": "origin", "title": "父节点"}}
        if path.endswith("members/auth"):
            return {"auth_result": allowed}
        if path.endswith("/public"):
            return {"permission_public": {"link_share_entity": "tenant_readable"}}
        return {"space": {"name": "团队知识库"}}
    monkeypatch.setattr(scoped_service, "request", request)
    checked = scoped_service.check_destination("a", {"kind": "wiki", "space_id": "space1", "node_token": "wiki1"})
    assert checked["can_create"] is allowed
    assert checked["path"] == ["团队知识库", "父节点"]
    assert calls[1][2]["params"] == {"type": "wiki", "action": "edit"}
    assert all(call[0] == "GET" for call in calls)


def test_wiki_creation_uses_obj_token_for_body_and_node_token_for_link(scoped_service, monkeypatch):
    calls = []
    monkeypatch.setattr(scoped_service, "check_destination", lambda *args: {"can_attempt_create": True})
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"node": {"obj_type": "docx", "obj_token": "doc123", "node_token": "wiki123"}}
    monkeypatch.setattr(scoped_service, "request", request)
    result = scoped_service.create_at_destination("a", "纪要", {"kind": "wiki", "space_id": "space1", "node_token": "parent"})
    assert result == ("doc123", "https://company.feishu.cn/wiki/wiki123")
    assert calls[0][1] == "wiki/v2/spaces/space1/nodes"
    assert calls[0][2]["body"] == {"obj_type": "docx", "node_type": "origin", "title": "纪要", "parent_node_token": "parent"}


def test_snapshot_survives_preference_changes_and_selected_revision_is_frozen(scoped_service, monkeypatch):
    save_workspace_fixture("a", "snapshot", "纪要", "原文")
    monkeypatch.setattr(scoped_service, "request", lambda *args, **kwargs: {"name": "共享目录"})
    scoped_service.save_preferences("a", {"notify_self": False, "groups": ["oc_group"], "auto_publish": False,
        "destination_config": {"kind": "folder", "folder_token": "fld1"}, "permission_policy": "inherit"})
    first = scoped_service.enqueue("a", "snapshot", "纪要", "原文", version_id="current-1", revision_id="1")
    duplicate = scoped_service.enqueue("a", "snapshot", "纪要", "原文", version_id="current-1", revision_id="1")
    assert duplicate["id"] == first["id"]
    scoped_service.save_preferences("a", {"notify_self": True, "groups": [], "auto_publish": False,
        "destination_config": {"kind": "personal"}, "permission_policy": "private"})
    saved = scoped_service.delivery("a", "snapshot")
    assert saved["destination"]["folder_token"] == "fld1"
    assert saved["version_id"] == "current-1" and saved["revision_id"] == "1"
    assert set(saved["recipients"]) == {"oc_group"}
    assert saved["content_revision"] == module.hashlib.sha256("纪要\n原文".encode()).hexdigest()
    save_workspace_fixture("a", "snapshot", "纪要", "修改", revision=2)
    assert scoped_service.enqueue("a", "snapshot", "纪要", "修改", version_id="current-2", revision_id="2")["id"] != first["id"]


def test_legacy_preference_save_does_not_reset_organization_target(scoped_service, monkeypatch):
    monkeypatch.setattr(scoped_service, "request", lambda *args, **kwargs: {"name": "共享目录"})
    scoped_service.save_preferences("a", {"notify_self": True, "groups": [], "auto_publish": False,
        "destination_config": {"kind": "folder", "folder_token": "fld1"}})
    saved = scoped_service.save_preferences("a", {"notify_self": False, "groups": [], "auto_publish": False})
    assert saved["destination_config"] == {"kind": "folder", "folder_token": "fld1"}
    assert saved["permission_policy"] == "inherit"


def test_permission_failure_retains_document_and_blocks_content_and_messages(scoped_service, monkeypatch):
    created, written, sent = [], [], []
    monkeypatch.setattr(scoped_service, "create_document", lambda *args: created.append(args) or ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(scoped_service, "write_document", lambda *args: written.append(args))
    monkeypatch.setattr(scoped_service, "send_message", lambda *args: sent.append(args))
    def deny(*args):
        raise module.FeishuError("组织策略限制", 403, code="policy_restricted")
    monkeypatch.setattr(scoped_service, "ensure_permission", deny)
    job = scoped_service.enqueue("a", "permission", "纪要", "text", destination_config={"kind": "personal"}, groups=[])
    scoped_service.process("a", job["id"])
    failed = scoped_service.delivery("a", "permission")
    assert failed["document_url"]
    assert failed["permission"]["status"] == "failed"
    assert failed["error_code"] == "policy_restricted"
    assert not written and not sent and len(created) == 1
    monkeypatch.setattr(scoped_service, "ensure_permission", lambda *args: {"status": "verified"})
    monkeypatch.setattr(scoped_service, "send_message", lambda *args: "message")
    scoped_service.process("a", job["id"])
    assert len(created) == 1
    assert scoped_service.delivery("a", "permission")["phase"] == "completed"


def test_explicit_no_recipients_publishes_document_without_bot(scoped_service, monkeypatch):
    monkeypatch.setattr(scoped_service, "create_document", lambda *args: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(scoped_service, "write_document", lambda *args: None)
    monkeypatch.setattr(scoped_service, "ensure_permission", lambda *args: {"status": "verified"})
    job = scoped_service.enqueue("a", "document-only", "纪要", "text", notify_self=False, groups=[])
    scoped_service.process("a", job["id"])
    assert scoped_service.delivery("a", "document-only")["phase"] == "completed"
    assert job["recipients"] == {}


def test_unknown_message_is_not_resent_on_retry(service, monkeypatch):
    sent = []
    monkeypatch.setattr(service, "create_document", lambda *args: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(service, "write_document", lambda *args: None)
    monkeypatch.setattr(service, "grant_group", lambda *args: None)
    def send(owner, target, job):
        sent.append(target)
        if target == "oc_group":
            raise module.FeishuError("结果未知", 502, uncertain=True)
        return "self-message"
    monkeypatch.setattr(service, "send_message", send)
    job = service.enqueue("a", "unknown-message", "纪要", "text")
    service.process("a", job["id"])
    service.process("a", job["id"], ["oc_group"])
    result = service.delivery("a", "unknown-message")
    assert result["phase"] == "unknown"
    assert result["recipients"]["ou_a"]["status"] == "sent"
    assert result["recipients"]["oc_group"]["status"] == "unknown"
    assert sent == ["ou_a", "oc_group"]


def test_selected_recipient_retry_preserves_success_and_rejects_new_target(service, monkeypatch):
    sent = []
    monkeypatch.setattr(service, "create_document", lambda *args: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(service, "write_document", lambda *args: None)
    monkeypatch.setattr(service, "grant_group", lambda *args: None)
    def send(owner, target, job):
        sent.append(target)
        if target == "oc_group" and sent.count(target) == 1:
            raise module.FeishuError("群暂时不可用", 403)
        return "message"
    monkeypatch.setattr(service, "send_message", send)
    job = service.enqueue("a", "selected", "纪要", "text")
    service.process("a", job["id"])
    with pytest.raises(module.FeishuError):
        service.process("a", job["id"], ["oc_unrelated"])
    service.process("a", job["id"], ["ou_a", "oc_group"])
    assert sent == ["ou_a", "oc_group", "oc_group"]


def test_disconnect_and_rebind_cannot_resume_previous_authorization(service, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "create_document", lambda *args: calls.append(args))
    job = service.enqueue("a", "disconnect", "纪要", "text")
    service.disconnect("a")
    service.store_connection("a", {"access_token": "new", "expires_in": 7200},
                             {"open_id": "ou_a", "tenant_key": "company"})
    service.process("a", job["id"])
    assert not calls
    assert service.delivery("a", "disconnect")["error_code"] == "connection_changed"


@pytest.mark.parametrize("http_status,provider_code,expected", [
    (403, 1770040, "permission_denied"), (400, 131006, "permission_denied"),
    (400, 1770039, "target_unavailable"), (403, 99991672, "app_scope_missing"),
    (403, 99991679, "user_scope_missing"), (400, 1063003, "policy_restricted"),
    (503, 1771005, "result_unknown"),
])
def test_provider_errors_are_distinct_and_do_not_leak_raw_messages(service, monkeypatch, http_status, provider_code, expected):
    monkeypatch.setattr(module.httpx, "request", lambda *args, **kwargs: module.httpx.Response(
        http_status, json={"code": provider_code, "msg": "sensitive-provider-detail"}))
    with pytest.raises(module.FeishuError) as caught:
        service.request("POST", "docx/v1/documents", token="token", body={"title": "test"})
    assert caught.value.code == expected
    assert "sensitive-provider-detail" not in caught.value.detail


def test_organization_private_policy_is_rejected_before_network(scoped_service):
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.enqueue("a", "invalid-policy", "纪要", "text",
                               destination_config={"kind": "folder", "folder_token": "fld1"}, permission_policy="private")
    assert caught.value.code == "unsupported_permission"


def test_private_permissions_are_read_back_before_success(scoped_service, monkeypatch):
    from types import SimpleNamespace
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        # Provider accepted PATCH but actual policy is still wider: fail closed.
        return {"permission_public": {"link_share_entity": "tenant_readable", "external_access_entity": "closed"}}
    monkeypatch.setattr(scoped_service, "request", request)
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.ensure_permission("a", SimpleNamespace(document_id="doc1"), {"permission_policy": "private"})
    assert caught.value.code == "permission_mismatch"
    assert [c[0] for c in calls] == ["PATCH", "GET"]
    assert calls[0][2]["body"]["link_share_entity"] == "closed"
    assert calls[0][2]["body"]["external_access_entity"] == "closed"


def test_group_permission_must_be_readable_before_notification(scoped_service, monkeypatch):
    sent = []
    monkeypatch.setattr(scoped_service, "create_document", lambda *args: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(scoped_service, "write_document", lambda *args: None)
    monkeypatch.setattr(scoped_service, "ensure_permission", lambda *args: {"status": "verified"})
    monkeypatch.setattr(scoped_service, "verify_group_permission", lambda *args: False)
    monkeypatch.setattr(scoped_service, "grant_group", lambda *args: None)
    monkeypatch.setattr(scoped_service, "send_message", lambda *args: sent.append(args))
    job = scoped_service.enqueue("a", "no-readable-group", "纪要", "text", notify_self=False, groups=["oc_group"])
    scoped_service.process("a", job["id"])
    result = scoped_service.delivery("a", "no-readable-group")
    assert not sent
    assert result["phase"] == "permission_unknown"
    assert result["recipients"]["oc_group"]["error_code"] == "permission_unknown"


def test_wiki_recovery_rejects_different_parent(scoped_service, monkeypatch):
    monkeypatch.setattr(scoped_service, "check_destination", lambda owner, value: {**value, "can_attempt_create": True})
    job = scoped_service.enqueue("a", "wiki-recovery", "纪要", "text",
        destination_config={"kind": "wiki", "space_id": "space1", "node_token": "parent1"}, groups=[])
    scoped_service.checkpoint("a", job["id"], document_id="__creating__", lease_until="0")
    monkeypatch.setattr(scoped_service, "request", lambda *args, **kwargs: {"node": {
        "space_id": "space1", "parent_node_token": "other", "node_type": "origin", "obj_type": "docx", "obj_token": "doc1"}})
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.recover_document("a", job["id"], "https://company.feishu.cn/wiki/wiki1")
    assert caught.value.code == "destination_mismatch"
    assert scoped_service.delivery("a", "wiki-recovery")["needs_document_recovery"]


def test_destination_routes_keep_auth_and_proxy_contract(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import feishu
    app = FastAPI()
    app.include_router(feishu.router, prefix="/api")
    calls = []
    monkeypatch.setattr(feishu, "proxy", lambda identity, method, path, body=None:
                        calls.append((identity, method, path, body)) or (True, {"items": [], "has_more": False, "page_token": ""}))
    def rejected():
        raise feishu.HTTPException(401, "auth required")
    app.dependency_overrides[feishu.principal] = rejected
    with TestClient(app) as client:
        assert client.get("/api/feishu/destinations?kind=wiki").status_code == 401
        assert not calls
        app.dependency_overrides[feishu.principal] = lambda: ("verified-owner", "local-user")
        assert client.get("/api/feishu/destinations?kind=wiki&space_id=space1&page_token=a%2Bb").status_code == 200
        assert "page_token=a%2Bb" in calls[-1][2]
        assert calls[-1][0] == ("verified-owner", "local-user")
        assert client.post("/api/feishu/destinations/check", json={"kind": "wiki", "space_id": "space1", "node_token": "parent"}).status_code == 200
        assert calls[-1][1:3] == ("POST", "/destinations/check")


def test_additive_metadata_table_does_not_alter_legacy_delivery_columns(tmp_path):
    from sqlalchemy import inspect
    from app.db_models import FeishuDeliveryDB
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        FeishuDeliveryDB.__table__.create(engine)
        original = inspect(engine).get_columns("feishu_deliveries")
        with Session(engine) as db, db.begin():
            db.add(FeishuDeliveryDB(id="legacy", owner="a", note_key="legacy", revision="revision", title="旧纪要", content="旧正文"))
        Base.metadata.create_all(engine)
        assert [c["name"] for c in inspect(engine).get_columns("feishu_deliveries")] == [c["name"] for c in original]
        assert "feishu_delivery_destinations" in inspect(engine).get_table_names()
        with Session(engine) as db:
            assert db.get(FeishuDeliveryDB, "legacy").content == "旧正文"
    finally:
        engine.dispose()


def save_workspace_fixture(owner, key, title="服务端标题", content="服务端正文", revision=1, deleted=False):
    from app.models.workspace import WorkspaceNoteDB, WorkspaceVersionDB
    with module.session_scope() as db:
        row = db.get(WorkspaceNoteDB, (owner, key))
        if not row:
            row = WorkspaceNoteDB(owner=owner, key=key)
            db.add(row)
        row.title, row.content, row.revision, row.deleted = title, content, revision, deleted
        db.add(WorkspaceVersionDB(owner=owner, note_key=key, id=f"current-{revision}", title=title, content=content))


def test_workspace_publish_reads_owner_bound_content_without_client_body(scoped_service):
    from app.db_models import FeishuDeliveryDB
    save_workspace_fixture("a", "shared-note")
    job = scoped_service.enqueue("a", "shared-note", version_id="current-1", revision_id="1", groups=[])
    assert job["content_source"]["kind"] == "workspace"
    assert job["content_source"]["verified"] is True
    assert job["revision_id"] == "1"
    with module.session_scope() as db:
        row = db.get(FeishuDeliveryDB, job["id"])
        assert row.title == "服务端标题" and row.content == "服务端正文"


def test_workspace_reference_does_not_fall_back_to_other_owner_or_local(scoped_service):
    save_workspace_fixture("b", "shared-note")
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.enqueue("a", "shared-note", "伪造标题", "伪造正文", version_id="current-1", revision_id="1")
    assert caught.value.code == "workspace_reference_not_found"
    assert scoped_service.delivery("a", "shared-note") is None


@pytest.mark.parametrize("version,revision,body,expected", [
    ("current-1", "1", "篡改正文", "workspace_content_mismatch"),
    ("missing", "1", "服务端正文", "workspace_reference_not_found"),
    ("current-1", "2", "服务端正文", "workspace_revision_conflict"),
    ("current-1", "2026-10-11T00:00:00Z", "服务端正文", "invalid_workspace_revision"),
    ("current-1", None, "服务端正文", "invalid_workspace_revision"),
])
def test_invalid_workspace_mapping_is_rejected_before_provider(scoped_service, version, revision, body, expected):
    save_workspace_fixture("a", "shared-note")
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.enqueue("a", "shared-note", "服务端标题", body, version_id=version, revision_id=revision)
    assert caught.value.code == expected


def test_workspace_historical_version_selection_is_owner_and_note_scoped(scoped_service):
    save_workspace_fixture("a", "history", content="旧正文")
    save_workspace_fixture("a", "history", content="新正文", revision=2)
    job = scoped_service.enqueue("a", "history", version_id="current-1", revision_id="2", groups=[])
    assert job["content_revision"] == module.hashlib.sha256("服务端标题\n旧正文".encode()).hexdigest()
    assert job["content_source"]["revision_semantics"] == "observed_workspace_revision"


def test_deleted_workspace_cannot_be_published_as_local_snapshot(scoped_service):
    save_workspace_fixture("a", "deleted", deleted=True)
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.enqueue("a", "deleted", "本地标题", "本地正文")
    assert caught.value.code == "workspace_deleted"


def test_legacy_local_snapshot_is_explicit_and_has_no_verified_version(service):
    job = service.enqueue("a", "not-synced", "标题", "正文")
    assert job["content_source"]["kind"] == "local_snapshot"
    assert job["content_source"]["verified"] is False
    assert job["version_id"] is None and job["revision_id"] is None


def test_confirmed_device_snapshot_ignores_retired_workspace_copy(scoped_service):
    from app.db_models import FeishuDeliveryDB
    save_workspace_fixture("a", "same-id", content="旧云端正文", deleted=True)
    job = scoped_service.enqueue(
        "a", "same-id", "当前标题", "当前正文", source_mode="local_snapshot",
        operation_id="frozen-device-operation", groups=[],
    )
    assert job["content_source"]["kind"] == "local_snapshot"
    assert job["content_source"]["explicit"] is True
    assert job["version_id"] is None and job["revision_id"] is None
    with module.session_scope() as db:
        saved = db.get(FeishuDeliveryDB, job["id"])
        assert (saved.title, saved.content) == ("当前标题", "当前正文")
    repeated = scoped_service.enqueue(
        "a", "same-id", "当前标题", "当前正文", source_mode="local_snapshot",
        operation_id="frozen-device-operation", groups=[],
    )
    assert repeated["id"] == job["id"]


def test_device_snapshot_requires_manual_confirmation_and_no_workspace_reference(scoped_service):
    with pytest.raises(module.FeishuError) as automatic:
        scoped_service.enqueue("a", "note", "标题", "正文", source_mode="local_snapshot", automatic=True)
    assert automatic.value.code == "explicit_publish_required"
    with pytest.raises(module.FeishuError) as reference:
        scoped_service.enqueue("a", "note", "标题", "正文", source_mode="local_snapshot", version_id="current-1")
    assert reference.value.code == "invalid_source_reference"


def test_legacy_synced_body_must_match_server_and_is_bound_to_revision(scoped_service):
    save_workspace_fixture("a", "already-synced")
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.enqueue("a", "already-synced", "服务端标题", "未保存编辑")
    assert caught.value.code == "workspace_content_mismatch"
    job = scoped_service.enqueue("a", "already-synced", "服务端标题", "服务端正文")
    assert job["content_source"]["verified"] is True
    assert job["version_id"] == "current-1"


def test_edit_during_destination_preflight_requires_reconfirmation(scoped_service, monkeypatch):
    save_workspace_fixture("a", "concurrent")
    def changed(owner, destination):
        save_workspace_fixture("a", "concurrent", content="另一个设备的新正文", revision=2)
        return {**destination, "can_attempt_create": True}
    monkeypatch.setattr(scoped_service, "check_destination", changed)
    with pytest.raises(module.FeishuError) as caught:
        scoped_service.enqueue("a", "concurrent", version_id="current-1", revision_id="1", groups=[])
    assert caught.value.code == "workspace_revision_conflict"
    assert scoped_service.delivery("a", "concurrent") is None


def test_workspace_retry_keeps_original_frozen_content_after_later_edit(scoped_service, monkeypatch):
    save_workspace_fixture("a", "frozen")
    job = scoped_service.enqueue("a", "frozen", version_id="current-1", revision_id="1", notify_self=False, groups=[])
    save_workspace_fixture("a", "frozen", content="稍后编辑", revision=2)
    written = []
    monkeypatch.setattr(scoped_service, "create_document", lambda *args: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(scoped_service, "ensure_permission", lambda *args: {"status": "verified"})
    monkeypatch.setattr(scoped_service, "write_document", lambda owner, row: written.append(row.content))
    scoped_service.process("a", job["id"])
    assert written == ["服务端正文"]
    assert scoped_service.delivery("a", "frozen")["revision_id"] == "1"


def test_pending_recovery_is_bounded_owner_scoped_and_skips_unknown(service):
    import json
    jobs = [service.enqueue("a", f"pending-{i}", "标题", "正文") for i in range(6)]
    service.checkpoint("a", jobs[1]["id"], document_id="__creating__", lease_until="0")
    service.checkpoint("a", jobs[2]["id"], status="processing", phase="writing", document_id="doc2", lease_until="0")
    service.checkpoint("a", jobs[3]["id"], status="processing", lease_until="0", recipients=json.dumps({"ou_a": {"status": "sending"}}))
    result = service.pending_recovery("a", 2)
    assert result["scheduled"] == [jobs[0]["id"], jobs[4]["id"]]
    assert set(result["needs_attention"]) == {jobs[i]["id"] for i in (1, 2, 3)}
    assert result["background_delivery"] is False
    with pytest.raises(module.FeishuError):
        service.pending_recovery("b")


def test_pending_recovery_does_not_revive_disconnected_consent(service):
    job = service.enqueue("a", "old-connection", "标题", "正文")
    service.disconnect("a")
    service.store_connection("a", {"access_token": "new", "expires_in": 7200}, {"open_id": "ou_a", "tenant_key": "company"})
    result = service.pending_recovery("a")
    assert not result["scheduled"]
    assert result["needs_attention"] == [job["id"]]
