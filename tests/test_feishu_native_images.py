"""Synthetic files/Docx/CLI only. No real authorization or document writes."""
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import json
import subprocess
from types import SimpleNamespace
import uuid

import httpx
from PIL import Image
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db_models import FeishuDeliveryDB, NoteDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuWriteBatchDB
from app.models.feishu_native_images import FeishuNativeImagePlanDB as Plan, FeishuNativeImageStepDB as Step
from app.services import feishu_native_images as media
from app.services.feishu_service import FeishuError
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def image_job(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("Real CLI, network and document writes are forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    artifacts = TaskArtifactService(tmp_path / "output")
    task = str(uuid.uuid4())
    folder = artifacts.create_task_dir(task)
    (folder / ".task_id").write_text(task)
    (folder / "recording_owner").write_text("alice")
    screenshots = folder / "screenshots"
    screenshots.mkdir()
    image = screenshots / "summary-source-0.png"
    Image.new("RGB", (32, 24), "blue").save(image)
    ref = f"/api/task/{task}/artifacts/screenshots/{image.name}"
    content = f"# 前文\n\n事实段落。\n\n![真实画面]({ref})\n\n## 后文\n\n后续说明。"
    engine = create_engine("sqlite:///" + (tmp_path / "images.db").as_posix())
    Base.metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    jobid = str(uuid.uuid4())
    snapshot = dict(connection_id="connection1", open_id="ou_sender", app_id="cli_app", tenant_key="tenant",
                    destination={"kind": "wiki", "space_id": "space", "node_token": "parent"})
    with scope() as db:
        db.add(NoteDB(id="note", title="会议", content=content, created_by="alice", task_id=task))
        db.add(FeishuDeliveryDB(id=jobid, owner="alice", note_key="note", revision="r1", title="会议",
                               content=content, document_id="doc1", document_url="https://example.invalid/wiki/node"))
        db.add(FeishuDeliveryDestinationDB(delivery_id=jobid, snapshot=json.dumps(snapshot)))
    ctx = SimpleNamespace(jobid=jobid, task=task, ref=ref, folder=folder, image=image, scope=scope,
                          snapshot=snapshot, content=content, artifacts=artifacts, writes=[], root=[], blocks={},
                          fail=None, after_write=lambda: None, verifies=[], converts=[])

    def pending():
        assert ctx.inside_dispatch, "revocation/connection guard must cover the external write"
        with scope() as db:
            steps = db.scalars(select(Step).where(Step.state == "dispatching")).all()
            assert len(steps) == 1, "a durable unique claim must precede external write"
            batch = db.get(FeishuWriteBatchDB, (jobid, steps[0].key))
            assert batch.state == "dispatching" and batch.fingerprint == steps[0].fingerprint

    def guard(owner, job, frozen):
        assert owner == "alice" and job.id == jobid and job.document_id == "doc1"
        assert frozen == snapshot
        ctx.verifies.append(owner)

    def request(owner, method, path, **kwargs):
        assert owner == "alice" and path.startswith("docx/v1/documents/doc1/")
        if method == "GET":
            block = path.rsplit("/", 1)[-1]
            if block == "doc1":
                return {"block": {"block_id": "doc1", "block_type": 1, "children": list(ctx.root)}}
            return {"block": deepcopy(ctx.blocks[block])}
        pending()
        body = kwargs["body"]
        if path.endswith("/descendant"):
            assert body["index"] == len(ctx.root)
            mapped = {i["block_id"]: "real" + str(len(ctx.root)) + "_" + str(n)
                      for n, i in enumerate(body["descendants"])}
            ctx.root.extend(mapped[i] for i in body["children_id"])
            ctx.writes.append("text")
            result = {"block_id_relations": [{"temporary_block_id": k, "block_id": v} for k, v in mapped.items()]}
        elif method == "POST":
            assert body == {"children": [{"block_type": 27, "image": {}}], "index": len(ctx.root)}
            block = "image" + str(len(ctx.root))
            ctx.root.append(block)
            ctx.blocks[block] = {"block_id": block, "parent_id": "doc1", "block_type": 27, "image": {}}
            ctx.writes.append("create")
            result = {"children": [ctx.blocks[block]]}
        else:
            assert method == "PATCH"
            item = body["requests"][0]
            ctx.blocks[item["block_id"]]["image"] = dict(item["replace_image"])
            ctx.writes.append("bind")
            result = {}
        ctx.after_write()
        if ctx.fail == ctx.writes[-1]:
            raise TimeoutError("synthetic lost acknowledgment")
        return result

    def upload(owner, binding, doc, block, asset, data):
        pending()
        assert owner == "alice" and binding == {k: snapshot[k] for k in ("connection_id", "open_id", "app_id", "tenant_key")}
        assert doc == "doc1" and block in ctx.blocks
        assert data == (screenshots / asset["file_name"]).read_bytes()
        assert asset["mime"] == "image/png" and asset["size"] == len(data)
        ctx.writes.append("upload")
        ctx.after_write()
        if ctx.fail == "upload":
            raise TimeoutError("synthetic lost upload response")
        return {"file_token": "uploadedToken"}

    def convert(value):
        ctx.converts.append(value)
        # Native selective planning handles simple text without conversion.
        return {"first_level_block_ids": ["p"], "blocks": [{"block_id": "p", "block_type": 2,
                "text": {"elements": [{"text_run": {"content": value}}]}}]}

    @contextmanager
    def dispatch_context(owner, job, frozen):
        guard(owner, job, frozen)
        ctx.inside_dispatch = True
        try:
            yield
        finally:
            ctx.inside_dispatch = False

    ctx.writer = media.NativeImageWriter(artifacts, request=request, guard=guard, convert=convert,
                                         upload=upload, session_factory=scope, dispatch_context=dispatch_context)
    yield ctx
    engine.dispose()


def test_real_image_three_journaled_steps_preserve_paragraph_order_and_no_repeat(image_job):
    c = image_job
    plan = c.writer.prepare("alice", c.jobid, c.task)
    assert c.writes == [] and [e["kind"] for e in plan["events"]] == ["text", "image", "text"]
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is False
    result = c.writer.run("alice", c.jobid)
    assert result["images_embedded"] is True and result["image_count"] == 1
    assert c.writes == ["text", "create", "upload", "bind", "text"]
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is True
    c.writer.run("alice", c.jobid)
    assert c.writes == ["text", "create", "upload", "bind", "text"]
    with c.scope() as db:
        assert all(row.state == "confirmed" for row in db.scalars(select(FeishuWriteBatchDB)))


def test_two_distinct_screenshots_keep_source_byte_and_paragraph_order(image_job):
    c = image_job
    second = c.image.with_name("second-source.png")
    Image.new("RGB", (32, 24), "red").save(second)
    second_ref = c.ref.rsplit("/", 1)[0] + "/" + second.name
    content = f"前文\n\n![第一张]({c.ref})\n\n中间说明\n\n![第二张]({second_ref})\n\n后文"
    with c.scope() as db:
        db.get(FeishuDeliveryDB, c.jobid).content = content
        db.get(NoteDB, "note").content = content
    uploaded = []
    original = c.writer.upload

    def upload(owner, binding, doc, block, asset, data):
        uploaded.append((asset["file_name"], asset["sha256"]))
        return original(owner, binding, doc, block, asset, data)

    c.writer.upload = upload
    plan = c.writer.prepare("alice", c.jobid, c.task)
    assert [e["kind"] for e in plan["events"]] == ["text", "image", "text", "image", "text"]
    assert c.writer.run("alice", c.jobid)["image_count"] == 2
    assert [name for name, _ in uploaded] == [c.image.name, second.name]
    assert uploaded[0][1] != uploaded[1][1]
    assert c.writes == ["text", "create", "upload", "bind", "text", "create", "upload", "bind", "text"]
    assert [item for item in c.root if item.startswith("image")] == [c.root[1], c.root[3]]
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is True


@pytest.mark.parametrize("phase", ["text", "create", "upload", "bind"])
def test_lost_ack_is_unknown_and_never_replays_or_rolls_back(image_job, phase):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    c.fail = phase
    with pytest.raises(FeishuError) as error:
        c.writer.run("alice", c.jobid)
    assert error.value.code == "image_step_unknown" and error.value.uncertain
    original = list(c.writes)
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is False
    c.fail = None
    with pytest.raises(FeishuError):
        c.writer.run("alice", c.jobid)
    assert c.writes == original
    with c.scope() as db:
        assert any(row.state == "unknown" for row in db.scalars(select(FeishuWriteBatchDB)))


def test_another_worker_cannot_dispatch_same_claim(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    called = []

    def contender():
        if not called:
            called.append(1)
            with pytest.raises(FeishuError):
                c.writer.run("alice", c.jobid)

    c.after_write = contender
    c.writer.run("alice", c.jobid)
    assert c.writes == ["text", "create", "upload", "bind", "text"] and called == [1]


@pytest.mark.parametrize("damage", ["owner", "task", "mime", "hash", "size", "symlink", "hardlink"])
def test_source_binding_and_real_bytes_checked_before_any_write(image_job, damage):
    c = image_job
    if damage == "hash":
        c.writer.prepare("alice", c.jobid, c.task)
        Image.new("RGB", (32, 24), "red").save(c.image)
        with pytest.raises(FeishuError):
            c.writer.run("alice", c.jobid)
        # Earlier text can be confirmed, but image content is never dispatched.
        assert "create" not in c.writes and "upload" not in c.writes
        return
    if damage == "owner": (c.folder / "recording_owner").write_text("bob")
    if damage == "task": (c.folder / ".task_id").write_text(str(uuid.uuid4()))
    if damage == "mime": c.image.write_text("not a PNG")
    if damage == "size":
        with c.image.open("wb") as stream:
            stream.truncate(media.MAX_BYTES + 1)
    if damage in ("symlink", "hardlink"):
        target = c.image.with_name("other.png")
        c.image.rename(target)
        try:
            c.image.symlink_to(target) if damage == "symlink" else c.image.hardlink_to(target)
        except OSError:
            pytest.skip("Filesystem does not permit link test")
    with pytest.raises(FeishuError):
        c.writer.prepare("alice", c.jobid, c.task)
    assert c.writes == [] and c.converts == []


@pytest.mark.parametrize("reference", ["https://model.invalid/picture.png", "file:///secret.png",
    "/api/task/../artifacts/screenshots/a.png", "/api/task/" + str(uuid.uuid4()) + "/artifacts/screenshots/a.png",
    "/api/task/" + str(uuid.uuid4()) + "/artifacts/screenshots/%2e%2e.png"])
def test_untrusted_reference_is_never_downloaded_or_accepted(image_job, reference):
    c = image_job
    with pytest.raises(FeishuError):
        media.read_asset(c.artifacts, "alice", c.task, reference)
    assert c.writes == []


def test_inline_and_table_images_are_explicitly_unsupported_not_published_as_text(image_job):
    c = image_job
    for source in (f"inline ![x]({c.ref}) after", f"|a|b|\n|---|---|\n|![x]({c.ref})|c|", '<img src="https://invalid/x.png">'):
        with pytest.raises(FeishuError):
            media.split_body(source)
    source = '```md\n![literal](https://invalid/x.png)\n```\n' + c.content
    assert len([p for p in media.split_body(source) if p["kind"] == "image"]) == 1


@pytest.mark.parametrize("damage", ["job_owner", "note_task", "snapshot", "plan", "original_body", "root"])
def test_frozen_target_and_plan_are_not_rebound(image_job, damage):
    c = image_job
    if damage not in ("job_owner", "note_task"):
        c.writer.prepare("alice", c.jobid, c.task)
    with c.scope() as db:
        if damage == "job_owner": db.get(FeishuDeliveryDB, c.jobid).owner = "bob"
        if damage == "note_task": db.get(NoteDB, "note").task_id = str(uuid.uuid4())
        if damage == "snapshot": db.get(FeishuDeliveryDestinationDB, c.jobid).snapshot = json.dumps({**c.snapshot, "connection_id": "other"})
        if damage == "plan": db.get(Plan, c.jobid).manifest = "{}"
        if damage == "original_body": db.get(FeishuDeliveryDB, c.jobid).content += "changed"
    if damage == "root": c.root.append("unrelatedBlock")
    with pytest.raises(Exception):
        c.writer.prepare("alice", c.jobid, c.task) if damage in ("job_owner", "note_task") else c.writer.run("alice", c.jobid)
    assert c.writes == []


def test_binding_readback_must_match_uploaded_token(image_job, monkeypatch):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    original = c.writer._verify_image

    def wrong_token(owner, job, snapshot, block, token):
        c.blocks[block]["image"]["token"] = "different"
        original(owner, job, snapshot, block, token)

    monkeypatch.setattr(c.writer, "_verify_image", wrong_token)
    with pytest.raises(FeishuError): c.writer.run("alice", c.jobid)
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is False
    assert c.writes == ["text", "create", "upload", "bind"]


def test_a_missing_dispatch_context_can_never_write(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    c.writer.dispatch_context = None
    with pytest.raises(FeishuError) as error: c.writer.run("alice", c.jobid)
    assert error.value.code == "image_dispatch_guard_missing" and c.writes == []


def test_revocation_after_claim_prevents_external_write_and_never_replays(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)

    @contextmanager
    def revoked(*args):
        raise FeishuError("synthetic revocation", 409, code="connection_changed")
        yield

    c.writer.dispatch_context = revoked
    with pytest.raises(FeishuError): c.writer.run("alice", c.jobid)
    assert c.writes == [] and c.writer.receipt("alice", c.jobid)["images_embedded"] is False


def test_shared_journal_mismatch_is_not_complete_or_replayable(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    c.writer.run("alice", c.jobid)
    original = list(c.writes)
    with c.scope() as db:
        batch = db.scalars(select(FeishuWriteBatchDB)).first()
        batch.state = "unknown"
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is False
    with pytest.raises(FeishuError): c.writer.run("alice", c.jobid)
    assert c.writes == original


def test_confirmed_resume_rechecks_actual_image_binding_without_rewrite(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    c.writer.run("alice", c.jobid)
    original = list(c.writes)
    next(iter(c.blocks.values()))["image"]["token"] = "externallyChangedToken"
    with pytest.raises(FeishuError): c.writer.run("alice", c.jobid)
    assert c.writes == original


def test_final_order_verification_is_required_even_after_all_write_acks(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)

    def concurrent_edit():
        if c.writes == ["text", "create", "upload", "bind", "text"]:
            c.root.append("concurrentUnrelatedBlock")

    c.after_write = concurrent_edit
    with pytest.raises(FeishuError): c.writer.run("alice", c.jobid)
    with c.scope() as db:
        assert all(s.state == "confirmed" for s in db.scalars(select(FeishuWriteBatchDB)))
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is False


def test_historical_receipt_remains_owner_readable_without_source_or_provider(image_job):
    c = image_job
    c.writer.prepare("alice", c.jobid, c.task)
    c.writer.run("alice", c.jobid)
    with c.scope() as db:
        db.delete(db.get(NoteDB, "note"))
    c.image.unlink()
    c.writer.guard = lambda *args: pytest.fail("receipt recovery never requires reauthorization")
    c.writer.request = lambda *args, **kwargs: pytest.fail("local receipts never call providers")
    assert c.writer.receipt("alice", c.jobid)["images_embedded"] is True
    with pytest.raises(Exception): c.writer.receipt("bob", c.jobid)


def test_binary_upload_uses_exact_bytes_explicit_user_and_no_hidden_rollback(image_job, monkeypatch):
    from app.services import feishu_cli as cli
    from app.services import feishu_cli_lock

    c = image_job
    asset, data = media.read_asset(c.artifacts, "alice", c.task, c.ref)
    calls = []
    monkeypatch.setattr(cli, "enabled", lambda: True)
    monkeypatch.setattr(cli, "directory", lambda owner: c.folder)
    monkeypatch.setattr(cli, "_command", lambda owner, args: {"args": args, "shell": False})

    @contextmanager
    def credential(identity, directory):
        assert identity == {"app_id": "cli_app", "open_id": "ou_sender"}
        yield

    monkeypatch.setattr(feishu_cli_lock, "credential_lock", credential)

    def run(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=b'{"ok":true,"identity":"user","data":{"file_token":"token"}}')

    monkeypatch.setattr(subprocess, "run", run)
    result = media.upload_cli("alice", c.snapshot, "doc1", "block1", asset, data)
    assert result == {"file_token": "token"} and len(calls) == 1
    assert calls[0]["input"] == data and calls[0]["shell"] is False
    args = calls[0]["args"]
    assert args[:3] == ["api", "POST", "/open-apis/drive/v1/medias/upload_all"]
    assert args[args.index("--file") + 1] == "-" and args[args.index("--as") + 1] == "user"
    assert "--yes" not in args and "--from-clipboard" not in args
