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
    with tracing.desktop_trace(tracing.DesktopTraceContext(
        workflow="meeting", source="local_file", media_type="audio",
    )):
        yield spans


def test_disabled_does_not_initialize_sdk(monkeypatch):
    monkeypatch.setattr(tracing.settings, "langfuse_enabled", False)
    assert tracing.get_client() is None


def test_browser_request_does_not_initialize_sdk(monkeypatch):
    get_client = Mock()
    monkeypatch.setattr(tracing, "get_client", get_client)

    with tracing.observation("browser"):
        pass

    get_client.assert_not_called()


def test_root_names_follow_desktop_workflow(recorder):
    from app.models.audio import AudioDownloadResult
    from app.models.transcript import TranscriptResult

    @tracing.traced("legacy", root=True, as_type="chain")
    def run(task_id):
        return SimpleNamespace(
            markdown="# 结果",
            audio_meta=AudioDownloadResult(file_path="", title="test", duration=1,
                                           video_id=task_id, platform="local", raw_info={}),
            transcript=TranscriptResult(language="zh", full_text="输入", segments=[]),
        )

    run("meeting-task")
    assert recorder[-1][0]["name"] == "桌面端｜会议纪要"
    with tracing.desktop_trace(tracing.DesktopTraceContext(
        workflow="note_organization", source="local_file", media_type="audio",
    )):
        run("note-task")
    assert recorder[-1][0]["name"] == "桌面端｜笔记整理"
    with tracing.desktop_trace(tracing.DesktopTraceContext(
        workflow="synthetic", source="build_check", media_type="transcript",
    )):
        run("synthetic-task")
    assert recorder[-1][0]["name"] == "桌面端｜笔记整理"


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

    with tracing.desktop_trace(tracing.DesktopTraceContext(
        workflow="meeting", source="local_file", media_type="audio",
    )):
        assert run("task").markdown == "result"
    business.assert_called_once()


def test_error_is_preserved_and_secrets_not_recorded(recorder):
    error = ValueError("api-key=private token=second password=third https://user:pass@example.test/path")

    @tracing.traced("test", root=True)
    def run(task_id, api_key):
        raise error

    with pytest.raises(ValueError) as caught:
        run("task", "secret")
    assert caught.value is error
    fields, span = recorder[0]
    assert fields["metadata"]["task_id"] == "task"
    assert fields["metadata"]["workflow"] == "meeting"
    failure = span.update.call_args.kwargs
    assert failure["level"] == "ERROR"
    message = failure["output"]["error_message"]
    assert "private" not in message
    assert "second" not in message
    assert "third" not in message
    assert "user:pass" not in message


def test_desktop_generation_records_complete_input_output(recorder):
    class Model:
        model = "test-model"

        @tracing.traced_generation
        def complete(self, **kwargs):
            tracing.record_usage({"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
            return "answer"

    model = Model()
    assert model.complete(system_prompt="system", user_prompt="private") == "answer"
    fields, span = recorder[-1]
    assert fields["input"][1]["content"] == "private"
    span.update.assert_any_call(usage_details={"input": 3, "output": 2, "total": 5})
    assert tracing._generation.get() is None
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
    def traced_run(task_id):
        assert child()
        return SimpleNamespace(markdown="done")

    def run(task_id):
        with tracing.desktop_trace(tracing.DesktopTraceContext(
            workflow="meeting", source="local_file", media_type="audio",
        )):
            return traced_run(task_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, ["task-a", "task-b"]))
        client.flush()
        spans = exporter.get_finished_spans()
        roots = [span for span in spans if span.name == "桌面端｜会议纪要"]
        children = [span for span in spans if span.name == "child"]
        assert len(roots) == len(children) == 2
        assert len({span.context.trace_id for span in roots}) == 2
        for child_span in children:
            parent = next(span for span in roots if span.context.trace_id == child_span.context.trace_id)
            assert child_span.parent.span_id == parent.context.span_id
    finally:
        client.shutdown()


@pytest.mark.parametrize("environment", ["test", "production"])
def test_desktop_tracing_uses_bundle_not_inherited_credentials(environment, monkeypatch):
    from scripts.desktop_backend import configure_langfuse
    import os

    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.setenv(key, "unrelated-project")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "true")
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "development")
    configure_langfuse({
        "LANGFUSE_BASE_URL": "http://localhost:3000", "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test", "LANGFUSE_TRACING_ENVIRONMENT": environment,
    })
    assert os.environ["LANGFUSE_ENABLED"] == "true"
    assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-test"
    assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-test"
    assert os.environ["LANGFUSE_CAPTURE_CONTENT"] == "true"
    assert os.environ["LANGFUSE_TRACING_ENVIRONMENT"] == environment


def test_incomplete_bundle_cannot_use_inherited_credentials(monkeypatch):
    from scripts.desktop_backend import configure_langfuse

    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "unrelated-project")
    with pytest.raises(RuntimeError, match="incomplete"):
        configure_langfuse({"LANGFUSE_BASE_URL": "http://localhost:3000", "LANGFUSE_PUBLIC_KEY": "pk-test"})


def test_source_tracing_cannot_be_disabled_by_legacy_switch(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    assert Settings().langfuse_enabled is True


def test_missing_project_credentials_fail_startup_without_printing_keys(monkeypatch):
    monkeypatch.setattr(tracing.settings, 'langfuse_enabled', True)
    monkeypatch.setattr(tracing.settings, 'desktop_runtime', True)
    monkeypatch.setattr(tracing.settings, 'langfuse_secret_key', '')
    with pytest.raises(RuntimeError, match='configuration is required'):
        tracing.validate_configuration()


def test_sdk_legacy_switch_cannot_disable_product_tracing(monkeypatch):
    import langfuse
    import os

    monkeypatch.setenv('LANGFUSE_TRACING_ENABLED', 'false')
    monkeypatch.setattr(tracing, '_client', None)
    monkeypatch.setattr(tracing.settings, 'langfuse_enabled', True)
    monkeypatch.setattr(tracing.settings, 'langfuse_public_key', 'pk-test')
    monkeypatch.setattr(tracing.settings, 'langfuse_secret_key', 'sk-test')
    monkeypatch.setattr(tracing.settings, 'langfuse_base_url', 'http://localhost:3000')
    constructor = Mock()
    monkeypatch.setattr(langfuse, 'Langfuse', constructor)
    assert tracing.get_client() is constructor.return_value
    assert os.environ['LANGFUSE_TRACING_ENABLED'] == 'true'
    assert constructor.call_args.kwargs['sample_rate'] == 1.0
    tracing.shutdown()
