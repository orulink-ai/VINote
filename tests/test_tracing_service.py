from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import tracing_service as tracing


@pytest.fixture
def recorder(monkeypatch):
    spans = []

    @contextmanager
    def start(**fields):
        span = Mock()
        spans.append((fields, span))
        yield span

    monkeypatch.setattr(tracing, "get_client", lambda: SimpleNamespace(start_as_current_observation=start))
    monkeypatch.setattr(tracing.settings, "langfuse_capture_content", False)
    return spans


def test_disabled_does_not_initialize_sdk(monkeypatch):
    monkeypatch.setattr(tracing.settings, "langfuse_enabled", False)
    assert tracing.get_client() is None


def test_trace_id_failure_does_not_break_task_status():
    class BrokenSpan:
        @property
        def trace_id(self):
            raise RuntimeError('SDK unavailable')

    token = tracing._active_span.set(BrokenSpan())
    try:
        assert tracing.current_trace_id() is None
    finally:
        tracing._active_span.reset(token)


def test_desktop_config_can_explicitly_disable_tracing(tmp_path, monkeypatch):
    from scripts.desktop_backend import configure_langfuse
    import os

    for key in ('LANGFUSE_ENABLED', 'LANGFUSE_BASE_URL', 'LANGFUSE_PUBLIC_KEY',
                'LANGFUSE_SECRET_KEY', 'LANGFUSE_CAPTURE_CONTENT', 'LANGFUSE_TRACING_ENVIRONMENT'):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / 'langfuse.env').write_text(
        'LANGFUSE_BASE_URL=http://localhost:3000\nLANGFUSE_PUBLIC_KEY=pk-test\n'
        'LANGFUSE_SECRET_KEY=sk-test\nLANGFUSE_ENABLED=false\n', encoding='utf-8',
    )
    configure_langfuse(tmp_path)
    assert os.environ['LANGFUSE_ENABLED'] == 'false'


@pytest.mark.parametrize("phase", ["start", "update", "close"])
def test_exporter_failure_does_not_fail_or_repeat_business_call(monkeypatch, phase):
    @contextmanager
    def start(**fields):
        if phase == "start":
            raise RuntimeError("unavailable")
        span = Mock()
        if phase == "update":
            span.update.side_effect = RuntimeError("unavailable")
        yield span
        if phase == "close":
            raise RuntimeError("unavailable")

    monkeypatch.setattr(tracing, "get_client", lambda: SimpleNamespace(start_as_current_observation=start))
    business = Mock(return_value=SimpleNamespace(markdown="result"))

    @tracing.traced("test", root=True)
    def run(task_id):
        return business()

    assert run("task").markdown == "result"
    business.assert_called_once()


def test_error_is_preserved_and_secrets_not_recorded(recorder):
    error = ValueError("api-key=private")

    @tracing.traced("test", root=True)
    def run(task_id, api_key):
        raise error

    with pytest.raises(ValueError) as caught:
        run("task", "secret")
    assert caught.value is error
    fields, span = recorder[0]
    assert fields["metadata"] == {"task_id": "task", "input_type": "test"}
    span.update.assert_called_once_with(level="ERROR", status_message="ValueError")


def test_generation_usage_and_content_toggle(recorder, monkeypatch):
    class Model:
        model = "test-model"

        @tracing.traced_generation
        def complete(self, **kwargs):
            tracing.record_usage({"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
            return "answer"

    model = Model()
    assert model.complete(system_prompt="system", user_prompt="private") == "answer"
    fields, span = recorder[-1]
    assert fields["input"][1]["content"] == {"redacted": True, "chars": 7}
    span.update.assert_any_call(usage_details={"input": 3, "output": 2, "total": 5})
    assert tracing._generation.get() is None
    monkeypatch.setattr(tracing.settings, "langfuse_capture_content", True)
    model.complete(system_prompt="system", user_prompt="private")
    fields, span = recorder[-1]
    assert fields["input"][1]["content"] == "private"
    span.update.assert_any_call(output="answer")


def test_real_sdk_parentage_and_concurrent_task_isolation(monkeypatch):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    client = Langfuse(public_key="pk-lf-unit-test", secret_key="unit-test",
                      base_url="http://127.0.0.1:1", tracer_provider=provider, span_exporter=exporter)
    monkeypatch.setattr(tracing, "get_client", lambda: client)

    @tracing.traced("child")
    def child():
        return True

    @tracing.traced("root", root=True)
    def run(task_id):
        assert child()
        return SimpleNamespace(markdown="done")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, ["task-a", "task-b"]))
        client.flush()
        spans = exporter.get_finished_spans()
        roots = [span for span in spans if span.name == "root"]
        children = [span for span in spans if span.name == "child"]
        assert len(roots) == len(children) == 2
        assert len({span.context.trace_id for span in roots}) == 2
        for child_span in children:
            parent = next(span for span in roots if span.context.trace_id == child_span.context.trace_id)
            assert child_span.parent.span_id == parent.context.span_id
    finally:
        client.shutdown()


def test_desktop_incomplete_config_does_not_mix_credentials(tmp_path, monkeypatch):
    from scripts.desktop_backend import configure_langfuse

    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "unrelated-project")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "unrelated-project")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://unrelated")
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "true")
    (tmp_path / "langfuse.env").write_text("LANGFUSE_BASE_URL=http://localhost:3000", encoding="utf-8")
    configure_langfuse(tmp_path)
    import os
    assert os.environ["LANGFUSE_ENABLED"] == "false"
    assert os.environ["LANGFUSE_SECRET_KEY"] == ""
    assert os.environ["LANGFUSE_PUBLIC_KEY"] == ""
    assert os.environ["LANGFUSE_CAPTURE_CONTENT"] == "false"


def test_desktop_config_enables_project_without_content_capture(tmp_path, monkeypatch):
    from scripts.desktop_backend import configure_langfuse
    import os

    for key in ("LANGFUSE_BASE_URL", "LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY",
                "LANGFUSE_ENABLED", "LANGFUSE_CAPTURE_CONTENT", "LANGFUSE_TRACING_ENVIRONMENT"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "langfuse.env").write_text(
        "LANGFUSE_BASE_URL=http://localhost:3000\nLANGFUSE_PUBLIC_KEY=pk-test\nLANGFUSE_SECRET_KEY=sk-test\n",
        encoding="utf-8",
    )
    configure_langfuse(tmp_path)
    assert os.environ["LANGFUSE_ENABLED"] == "true"
    assert os.environ["LANGFUSE_CAPTURE_CONTENT"] == "false"
    assert os.environ["LANGFUSE_TRACING_ENVIRONMENT"] == "production"
