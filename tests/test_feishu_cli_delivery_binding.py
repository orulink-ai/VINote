"""Frozen CLI dispatch and recovery contracts; all external I/O is forbidden."""
from contextlib import contextmanager
from contextvars import copy_context
from copy import deepcopy
import json
import subprocess
import threading
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.db_models import FeishuConnectionDB, FeishuDeliveryDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.feishu_meeting_wiki import FeishuMeetingWikiChildDB, FeishuMeetingWikiContainerDB
from app.services import feishu_auto_policy as policy
from app.services import feishu_cli as cli
from app.services import feishu_cli_service as module
from app.services import feishu_service as base
from app.services.cloud_account_service import _cipher
from app.services.feishu_cli_service import FeishuCLIService, USER
from app.services.feishu_service import FeishuError, _lock


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real CLI/network is forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(settings, "model_profile_encryption_key", "synthetic-test-key")
    engine = create_engine("sqlite:///" + (tmp_path / "delivery.db").as_posix(),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(module, "session_scope", scope)
    monkeypatch.setattr(base, "session_scope", scope)
    binding = dict(owner="alice", connection_id="synthetic-connection", sender_open_id="ou_alice",
                   app_id="cli_synthetic", tenant_key="synthetic-tenant")
    saved = policy.create(policy.spec(binding, {"kind": "personal"}, True, [], "private", []), True)
    with scope() as db:
        db.add(FeishuConnectionDB(owner="alice", open_id="ou_alice", tokens=_cipher().encrypt(json.dumps({
            "transport": "cli", "app_id": binding["app_id"], "tenant_key": binding["tenant_key"],
        }).encode()).decode(), preferences=json.dumps({
            "connection_id": binding["connection_id"], "auto_publish": True, "auto_policy": saved,
        })))
    snapshot = dict(open_id="ou_alice", connection_id=binding["connection_id"],
                    app_id=binding["app_id"], tenant_key=binding["tenant_key"],
                    automatic_policy_id=saved["id"], contact_selection_protocol=1,
                    destination={"kind": "personal"})
    ctx = SimpleNamespace(service=FeishuCLIService("alice"), scope=scope, snapshot=snapshot,
                          calls=[], verifications=[], on_verify=lambda: None,
                          response=lambda method, path, **kwargs: {})

    def verify(owner):
        assert owner == "alice"
        ctx.verifications.append(owner)
        ctx.on_verify()
        return USER

    def api(owner, method, path, **kwargs):
        assert owner == "alice"
        ctx.calls.append((method, path, deepcopy(kwargs)))
        return ctx.response(method, path, **kwargs)

    monkeypatch.setattr(ctx.service, "_verify_identity", verify)
    monkeypatch.setattr(cli, "api", api)
    yield ctx
    engine.dispose()


@contextmanager
def active(snapshot, owner="alice"):
    token = policy.active_delivery.set((owner, snapshot))
    try:
        yield
    finally:
        policy.active_delivery.reset(token)


@pytest.mark.parametrize("method,path", [("POST", "docx/v1/documents"),
    ("PATCH", "drive/v2/permissions/doc123/public"), ("POST", "wiki/v2/spaces/space/nodes"),
    ("POST", "im/v1/messages"), ("PUT", "drive/v1/files/doc123"),
    ("DELETE", "drive/v1/files/doc123"), ("post", "docx/v1/documents")])
def test_mutation_checks_original_snapshot_not_current_configuration(delivery, method, path):
    frozen = {**delivery.snapshot, "connection_id": "revoked-original-connection"}
    with active(frozen), pytest.raises(FeishuError) as error:
        delivery.service.request(method, path, token=USER)
    assert error.value.code == "connection_changed"
    assert delivery.calls == []


@pytest.mark.parametrize("field,value", [("open_id", "ou_previous"), ("app_id", "cli_previous"),
    ("tenant_key", "previous-tenant"), ("automatic_policy_id", "previous-policy")])
def test_old_identity_or_policy_never_dispatches(delivery, field, value):
    with active({**delivery.snapshot, field: value}), pytest.raises(FeishuError):
        delivery.service.request("POST", "im/v1/messages", token=USER)
    assert not delivery.calls


def test_active_execution_cannot_use_another_service_owner(delivery):
    with active(delivery.snapshot, "bob"), pytest.raises(FeishuError):
        delivery.service.request("POST", "docx/v1/documents", token=USER)
    assert not delivery.calls and not delivery.verifications


@pytest.mark.parametrize("change", ["reconnect", "revoke"])
def test_identity_verification_cannot_replace_frozen_authority(delivery, change):
    def mutate():
        with delivery.scope() as db:
            row = db.get(FeishuConnectionDB, "alice")
            prefs = json.loads(row.preferences)
            if change == "reconnect":
                prefs["connection_id"] = "new-connection"
            else:
                prefs["auto_publish"] = False
            row.preferences = json.dumps(prefs)
    delivery.on_verify = mutate
    with active(delivery.snapshot), pytest.raises(FeishuError):
        delivery.service.request("POST", "docx/v1/documents", token=USER)
    assert not delivery.calls


def test_original_snapshot_and_owner_lock_cover_actual_dispatch(delivery, monkeypatch):
    checked, entered, release, revoking, revoked = (threading.Event() for _ in range(5))
    observed, failures = [], []
    original = delivery.service.assert_delivery_connection

    def check(owner, snapshot):
        assert snapshot is delivery.snapshot
        original(owner, snapshot)
        checked.set()

    def dispatch(*args, **kwargs):
        assert checked.is_set()
        entered.set()
        assert release.wait(3)
        observed.append(revoked.is_set())
        return {"document": {"document_id": "doc123"}}

    def revoke():
        revoking.set()
        with _lock("alice"), delivery.scope() as db:
            row = db.get(FeishuConnectionDB, "alice")
            prefs = json.loads(row.preferences)
            prefs["auto_publish"] = False
            row.preferences = json.dumps(prefs)
        revoked.set()

    def write():
        try:
            delivery.service.request("POST", "docx/v1/documents", token=USER)
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(delivery.service, "assert_delivery_connection", check)
    delivery.response = dispatch
    with active(delivery.snapshot):
        context = copy_context()
    writer = threading.Thread(target=context.run, args=(write,))
    revoker = threading.Thread(target=revoke)
    writer.start()
    try:
        assert entered.wait(3)
        revoker.start()
        assert revoking.wait(3)
        assert not revoked.wait(.1)
    finally:
        release.set()
        writer.join(3)
        if revoker.ident is not None:
            revoker.join(3)
    assert not writer.is_alive() and not revoker.is_alive()
    assert failures == [] and observed == [False] and revoked.is_set()
    with active(delivery.snapshot), pytest.raises(FeishuError):
        delivery.service.request("POST", "im/v1/messages", token=USER)
    assert len(delivery.calls) == 1


def test_valid_manual_write_and_read_only_recovery_still_work(delivery):
    delivery.service.request("POST", "docx/v1/documents", token=USER, body={"title": "合成纪要"})
    with active({**delivery.snapshot, "connection_id": "revoked"}):
        delivery.service.request("GET", "docx/v1/documents/doc123", token=USER)
    assert [c[0] for c in delivery.calls] == ["POST", "GET"]
    assert delivery.calls[0][2]["credential_identity"] == {
        "app_id": "cli_synthetic", "open_id": "ou_alice"}
    with pytest.raises(FeishuError):
        delivery.service.request("POST", "im/v1/messages", token="unverified")
    assert len(delivery.calls) == 2


def recovery_job(delivery, *, snapshot=None, owner="alice", document_id="__creating__", lease="0"):
    with delivery.scope() as db:
        db.add(FeishuDeliveryDB(id="synthetic-job", owner=owner, note_key="synthetic-note", revision="r1",
            title="合成纪要", content="冻结正文", status="failed", document_id=document_id, lease_until=lease))
        db.add(FeishuDeliveryDestinationDB(delivery_id="synthetic-job",
            snapshot=json.dumps(snapshot if snapshot is not None else delivery.snapshot)))


@pytest.mark.parametrize("explicit_session", [True, False])
def test_cli_receipt_only_overrides_execution_location(delivery, explicit_session):
    recovery_job(delivery)
    with delivery.scope() as db:
        row = db.get(FeishuDeliveryDB, "synthetic-job")
        original = base.FeishuService.serialize(delivery.service, row, db=db)
        result = delivery.service.serialize(row, db=db if explicit_session else None)
    assert original["execution_location"] == "server"
    assert result == {**original, "execution_location": "device"}
    assert not delivery.calls and not delivery.verifications


def recovery_response(method, path, **kwargs):
    assert method == "GET" and path.startswith(("docx/", "drive/", "wiki/"))
    if path.endswith("/children"):
        return {"items": [], "has_more": False}
    if path == "drive/v1/files":
        return {"files": [{"token": "doc123", "type": "docx"}], "has_more": False}
    if path == "wiki/v2/spaces/get_node":
        return {"node": {"space_id": "space1", "parent_node_token": "parent1", "obj_type": "docx",
                         "node_type": "origin", "obj_token": "doc123", "node_token": "node123"}}
    return {"document": {"title": "合成纪要"}}


@pytest.mark.parametrize("host", ["tenant.feishu.cn", "www.feishu.cn", "tenant.department.feishu.cn"])
def test_tenant_recovery_uses_only_fixed_cli_api_and_base_checks(delivery, host):
    recovery_job(delivery)
    delivery.response = recovery_response
    result = delivery.service.recover_document("alice", "synthetic-job",
        f"https://{host}/docx/doc123?from=copylink#section")
    assert result["document_url"] == "https://www.feishu.cn/docx/doc123"
    assert result["needs_document_recovery"] is False
    assert [c[1] for c in delivery.calls] == ["docx/v1/documents/doc123",
        "docx/v1/documents/doc123/blocks/doc123/children"]
    assert all("https:" not in repr(c) and host not in repr(c) for c in delivery.calls)


@pytest.mark.parametrize("url", ["http://tenant.feishu.cn/docx/doc123", "https://feishu.cn/docx/doc123",
    "https://tenant.feishu.cn.evil.invalid/docx/doc123", "https://evil.invalid/docx/doc123",
    "https://user@tenant.feishu.cn/docx/doc123", "https://@tenant.feishu.cn/docx/doc123",
    "https://tenant.feishu.cn:8443/docx/doc123", "https://tenant.feishu.cn:invalid/docx/doc123",
    "https://-tenant.feishu.cn/docx/doc123", "https://tenant..feishu.cn/docx/doc123",
    "https://tenant.feishu.cn/wiki/doc123/extra", "https://tenant.feishu.cn/docx/a%2Fb",
    "https://tenant.feishu.cn/docx/../doc123", "https://tenant.feishu.cn/docx/文档",
    "https://tenant.feishu.cn/docx/doc123/extra", "https://tenant.feishu.cn/docx/doc123\n",
    "https://tenant.feishu.cn\\evil.invalid/docx/doc123", "https://tenant.feishu.cn/docx/%64oc123",
    "https://tenant.feishu.cn/docx//doc123", "https://tenant.feishu.cn./docx/doc123"])
@pytest.mark.parametrize("kind", ["docx", "wiki"])
def test_recovery_rejects_unsafe_links_before_cli_or_database_mutation(delivery, url, kind):
    url = url.replace('/docx/', '/' + kind + '/')
    recovery_job(delivery)
    with pytest.raises(FeishuError):
        delivery.service.recover_document("alice", "synthetic-job", url)
    assert not delivery.calls and not delivery.verifications
    with delivery.scope() as db:
        assert db.get(FeishuDeliveryDB, "synthetic-job").document_id == "__creating__"


@pytest.mark.parametrize("case", ["owner", "service_owner", "snapshot", "title", "body", "more",
    "folder", "wiki", "lease", "already_bound"])
def test_tenant_recovery_cannot_bypass_original_recovery_gates(delivery, case):
    snapshot = deepcopy(delivery.snapshot)
    if case == "snapshot":
        snapshot["connection_id"] = "old-connection"
    if case == "folder":
        snapshot["destination"] = {"kind": "folder", "folder_token": "frozenfolder"}
    if case == "wiki":
        snapshot["destination"] = {"kind": "wiki", "space_id": "space1", "node_token": "wrongparent"}
    recovery_job(delivery, snapshot=snapshot, owner="bob" if case == "owner" else "alice",
                 lease="99999999999" if case == "lease" else "0",
                 document_id="existingdoc" if case == "already_bound" else "__creating__")

    def response(method, path, **kwargs):
        result = recovery_response(method, path, **kwargs)
        if case == "title" and "document" in result:
            result["document"]["title"] = "不同纪要"
        if case == "body" and path.endswith("/children"):
            result["items"] = [{"block_id": "existing"}]
        if case == "more" and path.endswith("/children"):
            result["has_more"] = True
        if case == "folder" and path == "drive/v1/files":
            assert kwargs["params"]["folder_token"] == "frozenfolder"
            result["files"] = []
        return result

    delivery.response = response
    with pytest.raises(FeishuError):
        delivery.service.recover_document("bob" if case == "service_owner" else "alice",
            "synthetic-job", "https://tenant.feishu.cn/docx/doc123")
    with delivery.scope() as db:
        assert db.get(FeishuDeliveryDB, "synthetic-job").document_id == (
            "existingdoc" if case == "already_bound" else "__creating__")
    assert all(c[0] == "GET" for c in delivery.calls)


@pytest.mark.parametrize("destination", [{"kind": "folder", "folder_token": "frozenfolder"},
    {"kind": "wiki", "space_id": "space1", "node_token": "parent1"}])
def test_recovery_retains_matching_frozen_destination(delivery, destination):
    recovery_job(delivery, snapshot={**delivery.snapshot, "destination": destination})
    delivery.response = recovery_response
    result = delivery.service.recover_document("alice", "synthetic-job", "https://tenant.feishu.cn/docx/doc123")
    assert result["destination"] == destination and not result["needs_document_recovery"]
    assert all(c[0] == "GET" for c in delivery.calls)


def wiki_recovery_job(delivery, monkeypatch, *, grouped):
    from app.services import feishu_meeting_wiki as wiki

    root = {"kind": "wiki", "space_id": "space1", "node_token": "parent1"}
    snapshot = {**delivery.snapshot, "destination": root}
    if grouped:
        snapshot['group_meeting_versions'] = True
    recovery_job(delivery, snapshot=snapshot)
    monkeypatch.setattr(wiki, 'session_scope', delivery.scope)
    if grouped:
        with delivery.scope() as db:
            db.add(FeishuMeetingWikiContainerDB(scope_key='a' * 64, owner='alice',
                scope_json=json.dumps({'destination': root}), title='合成会议容器', state='confirmed',
                lease_id='synthetic-lease', lease_until=0, node_token='meetingParent',
                document_id='containerDoc', document_url='https://www.feishu.cn/wiki/meetingParent', error_code=''))
            db.add(FeishuMeetingWikiChildDB(delivery_id='synthetic-job', scope_key='a' * 64,
                snapshot='{}', summary_format='text:detailed', ordinal=2, title='文字｜V2'))
    parent = 'meetingParent' if grouped else 'parent1'
    title = '文字｜V2' if grouped else '合成纪要'

    def response(method, path, **kwargs):
        result = recovery_response(method, path, **kwargs)
        if path == 'wiki/v2/spaces/get_node':
            result['node']['parent_node_token'] = parent
        if 'document' in result:
            result['document']['title'] = title
        return result

    return root, response


@pytest.mark.parametrize('grouped', [False, True])
def test_wiki_link_recovery_preserves_kind_and_checks_actual_parent_without_fetching_tenant(delivery, monkeypatch, grouped):
    root, response = wiki_recovery_job(delivery, monkeypatch, grouped=grouped)
    delivery.response = response
    result = delivery.service.recover_document('alice', 'synthetic-job',
        'https://tenant.department.feishu.cn/wiki/node123?from=copylink#section')
    assert result['needs_document_recovery'] is False
    assert result['document_url'] == 'https://www.feishu.cn/wiki/node123'
    assert result['destination'] == root  # immutable root is not rewritten as the effective parent
    assert [call[1] for call in delivery.calls] == ['wiki/v2/spaces/get_node',
        'docx/v1/documents/doc123', 'docx/v1/documents/doc123/blocks/doc123/children']
    assert delivery.calls[0][2]['params'] == {'token': 'node123', 'obj_type': 'wiki'}
    assert all(call[0] == 'GET' and 'https:' not in repr(call)
               and 'tenant.department.feishu.cn' not in repr(call) for call in delivery.calls)


@pytest.mark.parametrize('damage', ['root_parent', 'space', 'shadow_node', 'wrong_title', 'body', 'more', 'connection'])
def test_grouped_wiki_recovery_keeps_all_base_checks_and_never_uses_root_as_effective_parent(delivery, monkeypatch, damage):
    _, original = wiki_recovery_job(delivery, monkeypatch, grouped=True)
    if damage == 'connection':
        with delivery.scope() as db:
            row = db.get(FeishuConnectionDB, 'alice')
            saved = json.loads(row.preferences); saved['connection_id'] = 'replacement'
            row.preferences = json.dumps(saved)

    def response(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if 'node' in result:
            if damage == 'root_parent': result['node']['parent_node_token'] = 'parent1'
            if damage == 'space': result['node']['space_id'] = 'otherSpace'
            if damage == 'shadow_node': result['node']['node_type'] = 'shortcut'
        if damage == 'wrong_title' and 'document' in result: result['document']['title'] = '合成纪要'
        if path.endswith('/children'):
            if damage == 'body': result['items'] = [{'block_id': 'existing'}]
            if damage == 'more': result['has_more'] = True
        return result

    delivery.response = response
    with pytest.raises(FeishuError):
        delivery.service.recover_document('alice', 'synthetic-job', 'https://tenant.feishu.cn/wiki/node123')
    with delivery.scope() as db:
        assert db.get(FeishuDeliveryDB, 'synthetic-job').document_id == '__creating__'
    assert all(call[0] == 'GET' for call in delivery.calls)


def test_private_permission_receipt_does_not_claim_organization_or_superior_policy(delivery):
    delivery.response = lambda *args, **kwargs: {"permission_public": {
        "external_access_entity": "closed", "link_share_entity": "closed"}}
    result = delivery.service.ensure_permission("alice", SimpleNamespace(document_id="doc123"),
                                               {"permission_policy": "private"})
    assert [c[0] for c in delivery.calls] == ["PATCH", "GET"]
    assert delivery.calls[0][2]["body"] == {"external_access_entity": "closed", "link_share_entity": "closed",
        "share_entity": "same_tenant", "manage_collaborator_entity": "collaborator_full_access"}
    assert result["verification_scope"] == "public_sharing_settings"
    assert result["organization_policy_verified"] is False and "上级" in result["note"]
