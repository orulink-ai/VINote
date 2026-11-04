import json
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.services.cloud_chat_stream import collect_chat_stream
from app.services.vilab_cloud_service import VILabCloudService


@pytest.fixture
def isolated_preferences(monkeypatch):
    # Transport tests must not read the developer's configured database.
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app.services import vilab_cloud_service

    @contextmanager
    def session():
        yield SimpleNamespace(get=lambda model, user_id: None)

    monkeypatch.setattr(vilab_cloud_service, "session_scope", session)


def response(events):
    return httpx.Response(200, text="".join(
        ": heartbeat\n\n" if event is None else "data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n"
        for event in events
    ))


def delta(text="", finish=None, **extra):
    return {"choices": [{"index": 0, "delta": {"content": text, **extra}, "finish_reason": finish}]}


def test_stream_line_and_event_timing_survives_remote_protocol_error(monkeypatch):
    from app.services.summary_failure import SummaryResultUnconfirmed
    from app.services.task_failure import failure_details
    clock = [100.0]
    monkeypatch.setattr("app.services.cloud_chat_stream.time.monotonic", lambda: clock[0])
    class Interrupted:
        def iter_lines(self):
            for when, line in [(101, ": PRIVATE heartbeat"), (101, ""),
                               (103, "data: " + json.dumps(delta("PRIVATE"))), (103, ""),
                               (110, ": heartbeat"), (110, "")]:
                clock[0] = when
                yield line
            clock[0] = 117
            raise httpx.RemoteProtocolError("SECRET")
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(Interrupted(), started=100)
    stream = failure_details(caught.value)["summary_failure_context"]["stream"]
    assert {k: stream[k] for k in ("first_line_ms", "last_line_ms", "idle_gap_ms",
                                    "line_count", "event_count")} == {
        "first_line_ms": 1000, "last_line_ms": 10000, "idle_gap_ms": 7000,
        "line_count": 6, "event_count": 1}
    assert "PRIVATE" not in json.dumps(stream) and "SECRET" not in json.dumps(stream)


def test_stream_timing_without_received_lines(monkeypatch):
    from app.services.summary_failure import SummaryResultUnconfirmed
    monkeypatch.setattr("app.services.cloud_chat_stream.time.monotonic", lambda: 105.0)
    class Empty:
        def iter_lines(self):
            raise httpx.RemoteProtocolError("SECRET")
            yield
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(Empty(), started=100)
    stream = caught.value.summary_failure_context["stream"]
    assert stream["first_line_ms"] is None and stream["last_line_ms"] is None
    assert stream["idle_gap_ms"] is None and stream["line_count"] == stream["event_count"] == 0


def direct_stream(client):
    def stream(*args, **kwargs):
        assert kwargs.pop('trust_env') is False
        return client.stream(*args, **kwargs)
    return stream


def test_collects_content_usage_and_ignores_reasoning_and_heartbeats():
    r = response([None, delta(reasoning_content="private reasoning"), delta("会议"),
                  delta("结论", "stop"), {"choices": [], "usage": {"total_tokens": 123}}, "[DONE]"])
    result = collect_chat_stream(r, started=time.monotonic())
    assert result["choices"][0]["message"]["content"] == "会议结论"
    assert result["usage"] == {"total_tokens": 123}


@pytest.mark.parametrize("events", [
    [delta("partial")], [delta("partial", "stop")],
    [delta("truncated", "length"), "[DONE]"], [delta("blocked", "content_filter"), "[DONE]"],
    [delta("partial"), {"error": {"message": "provider secret"}}], ["invalid json"],
    [{"choices": "invalid"}], [{"choices": [None]}],
    [{"choices": [{"delta": "invalid"}]}],
])
def test_never_accepts_partial_or_failed_output(events):
    with pytest.raises(HTTPException) as error:
        collect_chat_stream(response(events), started=time.monotonic())
    assert error.value.status_code == 502
    assert "provider secret" not in error.value.detail


def test_deadline_is_enforced_even_while_receiving_heartbeats():
    with pytest.raises(HTTPException) as error:
        collect_chat_stream(response([None]), started=time.monotonic() - 901)
    assert error.value.status_code == 504


def test_cloud_request_actually_uses_streaming_transport(isolated_preferences):
    seen = []
    def handler(request):
        seen.append(request)
        return response([delta("done", "stop"), "[DONE]"])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with patch("app.services.vilab_cloud_service.settings") as settings, patch("app.services.vilab_cloud_service.httpx.stream", side_effect=direct_stream(client)):
            settings.vilab_server_url = "https://example.test"
            settings.content_cloud_runtime = False
            settings.cloud_auth_url = ""
            settings.vilab_api_key = "test-key"
            result = VILabCloudService().request("user", "POST", "/openai/v1/chat/completions", json={"stream": True})
    assert result["choices"][0]["message"]["content"] == "done"
    assert seen[0].headers["authorization"] == "Bearer test-key"


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"discard me"}}]}\n\n'
        raise httpx.RemoteProtocolError("secret endpoint and credential")


def test_interrupted_stream_never_replays_inference_or_retains_partial_content(caplog, isolated_preferences):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, stream=BrokenStream())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
            patch("app.services.vilab_cloud_service.settings") as settings, \
            patch("app.services.vilab_cloud_service.httpx.stream", side_effect=direct_stream(client)), \
            patch("app.services.vilab_cloud_service.time.sleep"):
        settings.vilab_server_url = "https://example.test"
        settings.content_cloud_runtime = False
        settings.cloud_auth_url = ""
        settings.vilab_api_key = "test-key"
        with pytest.raises(HTTPException) as error:
            VILabCloudService().request("user", "POST", "/openai/v1/chat/completions", json={"stream": True})
        assert "连接中断" in error.value.detail
    assert len(seen) == 1
    assert "RemoteProtocolError" in caplog.text
    assert "secret endpoint" not in caplog.text
    assert "test-key" not in caplog.text

def test_partial_disconnect_diagnostic_survives_status_without_text(tmp_path):
    from app.services.summary_failure import SummaryResultUnconfirmed
    from app.services.task_failure import failure_details
    from app.services.task_artifact_service import TaskArtifactService
    class Interrupted:
        def iter_lines(self):
            yield 'data: ' + json.dumps({'id': 'chatcmpl-0123456789abcdef', 'choices': [{'delta': {'content': 'PRIVATE_CONTENT'}}]})
            yield ''
            raise httpx.ReadError('secret')
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(Interrupted(), started=time.monotonic())
    detail = failure_details(caught.value)
    stream = detail['summary_failure_context']['stream']
    assert stream['content_chars'] == 15 and stream['content_deltas'] == 1
    assert stream['request_id'] == 'chatcmpl-0123456789abcdef'
    assert stream['finish'] == 'missing' and stream['done_seen'] is False
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('stream-test')
    artifacts.update_status(folder, 'failed', **detail)
    assert artifacts.get_status('stream-test')['summary_failure_context']['stream'] == stream
    assert 'PRIVATE_CONTENT' not in json.dumps(detail)


@pytest.mark.parametrize("header,expected", [
    ("A1234567-89AB-4CDE-8FAB-1234567890AB", "a1234567-89ab-4cde-8fab-1234567890ab"),
    ("private-token", None),
    ("a1234567-89ab-4cde-8fab-1234567890ab\nsecret", None),
    ("chatcmpl-0123456789abcdef", None),
])
def test_http_request_id_is_separate_filtered_and_persisted(header, expected, tmp_path, isolated_preferences):
    from app.services.task_failure import failure_details
    from app.services.task_artifact_service import TaskArtifactService
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"id":"chatcmpl-0123456789abcdef","choices":[{"delta":{"content":"PRIVATE"}}]}\n\n'
            raise httpx.ReadError("SECRET")
    def handler(request):
        return httpx.Response(200, headers={"x-request-id": header}, stream=Interrupted())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
            patch("app.services.vilab_cloud_service.settings") as settings, \
            patch("app.services.vilab_cloud_service.httpx.stream", side_effect=direct_stream(client)):
        settings.vilab_server_url = "https://example.test"
        settings.content_cloud_runtime = False
        settings.cloud_auth_url = ""
        settings.vilab_api_key = "test-key"
        with pytest.raises(HTTPException) as caught:
            VILabCloudService().request("user", "POST", "/openai/v1/chat/completions", json={"stream": True})
    details = failure_details(caught.value)
    context = details["summary_failure_context"]
    assert context.get("http_request_id") == expected
    assert context["stream"]["request_id"] == "chatcmpl-0123456789abcdef"
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("http-id")
    artifacts.update_status(folder, "failed", **details)
    saved = artifacts.get_status("http-id")
    assert saved["summary_failure_context"] == context
    assert "PRIVATE" not in json.dumps(saved) and "SECRET" not in json.dumps(saved)
    if expected is None and header != "chatcmpl-0123456789abcdef":
        assert header not in json.dumps(saved)


def test_http_524_preserves_safe_http_request_id(isolated_preferences, tmp_path):
    from app.services.task_failure import failure_details
    from app.services.task_artifact_service import TaskArtifactService
    def handler(request):
        return httpx.Response(524, headers={"x-request-id": "a1234567-89ab-4cde-8fab-1234567890ab"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
            patch("app.services.vilab_cloud_service.settings") as settings, \
            patch("app.services.vilab_cloud_service.httpx.stream", side_effect=direct_stream(client)):
        settings.vilab_server_url = "https://example.test"
        settings.content_cloud_runtime = False
        settings.cloud_auth_url = ""
        settings.vilab_api_key = "test-key"
        with pytest.raises(HTTPException) as caught:
            VILabCloudService().request("user", "POST", "/openai/v1/chat/completions", json={"stream": True})
    details = failure_details(caught.value)
    assert details["summary_failure_context"]["http_request_id"] == "a1234567-89ab-4cde-8fab-1234567890ab"
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("http-524")
    artifacts.update_status(folder, "failed", **details)
    assert artifacts.get_status("http-524")["summary_failure_context"] == details["summary_failure_context"]

def test_timeout_stream_diagnostic_has_no_body_or_unsafe_id(monkeypatch):
    class Timed:
        def iter_lines(self):
            yield 'data: ' + json.dumps({'id': 'secret-token', 'choices': [{'delta': {'content': 'PRIVATE'}}]})
            yield ''
            yield ': heartbeat'
    times = iter([0, 0, 901, 901])
    monkeypatch.setattr('app.services.cloud_chat_stream.time.monotonic', lambda: next(times, 901))
    from app.services.summary_failure import SummaryResultUnconfirmed
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(Timed(), started=0)
    stream = caught.value.summary_failure_context['stream']
    assert stream['content_chars'] == 7 and stream['content_deltas'] == 1
    assert stream['elapsed_seconds'] >= 900 and stream['request_id'] is None
    assert 'PRIVATE' not in json.dumps(stream) and 'secret-token' not in json.dumps(stream)

def test_terminal_missing_done_diagnostic_includes_observed_progress():
    from app.services.summary_failure import SummaryResultUnconfirmed
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(response([delta('PRIVATE', 'stop')]), started=time.monotonic())
    stream = caught.value.summary_failure_context['stream']
    assert stream['content_chars'] == 7 and stream['content_deltas'] == 1
    assert stream['finish'] == 'stop' and stream['done_seen'] is False


@pytest.mark.parametrize("event,category", [
    ("not json PRIVATE", "invalid_event"),
    ({"error": {"message": "PRIVATE"}}, "provider_error"),
    ({"choices": "PRIVATE"}, "invalid_choices"),
    ({"choices": [{"delta": "PRIVATE"}]}, "invalid_delta"),
])
def test_invalid_event_persists_only_safe_progress(event, category, tmp_path):
    from app.services.summary_failure import SummaryResultUnconfirmed
    from app.services.task_failure import failure_details
    from app.services.task_artifact_service import TaskArtifactService
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        collect_chat_stream(response([delta("PRIVATE"), event]), started=time.monotonic())
    details = failure_details(caught.value)
    ctx = details["summary_failure_context"]
    assert ctx["diagnostic_protocol"] == "sse_stream/1" and ctx["category"] == category
    assert ctx["stream"]["content_chars"] == 7 and ctx["stream"]["content_deltas"] == 1
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("invalid-stream")
    artifacts.update_status(folder, "failed", **details)
    saved = artifacts.get_status("invalid-stream")
    assert saved["summary_failure_context"] == ctx
    assert "PRIVATE" not in json.dumps(saved)


@pytest.mark.parametrize("status,events", [(401, []), (403, []), (500, []), (200, [delta("partial")])])
def test_stream_http_and_completion_errors_are_not_transport_retried(status, events, isolated_preferences):
    seen = []

    def handler(request):
        seen.append(request)
        return response(events) if status == 200 else httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
            patch("app.services.vilab_cloud_service.settings") as settings, \
            patch("app.services.vilab_cloud_service.httpx.stream", side_effect=direct_stream(client)):
        settings.vilab_server_url = "https://example.test"
        settings.content_cloud_runtime = False
        settings.cloud_auth_url = ""
        settings.vilab_api_key = "test-key"
        with pytest.raises(HTTPException):
            VILabCloudService().request("user", "POST", "/openai/v1/chat/completions", json={"stream": True})
    assert len(seen) == 1
