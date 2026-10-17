"""Read-only frozen context for a future separately confirmed generation.

This helper neither captures current defaults nor authorizes/dispatches a POST.
"""
import hashlib
import json
import re
from pathlib import Path
from fastapi import HTTPException
from app.config import settings
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_original_service import TaskOriginalService
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.services.task_failure import recovery_status


def _unavailable(code, message):
    raise HTTPException(409, {"code": code, "message": message})


def _read_json(path: Path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        _unavailable("frozen_context_unavailable", "原任务的冻结信息尚不能核验，请保留原文件和处理记录。")


def frozen_generation_context(owner, task_id, *, active=False):
    # TaskOriginalService verifies owner, explicit workflow, mapping, original
    # containment and tombstone. It exposes neither arbitrary paths nor content.
    info, _ = TaskOriginalService().get(owner, "task:" + task_id)
    if active:
        _unavailable("task_active", "原任务仍在处理，请先查看原任务状态。")
    artifacts = TaskArtifactService(settings.output_dir)
    folder = artifacts.find_task_dir(task_id)
    if folder is None:
        _unavailable("source_unavailable", "原文件暂不可用，请重新读取资料。")
    status = recovery_status(_read_json(folder / "status.json"))
    if status.get("status") not in {"failed", "error"}:
        _unavailable("task_not_failed", "原任务尚未确认失败，请先查看原任务状态。")
    snapshot_path = folder / SNAPSHOT_FILE
    if not snapshot_path.exists():
        _unavailable("frozen_models_missing", "原任务缺少冻结模型，不能使用当前默认模型代替。")
    snapshot = validate_source(_read_json(snapshot_path), owner)
    if snapshot["mode"] != "cloud":
        _unavailable("frozen_local_models_not_exposed", "原任务的模型配置尚不能用于确认新的生成，未替换为默认模型。")
    if not snapshot.get("asr_model") or not snapshot.get("llm_model"):
        _unavailable("frozen_models_missing", "原任务缺少具体转写或总结模型，未使用默认模型。")
    media = _read_json(folder / "source_media.json")
    digest = media.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        _unavailable("source_version_unavailable", "原文件版本尚不能核验，请保留原文件。")
    frozen_models = {"mode": "cloud", "origin": snapshot["server_url"].rstrip("/"),
                     "asr_model": snapshot["asr_model"], "llm_model": snapshot["llm_model"]}
    public = {"protocol": 1, "parent_task_id": task_id,
              "workflow": "meeting" if info["purpose"] == "meeting" else "note_organization",
              "source": {"file_id": info["id"], "title": info["title"],
                         "type": info["source_type"], "size_bytes": info["size_bytes"], "version": digest},
              "frozen_models": frozen_models,
              "previous_task": {"status": status["status"], "error_code": status.get("error_code")},
              "eligibility": "not_checked", "new_operation_supported": True,
              "can_start_new_generation": False, "can_confirm_new_operation": True}
    # Revision is a consistency binding, never a capability or an authorization.
    # Hash the complete server-only frozen request/snapshot without exposing it.
    binding = {"owner": owner, "context": public, "snapshot": snapshot,
               "request": _read_json(folder / "request.json")}
    public["context_revision"] = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return public
