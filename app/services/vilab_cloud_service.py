"""Server-managed VILab access, independent of ViTalk accounts."""
import httpx
from contextlib import contextmanager
from contextvars import ContextVar
from fastapi import HTTPException

from app.config import settings
from app.db import session_scope
from app.db_models import VILabPreferenceDB

_task_source: ContextVar[tuple[str, dict] | None] = ContextVar("vinote_task_model_source", default=None)


class VILabCloudService:
    def validate_ready(self, user_id, *, needs_stt=True):
        if not user_id:
            return
        config = self.status(user_id)
        if config["mode"] != "cloud":
            return
        if not config["configured"]:
            raise ValueError("云端服务尚未配置，请联系管理员或切换到本地模式")
        defaults = self.defaults(user_id)
        if not defaults.get("llm_model") or (needs_stt and not defaults.get("asr_model")):
            raise ValueError("云端当前模型未配置，请联系服务管理员")

    def defaults(self, user_id):
        snapshot = _task_source.get()
        if snapshot and snapshot[0] == user_id:
            return dict(snapshot[1])
        defaults = self.request(user_id, "GET", "/v1/default-models")
        preferences = self.status(user_id)
        selections = {key: preferences.get(key) for key in ("asr_model", "llm_model")}
        if any(selections.values()):
            models = self.models(user_id)
            for key, kind in (("asr_model", "asr"), ("llm_model", "llm")):
                selected = selections[key]
                if selected:
                    try:
                        self._validate_selection(models, selected, kind)
                    except HTTPException:
                        fallback = defaults.get(key)
                        self._validate_selection(models, fallback, kind)
                        from app.services.tracing_service import observation, update_current
                        with observation("云端模型选择回退"):
                            update_current(input={"kind": kind, "unavailable_model": selected},
                                           output={"model": fallback, "reason": "saved_selection_unavailable"})
                    else:
                        defaults[key] = selected
        return defaults

    @staticmethod
    def _validate_selection(models, name, kind):
        if not any(model["id"] == name and model["modelType"] == kind
                   and model.get("runtimeStatus") == "available" for model in models):
            raise HTTPException(400, "所选云端模型当前不可用，请重新选择可用模型或跟随服务默认")

    def request(self, user_id, method, path, **kwargs):
        if not settings.vilab_server_url:
            raise HTTPException(503, "云端模型服务尚未配置，请联系管理员")
        headers = {}
        if settings.cloud_auth_url:
            from app.services.cloud_account_service import CloudAccountService
            headers["Authorization"] = "Bearer " + CloudAccountService().access_token(user_id)
        elif settings.vilab_api_key:
            headers["Authorization"] = "Bearer " + settings.vilab_api_key
        try:
            timeout = kwargs.pop("timeout", 300)
            response = httpx.request(method, settings.vilab_server_url + path,
                                    headers=headers, timeout=timeout, **kwargs)
        except httpx.RequestError:
            raise HTTPException(502, "无法连接云端模型服务，请稍后重试") from None
        if response.status_code in {401, 403}:
            raise HTTPException(502, "云端服务未接受当前身份，请检查账号登录及服务端可信身份来源配置")
        if not response.is_success:
            if path == "/v1/asr/transcriptions" and response.status_code == 502:
                try:
                    message = response.json().get("error", {}).get("message")
                except (ValueError, AttributeError):
                    message = None
                if message in {
                    "Aliyun ASR returned an empty transcript.",
                    "Volcengine ASR returned an empty transcript.",
                }:
                    from app.models.transcript import NoSpeechDetectedError
                    raise NoSpeechDetectedError("该音频片段未识别出文字")
            raise HTTPException(502, f"云端模型请求失败（HTTP {response.status_code}）")
        return response.json()

    def status(self, user_id):
        snapshot = _task_source.get()
        if snapshot and snapshot[0] == user_id:
            return dict(snapshot[1])
        with session_scope() as db:
            row = db.get(VILabPreferenceDB, user_id)
            return {"configured": bool(settings.vilab_server_url),
                    "server_url": settings.vilab_server_url,
                    "mode": row.mode if row else ("cloud" if settings.vilab_server_url else "local"),
                    "asr_model": row.asr_model if row else "", "llm_model": row.llm_model if row else ""}

    @contextmanager
    def task_snapshot(self, user_id):
        """An in-flight task keeps its model mode if the user switches modes."""
        if not user_id:
            yield
            return
        config = self.status(user_id)
        if config["mode"] == "cloud":
            config.update(self.defaults(user_id))
        token = _task_source.set((user_id, config))
        try:
            yield
        finally:
            _task_source.reset(token)

    def models(self, user_id):
        data = self.request(user_id, "GET", "/v1/models")
        return [{"id": m["id"], "modelType": m["modelType"], "runtimeStatus": m.get("runtimeStatus", "")}
                for m in data.get("data", []) if isinstance(m.get("id"), str) and m.get("modelType") in {"asr", "llm"}]

    def select(self, user_id, mode, asr_model, llm_model):
        if mode == "cloud":
            models = self.models(user_id)
            for name, kind in [(asr_model, "asr"), (llm_model, "llm")]:
                if name:
                    self._validate_selection(models, name, kind)
        with session_scope() as db:
            row = db.get(VILabPreferenceDB, user_id)
            if not row:
                row = VILabPreferenceDB(user_id=user_id)
                db.add(row)
            row.mode = mode
            if mode == "cloud":
                row.asr_model, row.llm_model = asr_model, llm_model
        return self.status(user_id)

    def set_mode(self, user_id, mode):
        """Persist the app-wide mode even when the cloud service is unavailable."""
        with session_scope() as db:
            row = db.get(VILabPreferenceDB, user_id)
            if not row:
                row = VILabPreferenceDB(user_id=user_id)
                db.add(row)
            row.mode = mode
        return self.status(user_id)
