"""Recipient ACL checkpoints: synthetic accounts, temporary DB, no external I/O."""
import json
import time
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException, Response

from app.routers import feishu
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.services import feishu_service as module
from test_feishu_contacts import contact_service, selection  # noqa: F401
from test_feishu_delivery import service, scoped_service  # noqa: F401

POLICY = "grant_view_and_notify"


def contact_job(client, monkeypatch, policy=POLICY, operation="op"):
    chosen = selection(client, monkeypatch)
    options = {} if policy is None else {"recipient_access_policy": policy}
    return client.enqueue("a", "note", "title", "body", contacts=[chosen],
                          operation_id=operation, notify_self=False, groups=[], **options)


def worker(client, monkeypatch, *, role=None, outcome="ok"):
    events, members = [], []
    if role:
        members.append({"member_type": "openid", "member_id": "ou_b", "perm": role})
    monkeypatch.setattr(client, "create_at_destination", lambda *a: events.append("create") or
                        ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(client, "ensure_permission", lambda *a: {"status": "verified"})
    monkeypatch.setattr(client, "write_document", lambda *a: events.append("write"))
    monkeypatch.setattr(client, "send_message", lambda *a: events.append("send") or "om_test")

    def request(method, path, **kwargs):
        assert path == "drive/v1/permissions/doc1/members"
        events.append(method)
        if method == "GET":
            return {"items": list(members)}
        assert method == "POST"
        assert kwargs["params"] == {"type": "docx", "need_notification": "false"}
        assert kwargs["body"] == {"member_type": "openid", "member_id": "ou_b", "perm": "view"}
        saved = client.delivery("a", "note")
        assert saved["recipients"]["ou_b"]["reading_permission"]["status"] == "granting"
        if outcome == "denied":
            raise module.FeishuError("denied", 403)
        if outcome in ("ok", "timeout_granted"):
            members.append({"member_type": "openid", "member_id": "ou_b", "perm": "view"})
        if outcome.startswith("timeout"):
            raise module.FeishuError("synthetic timeout", 502, uncertain=True)
        return {"member": kwargs["body"]}

    monkeypatch.setattr(client, "request", request)
    return events, members


def test_new_contact_explicit_policy_grants_reads_back_then_sends(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch)
    contact_service.process("a", job["id"])
    assert events == ["create", "write", "GET", "POST", "GET", "send"]
    result = contact_service.delivery_by_id("a", job["id"])
    assert result["status"] == "completed"
    assert result["recipient_access_policy"] == POLICY


@pytest.mark.parametrize("role", ["view", "edit", "full_access"])
def test_existing_access_is_not_downgraded(contact_service, monkeypatch, role):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch, role=role)
    contact_service.process("a", job["id"])
    assert "POST" not in events and events[-1] == "send"


@pytest.mark.parametrize("outcome", ["timeout_absent", "timeout_granted"])
def test_unknown_grant_only_readback_and_explicit_continue(contact_service, monkeypatch, outcome):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch, outcome=outcome)
    contact_service.process("a", job["id"])
    assert contact_service.delivery_by_id("a", job["id"])["phase"] == "permission_unknown"
    original = list(events)
    contact_service.process("a", job["id"], ["ou_b"])
    assert events == original  # even direct worker entry cannot replay
    result = contact_service.verify_delivery_permissions("a", job["id"])
    assert events == original + ["GET"]  # no create/write/grant/send
    assert result["recipients"]["ou_b"]["status"] == (
        "pending" if outcome == "timeout_granted" else "permission_unknown")
    if outcome == "timeout_granted":
        contact_service.process("a", job["id"], ["ou_b"])
        assert events.count("POST") == 1 and events.count("send") == 1
    else:
        contact_service.process("a", job["id"], ["ou_b"])
        assert "send" not in events and events.count("POST") == 1


def test_old_frozen_contact_does_not_gain_authorization(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch, policy=None)
    events, _ = worker(contact_service, monkeypatch)
    contact_service.process("a", job["id"])
    assert "POST" not in events and "send" not in events


def test_policy_bound_to_operation_and_revision(contact_service, monkeypatch):
    old = contact_job(contact_service, monkeypatch, policy=None)
    with pytest.raises(HTTPException) as error:
        contact_job(contact_service, monkeypatch)
    assert error.value.status_code == 409
    new = contact_job(contact_service, monkeypatch, operation="new")
    assert new["id"] != old["id"]


def test_legacy_group_timeout_cannot_replay(scoped_service, monkeypatch):
    job = scoped_service.enqueue("a", "group", "title", "body", notify_self=False,
                                 groups=["oc_group"], destination_config={"kind": "personal"})
    grants = []
    monkeypatch.setattr(scoped_service, "create_document", lambda *a: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(scoped_service, "ensure_permission", lambda *a: {"status": "verified"})
    monkeypatch.setattr(scoped_service, "write_document", lambda *a: None)
    monkeypatch.setattr(scoped_service, "verify_group_permission", lambda *a: False)
    def grant(*args):
        grants.append(1)
        raise module.FeishuError("timeout", 502, uncertain=True)
    monkeypatch.setattr(scoped_service, "grant_group", grant)
    scoped_service.process("a", job["id"])
    scoped_service.process("a", job["id"], ["oc_group"])
    assert grants == [1]
    assert scoped_service.delivery_by_id("a", job["id"])["phase"] == "permission_unknown"


@pytest.mark.parametrize("status", [401, 429, 502, 503])
def test_destination_unavailable_is_not_permission_denied(scoped_service, monkeypatch, status):
    def unavailable(*a, **k):
        raise module.FeishuError("unavailable", status, uncertain=True)
    monkeypatch.setattr(scoped_service, "user_token", unavailable)
    with pytest.raises(module.FeishuError) as error:
        scoped_service.enqueue("a", "dest", "title", "body", destination_config={"kind": "personal"})
    assert error.value.status_code == status
    assert scoped_service.delivery("a", "dest") is None


def test_proxy_refuses_missing_new_protocol_before_post(monkeypatch):
    calls = []
    monkeypatch.setattr(feishu, "proxy", lambda *args: calls.append(args) or
                        (True, {"contact_selection_protocol": 1}))
    payload = feishu.Publish(note_key="note", title="title", content="body", operation_id="op",
                            recipient_access_policy=POLICY)
    with pytest.raises(HTTPException) as error:
        feishu.publish(payload, BackgroundTasks(), ("a", "local"))
    assert error.value.status_code == 409
    assert len(calls) == 1 and calls[0][1] == "GET"


def test_status_declares_protocol(contact_service):
    assert contact_service.status("a")["recipient_access_protocol"] == 1


@pytest.mark.parametrize("patch", [{"automatic": True}, {"operation_id": None},
                                  {"recipient_access_policy": "grant_edit"}])
def test_policy_requires_explicit_operation(service, patch):
    options = {"operation_id": "op", "recipient_access_policy": POLICY, **patch}
    with pytest.raises(module.FeishuError) as error:
        service.enqueue("a", "invalid", "title", "body", **options)
    assert error.value.status_code == 422
    assert service.delivery("a", "invalid") is None


def test_explicit_policy_never_inherits_unselected_preferences(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    job = contact_service.enqueue("a", "only-selected", "title", "body", contacts=[chosen],
                                  operation_id="op", recipient_access_policy=POLICY)
    assert set(job["recipients"]) == {"ou_b"}


@pytest.mark.parametrize("checkpoint_phase", ["before_grant", "after_grant"])
def test_checkpoint_failure_before_and_after_dispatch(contact_service, monkeypatch, checkpoint_phase):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch)
    checkpoint = contact_service.checkpoint
    def fail(owner, job_id, **patch):
        recipients = json.loads(patch.get("recipients", "{}"))
        reading = recipients.get("ou_b", {}).get("reading_permission", {})
        if ((checkpoint_phase == "before_grant" and reading.get("status") == "granting") or
                (checkpoint_phase == "after_grant" and reading.get("status") == "verified")):
            raise RuntimeError("synthetic persistence failure")
        return checkpoint(owner, job_id, **patch)
    monkeypatch.setattr(contact_service, "checkpoint", fail)
    contact_service.process("a", job["id"])
    assert events.count("POST") == (0 if checkpoint_phase == "before_grant" else 1)
    assert "send" not in events
    if checkpoint_phase == "after_grant":
        assert contact_service.delivery_by_id("a", job["id"])["phase"] == "permission_unknown"
        contact_service.process("a", job["id"])
        assert events.count("POST") == 1


def test_process_crash_leaves_granting_durable_and_no_replay(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch)
    request = contact_service.request
    def crash(method, *a, **kw):
        result = request(method, *a, **kw)
        if method == "POST":
            raise KeyboardInterrupt("synthetic worker death")
        return result
    monkeypatch.setattr(contact_service, "request", crash)
    with pytest.raises(KeyboardInterrupt):
        contact_service.process("a", job["id"])
    with module.session_scope() as db:
        db.get(module.FeishuDeliveryDB, job["id"]).lease_until = "0"
    assert contact_service.delivery_by_id("a", job["id"])["phase"] == "permission_unknown"
    contact_service.process("a", job["id"])
    assert events.count("POST") == 1
    result = contact_service.verify_delivery_permissions("a", job["id"])
    assert result["recipients"]["ou_b"]["status"] == "pending"
    assert "send" not in events


def test_post_grant_readback_outage_does_not_repeat_grant(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch)
    request = contact_service.request
    def outage(method, *a, **kw):
        if method == "GET" and "POST" in events:
            raise module.FeishuError("unavailable", 502, uncertain=True)
        return request(method, *a, **kw)
    monkeypatch.setattr(contact_service, "request", outage)
    contact_service.process("a", job["id"])
    assert contact_service.delivery_by_id("a", job["id"])["phase"] == "permission_unknown"
    result = contact_service.verify_delivery_permissions("a", job["id"])
    assert result["phase"] == "permission_unknown"
    contact_service.process("a", job["id"])
    assert events.count("POST") == 1 and "send" not in events


def test_definite_grant_denial_is_explicitly_retryable_on_same_doc(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch)
    request, attempts = contact_service.request, []
    def denied_once(method, *a, **kw):
        if method == "POST":
            attempts.append(1)
            if len(attempts) == 1:
                raise module.FeishuError("denied", 403)
        return request(method, *a, **kw)
    monkeypatch.setattr(contact_service, "request", denied_once)
    contact_service.process("a", job["id"])
    assert contact_service.delivery_by_id("a", job["id"])["phase"] == "partial_success"
    contact_service.process("a", job["id"], ["ou_b"])
    assert len(attempts) == 2 and events.count("create") == 1 and events.count("send") == 1


@pytest.mark.parametrize("mode", ["other_owner", "app_changed", "connection_changed", "active"])
def test_verification_identity_and_active_guards(contact_service, monkeypatch, mode):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch, outcome="timeout_granted")
    contact_service.process("a", job["id"])
    original = list(events)
    owner = "b" if mode == "other_owner" else "a"
    if mode == "app_changed":
        monkeypatch.setattr(module.settings, "feishu_app_id", "changed-app")
    elif mode == "connection_changed":
        contact_service.disconnect("a")
    elif mode == "active":
        with module.session_scope() as db:
            db.get(module.FeishuDeliveryDB, job["id"]).lease_until = str(time.time() + 300)
    with pytest.raises(HTTPException):
        contact_service.verify_delivery_permissions(owner, job["id"])
    assert events == original


def test_message_unknown_is_not_resolved_by_acl_verification(contact_service, monkeypatch):
    chosen = selection(contact_service, monkeypatch)
    job = contact_service.enqueue("a", "note", "title", "body", contacts=[chosen],
                                  operation_id="op", notify_self=True, groups=[], recipient_access_policy=POLICY)
    events, _ = worker(contact_service, monkeypatch, outcome="timeout_granted")
    def ambiguous_message(*a):
        events.append("send")
        raise module.FeishuError("timeout", 502, uncertain=True)
    monkeypatch.setattr(contact_service, "send_message", ambiguous_message)
    contact_service.process("a", job["id"])
    result = contact_service.verify_delivery_permissions("a", job["id"])
    assert result["phase"] == "unknown"
    assert result["recipients"]["ou_a"]["status"] == "unknown"
    assert result["recipients"]["ou_b"]["status"] == "pending"
    assert events.count("send") == 1 and events.count("POST") == 1


def test_unknown_body_receipt_not_cleared_by_acl_verification(contact_service, monkeypatch):
    from app.services import feishu_receipt_service as receipts
    job = contact_job(contact_service, monkeypatch)
    worker(contact_service, monkeypatch, outcome="timeout_granted")
    contact_service.process("a", job["id"])
    with module.session_scope() as db:
        receipts.begin_batch(db, "a", job["id"], 0, {"synthetic": "unknown"})
    result = contact_service.verify_delivery_permissions("a", job["id"])
    assert result["phase"] == "unknown"
    assert result["error_code"] == "write_unknown"


@pytest.mark.parametrize("code", ["write_unknown", "result_unknown", "interrupted"])
def test_legacy_unknown_body_marker_not_cleared_without_batch(contact_service, monkeypatch, code):
    job = contact_job(contact_service, monkeypatch)
    worker(contact_service, monkeypatch, outcome="timeout_granted")
    contact_service.process("a", job["id"])
    with module.session_scope() as db:
        metadata = db.get(FeishuDeliveryDestinationDB, job["id"])
        metadata.phase, metadata.error_code = "unknown", code
    result = contact_service.verify_delivery_permissions("a", job["id"])
    assert result["phase"] == "unknown"
    assert result["error_code"] == "write_unknown"


def test_verify_route_never_schedules_and_retry_rejects_permission_unknown(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch, outcome="timeout_granted")
    contact_service.process("a", job["id"])
    monkeypatch.setattr(feishu, "service", contact_service)
    monkeypatch.setattr(feishu, "session_scope", module.session_scope)
    monkeypatch.setattr(contact_service, "for_owner", lambda owner: contact_service)
    monkeypatch.setattr(feishu, "proxy", lambda *a: (False, None))
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as error:
        feishu.retry(job["id"], tasks, identity=("a", None))
    assert error.value.status_code == 409 and not tasks.tasks
    before = list(events)
    response = Response()
    result = feishu.verify_permissions(job["id"], response, ("a", None))
    assert response.headers["cache-control"] == "no-store"
    assert events == before + ["GET"] and result["phase"] == "partial_success"
    assert not tasks.tasks


def test_verify_proxy_preserves_exact_id_and_no_worker(monkeypatch):
    calls = []
    monkeypatch.setattr(feishu, "proxy", lambda *a: calls.append(a) or (True, {"id": "exact"}))
    assert feishu.verify_permissions("exact", Response(), ("a", "local")) == {"id": "exact"}
    assert calls == [(("a", "local"), "POST", "/deliveries/exact/verify-permissions", {})]


def test_old_contact_cannot_be_upgraded_during_verification(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch, policy=None)
    events, _ = worker(contact_service, monkeypatch)
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, job["id"])
        row.document_id = "doc1"
        recipients = json.loads(row.recipients)
        recipients["ou_b"]["status"] = "permission_unknown"
        row.recipients = json.dumps(recipients)
    with pytest.raises(HTTPException) as error:
        contact_service.verify_delivery_permissions("a", job["id"])
    assert error.value.status_code == 409 and not events


def test_notification_header_generic_for_self_and_contact(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    with module.session_scope() as db:
        row = db.get(module.FeishuDeliveryDB, job["id"])
        row.document_id, row.document_url = "doc1", "https://company.feishu.cn/docx/doc1"
        db.expunge(row)
    monkeypatch.setattr(contact_service, "bot_token", lambda: "synthetic")
    cards = []
    monkeypatch.setattr(contact_service, "request", lambda *a, **kw:
                        cards.append(json.loads(kw["body"]["content"])) or {"message_id": "om"})
    contact_service.send_message("a", "ou_a", row)
    contact_service.send_message("a", "ou_b", row)
    assert all(card["header"]["title"]["content"] == row.title for card in cards)
    assert all(row.content not in str(card) for card in cards if row.content)


def test_shared_typescript_fixture_matches_actual_unknown_delivery(contact_service, monkeypatch):
    contract = json.loads((Path(__file__).parent / "fixtures/feishu_recipient_access_contract.json").read_text())
    payload = feishu.Publish.model_validate(contract["publish"])
    assert payload.recipient_access_policy == POLICY
    assert contact_service.status("a")["recipient_access_protocol"] == contract["status"]["recipient_access_protocol"]
    job = contact_job(contact_service, monkeypatch)
    worker(contact_service, monkeypatch, outcome="timeout_absent")
    contact_service.process("a", job["id"])
    result = contact_service.delivery_by_id("a", job["id"])
    expected = contract["unknown_delivery"]
    for key in ("status", "phase", "error_code", "recipient_access_policy"):
        assert result[key] == expected[key]
    assert result["recipients"]["ou_b"]["status"] == expected["recipients"]["ou_b"]["status"]
    assert result["recipients"]["ou_b"]["reading_permission"]["status"] == "unknown"
    route = next(r for r in feishu.router.routes if r.path.endswith("/{job_id}/verify-permissions"))
    assert route.methods == {contract["verify_action"]["method"]}


@pytest.mark.parametrize("policy", [None, POLICY])
def test_actual_group_grant_is_view_journaled_and_read_back(scoped_service, monkeypatch, policy):
    options = {"recipient_access_policy": policy, "operation_id": "op"} if policy else {}
    job = scoped_service.enqueue("a", "group-http", "title", "body", notify_self=False,
                                 groups=["oc_group"], destination_config={"kind": "personal"}, **options)
    events, members = [], []
    monkeypatch.setattr(scoped_service, "create_document", lambda *a: ("doc1", "https://company.feishu.cn/docx/doc1"))
    monkeypatch.setattr(scoped_service, "ensure_permission", lambda *a: {"status": "verified"})
    monkeypatch.setattr(scoped_service, "write_document", lambda *a: None)
    monkeypatch.setattr(scoped_service, "send_message", lambda *a: events.append("send") or "om")
    def request(method, path, **kw):
        assert path == "drive/v1/permissions/doc1/members"
        events.append(method)
        if method == "GET":
            return {"items": list(members)}
        assert kw["body"] == {"member_type": "openchat", "member_id": "oc_group", "perm": "view"}
        assert kw["params"] == {"type": "docx", "need_notification": "false"}
        saved = scoped_service.delivery_by_id("a", job["id"])
        assert saved["recipients"]["oc_group"]["reading_permission"]["status"] == "granting"
        members.append(kw["body"])
        return {"member": kw["body"]}
    monkeypatch.setattr(scoped_service, "verify_group_permission", module.FeishuService.verify_group_permission.__get__(scoped_service))
    monkeypatch.setattr(scoped_service, "request", request)
    scoped_service.process("a", job["id"])
    assert events == ["GET", "POST", "GET", "send"]


def test_old_contact_snapshot_bytes_preserved(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch, policy=None)
    with module.session_scope() as db:
        frozen = db.get(FeishuDeliveryDestinationDB, job["id"]).snapshot
    worker(contact_service, monkeypatch)
    contact_service.process("a", job["id"])
    with module.session_scope() as db:
        assert db.get(FeishuDeliveryDestinationDB, job["id"]).snapshot == frozen


def test_unexpected_grant_exception_remains_unknown(contact_service, monkeypatch):
    job = contact_job(contact_service, monkeypatch)
    events, _ = worker(contact_service, monkeypatch)
    request = contact_service.request
    def fault(method, *a, **kw):
        if method == "POST":
            events.append("POST")
            raise RuntimeError("synthetic transport fault")
        return request(method, *a, **kw)
    monkeypatch.setattr(contact_service, "request", fault)
    contact_service.process("a", job["id"])
    contact_service.process("a", job["id"])
    assert contact_service.delivery_by_id("a", job["id"])["phase"] == "permission_unknown"
    assert events.count("POST") == 1 and "send" not in events
