"""Exact object aliases over a partial, verified CLI-visible cache.

Integration owns CLI verification and model/router registration. Default binding
verification is lazy through the current owner-scoped FeishuService. Tests or
alternate adapters can inject read-only binding and *cache-only* refresh
callbacks. ``record_objects`` is for successful
contacts/groups reads, with the binding frozen BEFORE that read. No CLI command,
credential access, directory enumeration, publication, or learning happens here.
"""
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
import hashlib
import json
import re
import time
import unicodedata

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models.feishu_object_hotwords import FeishuObjectAliasDB, FeishuObjectDB

MAX_OBJECTS = 5000
MAX_BATCH = 1000
MAX_ALIASES = 200
Binding = Mapping[str, str]
BindingProvider = Callable[[str], Binding | None]
RefreshProvider = Callable[[str, Binding], Iterable[Mapping]]
SessionFactory = Callable[[], AbstractContextManager[Session]]
_BINDING_KEYS = {"owner", "connection_id", "sender_open_id", "app_id", "tenant_key"}


def _string(value, maximum, label):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum or
            any(unicodedata.category(char).startswith("C") for char in value)):
        raise HTTPException(422, f"{label}无效")
    return value.strip()


def _key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _binding(value):
    if not isinstance(value, Mapping) or set(value) != _BINDING_KEYS:
        raise HTTPException(409, "飞书连接尚未核验，请返回插件设置")
    result = {key: _string(value[key], 200, "连接身份") for key in sorted(_BINDING_KEYS)
              if key != "tenant_key"}
    # Some verified CLI identities lack a tenant key; retain its explicit empty
    # value rather than fabricate a tenant. All other binding fields are required.
    tenant = value["tenant_key"]
    if not isinstance(tenant, str) or len(tenant) > 200 or any(unicodedata.category(c).startswith("C") for c in tenant):
        raise HTTPException(409, "飞书租户身份无效")
    result["tenant_key"] = tenant
    if (not re.fullmatch(r"cli_[A-Za-z0-9_-]{1,196}", result["app_id"]) or
            not re.fullmatch(r"ou_[A-Za-z0-9_-]{1,196}", result["sender_open_id"])):
        raise HTTPException(409, "飞书连接身份不匹配，请重新核验")
    return result


def binding_hash(binding):
    """Only the five verified identity fields enter the deterministic hash."""
    return hashlib.sha256(json.dumps(_binding(binding), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _object(value):
    if not isinstance(value, Mapping) or value.get("kind") not in ("contact", "group"):
        raise HTTPException(422, "飞书对象类型无效")
    kind = value["kind"]
    object_id = _string(value.get("id"), 200, "飞书对象")
    prefix = "ou_" if kind == "contact" else "oc_"
    if not re.fullmatch(prefix + r"[A-Za-z0-9_-]{1,196}", object_id):
        raise HTTPException(422, "飞书对象与类型不匹配")
    return {"id": object_id, "name": _string(value.get("name"), 500, "飞书名称"), "kind": kind}


def _public_object(row):
    return {"id": row.id, "name": row.name, "kind": row.kind}


def _public_alias(row, target):
    return {"id": row.id, "alias": row.alias, "target_id": target.id,
            "target_name": target.name, "kind": target.kind}


def _write_lock(db):
    # Serialize check+insert/capacity checks across desktop SQLite processes.
    # This is the first statement in a fresh session, before any implicit BEGIN.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


class FeishuObjectHotwordsService:
    def __init__(self, *, binding_provider: BindingProvider | None = None,
                 cli_enabled: Callable[[], bool] | None = None,
                 refresh_provider: RefreshProvider | None = None,
                 session_factory: SessionFactory | None = None):
        self.binding_provider = binding_provider
        self.cli_enabled = cli_enabled or (lambda: False)
        self.refresh_provider = refresh_provider
        self.session_factory = session_factory or session_scope

    def enabled(self):
        return self.cli_enabled() is True

    def current_binding(self, owner):
        _string(owner, 128, "账号")
        if self.binding_provider is None:
            raise HTTPException(409, "飞书 CLI 连接尚未核验")
        return _binding(self.binding_provider(owner))

    def _scope(self, owner, binding):
        owner = _string(owner, 128, "账号")
        normalized = _binding(binding)
        if normalized["owner"] != owner:
            raise HTTPException(409, "飞书连接不属于当前账号")
        if self.binding_provider is not None:
            if not self.enabled():
                raise HTTPException(403, "飞书 CLI 已停用，请返回插件设置")
            if self.current_binding(owner) != normalized:
                raise HTTPException(409, "飞书账号或连接已变化，请重新读取")
        return owner, binding_hash(normalized)

    def _assert_current(self, owner, binding):
        self._scope(owner, binding)

    def record_objects(self, owner, binding, objects):
        """Merge only verified read results; absence is never a deletion claim.

        Input is normalized ``{id,name,kind}``, NOT a raw CLI payload. Caller
        must freeze binding before provider reads and supply current_binding
        verification to reject stale results. Extra provider fields are dropped.
        """
        owner, fingerprint = self._scope(owner, binding)
        batch = {}
        for index, value in enumerate(objects):
            if index >= MAX_BATCH:
                raise HTTPException(422, "本次可见对象过多，请分批记录")
            item = _object(value)
            if item["id"] in batch and batch[item["id"]] != item:
                raise HTTPException(422, "同一飞书对象返回不一致，请重新读取")
            batch[item["id"]] = item
        self._assert_current(owner, binding)
        if not batch:
            return
        with self.session_factory() as db:
            _write_lock(db)
            rows = db.scalars(select(FeishuObjectDB).where(
                FeishuObjectDB.owner == owner, FeishuObjectDB.binding_hash == fingerprint)).all()
            existing = {row.id: row for row in rows}
            if len(existing.keys() | batch.keys()) > MAX_OBJECTS:
                raise HTTPException(409, "已缓存可见对象达到上限")
            now = time.time()
            for object_id, item in batch.items():
                row = existing.get(object_id)
                if row is None:
                    db.add(FeishuObjectDB(owner=owner, binding_hash=fingerprint, updated_at=now, **item))
                else:
                    row.name, row.kind, row.updated_at = item["name"], item["kind"], now
            self._assert_current(owner, binding)

    def snapshot(self, owner, binding):
        owner, fingerprint = self._scope(owner, binding)
        with self.session_factory() as db:
            objects = db.scalars(select(FeishuObjectDB).where(
                FeishuObjectDB.owner == owner, FeishuObjectDB.binding_hash == fingerprint)
                .order_by(FeishuObjectDB.id)).all()
            aliases = db.scalars(select(FeishuObjectAliasDB).where(
                FeishuObjectAliasDB.owner == owner, FeishuObjectAliasDB.binding_hash == fingerprint)
                .order_by(FeishuObjectAliasDB.id)).all()
            by_id = {row.id: row for row in objects}
            result = {"objects": [_public_object(row) for row in objects],
                      "aliases": [_public_alias(row, by_id[row.target_id]) for row in aliases
                                  if row.target_id in by_id], "partial": True}
            if objects:
                result["updated_at"] = max(row.updated_at for row in objects)
        self._assert_current(owner, binding)
        return result

    def refresh(self, owner, binding):
        """Optional callback reads existing visible cache once; never enumerates CLI."""
        self._scope(owner, binding)
        if self.refresh_provider is not None:
            try:
                # Consume lazy results inside the guarded failure boundary.
                values = []
                for index, value in enumerate(self.refresh_provider(owner, dict(_binding(binding)))):
                    if index >= MAX_BATCH:
                        raise HTTPException(422, "本次可见对象过多，请分批记录")
                    values.append(value)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(503, "读取飞书可见对象缓存失败，请手动重试") from None
            self._assert_current(owner, binding)
            self.record_objects(owner, binding, values)
        return self.snapshot(owner, binding)

    def add_alias(self, owner, binding, alias, target_id):
        owner, fingerprint = self._scope(owner, binding)
        alias = _string(alias, 50, "别称")
        alias_key = _key(alias)
        if not alias_key or len(alias_key) > 200:
            raise HTTPException(422, "别称归一化后过长或为空")
        target_id = _string(target_id, 200, "飞书对象")
        try:
            with self.session_factory() as db:
                _write_lock(db)
                target = db.get(FeishuObjectDB, (owner, fingerprint, target_id))
                if target is None:
                    raise HTTPException(404, "当前连接未读取到该对象，请先搜索并选择")
                row = db.scalar(select(FeishuObjectAliasDB).where(
                    FeishuObjectAliasDB.owner == owner, FeishuObjectAliasDB.binding_hash == fingerprint,
                    FeishuObjectAliasDB.alias_key == alias_key))
                if row is not None and row.target_id != target_id:
                    raise HTTPException(409, "此别称已绑定其他对象，请先删除旧别称")
                if row is None:
                    count = db.scalar(select(func.count()).select_from(FeishuObjectAliasDB).where(
                        FeishuObjectAliasDB.owner == owner, FeishuObjectAliasDB.binding_hash == fingerprint))
                    if count >= MAX_ALIASES:
                        raise HTTPException(409, "别称数量达到上限")
                    row = FeishuObjectAliasDB(owner=owner, binding_hash=fingerprint, alias=alias,
                                              alias_key=alias_key, target_id=target_id, updated_at=time.time())
                    db.add(row)
                    db.flush()
                result = _public_alias(row, target)
                self._assert_current(owner, binding)
            return result
        except IntegrityError:
            raise HTTPException(409, "别称已变化，请重新读取后确认") from None

    def delete_alias(self, owner, binding, alias_id):
        owner, fingerprint = self._scope(owner, binding)
        alias_id = _string(alias_id, 36, "别称")
        with self.session_factory() as db:
            _write_lock(db)
            row = db.scalar(select(FeishuObjectAliasDB).where(
                FeishuObjectAliasDB.id == alias_id, FeishuObjectAliasDB.owner == owner,
                FeishuObjectAliasDB.binding_hash == fingerprint))
            if row is None:
                raise HTTPException(404, "当前连接下未找到该别称")
            db.delete(row)
            self._assert_current(owner, binding)
        return {"deleted": True}

    def resolve(self, owner, binding, query):
        """Exact normalized names/aliases only; never sends or guesses a target.

        A cache match is not a current permission/membership proof. Callers must
        still verify the selected target with the current CLI before any send.
        """
        query_key = _key(_string(query, 50, "查找名称"))
        snapshot = self.snapshot(owner, binding)
        by_id = {item["id"]: item for item in snapshot["objects"]}
        matched = {item["id"] for item in snapshot["objects"] if _key(item["name"]) == query_key}
        matched.update(item["target_id"] for item in snapshot["aliases"] if _key(item["alias"]) == query_key)
        matches = [by_id[object_id] for object_id in sorted(matched)]
        return matches


def _cli_enabled():
    from app.services.feishu_cli import enabled

    return enabled()


def _current_binding(owner):
    from app.services.feishu_service import FeishuService

    return FeishuService().for_owner(owner).contact_binding(owner)


service = FeishuObjectHotwordsService(binding_provider=_current_binding, cli_enabled=_cli_enabled)


def configure_runtime(*, binding_provider: BindingProvider, cli_enabled: Callable[[], bool],
                      refresh_provider: RefreshProvider | None = None):
    """Explicit local integration hook; callbacks must not return secrets."""
    global service
    service = FeishuObjectHotwordsService(binding_provider=binding_provider,
                                         cli_enabled=cli_enabled, refresh_provider=refresh_provider)
    return service


def record_objects(owner, binding, objects):
    return service.record_objects(owner, binding, objects)


def resolve(owner, binding, query):
    return service.resolve(owner, binding, query)
