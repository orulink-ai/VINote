"""CLI image hooks with real local journals and synthetic external actions."""
from contextlib import contextmanager
import json

import pytest

from app.db_models import FeishuConnectionDB, FeishuDeliveryDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.services import feishu_cli_service as module, feishu_service as base, feishu_markdown as markdown
from app.services import task_artifact_service
from app.services.feishu_cli_service import FeishuCLIService, USER
from app.services.feishu_service import FeishuError
from test_feishu_native_images import image_job  # noqa: F401


@pytest.fixture
def illustrated(image_job, monkeypatch):
    c = image_job
    service = FeishuCLIService("alice")
    monkeypatch.setattr(module, "session_scope", c.scope)
    monkeypatch.setattr(base, "session_scope", c.scope)
    monkeypatch.setattr(task_artifact_service, "TaskArtifactService", lambda: c.artifacts)
    monkeypatch.setattr(service, "_native_image_writer", lambda: c.writer)
    monkeypatch.setattr(service, "user_token", lambda owner: USER)
    monkeypatch.setattr(service, "assert_delivery_connection", lambda owner, snapshot: None)
    monkeypatch.setattr(service, "_check_automatic_delivery", lambda *a: None)
    from types import SimpleNamespace
    monkeypatch.setattr(FeishuCLIService, "config", property(lambda self: SimpleNamespace(
        feishu_app_id="cli_app", feishu_tenant_key="tenant")))
    c.grants = {"docx:document", "docs:document.media:upload", "docx:document.block:convert"}
    monkeypatch.setattr(service, "granted_scopes", lambda row: c.grants)
    c.snapshot["format_selection"] = markdown.format_selection(c.content)
    with c.scope() as db:
        db.get(FeishuDeliveryDestinationDB, c.jobid).snapshot = json.dumps(c.snapshot)
        db.add(FeishuConnectionDB(owner="alice", open_id="ou_sender", preferences='{"connection_id":"connection1"}'))
    # The real integration holds its owner lock; fake provider fixture verifies
    # every external call occurs inside the supplied context and durable claim.
    c.writer.guard = lambda owner, job, snapshot: None

    @contextmanager
    def dispatch(owner, job, snapshot):
        c.inside_dispatch = True
        try:
            yield
        finally:
            c.inside_dispatch = False

    c.writer.dispatch_context = dispatch
    checkpoints = []
    monkeypatch.setattr(service, "checkpoint", lambda owner, jobid, **kw: checkpoints.append(kw))
    c.service, c.checkpoints = service, checkpoints

    def job():
        with c.scope() as db:
            row = db.get(FeishuDeliveryDB, c.jobid)
            db.expunge(row)
            return row

    c.job = job
    return c


def test_image_preflight_before_create_freezes_source_without_external_writes(illustrated):
    c = illustrated
    with c.scope() as db:
        db.get(FeishuDeliveryDB, c.jobid).document_id = ""
    plan = c.service.prepare_native_body("alice", c.job())
    assert plan["preflight"] is True and c.writes == []
    with c.scope() as db:
        frozen = json.loads(db.get(FeishuDeliveryDestinationDB, c.jobid).snapshot)
    assert frozen["image_source_manifest"]["assets"][0]["sha256"]
    assert frozen["image_source_manifest"]["task_id"] == c.task


@pytest.mark.parametrize("permission,code", [("docs:document.media:upload", "image_upload_scope_missing"),
                                          ("docx:document", "user_scope_missing")])
def test_missing_grant_never_creates_writes_or_starts_authorization(illustrated, permission, code):
    c = illustrated
    c.grants.remove(permission)
    with pytest.raises(FeishuError) as error: c.service.prepare_native_body("alice", c.job())
    assert error.value.code == code and c.writes == []


def test_cli_image_write_uses_existing_receipts_and_reports_actual_verified_result(illustrated):
    c = illustrated
    result = c.service.write_document("alice", c.job())
    assert result["images_embedded"] is True
    assert c.writes == ["text", "create", "upload", "bind", "text"]
    assert c.checkpoints == [{"written_blocks": str(len(c.root))}]
    result = c.service.serialize(c.job())["formatting"]
    assert result["images_embedded"] is True and result["native_write_confirmed"] is True
    assert result["status"] == "written" and result["image_source_preserved"] is False


def test_unknown_image_step_is_not_serialized_as_complete_or_replayed(illustrated):
    c = illustrated
    c.fail = "upload"
    with pytest.raises(FeishuError): c.service.write_document("alice", c.job())
    original = list(c.writes)
    result = c.service.serialize(c.job())["formatting"]
    assert result["images_embedded"] is False and result["native_write_confirmed"] is False
    assert result["status"] == "partial"
    with pytest.raises(FeishuError): c.service.write_document("alice", c.job())
    assert c.writes == original and c.checkpoints == []


def test_unknown_document_creation_keeps_original_recovery_semantics(illustrated):
    c = illustrated
    with c.scope() as db: db.get(FeishuDeliveryDB, c.jobid).document_id = "__creating__"
    with pytest.raises(FeishuError) as error: c.service.prepare_native_body("alice", c.job())
    assert error.value.code == "create_unknown" and error.value.uncertain and c.writes == []


def test_changed_original_app_is_not_replaced_with_current_default(illustrated):
    c = illustrated
    with c.scope() as db:
        data = dict(c.snapshot)
        data.pop("app_id")
        db.get(FeishuDeliveryDestinationDB, c.jobid).snapshot = json.dumps(data)
    with pytest.raises(FeishuError) as error: c.service.prepare_native_body("alice", c.job())
    assert error.value.code == "connection_changed" and c.writes == []


def test_serialize_reuses_active_write_transaction_without_sql_writes_or_external_reads(illustrated, monkeypatch):
    from sqlalchemy import event, inspect
    c = illustrated
    c.service.write_document("alice", c.job())

    def forbidden(*a, **kw):
        raise AssertionError("Receipt serialization must only read the caller's session")

    monkeypatch.setattr(c.writer, "sessions", forbidden)
    monkeypatch.setattr(c.writer, "guard", forbidden)
    monkeypatch.setattr(c.writer, "request", forbidden)
    statements = []
    with c.scope() as db:
        row = db.get(FeishuDeliveryDB, c.jobid)
        row.error = "outer transaction write"
        db.flush()  # Hold SQLite writer lock; PostgreSQL also retains this transaction.
        row.error = "pending outer write"
        connection = db.connection()

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().upper())

        event.listen(connection, "before_cursor_execute", record)
        try:
            formatting = c.service.serialize(row, db=db)["formatting"]
            assert formatting["images_embedded"] is True
            assert db.is_modified(row) and inspect(row).session is db
        finally:
            event.remove(connection, "before_cursor_execute", record)
    assert statements and all(s.startswith(("SELECT", "PRAGMA")) for s in statements)


def test_bind_readback_unknown_never_resumes_image_write_or_marks_text_complete(illustrated):
    c = illustrated
    original_request = c.writer.request

    def missing_readback(owner, method, path, **kw):
        if method == "GET" and path.rsplit("/", 1)[-1].startswith("image"):
            raise TimeoutError("readback lost after acknowledged image binding")
        return original_request(owner, method, path, **kw)

    c.writer.request = missing_readback
    with pytest.raises(FeishuError) as error:
        c.service.write_document("alice", c.job())
    assert error.value.uncertain and c.writes == ["text", "create", "upload", "bind"]
    formatting = c.service.serialize(c.job())["formatting"]
    assert formatting["status"] == "partial" and formatting["images_embedded"] is False
    c.writer.request = original_request
    with pytest.raises(FeishuError): c.service.write_document("alice", c.job())
    assert c.writes == ["text", "create", "upload", "bind"] and c.checkpoints == []


def test_source_change_after_preflight_blocks_document_body_before_any_write(illustrated):
    from PIL import Image
    c = illustrated
    with c.scope() as db: db.get(FeishuDeliveryDB, c.jobid).document_id = ""
    c.service.prepare_native_body("alice", c.job())
    Image.new("RGB", (32, 24), "red").save(c.image)
    with c.scope() as db: db.get(FeishuDeliveryDB, c.jobid).document_id = "doc1"
    with pytest.raises(FeishuError) as error: c.service.write_document("alice", c.job())
    assert error.value.code == "image_source_changed" and c.writes == []


@pytest.mark.parametrize("app,tenant", [("cli_different", "tenant"), ("cli_app", "other_tenant")])
def test_each_image_dispatch_rechecks_original_app_and_tenant(illustrated, monkeypatch, app, tenant):
    from types import SimpleNamespace
    c = illustrated
    writer = FeishuCLIService._native_image_writer(c.service)
    monkeypatch.setattr(FeishuCLIService, "config", property(lambda self: SimpleNamespace(
        feishu_app_id=app, feishu_tenant_key=tenant)))
    with pytest.raises(FeishuError) as error:
        with writer.dispatch_context("alice", c.job(), c.snapshot):
            pytest.fail("Changed binding must not enter the external dispatch")
    assert error.value.code == "connection_changed" and c.writes == []


def test_process_preflights_images_before_creating_any_target(illustrated, monkeypatch):
    c = illustrated
    monkeypatch.setattr(c.service, "checkpoint", base.FeishuService.checkpoint.__get__(c.service))
    created = []
    monkeypatch.setattr(c.service, "create_document", lambda *a: created.append(a))
    with c.scope() as db: db.get(FeishuDeliveryDB, c.jobid).document_id = ""
    c.grants.remove("docs:document.media:upload")
    c.service.process("alice", c.jobid)
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, c.jobid)
        metadata = db.get(FeishuDeliveryDestinationDB, c.jobid)
        assert job.status == "failed" and job.document_id == ""
        assert metadata.error_code == "image_upload_scope_missing"
    assert created == [] and c.writes == []


def test_process_completes_only_after_native_image_readback_and_order(illustrated, monkeypatch):
    c = illustrated
    monkeypatch.setattr(c.service, "checkpoint", base.FeishuService.checkpoint.__get__(c.service))
    with c.scope() as db: db.get(FeishuDeliveryDB, c.jobid).document_id = ""
    created = []

    def create(owner, title):
        with c.scope() as db:
            job = db.get(FeishuDeliveryDB, c.jobid)
            snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, c.jobid).snapshot)
            assert job.document_id == "__creating__" and snapshot["image_source_manifest"]["assets"]
        assert c.writes == []
        created.append(title)
        return "doc1", "https://example.invalid/docx/doc1"

    monkeypatch.setattr(c.service, "create_document", create)
    c.service.process("alice", c.jobid)
    assert len(created) == 1 and c.writes == ["text", "create", "upload", "bind", "text"]
    result = c.service.serialize(c.job())
    assert result["status"] == "completed" and result["formatting"]["images_embedded"] is True


def test_process_unknown_image_cannot_be_completed_or_replayed(illustrated, monkeypatch):
    c = illustrated
    monkeypatch.setattr(c.service, "checkpoint", base.FeishuService.checkpoint.__get__(c.service))
    c.fail = "bind"
    c.service.process("alice", c.jobid)
    result = c.service.serialize(c.job())
    assert result["status"] == "failed" and result["phase"] == "unknown"
    assert result["formatting"]["images_embedded"] is False
    original = list(c.writes)
    c.fail = None
    c.service.process("alice", c.jobid)
    assert c.writes == original and c.service.serialize(c.job())["status"] == "failed"


@pytest.fixture
def image_status(illustrated, monkeypatch):
    c = illustrated
    with c.scope() as db:
        db.get(FeishuConnectionDB, "alice").tokens = "synthetic-encrypted-grant-evidence"
    monkeypatch.setattr(c.service, "configured", lambda: True)
    monkeypatch.setattr(c.service, "setup_status", lambda: {"ready": True})
    monkeypatch.setattr(c.service, "_verify_identity", lambda owner: USER)
    return c


@pytest.mark.parametrize("scopes,ready", [
    ({"docs:document.media:upload", "docx:document"}, True),
    ({"docs:document.media:upload", "docx:document:write_only", "docx:document:readonly"}, True),
    ({"docx:document", "docx:document.block:convert"}, False),
    ({"docs:document.media:upload", "docx:document:write_only"}, False),
    ({"docs:document.media:upload", "docx:document:readonly"}, False),
    (set(), False),
])
def test_cli_image_status_requires_actual_upload_read_and_write_grants_without_claiming_acceptance(image_status, scopes, ready):
    c = image_status
    c.grants = scopes
    result = c.service.status("alice")["markdown_conversion_preflight"]
    assert result["image_mode"] == ("source_bound_native" if ready else "unsupported_before_write")
    assert result["image_user_grant_available"] is ready
    assert result["image_provider_acceptance"] == "unverified" and result["image_write_confirmed"] is False
    assert "尚未完成真实飞书图文发布验收" in result["image_message"] and c.writes == []


@pytest.mark.parametrize("state", ["unavailable", "expired", "disconnected"])
def test_cli_image_status_never_uses_cached_grants_for_unverified_connection(image_status, monkeypatch, state):
    c = image_status
    if state == "unavailable":
        def unavailable(owner): raise FeishuError("synthetic provider outage", 503)
        monkeypatch.setattr(c.service, "_verify_identity", unavailable)
    else:
        with c.scope() as db:
            row = db.get(FeishuConnectionDB, "alice")
            if state == "expired": row.expired = True
            else: row.tokens = ""
    result = c.service.status("alice")["markdown_conversion_preflight"]
    assert result["image_mode"] == "unsupported_before_write"
    assert not result["image_user_grant_available"] and not any(result["image_grants"].values())
    assert c.writes == []


def test_http_connection_status_keeps_unsupported_image_mode(image_status):
    c = image_status
    result = base.FeishuService._connection_status(c.service, "alice")["markdown_conversion_preflight"]
    assert result["image_mode"] == "unsupported_before_write" and "image_protocol" not in result
