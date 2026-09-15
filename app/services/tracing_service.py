"""Always-enabled Langfuse tracing; exporter failures do not interrupt generation."""
import atexit
import hashlib
import hmac
import inspect
import logging
import os
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


def validate_configuration():
    """Reject missing deployment credentials instead of silently running unobserved."""
    if settings.langfuse_enabled and not all((value or '').strip() for value in (
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


@contextmanager
def observation(name, *, root=None, **fields):
    stack = ExitStack()
    span = None
    try:
        client = get_client()
        if client is not None:
            if root is not None:
                from langfuse import propagate_attributes
                user_id = root.get("user_id")
                if user_id:
                    user_id = hmac.new(settings.app_jwt_secret.encode(),
                                       str(user_id).encode(), hashlib.sha256).hexdigest()
                stack.enter_context(propagate_attributes(
                    session_id=root.get("task_id"), user_id=user_id,
                    trace_name=name, tags=["vinote", "note-generation"],
                ))
            span = stack.enter_context(client.start_as_current_observation(name=name, **fields))
    except Exception:
        logger.warning("Langfuse span initialization failed")
    token = _active_span.set(span)
    try:
        yield span
    except BaseException as exc:
        # Provider exceptions can contain credentials or complete request bodies.
        _update(span, level="ERROR", status_message=type(exc).__name__)
        raise
    finally:
        _active_span.reset(token)
        try:
            # Do not pass business exceptions to the SDK's automatic recorder.
            stack.close()
        except Exception:
            logger.warning("Langfuse span finalization failed")


def content_summary(text):
    return text if settings.langfuse_capture_content else {"redacted": True, "chars": len(text)}


def update_current(**fields):
    _update(_active_span.get(), **fields)


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
            metadata = {key: values[key] for key in (
                "task_id", "style", "summary_mode", "output_language"
            ) if key in values}
            if root:
                metadata["input_type"] = {"generate": "url", "generate_from_file": "file",
                                          "generate_from_transcript": "transcript"}.get(func.__name__, "test")
            with observation(name, root=values if root else None, metadata=metadata, as_type=as_type) as span:
                result = func(*args, **kwargs)
                if root:
                    output = {"status": "success"}
                    output["markdown"] = content_summary(result.markdown)
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
        with observation("调用大模型生成笔记", **fields) as span:
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
