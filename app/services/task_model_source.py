"""Durable, owner-bound model source; credentials never enter task artifacts."""
from contextlib import contextmanager
from functools import wraps
import hashlib
import inspect
import json
import os
import stat
import uuid
from pathlib import Path
import threading
from urllib.parse import urlsplit

from fastapi import HTTPException

_SNAPSHOT_LOCK = threading.RLock()
SNAPSHOT_FILE = "model_source_snapshot.json"


def config_fingerprint(config):
    value = config.model_dump(exclude={"api_key", "cloud_user_id"})
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_source(value, user_id):
    from app.config import settings
    if (not isinstance(value, dict) or value.get("version") != 1
            or value.get("owner") != user_id or value.get("mode") not in {"cloud", "local"}):
        raise HTTPException(409, "原任务的模型快照无效，未使用当前设置替换")
    if value["mode"] == "cloud":
        origin = value.get("server_url")
        if not isinstance(origin, str):
            raise HTTPException(409, "原任务缺少模型服务来源")
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment or origin.rstrip('/') != settings.vilab_server_url.rstrip('/')):
            raise HTTPException(409, "原任务的模型服务来源已变化，请明确确认恢复来源")
        for kind in ("llm_model", "asr_model"):
            if kind == "asr_model" and value.get("needs_stt") is False:
                continue
            if not isinstance(value.get(kind), str) or not value[kind].strip():
                raise HTTPException(409, "原任务缺少具体模型，请明确确认恢复模型")
        allowed = {"version", "owner", "mode", "server_url", "asr_model", "llm_model"}
    else:
        allowed = {"version", "owner", "mode", "server_url", "asr_model", "llm_model",
                   "local_llm_fingerprint", "local_stt_fingerprint"}
        for key in ("local_llm_fingerprint", "local_stt_fingerprint"):
            if not isinstance(value.get(key), str) or len(value[key]) != 64:
                raise HTTPException(409, "原任务缺少本地模型配置快照")
    allowed.add("needs_stt")
    if "needs_stt" in value and type(value["needs_stt"]) is not bool:
        raise HTTPException(409, "原任务模型快照的来源类型无效")
    if set(value) - allowed:
        raise HTTPException(409, "原任务模型快照含未知字段，未恢复")
    return dict(value)


def capture_source(user_id, options, confirmation=None):
    from app.config import settings
    from app.services.vilab_cloud_service import VILabCloudService
    service = VILabCloudService()
    cloud = service.status(user_id) if user_id else {"mode": "local"}
    if confirmation is not None:
        if (set(confirmation) != {"confirmed", "mode", "server_url", "asr_model", "llm_model"}
                or confirmation.get("confirmed") is not True or confirmation.get("mode") != "cloud"
                or not isinstance(confirmation.get("server_url"), str)
                or confirmation.get("server_url", "").rstrip('/') != settings.vilab_server_url.rstrip('/')):
            raise HTTPException(409, "请明确确认配置的服务来源及两个具体模型")
        cloud = {key: confirmation.get(key) for key in ("mode", "server_url", "asr_model", "llm_model")}
    value = {"version": 1, "owner": user_id, "mode": cloud["mode"],
             "server_url": cloud.get("server_url", settings.vilab_server_url), "asr_model": "", "llm_model": "",
             "needs_stt": options.get("needs_stt", True)}
    # asr_model is the explicit new paired-selection marker. model_name alone
    # retains its historical cloud/default and local/custom behavior.
    paired = options.get("asr_model") is not None and confirmation is None
    if paired:
        choices = {"asr_model": options.get("asr_model"), "llm_model": options.get("model_name")}
        if any(not isinstance(name, str) or not name.strip() or name != name.strip()
               or len(name) > 200 for name in choices.values()):
            raise HTTPException(422, "请同时明确选择 ASR 和 LLM 两个模型")
        if value["mode"] != "cloud":
            raise HTTPException(409, "当前为本地模型模式，未切换到请求中的云端模型")
        if not settings.vilab_server_url:
            raise HTTPException(503, "云端模型服务尚未配置")
        models = service.models(user_id)
        for key, kind in (("asr_model", "asr"), ("llm_model", "llm")):
            service._validate_selection(models, choices[key], kind)
        value.update(choices)
    if value["mode"] == "cloud":
        if not paired:
            choices = {key: cloud.get(key, "") for key in ("asr_model", "llm_model")}
            if (not choices["llm_model"] or value["needs_stt"] and not choices["asr_model"]) and confirmation is None:
                choices = service.defaults(user_id)
            value.update({key: choices.get(key) for key in ("asr_model", "llm_model")})
        if not value["llm_model"] or value["needs_stt"] and not value["asr_model"]:
            raise ValueError("云端当前模型未配置，请联系服务管理员")
    else:
        from app.services.llm_service import LLMService
        from app.services.stt_profile_service import STTProfileService
        with service.task_snapshot(user_id, snapshot={"mode": "local", "configured": False,
                                                     "asr_model": "", "llm_model": "", "server_url": ""}):
            llm_options = {key: options.get(key) for key in ("model_profile_id", "model_name", "api_key", "base_url")}
            if llm_options["model_profile_id"] == "vilab-cloud":
                llm_options["model_profile_id"] = None
            llm = LLMService().resolve_config(user_id=user_id, **llm_options)
            stt = (STTProfileService().resolve_config(user_id=user_id, stt_profile_id=options.get("stt_profile_id"))
                   if value["needs_stt"] else None)
        value.update(local_llm_fingerprint=config_fingerprint(llm), local_stt_fingerprint=config_fingerprint(stt) if stt else hashlib.sha256(b"not-used").hexdigest())
    return validate_source(value, user_id)


def ensure_source(folder, user_id, options, *, allow_capture=False, confirmation=None):
    from app.services.task_artifact_service import TaskArtifactService
    path = Path(folder) / SNAPSHOT_FILE
    with _SNAPSHOT_LOCK:
        if path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise HTTPException(409, "原任务模型快照无法读取，未使用当前设置替换") from None
            if confirmation is not None:
                raise HTTPException(409, "已有模型快照的任务不能更换模型，请另建确认操作")
            return validate_source(value, user_id)
        if not allow_capture and confirmation is None:
            raise HTTPException(409, "原任务缺少冻结模型，请明确确认服务来源、ASR 和 LLM 后再恢复")
        value = capture_source(user_id, options, confirmation)
        if confirmation is not None:
            from app.services.vilab_cloud_service import VILabCloudService
            with VILabCloudService().task_snapshot(user_id, snapshot=value):
                VILabCloudService().validate_ready(user_id)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            TaskArtifactService.write_json(temporary, value)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return value


def verify_local_config(user_id, kind, config):
    from app.services.vilab_cloud_service import _task_source
    snapshot = _task_source.get()
    if snapshot and snapshot[0] == user_id:
        expected = snapshot[1].get(f"local_{kind}_fingerprint")
        if expected and expected != config_fingerprint(config):
            raise HTTPException(409, "原任务的本地模型配置已变化，未静默使用新模型，请另建确认操作")


def verify_stt_result(function):
    @wraps(function)
    def wrapped(self, *, user_id, stt_profile_id):
        result = function(self, user_id=user_id, stt_profile_id=stt_profile_id)
        verify_local_config(user_id, "stt", result)
        return result
    return wrapped


def _bind_task_owner(folder, output_dir, owner):
    """Bind authenticated ownership before any model lookup can fail."""
    marker = folder / "recording_owner"
    with _SNAPSHOT_LOCK:
        if (folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
                or folder.resolve().parent != Path(output_dir).resolve()):
            raise HTTPException(404, "Task not found")

        def check_existing():
            try:
                info = marker.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise HTTPException(404, "Task not found")
                if marker.read_text(encoding="utf-8") != owner:
                    raise HTTPException(404, "Task not found")
            except (OSError, UnicodeError):
                raise HTTPException(404, "Task not found") from None

        if marker.exists() or marker.is_symlink():
            check_existing()
            return
        if not owner:
            return
        # Exclusive creation must never truncate/replace an existing owner.
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            check_existing()
            return
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(owner)


def freeze_generation_models(function):
    """Enter durable source before preflight/preparation, including direct callers."""
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        from app.services.vilab_cloud_service import VILabCloudService
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        service = values["self"]
        folder = service.artifact_service.create_task_dir(values["task_id"])
        owner = values.get("user_id")
        _bind_task_owner(folder, service.artifact_service.output_dir, owner)
        try:
            state = service.artifact_service.get_status(values["task_id"])
            options = dict(values, needs_stt=function.__name__ != "generate_from_transcript")
            source = ensure_source(folder, owner, options,
                allow_capture=not (folder / "request.json").exists() and state.get("status") not in {"failed", "error", "success"})
            with VILabCloudService().task_snapshot(owner, snapshot=source):
                return function(*args, **kwargs)
        except Exception as error:
            failed = service.artifact_service.find_task_dir(values["task_id"]) or folder
            service.artifact_service.update_status(failed, "failed", getattr(error, "detail", str(error)), retryable=True)
            raise
    return wrapped
