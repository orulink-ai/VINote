import json
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.services.cloud_chat_stream import collect_chat_stream
from app.services.vilab_cloud_service import VILabCloudService


def response(events):
    return httpx.Response(200, text="".join(
        ": heartbeat\n\n" if event is None else "data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n"
        for event in events
    ))


def delta(text="", finish=None, **extra):
    return {"choices": [{"index": 0, "delta": {"content": text, **extra}, "finish_reason": finish}]}


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


def test_cloud_request_actually_uses_streaming_transport():
    seen = []
    def handler(request):
        seen.append(request)
        return response([delta("done", "stop"), "[DONE]"])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with patch("app.services.vilab_cloud_service.settings") as settings, patch("app.services.vilab_cloud_service.httpx.stream", side_effect=client.stream):
            settings.vilab_server_url = "https://example.test"
            settings.cloud_auth_url = ""
            settings.vilab_api_key = "test-key"
            result = VILabCloudService().request("user", "POST", "/openai/v1/chat/completions", json={"stream": True})
    assert result["choices"][0]["message"]["content"] == "done"
    assert seen[0].headers["authorization"] == "Bearer test-key"
