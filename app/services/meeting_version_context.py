"""Meeting-version choices around the unchanged summary-only executor.

Default context is local/read-only. Only an explicit model change reads the
current connection catalog. Persisted request hashes protect query-only recovery
even after source/default changes; neither a receipt nor an unknown POST requeues.
"""
from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import update

from app.db_models import SourceRequestDB
from app.services.meeting_summary_regeneration import (
    SummaryConfirmation, SummaryRegenerationService, _digest, _submission,
)
from app.services.retained_task_source import SOURCE_LOCK
from app.services.source_request_service import _fingerprint
from app.services.task_generation_context import _read_json, _unavailable
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.services.vilab_cloud_service import VILabCloudService


class MeetingVersionConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    confirmed: Literal[True]
    context_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    asr_mode: Literal["reuse", "fresh"] = "reuse"
    llm_mode: Literal["inherit", "select"] = "inherit"
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    selection_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    connection_id: str | None = Field(default=None, min_length=1, max_length=200)
    content_depth: Literal["brief", "concise", "detailed"] = "concise"
    presentation: Literal["text", "illustrated", "html", "comic", "infographic"] = "text"
    asr_model: str | None = Field(default=None, min_length=1, max_length=200)
    fresh_context_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    extra_asr_consent: bool = False

    @field_validator("confirmed", "extra_asr_consent", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("请明确确认本次处理")
        return value

    @field_validator("model_name", "asr_model")
    @classmethod
    def exact_model(cls, value):
        if value is not None and value != value.strip():
            raise ValueError("请选择真实目录模型")
        return value

    @model_validator(mode="after")
    def choices(self):
        if self.llm_mode == "inherit":
            if any(value is not None for value in (self.model_name, self.selection_revision, self.connection_id)):
                raise ValueError("沿用原模型时不接受其他连接或模型")
        elif not self.model_name or not self.selection_revision:
            raise ValueError("请明确选择总结模型并核验当前连接")
        if self.asr_mode == "fresh":
            if (self.llm_mode != "select" or not self.asr_model
                    or not self.fresh_context_revision or self.extra_asr_consent is not True):
                raise ValueError("重新识别需明确选择 ASR 和 LLM 并确认额外额度")
        elif self.asr_model is not None or self.fresh_context_revision is not None or self.extra_asr_consent:
            raise ValueError("复用转写不会接受重新识别参数")
        return self


def _request_hash(parent, body):
    return _digest({"protocol": 1, "parent": parent, "request": body.model_dump(mode="json")})


class _VersionReceipts:
    """Bind the adapter request before the existing executor can queue work.

    A crash between the underlying reservation and binding stays query-only.
    The inner executor's snapshot hash and fingerprint remain unchanged.
    """
    def __init__(self, base, parent, request_hash):
        self.base, self.sessions = base, base.sessions
        self.tag = {"protocol": 1, "parent": parent, "request_sha256": request_hash}

    def get(self, *args):
        return self.base.get(*args)

    def _bind(self, owner, operation, *, allow_missing=False):
        for _ in range(3):
            with self.sessions() as db:
                row = db.get(SourceRequestDB, (owner, operation))
                if row is None:
                    _unavailable("meeting_version_operation_changed", "原提交尚不能核验，请查询原操作。")
                raw = row.receipt_json
                saved = json.loads(raw or "{}")
                previous = saved.get("meeting_version")
                if previous == self.tag:
                    return  # Existing operations are strictly read-only.
                if not (allow_missing and previous is None):
                    _unavailable("meeting_version_operation_changed", "提交标识已用于其他版本，请查询原操作。")
                saved["meeting_version"] = self.tag
                changed = db.execute(update(SourceRequestDB).where(
                    SourceRequestDB.owner == owner, SourceRequestDB.operation_id == operation,
                    SourceRequestDB.receipt_json == raw,
                ).values(receipt_json=json.dumps(saved)), execution_options={"synchronize_session": False})
                if changed.rowcount == 1:
                    return
        _unavailable("meeting_version_operation_changed", "原回执已变化，请查询原操作。")

    def reserve(self, owner, operation, submission, **kwargs):
        receipt = self.base.reserve(owner, operation, submission, **kwargs)
        self._bind(owner, operation, allow_missing=receipt.created)
        return receipt

    def accept(self, owner, operation, task, **kwargs):
        self._bind(owner, operation)
        receipt = self.base.accept(owner, operation, task, **kwargs)
        self._bind(owner, operation, allow_missing=True)
        return receipt


class MeetingVersionService:
    def __init__(self, summary=None, fresh_service=None):
        self.summary = summary or SummaryRegenerationService()
        self.fresh = fresh_service

    def _legacy_origin_proof(self, owner, link, snapshot):
        """Exact pre-presentation context algorithm (f8254ec/86406cc).

        Only the historical intent shape may use this proof. Its hash is already
        committed by the accepted DB fingerprint. A modern missing digest, or a
        different owned Origin on disk, never gains inheritance from this path.
        """
        expected = {"contract", "parent_task_id", "operation_id", "confirmed", "canonical_task_id",
                    "context_revision", "source_version", "model_name"}
        if set(link) != expected or link["canonical_task_id"] is not None or link["confirmed"] is not True:
            return False
        try:
            from app.services.summary_visual_evidence import legacy_selected_visual_cache
            with legacy_selected_visual_cache(link["parent_task_id"]):
                context, folder, _, _, request = self.summary._context(owner, link["parent_task_id"])
            original = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
            reference_path = folder / "source_reference.json"
            reference = _read_json(reference_path) if reference_path.exists() or reference_path.is_symlink() else None
            legacy_context = {key: context[key] for key in ("protocol", "parent_task_id", "canonical_task_id", "workflow",
                "source", "transcript_version", "requires_confirmation", "can_regenerate_summary")}
            proof = _digest({"owner": owner, "context": legacy_context, "request": request,
                             "snapshot": original, "source_reference": reference})
            return (proof == link["context_revision"] and context["source"]["version"] == link["source_version"]
                    and all(snapshot.get(key) == original.get(key) for key in
                            ("owner", "mode", "server_url", "connection_id", "connection_auth_mode")))
        except (HTTPException, OSError, ValueError, KeyError, TypeError):
            return False

    def _parent_snapshot(self, owner, parent, folder):
        """SourceRequestDB, not reference JSON alone, binds derived parents."""
        snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
        verified = True
        link_path = folder / "new_generation.json"
        reference = folder / "source_reference.json"
        if reference.exists() or reference.is_symlink():
            link = _read_json(link_path)
            if link.get("contract") == "meeting-summary-only-v1":
                body = SummaryConfirmation(**{k: link[k] for k in SummaryConfirmation.model_fields if k in link})
                submission = _submission(link["parent_task_id"], body)
                operation, marker = str(body.operation_id), "summary_generation_started"
            elif link.get("contract") == "meeting-fresh-asr-v1":
                from app.services.task_fresh_asr import _submission as fresh_submission
                submission = fresh_submission(link)
                operation, marker = link["operation_id"], "new_generation_started"
            else:
                from app.services.parent_asr_prefix import _submission as independent_submission
                submission = independent_submission(link)
                operation, marker = link["operation_id"], "new_generation_started"
            stamp = folder / marker
            if stamp.is_symlink() or stamp.read_text(encoding="utf-8") != "claimed":
                _unavailable("meeting_version_parent_unverified", "原版本的处理记录无法核验。")
            with self.summary.receipts.sessions() as db:
                accepted = db.get(SourceRequestDB, (owner, operation))
                if (not accepted or accepted.state != "accepted" or accepted.task_id != parent
                        or accepted.fingerprint != _fingerprint(submission)):
                    _unavailable("meeting_version_parent_unverified", "原版本的处理回执无法核验。")
                bound_snapshot = json.loads(accepted.receipt_json or "{}").get("summary_snapshot_sha256")
            if link.get("contract") == "meeting-summary-only-v1":
                if (snapshot.get("needs_stt") is not False
                        or snapshot["llm_model"] != body.model_name
                        or body.connection_id is not None and snapshot.get("connection_id") != body.connection_id):
                    _unavailable("meeting_version_parent_unverified", "原版本的冻结模型与处理回执不匹配。")
                if bound_snapshot is None:
                    # The accepted fingerprint still proves the selected source
                    # and requested model name. It does NOT prove its Origin.
                    # Permit explicit new selection, never automatic inheritance.
                    verified = self._legacy_origin_proof(owner, link, snapshot)
                elif bound_snapshot != _digest(snapshot):
                    _unavailable("meeting_version_parent_unverified", "原版本的冻结模型摘要与处理回执不匹配。")
            elif link.get("contract") == "meeting-fresh-asr-v1":
                if link.get("snapshot_sha256") != _digest(snapshot):
                    _unavailable("meeting_version_parent_unverified", "原识别模型与处理回执不匹配。")
            else:
                # Historical independent receipts commit the parent's entire
                # frozen context rather than a direct snapshot digest. Rebuild
                # that proof; disk snapshot equality alone grants no authority.
                from app.services.task_generation_context import frozen_generation_context
                original_context = frozen_generation_context(owner, link["parent_task_id"], receipts=self.summary.receipts)
                original_folder = self.summary.artifacts.find_task_dir(link["parent_task_id"])
                original_snapshot = validate_source(_read_json(original_folder / SNAPSHOT_FILE), owner)
                if original_context["context_revision"] != link["context_revision"] or snapshot != original_snapshot:
                    _unavailable("meeting_version_parent_unverified", "原识别模型的冻结来源无法核验。")
        elif link_path.exists() or link_path.is_symlink():
            _unavailable("meeting_version_parent_unverified", "原版本缺少可信原件关系。")
        if snapshot["mode"] != "cloud":
            _unavailable("meeting_version_cloud_required", "原版本的模型尚不能用于此操作，未使用当前默认模型。")
        return snapshot, verified

    def _context(self, owner, parent, *, active=False):
        capability = None
        reuse_available = True
        try:
            context, folder, _, _, _ = self.summary._context(owner, parent, active=active)
        except HTTPException as error:
            code = error.detail.get("code") if isinstance(error.detail, dict) else None
            if self.fresh is None or code not in {"summary_evidence_unavailable", "summary_visual_evidence_unavailable"}:
                raise
            capability = self.fresh.context(owner, parent, active=active)
            if not capability.get("available"):
                raise error
            folder = self.summary.artifacts.find_task_dir(parent)
            context = {"canonical_task_id": capability["canonical_task_id"], "source": capability["source"],
                       "presentation_options": capability.get("presentation_options", {}),
                       "context_revision": None}
            reuse_available = False
        try:
            snapshot, verified = self._parent_snapshot(owner, parent, folder)
        except (OSError, ValueError, KeyError, TypeError):
            _unavailable("meeting_version_parent_unverified", "原版本的处理信息无法核验。")
        public = {"protocol": 1, "parent_task_id": parent, "canonical_task_id": context["canonical_task_id"],
            "source": context["source"], "default_asr_mode": "reuse", "default_llm_mode": "inherit",
            "original_llm": {"model_name": snapshot["llm_model"], "server_url": snapshot["server_url"],
                             "verified": verified,
                             **({"reason": "原版本模型连接暂不能核验，请选择并确认本次模型。已有转写仍可复用。"} if not verified else {}),
                             **({"connection_id": snapshot["connection_id"]} if snapshot.get("connection_id") else {})},
            "presentation_options": context["presentation_options"],
            "asr_modes": {"reuse": {"available": reuse_available,
                **({"reason": "当前缺少完整可复用证据；可明确选择重新识别。"} if not reuse_available else {})},
                "fresh": {"available": False, "reason": "重新识别 ASR 尚未接入，当前可复用已有转写。"}}}
        public["context_revision"] = _digest({"protocol": 1, "owner": owner, "parent": parent,
            "summary_context_revision": context["context_revision"], "source": context["source"],
            "snapshot": snapshot, "original_model_verified": verified})
        if self.fresh is not None:
            try:
                capability = capability or self.fresh.context(owner, parent, active=active)
            except HTTPException:
                capability = {"available": False, "reason": "当前原件或识别来源尚不能用于重新识别。"}
            public["asr_modes"]["fresh"] = {k: capability[k] for k in ("available", "reason", "context_revision", "presentation_options") if k in capability}
        return public, context, snapshot

    def context(self, owner, parent, *, active=False):
        with SOURCE_LOCK:
            return self._context(owner, parent, active=active)[0]

    @staticmethod
    def _current(owner):
        current = VILabCloudService().connection_snapshot(owner)
        if current.get("mode") != "cloud" or not current.get("server_url"):
            _unavailable("meeting_version_selection_unavailable", "当前没有可选择的云端模型连接。")
        return {k: current[k] for k in ("mode", "server_url", "connection_id", "connection_auth_mode") if k in current}

    @staticmethod
    def _selection_revision(owner, context_revision, current):
        return _digest({"owner": owner, "context_revision": context_revision, "connection": current})

    def models(self, owner, parent, context_revision, *, active=False):
        with SOURCE_LOCK:
            public, _, _ = self._context(owner, parent, active=active)
            if public["context_revision"] != context_revision:
                _unavailable("meeting_version_context_changed", "来源已变化，请重新核验本次版本。")
            current = self._current(owner)
            cloud = VILabCloudService()
            with cloud.task_snapshot(owner, snapshot=current):
                models = cloud.models(owner)
            if self._current(owner) != current:
                _unavailable("meeting_version_selection_changed", "模型连接已变化，请重新读取目录。")
            return {"models": models, "connection": {k: current[k] for k in ("server_url", "connection_id") if k in current},
                    "selection_revision": self._selection_revision(owner, context_revision, current)}

    def _existing(self, owner, parent, body):
        operation = str(body.operation_id)
        with self.summary.receipts.sessions() as db:
            row = db.get(SourceRequestDB, (owner, operation))
            if row is None:
                return None
            tag = json.loads(row.receipt_json or "{}").get("meeting_version")
            if tag != {"protocol": 1, "parent": parent, "request_sha256": _request_hash(parent, body)}:
                _unavailable("meeting_version_operation_changed", "此提交已存在或结果未确认，请查询原操作，不要重复提交。")
        return self.summary.receipts.get(owner, operation)

    def accept(self, owner, parent, body, background, note_service=None, *, active=False):
        with SOURCE_LOCK:
            existing = self._existing(owner, parent, body)
            if existing is not None:
                return existing  # No context/catalog/provider lookup or queueing.
            public, summary_context, original = self._context(owner, parent, active=active)
            if public["context_revision"] != body.context_revision or public["source"]["version"] != body.source_version:
                _unavailable("meeting_version_context_changed", "原文件、证据或冻结模型已变化，请重新核验。")
            if body.asr_mode == "reuse" and not public["asr_modes"]["reuse"]["available"]:
                _unavailable("meeting_version_reuse_unavailable", "当前没有可完整复用的证据，未创建任务。")
            if body.llm_mode == "inherit" and not public["original_llm"]["verified"]:
                _unavailable("meeting_version_inherit_unverified", "历史模型连接无法核验，请明确选择本次模型，未创建任务。")
            if body.asr_mode == "fresh" and (self.fresh is None or not public["asr_modes"]["fresh"].get("available")):
                _unavailable("meeting_version_fresh_unavailable", "重新识别 ASR 尚不可用，未创建任务。")
            selected = {**original, "needs_stt": False}
            if body.llm_mode == "select":
                current = self._current(owner)
                if (body.selection_revision != self._selection_revision(owner, body.context_revision, current)
                        or body.connection_id != current.get("connection_id")):
                    _unavailable("meeting_version_selection_changed", "当前模型连接已变化，请重新核验目录。")
                selected = {"version": 1, "owner": owner, **current, "llm_model": body.model_name,
                            "asr_model": body.asr_model or "", "needs_stt": body.asr_mode == "fresh"}
            selected = validate_source(selected, owner)
            cloud = VILabCloudService()
            if body.asr_mode == "fresh":
                with cloud.task_snapshot(owner, snapshot=selected):
                    receipt = self.fresh.accept(owner, parent, body, background, note_service, active=active)
                _VersionReceipts(self.summary.receipts, parent, _request_hash(parent, body))._bind(owner, str(body.operation_id), allow_missing=True)
                return receipt
            receipts = _VersionReceipts(self.summary.receipts, parent, _request_hash(parent, body))
            executor = SummaryRegenerationService(receipts)
            executor.artifacts = self.summary.artifacts
            confirmation = SummaryConfirmation(operation_id=body.operation_id, confirmed=True,
                context_revision=summary_context["context_revision"], source_version=body.source_version,
                model_name=selected["llm_model"], connection_id=selected.get("connection_id"),
                content_depth=body.content_depth, presentation=body.presentation)
            with cloud.task_snapshot(owner, snapshot=selected):
                return executor.accept(owner, parent, confirmation, background, note_service, active=active)
