"""Reuse VINote document/permission/receipt workflows with device-owned CLI auth."""
from contextlib import contextmanager, nullcontext
from datetime import datetime
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from sqlalchemy import delete, inspect, update

from app.config import settings
from app.db import session_scope
from app.db_models import FeishuConnectionDB
from app.services import feishu_cli as cli
from app.services import feishu_auto_policy as auto_policy
from app.services.cloud_account_service import _cipher
from app.services.feishu_service import FeishuError, FeishuService, _lock

USER = "vinote:cli:user"


class FeishuCLIService(FeishuService):
    @property
    def config(self):
        with session_scope() as db:
            row = db.get(FeishuConnectionDB, self.owner)
            tokens = json.loads(_cipher().decrypt(row.tokens.encode())) if row and row.tokens else {}
        return SimpleNamespace(feishu_app_id=tokens.get("app_id", ""),
                               feishu_tenant_key=tokens.get("tenant_key", ""),
                               feishu_doc_base_url="https://www.feishu.cn")

    def for_owner(self, owner):
        return FeishuCLIService(owner)

    def serialize(self, row, db=None):
        if db is None:
            with session_scope() as session:
                return self.serialize(row, db=session)
        with db.no_autoflush:
            result = super().serialize(row, db=db)
        result["execution_location"] = "device"
        if result.get("formatting", {}).get("image_source_preserved"):
            from app.models.feishu_native_images import FeishuNativeImagePlanDB

            def has_plan(session):
                return (inspect(session.connection()).has_table(FeishuNativeImagePlanDB.__tablename__)
                        and session.get(FeishuNativeImagePlanDB, row.id) is not None)

            with db.no_autoflush:
                present = has_plan(db)
            if present:
                from app.services.feishu_native_images import PROTOCOL
                receipt = self._native_image_writer().receipt(row.owner, row.id, db=db)
                confirmed = receipt["images_embedded"] is True
                result["formatting"].update(protocol=PROTOCOL, status="written" if confirmed else "partial",
                    native_write_confirmed=confirmed, images_embedded=confirmed,
                    image_source_preserved=not confirmed,
                    message="原生图片及正文顺序已回读核验" if confirmed else "图片写入尚未完整核验，请查询原回执")
        return result

    def _native_image_writer(self):
        from app.services.feishu_native_images import NativeImageWriter
        from app.services.task_artifact_service import TaskArtifactService

        def guard(owner, job, snapshot):
            if owner != self.owner:
                raise FeishuError("交付账号不匹配", 409, code="connection_changed")
            config = self.config
            if (snapshot.get("app_id") != config.feishu_app_id or
                    snapshot.get("tenant_key") != config.feishu_tenant_key):
                raise FeishuError("原图文交付绑定的飞书应用或租户已变化", 409, code="connection_changed")
            self.assert_delivery_connection(owner, snapshot)
            self._check_automatic_delivery(owner, job)

        @contextmanager
        def dispatch_context(owner, job, snapshot):
            # Same lock as disconnect/revoke; hold it for ONE external action,
            # never across the complete publication pipeline.
            with _lock(owner):
                guard(owner, job, snapshot)
                yield

        def request(owner, method, path, **kwargs):
            return self.request(method, path, token=self.user_token(owner), **kwargs)

        def convert(content):
            return self.request("POST", "docx/v1/documents/blocks/convert", token=self.user_token(self.owner),
                                body={"content_type": "markdown", "content": content})

        return NativeImageWriter(TaskArtifactService(), request=request, guard=guard, convert=convert,
                                 dispatch_context=dispatch_context, session_factory=session_scope)

    def prepare_native_body(self, owner, job):
        from app.db_models import NoteDB
        from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuWriteBatchDB
        from app.models.feishu_native_images import FeishuNativeImagePlanDB
        from app.services import feishu_native_images as images, feishu_receipt_service as receipts
        from app.services.task_artifact_service import TaskArtifactService

        with session_scope() as db:
            original = receipts.owned_job(db, owner, job.id)
            metadata = db.get(FeishuDeliveryDestinationDB, job.id)
            snapshot = json.loads(metadata.snapshot) if metadata else {}
            if not snapshot.get("format_selection", {}).get("image_source_preserved"):
                illustrated = False
            else:
                illustrated = True
                if original.document_id == "__creating__":
                    raise FeishuError("创建图片目标文档的结果未确认，请查询原回执并关联原文档", 409,
                                      uncertain=True, code="create_unknown")
                if not inspect(db.get_bind()).has_table(FeishuNativeImagePlanDB.__tablename__):
                    raise FeishuError("原生图片回执存储尚未初始化，请重新启动桌面服务", 503, code="image_journal_unavailable")
                note = db.get(NoteDB, original.note_key)
                if note is None or note.created_by != owner or not note.task_id:
                    raise FeishuError("缺少当前账号已保存的会议来源", 409, code="image_task_unbound")
                task = note.task_id
                if original.content != job.content or original.document_id != job.document_id:
                    raise FeishuError("原发布内容或目标已变化", 409, code="image_plan_changed")
        if not illustrated:
            return super().prepare_native_body(owner, job)
        self.assert_delivery_connection(owner, snapshot)
        self.user_token(owner)
        with session_scope() as db:
            grants = self.granted_scopes(db.get(FeishuConnectionDB, owner))
        if images.REQUIRED_UPLOAD_SCOPE not in grants:
            raise FeishuError("缺少文档素材上传权限，图片未写入；需用户明确补充飞书授权", 403,
                              code="image_upload_scope_missing")
        if not grants & {"docx:document", "docx:document:write_only"}:
            raise FeishuError("缺少文档编辑权限，图片未写入", 403, code="user_scope_missing")
        if snapshot.get("format_selection", {}).get("needs_converter") and "docx:document.block:convert" not in grants:
            raise FeishuError("缺少原生格式转换权限，图片正文未写入", 403, code="converter_scope_missing")
        if not snapshot.get("app_id") or snapshot["app_id"] != self.config.feishu_app_id:
            raise FeishuError("图片交付缺少原应用快照，禁止补用当前默认值", 409, code="connection_changed")
        assets = []
        for part in images.split_body(job.content):
            if part["kind"] == "image":
                asset, _ = images.read_asset(TaskArtifactService(), owner, task, part["reference"])
                assets.append(asset)
        source = {"protocol": images.PROTOCOL, "task_id": task,
                  "source_hash": images.markdown.source_hash(job.content), "assets": assets}
        with session_scope() as db:
            original = receipts.owned_job(db, owner, job.id)
            metadata = db.get(FeishuDeliveryDestinationDB, job.id)
            current = json.loads(metadata.snapshot)
            previous = current.get("image_source_manifest")
            if previous is not None and previous != source:
                raise FeishuError("原截图或正文已变化，禁止继续原发布", 409, code="image_source_changed")
            if previous is None:
                if current != snapshot or original.content != job.content:
                    raise FeishuError("原发布快照已变化", 409, code="image_plan_changed")
                from sqlalchemy import select
                if int(original.written_blocks) or db.scalar(select(FeishuWriteBatchDB.job_id).where(
                        FeishuWriteBatchDB.job_id == job.id).limit(1)):
                    raise FeishuError("已有正文写入但缺少原图片清单，禁止重写", 409, uncertain=True, code="write_unknown")
                current["image_source_manifest"] = source
                changed = db.execute(update(FeishuDeliveryDestinationDB).where(
                    FeishuDeliveryDestinationDB.delivery_id == job.id,
                    FeishuDeliveryDestinationDB.snapshot == metadata.snapshot).values(snapshot=json.dumps(current)))
                if changed.rowcount != 1:
                    raise FeishuError("图片清单正在保存，请查询原发布", 409, code="image_plan_changed")
        if not job.document_id:
            return {"protocol": images.PROTOCOL, "preflight": True}
        return self._native_image_writer().prepare(owner, job.id, task)

    def write_document(self, owner, job):
        from app.services.feishu_native_images import PROTOCOL
        plan = self.prepare_native_body(owner, job)
        if isinstance(plan, dict) and plan.get("protocol") == PROTOCOL:
            result = self._native_image_writer().run(owner, job.id)
            self.checkpoint(owner, job.id, written_blocks=str(result["written_blocks"]))
            return result
        # The original text writer and its old receipt protocol remain intact.
        return super().write_document(owner, job)

    def configured(self):
        try:
            cli.executable()
            return bool(settings.model_profile_encryption_key)
        except FeishuError:
            return False

    def setup_status(self):
        return {"ready": self.configured(), "cli_available": self.configured(),
                "missing": [] if self.configured() else ["cli"]}

    def _verify_identity(self, owner, *, connect=False, flow_id=None):
        if owner != self.owner:
            raise FeishuError("飞书连接账号与当前调用不一致", 409, code="connection_changed")
        if connect:
            cli.completion_check(owner, flow_id)
        raw = cli.auth_status(owner)
        if not raw.get("appId") or raw.get("brand") != "feishu":
            raise FeishuError("请先扫码连接飞书", 401)
        # The CLI owns refresh/DPoP and its protected credentials. No token or
        # App Secret is copied into VINote, HTTP headers or frontend state.
        open_id = raw.get("identities", {}).get("user", {}).get("openId")
        if not isinstance(open_id, str) or not open_id.startswith("ou_"):
            raise FeishuError("请先扫码授权飞书用户", 401)
        who = cli.api(owner, "GET", "authen/v1/user_info", credential_identity={
            "app_id": raw["appId"], "open_id": open_id})
        current = cli.auth_status(owner)
        if connect:
            cli.completion_check(owner, flow_id)
        user = current.get("identities", {}).get("user", {})
        if (current.get("appId") != raw["appId"] or not isinstance(who.get("open_id"), str)
                or not who["open_id"].startswith("ou_") or not who.get("tenant_key")
                or user.get("openId") != who["open_id"] or user.get("tokenStatus") != "valid"):
            raise FeishuError("飞书身份尚未核验，请重新连接", 409, code="connection_changed")
        try:
            expiry = datetime.fromisoformat(user["expiresAt"].replace("Z", "+00:00")).timestamp()
        except (ValueError, KeyError, TypeError):
            raise FeishuError("授权有效期尚未核验，请重新连接", 502) from None
        # Network readback stays outside the completion guard. Recheck the flow
        # again on entering the guard, and commit/rollback the DB transaction
        # BEFORE releasing it, so cancellation cannot revive a late connection.
        with _lock(owner), cli.completion_commit(owner, flow_id) if connect else nullcontext():
            with session_scope() as db:
                row = db.get(FeishuConnectionDB, owner)
                old = json.loads(_cipher().decrypt(row.tokens.encode())) if row and row.tokens else {}
                if not connect and (not row or row.expired or not old or old.get("transport") != "cli"):
                    raise FeishuError("请扫码连接飞书", 401)
                if row and row.tokens and (row.open_id != who["open_id"] or
                        old.get("app_id") != raw["appId"] or old.get("tenant_key") != who["tenant_key"]):
                    raise FeishuError("飞书账号或应用已变化，请先断开原连接", 409, code="connection_changed")
                if not row:
                    row = FeishuConnectionDB(owner=owner)
                    db.add(row)
                preferences = json.loads(row.preferences or "{}")
                preferences.setdefault("connection_id", str(uuid.uuid4()))
                row.preferences = json.dumps(preferences)
                row.open_id, row.name, row.expired = who["open_id"], who.get("name", "飞书用户"), False
                # This encrypted evidence contains grants/identity only, not bearer
                # credentials. Expiry is the actual CLI-reported access-token expiry.
                row.tokens = _cipher().encrypt(json.dumps({
                    "transport": "cli", "scope": user.get("scope", ""), "expires_at": expiry,
                    "app_id": raw["appId"], "tenant_key": who["tenant_key"]}).encode()).decode()
        return USER

    def _connection_status(self, owner, refresh_unavailable=False):
        result = super()._connection_status(owner, refresh_unavailable)
        from app.services.feishu_native_images import PROTOCOL, REQUIRED_UPLOAD_SCOPE
        with session_scope() as db:
            scopes = self.granted_scopes(db.get(FeishuConnectionDB, owner)) if result.get("connected") else set()
        image_grants = {
            "upload": REQUIRED_UPLOAD_SCOPE in scopes,
            "document_write": bool(scopes & {"docx:document", "docx:document:write_only"}),
            "document_read": bool(scopes & {"docx:document", "docx:document:readonly"}),
        }
        ready = bool(result.get("connected") and all(image_grants.values()))
        # Capability and grant evidence never establish a successful image write
        # or real-provider acceptance. HTTP service's image mode stays unchanged.
        result["markdown_conversion_preflight"].update(
            image_mode="source_bound_native" if ready else "unsupported_before_write",
            image_protocol=PROTOCOL, image_required_scope=REQUIRED_UPLOAD_SCOPE,
            image_user_grant_available=ready, image_grants=image_grants,
            image_provider_acceptance="unverified", image_write_confirmed=False,
            image_message="仅支持账号与任务绑定的截图；尚未完成真实飞书图文发布验收，未确认写入")
        return result

    def status(self, owner):
        unavailable = False
        with session_scope() as db:
            row = db.get(FeishuConnectionDB, owner)
            connected = bool(row and row.tokens and not row.expired)
        if connected:
            try:
                self._verify_identity(owner)
            except FeishuError as exc:
                unavailable = True
                if exc.status_code == 401:
                    with session_scope() as db:
                        row = db.get(FeishuConnectionDB, owner)
                        if row:
                            row.expired = True
        result = self._connection_status(owner, unavailable)
        result.update(transport="cli", setup=self.setup_status())
        # Grant readiness is real; CLI/provider availability remains checked on
        # each request. This never implies a notification was delivered.
        if not connected:
            result.update(connection_state="disconnected", grant_state="disconnected")
        return result

    def authorize(self, owner):
        return cli.start(owner)

    def complete_authorization(self, owner, flow_id):
        # Exchange changes CLI credentials before the database connection is
        # committed. Serialize the whole transition with business dispatch.
        # The independent flow epoch lock still permits immediate cancellation.
        with _lock(owner):
            next_step = cli.complete(owner, flow_id)
            if next_step is not None:
                return next_step
            self._verify_identity(owner, connect=True, flow_id=flow_id)
            return self.status(owner)

    def user_token(self, owner):
        return self._verify_identity(owner)

    def bot_token(self):
        # Existing workflows use two token slots. The desktop intentionally
        # uses user identity for both, as ViTalk does, with no bot fallback.
        return self.user_token(self.owner)

    def request(self, method, path, *, token=None, body=None, params=None):
        if token != USER:
            raise FeishuError("飞书调用缺少已核验用户身份", 401)
        method = method.upper()
        execution = auto_policy.active_delivery.get()
        guarded_write = (execution and method in ("POST", "PUT", "PATCH", "DELETE") and
                         path.startswith(("docx/", "drive/", "wiki/", "im/")))
        if guarded_write and execution[0] != self.owner:
            raise FeishuError("交付绑定的账号与当前调用不一致", 409, code="connection_changed")
        # Recheck the ORIGINAL execution snapshot, not a snapshot of today's
        # config. Keep revoke/reconnect serialized until the CLI call returns;
        # releasing this lock after validation would reopen the dispatch race.
        with _lock(self.owner):
            if guarded_write:
                self.assert_delivery_connection(*execution)
            elif method != "GET":
                self._verify_identity(self.owner)
            with session_scope() as db:
                row = db.get(FeishuConnectionDB, self.owner)
                open_id = row.open_id if row else ""
            return cli.api(self.owner, method, path, body=body, params=params,
                           credential_identity={"app_id": self.config.feishu_app_id, "open_id": open_id})

    def recover_document(self, owner, job_id, url):
        """Preserve the Feishu object kind; never fetch the supplied tenant URL."""
        if owner != self.owner:
            raise FeishuError("交付记录不存在", 404)
        # urlsplit strips some controls, so reject them before parsing. Neither
        # query/fragment nor the supplied host is forwarded to the CLI API.
        if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in url):
            raise FeishuError("请填写有效的飞书云文档链接")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            valid_host = re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+feishu\.cn", host)
            document = re.fullmatch(r"/(docx|wiki)/([A-Za-z0-9]+)", parsed.path)
            valid = (parsed.scheme == "https" and valid_host and document and
                     parsed.username is None and parsed.password is None and parsed.port in (None, 443))
        except ValueError:
            valid = False
        if not valid:
            raise FeishuError("请填写有效的飞书云文档链接")
        # Delegate all owner, frozen binding/destination, lease, title and empty
        # body checks to the existing recovery workflow. Its GETs use only the
        # fixed official API paths; the tenant URL grants no recovery authority.
        return super().recover_document(owner, job_id,
            self.config.feishu_doc_base_url + "/" + document[1] + "/" + document[2])

    def refresh_objects(self, owner):
        """Read one filtered contact page and the current visible groups.

        CLI v1.0.60 emits data.users[{open_id, localized_name, ...}] and
        data.has_more. This is a read shortcut (its search HTTP method is POST),
        not a directory-wide listing, a notification or a scope request.
        """
        import re
        import unicodedata

        if owner != self.owner or not cli.enabled():
            raise FeishuError("请使用当前桌面账号读取飞书可见对象", 403)
        self.user_token(owner)
        binding = dict(self.contact_binding(owner))
        raw = cli.run(owner, ["contact", "+search-user", "--has-chatted", "--exclude-external-users",
                              "--page-size", "30", "--as", "user", "--json"],
                      credential_identity={"app_id": binding["app_id"], "open_id": binding["sender_open_id"]})
        # cli.run propagates permission/auth failures; never turn them into [].
        if not isinstance(raw, dict) or raw.get("ok") is not True:
            raise FeishuError("飞书未确认联系人读取结果，请检查授权后重试", 502,
                              code="contacts_response_invalid")
        if raw.get("identity") != "user":
            raise FeishuError("飞书联系人读取身份已变化，请重新核验", 409, code="connection_changed")
        data = raw.get("data")
        if (not isinstance(data, dict) or not isinstance(data.get("users"), list) or
                len(data["users"]) > 30 or type(data.get("has_more")) is not bool):
            raise FeishuError("飞书联系人响应不完整，请重新读取", 502, code="contacts_response_invalid")
        objects = {}
        for item in data["users"]:
            if not isinstance(item, dict):
                raise FeishuError("飞书联系人身份不完整，请重新读取", 502, code="contacts_response_invalid")
            object_id, name = item.get("open_id"), item.get("localized_name")
            if (not isinstance(object_id, str) or not re.fullmatch(r"ou_[A-Za-z0-9_-]{1,196}", object_id) or
                    not isinstance(name, str) or not name.strip() or len(name) > 500 or
                    any(unicodedata.category(char).startswith("C") for char in name) or
                    item.get("is_cross_tenant") is True or item.get("has_chatted") is False):
                raise FeishuError("飞书联系人与当前筛选不匹配，请重新读取", 502,
                                  code="contacts_response_invalid")
            value = {"id": object_id, "name": name.strip(), "kind": "contact"}
            if object_id in objects and objects[object_id] != value:
                raise FeishuError("飞书联系人名称返回不一致，请重新读取", 502, code="contacts_response_invalid")
            objects[object_id] = value
        # Verify real CLI identity again, not merely the DB metadata, after the
        # external read. Never assign late results to a newly connected profile.
        self.user_token(owner)
        if self.contact_binding(owner) != binding:
            raise FeishuError("飞书连接已变化，请重新读取可见对象", 409, code="connection_changed")
        self.groups(owner)
        if self.contact_binding(owner) != binding:
            raise FeishuError("飞书连接已变化，请重新读取可见对象", 409, code="connection_changed")
        self._remember(owner, binding, list(objects.values()))
        return {"objects": list(objects.values()), "has_more": data["has_more"], "partial": True}

    def groups(self, owner):
        self.user_token(owner)
        binding = self.contact_binding(owner)
        items, page, seen = [], "", set()
        for _ in range(10):
            result = self.request("GET", "im/v1/chats", token=USER,
                                  params={"page_size": 100, **({"page_token": page} if page else {})})
            items.extend({"chat_id": item["chat_id"], "name": item.get("name", "群聊")}
                         for item in result.get("items", []) if isinstance(item, dict)
                         and isinstance(item.get("chat_id"), str) and item["chat_id"].startswith("oc_"))
            if not result.get("has_more"):
                self._remember(owner, binding, [{"id": i["chat_id"], "name": i["name"], "kind": "group"} for i in items])
                return items
            page = result.get("page_token")
            if not page or page in seen:
                break
            seen.add(page)
        raise FeishuError("群列表尚未完整读取，请缩小范围后再试", 502)

    def _remember(self, owner, binding, objects):
        from app.services.feishu_object_hotwords import record_objects
        record_objects(owner, binding, objects)

    def contacts(self, owner, query, page_size=20, page_token=""):
        from app.services.feishu_object_hotwords import resolve
        self.user_token(owner)
        binding = self.contact_binding(owner)
        alias = resolve(owner, binding, query)
        # Aliases provide a query, not authority. Resolve actual contact results
        # and issue the existing fresh selection proof before it can be chosen.
        actual_query = alias[0]["name"] if len(alias) == 1 and alias[0]["kind"] == "contact" else query
        result = super().contacts(owner, actual_query, page_size, page_token)
        self._remember(owner, binding, [{"id": i["open_id"], "name": i["name"], "kind": "contact"}
                               for i in result["items"]])
        if len(alias) == 1 and alias[0]["kind"] == "contact":
            result["items"] = [i for i in result["items"] if i["open_id"] == alias[0]["id"]]
        return result

    def send_message(self, owner, target, job):
        self._check_automatic_delivery(owner, job)
        # User-authored notifications use a native rich-text post. Keep the
        # minutes in the document instead of dumping Markdown into chat.
        post = {"zh_cn": {"title": "会议纪要已就绪", "content": [
            [{"tag": "text", "text": job.title}],
            [{"tag": "a", "text": "查看飞书文档", "href": job.document_url}],
        ]}}
        result = self.request("POST", "im/v1/messages", token=self.user_token(owner),
                              params={"receive_id_type": "chat_id" if target.startswith("oc_") else "open_id"},
                              body={"receive_id": target, "msg_type": "post", "content": json.dumps(post),
                                    "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, job.id + target))})
        if not result.get("message_id"):
            raise FeishuError("通知响应缺少回执，请核对原消息", 502, uncertain=True)
        return result["message_id"]

    def disconnect(self, owner):
        cli.cancel(owner)
        # Revoke this VINote binding and queued intents. Do not log other CLI
        # applications/profiles out or destroy historical provider receipts.
        with _lock(owner), session_scope() as db:
            db.execute(delete(FeishuConnectionDB).where(FeishuConnectionDB.owner == owner))
        from app.services.feishu_auto_outbox import bind_device_policy
        bind_device_policy(owner, None)
        return self.status(owner)
