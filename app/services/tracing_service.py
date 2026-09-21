"""Desktop-only Langfuse tracing; exporter failures do not interrupt generation."""
import atexit
import hashlib
import hmac
import inspect
import logging
import os
import re
from dataclasses import dataclass
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock

from app.config import settings

logger = logging.getLogger(__name__)
_client = None
_lock = Lock()
_generation = ContextVar("vinote_generation", default=None)
_active_span = ContextVar("vinote_span", default=None)
_trace_context = ContextVar("vinote_trace_context", default=None)
_generation_name = ContextVar("vinote_generation_name", default=None)


@dataclass(frozen=True)
class DesktopTraceContext:
    workflow: str
    source: str
    media_type: str
    client_version: str = ""
    channel: str = ""
    session_id: str = ""
    input: dict | None = None

    @property
    def trace_name(self):
        return "桌面端｜会议纪要" if self.workflow == "meeting" else "桌面端｜笔记整理"


@contextmanager
def desktop_trace(context: DesktopTraceContext | None):
    """Scope tracing to an explicitly identified desktop generation task."""
    token = _trace_context.set(context)
    try:
        yield
    finally:
        _trace_context.reset(token)


@contextmanager
def generation_name(name: str):
    token = _generation_name.set(name)
    try:
        yield
    finally:
        _generation_name.reset(token)


def validate_configuration():
    """Reject missing deployment credentials instead of silently running unobserved."""
    if settings.desktop_runtime and settings.langfuse_enabled and not all((value or '').strip() for value in (
        settings.langfuse_base_url, settings.langfuse_public_key, settings.langfuse_secret_key,
    )):
        raise RuntimeError('Langfuse project configuration is required; configure backend credentials')


def get_client():
    global _client
    if not (settings.langfuse_enabled and settings.langfuse_public_key
            and settings.langfuse_secret_key and settings.langfuse_base_url):
        return None
    with _lock:
        if _client is None:
            try:
                from langfuse import Langfuse
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                provider = TracerProvider(resource=Resource.create({
                    "service.name": "vinote-backend",
                    "service.version": settings.langfuse_release,
                    "deployment.environment.name": settings.langfuse_environment,
                }))
                # The SDK also reads its own legacy switch; keep product policy authoritative.
                os.environ['LANGFUSE_TRACING_ENABLED'] = 'true'
                _client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    base_url=settings.langfuse_base_url,
                    environment=settings.langfuse_environment,
                    release=settings.langfuse_release,
                    tracer_provider=provider,
                    timeout=5,
                    sample_rate=1.0,
                )
                atexit.register(shutdown)
            except Exception:
                logger.warning("Langfuse initialization failed; continuing without tracing")
    return _client


def shutdown():
    global _client
    client, _client = _client, None
    if client is not None:
        try:
            client.shutdown()
        except Exception:
            logger.warning("Langfuse shutdown failed")


def _update(span, **fields):
    if span is not None:
        try:
            span.update(**fields)
        except Exception:
            logger.warning("Langfuse update failed")


def _safe_error_message(exc: BaseException) -> str:
    value = getattr(exc, "detail", None)
    text = str(value if isinstance(value, str) else exc)
    text = re.sub(r"(?i)(authorization:\s*bearer)\s+\S+", r"\1 <redacted>", text)
    text = re.sub(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|password)\b"
        r"(\s*[=:]\s*)[^\s,;&]+",
        r"\1\2<redacted>",
        text,
    )
    text = re.sub(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@", r"\1<redacted>@", text)
    text = re.sub(r"[A-Za-z]:\\[^\r\n]+", "<local-path>", text)
    return text[:500]


@contextmanager
def observation(name, *, root=None, **fields):
    stack = ExitStack()
    span = None
    try:
        trace_context = _trace_context.get()
        client = get_client() if trace_context is not None else None
        if client is not None:
            if root is not None:
                from langfuse import propagate_attributes
                user_id = root.get("user_id")
                if user_id:
                    user_id = hmac.new(settings.app_jwt_secret.encode(),
                                       str(user_id).encode(), hashlib.sha256).hexdigest()
                stack.enter_context(propagate_attributes(
                    session_id=trace_context.session_id or root.get("task_id"), user_id=user_id,
                    trace_name=name, tags=["vinote", "desktop", trace_context.workflow],
                ))
            span = stack.enter_context(client.start_as_current_observation(name=name, **fields))
    except Exception:
        logger.warning("Langfuse span initialization failed")
    token = _active_span.set(span)
    try:
        yield span
    except BaseException as exc:
        # Provider exceptions can contain credentials or complete request bodies.
        _update(span, level="ERROR", status_message=type(exc).__name__,
                output={"status": "failed", "error_type": type(exc).__name__,
                        "error_message": _safe_error_message(exc)})
        raise
    finally:
        _active_span.reset(token)
        try:
            # Do not pass business exceptions to the SDK's automatic recorder.
            stack.close()
        except Exception:
            logger.warning("Langfuse span finalization failed")


def content_summary(text):
    return text if _trace_context.get() is not None else {"redacted": True, "chars": len(text)}


def update_current(**fields):
    _update(_active_span.get(), **fields)


def update_trace_input(**fields):
    context = _trace_context.get()
    if context is None:
        return
    payload = dict(context.input or {})
    payload.update(fields)
    _update(_active_span.get(), input=payload)


def current_trace_id():
    span = _active_span.get()
    try:
        return getattr(span, "trace_id", None) if span is not None else None
    except Exception:
        logger.warning("Langfuse trace ID unavailable")
        return None


def traced(name, *, root=False, as_type="span"):
    def decorate(func):
        signature = inspect.signature(func)

        @wraps(func)
        def wrapped(*args, **kwargs):
            values = {}
            if root:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                values = bound.arguments
            trace_context = _trace_context.get()
            resolved_name = trace_context.trace_name if root and trace_context else name
            metadata = {key: values[key] for key in (
                "task_id", "style", "summary_mode", "output_language"
            ) if key in values}
            if root:
                metadata.update({
                    "workflow": trace_context.workflow if trace_context else "",
                    "source": trace_context.source if trace_context else "",
                    "media_type": trace_context.media_type if trace_context else "",
                    "client_version": trace_context.client_version if trace_context else "",
                    "desktop_channel": trace_context.channel if trace_context else "",
                })
            fields = {"metadata": metadata, "as_type": as_type}
            if root and trace_context:
                fields["input"] = trace_context.input or {}
            with observation(resolved_name, root=values if root else None, **fields) as span:
                result = func(*args, **kwargs)
                if root and span is not None:
                    output = {
                        "status": "success",
                        "final_note": content_summary(result.markdown),
                    }
                    audio_meta = getattr(result, "audio_meta", None)
                    transcript = getattr(result, "transcript", None)
                    if audio_meta is not None:
                        output["duration_seconds"] = audio_meta.duration
                    if transcript is not None:
                        output["transcript_characters"] = len(transcript.full_text)
                        output["transcript_segments"] = len(transcript.segments)
                    _update(span, output=output)
                return result
        return wrapped
    return decorate


def traced_generation(func):
    @wraps(func)
    def wrapped(self, *, system_prompt, user_prompt):
        fields = {"as_type": "generation", "model": self.model,
                  "metadata": {"adapter": type(self).__name__, "streamed": False,
                               "prompt_version": hashlib.sha256(system_prompt.encode()).hexdigest()[:16]}}
        fields["input"] = [
            {"role": "system", "content": content_summary(system_prompt)},
            {"role": "user", "content": content_summary(user_prompt)},
        ]
        with observation(_generation_name.get() or "LLM｜生成内容", **fields) as span:
            token = _generation.set(span)
            try:
                result = func(self, system_prompt=system_prompt, user_prompt=user_prompt)
                _update(span, output=content_summary(result))
                return result
            finally:
                _generation.reset(token)
    return wrapped


def record_model_parameters(parameters):
    # Only fields actually sent by our adapters; no headers, URLs or credentials.
    allowed = {"temperature", "max_tokens", "stream", "reasoning_effort"}
    _update(_generation.get(), model_parameters={key: value for key, value in parameters.items()
                                                if key in allowed})


def record_usage(usage):
    if usage is None:
        return
    try:
        data = usage if isinstance(usage, dict) else usage.model_dump()
        normalized = {}
        for target, keys in {
            "input": ("prompt_tokens", "input_tokens"),
            "output": ("completion_tokens", "output_tokens"),
            "total": ("total_tokens",),
        }.items():
            for key in keys:
                if isinstance(data.get(key), int) and data[key] >= 0:
                    normalized[target] = data[key]
                    break
        if normalized:
            _update(_generation.get(), usage_details=normalized)
    except Exception:
        logger.warning("Langfuse usage recording failed")
