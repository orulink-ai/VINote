"""Ordered task screenshots -> native Docx images, with per-write journals.

Integration is opt-in: import the models before init_db, then call prepare/run
from the owner's existing authorized publication worker. No router, scope
request, model/network image fetch, document creation or automatic rollback.

Official CLI source (installed 1.0.60, help/source checked 2026-10-20):
https://github.com/larksuite/cli/blob/v1.0.60/cmd/api/api.go#L151-L181
https://github.com/larksuite/cli/blob/v1.0.60/internal/cmdutil/fileupload.go#L86-L132
The raw API supports --file - plus inline --data JSON: stdin becomes the file
part, JSON keys become form fields. --data - conflicts with --file -.
https://github.com/larksuite/cli/blob/main/shortcuts/doc/doc_media_insert.go
https://github.com/larksuite/cli/blob/main/shortcuts/doc/doc_media_upload.go
The shortcut itself has hidden writes/rollback. Decompose its create/upload/bind
operations so VINote commits every receipt before dispatch. Only bounded PNG /
JPEG task screenshots and standalone Markdown image paragraphs are supported.
"""
from contextlib import nullcontext
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid
import warnings

from PIL import Image
from sqlalchemy import select, text

from app.db import session_scope
from app.db_models import NoteDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuWriteBatchDB
from app.models.feishu_native_images import FeishuNativeImagePlanDB as Plan, FeishuNativeImageStepDB as Step
from app.services import feishu_markdown as markdown, feishu_receipt_service as receipts
from app.services.feishu_service import FeishuError

PROTOCOL = "feishu-task-native-images-v1"
REQUIRED_UPLOAD_SCOPE = "docs:document.media:upload"
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_IMAGES = 16
_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
_REF = re.compile(r"/api/task/([0-9a-f-]{36})/artifacts/screenshots/([A-Za-z0-9_-]{1,150}\.(?:png|jpg|jpeg))\Z")
_IMAGE = re.compile(r" {0,3}!\[([^\]\n]{0,500})\]\(([^\s()]+)\)[ \t]*(?:\r?\n)?\Z")


def _error(code, *, unknown=False):
    return FeishuError("原生图片交付尚未核验；请查询原回执，不会自动重发", 409,
                       uncertain=unknown, code=code)


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value) or value == "__creating__":
        raise _error("image_target_invalid")
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _lock(db):
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def _regular(path, limit):
    """Read one opened inode, reject links/junctions and concurrent replacement."""
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                getattr(path, "is_junction", lambda: False)() or not 0 < info.st_size <= limit):
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
        if identity(info) != identity(opened) or identity(opened) != identity(after) or len(data) != info.st_size:
            raise ValueError()
        return data
    except (OSError, ValueError):
        raise _error("image_source_invalid") from None


def read_asset(artifacts, owner, task_id, reference):
    match = _REF.fullmatch(reference) if isinstance(reference, str) else None
    try:
        valid_uuid = str(uuid.UUID(task_id)) == task_id
    except (ValueError, TypeError, AttributeError):
        valid_uuid = False
    if not match or not valid_uuid or match[1] != task_id:
        raise _error("image_source_unbound")
    folder = artifacts.find_task_dir(task_id)
    root = artifacts.output_dir.resolve()
    if (folder is None or folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
            or folder.resolve().parent != root):
        raise _error("image_source_unbound")
    screenshots = folder / "screenshots"
    if (screenshots.is_symlink() or getattr(screenshots, "is_junction", lambda: False)()
            or screenshots.resolve().parent != folder.resolve()):
        raise _error("image_source_unbound")
    try:
        markers_match = (_regular(folder / "recording_owner", 512).decode("utf-8") == owner and
                         _regular(folder / ".task_id", 100).decode("utf-8").strip() == task_id)
    except UnicodeError:
        markers_match = False
    if not markers_match:
        raise _error("image_source_unbound")
    data = _regular(screenshots / match[2], MAX_BYTES)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                width, height = picture.size
                fmt = picture.format
                if (fmt not in ("PNG", "JPEG") or width < 1 or height < 1 or width * height > MAX_PIXELS
                        or getattr(picture, "n_frames", 1) != 1):
                    raise ValueError()
                picture.verify()
            with Image.open(BytesIO(data)) as picture:
                picture.load()
        suffix = Path(match[2]).suffix.lower()
        if (fmt == "PNG") != (suffix == ".png"):
            raise ValueError()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _error("image_mime_invalid") from None
    return {"reference": reference, "file_name": match[2], "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "mime": "image/png" if fmt == "PNG" else "image/jpeg",
            "width": width, "height": height}, data


def split_body(content):
    """Keep exact source order. Complex/remote/inline images fail before writes."""
    if not isinstance(content, str) or not 0 < len(content) <= 600000:
        raise _error("image_body_invalid")
    output, pending = [], ""
    for part in markdown.segments(content):
        if part["kind"] == "blocked_image_table":
            raise _error("image_table_unsupported")
        if part["kind"] != "image_source":
            pending += part["content"]
            continue
        for line in part["content"].splitlines(keepends=True):
            if not re.search(r"!\[|<img\b", line, re.I):
                pending += line
                continue
            match = _IMAGE.fullmatch(line)
            if not match or not _REF.fullmatch(match[2]):
                raise _error("image_reference_unsupported")
            if pending:
                output.append({"kind": "text", "content": pending})
                pending = ""
            output.append({"kind": "image", "caption": match[1], "reference": match[2]})
    if pending:
        output.append({"kind": "text", "content": pending})
    if not 1 <= sum(item["kind"] == "image" for item in output) <= MAX_IMAGES:
        raise _error("image_count_invalid")
    return output


class NativeImageWriter:
    """Callbacks are the main service's frozen owner/connection/policy boundary.

    request(owner, method, path, *, body=None, params=None): CLI user API.
    guard(owner, detached_job, frozen_snapshot): assert original binding and
    automatic policy before every provider read/write; never authorize/create.
    convert(text): existing official conversion, no inference.
    upload(owner, binding, doc_id, block_id, asset, bytes): one upload POST.
    dispatch_context(owner, job, snapshot): context manager holding the same
    owner lock used by connection/policy revocation, rechecking the ORIGINAL
    snapshot under that lock until this one external write has returned.
    """
    def __init__(self, artifacts, *, request, guard, convert, upload=None, session_factory=None,
                 dispatch_context=None):
        self.artifacts, self.request, self.guard, self.convert = artifacts, request, guard, convert
        self.upload = upload or upload_cli
        self.sessions = session_factory or session_scope
        self.dispatch_context = dispatch_context

    def _context(self, db, owner, job_id, *, detach=True):
        job = receipts.owned_job(db, owner, job_id)
        meta = db.get(FeishuDeliveryDestinationDB, job_id)
        snapshot = json.loads(meta.snapshot) if meta else {}
        _id(job.document_id)
        if not all(isinstance(snapshot.get(k), str) and snapshot[k] for k in
                   ("connection_id", "open_id", "app_id", "tenant_key")):
            raise _error("image_binding_unverified")
        if not snapshot["open_id"].startswith("ou_") or not snapshot["app_id"].startswith("cli_"):
            raise _error("image_binding_unverified")
        if detach:
            db.expunge(job)
        return job, snapshot

    def _root(self, owner, job, snapshot):
        self.guard(owner, job, snapshot)
        data = self.request(owner, "GET", f"docx/v1/documents/{job.document_id}/blocks/{job.document_id}")
        block = data.get("block", {}) if isinstance(data, dict) else {}
        children = block.get("children", [])
        if (block.get("block_id") != job.document_id or block.get("block_type") != 1 or
                not isinstance(children, list) or len(children) > 10000 or
                any(not isinstance(i, str) or not _ID.fullmatch(i) for i in children) or
                len(set(children)) != len(children)):
            raise _error("image_root_unverified")
        return children

    def prepare(self, owner, job_id, task_id):
        existing = None
        with self.sessions() as db:
            job, snapshot = self._context(db, owner, job_id)
            note = db.get(NoteDB, job.note_key)
            if note is None or note.created_by != owner or note.task_id != task_id:
                raise _error("image_task_unbound")
            prior = db.get(Plan, job_id)
            if prior:
                manifest = json.loads(prior.manifest)
                self._validate(job, snapshot, prior, manifest, task_id)
                existing = manifest
            elif int(job.written_blocks) or db.scalar(select(FeishuWriteBatchDB.job_id).where(
                    FeishuWriteBatchDB.job_id == job_id).limit(1)):
                raise _error("image_existing_write_unverified", unknown=True)
        self.guard(owner, job, snapshot)
        if existing is not None:
            return existing
        if 'graphic_delivery' in snapshot:
            from app.services.feishu_graphic_delivery import delivery_parts
            parts = delivery_parts(self.artifacts, owner, job, snapshot)
        else:
            parts = split_body(job.content)
        # Resolve every local image BEFORE conversion or any target write.
        for part in parts:
            if part["kind"] == "image":
                asset, _ = read_asset(self.artifacts, owner, task_id, part["reference"])
                part["asset"] = asset
        baseline = self._root(owner, job, snapshot)
        events, offset = [], len(baseline)
        for part in parts:
            if part["kind"] == "image":
                events.append({**part, "offset": offset})
                offset += 1
            elif part["content"].strip():
                for batch in markdown.selective_plan(part["content"], self.convert)["batches"]:
                    body = deepcopy(batch["body"])
                    prefix = f"imagepart{len(events)}-"
                    rename = lambda value: prefix + value
                    body["children_id"] = [rename(i) for i in body["children_id"]]
                    for node in body["descendants"]:
                        node["block_id"] = rename(node["block_id"])
                        if "children" in node:
                            node["children"] = [rename(i) for i in node["children"]]
                    body["index"] = offset
                    events.append({"kind": "text", "offset": offset, "body": body,
                                   "client_token": batch["client_token"]})
                    offset += len(body["children_id"])
        manifest = {"protocol": PROTOCOL, "owner": owner, "job_id": job_id, "note_key": job.note_key,
                    "task_id": task_id, "title_hash": markdown.source_hash(job.title),
                    "document_id": job.document_id, "revision": job.revision,
                    "source_hash": markdown.source_hash(job.content),
                    "snapshot_hash": receipts.fingerprint(snapshot),
                    "binding": {k: snapshot[k] for k in ("connection_id", "open_id", "app_id", "tenant_key")},
                    "baseline": baseline, "events": events}
        if 'graphic_delivery' in snapshot:
            manifest['graphic_manifest_hash'] = receipts.fingerprint(snapshot['graphic_manifest'])
        self.guard(owner, job, snapshot)
        with self.sessions() as db:
            _lock(db)
            current, fresh = self._context(db, owner, job_id)
            prior = db.get(Plan, job_id)
            if prior:
                saved = json.loads(prior.manifest)
                self._validate(current, fresh, prior, saved, task_id)
                return saved
            if current.content != job.content or current.document_id != job.document_id or fresh != snapshot:
                raise _error("image_plan_changed")
            if db.scalar(select(FeishuWriteBatchDB.job_id).where(FeishuWriteBatchDB.job_id == job_id).limit(1)):
                raise _error("image_existing_write_unverified", unknown=True)
            db.add(Plan(owner=owner, job_id=job_id, fingerprint=receipts.fingerprint(manifest), manifest=_json(manifest)))
        return manifest

    @staticmethod
    def _validate(job, snapshot, row, manifest, task_id=None):
        if (row.owner != job.owner or receipts.fingerprint(manifest) != row.fingerprint or
                manifest.get("protocol") != PROTOCOL or manifest.get("owner") != job.owner or
                manifest.get("job_id") != job.id or manifest.get("note_key") != job.note_key or
                manifest.get("title_hash") != markdown.source_hash(job.title) or
                manifest.get("document_id") != job.document_id or manifest.get("revision") != job.revision or
                manifest.get("source_hash") != markdown.source_hash(job.content) or
                manifest.get("snapshot_hash") != receipts.fingerprint(snapshot) or
                task_id is not None and manifest.get("task_id") != task_id):
            raise _error("image_plan_changed")
        if ('graphic_delivery' in snapshot and
                (not isinstance(snapshot.get('graphic_manifest'), dict)
                 or manifest.get('graphic_manifest_hash') != receipts.fingerprint(snapshot['graphic_manifest']))):
            raise _error('image_plan_changed')

    def _load(self, owner, job_id, *, for_write=True):
        with self.sessions() as db:
            job, snapshot = self._context(db, owner, job_id)
            row = db.get(Plan, job_id)
            if row is None:
                raise _error("image_plan_missing")
            manifest = json.loads(row.manifest)
            self._validate(job, snapshot, row, manifest)
            if for_write:
                note = db.get(NoteDB, job.note_key)
                if note is None or note.created_by != owner or note.task_id != manifest["task_id"]:
                    raise _error("image_task_unbound")
                if 'graphic_delivery' in snapshot and note.content != job.content:
                    raise _error('image_task_unbound')
        if for_write:
            self.guard(owner, job, snapshot)
            if 'graphic_delivery' in snapshot:
                from app.services.feishu_graphic_delivery import delivery_parts
                delivery_parts(self.artifacts, owner, job, snapshot)
        return job, snapshot, manifest

    def _step(self, owner, job, snapshot, key, bound, dispatch, validate):
        expected = receipts.fingerprint(bound)
        with self.sessions() as db:
            _lock(db)
            current, fresh = self._context(db, owner, job.id)
            plan = db.get(Plan, job.id)
            if plan is None:
                raise _error("image_plan_missing")
            self._validate(current, fresh, plan, json.loads(plan.manifest))
            row = db.get(Step, (job.id, key))
            if row:
                if row.fingerprint != expected:
                    raise _error("image_step_changed")
                journal = db.get(FeishuWriteBatchDB, (job.id, key))
                if journal is None or journal.fingerprint != expected or journal.state != row.state:
                    raise _error("image_step_receipt_mismatch", unknown=True)
                if row.state == "confirmed":
                    return json.loads(row.result)
                raise _error("image_step_unknown", unknown=True)
            # Reuse the original publication write journal, including its global
            # unknown gate. Both records commit BEFORE the external dispatch.
            if not receipts.begin_batch(db, owner, job.id, key, bound):
                raise _error("image_step_receipt_missing", unknown=True)
            db.add(Step(job_id=job.id, key=key, fingerprint=expected, state="dispatching", result="{}"))
        try:
            with self.dispatch_context(owner, job, snapshot):
                self.guard(owner, job, snapshot)
                result = validate(dispatch())
            with self.sessions() as db:
                row = db.get(Step, (job.id, key))
                if row.state != "dispatching" or row.fingerprint != expected:
                    raise _error("image_step_changed", unknown=True)
                row.state, row.result = "confirmed", _json(result)
                receipts.finish_batch(db, owner, job.id, key, "confirmed")
            return result
        except BaseException:
            # A timeout, cancellation, malformed response or interrupted commit
            # cannot authorize a second create/upload/bind (or rollback DELETE).
            with self.sessions() as db:
                row = db.get(Step, (job.id, key))
                if row and row.state == "dispatching":
                    row.state = "unknown"
                    receipts.finish_batch(db, owner, job.id, key, "unknown")
            raise _error("image_step_unknown", unknown=True) from None

    def run(self, owner, job_id):
        if self.dispatch_context is None:
            raise _error("image_dispatch_guard_missing")
        job, snapshot, manifest = self._load(owner, job_id)
        expected = list(manifest["baseline"])
        images = []
        for index, event in enumerate(manifest["events"]):
            prefix = f"im{index:04d}"
            if event["kind"] == "text":
                path = f"docx/v1/documents/{job.document_id}/blocks/{job.document_id}/descendant"
                bound = {"path": path, "body": event["body"], "client_token": event["client_token"]}

                def dispatch_text():
                    self._assert_order(owner, job, snapshot, expected)
                    return self.request(owner, "POST", path, body=event["body"],
                                        params={"client_token": event["client_token"]})

                def text_result(raw):
                    relations = raw.get("block_id_relations", [])
                    mapping = {i.get("temporary_block_id"): _id(i.get("block_id"))
                               for i in relations if isinstance(i, dict)}
                    if not {i["block_id"] for i in event["body"]["descendants"]} <= mapping.keys():
                        raise ValueError()
                    return {"root_ids": [mapping[i] for i in event["body"]["children_id"]]}

                result = self._step(owner, job, snapshot, prefix + "t", bound, dispatch_text, text_result)
                expected.extend(result["root_ids"])
                continue
            asset, data = read_asset(self.artifacts, owner, manifest["task_id"], event["reference"])
            if asset != event["asset"]:
                raise _error("image_source_changed")
            path = f"docx/v1/documents/{job.document_id}/blocks/{job.document_id}/children"
            body = {"children": [{"block_type": 27, "image": {}}], "index": event["offset"]}

            def create():
                self._assert_order(owner, job, snapshot, expected)
                return self.request(owner, "POST", path, body=body)

            def created(raw):
                children = raw.get("children", [])
                if len(children) != 1 or children[0].get("block_type") != 27:
                    raise ValueError()
                return {"block_id": _id(children[0].get("block_id"))}

            block = self._step(owner, job, snapshot, prefix + "c", {"path": path, "body": body,
                               "asset": asset}, create, created)["block_id"]
            expected.append(block)
            upload_bound = {"path": "drive/v1/medias/upload_all", "document_id": job.document_id,
                            "parent_node": block, "asset": asset}

            def upload():
                self._assert_order(owner, job, snapshot, expected)
                return self.upload(owner, manifest["binding"], job.document_id, block, asset, data)

            token = self._step(owner, job, snapshot, prefix + "u", upload_bound, upload,
                               lambda raw: {"file_token": _id(raw.get("file_token"))})["file_token"]
            path = f"docx/v1/documents/{job.document_id}/blocks/batch_update"
            body = {"requests": [{"block_id": block, "replace_image": {"token": token,
                     "width": asset["width"], "height": asset["height"],
                     "caption": {"content": event["caption"]}}}]}

            def bind():
                self._assert_order(owner, job, snapshot, expected)
                self.request(owner, "PATCH", path, body=body)
                self._verify_image(owner, job, snapshot, block, token)
                return {"block_id": block, "file_token": token}

            self._step(owner, job, snapshot, prefix + "b", {"path": path, "body": body}, bind, lambda raw: raw)
            images.append((block, token))
        for block, token in images:
            self._verify_image(owner, job, snapshot, block, token)
        self._assert_order(owner, job, snapshot, expected)
        # Completing writes is insufficient: the final ordered root and actual
        # image bindings must also have a durable, read-only verification.
        verified = {"plan_hash": receipts.fingerprint(manifest), "root_ids": expected, "images": images}
        with self.sessions() as db:
            _lock(db)
            row = db.get(Step, (job.id, "verify"))
            if row and row.fingerprint != receipts.fingerprint(verified):
                raise _error("image_verification_changed", unknown=True)
            if row is None:
                db.add(Step(job_id=job.id, key="verify", fingerprint=receipts.fingerprint(verified),
                            state="confirmed", result=_json(verified)))
        return {"protocol": PROTOCOL, "images_embedded": True,
                "image_count": sum(e["kind"] == "image" for e in manifest["events"]),
                "written_blocks": len(expected) - len(manifest["baseline"])}

    def _assert_order(self, owner, job, snapshot, expected):
        if self._root(owner, job, snapshot) != expected:
            raise _error("image_document_changed", unknown=True)

    def _verify_image(self, owner, job, snapshot, block, token):
        self.guard(owner, job, snapshot)
        raw = self.request(owner, "GET", f"docx/v1/documents/{job.document_id}/blocks/{block}")
        value = raw.get("block", {})
        if (value.get("block_id") != block or value.get("parent_id") != job.document_id or
                value.get("block_type") != 27 or value.get("image", {}).get("token") != token):
            raise _error("image_binding_unverified", unknown=True)

    def receipt(self, owner, job_id, *, db=None):
        """Local GET recovery; does not replay or infer success from text."""
        # Reuse the caller's transaction during serialize. No writer lock,
        # nested session, flush, provider request or authorization check here.
        with (nullcontext(db) if db is not None else self.sessions()) as session, session.no_autoflush:
            job, snapshot = self._context(session, owner, job_id, detach=False)
            plan = session.get(Plan, job_id)
            if plan is None:
                raise _error("image_plan_missing")
            manifest = json.loads(plan.manifest)
            self._validate(job, snapshot, plan, manifest)
            steps = session.scalars(select(Step).where(Step.job_id == job.id)).all()
            states = {s.key: s.state for s in steps}
            journals = {s.offset: s for s in session.scalars(select(FeishuWriteBatchDB).where(
                FeishuWriteBatchDB.job_id == job.id)).all()}
            consistent = all(s.key in journals and journals[s.key].fingerprint == s.fingerprint and
                             journals[s.key].state == s.state for s in steps if s.key != "verify")
            proof = next((s for s in steps if s.key == "verify"), None)
            try:
                verified = json.loads(proof.result) if proof is not None else {}
                consistent = consistent and proof is not None and receipts.fingerprint(verified) == proof.fingerprint \
                    and verified.get("plan_hash") == receipts.fingerprint(manifest)
            except (TypeError, ValueError):
                consistent = False
        required = {f"im{i:04d}{suffix}" for i, e in enumerate(manifest["events"])
                    for suffix in (("t",) if e["kind"] == "text" else ("c", "u", "b"))}
        required.add("verify")
        return {"protocol": PROTOCOL, "images_embedded": consistent and all(states.get(k) == "confirmed" for k in required),
                "steps": states}


def upload_cli(owner, binding, document_id, block_id, asset, data):
    """One bounded multipart upload; binary stdin avoids a second path read.

    No shortcut orchestration, temp files, network fetch, auth expansion or
    retries. CLI controls user credentials; only response file_token survives.
    """
    from app.services import feishu_cli as cli
    from app.services.feishu_cli_lock import credential_lock

    if not cli.enabled() or len(data) != asset["size"] or hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise _error("image_upload_source_changed")
    fields = {"file_name": asset["file_name"], "parent_type": "docx_image", "parent_node": _id(block_id),
              "size": len(data), "extra": _json({"drive_route_token": _id(document_id)})}
    args = ["api", "POST", "/open-apis/drive/v1/medias/upload_all", "--as", "user", "--json",
            "--file", "-", "--data", _json(fields)]
    try:
        with credential_lock({"app_id": binding["app_id"], "open_id": binding["open_id"]}, cli.directory(owner)):
            result = subprocess.run(**cli._command(owner, args), input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=30)
        if result.returncode or len(result.stdout) > 1_000_000:
            raise ValueError()
        raw = json.loads(result.stdout)
        if raw.get("ok") is not True or raw.get("identity") != "user":
            raise ValueError()
        return {"file_token": _id(raw.get("data", {}).get("file_token"))}
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        raise _error("image_upload_unknown", unknown=True) from None
