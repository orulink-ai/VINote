"""Server-managed VILab access, independent of ViTalk accounts."""
import httpx
import time
import logging
import math
import json
from contextlib import contextmanager
from contextvars import ContextVar
from fastapi import HTTPException

from app.config import settings
from app.db import session_scope
from app.db_models import VILabPreferenceDB

_task_source: ContextVar[tuple[str, dict] | None] = ContextVar("vinote_task_model_source", default=None)
logger = logging.getLogger(__name__)


def _chat_failure(response):
    """Project a bounded error envelope; never expose/log arbitrary messages."""
    payload = {}
    try:
        raw = bytearray()
        for block in response.iter_bytes(chunk_size=4096):
            if len(raw) + len(block) > 65536:
                break
            raw.extend(block)
        else:
            payload = json.loads(raw)
    except (httpx.HTTPError, ValueError, UnicodeError):
        pass
    error = payload.get('error') if isinstance(payload, dict) else None
    error = error if isinstance(error, dict) else {}
    codes = {'unauthorized', 'account_disabled', 'authentication_unavailable',
             'invalid_api_key', 'authentication_error', 'permission_denied',
             'access_denied', 'insufficient_quota', 'rate_limit_exceeded'}
    types = {'vilab_error', 'invalid_request_error', 'authentication_error',
             'permission_error', 'rate_limit_error', 'insufficient_quota'}
    code = error.get('code')
    kind = error.get('type')
    code = code if isinstance(code, str) and code in codes else None
    kind = kind if isinstance(kind, str) and kind in types else None
    status = response.status_code
    category = 'unclassified_rejection'
    detail = f'云端模型或上游服务拒绝本次请求（HTTP {status}），原模型与已有转写保留。'
    public_status = 502
    if kind == 'vilab_error' and code == 'unauthorized' and status == 401:
        category, detail = 'caller_auth', '云端服务未接受当前身份，请检查账号登录及服务端可信身份来源配置'
    elif kind == 'vilab_error' and code == 'account_disabled' and status == 403:
        category, detail = 'caller_disabled', '云端服务账号已停用，请联系服务管理员。'
    elif kind == 'vilab_error' and code == 'authentication_unavailable' and status in {500, 503}:
        category, detail = 'caller_auth_unavailable', '云端账号认证服务暂时不可用，请稍后核验服务状态。'
        public_status = 503
    elif code in {'invalid_api_key', 'authentication_error'} and status in {401, 403}:
        category, detail = 'provider_auth', f'上游模型服务鉴权失败（HTTP {status}），请管理员检查模型服务凭证。'
    elif code in {'permission_denied', 'access_denied'} and status in {401, 403}:
        category, detail = 'provider_permission', f'上游模型服务拒绝访问权限（HTTP {status}），请管理员核验所选模型权限。'
    elif code == 'insufficient_quota' and status in {402, 403, 429}:
        category, detail = 'provider_quota', f'上游模型服务额度不足（HTTP {status}），请管理员核验。'
    diagnostic = {'category': category, 'http_status': status}
    if code:
        diagnostic['error_code'] = code
    if kind:
        diagnostic['error_type'] = kind
    logger.warning('Cloud chat rejected: %s', diagnostic)
    failure = HTTPException(public_status, detail)
    failure.cloud_failure_context = diagnostic
    return failure


class VILabCloudService:
    def _request_chat_stream(self, method, path, headers, timeout, kwargs, *, server_url=None):
        from app.services.cloud_chat_stream import collect_chat_stream

        # POST/stream interruption cannot prove inference did not run. Never
        # replay automatically, including after response headers or partials.
        started = time.monotonic()
        received_headers = False
        try:
            with httpx.stream(method, (server_url or settings.vilab_server_url) + path,
                              headers=headers, timeout=timeout, **kwargs) as response:
                received_headers = True
                if not response.is_success:
                    raise _chat_failure(response)
                return collect_chat_stream(response, started=started)
        except httpx.RequestError as error:
            logger.warning('Cloud chat transport failed: kind=%s attempt=1 headers=%s elapsed_seconds=%.1f',
                           type(error).__name__, received_headers, time.monotonic() - started)
            detail = ('云端模型响应超时，结果尚未确认，未自动重试' if isinstance(error, httpx.TimeoutException)
                      else '云端模型响应连接中断，结果尚未确认，未自动重试' if received_headers
                      else '无法连接云端模型服务，结果尚未确认，未自动重试')
            raise HTTPException(502, detail) from None

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
        snapshot = _task_source.get()
        if snapshot and snapshot[0] == user_id:
            models = self.models(user_id)
            self._validate_selection(models, defaults["llm_model"], "llm")
            if needs_stt:
                self._validate_selection(models, defaults["asr_model"], "asr")


    def defaults(self, user_id):
        snapshot = _task_source.get()
        if snapshot and snapshot[0] == user_id:
            return dict(snapshot[1])
        preferences = self.status(user_id)
        selections = {key: preferences.get(key) for key in ("asr_model", "llm_model")}
        # 完整且可用的显式选择不依赖旧版服务的默认模型配置。
        if all(selections.values()):
            models = self.models(user_id)
            self._validate_selection(models, selections["asr_model"], "asr")
            self._validate_selection(models, selections["llm_model"], "llm")
            return selections
        defaults = self.request(user_id, "GET", "/v1/default-models")
        if any(selections.values()):
            models = self.models(user_id)
            for key, kind in (("asr_model", "asr"), ("llm_model", "llm")):
                selected = selections[key]
                if selected:
                    self._validate_selection(models, selected, kind)
                    defaults[key] = selected
        return defaults

    @staticmethod
    def _validate_selection(models, name, kind):
        model = next((model for model in models if model["id"] == name and model["modelType"] == kind), None)
        allowed = False
        if model:
            runtime = model.get("runtimeStatus")
            health = model.get("availability")
            if health is None:
                allowed = runtime == "available"
            elif isinstance(health, dict):
                status = health.get("status")
                if status == "available":
                    allowed = runtime == "available"
                elif status in {"service_error", "rate_limited"} and runtime in {"available", "not_available", "unavailable"}:
                    retry_at = health.get("retryAt")
                    allowed = (type(retry_at) in (int, float) and 0 < retry_at <= time.time() * 1000
                               and math.isfinite(retry_at))
        if not allowed:
            raise HTTPException(400, "所选云端模型当前不可用，原模型已保留；请在恢复可用后重试或明确确认新的生成操作")


    def request(self, user_id, method, path, **kwargs):
        if not settings.vilab_server_url:
            raise HTTPException(503, "云端模型服务尚未配置，请联系管理员")
        server_url = self.status(user_id).get("server_url") or settings.vilab_server_url
        headers = {}
        if settings.content_cloud_runtime:
            from app.services.cloud_content_identity import content_bearer
            headers["Authorization"] = "Bearer " + content_bearer(user_id)
        elif settings.cloud_auth_url:
            from app.services.cloud_account_service import CloudAccountService
            headers["Authorization"] = "Bearer " + CloudAccountService().access_token(user_id)
        elif settings.vilab_api_key:
            headers["Authorization"] = "Bearer " + settings.vilab_api_key
        try:
            timeout = kwargs.pop("timeout", 300)
            if path == "/openai/v1/chat/completions" and (kwargs.get("json") or {}).get("stream") is True:
                return self._request_chat_stream(method, path, headers, timeout, kwargs, server_url=server_url)
            response = httpx.request(method, server_url + path,
                                    headers=headers, timeout=timeout, **kwargs)
        except httpx.RequestError as error:
            logger.warning("Cloud request transport failed: kind=%s", type(error).__name__)
            raise HTTPException(502, "无法连接云端模型服务，请稍后重试") from None
        if path == '/openai/v1/chat/completions' and not response.is_success:
            raise _chat_failure(response)
        if response.status_code in {401, 403}:
            raise HTTPException(502, "云端服务未接受当前身份，请检查账号登录及服务端可信身份来源配置")
        if not response.is_success:
            if response.status_code == 503:
                try:
                    cloud_error = response.json().get("error")
                    message = cloud_error.get("message") if isinstance(cloud_error, dict) else cloud_error
                except (ValueError, AttributeError):
                    message = None
                if message == "Account authentication is temporarily unavailable":
                    raise HTTPException(503, "云端账号认证服务暂时不可用（HTTP 503），请稍后重试；若持续出现，请联系服务管理员检查认证服务。")
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
    def task_snapshot(self, user_id, *, snapshot=None):
        """An in-flight task keeps its model mode if the user switches modes."""
        if not user_id:
            yield
            return
        config = dict(snapshot) if snapshot is not None else self.status(user_id)
        if snapshot is None and config["mode"] == "cloud":
            config.update(self.defaults(user_id))
        config.setdefault("configured", bool(config.get("server_url")))
        token = _task_source.set((user_id, config))
        try:
            yield
        finally:
            _task_source.reset(token)

    def models(self, user_id):
        data = self.request(user_id, "GET", "/v1/models")
        return [{"id": m["id"], "modelType": m["modelType"], "runtimeStatus": m.get("runtimeStatus", ""),
                 **({"availability": m["availability"]} if "availability" in m else {}),
                 **({"capabilities": m["capabilities"]} if isinstance(m.get("capabilities"), dict) else {}),
                 **{key: value.strip() for key in ("name", "providerId", "providerModel")
                    if isinstance(value := m.get(key), str) and 0 < len(value) <= 120
                    and value.strip() and "://" not in value
                    and not any(ord(char) < 32 or ord(char) == 127 for char in value)}}
                for m in data.get("data", []) if isinstance(m, dict) and isinstance(m.get("id"), str) and m.get("modelType") in {"asr", "llm"}]

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
